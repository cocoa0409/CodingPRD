"""Case intake, triage, close, list/get."""
from flask import Blueprint, request

import errors
import lookup
import validate
from db import db, SERVED_COUNTIES
from middleware import require, authenticate, json_body, paginate
from records import make_record, touch, public
from response import object_response, array_response
import services

bp = Blueprint("cases", __name__)

CASE_TYPES = {"NATURAL", "ACCIDENT", "HOMICIDE", "PENDING"}
TRIAGE_TYPES = {"NATURAL", "ACCIDENT", "HOMICIDE"}


def _autopsy_required(case_type):
    return case_type in ("HOMICIDE", "ACCIDENT")


@bp.post("/cases")
def report_death():
    # Anonymous allowed (plus Investigator, Admin). Still require valid headers/role.
    user_id, role = authenticate()
    if role not in {"Anonymous", "Investigator", "Admin"}:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted to report a death")
    # entity-identity resolution for entity-backed roles
    from middleware import _resolve_identity
    _resolve_identity(user_id, role)

    body = json_body()
    decedent_name = validate.req_str(body, "decedent_name")
    reported_death_at = validate.req_datetime(body, "reported_death_at")
    death_location_county = validate.req_str(body, "death_location_county")
    investigator_user_id = validate.req_str(body, "investigator_user_id")

    from clock import fmt_iso
    rec = make_record({
        "decedent_name": decedent_name,
        "reported_death_at": fmt_iso(reported_death_at),
        "death_location_county": death_location_county,
        "jurisdiction_status": None,
        "case_type": "PENDING",
        "status": "REPORTED",
        "investigator_user_id": investigator_user_id,
        "served_county": None,
        "autopsy_required": False,
        "closed_at": None,
    })
    db.cases[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/cases/<id_>")
def get_case(id_):
    require({"Admin", "Investigator", "MedicalExaminer", "Pathologist"})
    rec = lookup.case(id_)
    return object_response(public(rec), 200)


@bp.get("/cases")
def list_cases():
    require({"Admin", "Investigator", "MedicalExaminer"})
    rows = list(db.cases.values())
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    inv = request.args.get("investigator_user_id")
    if inv is not None:
        rows = [c for c in rows if c["investigator_user_id"] == inv]
    page, limit, offset, total = paginate(rows)
    return array_response([public(c) for c in page], limit, offset, total)


@bp.post("/cases/<id_>/triage")
def triage(id_):
    require({"Investigator"})
    case = lookup.case(id_)
    body = json_body()
    case_type = validate.req_enum(body, "case_type", TRIAGE_TYPES)

    # state legality (priority 21)
    if case["status"] != "REPORTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Triage only allowed from REPORTED")

    served = case["death_location_county"] in SERVED_COUNTIES
    if served:
        case["jurisdiction_status"] = "ACCEPTED"
        case["served_county"] = True
        case["case_type"] = case_type
        case["autopsy_required"] = _autopsy_required(case_type)
        case["status"] = "ACCEPTED"
    else:
        case["jurisdiction_status"] = "DECLINED"
        case["served_county"] = False
        case["status"] = "DECLINED"
    touch(case)
    return object_response(public(case), 200)


@bp.post("/cases/<id_>/close")
def close_case(id_):
    require({"Investigator"})
    case = lookup.case(id_)
    if case["status"] != "CERTIFIED":
        raise errors.err(errors.ERR_INVALID_STATE, "Close only allowed from CERTIFIED")
    body = services.case_body(case["id"])
    if body is None or body["storage_status"] != "RELEASED":
        raise errors.err(errors.ERR_INVALID_STATE, "Case body must be RELEASED before close")
    if any(p["item_status"] == "HELD" for p in services.case_property_items(case["id"])):
        raise errors.err(errors.ERR_INVALID_STATE, "No property item may remain HELD before close")
    case["status"] = "CLOSED"
    case["closed_at"] = db.clock.now_iso()
    touch(case)
    return object_response(public(case), 200)
