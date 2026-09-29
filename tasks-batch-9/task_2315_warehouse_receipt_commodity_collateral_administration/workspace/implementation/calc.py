"""Calculation rules — SCAFFOLD §1.3 / PRD §2.9, §2.10, §3.1, §3.3, §3.5-§3.9.

All money is integer cents; all quantities are whole bushels; every rounding
point is named individually and applied with round-half-up (ties away from
zero) exactly where the specification places it.
"""

from decimal import Decimal

from core import dec, rhu

# --- §3.1 licence bond / net worth ----------------------------------------
MIN_NET_WORTH_CENTS = {"STATE": 5000000, "FEDERAL": 10000000}
NET_WORTH_CENTS_PER_BUSHEL = {"STATE": 4, "FEDERAL": 8}
BOND_MIN_CENTS = {"STATE": 2500000, "FEDERAL": 6000000}
BOND_CENTS_PER_BUSHEL = {"STATE": 5, "FEDERAL": 3}
NET_WORTH_SHORTFALL_TOLERANCE_BPS = 2500
BOND_SHORTFALL_MULTIPLIER_BPS = 15000

# --- §2.9 grade standard ---------------------------------------------------
GRADE_RANK = {"US_NO_1": 1, "US_NO_2": 2, "US_NO_3": 3, "SAMPLE_GRADE": 4}
GRADES = ("US_NO_1", "US_NO_2", "US_NO_3", "SAMPLE_GRADE")
GRADE_DISCOUNT_BPS = {"US_NO_1": 0, "US_NO_2": 150, "US_NO_3": 400,
                      "SAMPLE_GRADE": 1200}

# --- §3.3 weigh-in --------------------------------------------------------
MOISTURE_SHRINK_BPS_PER_POINT = 118

# --- §2.10 storage accrual ------------------------------------------------
BASE_TIER_DAYS = 90
SURCHARGE_MULTIPLIER_BPS = 12500
MIN_STORAGE_CHARGE_CENTS = 500

# --- §3.7 position reconciliation ----------------------------------------
EXAM_TOLERANCE_BPS = 50
EXAM_MIN_TOLERANCE_BUSHELS = 500

# --- §3.6 collateral valuation -------------------------------------------
IMPAIRED_DISCOUNT_BPS = 2500
LIEN_ADMIN_FEE_BPS = 25
ADVANCE_RATE_TIER_THRESHOLD_CENTS = 10000000
ADVANCE_RATE_HIGH_BPS = 8000
ADVANCE_RATE_LOW_BPS = 7000

# --- §3.9 indemnity waterfall --------------------------------------------
FUND_AGGREGATE_CAP_CENTS = 100000000
FUND_PER_CLAIMANT_CAP_CENTS = 30000000

# --- §3.5 bin condition ---------------------------------------------------
WATCH_MOISTURE_PCT = Decimal("14.0")
OOC_MOISTURE_PCT = Decimal("15.5")
WATCH_TEMPERATURE_F = Decimal("85")
OOC_TEMPERATURE_F = Decimal("95")
BLEND_SHRINK_BPS = 150
TREATMENT_ACTIONS = ("NONE", "AERATE", "TURN", "BLEND_OUT")

# --- §3.4 void window -----------------------------------------------------
RECEIPT_VOID_WINDOW_HOURS = 72

# --- §3.3 bin fill window buffer -----------------------------------------
BIN_REST_BUFFER_MINUTES = 240


# ===========================================================================
# license_bond_and_net_worth_requirement
# ===========================================================================

def license_financials(program, capacity_bushels, bond_amount_cents,
                       net_worth_cents):
    required_net_worth = max(
        MIN_NET_WORTH_CENTS[program],
        capacity_bushels * NET_WORTH_CENTS_PER_BUSHEL[program],
    )
    shortfall = max(0, required_net_worth - net_worth_cents)
    tolerance = rhu(dec(required_net_worth)
                    * NET_WORTH_SHORTFALL_TOLERANCE_BPS / 10000)
    base_bond = max(
        BOND_MIN_CENTS[program],
        capacity_bushels * BOND_CENTS_PER_BUSHEL[program],
    )
    required_bond = base_bond + rhu(
        dec(shortfall) * BOND_SHORTFALL_MULTIPLIER_BPS / 10000)
    bond_deficiency = max(0, required_bond - bond_amount_cents)
    return {
        "required_net_worth_cents": required_net_worth,
        "net_worth_shortfall_cents": shortfall,
        "net_worth_tolerance_cents": tolerance,
        "required_bond_cents": required_bond,
        "bond_deficiency_cents": bond_deficiency,
    }


# ===========================================================================
# deposit_grade_and_net_bushels
# ===========================================================================

def assign_grade(test_weight_lbs, damage_pct, foreign_material_pct):
    tw = dec(test_weight_lbs)
    dmg = dec(damage_pct)
    fm = dec(foreign_material_pct)
    if tw >= Decimal("56.0") and dmg <= Decimal("3.0") and fm <= Decimal("2.0"):
        return "US_NO_1"
    if tw >= Decimal("54.0") and dmg <= Decimal("5.0") and fm <= Decimal("3.0"):
        return "US_NO_2"
    if tw >= Decimal("52.0") and dmg <= Decimal("7.0") and fm <= Decimal("4.0"):
        return "US_NO_3"
    return "SAMPLE_GRADE"


def deposit_quantities(gross_bushels, dockage_pct, moisture_pct,
                       max_moisture_pct, storage_kind):
    dockage_bushels = rhu(dec(gross_bushels) * dec(dockage_pct) / 100)
    clean_bushels = gross_bushels - dockage_bushels
    excess = dec(moisture_pct) - dec(max_moisture_pct)
    if excess < 0:
        excess = Decimal(0)
    if storage_kind == "IDENTITY_PRESERVED":
        shrink_bushels = 0
    else:
        shrink_bushels = rhu(dec(clean_bushels) * excess
                             * MOISTURE_SHRINK_BPS_PER_POINT / 10000)
    net_bushels = clean_bushels - shrink_bushels
    return {
        "dockage_bushels": dockage_bushels,
        "clean_bushels": clean_bushels,
        "shrink_bushels": shrink_bushels,
        "net_bushels": net_bushels,
    }


# ===========================================================================
# storage_charge_accrual  (PROVISIONAL / FINAL)
# ===========================================================================

def storage_charge_accrual(variant, quantity_bushels, rate_millicents,
                           free_storage_days, issued_at, as_of_date):
    day_count = (as_of_date - issued_at.date()).days + 1
    if variant == "FINAL":
        chargeable_days = max(0, day_count - free_storage_days)
    else:
        chargeable_days = day_count
    base_days = min(chargeable_days, BASE_TIER_DAYS)
    surcharge_days = max(0, chargeable_days - BASE_TIER_DAYS)
    base_cents = rhu(dec(quantity_bushels) * rate_millicents * base_days / 1000)
    surcharge_cents = rhu(dec(quantity_bushels) * rate_millicents
                          * surcharge_days * SURCHARGE_MULTIPLIER_BPS
                          / 10000000)
    raw = base_cents + surcharge_cents
    if raw == 0:
        return 0
    return max(MIN_STORAGE_CHARGE_CENTS, raw)


# ===========================================================================
# position_reconciliation
# ===========================================================================

def examination_tolerance(obligation_bushels):
    return max(EXAM_MIN_TOLERANCE_BUSHELS,
               rhu(dec(obligation_bushels) * EXAM_TOLERANCE_BPS / 10000))


# ===========================================================================
# collateral_valuation_and_advance_limit  (seven normative steps)
# ===========================================================================

def collateral_valuation(valuation_basis, mark_price_cents_per_bushel,
                         quantity_bushels, receipt_grade, quality_flag,
                         face_price_cents_per_bushel,
                         provisional_storage_charge_cents,
                         receiving_charge_cents, principal_cents):
    # 1. gross value
    if valuation_basis == "MARK_TO_MARKET":
        price = mark_price_cents_per_bushel
    else:
        price = face_price_cents_per_bushel
    gross_value_cents = quantity_bushels * price
    # 2. quality / grade discount
    if valuation_basis == "FACE_ADVANCE":
        grade_discount_bps = 0
    else:
        grade_discount_bps = GRADE_DISCOUNT_BPS[receipt_grade]
        if quality_flag == "IMPAIRED":
            grade_discount_bps += IMPAIRED_DISCOUNT_BPS
    # 3. eligible value
    eligible_value_cents = rhu(dec(gross_value_cents)
                               * (10000 - grade_discount_bps) / 10000)
    # 4. administration fee — keyed on the PRE-lien eligible value
    if valuation_basis == "FACE_ADVANCE":
        admin_fee_cents = 0
    else:
        admin_fee_cents = rhu(dec(eligible_value_cents)
                              * LIEN_ADMIN_FEE_BPS / 10000)
    # 5. warehouseman's prior lien
    warehouseman_lien_cents = (provisional_storage_charge_cents
                               + receiving_charge_cents + admin_fee_cents)
    net_collateral_cents = max(0, eligible_value_cents
                               - warehouseman_lien_cents)
    # 6. advance-rate tier — keyed on the POST-lien net value, inclusive test
    if net_collateral_cents >= ADVANCE_RATE_TIER_THRESHOLD_CENTS:
        advance_rate_bps = ADVANCE_RATE_HIGH_BPS
    else:
        advance_rate_bps = ADVANCE_RATE_LOW_BPS
    # 7. limit and margin
    advance_limit_cents = rhu(dec(net_collateral_cents)
                              * advance_rate_bps / 10000)
    margin_deficiency_cents = max(0, principal_cents - advance_limit_cents)
    return {
        "gross_value_cents": gross_value_cents,
        "grade_discount_bps": grade_discount_bps,
        "eligible_value_cents": eligible_value_cents,
        "admin_fee_cents": admin_fee_cents,
        "warehouseman_lien_cents": warehouseman_lien_cents,
        "net_collateral_cents": net_collateral_cents,
        "advance_rate_bps": advance_rate_bps,
        "advance_limit_cents": advance_limit_cents,
        "margin_deficiency_cents": margin_deficiency_cents,
        "margin_status": ("SUFFICIENT" if margin_deficiency_cents == 0
                          else "DEFICIENT"),
    }


# ===========================================================================
# delivery_settlement
# ===========================================================================

def grade_delta_bps(delivered_grade, receipt_grade):
    return max(0, GRADE_DISCOUNT_BPS[delivered_grade]
               - GRADE_DISCOUNT_BPS[receipt_grade])


def quality_adjustment(delivered_bushels, settlement_price, delta_bps):
    return rhu(dec(delivered_bushels) * settlement_price * delta_bps / 10000)


def loadout_charge(delivered_bushels, loadout_charge_cents_per_bushel):
    return rhu(dec(delivered_bushels) * loadout_charge_cents_per_bushel)


# ===========================================================================
# bin_condition_assessment
# ===========================================================================

def derive_condition(moisture_pct, temperature_f):
    m = dec(moisture_pct)
    t = dec(temperature_f)
    if (m >= OOC_MOISTURE_PCT or t > OOC_TEMPERATURE_F
            or (m >= WATCH_MOISTURE_PCT and t > WATCH_TEMPERATURE_F)):
        return "OUT_OF_CONDITION"
    if m >= WATCH_MOISTURE_PCT or t > WATCH_TEMPERATURE_F:
        return "WATCH"
    return "SOUND"


def blend_loss(stored_bushels):
    return rhu(dec(stored_bushels) * BLEND_SHRINK_BPS / 10000)


# ===========================================================================
# indemnity_waterfall_allocation
# ===========================================================================

def waterfall(claims, bond_pool):
    """claims: list of dicts ordered arbitrarily; mutated in place.

    Tier 1 — the bond, shared by every allowed claimant, floor pro-rata with a
    one-cent remainder distribution ordered by allowed_cents DESC then
    created_at ASC.  Tier 2 — the indemnity fund, producer depositors only,
    walked sequentially in that same order.
    """
    total_allowed = sum(c["allowed_cents"] for c in claims)
    order = sorted(claims, key=lambda c: (-c["allowed_cents"],
                                          c["created_at"], c["_seq"]))
    if total_allowed <= bond_pool:
        for c in claims:
            c["bond_share_cents"] = c["allowed_cents"]
    else:
        for c in claims:
            c["bond_share_cents"] = int(
                (bond_pool * c["allowed_cents"]) // total_allowed)
        remainder = bond_pool - sum(c["bond_share_cents"] for c in claims)
        for c in order[:max(0, remainder)]:
            c["bond_share_cents"] += 1

    fund_remaining = FUND_AGGREGATE_CAP_CENTS
    for c in order:
        residual = c["allowed_cents"] - c["bond_share_cents"]
        if not c["fund_eligible"] or fund_remaining == 0:
            c["fund_share_cents"] = 0
        else:
            share = min(residual, FUND_PER_CLAIMANT_CAP_CENTS, fund_remaining)
            if share < 0:
                share = 0
            c["fund_share_cents"] = share
            fund_remaining -= share
    for c in claims:
        c["unpaid_cents"] = (c["allowed_cents"] - c["bond_share_cents"]
                             - c["fund_share_cents"])
