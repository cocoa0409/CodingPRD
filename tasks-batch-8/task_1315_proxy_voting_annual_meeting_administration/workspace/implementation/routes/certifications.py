"""InspectorCertification endpoints (PRD §3.8).

Creation snapshots the FINAL quorum variant and the CERTIFIED tabulation
outcomes; signing enforces segregation of duties (signer != creator) and OCC
on the meeting version, then resolves ACTIVE proposals and advances the
meeting to RESULTS_CERTIFIED.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CERTIFICATION_NOT_DRAFT,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_INVALID_MEETING_STATE,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_UNRESOLVED_CHALLENGES,
)
from middleware import require_roles
from response import success_object, success_list
from services.quorum import compute_quorum
from services.serializers import serialize, serialize_list
from services.tabulation import compute_tabulation
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_field,
    sort_by_created_at,
)

bp = Blueprint("certifications", __name__)


def get_certification_or_404(cert_id: str) -> dict:
    cert = db.certifications.get(cert_id)
    if cert is None:
        raise_err(ERR_CERTIFICATION_NOT_FOUND, "InspectorCertification id does not exist")
    return cert


def _open_challenges_exist(meeting_id: str) -> bool:
    return any(
        c["meeting_id"] == meeting_id and c["status"] == "OPEN"
        for c in db.challenges.values()
    )


def _certified_outcome_map(meeting_id: str) -> dict:
    """proposal_id -> PASSED | FAILED per the CERTIFIED tabulation variant."""
    outcomes = {}
    for proposal in db.proposals.values():
        if proposal["meeting_id"] == meeting_id and proposal["status"] == "ACTIVE":
            result = compute_tabulation(proposal, "CERTIFIED")
            outcomes[proposal["id"]] = (
                "PASSED" if result["projected_outcome"] == "PASS" else "FAILED"
            )
    return outcomes


@bp.route("/proxy/inspector-certifications", methods=["POST"])
@require_roles("InspectorOfElection")
def create_certification(_user_id: str, _role: str):
    body = get_json_body()
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    if meeting["status"] != "MEETING_HELD":
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Certification creation requires meeting MEETING_HELD",
        )
    if _open_challenges_exist(meeting_id):
        raise_err(
            ERR_UNRESOLVED_CHALLENGES,
            "Certification creation requires zero OPEN challenges",
        )

    # A new draft supersedes any existing DRAFT certification of the meeting.
    for cert in db.certifications.values():
        if cert["meeting_id"] == meeting_id and cert["status"] == "DRAFT":
            cert["status"] = "SUPERSEDED"
            db.touch(cert)

    # Snapshot the final state of play.
    final_quorum = compute_quorum(meeting, "FINAL")
    cert = {
        "meeting_id": meeting_id,
        "created_by_user_id": _user_id,
        "final_quorum_met": final_quorum["quorum_met"],
        "final_quorum_pct_bp": final_quorum["quorum_pct_bp"],
        "outcomes": _certified_outcome_map(meeting_id),
        "status": "DRAFT",
    }
    db.stamp_new(cert)
    db.certifications[cert["id"]] = cert
    return success_object(serialize(cert), 201)


@bp.route("/proxy/inspector-certifications", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def list_certifications(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.certifications.values()))
    items = apply_filters(items, ["meeting_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/inspector-certifications/<cert_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def get_certification(cert_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_certification_or_404(cert_id)))


@bp.route("/proxy/inspector-certifications/<cert_id>/sign", methods=["POST"])
@require_roles("InspectorOfElection")
def sign_certification(cert_id: str, _user_id: str, _role: str):
    cert = get_certification_or_404(cert_id)
    # State (precedence 4).
    if cert["status"] != "DRAFT":
        raise_err(
            ERR_CERTIFICATION_NOT_DRAFT,
            "Only a DRAFT certification may be signed",
        )
    meeting = db.meetings.get(cert["meeting_id"])
    # Segregation of duties (precedence 5).
    if _user_id == cert["created_by_user_id"]:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "Certification signer must differ from its creator",
        )
    # Domain (precedence 8): no unresolved challenges.
    if _open_challenges_exist(cert["meeting_id"]):
        raise_err(
            ERR_UNRESOLVED_CHALLENGES,
            "Certification signing requires zero OPEN challenges",
        )
    # OCC (precedence 9): expected_meeting_version is a required input (§2.7).
    body = get_json_body()
    expected = optional_field(body, "expected_meeting_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_meeting_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_meeting_version must be an integer")
    if meeting is None or expected != meeting["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_meeting_version does not match the meeting's current version",
        )

    cert["status"] = "SIGNED"
    db.touch(cert)
    # Resolve every ACTIVE proposal per its CERTIFIED tabulation outcome.
    for proposal in db.proposals.values():
        if proposal["meeting_id"] == cert["meeting_id"] and proposal["status"] == "ACTIVE":
            result = compute_tabulation(proposal, "CERTIFIED")
            proposal["status"] = (
                "PASSED" if result["projected_outcome"] == "PASS" else "FAILED"
            )
            db.touch(proposal)
    meeting["status"] = "RESULTS_CERTIFIED"
    db.touch(meeting)
    return success_object(serialize(cert))
