from datetime import timedelta

from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_car, get_part,
    get_resource, check_contract_party, fail, req_id, opt_id, req_int, req_bool,
    require_contract_operational, require_car_not_decommissioned,
    contract_of_car, parse_dt, parse_date_str, iso,
    ALL_ROLES, ROLE_CONTRACTOR,
)
from calc import (
    resolve_supersession, price_part_order, rule1_conflict,
    recompute_scheduled_downtime, recompute_project_target,
)

bp = Blueprint("part_orders", __name__)


def _render_like(sample, moment):
    """Render a shifted instant in the same textual shape the window already uses."""
    if isinstance(sample, str) and "." not in sample and sample.endswith("Z"):
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso(moment)


def _apply_window_shift(order, window, car, contract):
    """downtime_window_shift — hop 2 and hop 3 of the obsolete-part cascade."""
    promised = parse_date_str(order["promised_date"])
    start = parse_dt(window["window_start"])
    end = parse_dt(window["window_end"])
    if promised is None or start is None or end is None:
        return

    if promised <= start.date():
        return

    shift_days = (promised - start.date()).days
    candidate_start = start + timedelta(days=shift_days)
    candidate_end = end + timedelta(days=shift_days)

    if rule1_conflict(window["car_id"], candidate_start, candidate_end,
                      window["window_type"], exclude_window_id=window["id"]):
        window["status"] = "RESCHEDULE_REQUIRED"
        window["reschedule_count"] = window["reschedule_count"] + 1
        touch(window)
        if car is not None:
            recompute_scheduled_downtime(car)
            touch(car)
    else:
        window["window_start"] = _render_like(window["window_start"], candidate_start)
        window["window_end"] = _render_like(window["window_end"], candidate_end)
        window["reschedule_count"] = window["reschedule_count"] + 1
        touch(window)

    project_id = window.get("project_id")
    if not project_id:
        return
    project = db.projects.get(project_id)
    if project is None:
        return
    target = recompute_project_target(project)
    changed = False
    if target is not None and project["target_completion_date"] != target.isoformat():
        project["target_completion_date"] = target.isoformat()
        changed = True
    if (target is not None and contract is not None
            and target.isoformat() > contract["term_end_date"]
            and project["status"] in ("APPROVED", "IN_PROGRESS")):
        project["status"] = "AT_RISK"
        changed = True
    if changed:
        touch(project)


@bp.route(API_PREFIX + "/part-orders", methods=["POST"])
def create_part_order():
    user_id, role = authenticate([ROLE_CONTRACTOR])
    body = json_body()

    # Priority 30 — existence, left to right: car_id, part_id, window_id.
    car_id = req_id(body, "car_id")
    car = get_car(car_id)
    part_id = req_id(body, "part_id")
    part = get_part(part_id)
    window_id = opt_id(body, "window_id")
    window = None
    if window_id is not None:
        window = get_resource(db.windows, window_id)

    contract = contract_of_car(car)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    # Priority 50 — body schema.
    quantity = req_int(body, "quantity")
    expected_car_version = req_int(body, "expected_car_version")
    expedite = req_bool(body, "expedite", False)

    # Priority 55 — quantity, ahead of the stale-version check.
    if quantity < 1:
        fail("ERR_INVALID_QUANTITY")

    # Priority 60 — optimistic concurrency on the ElevatorCar.
    if expected_car_version != car["version"]:
        fail("ERR_STALE_CAR_VERSION")

    # Priority 72 / 80.
    require_contract_operational(contract)
    require_car_not_decommissioned(car)

    effective_part, hops, too_deep = resolve_supersession(part)

    # Priority 90 / 92 / 94.
    if (contract["scope_type"] == "OIL_AND_GREASE"
            and effective_part["part_class"] != "LUBRICATION"):
        fail("ERR_SCOPE_EXCLUDES_REPAIR")
    if effective_part["lifecycle_state"] == "DISCONTINUED":
        fail("ERR_PART_DISCONTINUED")
    if too_deep:
        fail("ERR_SUPERSESSION_CHAIN_TOO_DEEP")

    pricing = price_part_order(effective_part, quantity, expedite, hops)

    order = new_entity({
        "car_id": car_id,
        "part_id": part_id,
        "effective_part_id": effective_part["id"],
        "window_id": window_id,
        "quantity": quantity,
        "expedite": expedite,
        "subtotal_cents": pricing["subtotal_cents"],
        "expedite_surcharge_cents": pricing["expedite_surcharge_cents"],
        "total_cost_cents": pricing["total_cost_cents"],
        "lead_time_days_applied": pricing["lead_time_days_applied"],
        "promised_date": pricing["promised_date"],
        "substitution_hops": hops,
        "status": "SUBSTITUTED" if hops > 0 else "ORDERED",
    })
    db.part_orders[order["id"]] = order

    car["open_part_order_count"] = car["open_part_order_count"] + 1
    touch(car)

    if window is not None and hops > 0:
        _apply_window_shift(order, window, car, contract)

    return object_response(serialize(order), 201)


@bp.route(API_PREFIX + "/part-orders/<order_id>", methods=["GET"])
def read_part_order(order_id):
    authenticate(ALL_ROLES)
    order = get_resource(db.part_orders, order_id)
    return object_response(serialize(order))


@bp.route(API_PREFIX + "/part-orders", methods=["GET"])
def list_part_orders():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.part_orders)
    rows = filter_equals(rows, "car_id")
    rows = filter_equals(rows, "part_id")
    rows = filter_equals(rows, "effective_part_id")
    rows = filter_equals(rows, "window_id")
    rows = filter_equals(rows, "status")
    return paginate(rows)


@bp.route(API_PREFIX + "/part-orders/<order_id>/receive", methods=["POST"])
def receive_part_order(order_id):
    user_id, role = authenticate([ROLE_CONTRACTOR])
    order = get_resource(db.part_orders, order_id)
    car = db.cars.get(order["car_id"])
    contract = contract_of_car(car) if car is not None else None
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if order["status"] not in ("ORDERED", "SUBSTITUTED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    order["status"] = "RECEIVED"
    touch(order)

    if car is not None:
        car["open_part_order_count"] = max(0, car["open_part_order_count"] - 1)
        touch(car)

    return object_response(serialize(order))
