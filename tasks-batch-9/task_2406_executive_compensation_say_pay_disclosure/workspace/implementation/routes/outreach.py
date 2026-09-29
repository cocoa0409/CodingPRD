"""Shareholder outreach: requesting, scheduling and holding engagements (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint, request

from db import apply_changes, insert, now, sec, store, touch
from errors import ApiError
from middleware import (
    ROLE_CHAIR,
    ROLE_COMP_CONSULTANT,
    ROLE_COUNSEL,
    ROLE_IR_LEAD,
    authenticate,
)
from response import object_response
from routes.common import fetch, paginated
from services import domain
from validation import Body

bp = Blueprint("outreach", __name__)

CHANNELS = {"CALL", "MEETING", "LETTER"}
POSITIONS = {"SUPPORTIVE", "CONCERNED", "OPPOSED"}
QUIET_PERIOD_DAYS = 10
RIVAL_STATUSES = ("SCHEDULED", "HELD")


@bp.post("/exec-comp/pay-programs/<pid>/outreach-engagements")
def request_engagement(pid):
    authenticate([ROLE_IR_LEAD])
    program = fetch("pay_programs", pid)
    body = Body()
    investor_name = body.string("investor_name", required=True, min_len=1, max_len=120)
    ownership_pct = body.number(
        "ownership_pct", required=True, minimum="0.01", maximum=100, places=2
    )
    channel = body.enum("channel", CHANNELS, required=True)

    engagement = insert(
        store.outreach_engagements,
        {
            "pay_program_id": program["id"],
            "investor_name": investor_name,
            "investor_key": investor_name.strip().upper(),
            "ownership_pct": ownership_pct,
            "channel": channel,
            "window_start": None,
            "window_end": None,
            "engagement_status": "REQUESTED",
            "feedback_position": None,
            "feedback_summary": None,
            "held_at": None,
        },
    )
    return object_response(engagement, 201)


@bp.get("/exec-comp/pay-programs/<pid>/outreach-engagements")
def list_engagements(pid):
    authenticate([ROLE_IR_LEAD, ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    program = fetch("pay_programs", pid)
    rows = domain.program_engagements(program["id"])
    wanted = request.args.get("engagement_status")
    if wanted is not None:
        rows = [r for r in rows if r["engagement_status"] == wanted]
    return paginated(rows)


@bp.post("/exec-comp/outreach-engagements/<eid>/schedule")
def schedule_engagement(eid):
    authenticate([ROLE_IR_LEAD])
    engagement = fetch("outreach_engagements", eid)
    body = Body()
    window_start = body.instant("window_start", required=True)
    window_end = body.instant("window_end", required=True)
    if sec(window_end) <= sec(window_start):
        raise ApiError(
            "ERR_INVALID_REQUEST", "window_end must be strictly after window_start"
        )

    if engagement["engagement_status"] != "REQUESTED":
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")

    program = store.pay_programs[engagement["pay_program_id"]]
    meeting = sec(program["meeting_date"])
    blackout_start = meeting - timedelta(days=QUIET_PERIOD_DAYS)
    if sec(window_start) <= meeting and sec(window_end) > blackout_start:
        raise ApiError("ERR_QUIET_PERIOD_ENGAGEMENT")

    if sec(window_start) < sec(now()):
        raise ApiError("ERR_ENGAGEMENT_WINDOW_IN_PAST")

    for rival in domain.program_engagements(program["id"]):
        if rival["id"] == engagement["id"]:
            continue
        if rival["investor_key"] != engagement["investor_key"]:
            continue
        if rival["engagement_status"] not in RIVAL_STATUSES:
            continue
        if rival["window_start"] is None or rival["window_end"] is None:
            continue
        if sec(window_start) < sec(rival["window_end"]) and sec(
            rival["window_start"]
        ) < sec(window_end):
            raise ApiError("ERR_OUTREACH_WINDOW_OVERLAP")

    apply_changes(
        engagement,
        {
            "window_start": window_start,
            "window_end": window_end,
            "engagement_status": "SCHEDULED",
        },
    )
    touch(engagement)
    return object_response(engagement)


@bp.post("/exec-comp/outreach-engagements/<eid>/hold")
def hold_engagement(eid):
    authenticate([ROLE_IR_LEAD])
    engagement = fetch("outreach_engagements", eid)
    body = Body()
    feedback_position = body.enum("feedback_position", POSITIONS, required=True)
    feedback_summary = body.string("feedback_summary", max_len=2000)

    if engagement["engagement_status"] != "SCHEDULED":
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")

    apply_changes(
        engagement,
        {
            "engagement_status": "HELD",
            "feedback_position": feedback_position,
            "feedback_summary": feedback_summary,
            "held_at": now(),
        },
    )
    touch(engagement)

    program = store.pay_programs[engagement["pay_program_id"]]
    domain.recompute_program_coverage(program)
    domain.mark_screens_stale(program)
    return object_response(engagement)
