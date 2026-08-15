"""Meet lifecycle endpoints."""

from flask import Blueprint

from db import CLOCK, STORE, new_id
from errors import (
    ERR_EVENTS_ALREADY_UNDERWAY,
    ERR_EVENTS_NOT_OFFICIAL,
    ERR_ENTRY_WINDOW_STILL_OPEN,
    ERR_INVALID_REQUEST,
    ERR_MEET_INVALID_STATE,
    ERR_MEET_NOT_FOUND,
    ERR_MEET_NOT_SEEDABLE,
    ERR_QUALIFICATION_UNDECIDED,
    ERR_RECORDS_PENDING,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_object
from services import (
    COURSES,
    TIE_POLICIES,
    cascade_meet_reopen,
    get_or_404,
    is_int,
    pub_meet,
    req_body,
    run_meet_seeding,
    stamp,
    touch,
    v_datetime,
    v_enum,
    v_enum_opt,
    v_int_list_opt,
    v_int_opt,
    v_str,
    v_date,
)

bp = Blueprint("meets", __name__)


@bp.post("/meets")
def create_meet():
    _, role = ctx()
    require_role(role, "MeetDirector")
    b = req_body()
    meet_name = v_str(b, "meet_name")
    course = v_enum(b, "course", COURSES)
    start_date = v_date(b, "start_date")
    dl_raw, dl_dt = v_datetime(b, "entry_deadline_utc")
    lane_count = v_int_opt(b, "lane_count", 6)
    if lane_count < 1:
        raise_err(ERR_INVALID_REQUEST, "lane_count must be at least 1")
    points_table = v_int_list_opt(b, "points_table", [9, 7, 6, 5, 4, 3, 2, 1])
    relay_mult = v_int_opt(b, "relay_points_multiplier", 2)
    max_ind = v_int_opt(b, "max_individual_entries_per_swimmer", 4)
    protest = v_int_opt(b, "dq_protest_window_minutes", 30)
    recovery = v_int_opt(b, "min_recovery_minutes", 20)
    threshold = v_int_opt(b, "timing_delta_threshold_cs", 30)
    tie = v_enum_opt(b, "scoring_tie_policy", TIE_POLICIES, "SPLIT")

    meet = stamp(
        {
            "id": new_id(),
            "meet_name": meet_name,
            "course": course,
            "start_date": start_date,
            "entry_deadline_utc": dl_raw,
            "_deadline_dt": dl_dt,
            "lane_count": lane_count,
            "points_table": points_table,
            "relay_points_multiplier": relay_mult,
            "max_individual_entries_per_swimmer": max_ind,
            "dq_protest_window_minutes": protest,
            "min_recovery_minutes": recovery,
            "timing_delta_threshold_cs": threshold,
            "scoring_tie_policy": tie,
            "status": "SETUP",
        }
    )
    STORE["meets"][meet["id"]] = meet
    return ok_object(pub_meet(meet), 201)


@bp.get("/meets/<mid>")
def get_meet(mid):
    ctx()
    meet = get_or_404("meets", mid, ERR_MEET_NOT_FOUND)
    return ok_object(pub_meet(meet))


@bp.post("/meets/<mid>/open-entries")
def open_entries(mid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    meet = get_or_404("meets", mid, ERR_MEET_NOT_FOUND)
    if meet["status"] != "SETUP":
        raise_err(ERR_MEET_INVALID_STATE, "open-entries requires meet status SETUP")
    meet["status"] = "ENTRIES_OPEN"
    meet["version"] += 1
    touch(meet)
    return ok_object(pub_meet(meet))


@bp.post("/meets/<mid>/close-entries")
def close_entries(mid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    meet = get_or_404("meets", mid, ERR_MEET_NOT_FOUND)
    if meet["status"] != "ENTRIES_OPEN":
        raise_err(ERR_MEET_INVALID_STATE, "close-entries requires meet status ENTRIES_OPEN")
    if not CLOCK["now"] > meet["_deadline_dt"]:
        raise_err(
            ERR_ENTRY_WINDOW_STILL_OPEN,
            "logical clock has not passed entry_deadline_utc",
        )
    meet["status"] = "ENTRIES_CLOSED"
    meet["version"] += 1
    touch(meet)
    return ok_object(pub_meet(meet))


@bp.post("/meets/<mid>/seed")
def seed_meet(mid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    meet = get_or_404("meets", mid, ERR_MEET_NOT_FOUND)
    b = req_body()
    if "expected_meet_version" not in b or not is_int(b["expected_meet_version"]):
        raise_err(ERR_INVALID_REQUEST, "expected_meet_version is required")
    # OCC runs before any state-machine guard.
    if b["expected_meet_version"] != meet["version"]:
        raise_err(ERR_STALE_VERSION, "expected_meet_version does not match current version")
    if meet["status"] != "ENTRIES_CLOSED":
        raise_err(ERR_MEET_NOT_SEEDABLE, "seed requires meet status ENTRIES_CLOSED")
    ev_ids = {e["id"] for e in STORE["events"].values() if e["meet_id"] == meet["id"]}
    for entry in STORE["entries"].values():
        if entry["event_id"] in ev_ids and entry["qualification_status"] == "UNVERIFIED":
            raise_err(
                ERR_QUALIFICATION_UNDECIDED,
                "every entry must be VERIFIED or REJECTED before seeding",
            )
    run_meet_seeding(meet)
    meet["status"] = "SEEDED"
    meet["version"] += 1
    touch(meet)
    return ok_object(pub_meet(meet))


@bp.post("/meets/<mid>/reopen-entries")
def reopen_entries(mid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    meet = get_or_404("meets", mid, ERR_MEET_NOT_FOUND)
    b = req_body()
    new_raw, new_dt = v_datetime(b, "new_entry_deadline_utc")
    if meet["status"] != "SEEDED":
        raise_err(ERR_MEET_INVALID_STATE, "reopen-entries requires meet status SEEDED")
    for ev in STORE["events"].values():
        if ev["meet_id"] == meet["id"] and ev["status"] in (
            "IN_PROGRESS",
            "COMPLETED",
            "OFFICIAL",
        ):
            raise_err(
                ERR_EVENTS_ALREADY_UNDERWAY,
                "an event of this meet is already underway",
            )
    cascade_meet_reopen(meet, new_raw, new_dt)
    meet["status"] = "ENTRIES_OPEN"
    meet["version"] += 1
    touch(meet)
    return ok_object(pub_meet(meet))


@bp.post("/meets/<mid>/complete")
def complete_meet(mid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    meet = get_or_404("meets", mid, ERR_MEET_NOT_FOUND)
    if meet["status"] != "SEEDED":
        raise_err(ERR_MEET_INVALID_STATE, "complete requires meet status SEEDED")
    for ev in STORE["events"].values():
        if ev["meet_id"] == meet["id"] and ev["status"] not in ("OFFICIAL", "CANCELLED"):
            raise_err(
                ERR_EVENTS_NOT_OFFICIAL,
                "every event must be OFFICIAL or CANCELLED to complete the meet",
            )
    meet["status"] = "COMPLETED"
    meet["version"] += 1
    touch(meet)
    return ok_object(pub_meet(meet))


@bp.post("/meets/<mid>/finalize")
def finalize_meet(mid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    meet = get_or_404("meets", mid, ERR_MEET_NOT_FOUND)
    if meet["status"] != "COMPLETED":
        raise_err(ERR_MEET_INVALID_STATE, "finalize requires meet status COMPLETED")
    ev_ids = {e["id"] for e in STORE["events"].values() if e["meet_id"] == meet["id"]}
    for rec in STORE["records"].values():
        if rec["event_id"] in ev_ids and rec["status"] in (
            "PENDING_VERIFICATION",
            "SUBMITTED",
        ):
            raise_err(ERR_RECORDS_PENDING, "records still pending for this meet")
    meet["status"] = "OFFICIAL"
    meet["version"] += 1
    touch(meet)
    return ok_object(pub_meet(meet))
