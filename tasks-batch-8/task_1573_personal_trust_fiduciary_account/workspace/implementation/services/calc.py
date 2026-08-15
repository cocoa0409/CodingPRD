"""Business calculations: trustee fees, receipt allocation, IPS drift,
committee quorum, share reallocation, DNI, final distribution waterfall,
statement totals. All money is integer cents; Decimal + ROUND_HALF_UP."""

from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
import serialize
from services import workflow

D0 = Decimal("0")
CENT = Decimal("1")
TWO_DP = Decimal("0.01")

TIER1_CAP = Decimal(100000000)
TIER2_SPAN = Decimal(200000000)
TIER3_FLOOR = Decimal(300000000)
TIER1_RATE = Decimal("0.01")
TIER2_RATE = Decimal("0.0075")
TIER3_RATE = Decimal("0.005")
MIN_QUARTERLY_FEE_CENTS = 125000
EXEMPTION_CENTS = 30000
QUORUM = 3


def rhu(value, places=CENT):
    """Round half up to the given Decimal quantum."""
    return value.quantize(places, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- trustee fee

def compute_fee_amounts(base_cents):
    """trustee_fee_assessment: tiered annual fee, quarterly, floor, split."""
    b = Decimal(base_cents)
    tier1 = min(b, TIER1_CAP) * TIER1_RATE
    tier2 = min(max(b - TIER1_CAP, D0), TIER2_SPAN) * TIER2_RATE
    tier3 = max(b - TIER3_FLOOR, D0) * TIER3_RATE
    annual_exact = tier1 + tier2 + tier3
    annual_fee_cents = int(rhu(annual_exact))
    quarterly = int(rhu(annual_exact / Decimal(4)))
    assessed = max(quarterly, MIN_QUARTERLY_FEE_CENTS)
    income_portion = int(rhu(Decimal(assessed) * Decimal("0.5")))
    principal_portion = assessed - income_portion
    return {
        "base_market_value_cents": base_cents,
        "annual_fee_cents": annual_fee_cents,
        "assessed_fee_cents": assessed,
        "income_portion_cents": income_portion,
        "principal_portion_cents": principal_portion,
    }


def fee_base(trust_id, variant, period_end_str):
    """PROVISIONAL: current TMV. FINAL: holdings repriced at latest observation
    with priced_at <= period_end 23:59:59Z (creation price counts), plus the
    currently posted cash balances."""
    if variant == "PROVISIONAL":
        return serialize.total_market_value(trust_id)
    end_date = date.fromisoformat(period_end_str)
    cutoff = datetime.combine(end_date, time(23, 59, 59), tzinfo=timezone.utc)
    total = 0
    for h in db.holdings.values():
        if h["trust_id"] != trust_id:
            continue
        best_price = None
        best_dt = None
        for obs_dt, obs_price in h["price_history"]:
            if obs_dt <= cutoff and (best_dt is None or obs_dt > best_dt):
                best_dt, best_price = obs_dt, obs_price
        if best_price is not None:
            total += h["units"] * best_price
    total += serialize.income_balance(trust_id) + serialize.principal_balance(trust_id)
    return total


# ---------------------------------------------------------- receipt allocation

RECEIPT_TYPES = {
    "INITIAL_FUNDING", "INTEREST", "ORDINARY_DIVIDEND", "RENTAL_INCOME",
    "MINERAL_ROYALTY", "CAPITAL_GAIN_DISTRIBUTION", "SALE_PROCEEDS",
}


def classify_receipt(receipt_type, amount_cents):
    """Returns list of (bucket, amount). Split receipts: INCOME row first,
    PRINCIPAL row second; rounding remainder lands in PRINCIPAL."""
    a = Decimal(amount_cents)
    if receipt_type in ("INITIAL_FUNDING", "CAPITAL_GAIN_DISTRIBUTION", "SALE_PROCEEDS"):
        return [("PRINCIPAL", amount_cents)]
    if receipt_type in ("INTEREST", "ORDINARY_DIVIDEND"):
        return [("INCOME", amount_cents)]
    if receipt_type == "RENTAL_INCOME":
        income = int(rhu(a * Decimal("0.90")))
        return [("INCOME", income), ("PRINCIPAL", amount_cents - income)]
    if receipt_type == "MINERAL_ROYALTY":
        income = int(rhu(a * Decimal("0.10")))
        return [("INCOME", income), ("PRINCIPAL", amount_cents - income)]
    return []


# --------------------------------------------------------------- IPS drift

def _active_policy(trust_id):
    for p in db.policies.values():
        if p["trust_id"] == trust_id and p["status"] == "ACTIVE":
            return p
    return None


def _class_market_value(trust_id, asset_class):
    return sum(h["units"] * h["unit_price_cents"] for h in db.holdings.values()
               if h["trust_id"] == trust_id and h["asset_class"] == asset_class)


def _targets(policy, asset_class):
    if asset_class == "EQUITY":
        return (Decimal(str(policy["equity_target_pct"])),
                Decimal(str(policy["equity_band_pct"])))
    return (Decimal(str(policy["fixed_income_target_pct"])),
            Decimal(str(policy["fixed_income_band_pct"])))


def current_weight(trust_id, asset_class, policy):
    """Unrounded raw ratio, or None when TMV == 0."""
    tmv = serialize.total_market_value(trust_id)
    if tmv == 0:
        return None
    return Decimal(_class_market_value(trust_id, asset_class)) / Decimal(tmv)


def within_band(raw, target, band):
    """Inclusive band check used by resolve."""
    lower = (target - band) / Decimal(100)
    upper = (target + band) / Decimal(100)
    return lower <= raw <= upper


def run_drift_check(trust):
    """ips_drift_measurement. Returns (opened_count, opened_ids).
    No-op without an ACTIVE IPS or when TMV == 0. Creates or updates-in-place
    one non-RESOLVED review per (trust, class); a newly created CRITICAL review
    suspends an ACTIVE trust (version bump per the suspend transition)."""
    trust_id = trust["id"]
    policy = _active_policy(trust_id)
    if policy is None:
        return 0, []
    tmv = serialize.total_market_value(trust_id)
    if tmv == 0:
        return 0, []
    opened_ids = []
    for asset_class in ("EQUITY", "FIXED_INCOME"):
        target, band = _targets(policy, asset_class)
        raw = Decimal(_class_market_value(trust_id, asset_class)) / Decimal(tmv)
        over_limit = (target + band) / Decimal(100)
        under_limit = (target - band) / Decimal(100)
        if raw > over_limit:
            direction = "OVERWEIGHT"
            band_limit = target + band
            critical = raw > (target + Decimal(2) * band) / Decimal(100)
        elif raw < under_limit:
            direction = "UNDERWEIGHT"
            band_limit = target - band
            critical = False  # PRD: CRITICAL only when OVERWEIGHT beyond 2*band
        else:
            continue  # within band (equality at the edge is NOT a breach)
        measured = float(rhu(raw * Decimal(100), TWO_DP))
        severity = "CRITICAL" if critical else "STANDARD"
        existing = None
        for r in db.reviews.values():
            if (r["trust_id"] == trust_id and r["asset_class"] == asset_class
                    and r["status"] != "RESOLVED"):
                existing = r
                break
        if existing is not None:
            changed = (existing["direction"] != direction
                       or existing["measured_weight_pct"] != measured
                       or existing["band_limit_pct"] != float(band_limit)
                       or existing["severity"] != severity)
            existing["direction"] = direction
            existing["measured_weight_pct"] = measured
            existing["band_limit_pct"] = float(band_limit)
            existing["severity"] = severity
            if changed:
                workflow.touch(existing)
        else:
            review = workflow.new_entity()
            review.update({
                "trust_id": trust_id,
                "investment_policy_statement_id": policy["id"],
                "asset_class": asset_class,
                "direction": direction,
                "measured_weight_pct": measured,
                "band_limit_pct": float(band_limit),
                "severity": severity,
                "status": "OPEN",
                "remediation_note": None,
                "resolved_at": None,
            })
            db.reviews[review["id"]] = review
            opened_ids.append(review["id"])
            if severity == "CRITICAL" and trust["status"] == "ACTIVE":
                trust["status"] = "SUSPENDED"
                workflow.bump_trust(trust)
    return len(opened_ids), opened_ids


def has_overweight_block(trust_id, asset_class):
    for r in db.reviews.values():
        if (r["trust_id"] == trust_id and r["asset_class"] == asset_class
                and r["status"] != "RESOLVED" and r["direction"] == "OVERWEIGHT"):
            return True
    return False


# -------------------------------------------------------- committee quorum

def recount_tallies(request):
    approve = decline = abstain = 0
    for v in db.votes.values():
        if v["distribution_request_id"] != request["id"]:
            continue
        if v["vote"] == "APPROVE":
            approve += 1
        elif v["vote"] == "DECLINE":
            decline += 1
        else:
            abstain += 1
    request["approve_count"] = approve
    request["decline_count"] = decline
    request["abstain_count"] = abstain
    return approve, decline, abstain


# -------------------------------------------------------- share reallocation

def reallocate_shares(deceased):
    """Largest-remainder apportionment of the deceased's share over the ACTIVE
    survivors of the same class. Ties break by created_at ASC (never by id)."""
    cls = deceased["beneficiary_class"]
    survivors = [b for b in db.beneficiaries.values()
                 if b["trust_id"] == deceased["trust_id"]
                 and b["beneficiary_class"] == cls
                 and b["status"] == "ACTIVE"
                 and b["id"] != deceased["id"]]
    if not survivors:
        return
    d = deceased["share_bps"]
    survivors.sort(key=lambda b: (b["created_at"], b["_seq"]))
    s = sum(b["share_bps"] for b in survivors)
    if s <= 0 or d <= 0:
        return
    deceased["share_bps"] = 0
    fracs = []
    floors_sum = 0
    for b in survivors:
        raw = Decimal(d) * Decimal(b["share_bps"]) / Decimal(s)
        floor = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
        b["share_bps"] += floor
        floors_sum += floor
        fracs.append((raw - Decimal(floor), b))
    leftover = d - floors_sum
    # distribute one bp at a time to largest fractional remainders
    order = sorted(fracs, key=lambda t: (-t[0], t[1]["created_at"], t[1]["_seq"]))
    for i in range(leftover):
        order[i][1]["share_bps"] += 1
    for b in survivors:
        workflow.touch(b)


# ------------------------------------------------------------- tax (Form 1041)

def tax_year_window(tax_year):
    return date(tax_year, 1, 1), date(tax_year, 12, 31)


def _entries_in_window(trust_id, start, end):
    out = []
    for e in db.ledger_entries.values():
        if e["trust_id"] != trust_id:
            continue
        vd = date.fromisoformat(e["value_date"])
        if start <= vd <= end:
            out.append(e)
    return out


def compute_dni(trust_id, tax_year):
    """Pinned sequence: gross income (positive INCOME RECEIPT rows) minus
    income expenses (abs of FEE/INCOME rows)."""
    start, end = tax_year_window(tax_year)
    rows = _entries_in_window(trust_id, start, end)
    gross = sum(e["amount_cents"] for e in rows
                if e["bucket"] == "INCOME" and e["entry_kind"] == "RECEIPT"
                and e["amount_cents"] > 0)
    expenses = abs(sum(e["amount_cents"] for e in rows
                       if e["bucket"] == "INCOME" and e["entry_kind"] == "FEE"))
    return gross - expenses


def distributions_paid(trust_id, tax_year):
    start, end = tax_year_window(tax_year)
    return abs(sum(e["amount_cents"] for e in _entries_in_window(trust_id, start, end)
                   if e["entry_kind"] == "DISTRIBUTION"))


def elected_65day_cap(trust_id, tax_year):
    start = date(tax_year + 1, 1, 1)
    end = date(tax_year + 1, 3, 6)
    return abs(sum(e["amount_cents"] for e in _entries_in_window(trust_id, start, end)
                   if e["entry_kind"] == "DISTRIBUTION"))


# ------------------------------------------------------ final distribution

def build_distribution_lines(trust_id, pool_cents, beneficiary_class):
    """Per-line round-half-up first, then reconcile the delta onto the largest
    share (tie: created_at ASC, never id). Lines ordered created_at ASC."""
    members = [b for b in db.beneficiaries.values()
               if b["trust_id"] == trust_id
               and b["beneficiary_class"] == beneficiary_class
               and b["share_bps"] > 0]
    members.sort(key=lambda b: (b["created_at"], b["_seq"]))
    lines = []
    for b in members:
        amount = int(rhu(Decimal(pool_cents) * Decimal(b["share_bps"]) / Decimal(10000)))
        lines.append({
            "beneficiary_id": b["id"],
            "beneficiary_class": beneficiary_class,
            "amount_cents": amount,
        })
    if lines:
        delta = pool_cents - sum(l["amount_cents"] for l in lines)
        if delta != 0:
            share_of = {b["id"]: b["share_bps"] for b in members}
            # largest share; tie-break by created_at ASC (members already sorted)
            target = None
            for b in members:
                if target is None or share_of[b["id"]] > share_of[target["id"]]:
                    target = b
            for l in lines:
                if l["beneficiary_id"] == target["id"]:
                    l["amount_cents"] += delta
                    break
    return lines


# --------------------------------------------------------- statement totals

def statement_totals(trust, fiscal_year):
    start, end = workflow.fiscal_window(trust, fiscal_year)
    rows = [e for e in db.ledger_entries.values() if e["trust_id"] == trust["id"]]
    before = [e for e in rows if date.fromisoformat(e["value_date"]) < start]
    inside = [e for e in rows if start <= date.fromisoformat(e["value_date"]) <= end]

    def bucket_sum(entries, bucket):
        return sum(e["amount_cents"] for e in entries if e["bucket"] == bucket)

    def positive_sum(entries, bucket):
        return sum(e["amount_cents"] for e in entries
                   if e["bucket"] == bucket and e["amount_cents"] > 0)

    opening_i = bucket_sum(before, "INCOME")
    opening_p = bucket_sum(before, "PRINCIPAL")
    neg_non_df = sum(e["amount_cents"] for e in inside
                     if e["amount_cents"] < 0
                     and e["entry_kind"] not in ("DISTRIBUTION", "FEE"))
    fees = sum(e["amount_cents"] for e in inside if e["entry_kind"] == "FEE")
    dists = sum(e["amount_cents"] for e in inside if e["entry_kind"] == "DISTRIBUTION")
    return {
        "opening_income_cents": opening_i,
        "opening_principal_cents": opening_p,
        "receipts_income_cents": positive_sum(inside, "INCOME"),
        "receipts_principal_cents": positive_sum(inside, "PRINCIPAL"),
        "disbursements_cents": abs(neg_non_df),
        "fees_cents": abs(fees),
        "distributions_cents": abs(dists),
        "closing_income_cents": opening_i + bucket_sum(inside, "INCOME"),
        "closing_principal_cents": opening_p + bucket_sum(inside, "PRINCIPAL"),
    }


# ------------------------------------------------------------- purpose gates

PURPOSE_BY_STANDARD = {
    "HEMS": {"HEALTH", "EDUCATION", "MAINTENANCE", "SUPPORT"},
    "SUPPORT": {"HEALTH", "MAINTENANCE", "SUPPORT"},
    "DISCRETIONARY": {"HEALTH", "EDUCATION", "MAINTENANCE", "SUPPORT",
                      "TRAVEL", "LUXURY", "OTHER"},
}


def purpose_permitted(standard, category):
    return category in PURPOSE_BY_STANDARD.get(standard, set())


def reservation_waterfall(allocation_source, amount, avail_income, avail_principal):
    """Returns (income_portion, principal_portion) or None if it does not fit."""
    if allocation_source == "INCOME_ONLY":
        if amount <= avail_income:
            return amount, 0
        return None
    if allocation_source == "PRINCIPAL_ONLY":
        if amount <= avail_principal:
            return 0, amount
        return None
    if allocation_source == "INCOME_FIRST":
        income = min(amount, avail_income)
        remainder = amount - income
        if remainder <= avail_principal:
            return income, remainder
        return None
    if allocation_source == "PRINCIPAL_FIRST":
        principal = min(amount, avail_principal)
        remainder = amount - principal
        if remainder <= avail_income:
            return remainder, principal
        return None
    return None
