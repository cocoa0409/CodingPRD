"""Calculation rules (SCAFFOLD 1.3 / PRD 3.2-3.9). Every derived number is a
consequence recomputed from primary records."""
from decimal import Decimal

from common import D, num, quantize_quarter, rhu, sorted_records
from store import clock_now, db

# --- constants -------------------------------------------------------------
TRANSFER_OUT_LOS_HOURS = D("24.00")
TRANSFER_OUT_ISS_FLOOR = 9
MIN_ISS_INCLUSION = 4
CRIBARI_ISS = 16
UNDER_TRIAGE_ALERT_PCT = D("5.00")
OVER_TRIAGE_ALERT_PCT = D("35.00")
ESCALATION_SUSPEND_COUNT = 2
CONDITIONAL_PI_COUNT = 3
ABSTRACTION_WINDOW_DAYS = 60
LOOP_CLOSURE_DAYS = 60
ESCALATION_REMEDIATION_DAYS = 30
SUBMIT_MIN_READINESS = D("70.00")
TRAVEL_BUFFER_HOURS = 24
BAND_HIGH_MIN = D("95.00")
BAND_MID_MIN = D("90.00")
ERROR_WEIGHT = {"CRITICAL": 4, "MAJOR": 2, "MINOR": 1}
SEVERITY_RANK = {"CRITICAL": 1, "MAJOR": 2, "MINOR": 3}
KIND_WEIGHT = {
    "INJURY_PREVENTION": D("1.5"),
    "PROFESSIONAL_EDUCATION": D("1.0"),
    "COMMUNITY_OUTREACH": D("0.5"),
}
OPEN_PI_STATUSES = ("IDENTIFIED", "UNDER_REVIEW", "ACTION_PLANNED", "REOPENED")
CYCLE_OPEN_DEFICIENCY_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED", "ESCALATED")
DECIDED_CYCLE_STATUSES = ("VERIFIED", "DENIED")

# --- collection helpers ----------------------------------------------------


def cases_of_center(center_id):
    return [c for c in db.cases.values() if c["center_id"] == center_id]


def abstractions_of_case(case_id):
    return sorted_records([a for a in db.abstractions.values() if a["case_id"] == case_id])


def pi_events_of_center(center_id):
    return [e for e in db.pi_events.values() if e["center_id"] == center_id]


def actions_of_event(event_id):
    return sorted_records([a for a in db.actions.values() if a["pi_event_id"] == event_id])


def cycles_of_center(center_id):
    return sorted_records([c for c in db.cycles.values() if c["center_id"] == center_id])


def deficiencies_of_cycle(cycle_id):
    return sorted_records(
        [d for d in db.deficiencies.values() if d["verification_cycle_id"] == cycle_id]
    )


def deficiencies_of_center(center_id):
    result = []
    for cycle in cycles_of_center(center_id):
        result.extend(deficiencies_of_cycle(cycle["id"]))
    return result


def activities_of_center(center_id):
    return sorted_records([a for a in db.activities.values() if a["center_id"] == center_id])


def bookings_of_cycle(cycle_id):
    return sorted_records(
        [b for b in db.bookings.values() if b["verification_cycle_id"] == cycle_id]
    )


def center_of_cycle(cycle):
    return db.centers.get(cycle["center_id"])


def cycle_of_deficiency(deficiency):
    return db.cycles.get(deficiency["verification_cycle_id"])


# --- effective_iss and registry inclusion (PRD 3.2) ------------------------


def latest_validated_abstraction(case_id):
    records = [a for a in abstractions_of_case(case_id) if a["validation_status"] == "VALIDATED"]
    return records[-1] if records else None


def compute_effective_iss(case):
    if case["abstraction_status"] in ("VALIDATED", "LOCKED"):
        record = latest_validated_abstraction(case["id"])
        if record is not None and record["iss_abstracted"] is not None:
            return record["iss_abstracted"]
    return case["injury_severity_score"]


def classify_inclusion(case):
    """Three-branch classification, top to bottom, first match wins."""
    effective_iss = compute_effective_iss(case)
    case["effective_iss"] = effective_iss
    tier = db.tiers.get(case["activation_tier_id"])
    if (
        case["transfer_out_to_center_id"] is not None
        and D(case["los_hours"]) < TRANSFER_OUT_LOS_HOURS
        and effective_iss < TRANSFER_OUT_ISS_FLOOR
    ):
        return "EXCLUDED", "TRANSFER_OUT_MINOR_UNDER_24H"
    if effective_iss < MIN_ISS_INCLUSION and tier is not None and tier["tier_code"] == "TIER_3_CONSULT":
        return "EXCLUDED", "BELOW_INJURY_THRESHOLD"
    return "INCLUDED", "MEETS_INCLUSION_CRITERIA"


def apply_inclusion(case):
    status, reason = classify_inclusion(case)
    case["inclusion_status"] = status
    case["inclusion_reason"] = reason
    return status, reason


# --- triage rates (PRD 3.5) ------------------------------------------------


def _rate(numerator, denominator):
    if denominator == 0:
        return D("0.00")
    return rhu(D(100) * D(numerator) / D(denominator))


def triage_rates(center_id, variant="PROVISIONAL_MONITORING"):
    cases = [c for c in cases_of_center(center_id) if c["inclusion_status"] == "INCLUDED"]
    if variant == "VERIFICATION_AUDIT":
        cohort = [c for c in cases if c["abstraction_status"] in ("VALIDATED", "LOCKED")]
        under = 0
        over = 0
        for case in cohort:
            tier = db.tiers.get(case["activation_tier_id"])
            tier_code = tier["tier_code"] if tier else None
            effective_iss = case["effective_iss"]
            if effective_iss is not None and effective_iss >= CRIBARI_ISS and tier_code == "TIER_3_CONSULT":
                under += 1
            if effective_iss is not None and effective_iss < TRANSFER_OUT_ISS_FLOOR and tier_code == "TIER_1_FULL":
                over += 1
    else:
        cohort = cases
        under = len([c for c in cohort if c["triage_review_status"] == "UNDER_TRIAGE_CONFIRMED"])
        over = len([c for c in cohort if c["triage_review_status"] == "OVER_TRIAGE_CONFIRMED"])
    denominator = len(cohort)
    return {
        "variant": variant,
        "denominator_case_count": denominator,
        "under_triage_numerator": under,
        "over_triage_numerator": over,
        "under_triage_rate_pct": _rate(under, denominator),
        "over_triage_rate_pct": _rate(over, denominator),
    }


# --- data dictionary scan (PRD 3.3) ---------------------------------------


def band_multiplier(score_at_request_start):
    score = D(score_at_request_start)
    if score >= BAND_HIGH_MIN:
        return D("1.0")
    if score >= BAND_MID_MIN:
        return D("1.5")
    return D("2.0")


def _rule_violated(rule, value):
    kind = rule["rule_kind"]
    if kind == "REQUIRED":
        return value is None
    if value is None:
        return False
    if kind == "RANGE":
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            return False
        low = rule.get("min_value")
        high = rule.get("max_value")
        if low is not None and D(value) < D(low):
            return True
        if high is not None and D(value) > D(high):
            return True
        return False
    if kind == "CONFORMANCE":
        allowed = rule.get("allowed_codes") or []
        return value not in allowed and str(value) not in [str(a) for a in allowed]
    return False


def dictionary_scan(values):
    """Evaluate every dictionary rule in ascending (severity_rank, field_name)."""
    rules = sorted(
        db.rules.values(),
        key=lambda r: (SEVERITY_RANK.get(r["severity"], 9), r["field_name"], r["_seq"]),
    )
    violations = []
    raw_penalty = 0
    for rule in rules:
        value = values.get(rule["field_name"])
        if _rule_violated(rule, value):
            violations.append(rule)
            raw_penalty += ERROR_WEIGHT.get(rule["severity"], 0)
    return violations, len(violations), raw_penalty


# --- outreach credit-hour ledger (PRD 3.8) -------------------------------


def weighted_credit_hours(activity_kind, credit_hours):
    weight = KIND_WEIGHT.get(activity_kind, D("0"))
    return quantize_quarter(D(credit_hours) * weight)


def outreach_ledger(center_id):
    total = D("0")
    for activity in activities_of_center(center_id):
        if activity["verified_status"] == "VERIFIED":
            total += D(activity["weighted_credit_hours"])
    return rhu(total)


# --- response time compliance (PRD 3.4) ----------------------------------


def response_compliance(case, responder_role, notified_at, arrived_at):
    tier = db.tiers.get(case["activation_tier_id"])
    if tier is None:
        applicable = None
    elif responder_role == "SURGEON":
        applicable = tier["surgeon_response_limit_minutes"]
    else:
        applicable = tier["specialty_response_limit_minutes"]
    if arrived_at is None:
        return None, applicable, "UNDOCUMENTED"
    minutes = rhu(D((arrived_at - notified_at).total_seconds()) / D(60))
    if applicable is not None and minutes <= D(applicable):
        status = "COMPLIANT"
    else:
        status = "LATE"
    return minutes, applicable, status


# --- overdue loops and readiness posture (PRD 2.7 / 3.7) -----------------


def overdue_loop_count(center_id):
    now = clock_now()
    total = 0
    for event in pi_events_of_center(center_id):
        if event["status"] in OPEN_PI_STATUSES and event["loop_closure_due_at"] is not None:
            if event["loop_closure_due_at"] < now:
                total += 1
    return total


def open_pi_event_count(center_id):
    return len([e for e in pi_events_of_center(center_id) if e["status"] in OPEN_PI_STATUSES])


def closed_pi_event_count(center_id):
    return len([e for e in pi_events_of_center(center_id) if e["status"] == "LOOP_CLOSED"])


def open_critical_deficiency_count(center_id):
    return len(
        [
            d
            for d in deficiencies_of_center(center_id)
            if d["deficiency_class"] == "TYPE_I_CRITICAL" and d["status"] != "CLOSED"
        ]
    )


def escalated_critical_deficiency_count(center_id):
    return len(
        [
            d
            for d in deficiencies_of_center(center_id)
            if d["deficiency_class"] == "TYPE_I_CRITICAL" and d["status"] == "ESCALATED"
        ]
    )


def readiness_posture(center):
    """First-match-wins ladder; the ordering is normative (PRD 2.7)."""
    overdue = overdue_loop_count(center["id"])
    if (
        center["national_verification_status"] == "SUSPENDED"
        or center["escalated_critical_deficiency_count"] >= ESCALATION_SUSPEND_COUNT
    ):
        return "SUSPENDED"
    if (
        center["open_critical_deficiency_count"] >= 1
        or D(center["under_triage_rate_pct"]) >= UNDER_TRIAGE_ALERT_PCT
        or overdue >= 1
    ):
        return "AT_RISK"
    if (
        center["open_pi_event_count"] >= CONDITIONAL_PI_COUNT
        or D(center["over_triage_rate_pct"]) >= OVER_TRIAGE_ALERT_PCT
    ):
        return "CONDITIONAL"
    return "READY"


# --- verification readiness score (PRD 3.9) ------------------------------


def cycle_open_class_counts(cycle_id, open_set=CYCLE_OPEN_DEFICIENCY_STATUSES):
    counts = {"TYPE_I_CRITICAL": 0, "TYPE_II_MAJOR": 0, "TYPE_III_MINOR": 0}
    for deficiency in deficiencies_of_cycle(cycle_id):
        if deficiency["status"] in open_set and deficiency["deficiency_class"] in counts:
            counts[deficiency["deficiency_class"]] += 1
    return counts


def readiness_breakdown(cycle, variant="REVIEWER_ASSESSMENT"):
    center = center_of_cycle(cycle)
    if variant == "SELF_ASSESSMENT":
        open_set = ("OPEN", "ESCALATED")
    else:
        open_set = CYCLE_OPEN_DEFICIENCY_STATUSES
    counts = cycle_open_class_counts(cycle["id"], open_set)
    deficiency_penalty = min(
        D(60),
        D(15) * counts["TYPE_I_CRITICAL"]
        + D(6) * counts["TYPE_II_MAJOR"]
        + D(2) * counts["TYPE_III_MINOR"],
    )
    national = cycle["cycle_type"] == "NATIONAL_VERIFICATION"
    required_hours = D("12.00") if national else D("8.00")
    ledger = D(center["outreach_credit_hours_ytd"]) if center else D("0.00")
    gap = max(D("0.00"), required_hours - ledger)
    outreach_penalty = min(D("20.00"), rhu(gap * D("1.5")))
    open_events = center["open_pi_event_count"] if center else 0
    overdue = overdue_loop_count(cycle["center_id"])
    if national:
        pi_penalty = min(D(20), D(4) * open_events + D(8) * overdue)
    else:
        pi_penalty = min(D(10), D(2) * open_events)
    compliance = D(center["registry_compliance_score"]) if center else D("100.00")
    registry_penalty = max(D("0.00"), rhu((D("100.00") - compliance) * D("0.25")))
    score = rhu(
        max(
            D("0.00"),
            D("100.00") - deficiency_penalty - outreach_penalty - pi_penalty - registry_penalty,
        )
    )
    return {
        "variant": variant,
        "base_score": D("100.00"),
        "deficiency_penalty": deficiency_penalty,
        "outreach_penalty": outreach_penalty,
        "pi_penalty": pi_penalty,
        "registry_penalty": registry_penalty,
        "readiness_score": score,
    }


def readiness_score(cycle, variant="REVIEWER_ASSESSMENT"):
    return readiness_breakdown(cycle, variant)["readiness_score"]


# --- interval conflicts ---------------------------------------------------


def agreement_overlap(new_from, new_to, referring_id, receiving_id, exclude_id=None):
    """Half-open [effective_from, effective_to): adjacency is legal."""
    candidates = [
        a
        for a in db.agreements.values()
        if a["referring_center_id"] == referring_id
        and a["receiving_center_id"] == receiving_id
        and a["agreement_status"] == "ACTIVE"
        and a["id"] != exclude_id
    ]
    candidates.sort(key=lambda a: (a["effective_from"], a["created_at"], a["_seq"]))
    for candidate in candidates:
        if new_from < candidate["effective_to"] and candidate["effective_from"] < new_to:
            return candidate
    return None


def surveyor_conflict(surveyor_user_id, window_start, window_end, buffer_hours, exclude_id=None):
    """Closed windows padded symmetrically by the travel buffer; adjacency is
    not enough to avoid a conflict."""
    import datetime

    buffer_delta = datetime.timedelta(hours=buffer_hours)
    candidates = [
        b
        for b in db.bookings.values()
        if b["surveyor_user_id"] == surveyor_user_id and b["id"] != exclude_id
    ]
    candidates.sort(key=lambda b: (b["window_start"], b["created_at"], b["_seq"]))
    for candidate in candidates:
        if (
            window_start < candidate["window_end"] + buffer_delta
            and candidate["window_start"] < window_end + buffer_delta
        ):
            return candidate
    return None


def active_agreement_covering(referring_id, receiving_id, instant):
    candidates = [
        a
        for a in db.agreements.values()
        if a["referring_center_id"] == referring_id
        and a["receiving_center_id"] == receiving_id
        and a["agreement_status"] == "ACTIVE"
    ]
    candidates.sort(key=lambda a: (a["effective_from"], a["created_at"], a["_seq"]))
    for candidate in candidates:
        if candidate["effective_from"] <= instant < candidate["effective_to"]:
            return candidate
    return None
