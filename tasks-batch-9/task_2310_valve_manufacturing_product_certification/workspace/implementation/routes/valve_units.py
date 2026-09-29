"""Serialised valve units: build, test, certification and field-service dimensions."""

from flask import Blueprint

import calcs
import domain
from auth import ANY, require_action_role, require_roles
from calcs import dec, fnum
from db import clock_iso, db, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    BUILD_SEQUENCE,
    BUILD_STATUSES,
    DECERT_REASONS,
    SPECIAL_SERVICES,
    TEST_RESULTS,
    TEST_TYPES,
    filter_value,
    get_body,
    get_datetime,
    get_enum,
    get_enum_array,
    get_int,
    get_number,
    get_string,
    invalid,
    paginate,
    parse_pagination,
)

bp = Blueprint("valve_units", __name__)

BUILD_ACTION_ROLES = {
    "ADVANCE": ["TestTechnician"],
    "REWORK_COMPLETE": ["TestTechnician"],
}
CERT_ACTION_ROLES = {"CERTIFY": ["QualityManager"], "DECERTIFY": ["QualityManager"]}
SERVICE_ACTION_ROLES = {
    "OPEN": ["FieldServiceCoordinator"],
    "RESERVE_KIT": ["FieldServiceCoordinator"],
    "START": ["FieldServiceCoordinator"],
    "COMPLETE": ["FieldServiceCoordinator"],
    "ABORT": ["FieldServiceCoordinator"],
}


# ------------------------------------------------------------------- units ---
@bp.post("/valve-mfg/valve-units")
def create_unit():
    require_roles(["ProductEngineer", "TestTechnician"])
    body = get_body()
    model_id = get_string(body, "model_id")
    body_component_id = get_string(body, "body_component_id")
    monogram_license_id = get_string(body, "monogram_license_id")
    serial_number = get_string(body, "serial_number")
    special_services = get_enum_array(
        body, "special_services", SPECIAL_SERVICES, required=False, default=[]
    )
    engineered_order_id = get_string(
        body, "engineered_order_id", required=False, default=None
    )

    model = domain.find_model(model_id)
    component = domain.find_component(body_component_id)
    domain.find_license(monogram_license_id)
    if engineered_order_id is not None:
        domain.find_order(engineered_order_id)

    if component["status"] not in ("CREATED", "ISSUED_TO_MACHINING"):
        raise api_error(
            "ERR_COMPONENT_NOT_AVAILABLE",
            "component status is %s" % component["status"],
        )
    for unit in db.valve_units.values():
        if unit.get("body_component_id") == component["id"]:
            raise api_error(
                "ERR_COMPONENT_NOT_AVAILABLE",
                "the component is already consumed by another unit",
            )
    if component["component_type"] != "BODY":
        raise api_error(
            "ERR_COMPONENT_NOT_AVAILABLE", "the component is not of component_type BODY"
        )
    if component["target_model_id"] != model_id:
        raise api_error(
            "ERR_COMPONENT_NOT_AVAILABLE",
            "the component targets a different valve model",
        )

    if model["status"] not in ("IN_REVIEW", "RELEASED"):
        raise api_error(
            "ERR_MODEL_NOT_RELEASED",
            "valve model status is %s" % model["status"],
        )

    for unit in db.valve_units.values():
        if unit["serial_number"] == serial_number:
            raise api_error(
                "ERR_DUPLICATE_CODE",
                "serial_number '%s' is already in use" % serial_number,
            )

    row = new_row(
        {
            "model_id": model_id,
            "body_component_id": body_component_id,
            "monogram_license_id": monogram_license_id,
            "engineered_order_id": engineered_order_id,
            "serial_number": serial_number,
            "special_services": special_services,
            "build_status": "BLANK",
            "cert_status": "UNCERTIFIED",
            "service_status": "NONE",
            "reserved_kit_qty": 0,
            "service_engineer_user_id": None,
            "final_emission_leak_class": None,
            "certified_by_user_id": None,
            "certified_at": None,
            "decertification_reason": None,
        }
    )
    db.valve_units[row["id"]] = row
    component["status"] = "CONSUMED"
    touch(component)
    return object_response(domain.serialize_unit(row), 201)


@bp.get("/valve-mfg/valve-units")
def list_units():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.valve_units.values()))
    for row in rows:
        domain.refresh_unit(row)
    filters = [
        ("model_id", "model_id"),
        ("body_component_id", "body_component_id"),
        ("monogram_license_id", "monogram_license_id"),
        ("engineered_order_id", "engineered_order_id"),
        ("build_status", "build_status"),
        ("cert_status", "cert_status"),
        ("service_status", "service_status"),
    ]
    for param, field in filters:
        value = filter_value(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_unit(r) for r in page], limit, offset, total)


@bp.get("/valve-mfg/valve-units/<unit_id>")
def get_unit(unit_id):
    require_roles(ANY)
    unit = domain.find_unit(unit_id)
    return object_response(domain.serialize_unit(unit))


# ----------------------------------------------------------- build actions ---
@bp.post("/valve-mfg/valve-units/<unit_id>/build-actions")
def build_actions(unit_id):
    _user_id, role = require_roles(["TestTechnician"])
    body = get_body()
    action = get_enum(body, "action", list(BUILD_ACTION_ROLES.keys()))
    require_action_role(role, action, BUILD_ACTION_ROLES)
    to_build_status = None
    if action == "ADVANCE":
        to_build_status = get_enum(body, "to_build_status", BUILD_STATUSES)

    unit = domain.find_unit(unit_id)
    current = unit["build_status"]

    if action == "ADVANCE":
        if current == "SHIPPED":
            raise api_error(
                "ERR_STATE_INVALID", "the build dimension is terminal at SHIPPED"
            )
        if current == "REWORK":
            raise api_error(
                "ERR_STATE_INVALID",
                "a unit in REWORK must be closed out with REWORK_COMPLETE",
            )
        if current == "BLANK" and to_build_status == "MACHINED":
            component = db.components.get(unit["body_component_id"])
            if component is None or component["status"] not in (
                "CONSUMED",
                "ISSUED_TO_MACHINING",
            ):
                raise api_error(
                    "ERR_STATE_INVALID",
                    "the body component is not available for machining",
                )
        if to_build_status in ("PACKAGED", "SHIPPED") and unit["cert_status"] != "CERTIFIED":
            raise api_error(
                "ERR_UNIT_NOT_CERTIFIED",
                "cert_status is %s, not CERTIFIED" % unit["cert_status"],
            )
        if to_build_status == "PACKAGED":
            packages = domain.packages_of_unit(unit["id"])
            if packages:
                approved = [p for p in packages if p["sizing_status"] == "APPROVED"]
                if len(approved) != 1:
                    raise api_error(
                        "ERR_ACTUATOR_NOT_APPROVED",
                        "exactly one actuator package must be APPROVED",
                    )
        index = BUILD_SEQUENCE.index(current)
        expected = (
            BUILD_SEQUENCE[index + 1] if index + 1 < len(BUILD_SEQUENCE) else None
        )
        if to_build_status != expected:
            raise api_error(
                "ERR_BUILD_SEQUENCE_INVALID",
                "only the adjacent forward step (%s) may be advanced to" % expected,
            )
        unit["build_status"] = to_build_status
        touch(unit)

    else:  # REWORK_COMPLETE
        if current != "REWORK":
            raise api_error(
                "ERR_STATE_INVALID",
                "REWORK_COMPLETE requires build_status REWORK (current: %s)" % current,
            )
        if unit["service_status"] not in ("NONE", "SERVICED"):
            raise api_error(
                "ERR_STATE_INVALID",
                "service_status is %s; the field service job must be closed first"
                % unit["service_status"],
            )
        unit["build_status"] = "ASSEMBLED"
        touch(unit)

    return object_response(domain.serialize_unit(unit))


# ------------------------------------------------------------ test records ---
@bp.post("/valve-mfg/valve-units/<unit_id>/test-records")
def create_test_record(unit_id):
    user_id, _role = require_roles(["TestTechnician"])
    body = get_body()
    test_type = get_enum(body, "test_type", TEST_TYPES)
    test_bench_code = get_string(body, "test_bench_code")
    started_at_raw, started_at = get_datetime(body, "started_at")
    ended_at_raw, ended_at = get_datetime(body, "ended_at")
    test_pressure_bar = get_number(body, "test_pressure_bar", minimum=0)
    hold_seconds = get_int(body, "hold_seconds", minimum=1)
    result = get_enum(body, "result", TEST_RESULTS)
    leak_rate_ppm = get_number(
        body,
        "leak_rate_ppm",
        required=(test_type == "FUGITIVE_EMISSION"),
        default=None,
        minimum=0,
    )
    leak_drops = get_int(
        body, "leak_drops", required=(test_type == "SEAT"), default=None, minimum=0
    )
    standard_ref = get_string(body, "standard_ref", required=False, default="API-598")
    if started_at >= ended_at:
        raise invalid("started_at must be strictly before ended_at")

    unit = domain.find_unit(unit_id)
    model = db.valve_models.get(unit["model_id"])

    if unit["build_status"] not in ("ASSEMBLED", "PACKAGED"):
        raise api_error(
            "ERR_STATE_INVALID",
            "test records require build_status ASSEMBLED or PACKAGED (current: %s)"
            % unit["build_status"],
        )
    if unit["cert_status"] == "CERTIFIED":
        raise api_error(
            "ERR_STATE_INVALID", "a CERTIFIED unit may not take further test records"
        )

    required_pressure, required_hold = calcs.required_test_envelope(model, test_type)
    if dec(test_pressure_bar) < dec(required_pressure):
        raise api_error(
            "ERR_TEST_PRESSURE_BELOW_STANDARD",
            "test_pressure_bar is below the required %s bar" % required_pressure,
        )
    if hold_seconds < required_hold:
        raise api_error(
            "ERR_TEST_HOLD_TIME_SHORT",
            "hold_seconds is below the required %s seconds" % required_hold,
        )

    for other in db.test_records.values():
        if other["test_bench_code"] != test_bench_code:
            continue
        if started_at < other["_ended_at_dt"] and other["_started_at_dt"] < ended_at:
            raise api_error(
                "ERR_TEST_BENCH_OCCUPIED",
                "bench '%s' is already occupied over that interval" % test_bench_code,
            )

    row = new_row(
        {
            "valve_unit_id": unit["id"],
            "test_type": test_type,
            "test_bench_code": test_bench_code,
            "started_at": started_at_raw,
            "ended_at": ended_at_raw,
            "_started_at_dt": started_at,
            "_ended_at_dt": ended_at,
            "test_pressure_bar": test_pressure_bar,
            "hold_seconds": hold_seconds,
            "leak_rate_ppm": leak_rate_ppm,
            "leak_drops": leak_drops,
            "result": result,
            "standard_ref": standard_ref,
            "performed_by_user_id": user_id,
            "required_pressure_bar": fnum(required_pressure, 1),
            "required_hold_seconds": required_hold,
        }
    )
    row.pop("updated_at", None)
    row.pop("version", None)
    db.test_records[row["id"]] = row

    if unit["cert_status"] in ("UNCERTIFIED", "TESTS_FAILED", "DECERTIFIED"):
        unit["cert_status"] = "TESTS_IN_PROGRESS"
    domain.refresh_unit(unit)
    touch(unit)

    return object_response(domain.serialize_test_record(row), 201)


@bp.get("/valve-mfg/valve-units/<unit_id>/test-records")
def list_test_records(unit_id):
    require_roles(ANY)
    limit, offset = parse_pagination()
    unit = domain.find_unit(unit_id)
    rows = domain.records_of_unit(unit["id"])
    test_type = filter_value("test_type")
    result = filter_value("result")
    if test_type is not None:
        rows = [r for r in rows if r["test_type"] == test_type]
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    page, total = paginate(rows, limit, offset)
    return list_response(
        [domain.serialize_test_record(r) for r in page], limit, offset, total
    )


# ------------------------------------------------------------ cert actions ---
@bp.post("/valve-mfg/valve-units/<unit_id>/cert-actions")
def cert_actions(unit_id):
    user_id, role = require_roles(["QualityManager"])
    body = get_body()
    action = get_enum(body, "action", list(CERT_ACTION_ROLES.keys()))
    require_action_role(role, action, CERT_ACTION_ROLES)
    reason = get_enum(
        body, "decertification_reason", DECERT_REASONS, required=False, default="MANUAL"
    )

    unit = domain.find_unit(unit_id)
    model = db.valve_models.get(unit["model_id"])
    lic = db.licenses.get(unit["monogram_license_id"])
    if lic is not None:
        domain.refresh_license(lic)
        domain.refresh_unit(unit)

    if action == "CERTIFY":
        if unit["cert_status"] == "CERTIFIED":
            raise api_error(
                "ERR_UNIT_ALREADY_CERTIFIED", "the unit is already CERTIFIED"
            )
        if unit["cert_status"] != "TESTS_PASSED":
            raise api_error(
                "ERR_UNIT_NOT_TEST_PASSED",
                "cert_status is %s, not TESTS_PASSED" % unit["cert_status"],
            )
        if model is None or model["status"] != "RELEASED":
            raise api_error(
                "ERR_MODEL_NOT_RELEASED", "the valve model is not RELEASED"
            )
        posture = domain.license_posture(lic) if lic is not None else "FROZEN"
        services = unit.get("special_services") or []
        if posture == "FROZEN":
            raise api_error(
                "ERR_LICENSE_POSTURE_BLOCKED", "the license compliance posture is FROZEN"
            )
        if posture == "CONDITIONAL" and services:
            raise api_error(
                "ERR_LICENSE_POSTURE_BLOCKED",
                "a CONDITIONAL license may not certify special-service units",
            )
        if model["valve_type"] not in (lic.get("scope_valve_types") or []):
            raise api_error(
                "ERR_LICENSE_SCOPE_MISMATCH",
                "valve_type %s is outside the license scope" % model["valve_type"],
            )
        qualified = domain.model_qualified_special_services(model)
        missing = [s for s in services if s not in qualified]
        if missing:
            raise api_error(
                "ERR_SPECIAL_SERVICE_NOT_QUALIFIED",
                "special services without a valid type test: %s" % ", ".join(missing),
            )
        required = domain.required_test_set(unit)
        deciding = domain.deciding_records(unit)
        for test_type in required:
            record = deciding.get(test_type)
            if record is None or record["result"] != "PASS":
                raise api_error(
                    "ERR_REQUIRED_TESTS_INCOMPLETE",
                    "required test %s has no deciding PASS record" % test_type,
                )
        for record in domain.records_of_unit(unit["id"]):
            if record["performed_by_user_id"] == user_id:
                raise api_error(
                    "ERR_SOD_TEST_WITNESS_CONFLICT",
                    "the certifying user also witnessed a test of this unit",
                )
        final_class = domain.time_weighted_leak_class(unit)
        if "FUGITIVE_EMISSION" in services and final_class not in ("AA", "A", "B"):
            raise api_error(
                "ERR_EMISSION_CLASS_FAIL",
                "the time-weighted emission class is %s" % final_class,
            )

        unit["cert_status"] = "CERTIFIED"
        unit["certified_by_user_id"] = user_id
        unit["certified_at"] = clock_iso()
        unit["decertification_reason"] = None
        unit["final_emission_leak_class"] = final_class
        touch(unit)
        order = db.orders.get(unit.get("engineered_order_id"))
        if order is not None:
            touch(order)

    else:  # DECERTIFY
        if unit["cert_status"] != "CERTIFIED":
            raise api_error(
                "ERR_STATE_INVALID",
                "DECERTIFY requires cert_status CERTIFIED (current: %s)"
                % unit["cert_status"],
            )
        domain.decertify_unit(unit, reason)

    return object_response(domain.serialize_unit(unit))


# --------------------------------------------------------- service actions ---
@bp.post("/valve-mfg/valve-units/<unit_id>/service-actions")
def service_actions(unit_id):
    _user_id, role = require_roles(["FieldServiceCoordinator"])
    body = get_body()
    action = get_enum(body, "action", list(SERVICE_ACTION_ROLES.keys()))
    require_action_role(role, action, SERVICE_ACTION_ROLES)
    engineer_user_id = get_string(
        body, "engineer_user_id", required=(action == "OPEN"), default=None
    )
    kit_qty = get_int(
        body, "kit_qty", required=(action == "RESERVE_KIT"), default=None, minimum=1
    )

    unit = domain.find_unit(unit_id)
    model = db.valve_models.get(unit["model_id"])

    if action == "OPEN":
        if unit["service_status"] not in ("NONE", "SERVICED"):
            raise api_error(
                "ERR_STATE_INVALID",
                "OPEN requires service_status NONE or SERVICED (current: %s)"
                % unit["service_status"],
            )
        if unit["build_status"] not in ("PACKAGED", "SHIPPED", "REWORK"):
            raise api_error(
                "ERR_STATE_INVALID",
                "OPEN requires build_status PACKAGED, SHIPPED or REWORK (current: %s)"
                % unit["build_status"],
            )
        unit["service_status"] = "OPEN"
        unit["service_engineer_user_id"] = engineer_user_id
        touch(unit)

    elif action == "RESERVE_KIT":
        if unit["service_status"] != "OPEN":
            raise api_error(
                "ERR_STATE_INVALID",
                "RESERVE_KIT requires service_status OPEN (current: %s)"
                % unit["service_status"],
            )
        stock = model["repair_kit_stock_qty"] if model is not None else 0
        if kit_qty > stock:
            raise api_error(
                "ERR_REPAIR_KIT_OUT_OF_STOCK",
                "only %s repair kits are on hand" % stock,
            )
        model["repair_kit_stock_qty"] = stock - kit_qty
        touch(model)
        unit["reserved_kit_qty"] = kit_qty
        unit["service_status"] = "PARTS_RESERVED"
        touch(unit)

    elif action == "START":
        if unit["service_status"] != "PARTS_RESERVED":
            raise api_error(
                "ERR_STATE_INVALID",
                "START requires service_status PARTS_RESERVED (current: %s)"
                % unit["service_status"],
            )
        unit["service_status"] = "IN_SERVICE"
        if unit["cert_status"] == "CERTIFIED":
            domain.decertify_unit(unit, "MANUAL")
        else:
            if unit["build_status"] in ("ASSEMBLED", "PACKAGED"):
                unit["build_status"] = "REWORK"
            touch(unit)

    elif action == "COMPLETE":
        if unit["service_status"] != "IN_SERVICE":
            raise api_error(
                "ERR_STATE_INVALID",
                "COMPLETE requires service_status IN_SERVICE (current: %s)"
                % unit["service_status"],
            )
        unit["service_status"] = "SERVICED"
        unit["reserved_kit_qty"] = 0
        unit["service_engineer_user_id"] = None
        touch(unit)

    else:  # ABORT
        if unit["service_status"] not in ("OPEN", "PARTS_RESERVED", "IN_SERVICE"):
            raise api_error(
                "ERR_STATE_INVALID",
                "ABORT is not available from service_status %s" % unit["service_status"],
            )
        reserved = unit.get("reserved_kit_qty", 0) or 0
        if reserved and model is not None:
            model["repair_kit_stock_qty"] = model["repair_kit_stock_qty"] + reserved
            touch(model)
        unit["reserved_kit_qty"] = 0
        unit["service_engineer_user_id"] = None
        unit["service_status"] = "NONE"
        touch(unit)

    return object_response(domain.serialize_unit(unit))
