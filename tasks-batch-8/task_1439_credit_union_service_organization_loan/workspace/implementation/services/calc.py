"""Deterministic server-side calculations (PRD sections 2.5, 3.x).

Money is integer cents; all derived monetary figures use Decimal and are
rounded half up to whole cents unless a rule says otherwise. Regulatory caps
are rounded DOWN to whole cents before integer comparison.
"""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

YEAR_DAYS = 360
LATE_PENALTY_DAILY_BPS = 3
BASE_CAP_PCT = Decimal("0.01")
EXTENDED_CAP_PCT = Decimal("0.03")
WELL_CAPITALIZED_MIN_RATIO = Decimal("0.07")


def round_half_up(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_down(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_DOWN))


# ---------------------------------------------------------------------------
# Day-count conventions (PRD 2.5): inclusive windows over calendar dates
# ---------------------------------------------------------------------------

def day_count(convention, start_date, end_date):
    """Inclusive day count between two dates under the agreement convention."""
    if end_date < start_date:
        return 0
    if convention == "ACT_360":
        return (end_date - start_date).days + 1
    # THIRTY_360: each full calendar month counts 30 days; a partial month
    # counts min(actual calendar days in period within that month, 30).
    total = 0
    cur = start_date
    while cur <= end_date:
        last_dom = calendar.monthrange(cur.year, cur.month)[1]
        month_end = cur.replace(day=last_dom)
        seg_end = min(month_end, end_date)
        actual = (seg_end - cur).days + 1
        if cur.day == 1 and seg_end == month_end:
            total += 30
        else:
            total += min(actual, 30)
        cur = seg_end + timedelta(days=1)
    return total


def accrued_interest(base_cents, rate_bps, days):
    """round_half_up(base * rate_bps/10000 * days/360)"""
    if days <= 0 or base_cents <= 0:
        return 0
    amt = Decimal(base_cents) * Decimal(rate_bps) * Decimal(days) / Decimal(10000 * YEAR_DAYS)
    return round_half_up(amt)


def servicing_fee(beginning_outstanding_cents, fee_bps, days):
    if days <= 0 or beginning_outstanding_cents <= 0:
        return 0
    amt = (
        Decimal(beginning_outstanding_cents)
        * Decimal(fee_bps)
        * Decimal(days)
        / Decimal(10000 * YEAR_DAYS)
    )
    return round_half_up(amt)


def late_penalty(interest_portion_cents, principal_portion_cents, days_late):
    if days_late <= 0:
        return 0
    amt = (
        Decimal(interest_portion_cents + principal_portion_cents)
        * Decimal(LATE_PENALTY_DAILY_BPS)
        * Decimal(days_late)
        / Decimal(10000)
    )
    return round_half_up(amt)


# ---------------------------------------------------------------------------
# Regulatory caps (PRD 3.2): caps rounded down; comparisons on integers
# ---------------------------------------------------------------------------

def investment_caps(total_assets_cents):
    base = round_down(Decimal(total_assets_cents) * BASE_CAP_PCT)
    extended = round_down(Decimal(total_assets_cents) * EXTENDED_CAP_PCT)
    return base, extended


def net_worth_ratio(cu):
    if not cu["total_assets_cents"]:
        return Decimal(0)
    return Decimal(cu["net_worth_cents"]) / Decimal(cu["total_assets_cents"])


def concentration_cap(net_worth_cents, cap_pct):
    return round_down(Decimal(net_worth_cents) * Decimal(str(cap_pct)))


# ---------------------------------------------------------------------------
# Loss share allocation (PRD 3.7): per-share round-half-up, then residual one
# cent at a time by fractional part DESC / created_at ASC; cap at outstanding
# with pro-rata redistribution among uncapped certificates.
# ---------------------------------------------------------------------------

def _fractional(raw):
    return raw - int(raw.to_integral_value(rounding=ROUND_DOWN))


def _distribute(loss_amount, certs, weights):
    """Certs: list of dicts; weights: {cert_id: int}. Returns {cert_id: cents}."""
    total_weight = sum(weights.values())
    raws = {}
    shares = {}
    for c in certs:
        raw = Decimal(loss_amount) * Decimal(weights[c["id"]]) / Decimal(total_weight)
        raws[c["id"]] = raw
        shares[c["id"]] = round_half_up(raw)
    residual = loss_amount - sum(shares.values())
    if residual:
        sign = 1 if residual > 0 else -1
        order = sorted(
            certs,
            key=lambda c: (-_fractional(raws[c["id"]]), c["created_at"], c["_seq"]),
        )
        i = 0
        while residual != 0 and order:
            cid = order[i % len(order)]["id"]
            shares[cid] += sign
            residual -= sign
            i += 1
    return shares


def allocate_loss(loss_amount, certs, basis):
    """Returns (allocations list, per-cert dict). certs are the eligible
    certificates (status ACTIVE or EXCEPTION) in created order."""
    def weight(c):
        return (
            c["outstanding_principal_cents"]
            if basis == "OUTSTANDING"
            else c["committed_amount_cents"]
        )

    weights = {c["id"]: weight(c) for c in certs}
    shares = _distribute(loss_amount, certs, weights)

    # Cap each share at the certificate's outstanding principal and
    # redistribute the excess pro-rata among uncapped certificates, repeating.
    capped = set()
    while True:
        excess = 0
        for c in certs:
            cid = c["id"]
            if cid not in capped and shares[cid] > c["outstanding_principal_cents"]:
                excess += shares[cid] - c["outstanding_principal_cents"]
                shares[cid] = c["outstanding_principal_cents"]
                capped.add(cid)
        if excess == 0:
            break
        uncapped = [c for c in certs if c["id"] not in capped]
        uw = {c["id"]: weight(c) for c in uncapped}
        if not uncapped or sum(uw.values()) <= 0:
            break  # nothing left that can absorb; conservation impossible
        extra = _distribute(excess, uncapped, uw)
        for cid, amt in extra.items():
            shares[cid] += amt

    allocations = [
        {"certificate_id": c["id"], "allocated_cents": shares[c["id"]]} for c in certs
    ]
    return allocations, shares
