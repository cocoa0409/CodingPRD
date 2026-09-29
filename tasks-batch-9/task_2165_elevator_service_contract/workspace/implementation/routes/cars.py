from flask import Blueprint, request

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_contract, get_car,
    check_contract_party, fail, req_id, req_string, req_enum, req_int, num,
    ALL_ROLES, ROLE_ADMIN, CAR_TYPES, PERIOD_MONTH_RE,
)
from calc import car_uptime
from cascades import decommission_car

bp = Blueprint("cars", __name__)


@bp.route(API_PREFIX + "/cars", methods=["POST"])
def create_car():
    user_id, role = authenticate([ROLE_ADMIN])
    body = json_body()
    contract_id = req_id(body, "contract_id")
    contract = get_contract(contract_id)
    check_contract_party(contract, user_id, role)

    car_code = req_string(body, "car_code")
    car_type = req_enum(body, "car_type", CAR_TYPES)
    capacity_lbs = req_int(body, "capacity_lbs", 1)

    car = new_entity({
        "contract_id": contract_id,
        "car_code": car_code,
        "car_type": car_type,
        "capacity_lbs": capacity_lbs,
        "availability_state": "IN_SERVICE",
        "compliance_state": "INSPECTION_DUE",
        "scheduled_downtime_minutes": 0,
        "open_part_order_count": 0,
        "unplanned_outage_open_since": None,
        "red_tag_issued_at": None,
        "red_tag_lifted_at": None,
        "current_certificate_number": None,
        "certificate_expiry_date": None,
    })
    db.cars[car["id"]] = car
    return object_response(serialize(car), 201)


@bp.route(API_PREFIX + "/cars/<car_id>", methods=["GET"])
def read_car(car_id):
    authenticate(ALL_ROLES)
    car = get_car(car_id)
    return object_response(serialize(car))


@bp.route(API_PREFIX + "/cars", methods=["GET"])
def list_cars():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.cars)
    rows = filter_equals(rows, "contract_id")
    rows = filter_equals(rows, "availability_state")
    rows = filter_equals(rows, "compliance_state")
    return paginate(rows)


@bp.route(API_PREFIX + "/cars/<car_id>/uptime-report", methods=["GET"])
def uptime_report(car_id):
    authenticate(ALL_ROLES)
    car = get_car(car_id)
    period_month = request.args.get("period_month")
    if not period_month or not PERIOD_MONTH_RE.match(period_month):
        fail("ERR_VALIDATION", "Query parameter 'period_month' must match YYYY-MM.")
    report = car_uptime(car, period_month)
    return object_response({
        "car_id": report["car_id"],
        "period_month": report["period_month"],
        "period_minutes": report["period_minutes"],
        "unplanned_outage_minutes": report["unplanned_outage_minutes"],
        "planned_downtime_minutes": report["planned_downtime_minutes"],
        "available_minutes": report["available_minutes"],
        "uptime_pct_exclusive": num(report["uptime_pct_exclusive"]),
        "uptime_pct_inclusive": num(report["uptime_pct_inclusive"]),
        "outage_interval_count": report["outage_interval_count"],
    })


@bp.route(API_PREFIX + "/cars/<car_id>/decommission", methods=["POST"])
def decommission(car_id):
    user_id, role = authenticate([ROLE_ADMIN])
    car = get_car(car_id)
    contract = db.contracts.get(car["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)
    if car["availability_state"] not in ("IN_SERVICE", "OUT_OF_SERVICE"):
        fail("ERR_INVALID_STATE_TRANSITION")
    decommission_car(car)
    return object_response(serialize(car))
