"""The six calculation rules of SCAFFOLD §calculations / PRD §3."""

from decimal import Decimal

import config
import store
from util import days, round_half_up, round_half_up_int


# ---------------------------------------------------------------------------
# sterilization_compliance_status
# ---------------------------------------------------------------------------
def sterilization_candidates(establishment_id, now):
    window_start = now - days(config.STERILIZATION_LOOKBACK_DAYS)
    superseded = set()
    for rec in store.sterilization_records.values():
        if rec.get("supersedes_record_id"):
            superseded.add(rec["supersedes_record_id"])
    out = []
    for rec in store.sorted_rows(store.sterilization_records):
        if rec["establishment_id"] != establishment_id:
            continue
        completed = rec["cycle_completed_at"]
        if completed < window_start or completed > now:
            continue
        if rec["id"] in superseded:
            continue
        out.append(rec)
    return out


def sterilization_status(establishment_id, now):
    candidates = sterilization_candidates(establishment_id, now)
    pass_count = sum(1 for c in candidates if c["spore_test_result"] == "PASS")
    if not candidates:
        return "NONCOMPLIANT", 0, 0
    if any(c["spore_test_result"] in ("FAIL", "PENDING") for c in candidates):
        return "NONCOMPLIANT", len(candidates), pass_count
    if pass_count >= config.SPORE_TESTS_REQUIRED_PER_WINDOW:
        return "COMPLIANT", len(candidates), pass_count
    return "DEFICIENT", len(candidates), pass_count


def sterilization_penalty(status):
    if status == "NONCOMPLIANT":
        return config.STERILIZATION_NONCOMPLIANT_PENALTY
    if status == "DEFICIENT":
        return config.STERILIZATION_DEFICIENT_PENALTY
    return 0


# ---------------------------------------------------------------------------
# establishment_risk_score  (PROVISIONAL / AUDIT dual variant)
# ---------------------------------------------------------------------------
def risk_score(est, now, variant="PROVISIONAL", ster_status=None):
    window_start = now - days(config.RISK_LOOKBACK_DAYS)
    est_id = est["id"]

    def in_window(ts):
        return ts is not None and window_start <= ts <= now

    open_critical = est.get("open_critical_violation_count", 0)
    open_noncritical = est.get("open_violation_count", 0) - open_critical

    substantiated = 0
    in_flight_complaints = 0
    for c in store.complaints.values():
        if c["establishment_id"] != est_id or not in_window(c["received_at"]):
            continue
        if c["status"] == "SUBSTANTIATED":
            substantiated += 1
        elif c["status"] in ("TRIAGED", "INVESTIGATING"):
            in_flight_complaints += 1

    confirmed_inf = 0
    screening_inf = 0
    for r in store.infection_reports.values():
        if r["establishment_id"] != est_id or not in_window(r["created_at"]):
            continue
        if r["investigation_status"] == "CONFIRMED":
            confirmed_inf += 1
        elif r["investigation_status"] == "SCREENING":
            screening_inf += 1

    flagged_minor = 0
    for p in store.procedure_logs.values():
        if p["establishment_id"] != est_id:
            continue
        if p["client_age"] >= config.MINOR_AGE_THRESHOLD:
            continue
        if p["audit_status"] != "FLAGGED":
            continue
        if not in_window(p["started_at"]):
            continue
        flagged_minor += 1

    if ster_status is None:
        ster_status = est.get("sterilization_compliance_status", "NONCOMPLIANT")

    score = (
        config.OPEN_CRITICAL_WEIGHT * open_critical
        + config.OPEN_NONCRITICAL_WEIGHT * open_noncritical
        + config.SUBSTANTIATED_COMPLAINT_WEIGHT * substantiated
        + config.CONFIRMED_INFECTION_WEIGHT * confirmed_inf
        + config.FLAGGED_MINOR_LOG_WEIGHT * flagged_minor
        + sterilization_penalty(ster_status)
    )
    if variant == "AUDIT":
        score += (
            config.IN_FLIGHT_COMPLAINT_WEIGHT * in_flight_complaints
            + config.IN_FLIGHT_INFECTION_WEIGHT * screening_inf
        )
    return min(config.RISK_SCORE_CAP, score)


# ---------------------------------------------------------------------------
# operating_posture
# ---------------------------------------------------------------------------
def operating_posture(permit_status, risk, open_critical):
    if permit_status in (
        "PENDING_PLAN_REVIEW",
        "PENDING_INSPECTION",
        "SUSPENDED",
        "EXPIRED",
        "REVOKED",
    ):
        return "CLOSED"
    if risk >= config.RISK_RESTRICTED_THRESHOLD or open_critical > 0:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# violation_abatement_deadline
# ---------------------------------------------------------------------------
def abatement_due_at(issued_at, severity):
    n = (
        config.CRITICAL_ABATEMENT_DAYS
        if severity == "CRITICAL"
        else config.NONCRITICAL_ABATEMENT_DAYS
    )
    return issued_at + days(n)


# ---------------------------------------------------------------------------
# inspection_score
# ---------------------------------------------------------------------------
def inspection_score(inspection, cited, establishment_id):
    """Returns (score, per-line list of (violation, multiplier, deduction))."""
    lookback_start = inspection["scheduled_start_at"] - days(config.REPEAT_LOOKBACK_DAYS)
    lookback_end = inspection["scheduled_start_at"]

    # every violation reachable through this establishment's inspections
    est_inspection_ids = set(
        i["id"]
        for i in store.inspections.values()
        if i["establishment_id"] == establishment_id
    )
    prior = [
        v
        for v in store.violations.values()
        if v["inspection_id"] in est_inspection_ids
        and v["status"] in ("VERIFIED", "ESCALATED")
    ]

    lines = []
    raw_deduction = 0
    for v in cited:
        base = (
            config.CRITICAL_DEDUCTION_POINTS
            if v["severity"] == "CRITICAL"
            else config.NONCRITICAL_DEDUCTION_POINTS
        )
        is_repeat = any(
            p["violation_code"] == v["violation_code"]
            and p["id"] != v["id"]
            and p["issued_at"] is not None
            and lookback_start <= p["issued_at"] < lookback_end
            for p in prior
        )
        multiplier = Decimal(config.REPEAT_MULTIPLIER) if is_repeat else Decimal("1.0")
        deduction = round_half_up_int(Decimal(base) * multiplier)
        raw_deduction += deduction
        lines.append((v, float(multiplier), deduction))

    carryover = min(
        config.CARRYOVER_CAP,
        config.CARRYOVER_PER_OPEN_VIOLATION
        * inspection.get("open_violation_count_at_start", 0),
    )
    type_factor = (
        Decimal(config.REINSPECTION_SEVERITY_FACTOR)
        if inspection["inspection_type"] == "REINSPECTION"
        else Decimal("1.00")
    )
    total_deduction = round_half_up_int(
        Decimal(raw_deduction + carryover) * type_factor
    )
    score = max(0, config.INSPECTION_SCORE_MAX - total_deduction)
    return score, lines


# ---------------------------------------------------------------------------
# renewal_fee_total  (ESTIMATE / FINAL dual variant)
# ---------------------------------------------------------------------------
def renewal_fee_total(n, expedite_requested, permit_expires_on, evaluated_at):
    n = n or 0
    l_base = Decimal(config.BASE_RENEWAL_FEE_CENTS)
    l_artist = Decimal(
        min(n, 3) * config.ARTIST_TIER1_RATE_CENTS
        + max(0, min(n, 8) - 3) * config.ARTIST_TIER2_RATE_CENTS
        + max(0, n - 8) * config.ARTIST_TIER3_RATE_CENTS
    )
    l_tech = Decimal(n * config.TECH_FEE_PER_ARTIST_CENTS)
    l_expedite = Decimal(config.EXPEDITE_FEE_CENTS if expedite_requested else 0)

    mult = Decimal(config.COUNTY_ADMIN_MULTIPLIER)
    subtotal = (
        round_half_up_int(l_base * mult)
        + round_half_up_int(l_artist * mult)
        + round_half_up_int(l_tech * mult)
        + round_half_up_int(l_expedite * mult)
    )

    is_late = permit_expires_on is not None and evaluated_at > permit_expires_on
    late_fee = (
        round_half_up_int(Decimal(config.LATE_FEE_PCT) * Decimal(subtotal))
        if is_late
        else 0
    )
    return subtotal + late_fee, is_late


# ---------------------------------------------------------------------------
# reinstatement_penalty
# ---------------------------------------------------------------------------
def reinstatement_penalty(issued_at, lift_instant):
    elapsed = lift_instant - issued_at
    suspension_days = int(elapsed.total_seconds() // 86400)
    if suspension_days < 0:
        suspension_days = 0
    base_cents = (
        config.REINSTATEMENT_BASE_CENTS
        + config.SUSPENSION_DAY_RATE_CENTS * suspension_days
    )
    if base_cents < config.ADMIN_TIER1_CEILING_CENTS:
        pct = Decimal(config.ADMIN_PCT_TIER1)
    elif base_cents < config.ADMIN_TIER2_CEILING_CENTS:
        pct = Decimal(config.ADMIN_PCT_TIER2)
    else:
        pct = Decimal(config.ADMIN_PCT_TIER3)
    admin_fee = round_half_up_int(Decimal(base_cents) * pct)
    return suspension_days, base_cents, admin_fee, base_cents + admin_fee


# ---------------------------------------------------------------------------
# minor_consent_audit_rate
# ---------------------------------------------------------------------------
def minor_consent_audit_rate(establishment_id, now):
    window_start = now - days(config.AUDIT_WINDOW_DAYS)
    denominator = 0
    numerator = 0
    for p in store.procedure_logs.values():
        if p["establishment_id"] != establishment_id:
            continue
        if p["client_age"] >= config.MINOR_AGE_THRESHOLD:
            continue
        started = p["started_at"]
        if started < window_start or started > now:
            continue
        denominator += 1
        if p["audit_status"] == "FLAGGED":
            numerator += 1
    if denominator == 0:
        return 0.0, 0, 0
    rate = round_half_up(Decimal(numerator) / Decimal(denominator), 4)
    return float(rate), denominator, numerator
