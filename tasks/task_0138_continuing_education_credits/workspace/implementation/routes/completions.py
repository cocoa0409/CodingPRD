"""Completion endpoints (PRD §3.4): log, verify, reject, resubmit."""

from datetime import timedelta

from flask import Blueprint, g, request

import errors
import serialize
import services.cycle as cycle_service
import services.risk as risk_service
from common import (
    get_json_body,
    require_string,
    require_field,
    optional_field,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record, bump
from response import success_object, success_list
from routes.courses import get_course_or_404
from routes.licensees import get_licensee_or_404
from routes.renewal_cycles import get_cycle_or_404
from util import parse_iso


bp = Blueprint("completions", __name__)


def get_completion_or_404(completion_id):
    c = db.completions.get(completion_id)
    if c is None:
        raise errors.not_found(f"Completion '{completion_id}' not found.")
    return c


def _is_late(completed_at, cycle, board):
    """True when completed_at is within reminder_lead_days of cycle_end (i.e. in
    the reminder/overdue window): completed_at >= cycle_end - reminder_lead_days."""
    remind_at = cycle["cycle_end"] - timedelta(days=board["reminder_lead_days"])
    return completed_at >= remind_at


@bp.route("/completions", methods=["POST"])
@require_roles("Licensee", "BoardAdmin")
def create_completion():
    body = get_json_body()
    licensee_id = require_string(body, "licensee_id")
    course_id = require_string(body, "course_id")
    cycle_id = require_string(body, "cycle_id")
    completed_at_raw = require_field(body, "completed_at")
    completed_at = parse_iso(completed_at_raw, field="completed_at")

    # Existence (404), validated for each FK.
    licensee = get_licensee_or_404(licensee_id)
    course = get_course_or_404(course_id)
    cycle = get_cycle_or_404(cycle_id)

    # Ownership: a Licensee may only log completions for its own licensee_id.
    if g.user_role == "Licensee" and g.user_id != licensee_id:
        raise errors.not_resource_owner(
            "Licensee may only log completions for its own licensee_id."
        )

    # Temporal window: completed_at within [cycle_start, cycle_end).
    if not (cycle["cycle_start"] <= completed_at < cycle["cycle_end"]):
        raise errors.completion_out_of_window(
            "completed_at must fall within the renewal window."
        )

    board = db.license_boards[cycle["board_id"]]

    with db.lock:
        rec = new_full_record()
        rec.update({
            "licensee_id": licensee_id,
            "course_id": course_id,
            "cycle_id": cycle_id,
            "completed_at": completed_at,
            # Snapshot the award from the course at submission.
            "awarded_hours": course["credit_hours"],
            "category": course["category"],
            "status": "PENDING_VERIFICATION",
            "is_late": _is_late(completed_at, cycle, board),
        })
        db.completions[rec["id"]] = rec

        # Logging immediately recomputes the cycle's provisional tally.
        cycle_service.recompute_credit_tally(cycle)
        bump(cycle)

    return success_object(serialize.completion(rec), status=201)


@bp.route("/completions/<completion_id>", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def get_completion(completion_id):
    c = get_completion_or_404(completion_id)
    return success_object(serialize.completion(c), status=200)


@bp.route("/completions", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_completions():
    limit, offset = parse_pagination()
    licensee_id = request.args.get("licensee_id")
    course_id = request.args.get("course_id")
    cycle_id = request.args.get("cycle_id")
    items = list(db.completions.values())
    if licensee_id is not None:
        items = [c for c in items if c["licensee_id"] == licensee_id]
    if course_id is not None:
        items = [c for c in items if c["course_id"] == course_id]
    if cycle_id is not None:
        items = [c for c in items if c["cycle_id"] == cycle_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.completion(c) for c in page], limit, offset, total, status=200,
    )


@bp.route("/renewal-cycles/<cycle_id>/completions", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_cycle_completions(cycle_id):
    get_cycle_or_404(cycle_id)
    limit, offset = parse_pagination()
    items = [c for c in db.completions.values() if c["cycle_id"] == cycle_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.completion(c) for c in page], limit, offset, total, status=200,
    )


@bp.route("/completions/<completion_id>/verify", methods=["POST"])
@require_roles("BoardAdmin")
def verify_completion(completion_id):
    comp = get_completion_or_404(completion_id)

    with db.lock:
        # State gate (priority 5).
        if comp["status"] != "PENDING_VERIFICATION":
            raise errors.invalid_state("Completion must be PENDING_VERIFICATION to verify.")

        cycle = db.renewal_cycles[comp["cycle_id"]]
        course = db.courses[comp["course_id"]]
        provider = db.providers[course["provider_id"]]

        # Cycle must be OPEN or REQUIREMENTS_MET (part of the defined transition).
        if cycle["status"] not in ("OPEN", "REQUIREMENTS_MET"):
            raise errors.invalid_state(
                "Cycle must be OPEN or REQUIREMENTS_MET to verify a completion."
            )

        # Cross-entity accreditation gate (priority 6).
        if provider["status"] != "ACCREDITED":
            raise errors.provider_not_accredited(
                "The course's provider must be ACCREDITED to verify."
            )

        # Provider accreditation window (priority 8): [accredited_from, accredited_until).
        af = provider["accredited_from"]
        au = provider["accredited_until"]
        if af is None or au is None or not (af <= comp["completed_at"] < au):
            raise errors.completion_out_of_window(
                "completed_at is outside the provider accreditation window."
            )

        comp["status"] = "VERIFIED"
        bump(comp)

        cycle_service.recompute_credit_tally(cycle)
        bump(cycle)
        # Bubble-up: OPEN -> REQUIREMENTS_MET (and carryover) if now met.
        cycle_service.reconcile_after_recompute(cycle, bump)

    return success_object(serialize.completion(comp), status=200)


@bp.route("/completions/<completion_id>/reject", methods=["POST"])
@require_roles("BoardAdmin")
def reject_completion(completion_id):
    comp = get_completion_or_404(completion_id)
    body = get_json_body()
    _reason = optional_field(body, "reason", default=None, types=str)

    with db.lock:
        if comp["status"] != "PENDING_VERIFICATION":
            raise errors.invalid_state("Completion must be PENDING_VERIFICATION to reject.")

        cycle = db.renewal_cycles[comp["cycle_id"]]
        comp["status"] = "REJECTED"
        bump(comp)

        cycle_service.recompute_credit_tally(cycle)
        bump(cycle)
        cycle_service.reconcile_after_recompute(cycle, bump)

        # Recompute the owning licensee's audit_risk_score (intake variant).
        licensee = db.licensees[comp["licensee_id"]]
        new_score = risk_service.compute_intake(licensee["id"])
        if new_score != licensee["audit_risk_score"]:
            licensee["audit_risk_score"] = new_score
            bump(licensee)

    return success_object(serialize.completion(comp), status=200)


@bp.route("/completions/<completion_id>/resubmit", methods=["POST"])
@require_roles("Licensee")
def resubmit_completion(completion_id):
    comp = get_completion_or_404(completion_id)

    # Ownership: Licensee may only resubmit its own completion (priority 4).
    if g.user_role == "Licensee" and g.user_id != comp["licensee_id"]:
        raise errors.not_resource_owner(
            "Licensee may only resubmit its own completions."
        )

    with db.lock:
        if comp["status"] != "REJECTED":
            raise errors.invalid_state("Completion must be REJECTED to resubmit.")

        cycle = db.renewal_cycles[comp["cycle_id"]]
        if cycle["status"] not in ("OPEN", "REQUIREMENTS_MET"):
            raise errors.invalid_state(
                "Cycle must be OPEN or REQUIREMENTS_MET to resubmit a completion."
            )

        comp["status"] = "PENDING_VERIFICATION"
        bump(comp)

        cycle_service.recompute_credit_tally(cycle)
        bump(cycle)
        cycle_service.reconcile_after_recompute(cycle, bump)

    return success_object(serialize.completion(comp), status=200)
