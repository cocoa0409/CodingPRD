"""Calculation rules (SCAFFOLD §1.3 / PRD §3.7, §3.10).

All monetary math uses Decimal with ROUND_HALF_UP. Each step rounds at its
pinned boundary before the next step reads its value.
"""

from datetime import datetime
from decimal import Decimal

from config import (
    AGE_BONUS,
    AGE_BONUS_MAX_INCL,
    AGE_BONUS_MIN_INCL,
    AGE_FACTOR_FLOOR,
    AGE_FACTOR_STEP,
    APP_TYPE_INITIAL_REGISTRATION,
    BASE_HEAVY,
    BASE_LIGHT,
    BASE_MID,
    COUNTY_SURCHARGE,
    ID_WEIGHT,
    NON_RESIDENT_SURCHARGE,
    RATE_NON_RESIDENT,
    RATE_RESIDENT,
    RES_WEIGHT,
    REVISION_PENALTY_PER_CYCLE,
    SSN_WEIGHT,
    TIER_1_FEE,
    TIER_1_MAX,
    TIER_2_FEE,
    TIER_2_MAX,
    TIER_3_FEE,
    TIER_3_MAX,
    TIER_4_RATE,
    WEIGHT_HEAVY_MIN_INCL,
    WEIGHT_LIGHT_MAX_EXCL,
)
from utils import floor_age_years, round_half_up_2, to_decimal


def registration_fee(curb_weight_lbs: int, model_year: int, is_resident: bool,
                     current_calendar_year: int) -> Decimal:
    """SCAFFOLD calc 'registration_fee'.

    weight_base * age_factor + surcharge, rounded half-up to 2 decimals.
    """
    # Weight tier base
    if curb_weight_lbs < WEIGHT_LIGHT_MAX_EXCL:
        weight_base = BASE_LIGHT
    elif curb_weight_lbs < WEIGHT_HEAVY_MIN_INCL:
        weight_base = BASE_MID
    else:
        # >= 6000 lbs — inclusive boundary
        weight_base = BASE_HEAVY

    # Age depreciation
    age_years = max(0, current_calendar_year - model_year)
    age_factor = Decimal("1.00") - (AGE_FACTOR_STEP * Decimal(age_years))
    if age_factor < AGE_FACTOR_FLOOR:
        age_factor = AGE_FACTOR_FLOOR

    # County surcharge
    surcharge = COUNTY_SURCHARGE if is_resident else NON_RESIDENT_SURCHARGE

    raw = weight_base * age_factor + surcharge
    return round_half_up_2(raw)


def sales_tax_on_transfer(declared_sale_price: Decimal,
                          trade_in_value: Decimal,
                          is_resident: bool,
                          application_type: str) -> Decimal:
    """SCAFFOLD calc 'sales_tax_on_transfer' — dual-variant.

    Resident variant (TITLE_TRANSFER): trade_in deducted from taxable base.
    Resident variant + INITIAL_REGISTRATION: trade_in treated as 0
        (the call sites already default trade_in_value to 0 for initial reg
         but we enforce it here too for clarity).
    Non-resident variant: trade_in ignored entirely; rate is 0.085.
    """
    declared_sale_price = to_decimal(declared_sale_price)
    trade_in_value = to_decimal(trade_in_value) if trade_in_value is not None else Decimal("0.00")

    if is_resident:
        if application_type == APP_TYPE_INITIAL_REGISTRATION:
            effective_trade_in = Decimal("0.00")
        else:
            effective_trade_in = trade_in_value
        taxable_base = declared_sale_price - effective_trade_in
        if taxable_base < Decimal("0.00"):
            taxable_base = Decimal("0.00")
        raw = taxable_base * RATE_RESIDENT
    else:
        # Non-resident: trade_in_value is IGNORED entirely
        taxable_base = declared_sale_price
        raw = taxable_base * RATE_NON_RESIDENT

    return round_half_up_2(raw)


def total_due_with_processing(sales_tax: Decimal, reg_fee: Decimal):
    """SCAFFOLD calc 'total_due_with_processing'.

    Returns (fee_subtotal, processing_fee, total_due), each at 2dp.
    Step 1: fee_subtotal = round_half_up(sales_tax + reg_fee, 2)
    Step 2: processing_fee tier on fee_subtotal
    Step 3: total_due = round_half_up(fee_subtotal + processing_fee, 2)
    """
    fee_subtotal = round_half_up_2(to_decimal(sales_tax) + to_decimal(reg_fee))

    if fee_subtotal <= TIER_1_MAX:
        processing_fee = TIER_1_FEE
    elif fee_subtotal <= TIER_2_MAX:
        processing_fee = TIER_2_FEE
    elif fee_subtotal <= TIER_3_MAX:
        processing_fee = TIER_3_FEE
    else:
        processing_fee = round_half_up_2(fee_subtotal * TIER_4_RATE)

    total_due = round_half_up_2(fee_subtotal + processing_fee)
    return fee_subtotal, processing_fee, total_due


def real_id_eligibility_score(doc_id: bool, doc_res: bool, doc_ssn: bool,
                              date_of_birth_dt: datetime, now: datetime,
                              revision_count: int) -> Decimal:
    """SCAFFOLD calc 'real_id_eligibility_score'.

    Sum of weighted document points + age bonus - revision penalty, clamped
    to [0.00, 100.00], rounded half-up to 2 decimals.
    """
    id_pts = ID_WEIGHT if doc_id else 0
    res_pts = RES_WEIGHT if doc_res else 0
    ssn_pts = SSN_WEIGHT if doc_ssn else 0

    age = floor_age_years(date_of_birth_dt, now)
    age_bonus = AGE_BONUS if (AGE_BONUS_MIN_INCL <= age <= AGE_BONUS_MAX_INCL) else 0

    revision_penalty = -REVISION_PENALTY_PER_CYCLE * revision_count

    raw = Decimal(id_pts + res_pts + ssn_pts + age_bonus + revision_penalty)
    if raw < Decimal("0"):
        raw = Decimal("0")
    if raw > Decimal("100"):
        raw = Decimal("100")
    return round_half_up_2(raw)
