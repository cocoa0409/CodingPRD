"""Customer, warehouse and demand-bucket routes."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, ZERO, q2, q4, respond, touch
from errors import fail
from schema import add_schema, body_json, coerce, enum_filter, str_filter

bp = Blueprint("party", __name__)

CUSTOMER_CREATE = {
    "customer_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "email": {"type": "string", "required": True, "min_len": 3, "max_len": 200},
    "region_code": {"type": "string", "required": True, "min_len": 2, "max_len": 8},
}

ACK_SPEC = {"acknowledged_at": {"type": "ts", "required": True}}
SUSPEND_SPEC = {"suspend_reason": {"type": "string", "required": True,
                                   "min_len": 1, "max_len": 500}}


@bp.route("/customers", methods=["POST"])
def create_customer():
    auth.authenticate(("PlantAdmin", "LogisticsPlanner"))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, CUSTOMER_CREATE)

    def email_shape():
        if "@" not in body["email"]:
            fail("ERR_VALIDATION", "email must contain an '@' character.")

    checks.add(20.5, email_shape)
    checks.add(26, lambda: rt.unique_code("customers", "customer_code",
                                          body.get("customer_code")))
    checks.run()
    row = coerce(body, CUSTOMER_CREATE)
    row["storage_guidance_acknowledged_at"] = None
    row["status"] = "ACTIVE"
    core.insert("customers", row)
    return rt.one("customers", row, 201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    auth.authenticate(("PlantAdmin", "LogisticsPlanner", "WarrantyAgent"))
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("customers")
        rows = rt.filter_eq(rows, "region_code", str_filter("region_code"))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.PERSON_STATUSES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("customers", items[0])


@bp.route("/customers/<customer_id>", methods=["GET"])
def read_customer(customer_id):
    ctx = auth.authenticate(("PlantAdmin", "LogisticsPlanner", "WarrantyAgent",
                             "Customer"))
    checks = Checks()
    holder = {}
    checks.add(6, lambda: auth.scope_customer_row(ctx, S.customers.get(customer_id)))
    checks.add(10, lambda: holder.update(row=rt.find("customers", customer_id)))
    checks.run()
    return rt.one("customers", holder["row"])


@bp.route("/customers/<customer_id>/acknowledge-storage-guidance", methods=["POST"])
def acknowledge_guidance(customer_id):
    ctx = auth.authenticate(("PlantAdmin", "LogisticsPlanner", "Customer"))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(6, lambda: auth.scope_customer_row(ctx, S.customers.get(customer_id)))
    checks.add(10, lambda: holder.update(row=rt.find("customers", customer_id)))
    add_schema(checks, body, ACK_SPEC)
    checks.run()
    customer = holder["row"]
    customer["storage_guidance_acknowledged_at"] = coerce(body, ACK_SPEC)[
        "acknowledged_at"]
    touch(customer)
    return rt.one("customers", customer)


@bp.route("/customers/<customer_id>/suspend", methods=["POST"])
def suspend_customer(customer_id):
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("customers", customer_id)))
    add_schema(checks, body, SUSPEND_SPEC)

    def state():
        if holder["row"]["status"] != "ACTIVE":
            fail("ERR_CUSTOMER_NOT_ACTIVE", "Customer is already SUSPENDED.")

    checks.add(60, state)
    checks.run()
    customer = holder["row"]
    customer["status"] = "SUSPENDED"
    customer["suspend_reason"] = body["suspend_reason"]
    touch(customer)
    svc.void_open_claims(customer)
    return rt.one("customers", customer)


@bp.route("/customers/<customer_id>/reinstate", methods=["POST"])
def reinstate_customer(customer_id):
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("customers", customer_id)))
    add_schema(checks, body, {})

    def state():
        if holder["row"]["status"] != "SUSPENDED":
            fail("ERR_CUSTOMER_ALREADY_ACTIVE", "Customer is already ACTIVE.")

    checks.add(60, state)
    checks.run()
    customer = holder["row"]
    customer["status"] = "ACTIVE"
    touch(customer)
    return rt.one("customers", customer)


# --------------------------------------------------------------------------
# Warehouses.
# --------------------------------------------------------------------------
WAREHOUSE_CREATE = {
    "site_code": {"type": "string", "required": True, "min_len": 2, "max_len": 32},
    "footprint_capacity_cube_m3": {"type": "dec", "places": 4, "required": True, "gt": 0},
    "zones": {"type": "array", "required": True, "min_items": 1, "max_items": 12},
    "restricted_threshold_pct": {"type": "dec", "places": 2, "gt": 0, "max": 100,
                                 "default": "85.00"},
    "frozen_threshold_pct": {"type": "dec", "places": 2, "gt": 0, "max": 100,
                             "default": "95.00"},
}


def _zone_shapes(body):
    """Ladder rung 20 for the zones array: every element is an object with a
    2-16 character zone_code and a positive four-decimal capacity."""
    for element in body.get("zones") or []:
        if not isinstance(element, dict):
            fail("ERR_VALIDATION", "Each zones element must be an object.")
        code = element.get("zone_code")
        cap = element.get("capacity_cube_m3")
        if not isinstance(code, str) or not 2 <= len(code) <= 16:
            fail("ERR_VALIDATION", "zone_code must be 2 to 16 characters.")
        if isinstance(cap, bool) or not isinstance(cap, (int, Decimal, float)):
            fail("ERR_VALIDATION", "capacity_cube_m3 must be a number.")
        cap = Decimal(str(cap))
        if core.dec_places(cap) > 4:
            fail("ERR_VALIDATION", "capacity_cube_m3 carries more than 4 decimals.")
        if cap <= 0:
            fail("ERR_INVALID_QUANTITY", "capacity_cube_m3 must be greater than zero.")


def _zone_codes_unique(body):
    seen = []
    for element in body.get("zones") or []:
        code = element.get("zone_code")
        if code in seen:
            fail("ERR_DUPLICATE_CODE", "zone_code '%s' repeats within the site." % code)
        seen.append(code)


def _thresholds(values):
    if values["restricted_threshold_pct"] >= values["frozen_threshold_pct"]:
        fail("ERR_INVALID_QUANTITY",
             "restricted_threshold_pct must be strictly below frozen_threshold_pct.")


def _capacity_sum(body):
    total = ZERO
    for element in body.get("zones") or []:
        total += Decimal(str(element.get("capacity_cube_m3")))
    if q4(total) != q4(Decimal(str(body["footprint_capacity_cube_m3"]))):
        fail("ERR_VALIDATION",
             "footprint_capacity_cube_m3 must equal the sum of the zone capacities.")


@bp.route("/warehouses", methods=["POST"])
def create_warehouse():
    auth.authenticate(("PlantAdmin", "LogisticsPlanner"))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, WAREHOUSE_CREATE)
    checks.add(20.5, lambda: _zone_shapes(body))
    checks.add(22.5, lambda: _thresholds(coerce(body, WAREHOUSE_CREATE)))
    checks.add(23.5, lambda: _capacity_sum(body))
    checks.add(26, lambda: rt.unique_code("warehouses", "site_code",
                                          body.get("site_code")))
    checks.add(26.5, lambda: _zone_codes_unique(body))
    checks.run()
    row = coerce(body, WAREHOUSE_CREATE)
    row["zones"] = [
        {"zone_code": z["zone_code"],
         "capacity_cube_m3": q4(Decimal(str(z["capacity_cube_m3"])))}
        for z in body["zones"]
    ]
    row["committed_cube_m3"] = q4(ZERO)
    row["utilization_pct"] = q2(ZERO)
    row["posture"] = "NORMAL"
    core.insert("warehouses", row)
    return rt.one("warehouses", row, 201)


@bp.route("/warehouses", methods=["GET"])
def list_warehouses():
    auth.authenticate(("PlantAdmin", "LogisticsPlanner", "QualityInspector"))
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("warehouses")
        rows = rt.filter_eq(rows, "posture", enum_filter("posture", rt.POSTURES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("warehouses", items[0])


@bp.route("/warehouses/<warehouse_id>", methods=["GET"])
def read_warehouse(warehouse_id):
    auth.authenticate(("PlantAdmin", "LogisticsPlanner", "QualityInspector"))
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("warehouses", warehouse_id)))
    checks.run()
    return rt.one("warehouses", holder["row"])


@bp.route("/warehouses/<warehouse_id>/footprint-summary", methods=["GET"])
def warehouse_footprint_summary(warehouse_id):
    auth.authenticate(("PlantAdmin", "LogisticsPlanner"))
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("warehouses", warehouse_id)))
    checks.run()
    site = holder["row"]
    capacity = site["footprint_capacity_cube_m3"]
    committed = calc.warehouse_committed_cube(site)
    utilization = q2(committed / capacity * Decimal(100))
    zones = []
    for zone in site["zones"]:
        code = zone["zone_code"]
        zone_committed = calc.zone_committed_cube(site["id"], code)
        anchors = []
        stored = 0
        for unit in core.sorted_rows(calc.occupying_units(site["id"])):
            if unit.get("storage_zone_code") != code:
                continue
            stored += 1
            if unit.get("is_zone_anchor") and unit["product_model_id"] not in anchors:
                anchors.append(unit["product_model_id"])
        zones.append({
            "zone_code": code,
            "capacity_cube_m3": zone["capacity_cube_m3"],
            "committed_cube_m3": zone_committed,
            "remaining_cube_m3": q4(zone["capacity_cube_m3"] - zone_committed),
            "anchor_product_model_ids": anchors,
            "stored_unit_count": stored,
        })
    blocked = sum(1 for o in core.rows("production_orders")
                  if o["target_warehouse_id"] == site["id"]
                  and o["status"] == "BLOCKED_WAREHOUSE")
    return respond({
        "warehouse_id": site["id"],
        "footprint_capacity_cube_m3": capacity,
        "committed_cube_m3": committed,
        "remaining_cube_m3": q4(capacity - committed),
        "utilization_pct": utilization,
        "posture": calc.derive_posture(utilization, site),
        "zones": zones,
        "blocked_production_order_count": blocked,
    })


# --------------------------------------------------------------------------
# Demand forecast buckets.
# --------------------------------------------------------------------------
BUCKET_CREATE = {
    "season_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "product_model_id": {"type": "string", "required": True},
    "forecast_qty": {"type": "int", "required": True, "min": 1},
    "build_ahead_cap_pct": {"type": "dec", "places": 2, "gt": 0, "max": 100,
                            "default": "60.00"},
    "window_start_on": {"type": "date", "required": True},
    "window_end_on": {"type": "date", "required": True},
}


@bp.route("/demand-forecast-buckets", methods=["POST"])
def create_bucket():
    auth.authenticate(("PlantAdmin", "LogisticsPlanner"))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, BUCKET_CREATE)
    checks.add(11, lambda: rt.find("product_models", body.get("product_model_id")))

    def window():
        values = coerce(body, BUCKET_CREATE)
        if values["window_end_on"] < values["window_start_on"]:
            fail("ERR_INVALID_WINDOW", "window_end_on precedes window_start_on.")

    checks.add(24, window)
    checks.add(26, lambda: rt.unique_code(
        "demand_buckets", "season_code", body.get("season_code"),
        scope=lambda r: r["product_model_id"] == body.get("product_model_id")))
    checks.run()
    row = coerce(body, BUCKET_CREATE)
    row["build_ahead_cap_qty"] = core.floor_int(
        Decimal(row["forecast_qty"]) * row["build_ahead_cap_pct"] / Decimal(100))
    row["build_ahead_committed_qty"] = 0
    core.insert("demand_buckets", row)
    return rt.one("demand_buckets", row, 201)


@bp.route("/demand-forecast-buckets", methods=["GET"])
def list_buckets():
    auth.authenticate(("PlantAdmin", "LogisticsPlanner", "MoldingOperator"))
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("demand_buckets")
        rows = rt.filter_eq(rows, "product_model_id", str_filter("product_model_id"))
        rows = rt.filter_eq(rows, "season_code", str_filter("season_code"))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("demand_buckets", items[0])


@bp.route("/demand-forecast-buckets/<demand_forecast_bucket_id>", methods=["GET"])
def read_bucket(demand_forecast_bucket_id):
    auth.authenticate(("PlantAdmin", "LogisticsPlanner", "MoldingOperator"))
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("demand_buckets", demand_forecast_bucket_id)))
    checks.run()
    return rt.one("demand_buckets", holder["row"])
