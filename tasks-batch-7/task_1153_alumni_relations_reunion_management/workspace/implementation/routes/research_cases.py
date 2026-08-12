"""LostAlumniResearchCase endpoints."""

from flask import Blueprint

import db
from errors import (
    err_alumnus_not_lost, err_invalid_request, err_invalid_state, err_not_found,
    err_lead_confidence, err_reopen_limit,
)
from middleware import require_roles
from response import success_list, success_object
from services.cascades import reunite_alumnus
from services.common import (
    apply_pagination, json_body, logical_ts, new_entity, pagination_args,
    req_enum, req_int, req_str, touch,
)
from services.serializers import CASE_FIELDS, serialize

bp = Blueprint("research_cases", __name__)

ROLES = ("AlumniRelationsStaff", "AlumniRelationsDirector")
LEAD_SOURCES = ("SOCIAL_MEDIA", "PUBLIC_RECORDS", "PEER_TIP", "PROFESSIONAL_DATABASE")


def _get_case(case_id):
    case = db.research_cases.get(case_id)
    if case is None:
        raise err_not_found("LostAlumniResearchCase not found")
    return case


def _validate_lead_payload(body, require_all=True):
    required = ["lead_source", "lead_detail", "lead_confidence"] if require_all else []
    for f in required:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")
    out = {}
    if "lead_source" in body and body["lead_source"] is not None:
        out["lead_source"] = req_enum(body["lead_source"], "lead_source", LEAD_SOURCES)
    if "lead_detail" in body and body["lead_detail"] is not None:
        out["lead_detail"] = req_str(body["lead_detail"], "lead_detail")
    if "lead_confidence" in body and body["lead_confidence"] is not None:
        conf = req_int(body["lead_confidence"], "lead_confidence")
        if conf < 1 or conf > 100:
            raise err_invalid_request("lead_confidence must be between 1 and 100")
        out["lead_confidence"] = conf
    return out


@bp.route("/alumni/research-cases", methods=["POST"])
@require_roles(*ROLES)
def create_case(_role, _user_id):
    body = json_body(required=["alumni_id", "lead_source", "lead_detail", "lead_confidence"])
    alumni_id = req_str(body["alumni_id"], "alumni_id")
    record = db.records.get(alumni_id)
    if record is None:
        raise err_not_found("AlumniRecord not found")
    lead = _validate_lead_payload(body)

    case = new_entity({
        "alumni_id": alumni_id,
        "lead_source": lead["lead_source"],
        "lead_detail": lead["lead_detail"],
        "lead_confidence": lead["lead_confidence"],
        "status": "OPEN",
        "reopened_count": 0,
        "resolved_at": None,
    })
    db.research_cases[case["id"]] = case
    return success_object(serialize(case, CASE_FIELDS), status=201)


@bp.route("/alumni/research-cases/<cid>", methods=["GET"])
@require_roles(*ROLES)
def get_case(cid, _role, _user_id):
    return success_object(serialize(_get_case(cid), CASE_FIELDS))


@bp.route("/alumni/research-cases", methods=["GET"])
@require_roles(*ROLES)
def list_cases(_role, _user_id):
    from flask import request
    limit, offset = pagination_args()
    rows = list(db.research_cases.values())
    alumni_id = request.args.get("alumni_id")
    if alumni_id:
        rows = [c for c in rows if c["alumni_id"] == alumni_id]
    status = request.args.get("status")
    if status:
        rows = [c for c in rows if c["status"] == status]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(c, CASE_FIELDS) for c in page], limit, offset, total)


@bp.route("/alumni/research-cases/<cid>/log-lead", methods=["POST"])
@require_roles(*ROLES)
def log_lead(cid, _role, _user_id):
    case = _get_case(cid)
    if case["status"] != "OPEN":
        raise err_invalid_state("Case must be OPEN to log a lead")
    record = db.records.get(case["alumni_id"])
    if record is None or record["status"] != "LOST":
        raise err_alumnus_not_lost()
    body = json_body(required=["lead_source", "lead_detail", "lead_confidence"])
    lead = _validate_lead_payload(body)
    case.update(lead)
    case["status"] = "LEAD_LOGGED"
    touch(case)
    return success_object(serialize(case, CASE_FIELDS))


@bp.route("/alumni/research-cases/<cid>/verify", methods=["POST"])
@require_roles(*ROLES)
def verify(cid, _role, _user_id):
    case = _get_case(cid)
    if case["status"] != "LEAD_LOGGED":
        raise err_invalid_state("Case must be LEAD_LOGGED to verify")
    if case["lead_confidence"] < 60:
        raise err_lead_confidence()
    case["status"] = "VERIFIED"
    touch(case)
    return success_object(serialize(case, CASE_FIELDS))


@bp.route("/alumni/research-cases/<cid>/reopen", methods=["POST"])
@require_roles(*ROLES)
def reopen(cid, _role, _user_id):
    case = _get_case(cid)
    if case["status"] != "VERIFIED":
        raise err_invalid_state("Case must be VERIFIED to reopen")
    if case["reopened_count"] >= 3:
        raise err_reopen_limit()
    case["status"] = "OPEN"
    case["reopened_count"] += 1
    touch(case)
    return success_object(serialize(case, CASE_FIELDS))


@bp.route("/alumni/research-cases/<cid>/reunite", methods=["POST"])
@require_roles(*ROLES)
def reunite(cid, _role, _user_id):
    case = _get_case(cid)
    if case["status"] != "VERIFIED":
        raise err_invalid_state("Case must be VERIFIED to reunite")
    record = db.records.get(case["alumni_id"])
    if record is None or record["status"] != "LOST":
        raise err_alumnus_not_lost()
    case["status"] = "REUNITED"
    case["resolved_at"] = logical_ts()
    touch(case)
    reunite_alumnus(record)
    return success_object(serialize(case, CASE_FIELDS))


@bp.route("/alumni/research-cases/<cid>/dead-end", methods=["POST"])
@require_roles(*ROLES)
def dead_end(cid, _role, _user_id):
    case = _get_case(cid)
    if case["status"] != "LEAD_LOGGED":
        raise err_invalid_state("Case must be LEAD_LOGGED to declare dead end")
    case["status"] = "DEAD_END"
    case["resolved_at"] = logical_ts()
    touch(case)
    return success_object(serialize(case, CASE_FIELDS))
