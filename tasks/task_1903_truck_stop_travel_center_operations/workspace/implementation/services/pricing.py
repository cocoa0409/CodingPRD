"""Calculation rules (SCAFFOLD 1.3): quotes, parking/service/scale charges,
shop invoice, water usage, reorder suggestions. All rounding half-up."""
from decimal import ROUND_CEILING

from db import db
from services.core import TIER_MARGINS
from util import CLOCK, ceil_div_int, dec, rhu_dec, rhu_float, rhu_int

# Constants
POINT_VALUE_CENTS = dec("0.5")
FREIGHT_PER_GALLON = dec("0.1500")
PARKING_RATE_PER_HOUR_CENTS = 300
OVERSIZE_FEE_CENTS = 800
GRACE_MINUTES = 15
MAX_WINDOW_HOURS = 336
NO_SHOW_GRACE_HOURS = 2
SHOWER_BASE_CENTS = 1500
LAUNDRY_BASE_CENTS = 400
WEEKEND_SURCHARGE_CENTS = 300
PEAK_SURCHARGE_CENTS = 150
FIRST_WEIGH_FEE_CENTS = 1250
CERTIFIED_FEE_CENTS = 400
ENV_FEE_PER_TIRE_CENTS = 150
SHOP_SUPPLIES_PCT = dec("0.03")
SHOWER_CAP_MINUTES = 45
SHOWER_GPM = dec("2.5")
LAUNDRY_GAL_PER_LB = dec("2.0")
TARGET_FILL_PCT = dec("0.90")
VARIANCE_TOLERANCE_CENTS = 500


# ---------------------------------------------------------------------------
# Points redemption arithmetic (shared by every pricing path)
# ---------------------------------------------------------------------------

def capped_points(requested_redeem_points, member):
    """P = min(requested, member.stack_cap_points); 0 when no member attached."""
    if member is None:
        return 0
    return min(int(requested_redeem_points or 0), member["stack_cap_points"])


def points_discount_cents(points):
    """D = round_half_up(P x 0.005 x 100): each point worth half a cent."""
    return rhu_int(dec(int(points)) * POINT_VALUE_CENTS)


# ---------------------------------------------------------------------------
# Fuel quotes (calc retail_quote_cents_per_gallon / contract_quote_cents_per_gallon)
# ---------------------------------------------------------------------------

def retail_unit_cents(retail_cents, network_discount_per_gallon, points):
    """unit = max(0, round_half_up(R - N x 100) - D), floored at zero."""
    after_network = rhu_int(dec(retail_cents) - dec(network_discount_per_gallon) * dec(100))
    return max(0, after_network - points_discount_cents(points))


def contract_rate_cents(rack_price_4dp, pricing_tier):
    """rate_4dp = rhu4(rack + freight - tier_off); base = rhu(rate x 100)."""
    rate_4dp = rhu_dec(dec(rack_price_4dp) + FREIGHT_PER_GALLON - TIER_MARGINS[pricing_tier], 4)
    return rhu_int(rate_4dp * dec(100))


def contract_unit_cents(rate_cents, discount_per_gallon_off, points):
    """unit = max(0, rate - rhu(discount_off x 100) - D)."""
    discount_cents = rhu_int(dec(discount_per_gallon_off) * dec(100))
    return max(0, rate_cents - discount_cents - points_discount_cents(points))


def discount_exceeds_tier_margin(discount_per_gallon_off, pricing_tier) -> bool:
    return dec(discount_per_gallon_off) > TIER_MARGINS[pricing_tier]


def network_discount_for(member_id, fuel_type):
    """Largest discount_per_gallon among the member's ACTIVE enrollments whose
    network is ACTIVE and covers fuel_type; 0 when none."""
    best = dec("0")
    if member_id is None:
        return best
    for enr in db["enrollments"].values():
        if enr["loyalty_member_id"] != member_id or enr["status"] != "ACTIVE":
            continue
        net = db["networks"].get(enr["network_program_id"])
        if net is None or net["status"] != "ACTIVE":
            continue
        if fuel_type not in net["applicable_fuel_types"]:
            continue
        d = dec(net["discount_per_gallon"])
        if d > best:
            best = d
    return best


def fuel_amount_cents(unit_cents, gallons):
    """round_half_up(unit x dispensed_gallons)."""
    return rhu_int(dec(unit_cents) * dec(gallons))


# ---------------------------------------------------------------------------
# Parking (calc parking_paid_amount)
# ---------------------------------------------------------------------------

def parking_charges(reserved_from_dt, reserved_to_dt, space_type, points):
    total_minutes = int((reserved_to_dt - reserved_from_dt).total_seconds() // 60)
    paid_minutes = max(0, total_minutes - GRACE_MINUTES)
    billed_hours = ceil_div_int(paid_minutes, 60)
    base = billed_hours * PARKING_RATE_PER_HOUR_CENTS
    oversize = OVERSIZE_FEE_CENTS if space_type == "OVERSIZED" else 0
    discount = points_discount_cents(points)
    amount = max(0, base + oversize - discount)
    return {
        "paid_minutes": paid_minutes,
        "billed_hours": billed_hours,
        "oversize_fee_cents": oversize,
        "points_discount_cents": discount,
        "amount_cents": amount,
    }


# ---------------------------------------------------------------------------
# Service queue pricing (calc service_queue_price)
# ---------------------------------------------------------------------------

def service_charges(service_type, points, now=None):
    now = now or CLOCK.now()
    base = SHOWER_BASE_CENTS if service_type == "SHOWER" else LAUNDRY_BASE_CENTS
    weekend = WEEKEND_SURCHARGE_CENTS if now.weekday() >= 5 else 0  # Sat/Sun UTC
    peak = PEAK_SURCHARGE_CENTS if 17 <= now.hour < 22 else 0
    discount = points_discount_cents(points)
    total = max(0, base + weekend + peak - discount)
    return {
        "base_price_cents": base,
        "weekend_surcharge_cents": weekend,
        "peak_surcharge_cents": peak,
        "points_discount_cents": discount,
        "total_price_cents": total,
    }


# ---------------------------------------------------------------------------
# Scale (calc scale_ticket_total)
# ---------------------------------------------------------------------------

def scale_charge_cents(certified):
    return FIRST_WEIGH_FEE_CENTS + (CERTIFIED_FEE_CENTS if certified else 0)


# ---------------------------------------------------------------------------
# Water usage (calc water_usage)
# ---------------------------------------------------------------------------

def water_usage_gallons(service_type, shower_minutes=None, laundry_lbs=None):
    if service_type == "SHOWER":
        gallons = dec(min(dec(shower_minutes), dec(SHOWER_CAP_MINUTES))) * SHOWER_GPM
    else:
        gallons = dec(laundry_lbs) * LAUNDRY_GAL_PER_LB
    return rhu_float(gallons, 2)


# ---------------------------------------------------------------------------
# Shop invoice (calc shop_invoice_total; pinned order parts/labor/env/supplies/sum)
# ---------------------------------------------------------------------------

def shop_invoice(work_order, technician):
    parts_total = 0
    tire_count = 0
    for part in db["work_order_parts"].values():
        if part["work_order_id"] != work_order["id"]:
            continue
        net_qty = part["quantity"] - part["returned_quantity"]
        parts_total += net_qty * part["unit_price_cents"]
        item = db["stock_items"].get(part["stock_item_id"])
        if item is not None and "TIRE" in item["sku"]:
            tire_count += net_qty
    labor_total = rhu_int(dec(work_order["labor_hours_actual"]) * dec(technician["hourly_rate_cents"])) \
        if technician is not None else 0
    environmental_fee = ENV_FEE_PER_TIRE_CENTS * tire_count
    shop_supplies = rhu_int(dec(parts_total) * SHOP_SUPPLIES_PCT)
    invoice_total = parts_total + labor_total + environmental_fee + shop_supplies
    return {
        "parts_total_cents": parts_total,
        "labor_total_cents": labor_total,
        "environmental_fee_cents": environmental_fee,
        "shop_supplies_cents": shop_supplies,
        "invoice_total_cents": invoice_total,
    }


# ---------------------------------------------------------------------------
# Reorder suggestions (calc bulk_reorder_suggestion)
# ---------------------------------------------------------------------------

def reorder_suggestions(site_id):
    suggestions = []
    tanks = [t for t in db["bulk_tanks"].values() if t["site_id"] == site_id]
    tanks.sort(key=lambda t: t["_seq"])
    packaged_items = [i for i in db["stock_items"].values()
                      if i["site_id"] == site_id and i["category"] == "PACKAGED_OIL"
                      and i.get("case_pack_gallons")]
    packaged_items.sort(key=lambda i: i["_seq"])
    for tank in tanks:
        if dec(tank["current_gallons"]) > dec(tank["reorder_threshold_gallons"]):
            continue  # emitted only when current <= threshold
        projected = dec(tank["current_gallons"]) - dec(tank["daily_usage_gallons"]) * dec(tank["lead_time_days"])
        target = TARGET_FILL_PCT * dec(tank["capacity_gallons"])
        raw = target - projected + dec(tank["safety_stock_gallons"])
        if raw < 0:
            raw = dec("0")
        suggested = rhu_dec(raw, 2)
        entry = {
            "bulk_tank_id": tank["id"],
            "product_type": tank["product_type"],
            "current_gallons": rhu_float(tank["current_gallons"], 2),
            "reorder_threshold_gallons": rhu_float(tank["reorder_threshold_gallons"], 2),
            "projected_gallons": rhu_float(projected, 2),
            "target_gallons": rhu_float(target, 2),
            "suggested_gallons": float(suggested),
        }
        if tank["product_type"] == "OIL" and packaged_items:
            case_pack = dec(packaged_items[0]["case_pack_gallons"])
            # ceil(suggested / case_pack) via Decimal
            if case_pack > 0:
                cases = int((suggested / case_pack).to_integral_value(rounding=ROUND_CEILING))
            else:
                cases = 0
            entry["case_pack_gallons"] = float(case_pack)
            entry["suggested_cases"] = cases
            entry["suggested_gallons"] = float(rhu_dec(dec(cases) * case_pack, 2))
        suggestions.append(entry)
    return suggestions
