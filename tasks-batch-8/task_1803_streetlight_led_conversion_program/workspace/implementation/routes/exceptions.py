"""ComplianceException endpoints (PRD 3.8)."""
from flask import Blueprint

from db import new_record, store, touch
from domain import program_of_exception, require_active, ser_exception
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from util import CLOCK, parse_date
from validate import get_body, req_date, req_enum, req_int, req_str
from routes.common import list_endpoint, require_record

bp = Blueprint("exceptions", __name__)

PM = ["ProgramManager"]
CO = ["ComplianceOfficer"]
KINDS = ["CCT_WAIVER", "CONVERSION_EXEMPTION"]


@bp.route("/streetlights/compliance-exceptions", methods=["POST"])
@locked
def create_exception():
    caller = get_caller()
    body = get_body()
    pole_id = req_str(body, "pole_id")
    kind = req_enum(body, "exception_kind", KINDS)
    valid_until = req_date(body, "valid_until")
    if kind == "CCT_WAIVER":
        requested_cct = req_int(body, "requested_cct_kelvin", positive=True)
    else:
        if body.get("requested_cct_kelvin") is not None:
            raise_error("ERR_INVALID_REQUEST",
                        "requested_cct_kelvin must be null for CONVERSION_EXEMPTION")
        requested_cct = None
    require_roles(caller, PM)
    pole = store.poles.get(pole_id)
    if pole is None:
        raise_error("ERR_POLE_NOT_FOUND", f"pole not found: {pole_id}")
    require_active(program_of_exception({"pole_id": pole_id}))
    if valid_until < str(CLOCK.today()):
        raise_error("ERR_EXCEPTION_WINDOW_PAST", "valid_until must not be before the current date")
    rec = new_record("exceptions", {
        "pole_id": pole_id,
        "exception_kind": kind,
        "requested_cct_kelvin": requested_cct,
        "valid_until": valid_until,
        "decided_by_user_id": None,
        "status": "REQUESTED",
    })
    return success_object(ser_exception(rec), status=201)


@bp.route("/streetlights/compliance-exceptions", methods=["GET"])
@locked
def list_exceptions():
    return list_endpoint("exceptions", ser_exception,
                         ["pole_id", "exception_kind", "status"])


@bp.route("/streetlights/compliance-exceptions/<eid>", methods=["GET"])
@locked
def get_exception(eid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("exceptions", eid, "ERR_EXCEPTION_NOT_FOUND")
    return success_object(ser_exception(rec))


@bp.route("/streetlights/compliance-exceptions/<eid>/approve", methods=["POST"])
@locked
def approve_exception(eid):
    caller = get_caller()
    require_roles(caller, CO)
    exc = require_record("exceptions", eid, "ERR_EXCEPTION_NOT_FOUND")
    require_active(program_of_exception(exc))
    if exc["status"] != "REQUESTED":
        raise_error("ERR_EXCEPTION_NOT_PENDING", "approve requires a REQUESTED exception")
    pole = store.poles[exc["pole_id"]]
    if exc["exception_kind"] == "CONVERSION_EXEMPTION" and pole["status"] != "AUDIT_CLEARED":
        raise_error("ERR_POLE_NOT_AUDIT_CLEARED",
                    "CONVERSION_EXEMPTION approval requires an AUDIT_CLEARED pole")
    if exc["valid_until"] < str(CLOCK.today()):
        raise_error("ERR_EXCEPTION_WINDOW_PAST", "valid_until must not be before the current date")
    exc["decided_by_user_id"] = caller.user_id
    exc["status"] = "APPROVED"
    touch(exc)
    if exc["exception_kind"] == "CONVERSION_EXEMPTION":
        pole["status"] = "EXEMPT"
        touch(pole)
    return success_object(ser_exception(exc))


@bp.route("/streetlights/compliance-exceptions/<eid>/deny", methods=["POST"])
@locked
def deny_exception(eid):
    caller = get_caller()
    require_roles(caller, CO)
    exc = require_record("exceptions", eid, "ERR_EXCEPTION_NOT_FOUND")
    require_active(program_of_exception(exc))
    if exc["status"] != "REQUESTED":
        raise_error("ERR_EXCEPTION_NOT_PENDING", "deny requires a REQUESTED exception")
    exc["decided_by_user_id"] = caller.user_id
    exc["status"] = "DENIED"
    touch(exc)
    return success_object(ser_exception(exc))


@bp.route("/streetlights/compliance-exceptions/<eid>/refresh", methods=["POST"])
@locked
def refresh_exception(eid):
    """Any authenticated role may materialize time-based expiry."""
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    exc = require_record("exceptions", eid, "ERR_EXCEPTION_NOT_FOUND")
    require_active(program_of_exception(exc))
    if exc["status"] != "APPROVED":
        raise_error("ERR_EXCEPTION_NOT_PENDING", "refresh requires an APPROVED exception")
    if not (CLOCK.today() > parse_date(exc["valid_until"])):
        raise_error("ERR_EXCEPTION_NOT_EXPIRED", "the exception has not passed its valid_until")
    exc["status"] = "EXPIRED"
    touch(exc)
    return success_object(ser_exception(exc))
