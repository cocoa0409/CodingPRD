from flask import Blueprint, request

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import new_common, touch, get_or_404
from serialize import minute_out
from validate import (body, no_unknown, req_str, req_date, req_list, pagination)

bp = Blueprint("minutes", __name__)

READ_ROLES = ("Advisor", "ComplianceOfficer", "CommitteeMember", "CommitteeChair")


@bp.post("/advisory/committee-minutes")
def create_minute():
    uid, _ = authorize("CommitteeMember")
    b = body()
    no_unknown(b, {"meeting_date", "amendment_refs", "decisions_text"})
    meeting_date = req_date(b, "meeting_date")
    refs = req_list(b, "amendment_refs")
    for r in refs:
        if not isinstance(r, str):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "amendment_refs elements must be strings")
    decisions_text = req_str(b, "decisions_text")
    for r in refs:
        if r not in db.amendments:
            raise ApiError("ERR_INVALID_REFERENCE", 422,
                           "amendment_refs element does not resolve")
    if meeting_date > clock.now().date():
        raise ApiError("ERR_MEETING_DATE_IN_FUTURE", 422,
                       "meeting_date may not be future-dated")
    m = new_common()
    m.update({
        "meeting_date_d": meeting_date, "amendment_refs": list(refs),
        "decisions_text": decisions_text, "recorded_by_user_id": uid,
        "status": "DRAFT", "ratified_by_user_id": None, "ratified_at_dt": None,
    })
    db.minutes[m["id"]] = m
    return obj(minute_out(m), 201)


@bp.get("/advisory/committee-minutes")
def list_minutes():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    rows = sorted(db.minutes.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    status = request.args.get("status")
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    total = len(rows)
    return page([minute_out(m) for m in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/committee-minutes/<mid>")
def get_minute(mid):
    authorize(*READ_ROLES)
    m = get_or_404(db.minutes, mid)
    return obj(minute_out(m))


@bp.post("/advisory/committee-minutes/<mid>/ratify")
def ratify_minute(mid):
    uid, _ = authorize("CommitteeChair")
    if request.data:
        no_unknown(body(), set())
    m = get_or_404(db.minutes, mid)
    # PRD §3.8 battery order: DRAFT -> SoD -> refs resolve.
    if m["status"] != "DRAFT":
        raise ApiError("ERR_MINUTE_INVALID_STATE", 409,
                       "Ratify requires DRAFT")
    if uid == m["recorded_by_user_id"]:
        raise ApiError("ERR_SOD_MINUTE_SELF_RATIFY", 422,
                       "The recorder may not ratify their own minute")
    for r in m["amendment_refs"]:
        if r not in db.amendments:
            raise ApiError("ERR_INVALID_REFERENCE", 422,
                           "amendment_refs element does not resolve")
    m["status"] = "RATIFIED"
    m["ratified_by_user_id"] = uid
    m["ratified_at_dt"] = clock.now()
    touch(m)
    return obj(minute_out(m))
