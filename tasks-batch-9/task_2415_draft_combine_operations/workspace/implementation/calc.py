"""Pure calculations (PRD section 3, scaffold `calculations`). All rounding is
half-up; money is whole cents, chart points 1dp, imbalance 4dp, scores 2dp."""

from decimal import Decimal, ROUND_HALF_UP

import constants as K

ONE = Decimal(1)
Q1 = Decimal("0.1")
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimals; returns a Decimal."""
    value = dec(value)
    if places == 0:
        return value.quantize(ONE, rounding=ROUND_HALF_UP)
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def q1(value):
    return dec(value).quantize(Q1, rounding=ROUND_HALF_UP)


def q2(value):
    return dec(value).quantize(Q2, rounding=ROUND_HALF_UP)


def q4(value):
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# pick_trade_value_balance -- chart values
# --------------------------------------------------------------------------
def chart_value_points(round_number, pick_in_round):
    base = K.CHART_ROUND_BASE.get(round_number)
    if base is None:
        return q1(0)
    raw = base * (K.CHART_DECAY ** (pick_in_round - 1))
    return q1(raw)


def trade_authorization_tier(capital_points):
    capital = dec(capital_points)
    if capital >= K.TRADE_TIER_FULL_MIN:
        return "FULL"
    if capital >= K.TRADE_TIER_LIMITED_MIN:
        return "LIMITED"
    return "SUSPENDED"


def chart_balance(incoming_points, outgoing_points):
    """Returns (chart_balance_points, imbalance_ratio) as Decimals."""
    incoming = dec(incoming_points)
    outgoing = dec(outgoing_points)
    balance = q1(incoming - outgoing)
    denominator = max(incoming, outgoing, Decimal("1.0"))
    ratio = q4(abs(balance) / denominator)
    return balance, ratio


def pick_surplus_points(round_number, slot_total_value_cents):
    market = K.POSITIONAL_MARKET_APY_CENTS.get(round_number)
    if market is None:
        return q1(0)
    raw = (Decimal(market) - Decimal(slot_total_value_cents)) / K.SURPLUS_UNIT_CENTS
    return q1(raw)


# --------------------------------------------------------------------------
# slotted_rookie_contract_value
# --------------------------------------------------------------------------
def slotted_contract_value(round_number, pick_in_round, origin, udfa_bonus_cents=None):
    """Returns a dict with contract_years / total_value_cents /
    signing_bonus_cents / first_year_cap_charge_cents /
    total_cap_commitment_cents plus the per-year base list."""
    if origin == "DRAFTED":
        contract_years = K.CONTRACT_YEARS_DRAFTED
        base_year1 = K.ROUND_BASE_CENTS[round_number] - K.SLOT_DECREMENT_CENTS[
            round_number
        ] * (pick_in_round - 1)
        year1 = max(base_year1, K.MIN_YEAR1_CENTS)
    else:
        contract_years = K.CONTRACT_YEARS_UDFA
        year1 = K.MIN_YEAR1_CENTS

    years = []
    value = Decimal(year1)
    for _ in range(contract_years):
        rounded = rhu(value, 0)
        years.append(int(rounded))
        value = rounded * (ONE + K.ESCALATOR_PCT)
    total_value_cents = sum(years)

    if origin == "DRAFTED":
        signing_bonus_cents = rhu_int(
            Decimal(total_value_cents) * K.BONUS_SHARE_PCT[round_number]
        )
    else:
        signing_bonus_cents = int(udfa_bonus_cents or 0)

    # PINNED ORDER: prorate per year, round, THEN multiply back up.
    bonus_per_year = rhu_int(Decimal(signing_bonus_cents) / Decimal(contract_years))
    first_year_cap_charge_cents = years[0] + bonus_per_year
    total_cap_commitment_cents = total_value_cents + bonus_per_year * contract_years

    return {
        "contract_years": contract_years,
        "year_values": years,
        "total_value_cents": total_value_cents,
        "signing_bonus_cents": signing_bonus_cents,
        "first_year_cap_charge_cents": first_year_cap_charge_cents,
        "total_cap_commitment_cents": total_cap_commitment_cents,
    }


# --------------------------------------------------------------------------
# compensatory_pick_award_score
# --------------------------------------------------------------------------
def snap_band_factor(snap_pct):
    snap = dec(snap_pct)
    if snap >= Decimal("0.65"):
        return Decimal("1.00")
    if snap >= Decimal("0.45"):
        return Decimal("0.85")
    if snap >= Decimal("0.25"):
        return Decimal("0.70")
    return Decimal("0.50")


def honors_bonus(postseason_honor):
    if postseason_honor == "ALL_LEAGUE":
        return Decimal(40)
    if postseason_honor == "ALL_CONFERENCE":
        return Decimal(20)
    return Decimal(0)


def comp_scores(departed_apy_cents, snap_pct, postseason_honor):
    base = Decimal(int(departed_apy_cents)) / K.COMP_APY_UNIT_CENTS
    bonus = honors_bonus(postseason_honor)
    authoritative = q2(base * snap_band_factor(snap_pct) + bonus)
    advisory = q2(base * dec(snap_pct) + bonus)
    return authoritative, advisory


def comp_awarded_round(claim_score):
    score = dec(claim_score)
    if score >= Decimal(1200):
        return 3
    if score >= Decimal(700):
        return 4
    if score >= Decimal(450):
        return 5
    if score >= Decimal(300):
        return 6
    return 7


# --------------------------------------------------------------------------
# selection_clock_deadline
# --------------------------------------------------------------------------
def clock_minutes(round_number, compressed_final_day, timeouts_used):
    minutes = K.ROUND_CLOCK_MINUTES.get(round_number, 4)
    if compressed_final_day and round_number >= K.COMPRESSION_FIRST_ROUND:
        minutes -= K.CLOCK_COMPRESSION_MINUTES
    return minutes + K.TIMEOUT_EXTENSION_MINUTES * int(timeouts_used or 0)


# --------------------------------------------------------------------------
# udfa_pool_allocation
# --------------------------------------------------------------------------
def udfa_pool_total(rookie_pool_remaining_cents, lapsed_slot_charge_cents):
    base_pool = K.UDFA_BASE_POOL_CENTS + rhu_int(
        Decimal(int(rookie_pool_remaining_cents)) * K.UDFA_ROLLOVER_PCT
    )
    # PINNED: the tier is keyed on base_pool, never on the post-credit total.
    if base_pool >= K.UDFA_TIER_LOW_MIN:
        rate = K.UDFA_CREDIT_RATE_LOW
    elif base_pool >= K.UDFA_TIER_MID_MIN:
        rate = K.UDFA_CREDIT_RATE_MID
    else:
        rate = K.UDFA_CREDIT_RATE_HIGH
    credit = rhu_int(Decimal(int(lapsed_slot_charge_cents)) * rate)
    return base_pool + credit
