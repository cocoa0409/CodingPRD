"""Remediation action endpoints (PRD 3.6): proposal on an APPROVED SUBSTANTIATED
determination, decide, verify, and the OVERDUE extension loop."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    ACTION_TYPES,
    DECIDE_DECISIONS,
    action_view,
    bump,
    get_action,
    get_case,
    get_determination,
    maybe_close_out,
    paginate,
)
from util import body, pagination_args, req, req_dt, req_enum, req_str

bp = Blueprint("remediation", __name__)


@bp.post("/hotline/determinations/<did>/remediation-actions")
def create_action(did):
    user_id, role = auth(["ComplianceOfficer"])
    determination = get_determination(did)
    data = body()
    action_type = req_enum(data, "action_type", ACTION_TYPES)
    owner_department = req_str(data, "owner_department")
    description = req_str(data, "description", min_len=10)
    due_date = req_dt(data, "due_date")
    if not (
        determination["status"] == "APPROVED"
        and determination["finding"] == "SUBSTANTIATED"
    ):
        raise ApiError(
            "ERR_DETERMINATION_NOT_APPROVED",
            409,
            "Remediation actions require an APPROVED SUBSTANTIATED determination",
        )

    rec = {
        "id": new_id(),
        "case_id": determination["case_id"],
        "determination_id": determination["id"],
        "action_type": action_type,
        "owner_department": owner_department,
        "description": description,
        "due_date": due_date,
        "status": "PROPOSED",
        "created_by_id": user_id,
        "verified_by_id": None,
        "extension_count": 0,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["remediation_actions"][rec["id"]] = rec
    return ok(action_view(rec), status=201)


@bp.get("/hotline/cases/<cid>/remediation-actions")
def list_actions(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [a for a in DB["remediation_actions"].values() if a["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([action_view(a) for a in page], total, limit, offset)


@bp.post("/hotline/remediation-actions/<aid>/decide")
def decide_action(aid):
    user_id, role = auth(["ComplianceOfficer"])
    action = get_action(aid)
    data = body()
    decision = req_enum(data, "decision", DECIDE_DECISIONS)
    if action["status"] != "PROPOSED":
        raise ApiError(
            "ERR_REMEDIATION_INVALID_STATE", 409, "Decide requires action PROPOSED"
        )
    if user_id == action["created_by_id"]:
        raise ApiError(
            "ERR_SOD_SELF_VERIFY",
            409,
            "The deciding officer must differ from the action's creator",
        )
    action["status"] = "IN_PROGRESS" if decision == "APPROVE" else "REJECTED"
    bump(action)
    case = DB["cases"].get(action["case_id"])
    if case is not None:
        maybe_close_out(case, role, user_id)
    return ok(action_view(action))


@bp.post("/hotline/remediation-actions/<aid>/verify")
def verify_action(aid):
    user_id, role = auth(["ComplianceOfficer"])
    action = get_action(aid)
    body()
    if action["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_REMEDIATION_INVALID_STATE", 409, "Verify requires action IN_PROGRESS"
        )
    if user_id == action["created_by_id"]:
        raise ApiError(
            "ERR_SOD_SELF_VERIFY",
            409,
            "The verifying officer must differ from the action's creator",
        )
    action["status"] = "VERIFIED"
    action["verified_by_id"] = user_id
    bump(action)
    case = DB["cases"].get(action["case_id"])
    if case is not None:
        maybe_close_out(case, role, user_id)
    return ok(action_view(action))


@bp.post("/hotline/remediation-actions/<aid>/extend")
def extend_action(aid):
    user_id, role = auth(["ComplianceOfficer"])
    action = get_action(aid)
    data = body()
    new_due = req_dt(data, "due_date")
    if action["status"] != "OVERDUE":
        raise ApiError(
            "ERR_REMEDIATION_INVALID_STATE", 409, "Extend requires action OVERDUE"
        )
    now = now_dt()
    if not (new_due > now and new_due <= now + timedelta(days=30)):
        raise ApiError(
            "ERR_EXTENSION_WINDOW_EXCEEDED",
            409,
            "Extension due_date must be later than now and no later than now + 30 days",
        )
    action["due_date"] = new_due
    action["status"] = "IN_PROGRESS"
    action["extension_count"] += 1
    bump(action)
    case = DB["cases"].get(action["case_id"])
    if case is not None:
        maybe_close_out(case, role, user_id)
    return ok(action_view(action))
