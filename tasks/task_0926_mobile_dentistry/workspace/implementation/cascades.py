"""Multi-link cascades (PRD 3.1, 3.2, 3.3, 3.8)."""

import calc
import clock
import store
from validation import touch


# --------------------------------------------------------------------------
# Encounter charge recompute (used by the void path and by spore link three)
# --------------------------------------------------------------------------
def recompute_encounter_charges(encounter):
    """Recompute the charge fields from the surviving PERFORMED procedures and
    revert a PRICED billing axis to UNBILLED."""
    subtotal, surcharge, total = calc.charge_projection(encounter["id"])
    encounter["subtotal_cents"] = subtotal
    encounter["supply_surcharge_cents"] = surcharge
    encounter["total_charge_cents"] = total
    if encounter["billing_status"] == "PRICED":
        encounter["billing_status"] = "UNBILLED"
        encounter["allowed_amount_cents"] = 0
        encounter["patient_responsibility_cents"] = 0
        encounter["plan_paid_cents"] = 0
        encounter["write_off_cents"] = 0
        encounter["pricing_regime"] = None


def refresh_patient_varnish_for_procedure(procedure):
    encounter = store.get("encounters", procedure["encounter_id"])
    if encounter is None:
        return
    visit = store.get("site_visits", encounter["site_visit_id"])
    if visit is None:
        return
    calc.recompute_varnish(encounter["patient_id"], visit["program_period_id"])


# --------------------------------------------------------------------------
# The five-link spore cascade (PRD 3.3)
# --------------------------------------------------------------------------
def run_failed_spore_cascade(load, unit, recorded_by_staff_id=None, auto_failed=False):
    now = clock.now()

    # Link one -- the failing load itself.
    load["spore_result"] = "FAILED"
    load["result_recorded_at"] = now
    load["auto_failed"] = bool(auto_failed)
    load["result_recorded_by_staff_id"] = None if auto_failed else recorded_by_staff_id
    touch(load)

    # Link two -- the tainted load set and the procedures it reaches.
    tainted_loads = calc.spore_taint_loads(load, unit)
    tainted_load_ids = {l["id"] for l in tainted_loads}
    tainted_procedures = []
    for procedure in store.all_rows("procedures"):
        if procedure["status"] != "PERFORMED":
            continue
        if procedure.get("sterilization_load_id") not in tainted_load_ids:
            continue
        procedure["status"] = "TAINTED"
        procedure["taint_reason"] = "SPORE_TEST_FAILED"
        touch(procedure)
        tainted_procedures.append(procedure)
    load["tainted_procedure_count"] = len(tainted_procedures)

    # Chair-minute and varnish ledgers are re-established by full
    # recomputation over the surviving rows, without version bumps.
    for procedure in tainted_procedures:
        if procedure["procedure_code"] == "D1206":
            refresh_patient_varnish_for_procedure(procedure)

    # Link three -- every encounter that gained a newly tainted procedure.
    encounter_ids = []
    for procedure in tainted_procedures:
        if procedure["encounter_id"] not in encounter_ids:
            encounter_ids.append(procedure["encounter_id"])
    touched_encounters = []
    for encounter_id in encounter_ids:
        encounter = store.get("encounters", encounter_id)
        if encounter is None:
            continue
        recompute_encounter_charges(encounter)
        touch(encounter)
        touched_encounters.append(encounter)

    # Link four -- ACTIVE treatment plans on those encounters.
    superseded_plans = []
    for encounter in touched_encounters:
        for plan in store.all_rows("treatment_plans"):
            if plan["encounter_id"] != encounter["id"]:
                continue
            if plan["plan_status"] != "ACTIVE":
                continue
            plan["plan_status"] = "SUPERSEDED"
            plan["superseded_reason"] = "SPORE_TEST_FAILED"
            plan["follow_up_due_date"] = None
            touch(plan)
            superseded_plans.append(plan)

    # Link five -- OPEN or SENT referrals on those plans.
    for plan in superseded_plans:
        for referral in store.all_rows("referrals"):
            if referral["treatment_plan_id"] != plan["id"]:
                continue
            if referral["status"] not in ("OPEN", "SENT"):
                continue
            referral["status"] = "ABANDONED"
            referral["abandoned_at"] = now
            referral["case_management_opened_at"] = now
            referral["abandon_reason"] = "PLAN_SUPERSEDED"
            touch(referral)

    # Finally the unit itself is quarantined.
    unit["status"] = "QUARANTINED"
    unit["quarantined_at"] = now
    touch(unit)


def maybe_sweep_incubation_timeout(unit):
    """Sweep 1 (rung 15): fail the unit's most recent still-incubating load."""
    latest = calc.latest_load_for_unit(unit["id"])
    if latest is None:
        return False
    if latest["spore_result"] != "PENDING":
        return False
    if clock.now() < latest["incubation_ends_at"]:
        return False
    run_failed_spore_cascade(latest, unit, recorded_by_staff_id=None, auto_failed=True)
    return True


# --------------------------------------------------------------------------
# The consent tier-downgrade cascade (PRD 3.2)
# --------------------------------------------------------------------------
def run_consent_downgrade_cascade(old_consent, new_rank):
    from constants import CONSENT_TIER_RANK

    # Link two -- over-tier PLANNED procedures under encounters citing the
    # superseded consent.
    affected_encounters = []
    invalidated = 0
    for encounter in store.all_rows("encounters"):
        if encounter["consent_id"] != old_consent["id"]:
            continue
        touched_here = False
        for procedure in calc.encounter_procedures(encounter["id"]):
            if procedure["status"] != "PLANNED":
                continue
            if CONSENT_TIER_RANK[procedure["required_tier"]] <= new_rank:
                continue
            procedure["status"] = "INELIGIBLE"
            procedure["void_reason"] = "CONSENT_TIER_DOWNGRADE"
            touch(procedure)
            invalidated += 1
            touched_here = True
        if touched_here:
            affected_encounters.append(encounter)
    old_consent["invalidated_procedure_count"] = invalidated

    # Link three -- released chair minutes are re-established by full
    # recomputation; encounters stripped bare are deferred and their active
    # plans cancelled.
    for encounter in affected_encounters:
        live = [
            p for p in calc.encounter_procedures(encounter["id"])
            if p["status"] in ("PLANNED", "PERFORMED") and not p.get("_auto_created")
        ]
        if live:
            continue
        if encounter["clinical_status"] not in ("EXAMINED", "TREATED"):
            continue
        encounter["clinical_status"] = "DEFERRED"
        encounter["deferred_reason"] = "CONSENT_TIER_DOWNGRADE"
        touch(encounter)
        for plan in store.all_rows("treatment_plans"):
            if plan["encounter_id"] != encounter["id"]:
                continue
            if plan["plan_status"] != "ACTIVE":
                continue
            plan["plan_status"] = "CANCELLED"
            plan["superseded_reason"] = "CONSENT_TIER_DOWNGRADE"
            plan["follow_up_due_date"] = None
            touch(plan)
    return invalidated


# --------------------------------------------------------------------------
# The consent revocation cascade (PRD 3.2)
# --------------------------------------------------------------------------
def run_consent_revocation_cascade(consent):
    for encounter in store.all_rows("encounters"):
        if encounter["consent_id"] != consent["id"]:
            continue
        for procedure in calc.encounter_procedures(encounter["id"]):
            if procedure["status"] != "PLANNED":
                continue
            procedure["status"] = "INELIGIBLE"
            procedure["void_reason"] = "CONSENT_TIER_DOWNGRADE"
            touch(procedure)


# --------------------------------------------------------------------------
# The site-hold cascade (PRD 3.1)
# --------------------------------------------------------------------------
def run_site_hold_cascade(hold, site):
    from gates import intersects

    site["status"] = "SUSPENDED"
    touch(site)

    blocked = 0
    for visit in store.all_rows("site_visits"):
        if visit["site_id"] != site["id"]:
            continue
        if visit["status"] != "SCHEDULED":
            continue
        if not intersects(
            visit["scheduled_start_at"], visit["scheduled_end_at"],
            hold["starts_at"], hold["ends_at"],
        ):
            continue
        visit["status"] = "HOLD_BLOCKED"
        touch(visit)
        blocked += 1
        for encounter in calc.visit_encounters(visit["id"]):
            if encounter["clinical_status"] not in ("REGISTERED", "SCREENED"):
                continue
            encounter["clinical_status"] = "DEFERRED"
            encounter["deferred_reason"] = "SITE_HOLD"
            touch(encounter)
    hold["blocked_visit_count"] = blocked


def run_site_hold_release_cascade(hold, site):
    from gates import active_holds_for_site, intersects

    remaining = active_holds_for_site(site["id"])
    if not remaining:
        site["status"] = "ACTIVE"
    touch(site)

    for visit in store.all_rows("site_visits"):
        if visit["site_id"] != site["id"]:
            continue
        if visit["status"] != "HOLD_BLOCKED":
            continue
        still_blocked = any(
            intersects(
                visit["scheduled_start_at"], visit["scheduled_end_at"],
                other["starts_at"], other["ends_at"],
            )
            for other in remaining
        )
        if still_blocked:
            continue
        visit["status"] = "SCHEDULED"
        touch(visit)


# --------------------------------------------------------------------------
# The report-submission cascade (PRD 3.8)
# --------------------------------------------------------------------------
def run_report_submission_cascade(period):
    now = clock.now()
    period["status"] = "SUBMITTED"
    period["frozen_at"] = now
    touch(period)

    for visit in store.all_rows("site_visits"):
        if visit["program_period_id"] != period["id"]:
            continue
        if visit["status"] != "SCHEDULED":
            continue
        visit["status"] = "CANCELLED"
        visit["cancelled_at"] = now
        touch(visit)
        for encounter in calc.visit_encounters(visit["id"]):
            if encounter["clinical_status"] != "REGISTERED":
                continue
            encounter["clinical_status"] = "NO_SHOW"
            touch(encounter)
