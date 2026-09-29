"""Cross-aggregate side-effect engine.

Everything that mutates more than one row lives here: the Unit rental ledger,
the survey-posture ladder, the five-hop staging-validation cascade, the six-hop
consult-cancellation compensation, assessment supersession and the RCA-close
reversal.
"""

import calc
from core import (
    MAX_LOAD_BY_CERT,
    RCA_DUE_HOURS,
    RECLEAN_BUFFER_HOURS,
    add_hours,
    bump,
    dt_of,
    insert,
    new_row,
    now,
    rows_of,
    store,
)

# ---------------------------------------------------------------------------
# Unit rental ledger
# ---------------------------------------------------------------------------
def recompute_available(unit):
    unit["rental_available_cents"] = (
        int(unit.get("rental_budget_cap_cents") or 0)
        - int(unit.get("rental_encumbered_cents") or 0)
        - int(unit.get("rental_committed_cents") or 0)
    )
    return unit["rental_available_cents"]


def encumber(unit, amount):
    unit["rental_encumbered_cents"] = int(unit.get("rental_encumbered_cents") or 0) + int(amount)
    recompute_available(unit)


def release(unit, amount):
    unit["rental_encumbered_cents"] = int(unit.get("rental_encumbered_cents") or 0) - int(amount)
    unit["rental_released_cents"] = int(unit.get("rental_released_cents") or 0) + int(amount)
    recompute_available(unit)


def commit(unit, authorized, actual):
    unit["rental_encumbered_cents"] = int(unit.get("rental_encumbered_cents") or 0) - int(authorized)
    unit["rental_committed_cents"] = int(unit.get("rental_committed_cents") or 0) + int(actual)
    unit["rental_released_cents"] = int(unit.get("rental_released_cents") or 0) \
        + max(0, int(authorized) - int(actual))
    recompute_available(unit)


# ---------------------------------------------------------------------------
# Survey posture ladder — FROZEN >= 4, RESTRICTED >= 2, else OPEN
# ---------------------------------------------------------------------------
def derive_posture(open_hapi_rca_count):
    count = int(open_hapi_rca_count or 0)
    if count >= 4:
        return "FROZEN"
    if count >= 2:
        return "RESTRICTED"
    return "OPEN"


def apply_posture(unit):
    """Recompute survey_posture in place; returns (previous, current)."""
    previous = unit.get("survey_posture")
    current = derive_posture(unit.get("open_hapi_rca_count"))
    unit["survey_posture"] = current
    return previous, current


def hold_requested_orders(unit_id):
    """Validate cascade HOP 5 — posture tightened to RESTRICTED/FROZEN."""
    stamp = now()
    for order in rows_of("support_surface_orders"):
        if order.get("unit_id") != unit_id:
            continue
        if order.get("fulfillment_status") != "REQUESTED":
            continue
        order["requires_director_override"] = True
        order["posture_hold_applied_at"] = stamp
        bump(order)


def lift_requested_order_holds(unit_id):
    """RCA-close compensation — posture returned all the way to OPEN."""
    for order in rows_of("support_surface_orders"):
        if order.get("unit_id") != unit_id:
            continue
        if order.get("fulfillment_status") != "REQUESTED":
            continue
        order["requires_director_override"] = False
        order["posture_hold_applied_at"] = None
        bump(order)


# ---------------------------------------------------------------------------
# WocNurse derived fields
# ---------------------------------------------------------------------------
def apply_max_load(nurse):
    nurse["max_consult_load"] = MAX_LOAD_BY_CERT.get(
        nurse.get("certification_status"), 0)


def recompute_eligibility(nurse):
    nurse["certification_eligibility_score"] = \
        calc.certification_eligibility_score(nurse, now())


def recompute_last_signoff(nurse):
    """Ordered by signed_off_at DESC then created_at DESC, so an older signoff
    filed later never overwrites a newer one."""
    from core import DB
    rows = [s for s in DB.competency_signoffs if s.get("nurse_id") == nurse["id"]]
    if not rows:
        nurse["last_competency_signoff_at"] = None
        return
    rows.sort(key=lambda s: (s.get("signed_off_at") or "",
                            s.get("created_at") or "",
                            s.get("_seq", 0)), reverse=True)
    nurse["last_competency_signoff_at"] = rows[0].get("signed_off_at")


# ---------------------------------------------------------------------------
# ConsultRequest acuity recompute
# ---------------------------------------------------------------------------
def apply_acuity(consult, patient, stage_source, variant, area=None):
    score = calc.acuity_score(
        stage_source,
        patient.get("comorbidity_count"),
        patient.get("device_related_risk"),
        consult.get("consult_type"),
        area,
    )
    band = calc.priority_band(score)
    consult["acuity_score"] = score
    consult["acuity_variant"] = variant
    consult["priority_band"] = band
    consult["sla_due_at"] = calc.sla_due_at(consult.get("triaged_at"), band)
    return score, band


# ---------------------------------------------------------------------------
# Support surface occupation
# ---------------------------------------------------------------------------
OCCUPYING_FULFILLMENT = ("APPROVED", "DELIVERED")


def surface_interval_free(surface_id, candidate_start, candidate_end,
                         exclude_order_id=None):
    """HALF-OPEN candidate [rental_start, rental_end) against each existing
    blocked span [e.rental_start, e.rental_end + RECLEAN_BUFFER_HOURS).
    Aggregate capacity is exactly 1."""
    for order in rows_of("support_surface_orders"):
        if order.get("support_surface_id") != surface_id:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order.get("fulfillment_status") not in OCCUPYING_FULFILLMENT:
            continue
        blocked_start = order.get("rental_start")
        blocked_end = add_hours(order.get("rental_end"), RECLEAN_BUFFER_HOURS)
        if blocked_start is None or blocked_end is None:
            continue
        if candidate_start < blocked_end and blocked_start < candidate_end:
            return False
    return True


def occupy_surface(surface, until_iso):
    surface["status"] = "IN_USE"
    surface["occupied_until"] = until_iso
    surface["available_from"] = add_hours(until_iso, RECLEAN_BUFFER_HOURS)
    bump(surface)


def clean_surface(surface, until_iso):
    surface["status"] = "CLEANING"
    surface["occupied_until"] = until_iso
    surface["available_from"] = add_hours(until_iso, RECLEAN_BUFFER_HOURS)
    bump(surface)


# ---------------------------------------------------------------------------
# PressureInjuryCase helpers
# ---------------------------------------------------------------------------
CASE_RECLASSIFIABLE = ("OPEN", "CLASSIFIED_POA", "CLASSIFIED_HAPI", "RCA_REQUIRED")
CASE_HAPI_COUNTED = ("CLASSIFIED_HAPI", "RCA_REQUIRED", "RCA_IN_PROGRESS", "RCA_COMPLETE")


def case_for_assessment(assessment_id):
    for case in rows_of("pressure_injury_cases"):
        if case.get("skin_assessment_id") == assessment_id:
            return case
    return None


def create_case(assessment, patient, predecessor_case_id=None):
    case = new_row(
        "pic",
        patient_id=assessment.get("patient_id"),
        unit_id=patient.get("unit_id"),
        skin_assessment_id=assessment["id"],
        predecessor_case_id=predecessor_case_id,
        classification="UNDETERMINED",
        status="OPEN",
        rca_lead_nurse_id=None,
        rca_due_at=None,
        root_cause_category=None,
        contributing_factors=[],
        closed_at=None,
    )
    return insert("pressure_injury_cases", case)


# ---------------------------------------------------------------------------
# The five-hop staging-validation cascade.
#
#   HOP 1  assessment -> VALIDATED (+ Patient.poa_skin_assessment_documented)
#   HOP 1b consult acuity recomputed from confirmed_stage
#   HOP 2  case -> CLASSIFIED_POA / CLASSIFIED_HAPI (OPEN when INDETERMINATE)
#   HOP 3  CLASSIFIED_HAPI -> RCA_REQUIRED, rca_due_at set
#   HOP 4  Unit.open_hapi_rca_count + 1, survey_posture re-derived
#   HOP 5  posture tightened -> director-override hold on REQUESTED orders
# ---------------------------------------------------------------------------
def validate_cascade(assessment, patient, consult, confirmed_stage,
                     confirmed, validator_user_id):
    stamp = now()

    # HOP 1
    determination = calc.poa_determination(
        rows_of("skin_assessments"), assessment, patient, confirmed)
    assessment["validation_status"] = "VALIDATED"
    assessment["confirmed_stage"] = confirmed_stage
    assessment["validated_by_user_id"] = validator_user_id
    assessment["poa_determination"] = determination
    bump(assessment)

    if determination == "POA" and not patient.get("poa_skin_assessment_documented"):
        patient["poa_skin_assessment_documented"] = True
        bump(patient)
    elif determination == "POA":
        patient["poa_skin_assessment_documented"] = True
        bump(patient)

    # HOP 1b — recompute from confirmed_stage, never observed_stage.
    if consult is not None:
        apply_acuity(consult, patient, confirmed_stage, calc.VARIANT_ASSESSED,
                     assessment.get("measured_area_cm2"))
        bump(consult)

    # HOP 2
    case = case_for_assessment(assessment["id"])
    if case is not None and determination in ("POA", "HAPI") \
            and case.get("status") == "OPEN":
        case["classification"] = determination
        case["status"] = "CLASSIFIED_POA" if determination == "POA" \
            else "CLASSIFIED_HAPI"
        bump(case)

        if determination == "HAPI":
            # HOP 3
            case["status"] = "RCA_REQUIRED"
            case["rca_due_at"] = add_hours(stamp, RCA_DUE_HOURS)
            bump(case)

            # HOP 4
            unit = store("units").get(case.get("unit_id"))
            if unit is not None:
                unit["open_hapi_rca_count"] = int(unit.get("open_hapi_rca_count") or 0) + 1
                previous, current = apply_posture(unit)
                bump(unit)
                # HOP 5 — only when the posture actually tightened.
                if current != previous and current in ("RESTRICTED", "FROZEN"):
                    hold_requested_orders(unit["id"])

    return determination


# ---------------------------------------------------------------------------
# Assessment supersession, triggered by filing a newer assessment for the same
# (patient_id, anatomic_location) pair.
#
# Returns the id of the case that was reclassified, if any, so the caller can
# stamp it as the successor case's predecessor_case_id.
# ---------------------------------------------------------------------------
SUPERSEDABLE = ("PENDING_VALIDATION", "VALIDATED")


def supersede_prior_assessments(new_assessment, patient):
    predecessor_case_id = None
    priors = [
        a for a in rows_of("skin_assessments")
        if a["id"] != new_assessment["id"]
        and a.get("patient_id") == new_assessment.get("patient_id")
        and a.get("anatomic_location") == new_assessment.get("anatomic_location")
        and a.get("validation_status") in SUPERSEDABLE
    ]
    priors.sort(key=lambda a: (a.get("created_at") or "", a.get("_seq", 0)))
    for prior in priors:
        was_validated = prior.get("validation_status") == "VALIDATED"
        prior["validation_status"] = "SUPERSEDED"
        bump(prior)
        if not was_validated:
            continue
        case = case_for_assessment(prior["id"])
        if case is None or case.get("status") not in CASE_RECLASSIFIABLE:
            continue
        previous_status = case.get("status")
        case["status"] = "RECLASSIFIED"
        bump(case)
        predecessor_case_id = case["id"]
        if previous_status in ("CLASSIFIED_HAPI", "RCA_REQUIRED"):
            unit = store("units").get(case.get("unit_id"))
            if unit is not None:
                unit["open_hapi_rca_count"] = max(
                    0, int(unit.get("open_hapi_rca_count") or 0) - 1)
                apply_posture(unit)
                bump(unit)
    return predecessor_case_id


# ---------------------------------------------------------------------------
# RCA-close compensation — reverses validate-cascade hops 4 and 5 exactly.
# ---------------------------------------------------------------------------
def close_hapi_case(case):
    case["closed_at"] = now()
    case["status"] = "CLOSED"
    bump(case)
    unit = store("units").get(case.get("unit_id"))
    if unit is None:
        return
    unit["open_hapi_rca_count"] = max(0, int(unit.get("open_hapi_rca_count") or 0) - 1)
    previous, current = apply_posture(unit)
    bump(unit)
    if current == "OPEN" and previous != "OPEN":
        lift_requested_order_holds(unit["id"])


# ---------------------------------------------------------------------------
# Consult cancellation compensation.  Hop order is pinned: 1, 2, 3, 2b, 2c, 3b.
#
#   HOP 1  consult -> CANCELLED, assigned nurse load - 1
#   HOP 2  ENCUMBERED orders -> RELEASED (+ REQUESTED -> DENIED)
#   HOP 3  per released order: unit ledger release
#   HOP 2b ACTIVE dressing protocols -> VOIDED
#   HOP 2c live ostomy plans -> CLOSED_INCOMPLETE, followup cleared
#   HOP 3b plans that left FOLLOWUP_SCHEDULED: patient counter - 1
# ---------------------------------------------------------------------------
PLAN_LIVE_STATUSES = ("ACTIVE", "TEACH_BACK_PASSED", "SUPPLIES_TRANSITIONED",
                      "FOLLOWUP_SCHEDULED")


def cancel_cascade(consult):
    # HOP 1
    consult["status"] = "CANCELLED"
    nurse_id = consult.get("assigned_nurse_id")
    if nurse_id:
        nurse = store("woc_nurses").get(nurse_id)
        if nurse is not None:
            nurse["active_consult_load"] = max(
                0, int(nurse.get("active_consult_load") or 0) - 1)
            bump(nurse)

    # HOP 2
    released = []
    orders = [o for o in rows_of("support_surface_orders")
              if o.get("consult_request_id") == consult["id"]]
    orders.sort(key=lambda o: (o.get("created_at") or "", o.get("_seq", 0)))
    for order in orders:
        touched = False
        if order.get("billing_status") == "ENCUMBERED":
            order["billing_status"] = "RELEASED"
            released.append(order)
            touched = True
        if order.get("fulfillment_status") == "REQUESTED":
            order["fulfillment_status"] = "DENIED"
            order["denial_reason"] = "CONSULT_CANCELLED"
            touched = True
        if touched:
            bump(order)

    # HOP 3
    for order in released:
        unit = store("units").get(order.get("unit_id"))
        if unit is None:
            continue
        release(unit, int(order.get("authorized_cost_cents") or 0))
        bump(unit)

    # HOP 2b
    protocols = [p for p in rows_of("dressing_protocols")
                 if p.get("consult_request_id") == consult["id"]
                 and p.get("status") == "ACTIVE"]
    protocols.sort(key=lambda p: (p.get("created_at") or "", p.get("_seq", 0)))
    for protocol in protocols:
        protocol["status"] = "VOIDED"
        bump(protocol)

    # HOP 2c
    plans = [p for p in rows_of("ostomy_education_plans")
             if p.get("consult_request_id") == consult["id"]
             and p.get("status") in PLAN_LIVE_STATUSES]
    plans.sort(key=lambda p: (p.get("created_at") or "", p.get("_seq", 0)))
    left_followup = []
    for plan in plans:
        if plan.get("status") == "FOLLOWUP_SCHEDULED":
            left_followup.append(plan)
        plan["status"] = "CLOSED_INCOMPLETE"
        plan["followup_appointment_at"] = None
        bump(plan)

    # HOP 3b — only for plans that actually left FOLLOWUP_SCHEDULED.
    for plan in left_followup:
        patient = store("patients").get(plan.get("patient_id"))
        if patient is None:
            continue
        patient["pending_outpatient_followup_count"] = max(
            0, int(patient.get("pending_outpatient_followup_count") or 0) - 1)
        bump(patient)

    bump(consult)
    return consult


# ---------------------------------------------------------------------------
# Survey window contention — CLOSED intervals, no buffer.
# ---------------------------------------------------------------------------
def windows_collide(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def survey_window_conflict(candidate):
    """PREVALENCE capacity 1 against {OPEN, LOCKED, PUBLISHED};
    INCIDENCE capacity MAX_CONCURRENT_INCIDENCE_ROUNDS against {OPEN, LOCKED}."""
    from core import MAX_CONCURRENT_INCIDENCE_ROUNDS

    round_type = candidate.get("round_type")
    if round_type == "PREVALENCE":
        live = ("OPEN", "LOCKED", "PUBLISHED")
        capacity = 1
    else:
        live = ("OPEN", "LOCKED")
        capacity = MAX_CONCURRENT_INCIDENCE_ROUNDS

    candidate_units = set(candidate.get("participating_unit_ids") or [])
    per_unit = {}
    for other in rows_of("survey_rounds"):
        if other["id"] == candidate["id"]:
            continue
        if other.get("round_type") != round_type:
            continue
        if other.get("status") not in live:
            continue
        if not windows_collide(candidate.get("window_start"),
                               candidate.get("window_end"),
                               other.get("window_start"),
                               other.get("window_end")):
            continue
        shared = candidate_units & set(other.get("participating_unit_ids") or [])
        for unit_id in shared:
            per_unit[unit_id] = per_unit.get(unit_id, 0) + 1
    for count in per_unit.values():
        if count >= capacity:
            return True
    return False


def observations_for(round_id, unit_id=None):
    rows = [o for o in rows_of("survey_observations")
            if o.get("survey_round_id") == round_id
            and (unit_id is None or o.get("unit_id") == unit_id)]
    rows.sort(key=lambda o: (o.get("created_at") or "", o.get("_seq", 0)))
    return rows
