"""Business logic: calculations, state transitions, cascade helpers."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_id, now_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_QUESTIONNAIRE_INCOMPLETE, ERR_EXCEPTION_REQUIRED, ERR_EXCEPTION_EXPIRED,
    ERR_EXCEPTION_CAPACITY_REACHED, ERR_CONTRACT_NOT_EXECUTED,
    ERR_CONTRACT_PERIOD_OVERLAP, ERR_REVIEW_INTERVAL_TOO_SHORT,
    ERR_DUPLICATE_FILING, ERR_REVIEW_NOT_CLOSABLE, ERR_CONTRACTOR_STANDING_SUSPENDED,
    ERR_CONTRACTOR_NOT_VERIFIED, ERR_INSURANCE_BELOW_MINIMUM,
    ERR_DETERMINATION_REQUIRED, ERR_DETERMINATION_STALE, ERR_STALE_VERSION,
    ERR_STALE_CONTRACT_VERSION, ERR_ENGAGEMENT_NOT_APPROVAL_PENDING,
    ERR_APPROVAL_OUT_OF_ORDER, ERR_APPROVER_ALREADY_ACTED,
    ERR_FILING_NOT_SUBMITTABLE, ERR_CORRECTION_REQUIRES_ACCEPTED,
    ERR_AUDIT_NOT_OPEN, ERR_AUDIT_ACTIONS_OPEN, ERR_INQUIRY_DEADLINE_PASSED,
    ERR_CONVERSION_NOT_POSSIBLE,
)

FACTOR_KEYS = [
    "CONTROL_METHOD", "CONTROL_HOURS", "OUTSIDE_USUAL_BUSINESS", "INDEPENDENT_TRADE",
    "PROFIT_LOSS", "INVESTMENT", "INTEGRAL_TO_BUSINESS", "PERMANENCY",
]

APPROVAL_SEQUENCE = ["HRApprover", "LegalApprover", "ComplianceBoardMember"]

FEDERAL_1099_THRESHOLD_CENTS = 60000

EVENT_POINTS = {
    "SUPERVISION_OBSERVED": 15,
    "EQUIPMENT_PROVIDED": 10,
    "INTEGRATED_WORKFLOW": 15,
    "PAYMENT_REGULARITY": 5,
}
EVENT_OCCURRENCE_CAP = 3


# ---------------------------------------------------------------------------
# common helpers
# ---------------------------------------------------------------------------

def touch(resource):
    resource["updated_at"] = now_iso()
    resource["version"] = resource.get("version", 1) + 1


def stamp_new(resource):
    ts = now_iso()
    resource["created_at"] = ts
    resource["updated_at"] = ts
    resource["version"] = 1


def lazy_expire_grant(grant):
    if grant["status"] == "ACTIVE":
        from db import parse_iso
        exp = parse_iso(grant["expires_at"])
        if exp is not None and store.clock > exp:
            grant["status"] = "EXPIRED"


def lazy_expire_contract(contract):
    if contract["status"] == "EXECUTED":
        from db import parse_date
        end = parse_date(contract["end_date"])
        if end is not None and store.clock.date() > end:
            contract["status"] = "EXPIRED"
            touch(contract)


def get_engagement_or_404(engagement_id):
    from errors import ERR_ENGAGEMENT_NOT_FOUND
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise ApiError(ERR_ENGAGEMENT_NOT_FOUND, 404, "Engagement not found")
    return eng


def get_contractor_or_404(contractor_id):
    from errors import ERR_CONTRACTOR_NOT_FOUND
    c = store.contractors.get(contractor_id)
    if c is None:
        raise ApiError(ERR_CONTRACTOR_NOT_FOUND, 404, "Contractor not found")
    return c


# ---------------------------------------------------------------------------
# calculation: classification_test_application
# ---------------------------------------------------------------------------

def run_classification(engagement, questionnaire):
    jur = store.jurisdictions[engagement["jurisdiction_id"]]
    test_type = jur["test_type"]
    answers = {a["factor_key"]: a["answer"] for a in questionnaire["answers"]}

    def ans(key):
        return answers.get(key)

    if test_type == "COMMON_LAW_WEIGHTED":
        score = Decimal("0")
        if ans("CONTROL_METHOD") == "YES":
            score += Decimal("0.25")
        if ans("CONTROL_HOURS") == "YES":
            score += Decimal("0.20")
        if ans("INTEGRAL_TO_BUSINESS") == "YES":
            score += Decimal("0.20")
        if ans("PROFIT_LOSS") == "NO":
            score += Decimal("0.15")
        if ans("PERMANENCY") == "YES":
            score += Decimal("0.10")
        if ans("INVESTMENT") == "NO":
            score += Decimal("0.10")
        score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        threshold = Decimal(str(jur["employee_score_threshold"]))
        outcome = "EMPLOYEE_RISK" if score >= threshold else "CONTRACTOR"
        return outcome, float(score), 0

    if test_type == "ABC_TEST":
        failed = 0
        if ans("CONTROL_METHOD") == "YES" or ans("CONTROL_HOURS") == "YES":
            failed += 1
        if ans("OUTSIDE_USUAL_BUSINESS") == "NO":
            failed += 1
        if ans("INDEPENDENT_TRADE") == "NO":
            failed += 1
        outcome = "CONTRACTOR" if failed == 0 else "EMPLOYEE_RISK"
        return outcome, failed, failed

    # ECONOMIC_REALITY
    count = 0
    if ans("CONTROL_METHOD") == "YES":
        count += 1
    if ans("INTEGRAL_TO_BUSINESS") == "YES":
        count += 1
    if ans("PROFIT_LOSS") == "NO":
        count += 1
    if ans("INVESTMENT") == "NO":
        count += 1
    if ans("PERMANENCY") == "YES":
        count += 1
    if ans("OUTSIDE_USUAL_BUSINESS") == "NO":
        count += 1
    outcome = "EMPLOYEE_RISK" if count >= 2 else "CONTRACTOR"
    return outcome, count, 0


def recompute_risk_tier(engagement):
    det_id = engagement.get("current_determination_id")
    if not det_id:
        engagement["risk_tier"] = None
        engagement["required_approval_count"] = None
        return
    det = store.determinations[det_id]
    jur = store.jurisdictions[engagement["jurisdiction_id"]]
    if det["outcome"] == "EMPLOYEE_RISK":
        engagement["risk_tier"] = "HIGH"
    elif jur["test_type"] in ("ABC_TEST", "ECONOMIC_REALITY"):
        engagement["risk_tier"] = "ELEVATED"
    else:
        engagement["risk_tier"] = "STANDARD"
    engagement["required_approval_count"] = {
        "STANDARD": 1, "ELEVATED": 2, "HIGH": 3,
    }[engagement["risk_tier"]]


# ---------------------------------------------------------------------------
# calculation: scope_creep_index
# ---------------------------------------------------------------------------

def recompute_scope_creep(engagement):
    contracts = [c for c in store.contracts.values() if c["engagement_id"] == engagement["id"]]
    contract = contracts[0] if contracts else None

    a_count = 0
    if contract:
        a_count = sum(
            1 for am in store.amendments.values()
            if am["contract_id"] == contract["id"] and am["status"] == "APPLIED"
        )

    r = Decimal("0")
    if contract and contract.get("original_rate_cents"):
        orig = contract["original_rate_cents"]
        if orig:
            r = abs(Decimal(contract["rate_cents"]) - Decimal(orig)) / Decimal(orig)

    from db import parse_date
    end = parse_date(engagement["end_date"])
    d = 0
    if end is not None:
        delta = (store.clock.date() - end).days
        d = max(0, delta)

    raw = Decimal(min(a_count, 5) * 12)
    raw += min(r, Decimal("0.50")) * Decimal(200)
    raw += Decimal(min(d, 90))

    s = engagement.get("supervision_level", "NONE")
    if s == "CLOSE":
        raw = raw * Decimal("1.5")
    elif s == "LIGHT":
        raw = raw * Decimal("1.2")

    if engagement["status"] == "SUSPENDED":
        raw = max(raw, Decimal(70))

    idx = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    idx = min(100, idx)
    engagement["scope_creep_index"] = idx
    if idx < 25:
        engagement["scope_creep_tier"] = "LOW"
    elif idx < 50:
        engagement["scope_creep_tier"] = "MODERATE"
    elif idx < 75:
        engagement["scope_creep_tier"] = "HIGH"
    else:
        engagement["scope_creep_tier"] = "CRITICAL"


# ---------------------------------------------------------------------------
# calculation: reclassification_risk_score
# ---------------------------------------------------------------------------

def _full_months(start, end):
    """Full calendar months between two dates."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def compute_provisional_score(contractor_id, engagement_id):
    from db import parse_date
    if engagement_id:
        eng = store.engagements.get(engagement_id)
        if eng is None:
            scope_term = 0
            det_term = 0
            exc_term = 0
            month_term = 0
        else:
            scope_term = Decimal("0.5") * Decimal(eng.get("scope_creep_index", 0))
            det_term = Decimal(0)
            det_id = eng.get("current_determination_id")
            if det_id and store.determinations[det_id]["outcome"] == "EMPLOYEE_RISK":
                det_term = Decimal(40)
            exc_term = Decimal(10) * sum(
                1 for g in store.exceptions.values()
                if g["engagement_id"] == eng["id"] and g["status"] == "ACTIVE"
            )
            start = parse_date(eng["start_date"])
            months = _full_months(start, store.clock.date()) if start else 0
            month_term = Decimal(2) * Decimal(min(months, 12))
        total = scope_term + det_term + exc_term + month_term
        return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    # portfolio audit
    engs = [
        e for e in store.engagements.values()
        if e["contractor_id"] == contractor_id and e["status"] in ("ACTIVE", "SUSPENDED")
    ]
    if not engs:
        return 0.0
    scope_term = Decimal("0.5") * Decimal(max(e.get("scope_creep_index", 0) for e in engs))
    det_term = Decimal(0)
    for e in engs:
        det_id = e.get("current_determination_id")
        if det_id and store.determinations[det_id]["outcome"] == "EMPLOYEE_RISK":
            det_term = Decimal(40)
            break
    exc_count = 0
    for e in engs:
        exc_count += sum(
            1 for g in store.exceptions.values()
            if g["engagement_id"] == e["id"] and g["status"] == "ACTIVE"
        )
    exc_term = Decimal(10) * Decimal(exc_count)
    starts = [parse_date(e["start_date"]) for e in engs]
    starts = [s for s in starts if s]
    months = _full_months(min(starts), store.clock.date()) if starts else 0
    month_term = Decimal(2) * Decimal(min(months, 12))
    total = scope_term + det_term + exc_term + month_term
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def risk_level_for(score):
    if score < 25:
        return "LOW"
    if score < 50:
        return "MODERATE"
    if score < 75:
        return "HIGH"
    return "CRITICAL"


def compute_final_score(provisional, fieldwork_events):
    counts = {}
    points = Decimal(0)
    for ev in fieldwork_events:
        et = ev.get("event_type") if isinstance(ev, dict) else ev
        if et not in EVENT_POINTS:
            continue
        counts[et] = counts.get(et, 0) + 1
        if counts[et] <= EVENT_OCCURRENCE_CAP:
            points += Decimal(EVENT_POINTS[et])
    total = Decimal("0.3") * Decimal(str(provisional)) + points
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# calculation: conversion_lookback_compensation (pinned per-quarter rounding)
# ---------------------------------------------------------------------------

def compute_lookback(quarters):
    total = 0
    fees = 0
    for q in quarters:
        fee = int(q["service_fee_cents"])
        fees += fee
        employer_cost = int(
            (Decimal(fee) * Decimal("1.0765")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        benefits = int(
            (Decimal(employer_cost) * Decimal("0.30")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        total += employer_cost + benefits
    return total, total - fees


# ---------------------------------------------------------------------------
# calculation: reportable_amount_1099
# ---------------------------------------------------------------------------

def compute_reportable(tax_year, line_items, state_threshold_cents):
    from db import parse_date
    start = date(tax_year, 1, 1)
    end = date(tax_year, 12, 31)
    total = 0
    for item in line_items:
        if item.get("kind") != "SERVICE_FEE":
            continue
        pd_ = parse_date(item.get("payment_date"))
        if pd_ is None:
            continue
        if start <= pd_ <= end:
            total += int(item.get("amount_cents", 0))
    federal = total >= FEDERAL_1099_THRESHOLD_CENTS
    state = total >= int(state_threshold_cents)
    return total, federal, state


# ---------------------------------------------------------------------------
# calculation: late_filing_penalty
# ---------------------------------------------------------------------------

def compute_late_penalty(tax_year, filed_dt):
    deadline = date(tax_year + 1, 1, 31)
    days = (filed_dt.date() - deadline).days
    days_late = max(0, days)
    if days_late == 0:
        penalty = 0
    elif days_late <= 30:
        penalty = 6000
    elif days_late <= 121:
        penalty = 13000
    else:
        penalty = 33000
    return days_late, penalty


# ---------------------------------------------------------------------------
# calculation: agency_exposure_estimate (pinned order)
# ---------------------------------------------------------------------------

def compute_exposure(back_payments_cents, quarters_outstanding):
    base = int(back_payments_cents)
    if base < 10000000:
        rate = Decimal("0.10")
    elif base < 100000000:
        rate = Decimal("0.20")
    else:
        rate = Decimal("0.40")
    penalty = int((Decimal(base) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    interest = int(
        (Decimal(base + penalty) * Decimal("0.05") * Decimal(int(quarters_outstanding))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return base + penalty + interest


# ---------------------------------------------------------------------------
# lifetime reconciliation
# ---------------------------------------------------------------------------

def reconcile_lifetime(contractor_id):
    contractor = store.contractors.get(contractor_id)
    if contractor is None:
        return
    total = 0
    for f in store.filings.values():
        if f["contractor_id"] == contractor_id and f["status"] in ("SUBMITTED", "ACCEPTED"):
            total += f["signed_amount_cents"]
    if contractor["lifetime_reported_cents"] != total:
        contractor["lifetime_reported_cents"] = total
        touch(contractor)


# ---------------------------------------------------------------------------
# standing recompute (WATCH restore / revocation downgrade)
# ---------------------------------------------------------------------------

def maybe_restore_standing(contractor_id):
    contractor = store.contractors.get(contractor_id)
    if contractor is None or contractor["standing_status"] != "WATCH":
        return
    for a in store.audits.values():
        if a["contractor_id"] == contractor_id and a["open_action_count"] > 0:
            return
    contractor["standing_status"] = "GOOD_STANDING"
    touch(contractor)


def downgrade_standing_on_revoke(contractor_id):
    contractor = store.contractors.get(contractor_id)
    if contractor is None:
        return
    if contractor["standing_status"] == "GOOD_STANDING":
        contractor["standing_status"] = "WATCH"
        touch(contractor)


# ---------------------------------------------------------------------------
# exception grant helpers
# ---------------------------------------------------------------------------

def active_unexpired_grant(engagement_id):
    """Return (has_any_grant, has_active_unexpired_grant)."""
    any_grant = False
    active = False
    for g in store.exceptions.values():
        if g["engagement_id"] != engagement_id:
            continue
        lazy_expire_grant(g)
        if g["status"] == "ACTIVE":
            any_grant = True
            active = True
        elif g["status"] == "EXPIRED":
            any_grant = True
    return any_grant, active


def require_high_tier_exception(engagement):
    if engagement.get("risk_tier") != "HIGH":
        return
    grants = [g for g in store.exceptions.values() if g["engagement_id"] == engagement["id"]]
    if not grants:
        raise ApiError(ERR_EXCEPTION_REQUIRED, 422, "HIGH risk tier requires an ACTIVE ExceptionGrant")
    any_active = False
    any_expired = False
    for g in grants:
        lazy_expire_grant(g)
        if g["status"] == "ACTIVE":
            any_active = True
        elif g["status"] == "EXPIRED":
            any_expired = True
    if any_active:
        return
    if any_expired:
        raise ApiError(ERR_EXCEPTION_EXPIRED, 422, "ExceptionGrant has expired")
    raise ApiError(ERR_EXCEPTION_REQUIRED, 422, "HIGH risk tier requires an ACTIVE ExceptionGrant")
