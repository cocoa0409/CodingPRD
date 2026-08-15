"""CommunicationNotice endpoints (PRD §3.8): retrieval and send/retry."""

from flask import Blueprint, request

from db import CLOCK, NOTICES, now_iso, pub, touch
from errors import ApiError, ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import body, paginate, parse_date, req_enum

bp = Blueprint("notices", __name__)

DELIVERY_OUTCOMES = ("DELIVERED", "FAILED")


@bp.get("/recovery/notices/<string:noticeId>")
@require_roles(*ALL_ROLES)
def get_notice(noticeId):
    n = NOTICES.get(noticeId)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, "Communication notice not found", 404)
    return success_object(pub(n))


@bp.get("/recovery/notices")
@require_roles(*ALL_ROLES)
def list_notices():
    member_id = request.args.get("member_id")
    case_id = request.args.get("case_id")
    estate_case_id = request.args.get("estate_case_id")
    notice_type = request.args.get("notice_type")
    status = request.args.get("status")
    items = []
    for n in NOTICES.values():
        if member_id is not None and n["member_id"] != member_id:
            continue
        if case_id is not None and n["case_id"] != case_id:
            continue
        if estate_case_id is not None and n["estate_case_id"] != estate_case_id:
            continue
        if notice_type is not None and n["notice_type"] != notice_type:
            continue
        if status is not None and n["status"] != status:
            continue
        items.append(n)
    ordered, limit, offset = paginate(items)
    page = [pub(n) for n in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


@bp.post("/recovery/notices/<string:noticeId>/send")
@require_roles("RecoverySpecialist")
def send_notice(noticeId):
    b = body()
    outcome = req_enum(b, "delivery_outcome", DELIVERY_OUTCOMES)
    n = NOTICES.get(noticeId)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, "Communication notice not found", 404)
    # §3.8: sends and retries are defined from QUEUED and FAILED; DELIVERED is
    # terminal — sending it is a generic state error.
    if n["status"] not in ("QUEUED", "FAILED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Only a QUEUED or FAILED notice may be sent",
            409,
        )
    n["status"] = outcome
    n["sent_at"] = now_iso()
    # §3.8: is_late is true exactly when the sent calendar date falls after
    # the due_date; recomputed on every attempt.
    n["is_late"] = CLOCK.today() > parse_date(n["due_date"])
    touch(n)
    return success_object(pub(n))
