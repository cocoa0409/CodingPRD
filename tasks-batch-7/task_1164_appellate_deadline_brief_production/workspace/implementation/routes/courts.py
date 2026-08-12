"""Court endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_str, req_int, req_bool, req_enum,
    new_entity, paginate, path_court,
)

bp = Blueprint("courts", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


@bp.post("/appellate/courts")
def create_court():
    auth = get_auth()
    require_roles(auth, ("CourtAdmin",))
    body = get_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    jurisdiction = req_enum(body, "jurisdiction_type", ("FEDERAL", "STATE", "TRIBAL"))
    appeal_days = req_int(body, "appeal_deadline_days")
    reply_window = req_int(body, "reply_brief_window_days")
    uses_word = req_bool(body, "uses_word_count")
    mwo = req_int(body, "max_words_opening")
    mpo = req_int(body, "max_pages_opening")
    mwr = req_int(body, "max_words_reply")
    mpr = req_int(body, "max_pages_reply")
    efiling = req_bool(body, "efiling_required")
    rollforward = req_bool(body, "weekend_holiday_rollforward")

    for c in STORE.courts.values():
        if c["code"] == code:
            raise ApiError("ERR_DUPLICATE", "Court code already registered", 409)

    court = new_entity({
        "code": code,
        "name": name,
        "jurisdiction_type": jurisdiction,
        "appeal_deadline_days": appeal_days,
        "reply_brief_window_days": reply_window,
        "uses_word_count": uses_word,
        "max_words_opening": mwo,
        "max_pages_opening": mpo,
        "max_words_reply": mwr,
        "max_pages_reply": mpr,
        "efiling_required": efiling,
        "weekend_holiday_rollforward": rollforward,
    })
    STORE.courts[court["id"]] = court
    court.pop("_seq", None)
    return success_object(court, 201)


@bp.get("/appellate/courts/<cid>")
def get_court(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    court = path_court(cid)
    out = dict(court)
    out.pop("_seq", None)
    return success_object(out)


@bp.get("/appellate/courts")
def list_courts():
    auth = get_auth()
    require_roles(auth, ALL)
    items = list(STORE.courts.values())
    jt = request.args.get("jurisdiction_type")
    if jt is not None:
        items = [c for c in items if c["jurisdiction_type"] == jt]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)
