"""EventEntry endpoints."""

from flask import Blueprint, request

from db import CLOCK, STORE, new_id
from errors import (
    ERR_AGE_GROUP_INELIGIBLE,
    ERR_ENTRY_DEADLINE_PASSED,
    ERR_ENTRY_NOT_FOUND,
    ERR_ENTRY_NOT_SCRATCHABLE,
    ERR_ENTRY_NOT_UNSCRATCHABLE,
    ERR_ENTRY_NOT_VERIFIABLE,
    ERR_EVENT_NOT_FOUND,
    ERR_EVENT_NOT_IN_PROGRESS,
    ERR_GENDER_INELIGIBLE,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_MEET_NOT_ACCEPTING_ENTRIES,
    ERR_RECOVERY_WINDOW_VIOLATION,
    ERR_SWIMMER_ENTRY_LIMIT,
    ERR_SWIMMER_NOT_FOUND,
    ERR_TEAM_NOT_ACTIVE,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    ACTIVE_ENTRY_STATUSES,
    bump,
    entry_team_id,
    get_or_404,
    lane_for_entry,
    meet_of_event,
    paginate,
    pub_entry,
    pub_result,
    recompute_active_entry_count,
    recovery_violation,
    req_body,
    sort_created,
    stamp,
    v_int_opt,
    v_str,
)

bp = Blueprint("entries", __name__)


def _check_ownership(entry, user_id):
    if entry_team_id(entry) != user_id:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "coach may only act on their own team's entries")


@bp.post("/entries")
def create_entry():
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    b = req_body()
    event_id = v_str(b, "event_id")
    swimmer_id = v_str(b, "swimmer_id")
    seed_time = v_int_opt(b, "seed_time_cs", None, nullable=True)
    event = get_or_404("events", event_id, ERR_EVENT_NOT_FOUND)
    swimmer = get_or_404("swimmers", swimmer_id, ERR_SWIMMER_NOT_FOUND)
    if swimmer["team_id"] != user_id:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "coach may only enter their own swimmers")
    if event["is_relay"]:
        raise_err(
            ERR_INVALID_REQUEST, "relay events are entered via POST /relay-teams only"
        )
    meet = meet_of_event(event)
    if meet["status"] != "ENTRIES_OPEN":
        raise_err(ERR_MEET_NOT_ACCEPTING_ENTRIES, "meet is not accepting entries")
    if CLOCK["now"] > meet["_deadline_dt"]:
        raise_err(ERR_ENTRY_DEADLINE_PASSED, "entry deadline has passed")
    team = STORE["teams"][swimmer["team_id"]]
    if team["status"] != "REGISTERED":
        raise_err(ERR_TEAM_NOT_ACTIVE, "team is not active")
    if swimmer["age_group"] != event["age_group"]:
        raise_err(ERR_AGE_GROUP_INELIGIBLE, "swimmer age_group does not match the event")
    if event["gender"] != "MIXED" and swimmer["gender"] != event["gender"]:
        raise_err(ERR_GENDER_INELIGIBLE, "swimmer gender does not match the event")
    # Per-swimmer individual entry cap: the Nth is allowed, the (N+1)th refused.
    ev_ids = {e["id"] for e in STORE["events"].values() if e["meet_id"] == meet["id"]}
    existing = [
        e
        for e in STORE["entries"].values()
        if e["swimmer_id"] == swimmer["id"]
        and e["event_id"] in ev_ids
        and e["status"] in ACTIVE_ENTRY_STATUSES
    ]
    if len(existing) >= meet["max_individual_entries_per_swimmer"]:
        raise_err(
            ERR_SWIMMER_ENTRY_LIMIT, "swimmer has reached the individual entry limit"
        )
    # Recovery buffer on the same session_date.
    for other in existing:
        other_event = STORE["events"].get(other["event_id"])
        if other_event is None or other_event["session_date"] != event["session_date"]:
            continue
        if recovery_violation(
            event["scheduled_start_minute"],
            event["scheduled_end_minute"],
            other_event["scheduled_start_minute"],
            other_event["scheduled_end_minute"],
            meet["min_recovery_minutes"],
        ):
            raise_err(
                ERR_RECOVERY_WINDOW_VIOLATION,
                "insufficient recovery gap between same-session events",
            )
    entry = stamp(
        {
            "id": new_id(),
            "event_id": event["id"],
            "swimmer_id": swimmer["id"],
            "relay_team_id": None,
            "seed_time_cs": seed_time,
            "qualification_status": "UNVERIFIED",
            "status": "ENTERED",
        }
    )
    STORE["entries"][entry["id"]] = entry
    recompute_active_entry_count(team["id"])
    return ok_object(pub_entry(entry), 201)


@bp.get("/entries/<eid>")
def get_entry(eid):
    ctx()
    entry = get_or_404("entries", eid, ERR_ENTRY_NOT_FOUND)
    return ok_object(pub_entry(entry))


@bp.get("/entries")
def list_entries():
    ctx()
    items = list(STORE["entries"].values())
    event_id = request.args.get("event_id")
    swimmer_id = request.args.get("swimmer_id")
    relay_team_id = request.args.get("relay_team_id")
    team_id = request.args.get("team_id")
    if event_id is not None:
        items = [e for e in items if e["event_id"] == event_id]
    if swimmer_id is not None:
        items = [e for e in items if e["swimmer_id"] == swimmer_id]
    if relay_team_id is not None:
        items = [e for e in items if e["relay_team_id"] == relay_team_id]
    if team_id is not None:
        items = [e for e in items if entry_team_id(e) == team_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_entry(e) for e in page], limit, offset, total)


@bp.post("/entries/<eid>/verify")
def verify_entry(eid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    entry = get_or_404("entries", eid, ERR_ENTRY_NOT_FOUND)
    event = STORE["events"][entry["event_id"]]
    meet = meet_of_event(event)
    if meet["status"] not in ("ENTRIES_OPEN", "ENTRIES_CLOSED") or entry["status"] != "ENTERED":
        raise_err(
            ERR_ENTRY_NOT_VERIFIABLE,
            "verify requires meet ENTRIES_OPEN|ENTRIES_CLOSED and entry ENTERED",
        )
    cut = event["qualifying_time_cs"]
    if cut is None:
        entry["qualification_status"] = "VERIFIED"
    elif entry["seed_time_cs"] is not None and entry["seed_time_cs"] <= cut:
        entry["qualification_status"] = "VERIFIED"
    else:
        entry["qualification_status"] = "REJECTED"
    bump(entry)
    return ok_object(pub_entry(entry))


@bp.post("/entries/<eid>/scratch")
def scratch_entry(eid):
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    entry = get_or_404("entries", eid, ERR_ENTRY_NOT_FOUND)
    _check_ownership(entry, user_id)
    event = STORE["events"][entry["event_id"]]
    meet = meet_of_event(event)
    if entry["status"] == "ENTERED":
        if meet["status"] not in ("ENTRIES_OPEN", "ENTRIES_CLOSED"):
            raise_err(ERR_ENTRY_NOT_SCRATCHABLE, "entry is not scratchable now")
    elif entry["status"] == "SEEDED":
        if event["status"] != "SEEDED":
            raise_err(ERR_ENTRY_NOT_SCRATCHABLE, "entry is not scratchable now")
        lane = lane_for_entry(entry["id"])
        if lane is not None and lane["lane_status"] == "ACTIVE":
            lane["lane_status"] = "VOIDED"
            bump(lane)
    else:
        raise_err(ERR_ENTRY_NOT_SCRATCHABLE, "entry is not scratchable now")
    entry["status"] = "SCRATCHED"
    bump(entry)
    tid = entry_team_id(entry)
    if tid:
        recompute_active_entry_count(tid)
    return ok_object(pub_entry(entry))


@bp.post("/entries/<eid>/unscratch")
def unscratch_entry(eid):
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    entry = get_or_404("entries", eid, ERR_ENTRY_NOT_FOUND)
    _check_ownership(entry, user_id)
    event = STORE["events"][entry["event_id"]]
    meet = meet_of_event(event)
    if entry["status"] != "SCRATCHED":
        raise_err(ERR_ENTRY_NOT_UNSCRATCHABLE, "entry is not SCRATCHED")
    lane = lane_for_entry(entry["id"])
    if meet["status"] in ("ENTRIES_OPEN", "ENTRIES_CLOSED") and lane is None:
        entry["status"] = "ENTERED"
    elif (
        meet["status"] == "SEEDED"
        and event["status"] == "SEEDED"
        and lane is not None
        and lane["lane_status"] == "VOIDED"
    ):
        entry["status"] = "SEEDED"
        lane["lane_status"] = "ACTIVE"  # original heat_number/lane_number retained
        bump(lane)
    else:
        raise_err(ERR_ENTRY_NOT_UNSCRATCHABLE, "entry cannot be unscratches now")
    bump(entry)
    tid = entry_team_id(entry)
    if tid:
        recompute_active_entry_count(tid)
    return ok_object(pub_entry(entry))


@bp.post("/entries/<eid>/mark-no-show")
def mark_no_show(eid):
    _, role = ctx()
    require_role(role, "MeetReferee")
    entry = get_or_404("entries", eid, ERR_ENTRY_NOT_FOUND)
    event = STORE["events"][entry["event_id"]]
    if event["status"] != "IN_PROGRESS":
        raise_err(ERR_EVENT_NOT_IN_PROGRESS, "event is not IN_PROGRESS")
    if entry["status"] != "SEEDED":
        raise_err(ERR_EVENT_NOT_IN_PROGRESS, "entry is not SEEDED")
    lane = lane_for_entry(entry["id"])
    if lane is not None and lane["lane_status"] == "ACTIVE":
        lane["lane_status"] = "VOIDED"
        bump(lane)
    entry["status"] = "NO_SHOW"
    bump(entry)
    tid = entry_team_id(entry)
    if tid:
        recompute_active_entry_count(tid)
    return ok_object(pub_entry(entry))


@bp.get("/entries/<eid>/result")
def entry_result(eid):
    ctx()
    entry = get_or_404("entries", eid, ERR_ENTRY_NOT_FOUND)
    items = sort_created(
        [r for r in STORE["results"].values() if r["entry_id"] == entry["id"]]
    )
    return ok_list([pub_result(r) for r in items], 10, 0, len(items))
