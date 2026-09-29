from datetime import timedelta

from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_car, get_resource,
    check_contract_party, fail, req_id, req_enum, req_date, clock_iso,
    clock_date, parse_dt, parse_date_str, require_contract_operational,
    require_car_not_decommissioned, contract_of_car, inspections_of_car,
    ALL_ROLES, ROLE_ADMIN, ROLE_INSPECTOR, ROLE_MANAGER,
    INSPECTION_TYPES, INSPECTION_RESULTS, CERTIFICATE_VALIDITY_DAYS,
)
from cascades import (
    refresh_out_of_service_count, recompute_certificate_mirrors,
    car_has_open_out_of_service_callback,
)

bp = Blueprint("inspections", __name__)


def _inspection_context(inspection_id):
    inspection = get_resource(db.inspections, inspection_id)
    car = db.cars.get(inspection["car_id"])
    contract = contract_of_car(car) if car is not None else None
    return inspection, car, contract


@bp.route(API_PREFIX + "/inspections", methods=["POST"])
def create_inspection():
    user_id, role = authenticate([ROLE_ADMIN])
    body = json_body()
    car_id = req_id(body, "car_id")
    car = get_car(car_id)
    contract = contract_of_car(car)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    inspection_type = req_enum(body, "inspection_type", INSPECTION_TYPES)
    req_date(body, "scheduled_date")

    require_contract_operational(contract)
    require_car_not_decommissioned(car)

    inspection = new_entity({
        "car_id": car_id,
        "inspection_type": inspection_type,
        "scheduled_date": body["scheduled_date"],
        "status": "SCHEDULED",
        "result": None,
        "deficiency_codes": [],
        "result_recorded_at": None,
        "certificate_state": "NONE",
        "certificate_number": None,
        "certificate_issued_date": None,
        "certificate_expiry_date": None,
        "certificate_posted_at": None,
        "posted_by_user_id": None,
    })
    db.inspections[inspection["id"]] = inspection
    return object_response(serialize(inspection), 201)


@bp.route(API_PREFIX + "/inspections/<inspection_id>", methods=["GET"])
def read_inspection(inspection_id):
    authenticate(ALL_ROLES)
    inspection = get_resource(db.inspections, inspection_id)
    return object_response(serialize(inspection))


@bp.route(API_PREFIX + "/inspections", methods=["GET"])
def list_inspections():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.inspections)
    rows = filter_equals(rows, "car_id")
    rows = filter_equals(rows, "status")
    rows = filter_equals(rows, "certificate_state")
    return paginate(rows)


def _mint_certificate(inspection, car, contract):
    issued = clock_date()
    expiry = issued + timedelta(days=CERTIFICATE_VALIDITY_DAYS)
    inspection["certificate_state"] = "ISSUED"
    inspection["certificate_issued_date"] = issued.isoformat()
    inspection["certificate_expiry_date"] = expiry.isoformat()
    inspection["certificate_number"] = "CERT-%s-%s-%s" % (
        contract["jurisdiction_code"], car["car_code"], issued.strftime("%Y%m%d"))


@bp.route(API_PREFIX + "/inspections/<inspection_id>/record-result", methods=["POST"])
def record_result(inspection_id):
    user_id, role = authenticate([ROLE_INSPECTOR])
    inspection, car, contract = _inspection_context(inspection_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    result = req_enum(body, "result", INSPECTION_RESULTS)
    deficiency_codes = None
    if "deficiency_codes" in body and body["deficiency_codes"] is not None:
        raw = body["deficiency_codes"]
        if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
            fail("ERR_VALIDATION", "Field 'deficiency_codes' must be an array of strings.")
        deficiency_codes = list(raw)

    if inspection["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION")

    inspection["status"] = "COMPLETED"
    inspection["result"] = result
    if deficiency_codes is not None:
        inspection["deficiency_codes"] = deficiency_codes
    inspection["result_recorded_at"] = clock_iso()

    car_changed = False

    if result in ("PASS", "PASS_WITH_DEFICIENCIES"):
        _mint_certificate(inspection, car, contract)
        touch(inspection)
        if (inspection["inspection_type"] == "REINSPECTION"
                and car["compliance_state"] == "RED_TAGGED"):
            car["compliance_state"] = "INSPECTION_DUE"
            car["red_tag_lifted_at"] = clock_iso()
            car_changed = True
            if (car["availability_state"] == "OUT_OF_SERVICE"
                    and not car_has_open_out_of_service_callback(car)):
                car["availability_state"] = "IN_SERVICE"
                car["unplanned_outage_open_since"] = None
    else:
        touch(inspection)
        if car["compliance_state"] != "RED_TAGGED":
            if car["compliance_state"] == "CERTIFIED":
                for other in inspections_of_car(car["id"]):
                    if other["certificate_state"] == "POSTED":
                        other["certificate_state"] = "SUPERSEDED"
                        touch(other)
            car["compliance_state"] = "RED_TAGGED"
            car["red_tag_issued_at"] = clock_iso()
            recompute_certificate_mirrors(car)
            car_changed = True
            if car["availability_state"] == "IN_SERVICE":
                car["availability_state"] = "OUT_OF_SERVICE"
                car["unplanned_outage_open_since"] = clock_iso()

    if car_changed:
        touch(car)
        refresh_out_of_service_count(contract)

    return object_response(serialize(inspection))


@bp.route(API_PREFIX + "/inspections/<inspection_id>/post-certificate", methods=["POST"])
def post_certificate(inspection_id):
    user_id, role = authenticate([ROLE_MANAGER])
    inspection, car, contract = _inspection_context(inspection_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if inspection["certificate_state"] != "ISSUED":
        fail("ERR_CERTIFICATE_NOT_ISSUED")
    expiry = parse_date_str(inspection.get("certificate_expiry_date"))
    if expiry is None or clock_date() > expiry:
        fail("ERR_CERTIFICATE_EXPIRED")

    for other in inspections_of_car(car["id"]):
        if other["id"] != inspection["id"] and other["certificate_state"] == "POSTED":
            other["certificate_state"] = "SUPERSEDED"
            touch(other)

    inspection["certificate_state"] = "POSTED"
    inspection["certificate_posted_at"] = clock_iso()
    inspection["posted_by_user_id"] = user_id
    touch(inspection)

    if car["compliance_state"] in ("INSPECTION_DUE", "CERTIFICATE_EXPIRED"):
        car["compliance_state"] = "CERTIFIED"
    recompute_certificate_mirrors(car)
    touch(car)

    return object_response(serialize(inspection))
