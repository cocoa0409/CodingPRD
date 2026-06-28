"""Waitlist endpoints (PRD §3.8)."""

from flask import Blueprint, request

import errors
from errors import ApiError
from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_int, require_enum, require_iso_datetime, bad
from services.common import new_record, touch, lookup, paginate, sorted_by_created
from services import serialize, engine, booking

bp = Blueprint("waitlist", __name__)


@bp.route("/clinic/waitlist-entries", methods=["POST"])
@require_roles("ClinicAdmin", "SchedulingCoordinator")
def create_entry(user_id=None, role=None):
    body = get_body()
    child_id = require_str(body, "child_id")
    therapist_id = require_str(body, "therapist_id")
    discipline = require_enum(body, "discipline", {"SLP", "OT"})
    evaluation_id = require_str(body, "evaluation_id")
    requested = require_int(body, "requested_minutes", minimum=1)
    lookup(db.children, child_id)
    therapist = lookup(db.therapists, therapist_id)
    evaluation = lookup(db.evaluations, evaluation_id)
    # discipline must match therapist discipline.
    if discipline != therapist["discipline"]:
        raise ApiError(errors.ERR_THERAPIST_DISCIPLINE_MISMATCH, 409,
                       "Waitlist discipline does not match therapist discipline.")
    rec = new_record({
        "child_id": child_id,
        "therapist_id": therapist_id,
        "discipline": discipline,
        "evaluation_id": evaluation_id,
        # priority_score copied from the evaluation's severity_score.
        "priority_score": evaluation["severity_score"],
        "requested_minutes": requested,
        "status": "WAITING",
    })
    db.waitlist_entries[rec["id"]] = rec
    return success(serialize.waitlist_entry(rec), status=201)


@bp.route("/clinic/waitlist-entries", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_entries(user_id=None, role=None):
    items = list(db.waitlist_entries.values())
    for field in ("child_id", "therapist_id", "evaluation_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [w for w in items if w[field] == val]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.waitlist_entry(w) for w in page], limit, offset, total)


@bp.route("/clinic/waitlist-entries/<waitlist_entry_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_entry(waitlist_entry_id, user_id=None, role=None):
    rec = lookup(db.waitlist_entries, waitlist_entry_id)
    return success(serialize.waitlist_entry(rec), status=200)


@bp.route("/clinic/waitlist-entries/<waitlist_entry_id>/accept", methods=["POST"])
@require_roles("ClinicAdmin", "SchedulingCoordinator")
def accept(waitlist_entry_id, user_id=None, role=None):
    entry = lookup(db.waitlist_entries, waitlist_entry_id)
    if entry["status"] != "OFFERED":
        raise ApiError(errors.ERR_WAITLIST_NOT_OFFERED, 409,
                       "Waitlist entry must be OFFERED to accept.")
    body = get_body()
    authorization_id = require_str(body, "authorization_id")
    plan_of_care_id = require_str(body, "plan_of_care_id")
    start_dt = require_iso_datetime(body, "start_time")
    end_dt = require_iso_datetime(body, "end_time")
    if end_dt <= start_dt:
        raise bad("end_time must be after start_time.")
    # FK existence (PRD §2.5).
    lookup(db.authorizations, authorization_id)
    lookup(db.plans_of_care, plan_of_care_id)
    # Acceptance is a booking subject to the full scheduling battery; child and
    # therapist come from the entry.
    appt = booking.book_appointment(
        entry["child_id"], entry["therapist_id"], authorization_id,
        plan_of_care_id, start_dt, end_dt,
        from_waitlist_entry_id=entry["id"],
    )
    entry["status"] = "PLACED"
    touch(entry)
    return success(serialize.waitlist_entry(entry), status=200)


@bp.route("/clinic/waitlist-entries/<waitlist_entry_id>/decline", methods=["POST"])
@require_roles("ClinicAdmin", "SchedulingCoordinator")
def decline(waitlist_entry_id, user_id=None, role=None):
    entry = lookup(db.waitlist_entries, waitlist_entry_id)
    if entry["status"] != "OFFERED":
        raise ApiError(errors.ERR_WAITLIST_NOT_OFFERED, 409,
                       "Waitlist entry must be OFFERED to decline.")
    entry["status"] = "WAITING"
    touch(entry)
    # Re-run promotion so the next-highest-priority eligible entry is offered;
    # the just-declined entry is excluded from this round (PRD §3.8).
    engine.run_waitlist_promotion(entry["therapist_id"], exclude_ids={entry["id"]})
    return success(serialize.waitlist_entry(entry), status=200)


@bp.route("/clinic/waitlist-entries/<waitlist_entry_id>/withdraw", methods=["POST"])
@require_roles("ClinicAdmin", "SchedulingCoordinator")
def withdraw(waitlist_entry_id, user_id=None, role=None):
    entry = lookup(db.waitlist_entries, waitlist_entry_id)
    if entry["status"] not in ("WAITING", "OFFERED"):
        raise ApiError(errors.ERR_WAITLIST_NOT_WITHDRAWABLE, 409,
                       "Waitlist entry must be WAITING or OFFERED to withdraw.")
    entry["status"] = "WITHDRAWN"
    touch(entry)
    return success(serialize.waitlist_entry(entry), status=200)
