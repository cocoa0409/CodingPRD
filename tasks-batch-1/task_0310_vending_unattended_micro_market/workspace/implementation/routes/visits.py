"""RestockVisit endpoints (PRD 3.5): open, list, get, reconcile, reject."""
from datetime import timedelta

from flask import Blueprint, request

from common import get_json_body, get_or_404, list_response, require_int, require_str
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize
from services.inventory import recompute_slot_on_hand, rederive_machine_stock

bp = Blueprint("visits", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


def _validate_counted_lines(raw):
    """counted_lines is a list of {slot_id, physical_count, refill_units}."""
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", "counted_lines must be an array")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each counted line must be an object")
        slot_id = entry.get("slot_id")
        physical = entry.get("physical_count")
        refill = entry.get("refill_units")
        if not isinstance(slot_id, str) or slot_id == "":
            raise ApiError("ERR_INVALID_REQUEST", "counted line slot_id required")
        if isinstance(physical, bool) or not isinstance(physical, int) or physical < 0:
            raise ApiError("ERR_INVALID_REQUEST", "physical_count must be a non-negative integer")
        if isinstance(refill, bool) or not isinstance(refill, int) or refill < 0:
            raise ApiError("ERR_INVALID_REQUEST", "refill_units must be a non-negative integer")
        lines.append({"slot_id": slot_id, "physical_count": physical, "refill_units": refill})
    return lines


@bp.route("/operations/restock-visits", methods=["POST"])
@require_roles("RouteDriver")
def open_visit():
    body = get_json_body()
    route_stop_id = require_str(body, "route_stop_id")
    if "counted_lines" not in body:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: counted_lines")
    counted_lines = _validate_counted_lines(body["counted_lines"])
    expected_version = require_int(body, "expected_machine_version")

    # FK existence (priority 4)
    stop = db.stops.get(route_stop_id)
    if stop is None:
        raise ApiError("ERR_STOP_NOT_FOUND", "Route stop not found")

    obj = {
        "route_stop_id": route_stop_id,
        "machine_id": stop["machine_id"],  # denormalized from the stop
        "counted_lines": counted_lines,
        "total_shrink_units": 0,
        "shrink_value_cents": 0,
        "expected_machine_version": expected_version,
        "status": "DRAFT",
    }
    stamp_create(obj)
    db.visits[obj["id"]] = obj
    return object_response(serialize.visit(obj), 201)


@bp.route("/operations/restock-visits", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_visits():
    rows = list(db.visits.values())
    route_stop_id = request.args.get("route_stop_id")
    machine_id = request.args.get("machine_id")
    if route_stop_id is not None:
        rows = [v for v in rows if v["route_stop_id"] == route_stop_id]
    if machine_id is not None:
        rows = [v for v in rows if v["machine_id"] == machine_id]
    return list_response(rows, serialize.visit)


@bp.route("/operations/restock-visits/<visit_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_visit(visit_id):
    obj = get_or_404("visits", visit_id)
    return object_response(serialize.visit(obj))


@bp.route("/operations/restock-visits/<visit_id>/reconcile", methods=["POST"])
@require_roles("RouteDriver")
def reconcile(visit_id):
    visit = get_or_404("visits", visit_id)
    body = get_json_body()
    expected_version = require_int(body, "expected_machine_version")

    machine = db.machines.get(visit["machine_id"])
    stop = db.stops.get(visit["route_stop_id"])
    route = db.routes.get(stop["route_id"]) if stop else None

    # --- Validation order follows PRD 3.5 prose ---
    # 1. parent route DISPATCHED
    if route is None or route["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED", "Parent route is not dispatched")
    # 2. visit DRAFT
    if visit["status"] != "DRAFT":
        raise ApiError("ERR_VISIT_NOT_DRAFT", "Visit is not in DRAFT")
    # 3. machine IN_SERVICE
    if machine["service_status"] == "FROZEN":
        raise ApiError("ERR_MACHINE_FROZEN", "Machine is frozen")
    # 4. OCC version match
    if expected_version != machine["version"]:
        raise ApiError("ERR_STALE_MACHINE_VERSION", "expected_machine_version is stale")
    # 5. every counted line slot belongs to this machine and is ACTIVE
    for line in visit["counted_lines"]:
        slot = db.slots.get(line["slot_id"])
        if slot is None or slot["machine_id"] != machine["id"] or slot["status"] != "ACTIVE":
            raise ApiError("ERR_SLOT_NOT_ON_MACHINE",
                           "Counted slot does not belong to this machine or is not active")
    # 6. per-line overfill: refill_units + physical_count <= slot.capacity
    for line in visit["counted_lines"]:
        slot = db.slots[line["slot_id"]]
        if line["refill_units"] + line["physical_count"] > slot["capacity"]:
            raise ApiError("ERR_SLOT_OVERFILL", "refill_units + physical_count exceeds capacity")

    # --- All checks pass: compute shrink (per-line multiply then sum) ---
    total_shrink_units = 0
    shrink_value_cents = 0
    for line in visit["counted_lines"]:
        slot = db.slots[line["slot_id"]]
        theoretical = slot["on_hand"]  # pre-visit theoretical count
        line_shrink = max(0, theoretical - line["physical_count"])
        total_shrink_units += line_shrink
        shrink_value_cents += line_shrink * slot["price_cents"]

    visit["total_shrink_units"] = total_shrink_units
    visit["shrink_value_cents"] = shrink_value_cents

    # cascade hop 1: create a lot per refill line (refill_units > 0)
    clock = db.clock()
    touched_slot_ids = set()
    for line in visit["counted_lines"]:
        if line["refill_units"] <= 0:
            continue
        slot = db.slots[line["slot_id"]]
        product = db.products.get(slot["product_id"])
        unit_cost = product["unit_cost_cents"] if product else 0
        shelf_life = product["shelf_life_days"] if product else 0
        if shelf_life and shelf_life > 0:
            exp_dt = clock + timedelta(days=shelf_life)
            exp_iso = _iso(exp_dt)
        else:
            exp_dt = None
            exp_iso = None
        lot = {
            "slot_id": slot["id"],
            "machine_id": machine["id"],
            "filled_units": line["refill_units"],
            "unit_cost_cents": unit_cost,
            "remaining_units": line["refill_units"],
            "expiration_date": exp_iso,
            "_expiration_dt": exp_dt,
            "restock_visit_id": visit["id"],
            "status": "AVAILABLE",
        }
        stamp_create(lot)
        db.lots[lot["id"]] = lot
        touched_slot_ids.add(slot["id"])

    # cascade hop 2: recompute each touched slot on_hand
    for slot_id in touched_slot_ids:
        recompute_slot_on_hand(db.slots[slot_id])

    # cascade hop 3: re-derive machine stock_status (no version bump here — the
    # reconcile applies its own single version increment below).
    rederive_machine_stock(machine, bump_version=False)

    # increment machine version by one (the reconcile's OCC advance)
    machine["updated_at"] = _now()
    machine["version"] += 1

    # visit terminal state
    visit["status"] = "RECONCILED"
    touch(visit)

    # parent stop -> VISITED
    stop["status"] = "VISITED"
    touch(stop)

    return object_response(serialize.visit(visit))


@bp.route("/operations/restock-visits/<visit_id>/reject", methods=["POST"])
@require_roles("FieldOps")
def reject(visit_id):
    visit = get_or_404("visits", visit_id)
    if visit["status"] != "DRAFT":
        raise ApiError("ERR_VISIT_NOT_DRAFT", "Visit is not in DRAFT")
    visit["status"] = "REJECTED"
    touch(visit)
    # parent stop -> SKIPPED (no inventory/machine mutation)
    stop = db.stops.get(visit["route_stop_id"])
    if stop:
        stop["status"] = "SKIPPED"
        touch(stop)
    return object_response(serialize.visit(visit))


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _now():
    from response import now_iso
    return now_iso()
