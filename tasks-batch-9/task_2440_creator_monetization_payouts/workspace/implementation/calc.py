"""All nine calculation rules (PRD 2.5, 3.1-3.9).

Money is signed integer cents throughout; rates are integer basis points.
Exact rationals are carried in Fraction and rounded exactly once, in the
direction the PRD names for that rule.
"""
from fractions import Fraction

from store import db, sort_rows

# ------------------------------------------------------------------ constants
BPS = 10000
BACKUP_WITHHOLDING_BPS = 2400
NRA_DEFAULT_BPS = 3000
TAX_FORM_VALIDITY_DAYS = 1095
STRIKE_ACTIVE_DAYS = 90
MIN_FOLLOWERS = 10000
MIN_WATCH_MINUTES_365D = 240000
MAX_EFFECTIVE_SHARE_BPS = 9000
APPEAL_MAX_ROUNDS = 2
MAX_PAYOUT_RETRIES = 2
FUND_GUARANTEED_FLOOR_CENTS = 5000

TREATY_FLOOR_BPS = {"GB": 0, "DE": 0, "IN": 1500, "JP": 1000}
SUITABILITY_MULT_BPS = {"GREEN": 10000, "YELLOW": 6000, "RED": 0}
MONETIZATION_STATE = {"GREEN": "MONETIZED", "YELLOW": "LIMITED", "RED": "DEMONETIZED"}

PAYOUT_FLAT_CENTS = {"BANK_TRANSFER": 200, "INSTANT_DEBIT": 100, "CHECK": 500}
PAYOUT_RATE_BPS = {"BANK_TRANSFER": 0, "INSTANT_DEBIT": 150, "CHECK": 0}
PAYOUT_FEE_CAP_CENTS = {"BANK_TRANSFER": 1500, "INSTANT_DEBIT": 4000, "CHECK": 500}

ACCRUAL_TYPES = ("ACCRUAL", "ACCRUAL_REVERSAL", "ACCRUAL_RESTORE")


# ------------------------------------------------------------------- rounding
def round_half_up(frac):
    whole = frac.numerator // frac.denominator
    if frac - whole >= Fraction(1, 2):
        return whole + 1
    return whole


def round_up(frac):
    whole = frac.numerator // frac.denominator
    return whole + 1 if frac > whole else whole


def floor_div(frac):
    return frac.numerator // frac.denominator


# ------------------------------------------------- calculation: balances (2.6)
def ledger_balance_cents(creator_id):
    return sum(e["amount_cents"] for e in db.ledger.values() if e["creator_id"] == creator_id)


def held_cents(creator_id):
    total = 0
    for inv in db.investigations.values():
        if inv["creator_id"] == creator_id and inv["state"] == "OPEN" and inv["hold_payouts"]:
            total += inv["hold_amount_cents"]
    return total


def statement_payable_cents(creator_id):
    total = 0
    for st in db.statements.values():
        if st["creator_id"] != creator_id:
            continue
        if st["status"] not in ("FINALIZED", "ADJUSTED"):
            continue
        if st["payout_id"] is not None:
            continue
        total += st["net_payable_cents"] - st["clawback_applied_cents"] + st["dispute_adjustment_cents"]
    return total


def available_balance_cents(creator):
    return (statement_payable_cents(creator["id"])
            + creator["fund_credit_balance_cents"]
            - held_cents(creator["id"]))


def balances(creator):
    cid = creator["id"]
    payable = statement_payable_cents(cid)
    held = held_cents(cid)
    return {
        "ledger_balance_cents": ledger_balance_cents(cid),
        "held_cents": held,
        "statement_payable_cents": payable,
        "available_balance_cents": payable + creator["fund_credit_balance_cents"] - held,
    }


# ------------------------------------- calculation: payout_state_resolution (2.7)
def resolve_payout_state(creator):
    cid = creator["id"]
    if creator["outstanding_clawback_cents"] > 0:
        return "ARREARS"
    for inv in db.investigations.values():
        if inv["creator_id"] == cid and inv["state"] == "OPEN" and inv["hold_payouts"]:
            return "HOLD"
    for po in db.payouts.values():
        if po["creator_id"] == cid and po["state"] in ("PENDING", "PROCESSING"):
            return "PAYOUT_IN_FLIGHT"
    return "ACCRUING"


def apply_payout_state(creator):
    state = resolve_payout_state(creator)
    if creator["payout_state"] != state:
        creator["payout_state"] = state
        db.touch(creator)
    return state


# --------------------------------- calculation: eligibility_evaluation (3.1)
def eligibility_evaluation(creator, at):
    if creator["active_strike_count"] >= 1:
        creator["eligibility_status"] = "SUSPENDED"
        creator["last_evaluation_failed_criteria"] = ["POLICY_COMPLIANCE"]
    else:
        failed = []
        if creator["follower_count"] < MIN_FOLLOWERS:
            failed.append("FOLLOWER_MINIMUM")
        if creator["watch_time_minutes_365d"] < MIN_WATCH_MINUTES_365D:
            failed.append("WATCH_TIME_MINIMUM")
        creator["last_evaluation_failed_criteria"] = failed
        creator["eligibility_status"] = "INELIGIBLE" if failed else "ELIGIBLE"
    creator["evaluation_count"] += 1
    creator["last_evaluated_at"] = at
    db.touch(creator)
    return creator


# ------------------------------ calculation: withholding_rate_resolution (3.2)
def current_tax_profile(creator_id):
    candidates = [p for p in db.tax_profiles.values()
                  if p["creator_id"] == creator_id and p["status"] != "SUPERSEDED"]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]), reverse=True)
    return candidates[0]


def profile_rate_bps(profile):
    if profile is None or profile["status"] != "VERIFIED":
        return BACKUP_WITHHOLDING_BPS
    if profile["form_type"] == "W9":
        return 0 if profile["tin_provided"] else BACKUP_WITHHOLDING_BPS
    # W8BEN
    if not profile["treaty_claimed"] or not profile["tin_provided"]:
        return NRA_DEFAULT_BPS
    country = profile["country_code"]
    if country not in TREATY_FLOOR_BPS:
        return NRA_DEFAULT_BPS
    claimed = profile["treaty_rate_bps"] or 0
    return max(claimed, TREATY_FLOOR_BPS[country])


def withholding_rate_resolution(creator_id):
    return profile_rate_bps(current_tax_profile(creator_id))


def resolve_profile_rate(profile):
    """Rate written onto a profile on every status change of that profile."""
    return profile_rate_bps(profile)


# ----------------------------------- calculation: revenue_share_split (3.3)
def tier_bonus_bps(lifetime_paid_cents):
    if lifetime_paid_cents < 100000:
        return 0
    if lifetime_paid_cents < 1000000:
        return 200
    if lifetime_paid_cents < 10000000:
        return 400
    return 600


def revenue_share_split(gross_amount_cents, product, creator, rating, variant):
    """Returns (effective_share_bps, creator_share_cents, status)."""
    base = product["creator_share_bps"]
    bonus = tier_bonus_bps(creator["lifetime_paid_cents"])
    capped = min(base + bonus, MAX_EFFECTIVE_SHARE_BPS)
    multiplier = SUITABILITY_MULT_BPS[rating] if product["suitability_sensitive"] else BPS
    effective = floor_div(Fraction(capped * multiplier, BPS))
    share = round_half_up(Fraction(gross_amount_cents * effective, BPS))
    if variant == "RESCORE_ON_RERATING" and multiplier == 0:
        return effective, 0, "REVERSED"
    if share < product["min_payable_cents"]:
        return effective, 0, "BELOW_MINIMUM"
    return effective, share, "ACCRUED"


# ------------------------------- calculation: statement_withholding (3.5/3.6)
def accrual_basis_cents(event_id, cutoff):
    total = 0
    for entry in db.ledger.values():
        if entry["source_entity"] != "REVENUE_EVENT" or entry["source_id"] != event_id:
            continue
        if entry["entry_type"] not in ACCRUAL_TYPES:
            continue
        if cutoff is not None and entry["occurred_at"] > cutoff:
            continue
        total += entry["amount_cents"]
    return total


def statement_event_set(statement, cutoff):
    rows = [e for e in db.revenue_events.values()
            if e["period_id"] == statement["period_id"]
            and e["creator_id"] == statement["creator_id"]]
    rows = sort_rows(rows, lambda r: (r["occurred_at"], r["created_at"]))
    out = []
    for event in rows:
        basis = accrual_basis_cents(event["id"], cutoff)
        if basis > 0:
            out.append((event, basis))
    return out


def statement_withholding(statement, variant, cutoff):
    """Writes withholding_rate_bps, withholding_cents, net_payable_cents."""
    rate = withholding_rate_resolution(statement["creator_id"])
    statement["withholding_rate_bps"] = rate
    if variant == "PROVISIONAL":
        withheld = round_half_up(Fraction(statement["creator_share_cents"] * rate, BPS))
    else:
        withheld = 0
        for _event, basis in statement_event_set(statement, cutoff):
            withheld += round_half_up(Fraction(basis * rate, BPS))
    statement["withholding_variant"] = variant
    statement["withholding_cents"] = withheld
    statement["net_payable_cents"] = statement["creator_share_cents"] - withheld
    return withheld


# --------------------------------- calculation: payout_fee_and_amount (3.7)
def volume_tier_bps(payable):
    if payable < 50000:
        return 10000
    if payable < 500000:
        return 7500
    return 5000


def payout_fee_cents(payable, method):
    tier = volume_tier_bps(payable)
    pct = round_up(Fraction(payable * PAYOUT_RATE_BPS[method], BPS))
    gross_fee = PAYOUT_FLAT_CENTS[method] + pct
    scaled = round_up(Fraction(gross_fee * tier, BPS))
    capped = min(scaled, PAYOUT_FEE_CAP_CENTS[method])
    clamped = min(capped, payable - 1)
    return max(clamped, 0)


# ------------------------------------- calculation: clawback_waterfall (3.8)
def clawback_buckets(creator_id):
    rows = [st for st in db.statements.values()
            if st["creator_id"] == creator_id
            and st["status"] in ("FINALIZED", "ADJUSTED")
            and st["payout_id"] is None]
    return order_statements(rows)


def order_statements(rows):
    def key(st):
        period = db.periods.get(st["period_id"])
        return (period["period_start"] if period else st["created_at"], st["created_at"])
    return sort_rows(rows, key)


def substantiation_waterfall(creator_id, base_cents):
    """Single pass, no revisiting.  Returns (takes, remaining)."""
    remaining = base_cents
    takes = []
    for st in clawback_buckets(creator_id):
        if remaining <= 0:
            continue
        capacity = st["net_payable_cents"] - st["clawback_applied_cents"] + st["dispute_adjustment_cents"]
        if capacity < 0:
            capacity = 0
        taken = min(remaining, capacity)
        if taken > 0:
            takes.append((st, taken))
            remaining -= taken
    return takes, remaining


# ------------------------------------------ calculation: fund_allocation (3.9)
def fund_candidates(fund):
    rows = [c for c in db.creators.values()
            if c["eligibility_status"] == "ELIGIBLE"
            and c["watch_time_minutes_365d"] >= fund["min_watch_time_minutes"]
            and c["watch_time_minutes_365d"] > 0]
    rows.sort(key=lambda c: (-c["watch_time_minutes_365d"], c["created_at"], c["_seq"]))
    return rows


def _remainder_pass(amounts, pool_total, cap):
    remainder = pool_total - sum(amounts)
    for i in range(len(amounts)):
        if remainder <= 0:
            break
        if amounts[i] < cap:
            amounts[i] += 1
            remainder -= 1
    return amounts


def fund_allocation(fund, candidates):
    """Returns a list of (creator, rank, amount_cents) for positive amounts."""
    pool = fund["total_pool_cents"]
    cap = fund["max_allocation_cents"]
    total_wt = sum(c["watch_time_minutes_365d"] for c in candidates)
    amounts = []
    if fund["methodology"] == "PRO_RATA_WATCH_TIME":
        for cand in candidates:
            provisional = floor_div(Fraction(pool * cand["watch_time_minutes_365d"], total_wt))
            amounts.append(min(provisional, cap))
        amounts = _remainder_pass(amounts, pool, cap)
    else:
        floor_c = FUND_GUARANTEED_FLOOR_CENTS
        n = len(candidates)
        if pool < n * floor_c:
            left = pool
            for _cand in candidates:
                take = min(floor_c, left)
                amounts.append(take)
                left -= take
        else:
            surplus = pool - n * floor_c
            for cand in candidates:
                share = floor_div(Fraction(surplus * cand["watch_time_minutes_365d"], total_wt))
                amounts.append(min(floor_c + share, cap))
            amounts = _remainder_pass(amounts, pool, cap)
    out = []
    for index, cand in enumerate(candidates):
        if amounts[index] > 0:
            out.append((cand, index + 1, amounts[index]))
    return out
