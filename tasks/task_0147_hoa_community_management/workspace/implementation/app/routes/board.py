"""BoardResolution endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..errors import (
    APIError,
    err_invalid_state,
    err_resolution_target,
    err_segregation,
)
from ..serializers import serialize_board_resolution
from ..services.clock_sweep import run_sweep
from ..services.common import bump_version, require
from ..store import store
from ..util import new_uuid
from ._helpers import get_json_body, require_field

bp = Blueprint("board", __name__)

VALID_SUBJECTS = {
    "SPECIAL_ASSESSMENT",
    "RESERVE_STUDY_ADOPTION",
    "FINE_WAIVER",
    "LIEN_RECORDATION",
    "LIEN_RELEASE",
}

BOARD_SEATS = {"PRESIDENT", "TREASURER", "SECRETARY", "DIRECTOR"}


def _validate_target(subject: str, target_id: str) -> None:
    s = store()
    if subject == "SPECIAL_ASSESSMENT":
        cycle = s.assessment_cycles.get(target_id)
        if cycle is None:
            raise err_resolution_target("Target AssessmentCycle not found")
        if cycle["status"] != "DRAFT":
            raise err_resolution_target("Target cycle must be in DRAFT")
    elif subject == "RESERVE_STUDY_ADOPTION":
        study = s.reserve_studies.get(target_id)
        if study is None:
            raise err_resolution_target("Target ReserveStudy not found")
        if study["status"] != "DRAFT":
            raise err_resolution_target("Target study must be in DRAFT")
    elif subject == "FINE_WAIVER":
        v = s.violations.get(target_id)
        if v is None:
            raise err_resolution_target("Target Violation not found")
        if v["status"] not in {"OPEN", "FINED"}:
            raise err_resolution_target("Target violation must be OPEN or FINED")
    elif subject in {"LIEN_RECORDATION", "LIEN_RELEASE"}:
        lien = s.liens.get(target_id)
        if lien is None:
            raise err_resolution_target("Target Lien not found")
    else:
        raise err_resolution_target(f"Unknown subject {subject}")


@bp.route("/hoa/board-resolutions/<resolution_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_resolution(resolution_id: str):
    run_sweep()
    r = require("board_resolutions", resolution_id)
    return jsonify(success_object(serialize_board_resolution(r))), 200


@bp.route("/hoa/board-resolutions", methods=["POST"])
@require_roles(["PresidentRole", "TreasurerRole", "SecretaryRole", "DirectorRole"])
def create_resolution():
    body = get_json_body()
    subject = require_field(body, "subject")
    target_id = require_field(body, "target_id")

    if subject not in VALID_SUBJECTS:
        raise err_resolution_target(f"Unknown subject {subject}")

    _validate_target(subject, target_id)

    s = store()
    now = s.now()
    r = {
        "id": new_uuid(),
        "subject": subject,
        "target_id": target_id,
        "yes_votes": 0,
        "no_votes": 0,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "yes_voters": [],
        "no_voters": [],
    }
    s.insert("board_resolutions", r)
    return jsonify(success_object(serialize_board_resolution(r))), 201


@bp.route("/hoa/board-resolutions/<resolution_id>/votes", methods=["POST"])
@require_roles(["PresidentRole", "TreasurerRole", "SecretaryRole", "DirectorRole"])
def cast_resolution_vote(resolution_id: str):
    r = require("board_resolutions", resolution_id)
    body = get_json_body()
    vote = require_field(body, "vote")
    if vote not in {"YES", "NO"}:
        raise APIError("ERR_INVALID_STATE", "vote must be YES or NO", 409)

    # Trigger auto-FAIL by aging if applicable
    run_sweep()
    r = require("board_resolutions", resolution_id)

    if r["status"] != "PROPOSED":
        raise err_invalid_state(f"Resolution is {r['status']}, votes not accepted")

    s = store()
    voter = s.members.get(g.user_id)
    if voter is None or voter.get("board_role") not in BOARD_SEATS:
        raise err_invalid_state("Voter does not currently hold a board seat")

    # Segregation of duties for FINE_WAIVER: opener must not vote YES
    if r["subject"] == "FINE_WAIVER" and vote == "YES":
        violation = s.violations.get(r["target_id"])
        if violation is not None and violation.get("opened_by_member_id") == g.user_id:
            raise err_segregation("Member who opened the violation may not vote YES on its waiver")

    now = s.now()
    if vote == "YES":
        if g.user_id in r.get("yes_voters", []) or g.user_id in r.get("no_voters", []):
            raise err_invalid_state("Voter already cast a vote on this resolution")
        r["yes_voters"].append(g.user_id)
        r["yes_votes"] = r.get("yes_votes", 0) + 1
    else:
        if g.user_id in r.get("yes_voters", []) or g.user_id in r.get("no_voters", []):
            raise err_invalid_state("Voter already cast a vote on this resolution")
        r["no_voters"].append(g.user_id)
        r["no_votes"] = r.get("no_votes", 0) + 1

    bump_version(r, now)

    # Auto-transitions
    if r["yes_votes"] >= 3:
        r["status"] = "PASSED"
        bump_version(r, now)
    elif r["no_votes"] >= 2:
        r["status"] = "FAILED"
        bump_version(r, now)

    return jsonify(success_object(serialize_board_resolution(r))), 201
