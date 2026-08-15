"""Workshops and registrations (incl. waitlist promotion and attendance)."""
from flask import Blueprint, request

from db import STORE, logical_now
from errors import ApiError
from helpers import (
    body,
    invalid,
    opt_datetime,
    opt_int,
    paginate,
    pagination_params,
    req_datetime,
    req_int,
    req_str,
)
from middleware import ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT, forbidden, require_roles
from response import ok
from services.domain import (
    NO_SHOW_LIMIT,
    coach_conflict,
    confirmed_count,
    new_common,
    participant_conflict,
    run_promotion,
    ser_registration,
    ser_workshop,
    session_line_cents,
    sort_by_creation,
    sweep_coach,
    touch,
)

bp = Blueprint("workshops", __name__)


def _load_workshop(wid):
    rec = STORE["workshops"].get(wid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Workshop not found.", 404)
    return rec


def _load_registration(rid):
    rec = STORE["registrations"].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Registration not found.", 404)
    return rec


# ---------------------------------------------------------------------------
# Workshops
# ---------------------------------------------------------------------------

@bp.post("/workshops")
def create_workshop():
    require_roles(ROLE_ADMIN)
    data = body()
    module_id = req_str(data, "module_id")
    coach_id = req_str(data, "coach_id")
    location = req_str(data, "location")
    start_at = req_datetime(data, "start_at")
    end_at = req_datetime(data, "end_at")
    if end_at <= start_at:
        invalid("Field 'end_at' must be strictly after 'start_at'.")
    capacity = req_int(data, "capacity", minimum=1)

    # Existence, left to right: module_id, then coach_id.
    module = STORE["modules"].get(module_id)
    if module is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced module_id does not resolve.", 404)
    coach = STORE["coaches"].get(coach_id)
    if coach is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced coach_id does not resolve.", 404)

    # Business guards in pinned order: certification, schedule, module state.
    sweep_coach(coach)
    if coach["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_COACH_NOT_CERTIFIED", "Workshop coach must be CERTIFIED.", 409
        )
    if coach_conflict(coach_id, start_at, end_at):
        raise ApiError(
            "ERR_COACH_SCHEDULE_CONFLICT",
            "Coach already has a SCHEDULED workshop overlapping this window.",
            409,
        )
    if module["status"] != "ACTIVE":
        raise ApiError(
            "ERR_MODULE_RETIRED", "Cannot schedule a workshop against a RETIRED module.", 409
        )

    rec = new_common()
    rec.update(
        {
            "module_id": module_id,
            "coach_id": coach_id,
            "location": location,
            "start_at": start_at,
            "end_at": end_at,
            "capacity": capacity,
            "status": "SCHEDULED",
        }
    )
    STORE["workshops"][rec["id"]] = rec
    return ok(ser_workshop(rec), 201)


@bp.get("/workshops")
def list_workshops():
    require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    limit, offset = pagination_params()
    items = list(STORE["workshops"].values())
    module_id = request.args.get("module_id")
    coach_id = request.args.get("coach_id")
    status = request.args.get("status")
    if module_id is not None:
        items = [w for w in items if w["module_id"] == module_id]
    if coach_id is not None:
        items = [w for w in items if w["coach_id"] == coach_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_by_creation(items)
    page, page_meta = paginate(items, limit, offset)
    return ok([ser_workshop(w) for w in page], 200, pagination=page_meta)


@bp.get("/workshops/<wid>")
def get_workshop(wid):
    require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    return ok(ser_workshop(_load_workshop(wid)), 200)


@bp.patch("/workshops/<wid>")
def patch_workshop(wid):
    require_roles(ROLE_ADMIN)
    data = body()
    if "expected_workshop_version" not in data:
        invalid("Field 'expected_workshop_version' is required.")
    expected = req_int(data, "expected_workshop_version")
    new_start = opt_datetime(data, "start_at")
    new_end = opt_datetime(data, "end_at")
    new_capacity = opt_int(data, "capacity", minimum=1)
    if new_start is not None and new_end is not None and new_end <= new_start:
        invalid("Field 'end_at' must be strictly after 'start_at'.")

    rec = _load_workshop(wid)
    eff_start = new_start if new_start is not None else rec["start_at"]
    eff_end = new_end if new_end is not None else rec["end_at"]
    if eff_end <= eff_start:
        invalid("Field 'end_at' must be strictly after 'start_at'.")

    # OCC runs before any state or business rule (PRD §2.7 tier 5).
    if expected != rec["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_workshop_version does not match the workshop's current version.",
            412,
        )
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SCHEDULED workshop can be rescheduled.", 409
        )
    if new_start is not None or new_end is not None:
        if coach_conflict(rec["coach_id"], eff_start, eff_end, exclude_id=rec["id"]):
            raise ApiError(
                "ERR_COACH_SCHEDULE_CONFLICT",
                "Coach already has a SCHEDULED workshop overlapping this window.",
                409,
            )
    if new_capacity is not None and new_capacity < confirmed_count(rec["id"]):
        raise ApiError(
            "ERR_CAPACITY_BELOW_CONFIRMED",
            "Capacity may not be lowered below the current confirmed_count.",
            409,
        )

    if new_start is not None:
        rec["start_at"] = new_start
    if new_end is not None:
        rec["end_at"] = new_end
    if new_capacity is not None:
        rec["capacity"] = new_capacity
    touch(rec)
    return ok(ser_workshop(rec), 200)


@bp.post("/workshops/<wid>/cancel")
def cancel_workshop(wid):
    require_roles(ROLE_ADMIN)
    rec = _load_workshop(wid)
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SCHEDULED workshop can be cancelled.", 409
        )
    rec["status"] = "CANCELLED"
    touch(rec)
    for r in STORE["registrations"].values():
        if r["workshop_id"] == wid and r["status"] in ("REGISTERED", "WAITLISTED"):
            r["status"] = "CANCELLED"
            touch(r)
    # No waitlist promotion runs: the workshop itself is gone.
    return ok(ser_workshop(rec), 200)


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

@bp.post("/registrations")
def create_registration():
    uid, role = require_roles(ROLE_ADMIN, ROLE_PARTICIPANT)
    data = body()
    if role == ROLE_PARTICIPANT:
        pid = data.get("participant_id")
        if pid is not None and pid != uid:
            forbidden("A participant may register only themselves.")
    workshop_id = req_str(data, "workshop_id")
    participant_id = req_str(data, "participant_id")
    if role == ROLE_PARTICIPANT and participant_id != uid:
        forbidden("A participant may register only themselves.")

    workshop = STORE["workshops"].get(workshop_id)
    if workshop is None:
        raise ApiError("ERR_NOT_FOUND", "Referenced workshop_id does not resolve.", 404)
    participant = STORE["participants"].get(participant_id)
    if participant is None:
        raise ApiError(
            "ERR_NOT_FOUND", "Referenced participant_id does not resolve.", 404
        )

    if workshop["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", "Registrations require a SCHEDULED workshop.", 409
        )
    if logical_now() >= workshop["start_at"]:
        raise ApiError(
            "ERR_WORKSHOP_STARTED",
            "Registration is closed at or after the workshop start.",
            409,
        )
    if participant_conflict(
        participant_id, workshop["start_at"], workshop["end_at"]
    ):
        raise ApiError(
            "ERR_PARTICIPANT_SCHEDULE_CONFLICT",
            "Participant holds a REGISTERED registration within the buffered window.",
            409,
        )
    if any(
        r["workshop_id"] == workshop_id
        and r["participant_id"] == participant_id
        and r["status"] in ("REGISTERED", "WAITLISTED")
        for r in STORE["registrations"].values()
    ):
        raise ApiError(
            "ERR_ALREADY_REGISTERED",
            "Participant already holds a REGISTERED or WAITLISTED entry on this workshop.",
            409,
        )
    if participant["status"] == "RESTRICTED":
        raise ApiError(
            "ERR_PARTICIPANT_RESTRICTED",
            "RESTRICTED participants may not register.",
            409,
        )

    rec = new_common()
    rec.update(
        {
            "workshop_id": workshop_id,
            "participant_id": participant_id,
            "incentive_earned_cents": 0,
        }
    )
    if confirmed_count(workshop_id) < workshop["capacity"]:
        rec["status"] = "REGISTERED"
        rec["waitlist_position"] = None
    else:
        rec["status"] = "WAITLISTED"
        positions = [
            r["waitlist_position"]
            for r in STORE["registrations"].values()
            if r["workshop_id"] == workshop_id
            and r["status"] == "WAITLISTED"
            and r["waitlist_position"] is not None
        ]
        rec["waitlist_position"] = (max(positions) if positions else 0) + 1
    STORE["registrations"][rec["id"]] = rec
    return ok(ser_registration(rec), 201)


def _participant_scoped_list(items, uid, role, fk_field="participant_id"):
    """Participant role may only ever see own records; an explicit mismatched
    filter is an ownership failure (403), otherwise scope silently."""
    if role != ROLE_PARTICIPANT:
        return items
    supplied = request.args.get(fk_field)
    if supplied is not None and supplied != uid:
        forbidden("Participants may read only their own records.")
    return [r for r in items if r.get(fk_field) == uid]


@bp.get("/registrations")
def list_registrations():
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    limit, offset = pagination_params()
    items = _participant_scoped_list(list(STORE["registrations"].values()), uid, role)
    workshop_id = request.args.get("workshop_id")
    status = request.args.get("status")
    participant_id = request.args.get("participant_id")
    if workshop_id is not None:
        items = [r for r in items if r["workshop_id"] == workshop_id]
    if participant_id is not None:
        items = [r for r in items if r["participant_id"] == participant_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_creation(items)
    page, page_meta = paginate(items, limit, offset)
    return ok([ser_registration(r) for r in page], 200, pagination=page_meta)


@bp.get("/registrations/<rid>")
def get_registration(rid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT)
    rec = STORE["registrations"].get(rid)
    if role == ROLE_PARTICIPANT and rec is not None and rec["participant_id"] != uid:
        forbidden("Participants may read only their own registrations.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Registration not found.", 404)
    return ok(ser_registration(rec), 200)


@bp.post("/registrations/<rid>/cancel")
def cancel_registration(rid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_PARTICIPANT)
    rec = STORE["registrations"].get(rid)
    if role == ROLE_PARTICIPANT and rec is not None and rec["participant_id"] != uid:
        forbidden("Participants may cancel only their own registrations.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Registration not found.", 404)
    if rec["status"] not in ("REGISTERED", "WAITLISTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a REGISTERED or WAITLISTED registration can be cancelled.",
            409,
        )
    was_registered = rec["status"] == "REGISTERED"
    rec["status"] = "CANCELLED"
    touch(rec)
    if was_registered:
        workshop = STORE["workshops"].get(rec["workshop_id"])
        if workshop is not None:
            run_promotion(workshop)
    return ok(ser_registration(rec), 200)


@bp.post("/registrations/<rid>/mark-attendance")
def mark_attendance(rid):
    uid, role = require_roles(ROLE_ADMIN, ROLE_COACH)
    rec = STORE["registrations"].get(rid)
    workshop = STORE["workshops"].get(rec["workshop_id"]) if rec is not None else None
    if role == ROLE_COACH and workshop is not None and workshop["coach_id"] != uid:
        forbidden("A coach may mark attendance only on their own workshops.")
    data = body()
    outcome = req_str(data, "outcome")
    if outcome not in ("ATTENDED", "NO_SHOW"):
        invalid("Field 'outcome' must be ATTENDED or NO_SHOW.")
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Registration not found.", 404)
    if rec["status"] != "REGISTERED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Attendance can be marked only on a REGISTERED registration.",
            409,
        )
    if workshop["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Attendance can be marked only on a SCHEDULED workshop.",
            409,
        )
    if logical_now() < workshop["start_at"]:
        raise ApiError(
            "ERR_WORKSHOP_NOT_STARTED",
            "Attendance may be marked once the workshop has started.",
            409,
        )

    if outcome == "ATTENDED":
        module = STORE["modules"].get(workshop["module_id"])
        rec["incentive_earned_cents"] = session_line_cents(module, workshop)
        rec["status"] = "ATTENDED"
    else:
        rec["status"] = "NO_SHOW"
        participant = STORE["participants"].get(rec["participant_id"])
        if participant is not None:
            participant["no_show_count"] += 1
            if (
                participant["no_show_count"] >= NO_SHOW_LIMIT
                and participant["status"] == "ACTIVE"
            ):
                participant["status"] = "RESTRICTED"
            touch(participant)
    touch(rec)
    return ok(ser_registration(rec), 200)
