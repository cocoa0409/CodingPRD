"""Calculations 2, 3, 4 and 6 plus every derived-aggregate cascade.

  * partner_license_risk_score      (ROLLING_90D and LIFETIME_WEIGHTED variants)
  * partner_posture_derivation      (+ the order-hold cascade it drives)
  * refusal_return_settlement
  * courier_compliance_score        (+ certification suspension / attempt abort)
"""
from datetime import timedelta
from decimal import Decimal

from db import (
    CAP_VERIFIED_CREDIT,
    COMPLIANCE_REFUSAL_REASONS,
    COURIER_CASE_PENALTY,
    COURIER_SUSPENSION_SCORE_THRESHOLD,
    CERT_SUSPENSION_SCORE_THRESHOLD,
    CUSTOMER_BLOCK_DAYS,
    CUSTOMER_BLOCK_STRIKE_THRESHOLD,
    DECIDED_CASE_STATES,
    HANDOVER_BONUS_CAP,
    HANDOVER_BONUS_PER,
    OPEN_ATTEMPT_STATES,
    OPEN_CASE_STATES,
    POSTURE_RESTRICT_OPEN_CASES,
    POSTURE_RESTRICT_SCORE,
    POSTURE_SUSPEND_CRITICAL_CASES,
    POSTURE_SUSPEND_SCORE,
    SEVERITY_POINTS,
    SHOPPER_FAIL_PENALTY,
    TIER_MULTIPLIER,
    db,
    decided_sort_key,
    new_row,
    now,
    now_str,
    recorded_sort_key,
    sort_key,
    touch,
)
from util import add_days, dec, fmt_dt, parse_dt, rhu

ZERO2 = Decimal("0.00")
HUNDRED = Decimal("100.00")
POSTURE_RANK = {"OPEN": 0, "RESTRICTED": 1, "SUSPENDED": 2}
ROLLING_WINDOW_DAYS = 90
LIFETIME_DECAY_STEP_DAYS = 90
LIFETIME_DECAY_PER_STEP = Decimal("0.10")
LIFETIME_WEIGHT_FLOOR = Decimal("0.25")


# ---------------------------------------------------------------------------
# Calculation 2 -- partner_license_risk_score
# ---------------------------------------------------------------------------
def partner_case_terms(partner, clock=None):
    """Per-case rolling and lifetime terms, ordered decided_at ASC then created_at ASC."""
    if clock is None:
        clock = now()
    rows = [c for c in db.cases.values()
            if c["delivery_partner_id"] == partner["id"]
            and c["state"] in DECIDED_CASE_STATES
            and c.get("assessed_severity") is not None
            and c.get("decided_at")]
    rows.sort(key=decided_sort_key)
    terms = []
    for case in rows:
        decided = parse_dt(case["decided_at"])
        age_days = int((clock - decided).total_seconds() // 86400)
        points = Decimal(SEVERITY_POINTS[case["assessed_severity"]])
        credit = CAP_VERIFIED_CREDIT if case["state"] == "CLOSED_VERIFIED" else Decimal("1")
        included = age_days <= ROLLING_WINDOW_DAYS
        rolling_points = rhu(points * Decimal("1.00") * credit, 2) if included else ZERO2
        steps = age_days // LIFETIME_DECAY_STEP_DAYS if age_days >= 0 else 0
        lifetime_weight = max(LIFETIME_WEIGHT_FLOOR,
                              Decimal("1.00") - LIFETIME_DECAY_PER_STEP * steps)
        lifetime_points = rhu(points * lifetime_weight * credit, 2)
        terms.append({
            "case": case,
            "age_days": age_days,
            "included_in_rolling": included,
            "rolling_points": rolling_points,
            "lifetime_weight": lifetime_weight,
            "lifetime_points": lifetime_points,
        })
    return terms


def partner_scores(partner, clock=None):
    terms = partner_case_terms(partner, clock)
    tier = TIER_MULTIPLIER[partner["contract_tier"]]
    rolling_raw = Decimal("0")
    lifetime_raw = Decimal("0")
    for term in terms:
        rolling_raw += term["rolling_points"]
        lifetime_raw += term["lifetime_points"]
    rolling = min(HUNDRED, rhu(rolling_raw * tier, 2))
    lifetime = min(HUNDRED, rhu(lifetime_raw * tier, 2))
    return rolling, lifetime, terms, tier


def recompute_partner_scores(partner):
    rolling, lifetime, terms, _tier = partner_scores(partner)
    if partner["license_risk_score"] != rolling or partner["lifetime_risk_score"] != lifetime:
        partner["license_risk_score"] = rolling
        partner["lifetime_risk_score"] = lifetime
        touch(partner)
    return terms


def case_rolling_contribution(case, clock=None):
    """A single case's own rounded rolling term (0.00 unless SUBSTANTIATED)."""
    if case["state"] != "SUBSTANTIATED" or not case.get("assessed_severity") or not case.get("decided_at"):
        return ZERO2
    if clock is None:
        clock = now()
    decided = parse_dt(case["decided_at"])
    age_days = int((clock - decided).total_seconds() // 86400)
    if age_days > ROLLING_WINDOW_DAYS:
        return ZERO2
    return rhu(Decimal(SEVERITY_POINTS[case["assessed_severity"]]) * Decimal("1.00"), 2)


def recount_partner_cases(partner):
    open_count = 0
    critical_count = 0
    for case in db.cases.values():
        if case["delivery_partner_id"] != partner["id"]:
            continue
        if case["state"] not in OPEN_CASE_STATES:
            continue
        open_count += 1
        if case["severity"] == "CRITICAL":
            critical_count += 1
    if partner["open_case_count"] != open_count or partner["open_critical_case_count"] != critical_count:
        partner["open_case_count"] = open_count
        partner["open_critical_case_count"] = critical_count
        touch(partner)


# ---------------------------------------------------------------------------
# Calculation 3 -- partner_posture_derivation
# ---------------------------------------------------------------------------
def rederive_posture(partner):
    """Always evaluated strictly after the risk score has been rewritten."""
    previous = partner["posture"]
    score = partner["license_risk_score"]
    if score >= POSTURE_SUSPEND_SCORE or partner["open_critical_case_count"] >= POSTURE_SUSPEND_CRITICAL_CASES:
        derived = "SUSPENDED"
    elif score >= POSTURE_RESTRICT_SCORE or partner["open_case_count"] >= POSTURE_RESTRICT_OPEN_CASES:
        derived = "RESTRICTED"
    else:
        derived = "OPEN"
    if derived == previous:
        return False
    partner["posture"] = derived
    touch(partner)
    if POSTURE_RANK[derived] > POSTURE_RANK[previous]:
        hold_dispatched_orders(partner, derived)
    for courier in couriers_of(partner["id"]):
        rederive_courier_gates(courier)
    return True


def hold_dispatched_orders(partner, new_posture):
    """Worsening posture recalls DISPATCHED orders, in created_at ASC order."""
    rows = [o for o in db.orders.values()
            if o["delivery_partner_id"] == partner["id"] and o["fulfillment_state"] == "DISPATCHED"]
    rows.sort(key=sort_key)
    for order in rows:
        order["fulfillment_state"] = "HELD_AT_HUB"
        order["dispatched_at"] = None
        order["hold_reason"] = "PARTNER_POSTURE_" + new_posture
        if order["compliance_state"] in ("PREVERIFIED", "COMPLIANCE_CLEARED"):
            order["compliance_state"] = "PENDING_COMPLIANCE_REVIEW"
        touch(order)


def refresh_partner(partner):
    """Recount counters, rewrite both risk variants, then re-derive posture."""
    recount_partner_cases(partner)
    recompute_partner_scores(partner)
    rederive_posture(partner)


# ---------------------------------------------------------------------------
# Courier gates and Calculation 6 -- courier_compliance_score
# ---------------------------------------------------------------------------
def couriers_of(partner_id):
    rows = [c for c in db.couriers.values() if c["delivery_partner_id"] == partner_id]
    rows.sort(key=sort_key)
    return rows


def certifications_of(courier_id, state=None):
    rows = [c for c in db.certifications.values() if c["courier_id"] == courier_id]
    if state is not None:
        rows = [c for c in rows if c["state"] == state]
    rows.sort(key=sort_key)
    return rows


def attempts_of_courier(courier_id):
    rows = [a for a in db.attempts.values() if a["courier_id"] == courier_id]
    rows.sort(key=sort_key)
    return rows


def courier_compliance_score(courier):
    total = HUNDRED
    fails = [t for t in db.shopper_tests.values()
             if t["courier_id"] == courier["id"] and t["verdict"] == "FAIL"]
    fails.sort(key=recorded_sort_key)
    for _ in fails:
        total -= SHOPPER_FAIL_PENALTY
    cases = []
    for case in db.cases.values():
        if case["state"] not in DECIDED_CASE_STATES:
            continue
        if not case.get("delivery_attempt_id"):
            continue
        attempt = db.attempts.get(case["delivery_attempt_id"])
        if attempt is None or attempt["courier_id"] != courier["id"]:
            continue
        if not case.get("assessed_severity"):
            continue
        cases.append(case)
    cases.sort(key=decided_sort_key)
    for case in cases:
        total -= COURIER_CASE_PENALTY[case["assessed_severity"]]
    bonus = min(HANDOVER_BONUS_CAP, HANDOVER_BONUS_PER * courier["compliant_handover_count"])
    total = rhu(total + bonus, 2)
    if total < ZERO2:
        total = ZERO2
    if total > HUNDRED:
        total = HUNDRED
    return total


def rederive_courier_gates(courier):
    score = courier["compliance_score"]
    has_active = len(certifications_of(courier["id"], "ACTIVE")) > 0
    if score < COURIER_SUSPENSION_SCORE_THRESHOLD:
        derived = "SUSPENDED"
    elif has_active:
        derived = "CERTIFIED"
    else:
        derived = "UNCERTIFIED"
    partner = db.partners.get(courier["delivery_partner_id"])
    eligible = derived == "CERTIFIED" and partner is not None and partner["posture"] != "SUSPENDED"
    if courier["certification_state"] != derived or courier["dispatch_eligible"] != eligible:
        courier["certification_state"] = derived
        courier["dispatch_eligible"] = eligible
        touch(courier)


def recount_compliant_handovers(courier):
    count = 0
    for attempt in db.attempts.values():
        if attempt["courier_id"] != courier["id"]:
            continue
        if attempt["state"] == "HANDED_OVER" and attempt["id_check_compliant"]:
            count += 1
    if courier["compliant_handover_count"] != count:
        courier["compliant_handover_count"] = count
        touch(courier)


def recompute_courier_score(courier):
    """Link 1, then the two cascades it can trigger, then the derived gates."""
    score = courier_compliance_score(courier)
    if courier["compliance_score"] != score:
        courier["compliance_score"] = score
        touch(courier)
    if score < CERT_SUSPENSION_SCORE_THRESHOLD:
        active = certifications_of(courier["id"], "ACTIVE")
        if active:
            for certification in active:
                certification["state"] = "SUSPENDED"
                touch(certification)
            abort_open_attempts(courier, "CERTIFICATION_SUSPENDED")
    rederive_courier_gates(courier)


def abort_open_attempts(courier, reason="CERTIFICATION_SUSPENDED"):
    """Cascade link 3: abort in-flight attempts, in created_at ASC order."""
    for attempt in attempts_of_courier(courier["id"]):
        if attempt["state"] not in OPEN_ATTEMPT_STATES:
            continue
        attempt["state"] = "ABORTED"
        attempt["abort_reason"] = reason
        touch(attempt)
        order = db.orders.get(attempt["order_id"])
        if order is None:
            continue
        if order["fulfillment_state"] == "OUT_FOR_DELIVERY":
            order["fulfillment_state"] = "RETURN_IN_TRANSIT"
        order["hold_reason"] = "COURIER_CERTIFICATION_SUSPENDED"
        touch(order)


# ---------------------------------------------------------------------------
# Customer derived aggregates
# ---------------------------------------------------------------------------
def rederive_latest_identity_result(customer):
    rows = [c for c in db.identity_checks.values()
            if c["customer_id"] == customer["id"] and c["status"] == "VALID"]
    if rows:
        rows.sort(key=sort_key)
        derived = rows[-1]["result"]
    else:
        derived = "NONE"
    if customer["latest_identity_check_result"] != derived:
        customer["latest_identity_check_result"] = derived
        touch(customer)
        return True
    return False


def recompute_refusal_strikes(customer, trigger_attempt=None):
    strikes = 0
    for attempt in db.attempts.values():
        if attempt["state"] != "REFUSED":
            continue
        if attempt.get("refusal_reason") not in COMPLIANCE_REFUSAL_REASONS:
            continue
        order = db.orders.get(attempt["order_id"])
        if order is None or order["customer_id"] != customer["id"]:
            continue
        strikes += 1
    changed = customer["refusal_strikes"] != strikes
    customer["refusal_strikes"] = strikes
    if strikes >= CUSTOMER_BLOCK_STRIKE_THRESHOLD and trigger_attempt is not None:
        started = parse_dt(trigger_attempt["started_at"])
        blocked_until = fmt_dt(add_days(started, CUSTOMER_BLOCK_DAYS))
        if customer["blocked_until"] != blocked_until:
            customer["blocked_until"] = blocked_until
            changed = True
    if changed:
        touch(customer)


# ---------------------------------------------------------------------------
# Violation case opening (shared by the refusal and shopper-fail cascades)
# ---------------------------------------------------------------------------
def open_case(partner_id, severity, summary, origin,
              delivery_attempt_id=None, secret_shopper_test_id=None):
    case = new_row(
        delivery_partner_id=partner_id,
        delivery_attempt_id=delivery_attempt_id,
        secret_shopper_test_id=secret_shopper_test_id,
        severity=severity,
        assessed_severity=None,
        summary=summary,
        state="OPEN",
        investigation_rounds=0,
        decided_at=None,
        substantiated_by_user_id=None,
        risk_contribution=ZERO2,
        response_due_at=None,
        partner_response_text=None,
        notes=None,
        origin=origin,
    )
    db.cases[case["id"]] = case
    return case


# ---------------------------------------------------------------------------
# Calculation 4 -- refusal_return_settlement
# ---------------------------------------------------------------------------
def restocking_tier_bps(gross_cents):
    if gross_cents < 5000:
        return 0
    if gross_cents < 20000:
        return 500
    return 800


def governing_refusal_reason(order):
    """The REFUSED attempt with the greatest started_at; ties break on earlier created_at."""
    rows = [a for a in db.attempts.values()
            if a["order_id"] == order["id"] and a["state"] == "REFUSED"]
    if not rows:
        return None
    rows.sort(key=lambda a: (parse_dt(a["started_at"]), a["created_at"], a["_seq"]))
    return rows[-1].get("refusal_reason")


def settlement_figures(order):
    reason = governing_refusal_reason(order)
    gross = order["item_subtotal_cents"]
    bps = restocking_tier_bps(gross)
    if reason == "COURIER_FAULT":
        fee = 0
        fee_refund = order["delivery_fee_cents"]
    else:
        fee = (gross * bps) // 10000
        fee_refund = 0
    refunded = gross - fee + fee_refund
    retained = order["charged_cents"] - refunded
    return {
        "reason": reason,
        "restocking_fee_cents": fee,
        "refunded_cents": refunded,
        "retained_cents": retained,
    }
