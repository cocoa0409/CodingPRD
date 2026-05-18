"""ACCRequest and ACCVote endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, jsonify

from ..auth import require_roles
from ..calculations import ACC_DEEMED_DECISION_DAYS
from ..envelope import success_object
from ..errors import (
    APIError,
    err_forbidden,
    err_invalid_state,
    err_not_on_acc,
    err_owner_delinquent,
    err_reserve_posture,
)
from ..serializers import serialize_acc_request, serialize_acc_vote
from ..services.clock_sweep import run_sweep
from ..services.common import (
    bump_member_overdue,
    bump_version,
    check_version,
    latest_adopted_reserve_study,
    require,
)
from ..store import store
from ..util import new_uuid
from ._helpers import get_json_body, get_version, require_field

bp = Blueprint("acc", __name__)

ACC_SEATS = {"PRESIDENT", "SECRETARY", "DIRECTOR"}


@bp.route("/hoa/acc-requests/<request_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_acc_request(request_id: str):
    run_sweep()
    req = require("acc_requests", request_id)
    return jsonify(success_object(serialize_acc_request(req))), 200


@bp.route("/hoa/acc-requests", methods=["POST"])
@require_roles(["Member"])
def submit_acc_request():
    body = get_json_body()
    unit_id = require_field(body, "unit_id")
    category = require_field(body, "category")
    description = require_field(body, "description")

    if category not in {"APPEARANCE", "LANDSCAPING"}:
        raise APIError("ERR_INVALID_STATE", "category must be APPEARANCE or LANDSCAPING", 409)

    unit = require("units", unit_id)
    if unit["owner_member_id"] != g.user_id:
        raise err_forbidden("Submitter must own the unit")

    s = store()
    now = s.now()
    req = {
        "id": new_uuid(),
        "unit_id": unit_id,
        "submitted_by_member_id": g.user_id,
        "category": category,
        "description": description,
        "submitted_at": now,
        "deemed_decision_deadline": now + timedelta(days=ACC_DEEMED_DECISION_DAYS),
        "status": "SUBMITTED",
        "yes_votes": 0,
        "no_votes": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("acc_requests", req)
    return jsonify(success_object(serialize_acc_request(req))), 201


@bp.route("/hoa/acc-requests/<request_id>/begin-review", methods=["POST"])
@require_roles(["SecretaryRole"])
def begin_review(request_id: str):
    req = require("acc_requests", request_id)
    body = get_json_body()
    version = get_version(body)

    # PRD §2.7 validation ordering: state-transition admissibility precedes
    # domain checks; optimistic concurrency is reported only after the
    # foregoing checks have passed.
    if req["status"] != "SUBMITTED":
        raise err_invalid_state(f"Request is in {req['status']}, cannot begin review")

    s = store()
    owner = s.members.get(req["submitted_by_member_id"])
    if owner is None:
        raise err_invalid_state("Submitter member missing")

    # Refresh owner overdue first to enforce up-to-date check
    bump_member_overdue(owner)
    if owner.get("total_overdue_amount_cents", 0) != 0:
        raise err_owner_delinquent()

    # Reserve posture check
    latest = latest_adopted_reserve_study()
    if latest is not None and latest.get("posture") == "SPECIAL_ASSESSMENT_REQUIRED":
        raise err_reserve_posture()

    # Optimistic concurrency last, per §2.7.
    check_version(req, version)

    now = s.now()
    req["status"] = "UNDER_REVIEW"
    # Deemed decision deadline assignment is idempotent
    req["deemed_decision_deadline"] = req["submitted_at"] + timedelta(days=ACC_DEEMED_DECISION_DAYS)
    bump_version(req, now)

    return jsonify(success_object(serialize_acc_request(req))), 200


@bp.route("/hoa/acc-requests/<request_id>/votes", methods=["POST"])
@require_roles(["PresidentRole", "SecretaryRole", "DirectorRole"])
def cast_acc_vote(request_id: str):
    req = require("acc_requests", request_id)
    body = get_json_body()
    vote = require_field(body, "vote")
    if vote not in {"YES", "NO"}:
        raise APIError("ERR_INVALID_STATE", "vote must be YES or NO", 409)

    # Bring lazy auto-resolutions up-to-date
    run_sweep()
    req = require("acc_requests", request_id)
    if req["status"] != "UNDER_REVIEW":
        raise err_invalid_state(f"Request is in {req['status']}, votes not accepted")

    s = store()
    voter = s.members.get(g.user_id)
    if voter is None or voter.get("board_role") not in ACC_SEATS:
        raise err_not_on_acc()

    now = s.now()
    new_vote = {
        "id": new_uuid(),
        "request_id": request_id,
        "voter_member_id": g.user_id,
        "vote": vote,
        "cast_at": now,
        "created_at": now,
    }
    s.insert("acc_votes", new_vote)

    if vote == "YES":
        req["yes_votes"] = req.get("yes_votes", 0) + 1
    else:
        req["no_votes"] = req.get("no_votes", 0) + 1
    bump_version(req, now)

    # Auto-transition on threshold (before deadline)
    if now < req["deemed_decision_deadline"]:
        if req["yes_votes"] >= 2:
            req["status"] = "APPROVED"
            bump_version(req, now)
        elif req["no_votes"] >= 2:
            req["status"] = "DENIED"
            bump_version(req, now)

    return jsonify(success_object(serialize_acc_vote(new_vote))), 201


@bp.route("/hoa/acc-requests/<request_id>", methods=["DELETE"])
@require_roles(["Member"])
def withdraw_acc_request(request_id: str):
    req = require("acc_requests", request_id)

    if req["submitted_by_member_id"] != g.user_id:
        raise err_forbidden("Only the submitter may withdraw")

    if req["status"] == "SUBMITTED":
        pass
    elif req["status"] == "UNDER_REVIEW":
        if req.get("yes_votes", 0) >= 2 or req.get("no_votes", 0) >= 2:
            raise err_invalid_state("Decision threshold crossed; cannot withdraw")
    else:
        raise err_invalid_state(f"Request is in {req['status']}, cannot withdraw")

    now = store().now()
    req["status"] = "WITHDRAWN"
    bump_version(req, now)

    return jsonify(success_object(serialize_acc_request(req))), 200
