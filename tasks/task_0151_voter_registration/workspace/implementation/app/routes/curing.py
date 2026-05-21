"""Curing-case endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_user, require_roles
from ..envelope import success_object
from ..errors import (
    err_deadline_passed,
    err_forbidden,
    err_forbidden_sod,
    err_invalid_state,
    err_max_rounds,
)
from ..serializers import serialize_curing_case
from ..services.cascades import cascade_curing_resolved_accept
from ..services.common import bump_version, check_version, require
from ..store import store
from ..util import new_uuid
from ._helpers import as_str, get_json_body, get_version, require_field

bp = Blueprint("curing", __name__)


@bp.route("/curing-cases/<case_id>", methods=["GET"])
@require_roles(["Voter", "ReviewerClerk", "ElectionBoard"])
def get_case(case_id: str):
    cc = require("curing_cases", case_id)
    uid, role = current_user()
    if role == "Voter" and cc["voter_id"] != uid:
        raise err_forbidden("Voter can only view their own curing case")
    return jsonify(success_object(serialize_curing_case(cc))), 200


@bp.route("/curing-cases/<case_id>/submit", methods=["POST"])
@require_roles(["Voter"])
def submit_cure(case_id: str):
    cc = require("curing_cases", case_id)
    uid, _ = current_user()

    # Priority: SOD-style ownership check before state
    if cc["voter_id"] != uid:
        raise err_forbidden("Only the owning voter can submit a cure")

    if cc["status"] != "OPEN_PENDING_VOTER":
        raise err_invalid_state("CuringCase must be OPEN_PENDING_VOTER to submit")

    body = get_json_body()
    voter_submission_text = as_str(
        require_field(body, "voter_submission_text"), "voter_submission_text"
    )
    voter_choice = as_str(require_field(body, "voter_choice"), "voter_choice")
    version = get_version(body)

    s = store()
    election = require("elections", cc["election_id"])
    now = s.now()

    # PRD §3.5 strict > comparison on cure_deadline
    if now > election["cure_deadline"]:
        raise err_deadline_passed("cure_deadline has passed")
    check_version(cc, version)

    cc["status"] = "UNDER_REVIEW"
    cc["voter_submission_text"] = voter_submission_text
    cc["voter_choice"] = voter_choice
    bump_version(cc, now)
    return jsonify(success_object(serialize_curing_case(cc))), 200


@bp.route("/curing-cases/<case_id>/request-revision", methods=["POST"])
@require_roles(["ReviewerClerk"])
def request_revision(case_id: str):
    cc = require("curing_cases", case_id)
    uid, _ = current_user()

    # SOD priority (per §2.9 priority 4)
    voter = require("voters", cc["voter_id"])
    if voter.get("registered_by_user_id") == uid:
        raise err_forbidden_sod()

    if cc["status"] != "UNDER_REVIEW":
        raise err_invalid_state("CuringCase must be UNDER_REVIEW to request revision")

    body = get_json_body()
    version = get_version(body)
    s = store()
    election = require("elections", cc["election_id"])
    now = s.now()

    if cc.get("round_count", 0) >= cc.get("max_rounds", 3):
        raise err_max_rounds()
    if now > election["cure_deadline"]:
        raise err_deadline_passed("cure_deadline has passed")
    check_version(cc, version)

    cc["status"] = "OPEN_PENDING_VOTER"
    cc["round_count"] = cc.get("round_count", 0) + 1
    bump_version(cc, now)
    return jsonify(success_object(serialize_curing_case(cc))), 200


@bp.route("/curing-cases/<case_id>/state", methods=["POST"])
@require_roles(["ReviewerClerk"])
def resolve_case(case_id: str):
    cc = require("curing_cases", case_id)
    uid, _ = current_user()
    voter = require("voters", cc["voter_id"])

    # SOD check
    if voter.get("registered_by_user_id") == uid:
        raise err_forbidden_sod()

    body = get_json_body()
    to_state = as_str(require_field(body, "to_state"), "to_state")
    version = get_version(body)

    if cc["status"] != "UNDER_REVIEW":
        raise err_invalid_state("CuringCase must be UNDER_REVIEW to resolve")
    if to_state not in ("RESOLVED_ACCEPT", "RESOLVED_REJECT"):
        raise err_invalid_state("to_state must be RESOLVED_ACCEPT or RESOLVED_REJECT")

    s = store()
    election = require("elections", cc["election_id"])
    now = s.now()

    if to_state == "RESOLVED_ACCEPT":
        if now > election["cure_deadline"]:
            raise err_deadline_passed("cure_deadline has passed")
        check_version(cc, version)
        cc["status"] = "RESOLVED_ACCEPT"
        bump_version(cc, now)
        cascade_curing_resolved_accept(cc)
    else:  # RESOLVED_REJECT
        check_version(cc, version)
        cc["status"] = "RESOLVED_REJECT"
        bump_version(cc, now)

    return jsonify(success_object(serialize_curing_case(cc))), 200
