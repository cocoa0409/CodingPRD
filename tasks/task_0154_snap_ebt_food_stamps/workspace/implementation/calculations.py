"""Core calculations: net income, monthly allotment, EA, eligible amount, fraud score, abawd status."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import List, Dict, Any

from common import STORE, round_half_up_int, round_half_up_2, parse_iso8601


# Constants from scaffold (calc_net_monthly_income)
STANDARD_DEDUCTION_TABLE = {1: 19300, 2: 19300, 3: 19300, 4: 20600, 5: 24100, 6: 27600}
DEPENDENT_CARE_CAP_CENTS = 25000
EXCESS_SHELTER_CAP_CENTS = 67200

# Constants for monthly allotment
MAX_ALLOTMENT_TABLE = {1: 29100, 2: 53500, 3: 76600, 4: 97300, 5: 115500, 6: 138600}
MINIMUM_BENEFIT_CENTS = 2300
GROSS_INCOME_LIMIT_TABLE = {1: 162200, 2: 218800, 3: 275400, 4: 332000, 5: 388600, 6: 445200}
NET_INCOME_LIMIT_TABLE = {1: 124800, 2: 168300, 3: 211800, 4: 255400, 5: 298900, 6: 342400}

EA_FLOOR_CENTS = 9500
ROLLING_WINDOW_DAYS = 30
WEIGHT_A = Decimal("0.50")
WEIGHT_B = Decimal("0.30")
WEIGHT_C = Decimal("0.20")

INELIGIBLE_CATEGORIES = {"NON_FOOD", "ALCOHOL", "TOBACCO"}
HOT_OR_COLD = {"HOT_PREPARED", "COLD_PREPARED"}


def _bracket(household_size: int) -> int:
    return max(1, min(household_size, 6))


def gross_income_limit(household_size: int) -> int:
    return GROSS_INCOME_LIMIT_TABLE[_bracket(household_size)]


def net_income_limit(household_size: int) -> int:
    return NET_INCOME_LIMIT_TABLE[_bracket(household_size)]


def max_allotment_for_size(household_size: int) -> int:
    return MAX_ALLOTMENT_TABLE[_bracket(household_size)]


def standard_deduction_for_size(household_size: int) -> int:
    return STANDARD_DEDUCTION_TABLE[_bracket(household_size)]


def age_years_truncated(date_of_birth_iso: str, clock_now) -> int:
    """Truncated integer years using 365.25 days/year per scaffold."""
    dob = parse_iso8601(date_of_birth_iso)
    delta_days = (clock_now - dob).total_seconds() / 86400.0
    return int(delta_days // 365.25)


def get_active_members(household_id: str) -> List[dict]:
    return [m for m in STORE.members.values()
            if m["household_id"] == household_id and m["status"] == "ACTIVE"]


def compute_household_size(household_id: str) -> int:
    return len(get_active_members(household_id))


def compute_gross_income_cents(household_id: str) -> int:
    return sum(m["earned_income_cents"] + m["unearned_income_cents"]
               for m in get_active_members(household_id))


def compute_has_elderly_or_disabled(household_id: str, clock_now) -> bool:
    for m in get_active_members(household_id):
        if m.get("is_disabled"):
            return True
        try:
            if age_years_truncated(m["date_of_birth"], clock_now) >= 60:
                return True
        except Exception:
            continue
    return False


def calc_net_monthly_income(household: dict) -> int:
    """Compute net monthly income per the documented algorithm with per-step rounding."""
    clock_now = STORE.clock.now
    actives = get_active_members(household["id"])
    if not actives:
        return 0

    gross = sum(m["earned_income_cents"] + m["unearned_income_cents"] for m in actives)
    earned = sum(m["earned_income_cents"] for m in actives)
    size = len(actives)

    standard_deduction = standard_deduction_for_size(size)
    earned_income_deduction = round_half_up_int(Decimal(earned) * Decimal("0.20"))
    dependent_care_deduction = min(household.get("dependent_care_expense_cents", 0), DEPENDENT_CARE_CAP_CENTS)

    adjusted_income = max(0, gross - standard_deduction - earned_income_deduction - dependent_care_deduction)

    half_adjusted = round_half_up_int(Decimal(adjusted_income) / Decimal(2))
    excess_shelter_raw = household.get("shelter_expense_cents", 0) - half_adjusted
    shelter_deduction_uncapped = max(0, excess_shelter_raw)

    has_eod = compute_has_elderly_or_disabled(household["id"], clock_now)
    if has_eod:
        shelter_deduction = shelter_deduction_uncapped
    else:
        shelter_deduction = min(shelter_deduction_uncapped, EXCESS_SHELTER_CAP_CENTS)

    net = max(0, adjusted_income - shelter_deduction)
    return net


def calc_monthly_allotment(household: dict) -> int:
    size = household.get("household_size", 0)
    if size == 0:
        return 0
    max_allot = max_allotment_for_size(size)
    expected_contribution = round_half_up_int(Decimal(household.get("net_monthly_income_cents", 0)) * Decimal("0.30"))
    raw_allotment = max(0, max_allot - expected_contribution)
    if size <= 2 and raw_allotment < MINIMUM_BENEFIT_CENTS:
        return MINIMUM_BENEFIT_CENTS
    return raw_allotment


def calc_emergency_allotment(household: dict) -> int:
    size = household.get("household_size", 0)
    if size == 0:
        size = 1
    max_allot = max_allotment_for_size(size)
    top_up = max(0, max_allot - household.get("monthly_allotment_cents", 0))
    return max(top_up, EA_FLOOR_CENTS)


def calc_eligible_amount(line_items: List[dict], merchant: dict, household: dict) -> int:
    eligible = 0
    hot_food_pilot = bool(merchant.get("hot_food_pilot"))
    has_eod = bool(household.get("has_elderly_or_disabled"))
    for item in line_items:
        cat = item.get("item_category")
        if cat in INELIGIBLE_CATEGORIES:
            continue
        if cat in HOT_OR_COLD:
            if not (hot_food_pilot and has_eod):
                continue
        unit_price = int(item.get("unit_price_cents", 0))
        qty = int(item.get("quantity", 0))
        eligible += unit_price * qty
    return eligible


# -----------------------------------------------------------------------------
# Fraud score
# -----------------------------------------------------------------------------

def _window_start(clock_now):
    return clock_now - timedelta(days=ROLLING_WINDOW_DAYS)


def calc_fraud_score(household: dict) -> float:
    clock_now = STORE.clock.now
    window_start = _window_start(clock_now)
    hid = household["id"]

    household_ledger = [e for e in STORE.ledger.values() if e["household_id"] == hid]

    # Signal A: rapid-balance-depletion ratio
    credits = []
    for e in household_ledger:
        if e["entry_type"] in ("REGULAR_ALLOTMENT", "EMERGENCY_ALLOTMENT"):
            credits.append(parse_iso8601(e["created_at"]))

    a_total = 0
    for e in household_ledger:
        if e["entry_type"] != "PURCHASE":
            continue
        e_dt = parse_iso8601(e["created_at"])
        if e_dt < window_start:
            continue
        # Must have a credit within 24h preceding the purchase
        for c_dt in credits:
            delta = e_dt - c_dt
            if timedelta(0) <= delta <= timedelta(hours=24):
                a_total += abs(int(e["amount_cents"]))
                break

    monthly_allotment_cents = household.get("monthly_allotment_cents", 0) or 0
    denom = max(1, monthly_allotment_cents)
    a_signal_raw = Decimal(a_total) / Decimal(denom)
    if a_signal_raw > Decimal("1.0"):
        a_signal = Decimal("1.0")
    else:
        a_signal = a_signal_raw

    # Get approved transactions within window for this household
    # Find card ids of this household
    hh_card_ids = {c["id"] for c in STORE.cards.values() if c["household_id"] == hid}
    approved_txns = []
    for t in STORE.transactions.values():
        if t["status"] != "APPROVED":
            continue
        if t["card_id"] not in hh_card_ids:
            continue
        if t.get("posted_at"):
            pdt = parse_iso8601(t["posted_at"])
            if pdt < window_start:
                continue
        approved_txns.append(t)

    total_tx = len(approved_txns)

    # Signal B: out-of-state merchant ratio
    # Note: scaffold says "merchant resolves to a state different from the household's state_code"
    # Merchant entity has no state_code in our scaffold — this is intentional, so we treat
    # all merchants as in-state (signal B = 0.0). The PRD references this signal but the
    # Merchant model has no state field defined, so we conservatively treat all txns as in-state.
    # If a `state_code` happens to be set on the merchant we'll honor it.
    oos_tx = 0
    hh_state = household.get("state_code")
    for t in approved_txns:
        merchant = STORE.merchants.get(t["merchant_id"])
        if merchant and merchant.get("state_code") and merchant["state_code"] != hh_state:
            oos_tx += 1
    b_signal = Decimal(0) if total_tx == 0 else Decimal(oos_tx) / Decimal(total_tx)

    # Signal C: even-amount clustering
    even_count = 0
    for t in approved_txns:
        amt = t.get("eligible_amount_cents", 0) or 0
        if amt > 0 and amt % 10000 == 0:
            even_count += 1
    c_signal = Decimal(0) if total_tx == 0 else Decimal(even_count) / Decimal(total_tx)

    raw = WEIGHT_A * a_signal + WEIGHT_B * b_signal + WEIGHT_C * c_signal
    score = round_half_up_2(raw)
    # clamp to 0..1
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return score


# -----------------------------------------------------------------------------
# ABAWD status
# -----------------------------------------------------------------------------

def calc_abawd_status(member: dict) -> str:
    clock_now = STORE.clock.now
    if member["status"] != "ACTIVE":
        return member.get("abawd_status", "NOT_ABAWD")
    try:
        age_years = age_years_truncated(member["date_of_birth"], clock_now)
    except Exception:
        return "NOT_ABAWD"
    if not (18 <= age_years <= 49):
        return "NOT_ABAWD"
    if member.get("is_disabled") or member.get("is_pregnant"):
        return "ABAWD_EXEMPT"
    # Check siblings under 18
    siblings = [m for m in STORE.members.values()
                if m["household_id"] == member["household_id"]
                and m["status"] == "ACTIVE"
                and m["id"] != member["id"]]
    for s in siblings:
        try:
            s_age = age_years_truncated(s["date_of_birth"], clock_now)
            if s_age < 18:
                return "ABAWD_EXEMPT"
        except Exception:
            continue
    # Check approved waiver covering Clock.now
    for w in STORE.waivers.values():
        if w["member_id"] != member["id"]:
            continue
        if w["state"] != "APPROVED":
            continue
        try:
            ef = parse_iso8601(w["effective_from"])
            et = parse_iso8601(w["effective_to"])
        except Exception:
            continue
        if ef <= clock_now < et:
            return "ABAWD_WAIVED"
    return "ABAWD_SUBJECT"
