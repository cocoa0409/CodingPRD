"""Pricing, permit fee, verdict, deposit, refund, RTO schedule and warranty
calculations (SCAFFOLD Table 3 / PRD §3). All money math uses Decimal with
ROUND_HALF_UP; each fee line is rounded to whole cents before summation."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- order_total_price constants ---
OPTION_PRICE_CENTS = {"WINDOW": 15000, "LOFT": 25000, "RAMP": 10000, "ELECTRICAL": 40000}
DELIVERY_PREBUILT_CENTS = 25000
DELIVERY_ONSITE_CENTS = 45000
GRAVEL_PER_SQFT_CENTS = 800
SLAB_PER_SQFT_CENTS = 1500
SLAB_MIN_CENTS = 200000
PIER_EACH_CENTS = 12000
AUGER_EACH_CENTS = 7500
REMOVAL_BASE_CENTS = 30000
REMOVAL_PER_SQFT_CENTS = 500
TRADE_IN_CAP_BP = 1500
RTO_FACTOR_BP = 16000

# --- rto_payment_schedule constants ---
LATE_FEE_BP = 1000
INSTALLMENT_INTERVAL_DAYS = 30

# --- site_suitability_verdict constants ---
ACCESS_MARGIN_PREBUILT_IN = 12
ACCESS_MARGIN_ONSITE_IN = 36
MAX_SLOPE_PCT = 15
PREP_SLOPE_PCT = 8

# --- deposit_requirement constants ---
DEPOSIT_BP = 2000

# --- cancellation_refund constants ---
ADMIN_FEE_CENTS = 5000
RESTOCK_BP = 1000

# --- rto_delinquency_evaluation constants ---
GRACE_DAYS = 7
DEFAULT_AFTER_DAYS = 45

# --- warranty_charge constants ---
SERVICE_CALL_BASE_CENTS = 15000
REOPEN_WINDOW_DAYS = 30


def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal amount to whole cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_area_sqft(width_ft, depth_ft) -> float:
    """area_sqft = width_ft * depth_ft"""
    return float(Decimal(str(width_ft)) * Decimal(str(depth_ft)))


def compute_structure_price_cents(model: dict, area_sqft) -> int:
    """Tiered overage pricing per calculations.order_total_price."""
    base_area = Decimal(str(model["min_width_ft"])) * Decimal(str(model["min_depth_ft"]))
    area = Decimal(str(area_sqft))
    overage = max(Decimal("0"), area - base_area)
    tier1_sqft = min(overage, Decimal("40"))
    tier2_sqft = max(Decimal("0"), overage - Decimal("40"))
    price = (Decimal(model["base_price_cents"])
             + tier1_sqft * Decimal(model["overage_rate_tier1_cents"])
             + tier2_sqft * Decimal(model["overage_rate_tier2_cents"]))
    return round_half_up_cents(price)


def compute_order_pricing(order: dict, model: dict, jurisdiction: dict) -> dict:
    """Full pinned pricing pipeline. Returns dict with structure_price_cents and
    total_cents (the quoted/final total for the order's purchase_type)."""
    area_sqft = order["area_sqft"]
    area = Decimal(str(area_sqft))

    structure_price_cents = compute_structure_price_cents(model, area_sqft)

    options_total_cents = sum(OPTION_PRICE_CENTS[o] for o in order.get("options", []))

    delivery_fee_cents = (DELIVERY_PREBUILT_CENTS if order["delivery_mode"] == "PRE_BUILT"
                          else DELIVERY_ONSITE_CENTS)

    ft = order["foundation_type"]
    if ft == "GRAVEL_PAD":
        foundation_fee_cents = round_half_up_cents(area * Decimal(GRAVEL_PER_SQFT_CENTS))
    elif ft == "CONCRETE_SLAB":
        foundation_fee_cents = max(round_half_up_cents(area * Decimal(SLAB_PER_SQFT_CENTS)),
                                   SLAB_MIN_CENTS)
    elif ft == "PIERS":
        piers = (math.ceil(Decimal(str(order["width_ft"])) / Decimal("4"))
                 * math.ceil(Decimal(str(order["depth_ft"])) / Decimal("4")))
        foundation_fee_cents = piers * PIER_EACH_CENTS
    else:  # NONE
        foundation_fee_cents = 0

    if order["anchor_type"] == "AUGER_STRAP":
        anchors = 4 + 2 * math.floor(area / Decimal("100"))
        anchor_fee_cents = anchors * AUGER_EACH_CENTS
    else:
        anchor_fee_cents = 0

    prep_fee_cents = order.get("site_prep_fee_cents", 0)

    if order.get("removal_requested"):
        old_area = Decimal(str(order.get("old_structure_area_sqft", 0)))
        removal_fee_cents = REMOVAL_BASE_CENTS + round_half_up_cents(old_area * Decimal(REMOVAL_PER_SQFT_CENTS))
    else:
        removal_fee_cents = 0

    appraised = Decimal(order.get("trade_in_appraised_cents") or 0)
    cap = (Decimal(structure_price_cents) * Decimal(TRADE_IN_CAP_BP) / Decimal(10000)).to_integral_value(
        rounding="ROUND_FLOOR")
    trade_in_credit_cents = int(min(appraised, cap))

    subtotal_cents = max(0, structure_price_cents + options_total_cents + delivery_fee_cents
                         + foundation_fee_cents + anchor_fee_cents + prep_fee_cents
                         + removal_fee_cents - trade_in_credit_cents)

    tax_cents = round_half_up_cents(
        Decimal(structure_price_cents + options_total_cents)
        * Decimal(jurisdiction["tax_rate_bp"]) / Decimal(10000))

    if order["purchase_type"] == "RTO":
        total_cents = (round_half_up_cents(Decimal(subtotal_cents) * Decimal(RTO_FACTOR_BP) / Decimal(10000))
                       + tax_cents)
    else:
        total_cents = subtotal_cents + tax_cents

    return {
        "structure_price_cents": structure_price_cents,
        "total_cents": total_cents,
    }


def compute_permit_fee(area_sqft, jurisdiction: dict):
    """permit_required is inclusive of the threshold; fee = base + area*per_sqft."""
    required = Decimal(str(area_sqft)) >= Decimal(str(jurisdiction["permit_threshold_sqft"]))
    if not required:
        return False, 0
    fee = Decimal(jurisdiction["permit_base_fee_cents"]) + Decimal(str(area_sqft)) * Decimal(
        jurisdiction["permit_per_sqft_cents"])
    return True, round_half_up_cents(fee)


def compute_verdict(order: dict, jurisdiction: dict, report: dict) -> str:
    """Site suitability verdict per calculations.site_suitability_verdict."""
    if order["delivery_mode"] == "PRE_BUILT":
        required_access_in = Decimal(str(order["width_ft"])) * Decimal(12) + Decimal(
            ACCESS_MARGIN_PREBUILT_IN)
    else:
        required_access_in = Decimal(ACCESS_MARGIN_ONSITE_IN)

    hard_fail = (
        Decimal(str(report["setback_front_ft"])) < Decimal(str(jurisdiction["setback_front_ft"]))
        or Decimal(str(report["setback_side_ft"])) < Decimal(str(jurisdiction["setback_side_ft"]))
        or Decimal(str(report["setback_rear_ft"])) < Decimal(str(jurisdiction["setback_rear_ft"]))
        or Decimal(str(report["measured_slope_pct"])) > Decimal(MAX_SLOPE_PCT)
        or Decimal(report["measured_access_width_in"]) < required_access_in
    )
    if hard_fail:
        return "UNSUITABLE"
    needs_prep = (Decimal(str(report["measured_slope_pct"])) > Decimal(PREP_SLOPE_PCT)
                  or report["ground_prep_needed"])
    return "SUITABLE_WITH_PREP" if needs_prep else "SUITABLE"


def compute_required_deposit_cents(quoted_total_cents: int) -> int:
    return round_half_up_cents(Decimal(quoted_total_cents) * Decimal(DEPOSIT_BP) / Decimal(10000))


def compute_rto_schedule(total_contract_cents: int, term_months: int):
    """Round the monthly installment first, then derive the final installment as
    the remainder so the sum equals the contract total exactly."""
    monthly = round_half_up_cents(Decimal(total_contract_cents) / Decimal(term_months))
    final = total_contract_cents - monthly * (term_months - 1)
    return monthly, final


def compute_late_fee_cents(monthly_payment_cents: int) -> int:
    return round_half_up_cents(Decimal(monthly_payment_cents) * Decimal(LATE_FEE_BP) / Decimal(10000))


def due_date_k(first_due_date: str, k: int) -> str:
    """due_k = date(completed_at) + 30*k days; first_due_date is already due_1."""
    base = db_parse_date(first_due_date)
    from datetime import date as date_cls
    d = base + timedelta(days=INSTALLMENT_INTERVAL_DAYS * (k - 1))
    return d.isoformat()


def db_parse_date(s: str):
    """Parse 'YYYY-MM-DD' into a datetime.date."""
    from datetime import date as date_cls
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    return date_cls(y, m, d)
