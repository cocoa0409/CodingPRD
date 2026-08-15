"""SwimEvent endpoints, heat sheet, nested collections, assignment proposal, records creation."""

from flask import Blueprint, request

from db import STORE, new_id
from errors import (
    ERR_CERTIFICATION_INVALID,
    ERR_DQ_NOT_TERMINAL,
    ERR_EVENT_NOT_COMPLETED,
    ERR_EVENT_NOT_FOUND,
    ERR_EVENT_NOT_IN_PROGRESS,
    ERR_EVENT_NOT_SEEDED,
    ERR_INVALID_REQUEST,
    ERR_MEET_NOT_FOUND,
    ERR_MEET_NOT_SEEDED,
    ERR_OFFICIAL_COVERAGE_INCOMPLETE,
    ERR_OFFICIAL_NOT_FOUND,
    ERR_OFFICIAL_ASSIGNMENT_CONFLICT,
    ERR_RECORD_STANDING_EXISTS,
    ERR_STALE_VERSION,
    ERR_UNRESOLVED_LANES_EXIST,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    AGE_GROUPS,
    DECK_ROLES,
    EVENT_GENDERS,
    NON_TERMINAL_DQ_STATUSES,
    STROKES,
    entry_team_id,
    get_or_404,
    is_int,
    meet_of_event,
    paginate,
    pub_assignment,
    pub_event,
    pub_lane,
    pub_record,
    pub_result,
    recompute_team_points,
    record_challenge_check,
    req_body,
    score_event_completion,
    sort_created,
    stamp,
    bump,
    touch,
    v_bool,
    v_date,
    v_enum,
    v_int,
    v_int_opt,
    v_str,
    windows_overlap,
)

bp = Blueprint("events", __name__)


@bp.post("/events")
def create_event():
    _, role = ctx()
    require_role(role, "MeetDirector")
    b = req_body()
    meet_id = v_str(b, "meet_id")
    event_number = v_int(b, "event_number")
    gender = v_enum(b, "gender", EVENT_GENDERS)
    age_group = v_enum(b, "age_group", AGE_GROUPS)
    stroke = v_enum(b, "stroke", STROKES)
    distance = v_int(b, "distance_meters")
    is_relay = v_bool(b, "is_relay")
    qualifying = v_int_opt(b, "qualifying_time_cs", None, nullable=True)
    session_date = v_date(b, "session_date")
    start_min = v_int(b, "scheduled_start_minute")
    end_min = v_int(b, "scheduled_end_minute")
    get_or_404("meets", meet_id, ERR_MEET_NOT_FOUND)
    if end_min <= start_min:
        raise_err(
            ERR_INVALID_REQUEST, "scheduled_end_minute must be greater than scheduled_start_minute"
        )
    for ev in STORE["events"].values():
        if ev["meet_id"] == meet_id and ev["event_number"] == event_number:
            raise_err(ERR_INVALID_REQUEST, "event_number must be unique within the meet")
    event = stamp(
        {
            "id": new_id(),
            "meet_id": meet_id,
            "event_number": event_number,
            "gender": gender,
            "age_group": age_group,
            "stroke": stroke,
            "distance_meters": distance,
            "is_relay": is_relay,
            "qualifying_time_cs": qualifying,
            "session_date": session_date,
            "scheduled_start_minute": start_min,
            "scheduled_end_minute": end_min,
            "status": "PENDING",
        }
    )
    STORE["events"][event["id"]] = event
    return ok_object(pub_event(event), 201)


@bp.get("/events/<eid>")
def get_event(eid):
    ctx()
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    return ok_object(pub_event(event))


@bp.get("/events")
def list_events():
    ctx()
    items = list(STORE["events"].values())
    meet_id = request.args.get("meet_id")
    if meet_id is not None:
        items = [e for e in items if e["meet_id"] == meet_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_event(e) for e in page], limit, offset, total)


@bp.post("/events/<eid>/start")
def start_event(eid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    meet = meet_of_event(event)
    if meet["status"] != "SEEDED":
        raise_err(ERR_MEET_NOT_SEEDED, "event start requires meet status SEEDED")
    if event["status"] != "SEEDED":
        raise_err(ERR_EVENT_NOT_SEEDED, "event start requires event status SEEDED")
    has_ref = False
    has_stj = False
    for a in STORE["official_assignments"].values():
        if a["event_id"] != event["id"] or a["status"] != "CONFIRMED":
            continue
        if a["role_on_deck"] == "REFEREE":
            has_ref = True
        elif a["role_on_deck"] == "STROKE_TURN_JUDGE":
            has_stj = True
    if not (has_ref and has_stj):
        raise_err(
            ERR_OFFICIAL_COVERAGE_INCOMPLETE,
            "event requires a CONFIRMED REFEREE and a CONFIRMED STROKE_TURN_JUDGE",
        )
    event["status"] = "IN_PROGRESS"
    event["version"] += 1
    touch(event)
    return ok_object(pub_event(event))


@bp.post("/events/<eid>/complete")
def complete_event(eid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    b = req_body()
    if "expected_event_version" not in b or not is_int(b["expected_event_version"]):
        raise_err(ERR_INVALID_REQUEST, "expected_event_version is required")
    # OCC runs before any state-machine guard.
    if b["expected_event_version"] != event["version"]:
        raise_err(ERR_STALE_VERSION, "expected_event_version does not match current version")
    if event["status"] != "IN_PROGRESS":
        raise_err(ERR_EVENT_NOT_IN_PROGRESS, "complete requires event status IN_PROGRESS")
    for lane in STORE["lane_assignments"].values():
        if lane["event_id"] != event["id"] or lane["lane_status"] != "ACTIVE":
            continue
        if lane["reconciliation_status"] not in ("AUTO_CONFIRMED", "RESOLVED"):
            raise_err(
                ERR_UNRESOLVED_LANES_EXIST,
                "every ACTIVE lane must be AUTO_CONFIRMED or RESOLVED",
            )
    score_event_completion(event)
    event["status"] = "COMPLETED"
    event["version"] += 1
    touch(event)
    return ok_object(pub_event(event))


@bp.post("/events/<eid>/reopen")
def reopen_event(eid):
    _, role = ctx()
    require_role(role, "MeetReferee")
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    if event["status"] != "COMPLETED":
        raise_err(ERR_EVENT_NOT_COMPLETED, "reopen requires event status COMPLETED")
    affected_teams = {
        r["team_id"]
        for r in STORE["results"].values()
        if r["event_id"] == event["id"]
    }
    doomed = [rid for rid, r in STORE["results"].items() if r["event_id"] == event["id"]]
    for rid in doomed:
        del STORE["results"][rid]
    for en in STORE["entries"].values():
        if en["event_id"] == event["id"] and en["status"] == "FINISHED":
            en["status"] = "SEEDED"
            bump(en)
    for tid in affected_teams:
        if tid:
            recompute_team_points(tid)
    event["status"] = "IN_PROGRESS"
    event["version"] += 1
    touch(event)
    return ok_object(pub_event(event))


@bp.post("/events/<eid>/publish")
def publish_event(eid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    if event["status"] != "COMPLETED":
        raise_err(ERR_EVENT_NOT_COMPLETED, "publish requires event status COMPLETED")
    lane_ids = {
        l["id"] for l in STORE["lane_assignments"].values() if l["event_id"] == event["id"]
    }
    for dq in STORE["disqualifications"].values():
        if dq["lane_assignment_id"] in lane_ids and dq["status"] in NON_TERMINAL_DQ_STATUSES:
            raise_err(ERR_DQ_NOT_TERMINAL, "a disqualification on this event is not terminal")
    affected_teams = set()
    for r in STORE["results"].values():
        if r["event_id"] == event["id"] and r["status"] == "UNOFFICIAL":
            r["status"] = "OFFICIAL"
            bump(r)
            if r["team_id"]:
                affected_teams.add(r["team_id"])
        elif r["event_id"] == event["id"] and r["status"] == "OFFICIAL":
            if r["team_id"]:
                affected_teams.add(r["team_id"])
    for tid in affected_teams:
        recompute_team_points(tid)
    record_challenge_check(event)
    event["status"] = "OFFICIAL"
    event["version"] += 1
    touch(event)
    return ok_object(pub_event(event))


@bp.get("/events/<eid>/heat-sheet")
def heat_sheet(eid):
    ctx()
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    lanes = [
        l
        for l in STORE["lane_assignments"].values()
        if l["event_id"] == event["id"] and l["lane_status"] == "ACTIVE"
    ]
    heats = {}
    for l in lanes:
        heats.setdefault(l["heat_number"], []).append(l)
    heat_list = []
    for heat_number in sorted(heats):
        heat_list.append(
            {
                "heat_number": heat_number,
                "lanes": [
                    pub_lane(l)
                    for l in sorted(heats[heat_number], key=lambda x: x["lane_number"])
                ],
            }
        )
    return ok_object({"event_id": event["id"], "heats": heat_list})


@bp.get("/events/<eid>/results")
def event_results(eid):
    ctx()
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    items = sort_created(
        [r for r in STORE["results"].values() if r["event_id"] == event["id"]]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub_result(r) for r in page], limit, offset, total)


@bp.get("/events/<eid>/official-assignments")
def event_assignments(eid):
    ctx()
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    items = sort_created(
        [
            a
            for a in STORE["official_assignments"].values()
            if a["event_id"] == event["id"]
        ]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub_assignment(a) for a in page], limit, offset, total)


@bp.get("/events/<eid>/records")
def event_records(eid):
    ctx()
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    items = sort_created(
        [r for r in STORE["records"].values() if r["event_id"] == event["id"]]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub_record(r) for r in page], limit, offset, total)


def _assignment_conflict(official_id, event, statuses, exclude_id=None):
    """Half-open overlap vs the official's other assignments on the same session_date."""
    for a in STORE["official_assignments"].values():
        if a["official_id"] != official_id or a["id"] == exclude_id:
            continue
        if a["status"] not in statuses:
            continue
        other = STORE["events"].get(a["event_id"])
        if other is None or other["session_date"] != event["session_date"]:
            continue
        if windows_overlap(
            event["scheduled_start_minute"],
            event["scheduled_end_minute"],
            other["scheduled_start_minute"],
            other["scheduled_end_minute"],
        ):
            return True
    return False


@bp.post("/events/<eid>/official-assignments")
def propose_assignment(eid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    b = req_body()
    official_id = v_str(b, "official_id")
    role_on_deck = v_enum(b, "role_on_deck", DECK_ROLES)
    official = get_or_404("officials", official_id, ERR_OFFICIAL_NOT_FOUND)
    # Certification: role covered AND expiry on/after the event's session_date (equality valid).
    if role_on_deck not in official["certifications"] or (
        official["certification_expires_on"] < event["session_date"]
    ):
        raise_err(
            ERR_CERTIFICATION_INVALID,
            "official lacks the role certification or it expires before the session",
        )
    if _assignment_conflict(official_id, event, ("PROPOSED", "CONFIRMED")):
        raise_err(
            ERR_OFFICIAL_ASSIGNMENT_CONFLICT,
            "official has an overlapping assignment on this session_date",
        )
    assignment = stamp(
        {
            "id": new_id(),
            "event_id": event["id"],
            "official_id": official_id,
            "role_on_deck": role_on_deck,
            "status": "PROPOSED",
        }
    )
    STORE["official_assignments"][assignment["id"]] = assignment
    return ok_object(pub_assignment(assignment), 201)


@bp.post("/events/<eid>/records")
def create_standing_record(eid):
    _, role = ctx()
    require_role(role, "RecordsOfficer")
    event = get_or_404("events", eid, ERR_EVENT_NOT_FOUND)
    b = req_body()
    record_time_cs = v_int(b, "record_time_cs")
    holder_name = v_str(b, "holder_name")
    holder_team = v_str(b, "holder_team")
    set_on_date = v_date(b, "set_on_date")
    for rec in STORE["records"].values():
        if rec["event_id"] == event["id"] and rec["status"] == "CURRENT":
            raise_err(
                ERR_RECORD_STANDING_EXISTS,
                "a CURRENT record already exists for this event",
            )
    rec = stamp(
        {
            "id": new_id(),
            "event_id": event["id"],
            "record_time_cs": record_time_cs,
            "holder_name": holder_name,
            "holder_team": holder_team,
            "set_on_date": set_on_date,
            "challenger_entry_id": None,
            "status": "CURRENT",
        }
    )
    STORE["records"][rec["id"]] = rec
    return ok_object(pub_record(rec), 201)
