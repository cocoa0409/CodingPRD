"""Business logic services: calculations, weather gating, cascades, lazy evaluation."""

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from clock import now, parse_iso, format_iso_ms, today_date
from db import DB
from errors import (
    err,
    ERR_ASSESSMENT_EXPIRED,
    ERR_ASSESSMENT_NOT_USABLE,
    ERR_WEATHER_DATA_MISSING,
    ERR_WEATHER_WINDOW_VIOLATION,
    ERR_QUOTE_EXPIRED,
    ERR_WARRANTY_EXPIRED,
)
from middleware import round_half_up_decimal, add_months


# -------------------- calculations --------------------

GRADE_FACTORS = {"STANDARD": Decimal("1.00"), "PREMIUM": Decimal("1.35"), "ECO": Decimal("1.15")}


def pavement_condition_index(measured_area_sqft, crack_linear_ft, pothole_area_sqft,
                              oil_spot_area_sqft, slope_severity):
    d_crack = min(40, round_half_up_decimal(Decimal(str(crack_linear_ft)) / Decimal(str(measured_area_sqft)) * Decimal(400)))
    d_pothole = min(35, round_half_up_decimal(Decimal(str(pothole_area_sqft)) / Decimal(str(measured_area_sqft)) * Decimal(700)))
    d_oil = min(15, round_half_up_decimal(Decimal(str(oil_spot_area_sqft)) / Decimal(str(measured_area_sqft)) * Decimal(300)))
    d_slope = 10 if slope_severity == "STEEP" else (5 if slope_severity == "MODERATE" else 0)
    return max(0, 100 - d_crack - d_pothole - d_oil - d_slope)


def seal_rate_cents(area):
    """Average-rate tiering on total area."""
    if area <= 1000:
        return 30
    elif area <= 5000:
        return 24
    else:
        return 18


def material_gallons_required(area_sqft, coats, coverage_sqft_per_gallon, include_seal):
    if not include_seal:
        return 0
    numer = Decimal(str(area_sqft)) * Decimal(int(coats)) * Decimal("1.10")
    res = numer / Decimal(str(coverage_sqft_per_gallon))
    return int(res.to_integral_value(rounding="ROUND_CEILING"))


def price_lines(area, crack_ft, pothole_area, stripe_ft, include_seal, include_crack_fill,
                include_patch, include_striping, coats, grade):
    """Per-line rounded pricing per calculations.job_pricing."""
    seal_line = 0
    if include_seal:
        rate = seal_rate_cents(area)
        val = Decimal(str(area)) * Decimal(rate) * GRADE_FACTORS[grade] * Decimal(int(coats))
        seal_line = round_half_up_decimal(val)
    crack_line = round_half_up_decimal(Decimal(str(crack_ft)) * Decimal(150)) if include_crack_fill else 0
    patch_line = round_half_up_decimal(Decimal(str(pothole_area)) * Decimal(800)) if include_patch else 0
    striping_line = round_half_up_decimal(Decimal(str(stripe_ft)) * Decimal(90)) if include_striping else 0
    return seal_line, crack_line, patch_line, striping_line


def quote_pricing(area, crack_ft, pothole_area, stripe_ft, include_seal, include_crack_fill,
                  include_patch, include_striping, coats, grade, discount_pct,
                  material_coverage, material_price_per_gallon_cents):
    """Provisional quote pricing; returns dict of computed fields. Raises ERR_PRICE_BELOW_COST_FLOOR."""
    seal_line, crack_line, patch_line, striping_line = price_lines(
        area, crack_ft, pothole_area, stripe_ft,
        include_seal, include_crack_fill, include_patch, include_striping, coats, grade,
    )
    subtotal = seal_line + crack_line + patch_line + striping_line
    discount = round_half_up_decimal(Decimal(subtotal) * Decimal(str(discount_pct)))
    mobilization = 7500 if (subtotal - discount) < 200000 else 0
    total = max(subtotal - discount + mobilization, 25000)
    # cost floor check
    material_cost = 0
    if include_seal:
        gallons = material_gallons_required(area, coats, material_coverage, True)
        material_cost = gallons * int(material_price_per_gallon_cents)
    labor_floor = round_half_up_decimal(Decimal(str(area)) * Decimal(5))
    floor = material_cost + labor_floor
    from errors import ERR_PRICE_BELOW_COST_FLOOR
    if total < floor:
        raise err(ERR_PRICE_BELOW_COST_FLOOR, 422, "Discounted quote total below material-cost + labor floor")
    return {
        "seal_line_cents": seal_line,
        "crack_line_cents": crack_line,
        "patch_line_cents": patch_line,
        "striping_line_cents": striping_line,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "mobilization_fee_cents": mobilization,
        "total_cents": total,
    }


def invoice_settlement(wo, material_grade):
    """Final pricing on actuals per calculations.invoice_settlement. Returns (line_items, subtotal, surcharge, total)."""
    include_seal = wo["include_seal"]
    include_crack_fill = wo["include_crack_fill"]
    include_patch = wo["include_patch"]
    include_striping = wo["include_striping"]
    coats = wo["coats"]

    if wo["warranty_claim_id"] is not None:
        # Warranty repair: every line zeroed, total 0
        line_items = []
        if include_seal:
            line_items.append({"label": "seal", "amount_cents": 0})
        if include_crack_fill:
            line_items.append({"label": "crack_fill", "amount_cents": 0})
        if include_patch:
            line_items.append({"label": "patch", "amount_cents": 0})
        if include_striping:
            line_items.append({"label": "striping", "amount_cents": 0})
        line_items.append({"label": "mobilization", "amount_cents": 0})
        return line_items, 0, 0, 0

    seal_line, crack_line, patch_line, striping_line = price_lines(
        wo["actual_area_sqft"], wo["actual_crack_ft"], wo["actual_pothole_area_sqft"],
        wo["actual_stripe_ft"], include_seal, include_crack_fill, include_patch,
        include_striping, coats, material_grade,
    )
    line_items = []
    if include_seal:
        line_items.append({"label": "seal", "amount_cents": seal_line})
    if include_crack_fill:
        line_items.append({"label": "crack_fill", "amount_cents": crack_line})
    if include_patch:
        line_items.append({"label": "patch", "amount_cents": patch_line})
    if include_striping:
        line_items.append({"label": "striping", "amount_cents": striping_line})

    lines_sum = seal_line + crack_line + patch_line + striping_line
    mobilization = 7500 if lines_sum < 200000 else 0
    line_items.append({"label": "mobilization", "amount_cents": mobilization})
    subtotal = lines_sum + mobilization

    if subtotal < 100000:
        pct = Decimal("0.06")
    elif subtotal < 500000:
        pct = Decimal("0.04")
    else:
        pct = Decimal("0.02")
    surcharge = round_half_up_decimal(Decimal(subtotal) * pct)
    total = subtotal + surcharge
    return line_items, subtotal, surcharge, total


def latest_weather_snapshot(target_date_str):
    """Latest snapshot for a date: created_at DESC, OBSERVED preferred over FORECAST on ties."""
    candidates = [s for s in DB.weather_snapshots.values() if s["target_date"] == target_date_str]
    if not candidates:
        return None
    # OBSERVED preferred on ties; treat OBSERVED as 0, FORECAST as 1 for sort
    def key(s):
        src_rank = 0 if s["source"] == "OBSERVED" else 1
        # We want created_at DESC and src_rank ASC -> use negative-ish approach via tuple
        return (s["created_at"], -src_rank)  # careful: we sort ascending then pick last
    # Sort by created_at asc, then source preference (OBSERVED later so it wins ties)
    candidates.sort(key=lambda s: (s["created_at"], 0 if s["source"] == "FORECAST" else 1))
    return candidates[-1]


def weather_gate(material, date_str):
    """Raises ERR_WEATHER_DATA_MISSING / ERR_WEATHER_WINDOW_VIOLATION as applicable."""
    snap = latest_weather_snapshot(date_str)
    if snap is None:
        raise err(ERR_WEATHER_DATA_MISSING, 422, "No weather snapshot exists for the service date")
    if snap["min_temp_f"] < material["min_apply_temp_f"] or \
       snap["precip_probability_pct"] > material["max_precip_probability_pct"]:
        raise err(ERR_WEATHER_WINDOW_VIOLATION, 422,
                  "Latest snapshot fails the material's temperature/precipitation thresholds")
    return snap


def cure_hours(material, date_str):
    """Provisional/observed cure projection per calculations.cure_window_projection."""
    base = int(material["cure_hours_vehicle"])
    snap = latest_weather_snapshot(date_str)
    if snap is None:
        return base
    hours = base
    if snap["min_temp_f"] < 55:
        hours = int((Decimal(str(base)) * Decimal("1.5")).to_integral_value(rounding="ROUND_CEILING"))
    if snap["precipitation_mm"] > 0:
        hours = hours + 12
    return hours


def ada_stall_requirement(stall_count):
    n = int(stall_count)
    if n <= 25:
        ada = 1
    elif n <= 50:
        ada = 2
    elif n <= 75:
        ada = 3
    elif n <= 100:
        ada = 4
    else:
        ada = 4 + math.ceil((n - 100) / 50)
    return ada


# -------------------- lazy evaluations --------------------

def lazy_assessment_expiry(assessment):
    """If SUBMITTED and past 30-day shelf life, flip to EXPIRED. Returns the (possibly updated) assessment."""
    if assessment["status"] == "SUBMITTED" and assessment["submitted_at"] is not None:
        sub_dt = parse_iso(assessment["submitted_at"])
        if now().date() > (sub_dt.date() + timedelta(days=30)):
            assessment["status"] = "EXPIRED"
            assessment["updated_at"] = format_iso_ms(now())
            assessment["version"] += 1
    return assessment


def check_assessment_usable_for_quote(assessment):
    """For quote create/send: raise the right error if assessment is not usable."""
    lazy_assessment_expiry(assessment)
    if assessment["status"] == "EXPIRED":
        raise err(ERR_ASSESSMENT_EXPIRED, 422, "Assessment older than 30 days flips to EXPIRED when referenced")
    if assessment["status"] != "SUBMITTED":
        raise err(ERR_ASSESSMENT_NOT_USABLE, 422,
                  "Quote send requires the pinned assessment to still be SUBMITTED")


def lazy_quote_expiry(quote):
    """If SENT and past expires_on, flip to EXPIRED and clear property open_quote_id."""
    if quote["status"] == "SENT" and quote["expires_on"] is not None:
        exp = parse_iso(quote["expires_on"]).date() if "T" in quote["expires_on"] else datetime.strptime(quote["expires_on"], "%Y-%m-%d").date()
        if today_date() > exp:
            quote["status"] = "EXPIRED"
            quote["updated_at"] = format_iso_ms(now())
            quote["version"] += 1
            prop = DB.properties.get(quote["property_id"])
            if prop is not None and prop["open_quote_id"] == quote["id"]:
                prop["open_quote_id"] = None
                prop["updated_at"] = format_iso_ms(now())
                prop["version"] += 1
            return True
    return False


def check_quote_not_expired(quote):
    """Raises ERR_QUOTE_EXPIRED if the quote lazily expires at this moment."""
    if lazy_quote_expiry(quote):
        raise err(ERR_QUOTE_EXPIRED, 409, "Quote past expires_on flips to EXPIRED when acted upon")


def lazy_warranty_expiry(record):
    """If ACTIVE and past expires_on, flip to EXPIRED."""
    if record["status"] == "ACTIVE" and record["expires_on"] is not None:
        exp = datetime.strptime(record["expires_on"], "%Y-%m-%d").date()
        if today_date() > exp:
            record["status"] = "EXPIRED"
            record["updated_at"] = format_iso_ms(now())
            record["version"] += 1
            return True
    return False


def check_warranty_active(record):
    """Raises ERR_WARRANTY_EXPIRED on lazy expiry flip."""
    if lazy_warranty_expiry(record):
        raise err(ERR_WARRANTY_EXPIRED, 409, "Claim after expires_on flips the record to EXPIRED")


def lazy_route_sheet_completion(sheet):
    """If past service date and no active WOs, settle to COMPLETED."""
    if sheet["status"] in ("OPEN", "PUBLISHED"):
        svc = datetime.strptime(sheet["service_date"], "%Y-%m-%d").date()
        if today_date() > svc:
            active_statuses = {"SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS", "CURING"}
            has_active = any(
                wo["route_sheet_id"] == sheet["id"] and wo["execution_status"] in active_statuses
                for wo in DB.work_orders.values()
            )
            if not has_active:
                sheet["status"] = "COMPLETED"
                sheet["updated_at"] = format_iso_ms(now())
                sheet["version"] += 1
    return sheet


# -------------------- property / customer helpers --------------------

def property_of_quote(quote):
    return DB.properties.get(quote["property_id"])


def property_of_work_order(wo):
    return DB.properties.get(wo["property_id"])


def customer_owns_property(user_id, prop):
    return prop is not None and prop["customer_id"] == user_id


def find_open_quote_for_property(property_id):
    for q in DB.quotes.values():
        if q["property_id"] == property_id and q["status"] in ("DRAFT", "SENT", "REVISION_REQUESTED"):
            return q
    return None


# -------------------- cascades --------------------

def refresh_material_lot(lot):
    """Recompute on_hand, reorder_flag, and DEPLETED/RECEIVED transitions."""
    lot["on_hand_gallons"] = (
        lot["delivered_gallons"] - lot["reserved_gallons"] - lot["consumed_gallons"] - lot["wasted_gallons"]
    )
    lot["reorder_flag"] = lot["on_hand_gallons"] <= lot["reorder_threshold_gallons"]
    # Status transitions
    if lot["status"] in ("RECEIVED", "IN_USE"):
        if lot["on_hand_gallons"] == 0 and lot["reserved_gallons"] == 0:
            lot["status"] = "DEPLETED"
        elif lot["status"] == "IN_USE" and lot["reserved_gallons"] == 0 and lot["consumed_gallons"] == 0:
            lot["status"] = "RECEIVED"
    lot["updated_at"] = format_iso_ms(now())
    lot["version"] += 1


def refresh_route_sheet(sheet):
    """Recompute booked_sqft, total_drive_minutes, open_capacity_sqft from scratch."""
    included = {"SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS", "CURING", "COMPLETED"}
    booked = 0
    drive = 0
    for wo in DB.work_orders.values():
        if wo["route_sheet_id"] == sheet["id"] and wo["execution_status"] in included:
            booked += wo["quoted_area_sqft"] if wo["quoted_area_sqft"] is not None else 0
            drive += wo["drive_minutes_est"] if wo["drive_minutes_est"] is not None else 0
    sheet["booked_sqft"] = booked
    sheet["total_drive_minutes"] = drive
    sheet["open_capacity_sqft"] = sheet["capacity_sqft"] - booked
    sheet["updated_at"] = format_iso_ms(now())
    sheet["version"] += 1


def find_displacement_plan_for_work_order(wo_id):
    for p in DB.displacement_plans.values():
        if p["work_order_id"] == wo_id:
            return p
    return None


def date_at_hour_utc(date_str, hour):
    """Build an ISO timestamp at date_str T hour:00 UTC."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    dt = dt.replace(hour=int(hour), minute=0, second=0, microsecond=0)
    return format_iso_ms(dt)
