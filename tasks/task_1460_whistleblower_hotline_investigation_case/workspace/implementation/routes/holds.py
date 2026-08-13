"""Legal hold endpoints (PRD 3.8): closed-interval holds with zero-buffer
touch/overlap rejection and release under segregation of duties."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    CASE_TERMINAL_STATES,
    add_event,
    bump,
    get_case,
    get_hold,
    hold_view,
    maybe_close_out,
    paginate,
)
from util import body, pagination_args, req, req_dt, req_str

bp = Blueprint("holds", __name__)


@bp.post("/hotline/legal-holds")
def create_hold():
    user_id, role = auth(["ComplianceOfficer"])
    data = body()
    case_id = req(data, "case_id")
    if not isinstance(case_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field case_id must be a string")
    start_at = req_dt(data, "start_at")
    end_at = req_dt(data, "end_at")
    reason = req_str(data, "reason", min_len=10)
    # Closed interval: end_at no earlier than start_at.
    if end_at < start_at:
        raise ApiError(
            "ERR_INVALID_INTERVAL", 400, "end_at must not be earlier than start_at"
        )
    case = get_case(case_id)
    if case["status"] in CASE_TERMINAL_STATES:
        raise ApiError(
            "ERR_CASE_TERMINAL", 409, "Legal holds attach only to non-terminal cases"
        )
    # Closed intervals on one case must not touch or overlap (zero buffer).
    for other in DB["legal_holds"].values():
        if other["case_id"] != case["id"] or other["status"] != "ACTIVE":
            continue
        if start_at <= other["end_at"] and other["start_at"] <= end_at:
            raise ApiError(
                "ERR_LEGAL_HOLD_OVERLAP",
                409,
                "The hold interval touches or overlaps an ACTIVE hold on the case",
            )

    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
        "status": "ACTIVE",
        "placed_by_id": user_id,
        "released_by_id": None,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["legal_holds"][rec["id"]] = rec
    add_event(case["id"], "LEGAL_HOLD_PLACED", None, "ACTIVE", role, user_id)
    return ok(hold_view(rec), status=201)


@bp.get("/hotline/cases/<cid>/legal-holds")
def list_holds(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [h for h in DB["legal_holds"].values() if h["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [h for h in records if h["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([hold_view(h) for h in page], total, limit, offset)


@bp.post("/hotline/legal-holds/<hid>/release")
def release_hold(hid):
    user_id, role = auth(["ComplianceOfficer"])
    hold = get_hold(hid)
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_HOLD_NOT_ACTIVE", 409, "Release requires hold ACTIVE")
    if user_id == hold["placed_by_id"]:
        raise ApiError(
            "ERR_SOD_HOLD_RELEASE",
            409,
            "The releasing officer must differ from the placing officer",
        )
    hold["status"] = "RELEASED"
    hold["released_by_id"] = user_id
    bump(hold)
    add_event(hold["case_id"], "LEGAL_HOLD_RELEASED", "ACTIVE", "RELEASED", role, user_id)
    # Re-evaluate any close-out deferred by the FROZEN posture.
    case = DB["cases"].get(hold["case_id"])
    if case is not None:
        maybe_close_out(case, role, user_id)
    return ok(hold_view(hold))
