"""Shipment and ShipmentLine routes.

The trailer roll-ups (nest_position, both line cubes, the shipment cube, weight,
utilisation and density figures) are recomputed from scratch on every line
addition and removal, never patched incrementally, because removing a
position-1 line promotes a nested follower to full gross cube and can RAISE the
trailer's nested cube.  Departure - not sealing - is the event that frees
warehouse footprint, and it fires CASCADE-C once per vacated nest group.
"""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, ZERO, q2, q3, q4, touch
from errors import fail
from schema import add_schema, body_json, coerce, enum_filter, str_filter

bp = Blueprint("ship", __name__)

SHIP_READ = ("PlantAdmin", "LogisticsPlanner", "WarrantyAgent")
SHIP_READ_ONE = SHIP_READ + ("Customer",)
MIN_SEAL_UTILIZATION_PCT = Decimal("60.00")

SHIPMENT_CREATE = {
    "shipment_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "customer_id": {"type": "string", "required": False},
    "origin_warehouse_id": {"type": "string", "required": True},
    "destination_zone": {"type": "enum", "required": True, "values": rt.DEST_ZONES},
    "carrier_code": {"type": "string", "required": True, "min_len": 2, "max_len": 16},
    "trailer_cube_capacity_m3": {"type": "dec", "places": 4, "required": True, "gt": 0},
    "trailer_max_payload_kg": {"type": "dec", "places": 3, "required": True, "gt": 0},
}


def _snapshot(shipment):
    """Per-line values before a roll-up, so only rows that actually move are
    restamped and a freshly created line keeps version 1."""
    out = {}
    for line in calc.lines_of_shipment(shipment["id"], "LOADED"):
        out[line["id"]] = (line["nest_position"], line["line_gross_cube_m3"],
                           line["line_nested_cube_m3"], line["line_freight_cents"])
    return out


def _apply_rollup(shipment, before):
    lines = calc.shipment_rollup(shipment)
    for line in lines:
        after = (line["nest_position"], line["line_gross_cube_m3"],
                 line["line_nested_cube_m3"], line["line_freight_cents"])
        if line["id"] in before and before[line["id"]] != after:
            touch(line)
    return lines


def _loaded_units(shipment):
    units = []
    for line in calc.ordered_loaded_lines(shipment["id"]):
        unit = S.finished_units.get(line["finished_unit_id"])
        if unit is not None:
            units.append(unit)
    return units


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    auth.authenticate(("LogisticsPlanner",))
    body = body_json()
    checks = Checks()
    holder = {}
    add_schema(checks, body, SHIPMENT_CREATE)

    def resolve():
        holder["site"] = rt.find("warehouses", body.get("origin_warehouse_id"))
        supplied = body.get("customer_id")
        holder["customer"] = rt.find("customers", supplied) if supplied else None

    def customer_active():
        customer = holder["customer"]
        if customer is not None and customer["status"] != "ACTIVE":
            fail("ERR_CUSTOMER_NOT_ACTIVE", "The customer is suspended.")

    def posture_allows():
        site = holder["site"]
        if site["posture"] not in ("RESTRICTED", "FROZEN"):
            return
        remaining = q4(site["footprint_capacity_cube_m3"] - site["committed_cube_m3"])
        if q4(coerce(body, SHIPMENT_CREATE)["trailer_cube_capacity_m3"]) > remaining:
            fail("ERR_WAREHOUSE_POSTURE_RESTRICTED",
                 "A %s site cannot book a trailer larger than its remaining cube."
                 % site["posture"])

    checks.add(11, resolve)
    checks.add(26, lambda: rt.unique_code("shipments", "shipment_code",
                                          body.get("shipment_code")))
    checks.add(60, customer_active)
    checks.add(66, posture_allows)
    checks.run()
    row = coerce(body, SHIPMENT_CREATE)
    row["loaded_cube_m3"] = q4(ZERO)
    row["nested_cube_m3"] = q4(ZERO)
    row["loaded_weight_kg"] = q3(ZERO)
    row["cube_utilization_pct"] = q2(ZERO)
    row["density_kg_per_m3"] = q3(ZERO)
    row["quoted_freight_cents"] = None
    row["billed_freight_cents"] = None
    row["status"] = "PLANNED"
    row["sealed_at"] = None
    row["departed_at"] = None
    row["delivered_at"] = None
    core.insert("shipments", row)
    return rt.one("shipments", row, 201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    auth.authenticate(SHIP_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("shipments")
        rows = rt.filter_eq(rows, "origin_warehouse_id",
                            str_filter("origin_warehouse_id"))
        rows = rt.filter_eq(rows, "destination_zone",
                            enum_filter("destination_zone", rt.DEST_ZONES))
        rows = rt.filter_eq(rows, "carrier_code", str_filter("carrier_code"))
        rows = rt.filter_eq(rows, "status",
                            enum_filter("status", rt.SHIPMENT_STATUSES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("shipments", items[0])


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def read_shipment(shipment_id):
    ctx = auth.authenticate(SHIP_READ_ONE)
    checks = Checks()
    holder = {}
    checks.add(6, lambda: auth.scope_shipment(ctx, S.shipments.get(shipment_id)))
    checks.add(10, lambda: holder.update(row=rt.find("shipments", shipment_id)))
    checks.run()
    return rt.one("shipments", holder["row"])


# --------------------------------------------------------------------------
# Trailer transitions.  Ladder rungs: 41 (shipment status), 48 (missing quote),
# 49 (empty trailer), 68 (seal utilisation floor).
# --------------------------------------------------------------------------
UNSEAL_SPEC = {"unseal_reason": {"type": "string", "required": True,
                                 "min_len": 1, "max_len": 500}}
DEPART_SPEC = {"departed_at": {"type": "ts", "required": True}}
DELIVER_SPEC = {"delivered_at": {"type": "ts", "required": True}}
CANCEL_SPEC = {"cancel_reason": {"type": "string", "required": True,
                                 "min_len": 1, "max_len": 500}}


def _ship_action(shipment_id, spec, allowed_statuses):
    auth.authenticate(("LogisticsPlanner",))
    body = body_json()
    checks = Checks()
    holder = {}

    def state():
        if holder["row"]["status"] not in allowed_statuses:
            fail("ERR_SHIPMENT_INVALID_STATE",
                 "Shipment status is %s." % holder["row"]["status"])

    checks.add(10, lambda: holder.update(row=rt.find("shipments", shipment_id)))
    add_schema(checks, body, spec)
    checks.add(41, state)
    return holder, body, checks


@bp.route("/shipments/<shipment_id>/seal", methods=["POST"])
def seal_shipment(shipment_id):
    holder, body, checks = _ship_action(shipment_id, {}, ("LOADING",))

    def not_empty():
        holder["lines"] = calc.ordered_loaded_lines(shipment_id)
        if not holder["lines"]:
            fail("ERR_SHIPMENT_EMPTY", "The trailer holds no loaded line.")

    def utilised():
        if holder["row"]["cube_utilization_pct"] < MIN_SEAL_UTILIZATION_PCT:
            fail("ERR_TRAILER_UNDERUTILIZED",
                 "cube_utilization_pct %s is below the 60.00 seal floor."
                 % holder["row"]["cube_utilization_pct"])

    def hulls_still_good():
        for line in holder["lines"]:
            unit = S.finished_units.get(line["finished_unit_id"])
            if unit is None or unit["build_status"] != "SELLABLE" \
                    or unit["logistics_status"] != "LOADED":
                fail("ERR_UNIT_INVALID_BUILD_STATE",
                     "Every loaded hull must still be SELLABLE and LOADED.")

    checks.add(49, not_empty)
    checks.add(68, utilised)
    checks.add(68.5, hulls_still_good)
    checks.run()
    shipment = holder["row"]
    shipment["status"] = "SEALED"
    shipment["sealed_at"] = core.now()
    # QUOTED variant: every line billed on its NESTED cube.
    shipment["quoted_freight_cents"] = calc.shipment_freight(
        shipment, "QUOTED")["freight_cents"]
    touch(shipment)
    return rt.one("shipments", shipment)


@bp.route("/shipments/<shipment_id>/unseal", methods=["POST"])
def unseal_shipment(shipment_id):
    holder, body, checks = _ship_action(shipment_id, UNSEAL_SPEC, ("SEALED",))
    checks.run()
    shipment = holder["row"]
    shipment["status"] = "LOADING"
    shipment["quoted_freight_cents"] = None
    shipment["sealed_at"] = None
    shipment["unseal_reason"] = body["unseal_reason"]
    touch(shipment)
    return rt.one("shipments", shipment)


@bp.route("/shipments/<shipment_id>/depart", methods=["POST"])
def depart_shipment(shipment_id):
    holder, body, checks = _ship_action(shipment_id, DEPART_SPEC, ("SEALED",))

    def quoted():
        if holder["row"]["quoted_freight_cents"] is None:
            fail("ERR_FREIGHT_QUOTE_MISSING",
                 "A sealed trailer must carry a freight quote before departure.")

    checks.add(48, quoted)
    checks.run()
    shipment = holder["row"]
    shipment["status"] = "IN_TRANSIT"
    shipment["departed_at"] = core.now()
    site_ids, bucket_ids = [], []
    for unit in _loaded_units(shipment):
        if unit.get("warehouse_id") and unit["warehouse_id"] not in site_ids:
            site_ids.append(unit["warehouse_id"])
        if unit.get("demand_bucket_id") and unit["demand_bucket_id"] not in bucket_ids:
            bucket_ids.append(unit["demand_bucket_id"])
        # Departure is what frees footprint: the hull leaves its zone here, and
        # the vacate half of the footprint rule (CASCADE-C link 2, anchor
        # promotion) runs once per vacated nest group.  warehouse_id is retained
        # until delivery.
        unit["logistics_status"] = "IN_TRANSIT"
        svc.vacate_unit(unit)
        touch(unit)
    for site_id in site_ids:
        site = S.warehouses.get(site_id)
        if site is not None:
            svc.recompute_warehouse(site)
    for bucket_id in bucket_ids:
        svc.recompute_bucket_of(bucket_id)
    touch(shipment)
    return rt.one("shipments", shipment)


@bp.route("/shipments/<shipment_id>/deliver", methods=["POST"])
def deliver_shipment(shipment_id):
    holder, body, checks = _ship_action(shipment_id, DELIVER_SPEC, ("IN_TRANSIT",))
    checks.run()
    shipment = holder["row"]
    stamp = core.now()
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = stamp
    # BILLED variant: every line billed on its GROSS cube, so the invoice
    # normally exceeds the nested quote.
    shipment["billed_freight_cents"] = calc.shipment_freight(
        shipment, "BILLED")["freight_cents"]
    for unit in _loaded_units(shipment):
        if unit["logistics_status"] != "IN_TRANSIT":
            continue
        unit["logistics_status"] = "DELIVERED"
        unit["warehouse_id"] = None
        # The per-hull stamp is the origin of the warranty clock.
        unit["delivered_at"] = stamp
        touch(unit)
    touch(shipment)
    return rt.one("shipments", shipment)


@bp.route("/shipments/<shipment_id>/cancel", methods=["POST"])
def cancel_shipment(shipment_id):
    holder, body, checks = _ship_action(
        shipment_id, CANCEL_SPEC, ("PLANNED", "LOADING", "SEALED"))
    checks.run()
    shipment = holder["row"]
    was_sealed = shipment["status"] == "SEALED"
    # Every loaded hull goes back to STORED in the zone it never left, so no
    # footprint moves and the origin site's cube is unchanged.
    for line in core.sorted_rows(calc.lines_of_shipment(shipment["id"], "LOADED")):
        unit = S.finished_units.get(line["finished_unit_id"])
        line["status"] = "REMOVED"
        line["removed_reason"] = "SHIPMENT_CANCELLED"
        touch(line)
        if unit is not None and unit["logistics_status"] == "LOADED":
            unit["logistics_status"] = "STORED"
            touch(unit)
    shipment["status"] = "CANCELLED"
    shipment["cancel_reason"] = body["cancel_reason"]
    if was_sealed:
        shipment["quoted_freight_cents"] = None
        shipment["sealed_at"] = None
    calc.shipment_rollup(shipment)
    touch(shipment)
    return rt.one("shipments", shipment)


# --------------------------------------------------------------------------
# Trailer lines.  Both admission tests run on the ROUNDED post-addition
# figures, before the row is written, so a rejected line leaves nothing behind
# and the caller may retry with the same expected_shipment_version.
# --------------------------------------------------------------------------
LINE_CREATE = {
    "shipment_id": {"type": "string", "required": True},
    "finished_unit_id": {"type": "string", "required": True},
    "expected_shipment_version": {"type": "int", "required": True, "min": 1},
}
LINE_REMOVE = {"remove_reason": {"type": "string", "required": True,
                                 "min_len": 1, "max_len": 500}}


@bp.route("/shipment-lines", methods=["POST"])
def create_line():
    auth.authenticate(("LogisticsPlanner",))
    body = body_json()
    checks = Checks()
    holder = {}
    add_schema(checks, body, LINE_CREATE)

    def resolve():
        holder["ship"] = rt.find("shipments", body.get("shipment_id"))
        holder["unit"] = rt.find("finished_units", body.get("finished_unit_id"))
        holder["model"] = S.product_models.get(holder["unit"]["product_model_id"])

    def build_state():
        if holder["unit"]["build_status"] != "SELLABLE":
            fail("ERR_UNIT_INVALID_BUILD_STATE",
                 "Only a SELLABLE hull may be loaded; this one is %s."
                 % holder["unit"]["build_status"])

    def logistics_state():
        if holder["unit"]["logistics_status"] != "STORED":
            fail("ERR_UNIT_INVALID_LOGISTICS_STATE",
                 "Hull logistics_status is %s." % holder["unit"]["logistics_status"])

    def not_already_loaded():
        for line in core.rows("shipment_lines"):
            if line["finished_unit_id"] == holder["unit"]["id"] \
                    and line["status"] == "LOADED":
                fail("ERR_UNIT_INVALID_LOGISTICS_STATE",
                     "The hull already carries a loaded trailer line.")

    def ship_state():
        if holder["ship"]["status"] not in ("PLANNED", "LOADING"):
            fail("ERR_SHIPMENT_INVALID_STATE",
                 "Shipment status is %s." % holder["ship"]["status"])

    def same_site():
        if holder["unit"].get("warehouse_id") != holder["ship"]["origin_warehouse_id"]:
            fail("ERR_WAREHOUSE_MISMATCH",
                 "A trailer cannot pick from two sites.")

    def candidate():
        model = holder["model"]
        earlier = 0
        for line in calc.ordered_loaded_lines(holder["ship"]["id"]):
            other = S.finished_units.get(line["finished_unit_id"])
            if other is not None and other["product_model_id"] == model["id"]:
                earlier += 1
        position = earlier + 1
        holder["position"] = position
        holder["nested"] = (q4(model["gross_cube_m3"]) if position == 1
                            else q4(model["gross_cube_m3"] * model["nest_factor"]))

    def cube_fits():
        ship = holder["ship"]
        if q4(ship["nested_cube_m3"] + holder["nested"]) > ship["trailer_cube_capacity_m3"]:
            fail("ERR_TRAILER_CUBE_EXCEEDED",
                 "The trailer cube cannot hold the new line.")

    def payload_fits():
        ship = holder["ship"]
        total = q3(ship["loaded_weight_kg"] + holder["model"]["unit_weight_kg"])
        if total > ship["trailer_max_payload_kg"]:
            fail("ERR_TRAILER_PAYLOAD_EXCEEDED",
                 "The trailer payload cannot hold the new line.")

    def occ():
        if body["expected_shipment_version"] != holder["ship"]["version"]:
            fail("ERR_STALE_SHIPMENT_VERSION",
                 "expected_shipment_version does not match the stored version.")

    checks.add(11, resolve)
    checks.add(38, build_state)
    checks.add(38.5, logistics_state)
    checks.add(38.6, not_already_loaded)
    checks.add(41, ship_state)
    checks.add(65, same_site)
    checks.add(76.5, candidate)
    checks.add(77, cube_fits)
    checks.add(78, payload_fits)
    checks.add(83, occ)
    checks.run()

    shipment, unit = holder["ship"], holder["unit"]
    before = _snapshot(shipment)
    row = {
        "shipment_id": shipment["id"],
        "finished_unit_id": unit["id"],
        "nest_position": holder["position"],
        "line_gross_cube_m3": q4(holder["model"]["gross_cube_m3"]),
        "line_nested_cube_m3": holder["nested"],
        "line_freight_cents": 0,
        "status": "LOADED",
    }
    core.insert("shipment_lines", row)
    # The hull stays physically in its zone: no footprint field moves here.
    unit["logistics_status"] = "LOADED"
    touch(unit)
    if shipment["status"] == "PLANNED":
        shipment["status"] = "LOADING"
    _apply_rollup(shipment, before)
    touch(shipment)
    return rt.one("shipment_lines", row, 201)


@bp.route("/shipment-lines", methods=["GET"])
def list_lines():
    auth.authenticate(SHIP_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("shipment_lines")
        rows = rt.filter_eq(rows, "shipment_id", str_filter("shipment_id"))
        rows = rt.filter_eq(rows, "finished_unit_id", str_filter("finished_unit_id"))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.LINE_STATUSES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("shipment_lines", items[0])


@bp.route("/shipment-lines/<shipment_line_id>", methods=["GET"])
def read_line(shipment_line_id):
    auth.authenticate(SHIP_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("shipment_lines", shipment_line_id)))
    checks.run()
    return rt.one("shipment_lines", holder["row"])


@bp.route("/shipment-lines/<shipment_line_id>/remove", methods=["POST"])
def remove_line(shipment_line_id):
    auth.authenticate(("LogisticsPlanner",))
    body = body_json()
    checks = Checks()
    holder = {}

    def resolve():
        holder["ship"] = rt.find("shipments", holder["row"]["shipment_id"])

    def ship_state():
        if holder["ship"]["status"] not in ("PLANNED", "LOADING", "SEALED"):
            fail("ERR_SHIPMENT_INVALID_STATE",
                 "Nothing may be pulled off a trailer in status %s."
                 % holder["ship"]["status"])

    def line_state():
        if holder["row"]["status"] != "LOADED":
            fail("ERR_SHIPMENT_LINE_ALREADY_REMOVED",
                 "The line is already REMOVED.")

    checks.add(10, lambda: holder.update(
        row=rt.find("shipment_lines", shipment_line_id)))
    checks.add(11, resolve)
    add_schema(checks, body, LINE_REMOVE)
    checks.add(41, ship_state)
    checks.add(42, line_state)
    checks.run()

    line, shipment = holder["row"], holder["ship"]
    unit = S.finished_units.get(line["finished_unit_id"])
    before = _snapshot(shipment)
    before.pop(line["id"], None)
    line["status"] = "REMOVED"
    line["removed_reason"] = body["remove_reason"]
    touch(line)
    if unit is not None and unit["logistics_status"] == "LOADED":
        # Back to STORED in the zone it never left - no footprint movement.
        unit["logistics_status"] = "STORED"
        touch(unit)
    if shipment["status"] == "SEALED":
        shipment["status"] = "LOADING"
        shipment["quoted_freight_cents"] = None
    # Renumbering can promote a nested follower into position 1 and therefore
    # RAISE nested_cube_m3 and cube_utilization_pct.
    remaining = _apply_rollup(shipment, before)
    if not remaining and shipment["status"] == "LOADING":
        shipment["status"] = "PLANNED"
    touch(shipment)
    return rt.one("shipment_lines", line)


@bp.route("/shipments/<shipment_id>/freight-summary", methods=["GET"])
def freight_summary(shipment_id):
    """Read-only: both bases side by side, so the quote-to-bill variance is
    observable in one call.  Never advances a version."""
    auth.authenticate(("PlantAdmin", "LogisticsPlanner"))
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("shipments", shipment_id)))
    checks.run()
    shipment = holder["row"]
    quoted = calc.shipment_freight(shipment, "QUOTED")
    billed = calc.shipment_freight(shipment, "BILLED")
    lines = []
    for line in calc.ordered_loaded_lines(shipment["id"]):
        unit = S.finished_units.get(line["finished_unit_id"])
        lines.append({
            "shipment_line_id": line["id"],
            "hull_serial": unit["hull_serial"] if unit else None,
            "nest_position": line["nest_position"],
            "line_gross_cube_m3": line["line_gross_cube_m3"],
            "line_nested_cube_m3": line["line_nested_cube_m3"],
            "chargeable_kg_nested": calc.chargeable_kg(
                line, line["line_nested_cube_m3"]),
            "chargeable_kg_gross": calc.chargeable_kg(
                line, line["line_gross_cube_m3"]),
            "line_freight_cents": line["line_freight_cents"],
        })
    payload = {
        "shipment_id": shipment["id"],
        "loaded_line_count": len(lines),
        "loaded_cube_m3": shipment["loaded_cube_m3"],
        "nested_cube_m3": shipment["nested_cube_m3"],
        "loaded_weight_kg": shipment["loaded_weight_kg"],
        "cube_utilization_pct": shipment["cube_utilization_pct"],
        "density_kg_per_m3": shipment["density_kg_per_m3"],
        "discount_rate_pct": quoted["discount_rate_pct"],
        "quoted_pre_discount_cents": quoted["pre_discount_cents"],
        "quoted_freight_cents": shipment["quoted_freight_cents"],
        "billed_pre_discount_cents": billed["pre_discount_cents"],
        "billed_freight_cents": shipment["billed_freight_cents"],
        "lines": lines,
    }
    return core.respond(payload)
