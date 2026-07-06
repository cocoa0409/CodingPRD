"""Domain calculations: conformance score, risk exposure, invoice, SLA, credit."""
from decimal import Decimal, ROUND_HALF_UP

SEVERITY_WEIGHT = {"CRITICAL": 10, "SERIOUS": 5, "MODERATE": 2, "MINOR": 1}

SLA_HOURS = {"CRITICAL": 72, "SERIOUS": 168, "MODERATE": 720, "MINOR": 2160}

TIER_FEE = {"SCAN": 9900, "MONITOR": 24900, "MANAGED": 49900}
PER_PAGE = {"SCAN": 0, "MONITOR": 5, "MANAGED": 12}

RISK_OPEN_SET = {"OPEN", "IN_REMEDIATION", "RETEST_PENDING", "REOPENED"}
ACTIVE_DEMAND_STATUSES = {"RECEIVED", "RESPONDING", "ESCALATED"}

CREDIT = {
    "WCAG_AA_FULL": 0,
    "WCAG_AA_PARTIAL": 2500,
    "WCAG_A": 5000,
    "NON_CONFORMANT": 10000,
}


def round_half_up_2dp(value):
    """Round a numeric value to 2 decimal places, ROUND_HALF_UP. Returns float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def round_half_up_cents(value):
    """Round to whole cents (integer), ROUND_HALF_UP."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def conformance_score(findings, remediated_set):
    """Weighted conformance score over the scan's findings.

    findings: list of finding dicts (all the scan's findings, all statuses).
    remediated_set: set of statuses that count as passed.
    Returns float rounded half-up to 2dp.
    """
    total_weight = 0
    passed_weight = 0
    for f in findings:
        w = SEVERITY_WEIGHT[f["severity"]]
        total_weight += w
        if f["status"] in remediated_set:
            passed_weight += w
    if total_weight == 0:
        return 100.00
    raw = Decimal(100) * Decimal(passed_weight) / Decimal(total_weight)
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sla_due_at(completed_at, severity):
    """completed_at (aware datetime) + SLA hours for severity."""
    from datetime import timedelta
    return completed_at + timedelta(hours=SLA_HOURS[severity])


def is_overdue(finding, clock_now):
    sla = finding.get("sla_due_at")
    if sla is None:
        return False
    if finding["status"] in ("RESOLVED", "WONT_FIX_ACCEPTED"):
        return False
    return clock_now > sla


def overdue_days(finding, clock_now):
    """Floor whole days past sla_due_at; assumes finding is overdue."""
    sla = finding["sla_due_at"]
    delta_seconds = (clock_now - sla).total_seconds()
    return int(delta_seconds // 86400)


def risk_exposure(site_findings, site_has_active_demand, clock_now, open_set):
    """Compute risk exposure score per the CURRENT/PROJECTED variant.

    site_findings: findings whose open-set membership is decided by `open_set`
                   (already filtered to the relevant population for the variant).
    open_set: set of statuses considered "open" for counting C/S.
    Returns float rounded half-up to 2dp, capped at 100.
    """
    C = 0
    S = 0
    max_overdue_days = 0
    for f in site_findings:
        if f["status"] not in open_set:
            continue
        if f["severity"] == "CRITICAL":
            C += 1
        elif f["severity"] == "SERIOUS":
            S += 1
        if is_overdue(f, clock_now):
            d = overdue_days(f, clock_now)
            if d > max_overdue_days:
                max_overdue_days = d
    base = min(100, 8 * C + 3 * S)
    overdue_factor = 1 + min(1.0, 0.02 * max_overdue_days)
    legal_bump = 25 if site_has_active_demand else 0
    raw = Decimal(str(base)) * Decimal(str(overdue_factor)) + Decimal(legal_bump)
    capped = min(Decimal("100.0"), raw)
    return float(capped.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def discount(n):
    if n >= 10:
        return Decimal("0.15")
    if n >= 5:
        return Decimal("0.10")
    return Decimal("0.0")


def subscription_invoice(sites, tier):
    """Tiered per-site invoice; round per site then sum. Returns int cents."""
    n = len(sites)
    disc = discount(n)
    total = 0
    fee = TIER_FEE[tier]
    per_page = PER_PAGE[tier]
    for s in sites:
        raw = (Decimal(fee) + Decimal(per_page) * Decimal(s["audited_page_count"])) * (Decimal(1) - disc)
        per_site = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += per_site
    return total


def conformance_level(score):
    if score >= 95:
        return "WCAG_AA_FULL"
    if score >= 80:
        return "WCAG_AA_PARTIAL"
    if score >= 50:
        return "WCAG_A"
    return "NON_CONFORMANT"


def remediation_credit(level):
    return CREDIT[level]
