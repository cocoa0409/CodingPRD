"""Money math: deductible determination, invoice line pricing, totals, OEM upcharge.

All monetary values are integer cents; fractional results round HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import (
    ApiError,
    ERR_PART_NOT_FOUND,
    ERR_PART_DISCONTINUED,
    ERR_MOBILE_FEE_NOT_ALLOWED,
    ERR_LINE_PRICE_EXCEEDS_AGREEMENT,
    ERR_INVALID_REQUEST,
)

TIER_MULTIPLIERS = {
    "PLATINUM": Decimal("0.75"),
    "PREFERRED": Decimal("0.85"),
    "STANDARD": Decimal("0.95"),
}

MOBILE_FEE_CENTS = 5000
MATERIALS_BASE_CENTS = 1500
OEM_UPCHARGE_RATE = Decimal("0.25")

LINE_TYPES = {"PART", "CALIBRATION", "MOBILE_FEE", "MATERIALS"}
PART_ORIGINS = {"OEM", "AFTERMARKET"}


def round_half_up(value):
    """Round a Decimal to integer cents, HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def effective_deductible(policy, regulation):
    deductible = policy["deductible_cents"]
    cap = regulation.get("max_deductible_cents")
    if cap is not None:
        deductible = min(deductible, cap)
    return deductible


def zero_deductible_applies(claim, policy, regulation):
    return (
        regulation["zero_deductible_windshield"] is True
        and claim["part_category"] == "WINDSHIELD"
        and policy["coverage_type"] == "COMPREHENSIVE"
    )


def provisional_responsibility(claim, policy, regulation):
    if zero_deductible_applies(claim, policy, regulation):
        return 0
    return min(effective_deductible(policy, regulation), claim["estimated_repair_cost_cents"])


def final_deductible_basis(claim, policy, regulation):
    if zero_deductible_applies(claim, policy, regulation):
        return 0
    return effective_deductible(policy, regulation)


def agreement_unit_price(line_type, entry, shop, work_order):
    """Compute the per-line agreement price (HALF_UP per line).

    Raises ERR_PART_DISCONTINUED / ERR_MOBILE_FEE_NOT_ALLOWED (callers run the
    passes in the priority order that fits the endpoint).
    """
    tier = TIER_MULTIPLIERS[shop["agreement_tier"]]
    if line_type in ("PART", "CALIBRATION"):
        multiplier = Decimal("1.00") if entry["part_origin"] == "OEM" else tier
        return round_half_up(Decimal(entry["nags_list_price_cents"]) * multiplier)
    if line_type == "MOBILE_FEE":
        return MOBILE_FEE_CENTS
    # MATERIALS
    return round_half_up(Decimal(MATERIALS_BASE_CENTS) * tier)


def check_line_constraints(line_type, entry, work_order):
    if line_type in ("PART", "CALIBRATION"):
        if entry["status"] != "AVAILABLE":
            raise ApiError(ERR_PART_DISCONTINUED, 422, "Referenced part catalog entry is DISCONTINUED")
    if line_type == "MOBILE_FEE":
        if work_order.get("service_mode") != "MOBILE":
            raise ApiError(
                ERR_MOBILE_FEE_NOT_ALLOWED,
                422,
                "MOBILE_FEE line on a work order whose service_mode is not MOBILE",
            )


def validate_line_specs(line_items, require_part_ref=True):
    """Payload-sanity pass over raw line item dicts."""
    for idx, item in enumerate(line_items):
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"line_items[{idx}] must be an object")
        line_type = item.get("line_type")
        if not isinstance(line_type, str) or line_type not in LINE_TYPES:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"line_items[{idx}].line_type is invalid")
        qty = item.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"line_items[{idx}].quantity must be an integer >= 1")
        price = item.get("unit_price_cents")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"line_items[{idx}].unit_price_cents must be an integer >= 0")
        if line_type in ("PART", "CALIBRATION") and require_part_ref:
            ref = item.get("part_catalog_entry_id")
            if ref is None or not isinstance(ref, str):
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    400,
                    f"line_items[{idx}].part_catalog_entry_id is required for {line_type} lines",
                )
        if line_type == "PART":
            origin = item.get("origin_claimed")
            if not isinstance(origin, str) or origin not in PART_ORIGINS:
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    400,
                    f"line_items[{idx}].origin_claimed must be OEM or AFTERMARKET for PART lines",
                )


def check_part_existence(line_items):
    for item in line_items:
        if isinstance(item, dict):
            ref = item.get("part_catalog_entry_id")
            if ref is not None and ref not in store.parts:
                raise ApiError(ERR_PART_NOT_FOUND, 404, "Referenced part catalog entry does not exist")


def price_and_build_lines(line_items, shop, work_order):
    """Constraint + fiscal passes; returns list of computed line dicts (unsaved)."""
    validate_line_specs(line_items)
    built = []
    for item in line_items:
        line_type = item["line_type"]
        entry = None
        if line_type in ("PART", "CALIBRATION"):
            entry = store.parts[item["part_catalog_entry_id"]]
        check_line_constraints(line_type, entry, work_order)
        built.append((item, entry))
    results = []
    for item, entry in built:
        line_type = item["line_type"]
        agreement = agreement_unit_price(line_type, entry, shop, work_order)
        if item["unit_price_cents"] > agreement:
            raise ApiError(
                ERR_LINE_PRICE_EXCEEDS_AGREEMENT,
                402,
                "Billed unit_price_cents exceeds the agreement unit price",
            )
        results.append(
            {
                "part_catalog_entry_id": item.get("part_catalog_entry_id")
                if line_type in ("PART", "CALIBRATION")
                else None,
                "line_type": line_type,
                "quantity": item["quantity"],
                "origin_claimed": item.get("origin_claimed") if line_type == "PART" else None,
                "unit_price_cents": item["unit_price_cents"],
                "agreement_unit_price_cents": agreement,
                "line_total_cents": item["unit_price_cents"] * item["quantity"],
                "approved_amount_cents": None,
                "approved_origin": None,
            }
        )
    return results


def compute_totals(lines, regulation):
    """Pinned order: per-line totals first, then tax on summed parts subtotal."""
    parts_subtotal = sum(l["line_total_cents"] for l in lines if l["line_type"] == "PART")
    tax = round_half_up(Decimal(parts_subtotal) * Decimal(regulation["glass_sales_tax_rate_bp"]) / Decimal(10000))
    submitted = sum(l["line_total_cents"] for l in lines) + tax
    return submitted, tax


def compute_oem_upcharge(lines, policy):
    if policy.get("oem_endorsement") is True:
        return 0
    total = 0
    for line in lines:
        if line["line_type"] != "PART":
            continue
        final_origin = line.get("approved_origin") or line.get("origin_claimed")
        if final_origin != "OEM":
            continue
        total += round_half_up(Decimal(line["approved_amount_cents"]) * OEM_UPCHARGE_RATE)
    return total
