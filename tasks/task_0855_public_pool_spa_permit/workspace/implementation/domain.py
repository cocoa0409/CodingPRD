"""Derived fields, calculations and cross-entity cascades."""

import math
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from clock import LOGICAL_CLOCK, add_days, add_minutes, parse_date
from store import DB, base_record, ordered, touch

VGB_ENFORCEMENT_DATE = parse_date(C.VGB_ENFORCEMENT_START_DATE)


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal/number half up to the nearest whole unit (int)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


# --------------------------------------------------------------------------
# facility classification derivation
# --------------------------------------------------------------------------

def water_type_of(facility):
    return "SPA" if facility["facility_class"] == "SPA" else "POOL"


def max_bather_load_of(facility):
    divisor = (C.BATHER_LOAD_SQFT_PER_BATHER_SPA
               if water_type_of(facility) == "SPA"
               else C.BATHER_LOAD_SQFT_PER_BATHER_POOL)
    return int(math.floor(float(facility["surface_area_sqft"]) / divisor))


def lifeguard_required_of(facility):
    return (facility["facility_class"] in ("CLASS_A_COMPETITION", "CLASS_B_PUBLIC")
            and max_bather_load_of(facility) >= C.LIFEGUARD_REQUIRED_BATHER_LOAD_THRESHOLD)


def required_signage_types_of(facility):
    base = (C.REQUIRED_SIGNAGE_TYPES_SPA
            if water_type_of(facility) == "SPA"
            else C.REQUIRED_SIGNAGE_TYPES_POOL)
    types = list(base)
    if not lifeguard_required_of(facility):
        types.append(C.SIGNAGE_TYPE_WHEN_NO_LIFEGUARD)
    return types


# --------------------------------------------------------------------------
# compliance artifacts / VGB drain safety
# --------------------------------------------------------------------------

def artifacts_of(facility_id):
    return ordered([a for a in DB.compliance_artifacts.values()
                    if a["facility_id"] == facility_id])


def artifact_key(artifact):
    return (artifact["facility_id"], artifact["artifact_type"], artifact["signage_type"])


def artifact_status(artifact):
    key = artifact_key(artifact)
    mine = (artifact["created_at"], artifact["_seq"])
    for other in DB.compliance_artifacts.values():
        if other["id"] == artifact["id"]:
            continue
        if artifact_key(other) != key:
            continue
        if (other["created_at"], other["_seq"]) > mine:
            return "SUPERSEDED"
    if LOGICAL_CLOCK.today() > artifact["expires_on"]:
        return "EXPIRED"
    return "ACTIVE"


def vgb_compliance_status(facility):
    certs = [a for a in DB.compliance_artifacts.values()
             if a["facility_id"] == facility["id"]
             and a["artifact_type"] == "DRAIN_CERTIFICATION"]
    if not certs:
        return "NONCOMPLIANT"
    governing = sorted(certs, key=lambda a: (a["effective_on"], a["created_at"],
                                             a["_seq"]))[-1]
    if LOGICAL_CLOCK.today() > governing["expires_on"]:
        return "EXPIRED"
    if (facility["drain_count"] < C.VGB_SINGLE_DRAIN_MIN_COUNT
            and governing["sva_system_type"] == "NONE"):
        return "NONCOMPLIANT"
    return "COMPLIANT"


# --------------------------------------------------------------------------
# violations / demerits
# --------------------------------------------------------------------------

def violations_of_inspection(inspection_id):
    return ordered([v for v in DB.violations.values()
                    if v["inspection_id"] == inspection_id])


def qualifying_open_violations(facility_id, severities):
    """OPEN violations of the given severities hanging off a FINALIZED inspection."""
    out = []
    for v in DB.violations.values():
        if v["status"] != "OPEN" or v["severity"] not in severities:
            continue
        insp = DB.inspections.get(v["inspection_id"])
        if not insp or insp["facility_id"] != facility_id:
            continue
        if insp["workflow_status"] != "FINALIZED":
            continue
        out.append(v)
    return out


def open_demerit_points(facility_id):
    total = 0
    for v in DB.violations.values():
        if v["status"] != "OPEN":
            continue
        insp = DB.inspections.get(v["inspection_id"])
        if not insp or insp["facility_id"] != facility_id:
            continue
        if insp["workflow_status"] != "FINALIZED":
            continue
        total += v["points_assessed"]
    return total


# --------------------------------------------------------------------------
# permits attached to a facility
# --------------------------------------------------------------------------

def permits_of(facility_id):
    return ordered([p for p in DB.permits.values() if p["facility_id"] == facility_id])


def active_permit_id(facility_id):
    issued = [p for p in DB.permits.values()
              if p["facility_id"] == facility_id and p["status"] == "ISSUED"]
    if not issued:
        return None
    issued.sort(key=lambda p: (p["term_start_date"], p["created_at"], p["_seq"]))
    return issued[-1]["id"]


def issued_permit(facility_id):
    pid = active_permit_id(facility_id)
    return DB.permits.get(pid) if pid else None


# --------------------------------------------------------------------------
# the nine-clause operating posture gate (PRD 2.9)
# --------------------------------------------------------------------------

def operating_posture(facility):
    fid = facility["id"]
    clock_date = LOGICAL_CLOCK.today()
    clock_now = LOGICAL_CLOCK.now()

    # 1
    for order in DB.closure_orders.values():
        if order["facility_id"] == fid and order["status"] in ("OPEN", "REOPEN_REQUESTED"):
            return "CLOSED", "CLOSURE_ORDER_OPEN"
    # 2
    facility_permits = [p for p in DB.permits.values() if p["facility_id"] == fid]
    if len(facility_permits) == 0:
        return "CLOSED", "PERMIT_MISSING"
    # 3
    if not any(p["status"] == "ISSUED" for p in facility_permits):
        return "CLOSED", "PERMIT_NOT_ACTIVE"
    # 4
    if facility["is_seasonal"]:
        start = facility["season_start_date"]
        end = facility["season_end_date"]
        if not (start is not None and end is not None and start <= clock_date <= end):
            return "CLOSED", "OUT_OF_SEASON"
    # 5
    if clock_date >= VGB_ENFORCEMENT_DATE and vgb_compliance_status(facility) != "COMPLIANT":
        return "RESTRICTED", "VGB_NONCOMPLIANT"
    # 6
    if qualifying_open_violations(fid, ("CRITICAL", "IMMINENT_HEALTH_HAZARD")):
        return "RESTRICTED", "CRITICAL_VIOLATION_OPEN"
    # 7
    active_signs = set()
    for a in DB.compliance_artifacts.values():
        if a["facility_id"] != fid or a["artifact_type"] != "SIGNAGE":
            continue
        if artifact_status(a) == "ACTIVE":
            active_signs.add(a["signage_type"])
    for required in required_signage_types_of(facility):
        if required not in active_signs:
            return "RESTRICTED", "SIGNAGE_INCOMPLETE"
    # 8
    if lifeguard_required_of(facility):
        covered = False
        for sa in DB.staff_assignments.values():
            if sa["facility_id"] != fid or sa["status"] != "SCHEDULED":
                continue
            if sa["role_type"] != "LIFEGUARD":
                continue
            if sa["shift_start_at"] <= clock_now < sa["shift_end_at"]:
                covered = True
                break
        if not covered:
            return "RESTRICTED", "LIFEGUARD_COVERAGE_MISSING"
    # 9
    return "OPEN", "NONE"


def bump_facility(facility):
    """Posture recomputation trace: every cascade bumps the facility version."""
    touch(facility)
    return facility


# --------------------------------------------------------------------------
# fee ledger
# --------------------------------------------------------------------------

def post_ledger_entry(operator_id, entry_type, amount_cents, permit_id=None,
                      reference_note=None):
    entry = base_record(versioned=False)
    entry.update({
        "operator_id": operator_id,
        "permit_id": permit_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "posted_at": LOGICAL_CLOCK.now(),
        "reference_note": reference_note,
    })
    DB.ledger_entries[entry["id"]] = entry
    return entry


def fee_balance_cents(operator_id):
    return sum(e["amount_cents"] for e in DB.ledger_entries.values()
               if e["operator_id"] == operator_id)


# --------------------------------------------------------------------------
# permit fee assessment (PRD 3.3)
# --------------------------------------------------------------------------

def assess_permit_fee(permit, facility):
    base_cents = C.PERMIT_BASE_FEE_CENTS[facility["facility_class"]]

    billable_gallons = max(0, facility["water_volume_gallons"]
                           - C.VOLUME_SURCHARGE_FREE_GALLONS)
    volume_units = ceil_div(billable_gallons, 10000)
    volume_cents = volume_units * C.VOLUME_SURCHARGE_CENTS_PER_10K_GALLONS

    feature_cents = sum(C.FEATURE_SURCHARGE_CENTS[f] for f in facility["features"])

    if permit["permit_type"] == "ANNUAL":
        fee_variant = "FULL_TERM"
        subtotal_cents = base_cents + volume_cents + feature_cents
    else:
        fee_variant = "SEASONAL_PRORATED"
        term_days = Decimal(permit["term_days"])
        denom = Decimal(C.SEASONAL_TERM_DENOMINATOR_DAYS)
        prorated_base = round_half_up(Decimal(base_cents) * term_days / denom)
        prorated_volume = round_half_up(Decimal(volume_cents) * term_days / denom)
        subtotal_cents = prorated_base + prorated_volume + feature_cents

    if permit["is_late_application"]:
        penalty_cents = round_half_up(
            Decimal(subtotal_cents) * Decimal(C.LATE_APPLICATION_PENALTY_PCT))
    else:
        penalty_cents = 0

    return fee_variant, subtotal_cents, penalty_cents


# --------------------------------------------------------------------------
# inspection scoring (PRD 3.5)
# --------------------------------------------------------------------------

def violation_points(severity, corrected_on_site):
    base = C.SEVERITY_POINTS[severity]
    if corrected_on_site and severity != "IMMINENT_HEALTH_HAZARD":
        return round_half_up(Decimal(base) * Decimal(C.CORRECTED_ON_SITE_CREDIT_FACTOR))
    return base


def score_inspection(inspection):
    rows = [v for v in violations_of_inspection(inspection["id"])
            if v["status"] != "VOIDED"]
    raw_critical = sum(v["points_assessed"] for v in rows
                       if v["severity"] in ("IMMINENT_HEALTH_HAZARD", "CRITICAL"))
    raw_noncritical = sum(v["points_assessed"] for v in rows
                          if v["severity"] == "NONCRITICAL")
    critical_demerits = min(raw_critical, C.CRITICAL_DEMERIT_CAP)
    noncritical_demerits = min(raw_noncritical, C.NONCRITICAL_DEMERIT_CAP)
    score = max(0, C.INSPECTION_SCORE_MAX - critical_demerits - noncritical_demerits)

    has_imminent = any(v["severity"] == "IMMINENT_HEALTH_HAZARD" for v in rows)
    has_uncorrected_critical = any(v["severity"] == "CRITICAL"
                                   and v["corrected_on_site"] is False
                                   for v in rows)
    if has_imminent or score < C.SCORE_FAIL_THRESHOLD:
        result = "FAIL"
    elif score < C.SCORE_PASS_THRESHOLD or has_uncorrected_critical:
        result = "CONDITIONAL"
    else:
        result = "PASS"
    return critical_demerits, noncritical_demerits, score, result


# --------------------------------------------------------------------------
# water chemistry classification (PRD 3.7)
# --------------------------------------------------------------------------

def classify_reading(facility, free_chlorine_ppm, combined_chloramine_ppm, ph,
                     cyanuric_acid_ppm, water_temp_f):
    is_spa = water_type_of(facility) == "SPA"
    cl_min = C.FREE_CHLORINE_MIN_PPM_SPA if is_spa else C.FREE_CHLORINE_MIN_PPM_POOL
    cl_imminent = (C.FREE_CHLORINE_IMMINENT_PPM_SPA if is_spa
                   else C.FREE_CHLORINE_IMMINENT_PPM_POOL)
    temp_max = C.WATER_TEMP_MAX_F_SPA if is_spa else C.WATER_TEMP_MAX_F_POOL

    breaches = []
    if free_chlorine_ppm < cl_min:
        breaches.append("FREE_CHLORINE_LOW")
    if free_chlorine_ppm > C.FREE_CHLORINE_MAX_PPM:
        breaches.append("FREE_CHLORINE_HIGH")
    if combined_chloramine_ppm > C.COMBINED_CHLORAMINE_MAX_PPM:
        breaches.append("COMBINED_CHLORAMINE_HIGH")
    if ph < C.PH_MIN:
        breaches.append("PH_LOW")
    if ph > C.PH_MAX:
        breaches.append("PH_HIGH")
    if cyanuric_acid_ppm > C.CYANURIC_ACID_MAX_PPM:
        breaches.append("CYANURIC_ACID_HIGH")
    if water_temp_f > temp_max:
        breaches.append("TEMP_HIGH")

    imminent = (free_chlorine_ppm < cl_imminent
                or ph < C.PH_IMMINENT_LOW
                or ph > C.PH_IMMINENT_HIGH)
    if imminent:
        status = "IMMINENT_HAZARD"
    elif breaches:
        status = "OUT_OF_RANGE"
    else:
        status = "IN_RANGE"
    return status, breaches


# --------------------------------------------------------------------------
# reopen remediation window (PRD 3.7)
# --------------------------------------------------------------------------

def compute_remediation_window(order):
    reason = order["closure_reason"]
    chlorine = order.get("treatment_free_chlorine_ppm")
    ph = order.get("treatment_ph")
    ct_eligible = reason in C.CT_ELIGIBLE_REASONS
    supplied = chlorine is not None and chlorine > 0 and ph is not None

    if ct_eligible and supplied:
        variant = "CT_COMPUTED"
        target = Decimal(C.CT_TARGET_PPM_MINUTES)
        if ph > C.CT_PH_THRESHOLD:
            target = target * Decimal(C.CT_PH_HIGH_MULTIPLIER)
        quotient = target / Decimal(str(chlorine))
        minutes = int(math.ceil(quotient))
        required = max(C.MIN_REMEDIATION_MINUTES, minutes)
    else:
        variant = "FIXED_TABLE"
        required = C.REMEDIATION_MINUTES_TABLE[reason]

    order["remediation_variant"] = variant
    order["required_remediation_minutes"] = required
    order["earliest_reopen_at"] = add_minutes(order["ordered_at"], required)
    return order


# --------------------------------------------------------------------------
# closure order creation + its cascades (shared by manual and automatic paths)
# --------------------------------------------------------------------------

def create_closure_order(facility, closure_reason, ordered_by_user_id,
                         ordered_by_role, note=None, triggering_reading_id=None):
    order = base_record()
    order.update({
        "facility_id": facility["id"],
        "triggering_reading_id": triggering_reading_id,
        "closure_reason": closure_reason,
        "note": note,
        "ordered_by_user_id": ordered_by_user_id,
        "ordered_by_role": ordered_by_role,
        "ordered_at": LOGICAL_CLOCK.now(),
        "status": "OPEN",
        "treatment_free_chlorine_ppm": None,
        "treatment_ph": None,
        "verification_reading_id": None,
        "reopen_requested_at": None,
        "reopen_decided_at": None,
        "reopen_decided_by_user_id": None,
        "reopen_denial_reason": None,
        "denial_count": 0,
        "cleared_at": None,
    })
    compute_remediation_window(order)
    DB.closure_orders[order["id"]] = order

    # cascade: the facility posture recomputation always bumps the version
    bump_facility(facility)

    # cascade: cancel scheduled shifts that overlap the closure window
    now = LOGICAL_CLOCK.now()
    for sa in ordered(list(DB.staff_assignments.values())):
        if sa["facility_id"] != facility["id"] or sa["status"] != "SCHEDULED":
            continue
        if (sa["shift_start_at"] < order["earliest_reopen_at"]
                and sa["shift_end_at"] > order["ordered_at"]):
            sa["status"] = "CANCELLED"
            sa["cancel_reason"] = "FACILITY_CLOSED"
            sa["cancelled_at"] = now
            touch(sa)
    return order


def has_blocking_closure(facility_id):
    return any(o["facility_id"] == facility_id
               and o["status"] in ("OPEN", "REOPEN_REQUESTED")
               for o in DB.closure_orders.values())


# --------------------------------------------------------------------------
# permit suspension driven by the enforcement cascade
# --------------------------------------------------------------------------

def suspend_issued_permit_for_hazard(facility):
    permit = issued_permit(facility["id"])
    if permit is None:
        return None
    permit["status"] = "SUSPENDED"
    permit["suspension_reason"] = "IMMINENT_HEALTH_HAZARD"
    touch(permit)
    bump_facility(facility)
    return permit


# --------------------------------------------------------------------------
# recreational-water-illness risk scoring (PRD 3.9)
# --------------------------------------------------------------------------

def score_complaint(complaint):
    if complaint["complaint_type"] != "RWI_ILLNESS":
        return None, 0, 0, False

    window_start = add_days(complaint["reported_at"], -C.RWI_CLUSTER_WINDOW_DAYS)
    peers = []
    for other in DB.complaints.values():
        if other["id"] == complaint["id"]:
            continue
        if other["facility_id"] != complaint["facility_id"]:
            continue
        if other["complaint_type"] != "RWI_ILLNESS":
            continue
        if other["status"] in ("UNSUBSTANTIATED", "CLOSED"):
            continue
        if window_start <= other["reported_at"] <= complaint["reported_at"]:
            peers.append(other)

    if not peers:
        risk_variant = "SINGLE_REPORT"
        cluster_case_count = complaint["illness_case_count"]
        pathogen_pool = [complaint["pathogen_suspected"]]
    else:
        risk_variant = "CLUSTER_AGGREGATE"
        cluster_case_count = complaint["illness_case_count"] + sum(
            p["illness_case_count"] for p in peers)
        pathogen_pool = ([complaint["pathogen_suspected"]]
                         + [p["pathogen_suspected"] for p in peers])

    case_component = min(C.RWI_CASE_POINTS_CAP, cluster_case_count * C.RWI_CASE_POINTS)
    pathogen_component = max(
        (C.RWI_PATHOGEN_WEIGHTS[p] if p is not None else C.RWI_PATHOGEN_WEIGHT_WHEN_NULL)
        for p in pathogen_pool)
    onset_gap_days = (complaint["reported_at"].date()
                      - complaint["symptom_onset_date"]).days
    recency_component = (C.RWI_RECENCY_BONUS
                         if onset_gap_days <= C.RWI_RECENCY_WINDOW_DAYS else 0)

    risk_score = min(C.RWI_SCORE_MAX,
                     case_component + pathogen_component + recency_component)
    escalated = risk_score >= C.RWI_ESCALATION_THRESHOLD
    return risk_variant, cluster_case_count, risk_score, escalated
