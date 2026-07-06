"""Registration endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import db, new_record, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_STALE_SESSION_VERSION,
    ERR_AGE_INELIGIBLE,
    ERR_VALIDATION,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_int,
    parse_pagination,
    paginate,
)
from services.lookups import get_program, get_membership, get_registration
from services.serialize import registration_view
from services.calculations import program_tuition_pricing
from services.program_logic import (
    recompute_enrolled_count,
    recompute_waitlist_positions,
    waitlisted_registrations,
)

bp = Blueprint("registrations", __name__)


@bp.route("/registrations", methods=["POST"])
def create_registration():
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    body = get_body()
    require_string(body, "program_session_id")
    session_id = body["program_session_id"]
    participant_name = require_string(body, "participant_name")
    participant_age = require_int(body, "participant_age")
    expected_session_version = require_int(body, "expected_session_version")
    membership_id = body.get("membership_id")

    with db.lock:
        # Existence (priority 3).
        program = get_program(session_id)
        membership = None
        if membership_id is not None:
            membership = get_membership(membership_id)

        # State (priority 5): registration is only defined while the session is
        # ENROLLING or FULL (the two states the WAITLISTED/ENROLLED transitions
        # reference). STARTED/CANCELLED are terminal — no registration target.
        if program["status"] not in ("ENROLLING", "FULL"):
            raise err(ERR_INVALID_STATE, "Session is not open for registration")

        # OCC stale-version (priority 6).
        if expected_session_version != program["version"]:
            raise err(ERR_STALE_SESSION_VERSION, "Session version is stale")

        # Age eligibility (priority 8) — checked before the generic field-range
        # (priority 20) per PRD §3.10.
        if not (program["min_age"] <= participant_age <= program["max_age"]):
            raise err(ERR_AGE_INELIGIBLE, "Participant age outside the session band")

        # Field-range (participant_age >= 0) — generic, lowest priority.
        if participant_age < 0:
            raise err(ERR_VALIDATION, "participant_age must be >= 0")

        enrolled_before = program["enrolled_count"]
        seat_available = enrolled_before < program["capacity"]

        rec = new_record(with_version=True)
        rec.update({
            "program_session_id": session_id,
            "membership_id": membership_id,
            "participant_name": participant_name,
            "participant_age": participant_age,
            "tuition_charged_cents": None,
            "waitlist_position": None,
            "expected_session_version": expected_session_version,
            "status": "WAITLISTED",
        })

        if seat_available:
            # Enroll directly; snapshot tuition (uses enrolled_count BEFORE this).
            rec["status"] = "ENROLLED"
            rec["tuition_charged_cents"] = program_tuition_pricing(
                program, membership, enrolled_before
            )
            db.registrations[rec["id"]] = rec
            recompute_enrolled_count(program)
            # Bubble-up ENROLLING -> FULL if at capacity.
            if program["status"] == "ENROLLING" and program["enrolled_count"] >= program["capacity"]:
                program["status"] = "FULL"
            recompute_waitlist_positions(program)
            touch(program)
        else:
            # Waitlist: tuition is not snapshotted (only enrolled registrations).
            # enrolled_count is unchanged and the session itself is not mutated,
            # so the session's version is NOT bumped (PRD §2.4: version bumps on
            # a mutation that touches the resource; a waitlist add does not).
            db.registrations[rec["id"]] = rec
            recompute_waitlist_positions(program)
        return success(registration_view(rec), status=201)


@bp.route("/registrations", methods=["GET"])
def list_registrations():
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    limit, offset = parse_pagination()
    session_id = request.args.get("program_session_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    with db.lock:
        records = list(db.registrations.values())
        if session_id is not None:
            records = [r for r in records if r["program_session_id"] == session_id]
        if membership_id is not None:
            records = [r for r in records if r["membership_id"] == membership_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [registration_view(r) for r in page]
    return success(data, status=200, pagination=meta)


@bp.route("/registrations/<rid>", methods=["GET"])
def get_one_registration(rid):
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    with db.lock:
        r = get_registration(rid)
        return success(registration_view(r), status=200)


@bp.route("/registrations/<rid>/cancel", methods=["POST"])
def cancel_registration(rid):
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    with db.lock:
        r = get_registration(rid)
        program = get_program(r["program_session_id"])

        if r["status"] == "WAITLISTED":
            # Simply leave the waitlist; remaining positions shift down.
            r["status"] = "CANCELLED"
            r["waitlist_position"] = None
            touch(r)
            recompute_waitlist_positions(program)
            return success(registration_view(r), status=200)

        if r["status"] == "ENROLLED":
            # Permitted only while session is ENROLLING or FULL.
            if program["status"] not in ("ENROLLING", "FULL"):
                raise err(ERR_INVALID_STATE, "Session not in a cancellable state")
            r["status"] = "CANCELLED"
            r["waitlist_position"] = None
            touch(r)
            # Recompute enrolled_count downward.
            recompute_enrolled_count(program)
            # Promote earliest WAITLISTED -> ENROLLED to fill the freed seat.
            wl = waitlisted_registrations(program)
            if wl:
                promoted = wl[0]
                enrolled_before = program["enrolled_count"]
                promoted["status"] = "ENROLLED"
                promoted["tuition_charged_cents"] = program_tuition_pricing(
                    program, _membership_of(promoted), enrolled_before
                )
                promoted["waitlist_position"] = None
                touch(promoted)
                recompute_enrolled_count(program)
            else:
                # No waitlist remains; reopen the session if it was FULL.
                if program["status"] == "FULL" and program["enrolled_count"] < program["capacity"]:
                    program["status"] = "ENROLLING"
            recompute_waitlist_positions(program)
            touch(program)
            return success(registration_view(r), status=200)

        raise err(ERR_INVALID_STATE, "Registration is not in a cancellable state")


def _membership_of(reg):
    mid = reg.get("membership_id")
    if mid is None:
        return None
    return db.memberships.get(mid)
