"""FalseAlarmCase endpoints."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, MARSHAL_AND_ADMIN,
    ROLE_CONTRACTOR_ADMIN, ROLE_FIRE_MARSHAL,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_enum, req_datetime
from errors import invalid_state
from services.core import (
    base_record, public, touch,
    get_property, get_alarm_case,
    contractor_of_property, require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("alarms", __name__)

CAUSE_CODES = {"NEGLIGENCE", "EQUIPMENT_FAULT", "UNKNOWN", "MALICIOUS", "WEATHER"}


@bp.route("/fire-compliance/properties/<pid>/false-alarm-cases", methods=["POST"])
def create_alarm_case(pid):
    require_roles([ROLE_FIRE_MARSHAL])
    prop = get_property(pid)
    body = get_body()
    check_unknown_fields(body, {"alarm_occurred_at", "cause_code"})
    alarm_occurred_at = req_datetime(body, "alarm_occurred_at")
    con = contractor_of_property(prop)
    require_contractor_active(con)
    require_property_active(prop)
    cause_code = req_enum(body, "cause_code", CAUSE_CODES)

    chargeable = cause_code in calc.CHARGEABLE_CAUSES
    alarm_date = alarm_occurred_at.date()
    sequence = calc.false_alarm_sequence_number(prop, alarm_date) if chargeable else None

    rec = base_record()
    rec.update({
        "property_id": prop["id"],
        "alarm_occurred_at": alarm_occurred_at,
        "cause_code": cause_code,
        "chargeable": chargeable,
        "sequence_number": sequence,
        "fee_cents": 0,
        "waived": False,
        "status": "OPEN",
    })
    store.false_alarm_cases[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/properties/<pid>/false-alarm-cases", methods=["GET"])
def list_alarm_cases(pid):
    require_roles(MARSHAL_AND_ADMIN)
    prop = get_property(pid)
    status = request.args.get("status")
    rows = [c for c in store.false_alarm_cases.values() if c["property_id"] == prop["id"]]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/false-alarm-cases/<aid>", methods=["GET"])
def fetch_alarm_case(aid):
    require_roles(MARSHAL_AND_ADMIN)
    return success_object(public(get_alarm_case(aid)))


@bp.route("/fire-compliance/false-alarm-cases/<aid>/assess", methods=["POST"])
def assess_alarm_case(aid):
    require_roles([ROLE_FIRE_MARSHAL])
    case = get_alarm_case(aid)
    if case["status"] != "OPEN":
        raise invalid_state("FalseAlarmCase is not OPEN")
    prop = store.properties.get(case["property_id"])
    if case["chargeable"] and case["sequence_number"] is not None:
        case["fee_cents"] = calc.false_alarm_fee_cents(
            prop["occupancy_class"] if prop else "", case["sequence_number"])
    else:
        case["fee_cents"] = 0
    case["status"] = "ASSESSED"
    touch(case)
    con = contractor_of_property(prop) if prop else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(case))


@bp.route("/fire-compliance/false-alarm-cases/<aid>/waive", methods=["POST"])
def waive_alarm_case(aid):
    require_roles([ROLE_FIRE_MARSHAL])
    case = get_alarm_case(aid)
    if case["status"] not in ("OPEN", "ASSESSED"):
        raise invalid_state("FalseAlarmCase is not OPEN or ASSESSED")
    case["fee_cents"] = 0
    case["waived"] = True
    case["status"] = "WAIVED"
    touch(case)
    prop = store.properties.get(case["property_id"])
    con = contractor_of_property(prop) if prop else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(case))


@bp.route("/fire-compliance/false-alarm-cases/<aid>/record-payment", methods=["POST"])
def record_alarm_payment(aid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    case = get_alarm_case(aid)
    if case["status"] != "ASSESSED":
        raise invalid_state("FalseAlarmCase is not ASSESSED")
    prop = store.properties.get(case["property_id"])
    con = contractor_of_property(prop) if prop else None
    require_contractor_active(con)
    require_property_active(prop)
    case["status"] = "PAID"
    touch(case)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(case))
