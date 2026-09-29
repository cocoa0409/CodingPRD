"""Session and session-slot endpoints."""

from flask import Blueprint

from db import db, new_row, parse_dt, touch
from errors import fail
from middleware import (ROLE_ADMIN, ROLE_AUTHOR, ROLE_CHAIR, ROLE_PRESS,
                        ROLE_REVIEWER, endpoint)
from response import created, ok, ok_list
from routes.helpers import check_occ, filtered, lookup, resolve_fk
from services import calc, derive, logic
from validators import (body_json, paginate, present, q_str, v_bool, v_datetime,
                        v_enum, v_int, v_string)

bp = Blueprint("sessions", __name__)

SESSION_STATUSES = ("PLANNED", "PUBLISHED", "LOCKED", "CANCELLED")
SLOT_STATUSES = ("SCHEDULED", "PRESENTED", "NO_SHOW_RECORDED", "WITHDRAWN", "MOVED")
FORMATS = ("ORAL", "POSTER", "WORKSHOP")


@bp.post("/sessions")
@endpoint(ROLE_CHAIR)
def create_session(actor):
    body = body_json()
    conference = resolve_fk(body, "conference_id")
    chair = resolve_fk(body, "chair_member_id")

    theme_code = v_string(body, "theme_code", required=True, min_len=2, max_len=16)
    fmt = v_enum(body, "format", FORMATS, required=True)
    room_code = v_string(body, "room_code", required=True, min_len=1, max_len=16)
    start_utc = v_datetime(body, "start_utc", required=True)
    end_utc = v_datetime(body, "end_utc", required=True)
    capacity_slots = v_int(body, "capacity_slots", minimum=1, maximum=20, default=6)
    cme_designated = v_bool(body, "cme_designated", default=False)
    if conference is None:
        fail("ERR_VALIDATION", "conference_id is required.")
    if chair is None:
        fail("ERR_VALIDATION", "chair_member_id is required.")

    # Band 9.
    if conference["status"] not in ("REVIEW_CLOSED", "DECISIONS_RELEASED"):
        fail("ERR_CONFERENCE_STATE_INVALID",
             "Sessions are planned once review has closed.")
    # Band 10.
    if (chair["member_role"] != "CHAIR" or chair["status"] != "ACTIVE"
            or chair["conference_id"] != conference["id"]):
        fail("ERR_MEMBER_STATE_INVALID")
    # Band 15.
    start, end = parse_dt(start_utc), parse_dt(end_utc)
    if not (end > start):
        fail("ERR_INVALID_DATE_RANGE", "end_utc must be after start_utc.")
    if start < parse_dt(conference["event_start_utc"]):
        fail("ERR_INVALID_DATE_RANGE", "start_utc must fall inside the conference window.")
    if end > parse_dt(conference["event_end_utc"]):
        fail("ERR_INVALID_DATE_RANGE", "end_utc must fall inside the conference window.")
    # Band 18 — room first, then chair.
    if logic.room_conflict(conference["id"], room_code, start, end) is not None:
        fail("ERR_ROOM_TIME_CONFLICT")
    if logic.chair_conflict(chair["id"], start, end) is not None:
        fail("ERR_CHAIR_TIME_CONFLICT")

    row = new_row({
        "conference_id": conference["id"],
        "chair_member_id": chair["id"],
        "theme_code": theme_code,
        "format": fmt,
        "room_code": room_code,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "capacity_slots": capacity_slots,
        "cme_designated": bool(cme_designated),
        "status": "PLANNED",
    })
    db.sessions[row["id"]] = row
    logic.bump_member(chair)
    return created(derive.session_out(row))


@bp.get("/sessions")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def list_sessions(actor):
    rows = filtered(db.sessions.values(), {
        "conference_id": q_str("conference_id"),
        "chair_member_id": q_str("chair_member_id"),
        "status": q_str("status"),
        "format": q_str("format"),
        "theme_code": q_str("theme_code"),
        "room_code": q_str("room_code"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.session_out(r) for r in page], meta)


@bp.get("/sessions/<session_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def get_session(actor, session_id):
    row = lookup("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    return ok(derive.session_out(row))


@bp.post("/sessions/<session_id>/status-transitions")
@endpoint(ROLE_CHAIR, ROLE_ADMIN)
def session_status_transition(actor, session_id):
    session = lookup("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    conference = db.conferences.get(session["conference_id"])
    body = body_json()
    to_status = v_enum(body, "to_status", SESSION_STATUSES, required=True)
    if present(body, "reason"):
        v_string(body, "reason", min_len=1)
    current = session["status"]

    if to_status == "PUBLISHED":
        if current != "PLANNED":
            fail("ERR_SESSION_STATE_INVALID")
        if conference["status"] != "DECISIONS_RELEASED":
            fail("ERR_CONFERENCE_STATE_INVALID",
                 "Sessions are published once decisions are released.")
        slots = derive.counted_slots(session_id)
        if len(slots) < 1:
            fail("ERR_EMPTY_SESSION")
        for slot in slots:
            abstract = db.abstracts.get(slot["abstract_id"])
            if abstract is None or abstract["status"] != "SCHEDULED":
                fail("ERR_ABSTRACT_STATE_INVALID",
                     "Every slotted abstract must be SCHEDULED before publication.")
        if derive.session_posture(session) == "NON_COMPLIANT":
            fail("ERR_SESSION_NOT_ACCREDITED")
        session["status"] = "PUBLISHED"
        touch(session)

    elif to_status == "PLANNED":
        if current != "PUBLISHED":
            fail("ERR_SESSION_STATE_INVALID")
        if not (db.now() < parse_dt(conference["program_freeze_utc"])):
            fail("ERR_PROGRAM_FROZEN")
        session["status"] = "PLANNED"
        touch(session)

    elif to_status == "CANCELLED":
        if current not in ("PLANNED", "PUBLISHED"):
            fail("ERR_SESSION_STATE_INVALID")
        if not (db.now() < parse_dt(conference["program_freeze_utc"])):
            fail("ERR_PROGRAM_FROZEN")
        session["status"] = "CANCELLED"
        touch(session)
        for slot in derive.session_slots(session_id):
            if slot["status"] != "SCHEDULED":
                continue
            slot["status"] = "WITHDRAWN"
            touch(slot)
            abstract = db.abstracts.get(slot["abstract_id"])
            if abstract is not None and abstract["status"] == "SCHEDULED":
                abstract["status"] = "CONFIRMED"
                touch(abstract)
        logic.bump_member(db.members.get(session["chair_member_id"]))

    else:
        fail("ERR_SESSION_STATE_INVALID",
             "Session cannot move from %s to %s." % (current, to_status))

    return ok(derive.session_out(session))


# ---------------------------------------------------------------------------
# slot creation — session packing
# ---------------------------------------------------------------------------

@bp.post("/sessions/<session_id>/slots")
@endpoint(ROLE_CHAIR)
def create_slot(actor, session_id):
    session = lookup("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    conference = db.conferences.get(session["conference_id"])
    body = body_json()
    abstract = resolve_fk(body, "abstract_id")
    presenter = resolve_fk(body, "presenter_author_id")

    position = v_int(body, "position", required=True, minimum=1, maximum=20)
    duration = v_int(body, "duration_minutes", required=True, minimum=5, maximum=120)
    if abstract is None:
        fail("ERR_VALIDATION", "abstract_id is required.")
    if presenter is None:
        fail("ERR_VALIDATION", "presenter_author_id is required.")
    # Band 8 — optimistic concurrency on the session ledger.
    check_occ(body, "expected_session_version", session["version"],
              "ERR_STALE_SESSION_VERSION")

    # Band 10.
    if session["status"] != "PLANNED":
        fail("ERR_SESSION_STATE_INVALID", "Slots are added while the session is PLANNED.")
    if abstract["status"] != "CONFIRMED":
        fail("ERR_ABSTRACT_STATE_INVALID", "Only a CONFIRMED abstract can be slotted.")
    # Band 12.
    if derive.is_barred(presenter):
        fail("ERR_AUTHOR_BARRED")
    # Band 14.
    if abstract["decision"] != session["format"]:
        fail("ERR_SESSION_FORMAT_MISMATCH")
    if session["theme_code"] not in abstract["keywords"]:
        fail("ERR_SESSION_THEME_MISMATCH")
    if presenter["email"] not in derive.author_emails(abstract):
        fail("ERR_PRESENTER_NOT_ON_ABSTRACT")
    # Band 15.
    if not (db.now() < parse_dt(conference["program_freeze_utc"])):
        fail("ERR_PROGRAM_FROZEN")
    # Band 18.
    if logic.presenter_conflict(presenter["id"], session) is not None:
        fail("ERR_PRESENTER_TIME_CONFLICT")
    # Band 19 — capacity, then duplicate position, then duration packing.
    counted = derive.counted_slots(session_id)
    if len(counted) >= session["capacity_slots"]:
        fail("ERR_SESSION_SLOT_CAPACITY_REACHED")
    if any(slot["position"] == position for slot in counted):
        fail("ERR_DUPLICATE_SLOT_POSITION")
    durations = [slot["duration_minutes"] for slot in counted]
    if not calc.packing_admissible(durations, duration,
                                   derive.session_window_minutes(session)):
        fail("ERR_SESSION_DURATION_EXCEEDED")

    row = new_row({
        "session_id": session["id"],
        "abstract_id": abstract["id"],
        "presenter_author_id": presenter["id"],
        "swapped_with_slot_id": None,
        "position": position,
        "duration_minutes": duration,
        "status": "SCHEDULED",
    })
    db.slots[row["id"]] = row
    abstract["status"] = "SCHEDULED"
    touch(abstract)
    touch(session)
    return created(derive.slot_out(row))


# ---------------------------------------------------------------------------
# session slots
# ---------------------------------------------------------------------------

slots_bp = Blueprint("slots", __name__)


@slots_bp.get("/session-slots")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def list_slots(actor):
    rows = filtered(db.slots.values(), {
        "session_id": q_str("session_id"),
        "abstract_id": q_str("abstract_id"),
        "presenter_author_id": q_str("presenter_author_id"),
        "swapped_with_slot_id": q_str("swapped_with_slot_id"),
        "status": q_str("status"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.slot_out(r) for r in page], meta)


@slots_bp.get("/session-slots/<slot_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def get_slot(actor, slot_id):
    row = lookup("slots", slot_id, "ERR_SLOT_NOT_FOUND")
    return ok(derive.slot_out(row))


@slots_bp.post("/session-slots/<slot_id>/status-transitions")
@endpoint(ROLE_CHAIR, ROLE_ADMIN)
def slot_status_transition(actor, slot_id):
    slot = lookup("slots", slot_id, "ERR_SLOT_NOT_FOUND")
    session = db.sessions.get(slot["session_id"])
    abstract = db.abstracts.get(slot["abstract_id"])
    body = body_json()
    to_status = v_enum(body, "to_status", SLOT_STATUSES, required=True)
    if present(body, "reason"):
        v_string(body, "reason", min_len=1)

    if to_status not in ("PRESENTED", "NO_SHOW_RECORDED"):
        fail("ERR_SLOT_STATE_INVALID",
             "Slot cannot move from %s to %s." % (slot["status"], to_status))
    if slot["status"] != "SCHEDULED":
        fail("ERR_SLOT_STATE_INVALID")
    if session is None or session["status"] not in ("PUBLISHED", "LOCKED"):
        fail("ERR_SESSION_STATE_INVALID",
             "On-site outcomes require a published or locked session.")

    now = db.now()
    if to_status == "PRESENTED":
        if now < parse_dt(session["start_utc"]):
            fail("ERR_SLOT_STATE_INVALID", "The session has not started yet.")
        slot["status"] = "PRESENTED"
        touch(slot)
        if abstract is not None:
            abstract["status"] = "PRESENTED"
            touch(abstract)
    else:
        if now < parse_dt(session["end_utc"]):
            fail("ERR_SLOT_STATE_INVALID", "The session has not ended yet.")
        logic.record_no_show(slot, abstract)

    return ok(derive.slot_out(slot))
