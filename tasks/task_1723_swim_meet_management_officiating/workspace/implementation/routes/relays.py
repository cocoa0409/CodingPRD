"""RelayTeam and RelayLeg endpoints."""

from flask import Blueprint, request

from db import CLOCK, STORE, new_id, iso3, wall_now
from errors import (
    ERR_AGE_GROUP_INELIGIBLE,
    ERR_ENTRY_DEADLINE_PASSED,
    ERR_EVENT_NOT_FOUND,
    ERR_GENDER_INELIGIBLE,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_MEET_NOT_ACCEPTING_ENTRIES,
    ERR_QUALIFICATION_UNDECIDED,
    ERR_RELAY_LEGS_LOCKED,
    ERR_RELAY_LEG_COUNT_INCOMPLETE,
    ERR_RELAY_LOCK_WINDOW_CLOSED,
    ERR_RELAY_NOT_SCRATCHABLE,
    ERR_RELAY_SWIMMER_DUPLICATE,
    ERR_RELAY_SWIMMER_TEAM_MISMATCH,
    ERR_RELAY_TEAM_NOT_FOUND,
    ERR_SWIMMER_NOT_FOUND,
    ERR_TEAM_NOT_ACTIVE,
    ERR_TEAM_NOT_FOUND,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    bump,
    get_or_404,
    lane_for_entry,
    meet_of_event,
    paginate,
    pub_leg,
    pub_relay,
    recompute_active_entry_count,
    req_body,
    sort_created,
    stamp,
    v_int,
    v_int_opt,
    v_str,
)

bp = Blueprint("relays", __name__)


def _check_relay_ownership(relay, user_id):
    if relay["team_id"] != user_id:
        raise_err(
            ERR_INSUFFICIENT_PERMISSIONS, "coach may only act on their own team's relays"
        )


@bp.post("/relay-teams")
def declare_relay():
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    b = req_body()
    team_id = v_str(b, "team_id")
    event_id = v_str(b, "event_id")
    relay_name = v_str(b, "relay_name")
    seed_time = v_int_opt(b, "seed_time_cs", None, nullable=True)
    if team_id != user_id:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "coach may only declare relays for their own team")
    team = get_or_404("teams", team_id, ERR_TEAM_NOT_FOUND)
    event = get_or_404("events", event_id, ERR_EVENT_NOT_FOUND)
    if not event["is_relay"]:
        raise_err(ERR_INVALID_REQUEST, "event is not a relay event")
    meet = meet_of_event(event)
    if meet["status"] != "ENTRIES_OPEN":
        raise_err(ERR_MEET_NOT_ACCEPTING_ENTRIES, "meet is not accepting entries")
    if CLOCK["now"] > meet["_deadline_dt"]:
        raise_err(ERR_ENTRY_DEADLINE_PASSED, "entry deadline has passed")
    if team["status"] != "REGISTERED":
        raise_err(ERR_TEAM_NOT_ACTIVE, "team is not active")
    for rt in STORE["relay_teams"].values():
        if (
            rt["team_id"] == team_id
            and rt["event_id"] == event_id
            and rt["relay_name"] == relay_name
        ):
            raise_err(
                ERR_INVALID_REQUEST, "relay_name must be unique per team within the event"
            )
    relay = stamp(
        {
            "id": new_id(),
            "team_id": team_id,
            "event_id": event_id,
            "relay_name": relay_name,
            "entry_id": None,
            "status": "DECLARED",
        }
    )
    STORE["relay_teams"][relay["id"]] = relay
    entry = stamp(
        {
            "id": new_id(),
            "event_id": event_id,
            "swimmer_id": None,
            "relay_team_id": relay["id"],
            "seed_time_cs": seed_time,
            "qualification_status": "UNVERIFIED",
            "status": "ENTERED",
        }
    )
    STORE["entries"][entry["id"]] = entry
    relay["entry_id"] = entry["id"]
    recompute_active_entry_count(team_id)
    return ok_object(pub_relay(relay), 201)


@bp.get("/relay-teams/<rid>")
def get_relay(rid):
    ctx()
    relay = get_or_404("relay_teams", rid, ERR_RELAY_TEAM_NOT_FOUND)
    return ok_object(pub_relay(relay))


@bp.get("/relay-teams")
def list_relays():
    ctx()
    items = list(STORE["relay_teams"].values())
    team_id = request.args.get("team_id")
    event_id = request.args.get("event_id")
    entry_id = request.args.get("entry_id")
    if team_id is not None:
        items = [r for r in items if r["team_id"] == team_id]
    if event_id is not None:
        items = [r for r in items if r["event_id"] == event_id]
    if entry_id is not None:
        items = [r for r in items if r["entry_id"] == entry_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_relay(r) for r in page], limit, offset, total)


@bp.post("/relay-teams/<rid>/legs")
def add_leg(rid):
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    relay = get_or_404("relay_teams", rid, ERR_RELAY_TEAM_NOT_FOUND)
    b = req_body()
    leg_number = v_int(b, "leg_number")
    swimmer_id = v_str(b, "swimmer_id")
    _check_relay_ownership(relay, user_id)
    if leg_number < 1 or leg_number > 4:
        raise_err(ERR_INVALID_REQUEST, "leg_number must be between 1 and 4")
    swimmer = get_or_404("swimmers", swimmer_id, ERR_SWIMMER_NOT_FOUND)
    if relay["status"] != "DECLARED":
        raise_err(ERR_RELAY_LEGS_LOCKED, "legs may only be managed while DECLARED")
    team = STORE["teams"][relay["team_id"]]
    if team["status"] != "REGISTERED":
        raise_err(ERR_TEAM_NOT_ACTIVE, "team is not active")
    event = STORE["events"][relay["event_id"]]
    if swimmer["age_group"] != event["age_group"]:
        raise_err(ERR_AGE_GROUP_INELIGIBLE, "swimmer age_group does not match the event")
    if event["gender"] != "MIXED" and swimmer["gender"] != event["gender"]:
        raise_err(ERR_GENDER_INELIGIBLE, "swimmer gender does not match the event")
    for leg in STORE["relay_legs"].values():
        if (
            leg["relay_team_id"] == relay["id"]
            and leg["swimmer_id"] == swimmer_id
            and leg["leg_number"] != leg_number
        ):
            raise_err(ERR_RELAY_SWIMMER_DUPLICATE, "swimmer already on another leg of this relay")
    if swimmer["team_id"] != relay["team_id"]:
        raise_err(ERR_RELAY_SWIMMER_TEAM_MISMATCH, "swimmer is not on the relay's team")
    existing = None
    for leg in STORE["relay_legs"].values():
        if leg["relay_team_id"] == relay["id"] and leg["leg_number"] == leg_number:
            existing = leg
            break
    if existing is not None:
        existing["swimmer_id"] = swimmer_id  # replace; RelayLeg has no updated_at/version
        return ok_object(pub_leg(existing), 201)
    leg = {
        "id": new_id(),
        "relay_team_id": relay["id"],
        "leg_number": leg_number,
        "swimmer_id": swimmer_id,
        "created_at": iso3(wall_now()),
    }
    STORE["relay_legs"][leg["id"]] = leg
    return ok_object(pub_leg(leg), 201)


@bp.get("/relay-teams/<rid>/legs")
def list_relay_legs(rid):
    ctx()
    relay = get_or_404("relay_teams", rid, ERR_RELAY_TEAM_NOT_FOUND)
    items = sort_created(
        [l for l in STORE["relay_legs"].values() if l["relay_team_id"] == relay["id"]]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub_leg(l) for l in page], limit, offset, total)


@bp.get("/relay-legs/<lid>")
def get_leg(lid):
    ctx()
    leg = STORE["relay_legs"].get(lid)
    if leg is None:
        raise_err(ERR_INVALID_REQUEST, "relay leg not found: %s" % lid)
    return ok_object(pub_leg(leg))


@bp.get("/relay-legs")
def list_legs():
    ctx()
    items = list(STORE["relay_legs"].values())
    swimmer_id = request.args.get("swimmer_id")
    relay_team_id = request.args.get("relay_team_id")
    if swimmer_id is not None:
        items = [l for l in items if l["swimmer_id"] == swimmer_id]
    if relay_team_id is not None:
        items = [l for l in items if l["relay_team_id"] == relay_team_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_leg(l) for l in page], limit, offset, total)


@bp.post("/relay-teams/<rid>/lock")
def lock_relay(rid):
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    relay = get_or_404("relay_teams", rid, ERR_RELAY_TEAM_NOT_FOUND)
    _check_relay_ownership(relay, user_id)
    if relay["status"] != "DECLARED":
        raise_err(ERR_RELAY_LEGS_LOCKED, "relay is not DECLARED")
    event = STORE["events"][relay["event_id"]]
    if event["status"] not in ("PENDING", "SEEDED"):
        raise_err(ERR_RELAY_LOCK_WINDOW_CLOSED, "the lock window has closed")
    legs = [l for l in STORE["relay_legs"].values() if l["relay_team_id"] == relay["id"]]
    if len(legs) != 4:
        raise_err(ERR_RELAY_LEG_COUNT_INCOMPLETE, "exactly 4 legs are required to lock")
    entry = STORE["entries"].get(relay["entry_id"])
    if entry is None or entry["qualification_status"] != "VERIFIED":
        raise_err(ERR_QUALIFICATION_UNDECIDED, "the relay's entry is not VERIFIED")
    relay["status"] = "LEGS_LOCKED"
    bump(relay)
    return ok_object(pub_relay(relay))


@bp.post("/relay-teams/<rid>/scratch")
def scratch_relay(rid):
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    relay = get_or_404("relay_teams", rid, ERR_RELAY_TEAM_NOT_FOUND)
    _check_relay_ownership(relay, user_id)
    event = STORE["events"][relay["event_id"]]
    if relay["status"] == "DECLARED":
        pass  # unconditional
    elif relay["status"] == "LEGS_LOCKED":
        if event["status"] not in ("PENDING", "SEEDED"):
            raise_err(ERR_RELAY_NOT_SCRATCHABLE, "relay is not scratchable once underway")
    else:
        raise_err(ERR_RELAY_NOT_SCRATCHABLE, "relay is already SCRATCHED")
    entry = STORE["entries"].get(relay["entry_id"])
    if entry is not None and entry["status"] in ("ENTERED", "SEEDED"):
        if entry["status"] == "SEEDED":
            lane = lane_for_entry(entry["id"])
            if lane is not None and lane["lane_status"] == "ACTIVE":
                lane["lane_status"] = "VOIDED"
                bump(lane)
        entry["status"] = "SCRATCHED"
        bump(entry)
    relay["status"] = "SCRATCHED"
    bump(relay)
    recompute_active_entry_count(relay["team_id"])
    return ok_object(pub_relay(relay))
