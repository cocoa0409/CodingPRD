"""ScholarshipOffer endpoints (state machine: DRAFT/SENT/ACCEPTED/DECLINED/WITHDRAWN)."""

from flask import Blueprint, g, request

import db
import services
from errors import (
    APIError,
    ERR_ATHLETE_NOT_CERTIFIED,
    ERR_COACH_PROGRAM_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_SLOT_CAP_EXCEEDED,
    ERR_STALE_PROGRAM_VERSION,
    invalid_request,
    invalid_state,
    not_found,
    unauthorized,
)
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("scholarship_offers", __name__)


OFFER_STATUSES = {"DRAFT", "SENT", "ACCEPTED", "DECLINED", "WITHDRAWN"}


@bp.post("/ncaa/scholarship-offers")
def create_offer():
    require_roles("Coach")
    body = get_body()
    program_id = require_field(body, "program_id", str)
    athlete_id = require_field(body, "student_athlete_id", str)
    raw_value = body.get("annual_value_cents")
    if raw_value is None:
        raise invalid_request("Required field 'annual_value_cents' is missing.")
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise invalid_request("annual_value_cents must be an integer.")
    if raw_value < 0:
        raise invalid_request("annual_value_cents must be >= 0.")
    program = db.programs.get(program_id)
    if program is None:
        raise not_found("Program not found.")
    athlete = db.student_athletes.get(athlete_id)
    if athlete is None:
        raise not_found("StudentAthlete not found.")
    row = {
        "id": db.new_id(),
        "program_id": program_id,
        "student_athlete_id": athlete_id,
        "status": "DRAFT",
        "annual_value_cents": int(raw_value),
        "sent_at": None,
        # Pin the coach who authored the offer; later coach-driven transitions
        # require the acting X-User-ID to match this (PRD §2.1).
        "coach_user_id": g.user_id,
    }
    db.stamp_create(row)
    db.scholarship_offers[row["id"]] = row
    # PRD §3.4: "A draft offer does not occupy a slot." PRD §1.3 lists the
    # events that recompute slot counts: every `ScholarshipOffer` state
    # transition, every `EligibilityCertification` denial cascade, and every
    # booster-incident sustain that escalates the program to `POSTSEASON_BAN`.
    # DRAFT creation is the initial state, not a transition between states —
    # it does NOT trigger a recompute or program version bump. slots_projected
    # is computed at read time from current offer rows (see compute endpoint).
    return ok_object(row, 201)


@bp.get("/ncaa/scholarship-offers/<offer_id>")
def get_offer(offer_id):
    require_roles("ComplianceOfficer", "Coach", "StudentAthlete")
    row = db.scholarship_offers.get(offer_id)
    if row is None:
        raise not_found("ScholarshipOffer not found.")
    return ok_object(row)


@bp.get("/ncaa/scholarship-offers")
def list_offers():
    require_roles("ComplianceOfficer", "Coach", "StudentAthlete")
    limit, offset = parse_pagination()
    program_id = request.args.get("program_id")
    athlete_id = request.args.get("student_athlete_id")
    status = request.args.get("status")
    if status is not None and status not in OFFER_STATUSES:
        raise invalid_request("status filter is not a valid enum.")
    rows = list(db.scholarship_offers.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if athlete_id is not None:
        rows = [r for r in rows if r["student_athlete_id"] == athlete_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/ncaa/scholarship-offers/<offer_id>/send")
def send_offer(offer_id):
    require_roles("Coach")
    offer = db.scholarship_offers.get(offer_id)
    if offer is None:
        raise not_found("ScholarshipOffer not found.")
    # Body validation: expected_program_version is required and non-optional
    body = get_body()
    if "expected_program_version" not in body:
        raise invalid_request("expected_program_version is required.")
    raw_v = body["expected_program_version"]
    if isinstance(raw_v, bool) or not isinstance(raw_v, int):
        raise invalid_request("expected_program_version must be an integer.")
    # State check
    if offer["status"] != "DRAFT":
        raise invalid_state("Offer is not in DRAFT state.")
    # OCC on Program (priority 6 per validation table)
    program = db.programs.get(offer["program_id"])
    if program is None:
        raise not_found("Program not found.")
    if int(raw_v) != int(program["version"]):
        raise APIError(
            ERR_STALE_PROGRAM_VERSION,
            "expected_program_version does not match Program.version.",
            412,
        )
    # Business rules (after OCC)
    # ERR_COACH_PROGRAM_MISMATCH (priority 12)
    if g.user_id != offer["coach_user_id"]:
        raise APIError(
            ERR_COACH_PROGRAM_MISMATCH,
            "Coach is not affiliated with this offer's program.",
            403,
        )
    # ERR_ATHLETE_NOT_CERTIFIED (priority 14)
    athlete = db.student_athletes.get(offer["student_athlete_id"])
    if athlete is None or athlete["eligibility_status"] != "CERTIFIED":
        raise APIError(
            ERR_ATHLETE_NOT_CERTIFIED,
            "Athlete must be CERTIFIED to receive a sent offer.",
            422,
        )
    # ERR_PROGRAM_UNDER_SANCTION-equivalent: POSTSEASON_BAN forbids new sends.
    # Per scaffold preconditions, Program.penalty_tier != POSTSEASON_BAN.
    if program["penalty_tier"] == "POSTSEASON_BAN":
        raise invalid_state(
            "Program is under POSTSEASON_BAN; new offers cannot be sent."
        )
    # ERR_SLOT_CAP_EXCEEDED (priority 17)
    committed = services.compute_slots_committed(offer["program_id"])
    if committed + 1 > program["scholarship_slot_cap"]:
        raise APIError(
            ERR_SLOT_CAP_EXCEEDED,
            "Sending this offer would exceed the program's scholarship_slot_cap.",
            422,
        )
    # Apply
    offer["status"] = "SENT"
    offer["sent_at"] = db.current_utc_iso()
    db.stamp_update(offer)
    services.refresh_program_counts(program)
    db.stamp_update(program)
    return ok_object(offer)


@bp.post("/ncaa/scholarship-offers/<offer_id>/accept")
def accept_offer(offer_id):
    require_roles("StudentAthlete")
    offer = db.scholarship_offers.get(offer_id)
    if offer is None:
        raise not_found("ScholarshipOffer not found.")
    if offer["status"] != "SENT":
        raise invalid_state("Offer is not in SENT state.")
    # Acting athlete must be the offer's recipient.
    if g.user_id != offer["student_athlete_id"]:
        raise unauthorized(
            "Acting StudentAthlete is not the recipient of this offer."
        )
    offer["status"] = "ACCEPTED"
    db.stamp_update(offer)
    athlete = db.student_athletes.get(offer["student_athlete_id"])
    if athlete is not None:
        athlete["enrolled_program_id"] = offer["program_id"]
        db.stamp_update(athlete)
    # Slot count semantics: ACCEPTED keeps the slot. compute_slots_committed
    # counts both SENT and ACCEPTED, so committed is unchanged. But refresh
    # & bump program version only if recomputed counts changed.
    program = db.programs.get(offer["program_id"])
    if program is not None:
        old_committed = program.get("slots_committed", 0)
        old_proj = program.get("slots_projected", 0)
        services.refresh_program_counts(program)
        if (program.get("slots_committed", 0) != old_committed
                or program.get("slots_projected", 0) != old_proj):
            db.stamp_update(program)
    return ok_object(offer)


@bp.post("/ncaa/scholarship-offers/<offer_id>/decline")
def decline_offer(offer_id):
    require_roles("StudentAthlete")
    offer = db.scholarship_offers.get(offer_id)
    if offer is None:
        raise not_found("ScholarshipOffer not found.")
    if offer["status"] != "SENT":
        raise invalid_state("Offer is not in SENT state.")
    if g.user_id != offer["student_athlete_id"]:
        raise unauthorized(
            "Acting StudentAthlete is not the recipient of this offer."
        )
    offer["status"] = "DECLINED"
    db.stamp_update(offer)
    program = db.programs.get(offer["program_id"])
    if program is not None:
        services.refresh_program_counts(program)
        db.stamp_update(program)
    return ok_object(offer)


@bp.post("/ncaa/scholarship-offers/<offer_id>/withdraw")
def withdraw_offer(offer_id):
    require_roles("Coach")
    offer = db.scholarship_offers.get(offer_id)
    if offer is None:
        raise not_found("ScholarshipOffer not found.")
    if offer["status"] not in ("DRAFT", "SENT"):
        raise invalid_state("Offer is not in DRAFT or SENT state.")
    if g.user_id != offer["coach_user_id"]:
        raise APIError(
            ERR_COACH_PROGRAM_MISMATCH,
            "Coach is not affiliated with this offer's program.",
            403,
        )
    prior = offer["status"]
    offer["status"] = "WITHDRAWN"
    db.stamp_update(offer)
    program = db.programs.get(offer["program_id"])
    if program is not None:
        old_committed = program.get("slots_committed", 0)
        old_proj = program.get("slots_projected", 0)
        services.refresh_program_counts(program)
        if (program.get("slots_committed", 0) != old_committed
                or program.get("slots_projected", 0) != old_proj):
            db.stamp_update(program)
    return ok_object(offer)
