"""Registration routes + withdraw/promotion (PRD §3.5)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize, calc, cascade
from services.common import (
    new_record, get_body, get_or_404, paginate, touch, check_owner,
    req_str, opt_str,
)

bp = Blueprint("registrations", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}
WRITE_ROLES = {"Visitor", "GardenStaff"}


@bp.route("/v1/registrations", methods=["POST"])
def create_registration():
    _, role = get_identity()
    require_role(role, WRITE_ROLES)
    body = get_body()
    garden_id = req_str(body, "garden_id")
    program_session_id = req_str(body, "program_session_id")
    participant_name = req_str(body, "participant_name")
    membership_id = opt_str(body, "membership_id", "")

    get_or_404(db.gardens, garden_id)
    session = get_or_404(db.program_sessions, program_session_id)
    membership = None
    if membership_id:
        membership = get_or_404(db.memberships, membership_id)

    # Same-garden referential integrity.
    if session["garden_id"] != garden_id:
        raise errors.cross_garden_reference()
    if membership is not None and membership["garden_id"] != garden_id:
        raise errors.cross_garden_reference()

    # CLOSED session rejects new registrations (PRD §3.5).
    if session["status"] == "CLOSED":
        raise errors.session_closed()

    # Member discount applies when membership attached AND ACTIVE.
    applies = False
    discount_pct = 0
    if membership is not None and membership["status"] == "ACTIVE":
        plan = db.membership_plans.get(membership["plan_id"])
        if plan is not None:
            applies = True
            discount_pct = plan["program_discount_pct"]

    if session["enrolled_count"] < session["capacity"]:
        # Room: enroll immediately.
        charged_cents = calc.program_tuition_charge(
            session["tuition_cents"], applies, discount_pct)
        rec = new_record({
            "garden_id": garden_id,
            "program_session_id": program_session_id,
            "membership_id": membership_id,
            "participant_name": participant_name,
            "charged_cents": charged_cents,
            "status": "ENROLLED",
            "waitlist_rank": 0,
        })
        db.registrations[rec["id"]] = rec
        session["enrolled_count"] = session["enrolled_count"] + 1
        touch(session)
    else:
        # Full: waitlist at the back. waitlist_rank = current waitlist size + 1.
        current_waitlist = [r for r in db.registrations.values()
                            if r["program_session_id"] == program_session_id
                            and r["status"] == "WAITLISTED"]
        rank = len(current_waitlist) + 1
        rec = new_record({
            "garden_id": garden_id,
            "program_session_id": program_session_id,
            "membership_id": membership_id,
            "participant_name": participant_name,
            "charged_cents": 0,  # charged only when ENROLLED
            "status": "WAITLISTED",
            "waitlist_rank": rank,
        })
        db.registrations[rec["id"]] = rec

    return success(serialize.registration(rec), status=201)


@bp.route("/v1/registrations/<registration_id>", methods=["GET"])
def read_registration(registration_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.registrations, registration_id)
    return success(serialize.registration(rec), status=200)


@bp.route("/v1/registrations", methods=["GET"])
def list_registrations():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    program_session_id = request.args.get("program_session_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    records = list(db.registrations.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if program_session_id is not None:
        records = [r for r in records if r["program_session_id"] == program_session_id]
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.registration(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/registrations/<registration_id>/withdraw", methods=["POST"])
def withdraw_registration(registration_id):
    user_id, role = get_identity()
    require_role(role, WRITE_ROLES)
    rec = get_or_404(db.registrations, registration_id)
    check_owner(role, user_id, rec["membership_id"])
    # Only ENROLLED or WAITLISTED may be withdrawn (PRD §3.5).
    if rec["status"] not in {"ENROLLED", "WAITLISTED"}:
        raise errors.invalid_state()

    session = db.program_sessions.get(rec["program_session_id"])
    if rec["status"] == "ENROLLED":
        rec["status"] = "WITHDRAWN"
        touch(rec)
        if session is not None:
            session["enrolled_count"] = session["enrolled_count"] - 1
            touch(session)
            cascade.promote_head_waitlister(session)
    else:  # WAITLISTED
        removed_rank = rec["waitlist_rank"]
        rec["status"] = "WITHDRAWN"
        rec["waitlist_rank"] = 0
        touch(rec)
        if session is not None:
            cascade.rerank_after_waitlist_removal(session, removed_rank)

    return success(serialize.registration(rec), status=200)
