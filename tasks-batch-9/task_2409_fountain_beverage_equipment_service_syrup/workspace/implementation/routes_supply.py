"""The SKU catalogue, telemetry ingestion, stock positions and forecasting
(PRD 3.4 and 3.6)."""

from decimal import Decimal

from flask import Blueprint, g

from calc import OUNCES_PER_GALLON, outlet_supply_forecast
from cascade import bump_overdue
from core import (
    ALERT_LEVELS,
    FORECAST_VARIANTS,
    SUPPLY_FORMS,
    TELEMETRY_SOURCES,
    D,
    body,
    db,
    endpoint,
    f_bool,
    f_dt,
    f_int,
    f_num,
    f_str,
    fail,
    get_item,
    get_outlet,
    get_position,
    get_reading,
    get_unit,
    interval_ok,
    new_id,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    parse_dt,
    present,
    q_dt,
    q_str,
    require,
    require_outlet_ownership,
    round_half_up,
    sort_rows,
    stamp_new,
    touch,
)
from serialize import ser_item, ser_position, ser_reading

bp = Blueprint("supply", __name__)


# ===========================================================================
# Supply items
# ===========================================================================
@bp.post("/supply-items")
@endpoint(["NetworkAdmin"])
def create_item():
    payload = body()
    # rung 3
    sku_code = f_str(payload, "sku_code", required=True)
    brand_name = f_str(payload, "brand_name", required=True)
    supply_form = f_str(payload, "supply_form", required=True, enum=SUPPLY_FORMS)
    case_pack_units = f_int(payload, "case_pack_units", required=True, ge=1)
    ounces_per_unit = f_num(payload, "ounces_per_unit", required=True, gt=0)
    promotional = f_bool(payload, "promotional", default=False)
    promo_start_raw, promo_start = f_dt(payload, "promo_window_start")
    promo_end_raw, promo_end = f_dt(payload, "promo_window_end")
    national_allocation_units = f_int(payload, "national_allocation_units", default=0, ge=0)
    # rung 21
    interval_ok(promo_start, promo_end)
    # rung 30
    for row in db.supply_items.values():
        if row["sku_code"] == sku_code:
            fail("ERR_DUPLICATE_SKU_CODE", "SKU code %s already exists." % sku_code)

    item = {
        "id": new_id(),
        "sku_code": sku_code,
        "brand_name": brand_name,
        "supply_form": supply_form,
        "case_pack_units": case_pack_units,
        "ounces_per_unit": ounces_per_unit,
        "promotional": promotional,
        "promo_window_start": promo_start_raw,
        "promo_window_end": promo_end_raw,
        "_promo_start": promo_start,
        "_promo_end": promo_end,
        "national_allocation_units": national_allocation_units,
        "reserved_pool_units": 0,
    }
    stamp_new(item)
    db.supply_items[item["id"]] = item
    return ok(ser_item(item), 201)


@bp.get("/supply-items/<iid>")
@endpoint(["NetworkAdmin", "SupplyPlanner", "RouteDriver", "OutletManager"])
def read_item(iid):
    return ok(ser_item(get_item(iid)))


@bp.patch("/supply-items/<iid>")
@endpoint(["NetworkAdmin"])
def patch_item(iid):
    payload = body()
    # rung 3
    national_allocation_units = f_int(payload, "national_allocation_units", ge=0)
    promo_start_raw, promo_start = f_dt(payload, "promo_window_start")
    promo_end_raw, promo_end = f_dt(payload, "promo_window_end")
    has_start = present(payload, "promo_window_start")
    has_end = present(payload, "promo_window_end")
    # rung 4
    item = get_item(iid)
    # rung 21 - validated against the merged (patched + stored) window
    merged_start = promo_start if has_start else item["_promo_start"]
    merged_end = promo_end if has_end else item["_promo_end"]
    interval_ok(merged_start, merged_end)
    # outside the ladder: the single-field guard of PRD 2.6
    if national_allocation_units is not None:
        require(
            national_allocation_units >= item["reserved_pool_units"],
            "ERR_POOL_BELOW_RESERVED",
            "national_allocation_units may not fall below reserved_pool_units (%s)."
            % item["reserved_pool_units"],
        )
        item["national_allocation_units"] = national_allocation_units
    if has_start:
        item["promo_window_start"] = promo_start_raw
        item["_promo_start"] = promo_start
    if has_end:
        item["promo_window_end"] = promo_end_raw
        item["_promo_end"] = promo_end
    touch(item)
    return ok(ser_item(item))


# ===========================================================================
# Telemetry readings
# ===========================================================================
@bp.post("/telemetry-readings")
@endpoint(["SupplyPlanner", "ServiceTechnician"])
def create_reading():
    payload = body()
    # rung 3
    unit_id = f_str(payload, "dispenser_unit_id", required=True)
    item_id = f_str(payload, "supply_item_id", required=True)
    dispensed_ounces = f_num(payload, "dispensed_ounces", required=True, ge=0)
    reading_raw, reading_at = f_dt(payload, "reading_at", required=True)
    window_days = f_int(payload, "window_days", default=7, ge=1, le=90)
    source = f_str(payload, "source", default="TELEMETRY", enum=TELEMETRY_SOURCES)
    # rung 5
    unit = get_unit(unit_id)
    item = get_item(item_id)
    # rung 20
    require(
        reading_at <= now(),
        "ERR_TIMESTAMP_IN_FUTURE",
        "reading_at must be at or before the logical clock.",
    )

    reading = {
        "id": new_id(),
        "dispenser_unit_id": unit["id"],
        "supply_item_id": item["id"],
        "dispensed_ounces": dispensed_ounces,
        "reading_at": reading_raw,
        "_reading_at": reading_at,
        "window_days": window_days,
        "source": source,
        "created_at": None,
    }
    stamp_new(reading)
    # a telemetry reading is an immutable event: no updated_at, no version
    reading.pop("updated_at", None)
    reading.pop("version", None)
    db.readings[reading["id"]] = reading

    # the machine's odometer
    unit["_total_ounces"] = D(unit.get("_total_ounces", 0)) + D(dispensed_ounces)
    unit["lifetime_dispensed_gallons"] = round_half_up(
        D(unit["_total_ounces"]) / OUNCES_PER_GALLON, 2
    )
    touch(unit)

    # re-evaluate the unit's SCHEDULED FILTER_CHANGE tasks on the volume limb
    outlet = db.outlets.get(unit["outlet_id"])
    tasks = sort_rows(
        [
            t
            for t in db.tasks.values()
            if t["dispenser_unit_id"] == unit["id"]
            and t["status"] == "SCHEDULED"
            and t["task_type"] == "FILTER_CHANGE"
        ]
    )
    for task in tasks:
        eff = task.get("effective_gallon_interval")
        if eff is None:
            continue
        since = D(unit["lifetime_dispensed_gallons"]) - D(unit["gallons_at_last_filter_change"])
        if since >= D(eff):
            task["status"] = "OVERDUE"
            task["breach_kind"] = "GALLON"
            touch(task)
            if outlet is not None:
                bump_overdue(outlet, 1)
    return ok(ser_reading(reading), 201)


@bp.get("/telemetry-readings/<rid>")
@endpoint(["NetworkAdmin", "SupplyPlanner", "ServiceTechnician", "ComplianceOfficer"])
def read_reading(rid):
    return ok(ser_reading(get_reading(rid)))


@bp.get("/telemetry-readings")
@endpoint(["NetworkAdmin", "SupplyPlanner", "ServiceTechnician", "ComplianceOfficer"])
def list_readings():
    limit, offset = pagination()
    unit_id = q_str("dispenser_unit_id")
    item_id = q_str("supply_item_id")
    at_from = q_dt("reading_at_from")
    at_to = q_dt("reading_at_to")
    rows = list(db.readings.values())
    if unit_id is not None:
        rows = [r for r in rows if r["dispenser_unit_id"] == unit_id]
    if item_id is not None:
        rows = [r for r in rows if r["supply_item_id"] == item_id]
    if at_from is not None:
        rows = [r for r in rows if r["_reading_at"] >= at_from]
    if at_to is not None:
        rows = [r for r in rows if r["_reading_at"] <= at_to]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_reading(r) for r in page], limit, offset, total)


# ===========================================================================
# Outlet supply positions
# ===========================================================================
@bp.post("/supply-positions")
@endpoint(["SupplyPlanner"])
def create_position():
    payload = body()
    # rung 3
    outlet_id = f_str(payload, "outlet_id", required=True)
    item_id = f_str(payload, "supply_item_id", required=True)
    on_hand_units = f_int(payload, "on_hand_units", default=0, ge=0)
    # rung 5
    outlet = get_outlet(outlet_id)
    item = get_item(item_id)
    # rung 30
    for row in db.positions.values():
        if row["outlet_id"] == outlet["id"] and row["supply_item_id"] == item["id"]:
            fail(
                "ERR_DUPLICATE_SUPPLY_POSITION",
                "A supply position already exists for this outlet and SKU.",
            )

    position = {
        "id": new_id(),
        "outlet_id": outlet["id"],
        "supply_item_id": item["id"],
        "on_hand_units": on_hand_units,
        "forecast_variant": "TRAILING_ACTUAL",
        "forecast_units": 0,
        "requested_units": 0,
        "allocated_units": 0,
        "planned_route_stop_id": None,
        "alert_level": "NONE",
        "promo_suppressed": False,
        "alert_acknowledged_by_user_id": None,
        "_daily_ounces": Decimal(0),
    }
    stamp_new(position)
    db.positions[position["id"]] = position
    return ok(ser_position(position), 201)


@bp.get("/supply-positions/<pid>")
@endpoint(["NetworkAdmin", "SupplyPlanner", "RouteDriver", "OutletManager"])
def read_position(pid):
    return ok(ser_position(get_position(pid)))


@bp.get("/supply-positions")
@endpoint(["NetworkAdmin", "SupplyPlanner", "RouteDriver", "OutletManager"])
def list_positions():
    limit, offset = pagination()
    outlet_id = q_str("outlet_id")
    item_id = q_str("supply_item_id")
    stop_id = q_str("planned_route_stop_id")
    alert_level = q_str("alert_level", enum=ALERT_LEVELS)
    rows = list(db.positions.values())
    if outlet_id is not None:
        rows = [r for r in rows if r["outlet_id"] == outlet_id]
    if item_id is not None:
        rows = [r for r in rows if r["supply_item_id"] == item_id]
    if stop_id is not None:
        rows = [r for r in rows if r["planned_route_stop_id"] == stop_id]
    if alert_level is not None:
        rows = [r for r in rows if r["alert_level"] == alert_level]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_position(r) for r in page], limit, offset, total)


@bp.post("/supply-positions/<pid>/forecast")
@endpoint(["SupplyPlanner"])
def run_forecast(pid):
    payload = body()
    # rung 3
    variant = f_str(payload, "variant", required=True, enum=FORECAST_VARIANTS)
    window_days = f_int(payload, "window_days", required=True, ge=1)
    # rung 4
    position = get_position(pid)
    item = db.supply_items[position["supply_item_id"]]
    outlet = db.outlets[position["outlet_id"]]

    result = outlet_supply_forecast(position, item, outlet, variant, window_days, now())
    position["forecast_variant"] = variant
    position["forecast_units"] = result["forecast_units"]
    position["requested_units"] = result["requested_units"]
    position["alert_level"] = result["alert_level"]
    position["promo_suppressed"] = result["promo_suppressed"]
    position["alert_acknowledged_by_user_id"] = None
    position["_daily_ounces"] = result["daily_ounces"]
    touch(position)
    return ok(ser_position(position))


@bp.post("/supply-positions/<pid>/acknowledge-alert")
@endpoint(["OutletManager"])
def acknowledge_alert(pid):
    # rung 4
    position = get_position(pid)
    # rung 6
    require_outlet_ownership(position["outlet_id"])
    position["alert_acknowledged_by_user_id"] = g.user_id
    touch(position)
    return ok(ser_position(position))
