"""The hearing calendar: one officer's sitting in one room."""

from flask import Blueprint

import calc
import engine
import rt
from core import (F, authenticate, created, listing, ok, q, q_instant, validate)
from errors import ApiError
from store import base_row, now, store, touch

bp = Blueprint("dockets", __name__)

CREATE_ROLES = ["ProgramAdministrator", "HearingOfficer"]
READ_ROLES = ["ProgramAdministrator", "HearingOfficer",
              "FalseAlarmReviewOfficer", "PermitClerk", "AlarmUser"]
LIVE_DOCKET_STATUSES = ("OPEN", "CLOSED_FOR_SCHEDULING", "HELD")
SEATABLE_STATUSES = ("OPEN", "CLOSED_FOR_SCHEDULING")

CREATE_FIELDS = [
    F("hearing_officer_user_id", "string"),
    F("session_start", "ts"),
    F("session_end", "ts"),
    F("location", "string"),
    F("capacity", "int", min=1, max=8, required=False),
]

CANCEL_FIELDS = [F("cancellation_reason", "string", required=False)]


@bp.post("/hearing-dockets")
def create_docket():
    ctx = authenticate(CREATE_ROLES)
    data = validate(ctx.body, CREATE_FIELDS)
    start = data["session_start"]
    end = data["session_end"]
    if start <= now() or end <= start:
        raise ApiError("ERR_HEARING_SESSION_IN_PAST",
                       "The session must open in the future and end after it "
                       "starts.")
    officer = data["hearing_officer_user_id"]
    for docket in rt.all_rows("HearingDocket"):
        if docket.get("hearing_officer_user_id") != officer:
            continue
        if docket.get("status") not in LIVE_DOCKET_STATUSES:
            continue
        if calc.docket_sessions_conflict(start, end, docket.get("session_start"),
                                        docket.get("session_end")):
            raise ApiError("ERR_DOCKET_SESSION_OVERLAP",
                           "This officer already sits across that window.")
    row = base_row()
    row["hearing_officer_user_id"] = officer
    row["session_start"] = start
    row["session_end"] = end
    row["location"] = data["location"]
    row["capacity"] = data.get("capacity", 4)
    row["scheduled_appeal_count"] = 0
    row["status"] = "OPEN"
    row["held_at"] = None
    store.hearing_dockets[row["id"]] = row
    return created(row)


@bp.post("/hearing-dockets/<docket_id>/hold-session")
def hold_session(docket_id):
    ctx = authenticate(["HearingOfficer"])
    docket = rt.resolve("HearingDocket", docket_id)
    if docket.get("hearing_officer_user_id") != ctx.user_id:
        raise ApiError("ERR_NOT_DOCKET_OFFICER",
                       "Only the docket's own officer may hold the session.")
    if docket.get("status") not in SEATABLE_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "A %s docket may not be held." % docket.get("status"))
    session_start = docket.get("session_start")
    if session_start is not None and now() < session_start:
        raise ApiError("ERR_HEARING_SESSION_NOT_STARTED",
                       "The logical clock has not reached the session start.")
    if (docket.get("scheduled_appeal_count") or 0) < 1:
        raise ApiError("ERR_DOCKET_EMPTY", "The docket seats no appeal.")
    docket["status"] = "HELD"
    docket["held_at"] = now()
    touch(docket)
    for appeal in engine.docket_appeals(docket["id"]):
        if appeal.get("status") == "SCHEDULED":
            appeal["status"] = "HEARD"
            touch(appeal)
    return ok(docket)


@bp.post("/hearing-dockets/<docket_id>/cancel")
def cancel_docket(docket_id):
    ctx = authenticate(CREATE_ROLES)
    validate(ctx.body, CANCEL_FIELDS)
    docket = rt.resolve("HearingDocket", docket_id)
    if docket.get("status") not in SEATABLE_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "A %s docket may not be cancelled." % docket.get("status"))
    for appeal in engine.docket_appeals(docket["id"]):
        if appeal.get("status") == "SCHEDULED":
            appeal["status"] = "FILED"
            appeal["hearing_docket_id"] = None
            touch(appeal)
    docket["status"] = "CANCELLED"
    docket["scheduled_appeal_count"] = 0
    touch(docket)
    return ok(docket)


@bp.get("/hearing-dockets/<docket_id>")
def get_docket(docket_id):
    authenticate(READ_ROLES)
    return ok(rt.resolve("HearingDocket", docket_id))


@bp.get("/hearing-dockets")
def list_dockets():
    authenticate(READ_ROLES)
    rows = rt.all_rows("HearingDocket")
    for field in ("hearing_officer_user_id", "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    session_from = q_instant("session_from")
    session_to = q_instant("session_to")
    if session_from is not None:
        rows = [r for r in rows if r.get("session_start") is not None
                and r["session_start"] >= session_from]
    if session_to is not None:
        rows = [r for r in rows if r.get("session_start") is not None
                and r["session_start"] <= session_to]
    return listing(rows, rt.fields("HearingDocket"))
