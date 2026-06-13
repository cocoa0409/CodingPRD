"""Peer reviewers, credentialing files, votes, and finalize."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth, require_role
from response import success_array, success_object
from services.calc import (
    compute_recred_due_date,
    compute_tally,
)
from services.common import (
    parse_pagination,
    paginate,
    require_body,
    sort_by_created,
)
from services.lookups import (
    get_credentialing_file,
    get_peer_reviewer,
    get_provider,
    get_vote,
)
from services.model import make_record, serialize, touch

bp = Blueprint("peerreview", __name__)


# ---------------------------------------------------------------------------
# Peer reviewers
# ---------------------------------------------------------------------------
@bp.route("/peer-reviewers", methods=["POST"])
def create_reviewer():
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "MedicalDirector"})
    body = require_body()

    org_id = body.get("org_id")
    if not isinstance(org_id, str) or org_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "org_id is required.")
    # org existence is a body FK -> priority 4, before other field validation
    if org_id not in store.orgs:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "org_id does not reference an existing organization.")

    user_id = body.get("user_id")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "user_id is required.")
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or full_name.strip() == "":
        raise err("ERR_INVALID_REQUEST", "full_name is required.")
    vote_weight = body.get("vote_weight", 1)
    if not isinstance(vote_weight, int) or isinstance(vote_weight, bool) or vote_weight < 1:
        raise err("ERR_INVALID_REQUEST", "vote_weight must be a positive integer.")

    rec = make_record("peer_reviewers", {
        "org_id": org_id,
        "user_id": user_id,
        "full_name": full_name,
        "vote_weight": vote_weight,
    })
    return success_object(serialize(rec), 201)


@bp.route("/peer-reviewers", methods=["GET"])
def list_reviewers():
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "MedicalDirector", "CredentialingSpecialist"})
    org_id = request.args.get("org_id")
    limit, offset = parse_pagination()
    rows = [r for r in store.peer_reviewers.values()
            if org_id is None or r["org_id"] == org_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/peer-reviewers/<rid>", methods=["GET"])
def get_reviewer_route(rid):
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "MedicalDirector", "CredentialingSpecialist"})
    rec = get_peer_reviewer(rid)
    return success_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Credentialing files
# ---------------------------------------------------------------------------
@bp.route("/providers/<rid>/credentialing-files", methods=["POST"])
def create_file(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector"})
    prov = get_provider(rid)

    rec = make_record("credentialing_files", {
        "provider_id": rid,
        "review_status": "ASSEMBLING",
        "opened_at": None,
        "chair_user_id": None,
        "tally_yes": 0,
        "tally_no": 0,
        "decision_reason": None,
    })
    return success_object(serialize(rec), 201)


@bp.route("/providers/<rid>/credentialing-files", methods=["GET"])
def list_provider_files(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "ComplianceOfficer", "SystemAdmin"})
    get_provider(rid)
    limit, offset = parse_pagination()
    rows = [f for f in store.credentialing_files.values() if f["provider_id"] == rid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/credentialing-files/<rid>", methods=["GET"])
def get_file_route(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "ComplianceOfficer", "SystemAdmin"})
    rec = get_credentialing_file(rid)
    return success_object(serialize(rec), 200)


@bp.route("/credentialing-files/<rid>/open-review", methods=["POST"])
def open_review(rid):
    user_id, role = require_auth()
    require_role(role, {"MedicalDirector"})
    file = get_credentialing_file(rid)
    prov = store.providers.get(file["provider_id"])

    if file["review_status"] != "ASSEMBLING":
        raise err("ERR_FILE_NOT_ASSEMBLING", "File is not ASSEMBLING.")
    if prov is None or prov["application_status"] != "READY_FOR_REVIEW":
        raise err("ERR_PROVIDER_NOT_READY", "Provider is not READY_FOR_REVIEW.")
    if prov["credentialing_status"] == "EXCLUDED":
        raise err("ERR_PROVIDER_EXCLUDED", "Provider is EXCLUDED.")

    file["review_status"] = "UNDER_REVIEW"
    file["opened_at"] = store.orgs[prov["org_id"]]["current_utc"]
    file["chair_user_id"] = user_id
    touch(file)
    return success_object(serialize(file), 200)


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------
@bp.route("/credentialing-files/<rid>/cast-vote", methods=["POST"])
def cast_vote(rid):
    user_id, role = require_auth()
    require_role(role, {"MedicalDirector", "PeerReviewer"})
    file = get_credentialing_file(rid)
    body = require_body()

    reviewer_id = body.get("reviewer_id")
    if not isinstance(reviewer_id, str) or reviewer_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "reviewer_id is required.")
    # body FK: reviewer must exist (priority 4, before other field validation)
    reviewer = store.peer_reviewers.get(reviewer_id)
    prov = store.providers.get(file["provider_id"])
    if reviewer is None:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "reviewer_id does not reference an existing reviewer.")

    ballot = body.get("ballot")
    if ballot not in ("YES", "NO", "ABSTAIN"):
        raise err("ERR_INVALID_REQUEST", "ballot must be YES, NO, or ABSTAIN.")
    comment = body.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise err("ERR_INVALID_REQUEST", "comment must be a string.")

    # state: file must be UNDER_REVIEW
    if file["review_status"] != "UNDER_REVIEW":
        raise err("ERR_FILE_NOT_UNDER_REVIEW", "File is not UNDER_REVIEW.")

    # priority 8: reviewer org must match the file's provider org
    if prov is None or reviewer["org_id"] != prov["org_id"]:
        raise err("ERR_REVIEWER_ORG_MISMATCH", "Reviewer belongs to a different org than the file's provider.")

    # priority 9: segregation of duties - caster must not be initiated_by_user_id
    if prov.get("initiated_by_user_id") is not None and user_id == prov["initiated_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Application initiator may not vote on this provider's review.")

    # priority 10: a reviewer may cast at most one vote per file
    for v in store.peer_review_votes.values():
        if v["credentialing_file_id"] == rid and v["reviewer_id"] == reviewer_id:
            raise err("ERR_DUPLICATE_VOTE", "Reviewer has already voted on this file.")

    rec = make_record("peer_review_votes", {
        "credentialing_file_id": rid,
        "reviewer_id": reviewer_id,
        "voter_user_id": user_id,
        "ballot": ballot,
        "comment": comment,
    })

    # recompute tally and write back onto the file (bumps file version)
    tally_yes, tally_no, _ = compute_tally(file)
    file["tally_yes"] = tally_yes
    file["tally_no"] = tally_no
    touch(file)

    return success_object(serialize(rec), 201)


@bp.route("/credentialing-files/<rid>/votes", methods=["GET"])
def list_file_votes(rid):
    _, role = require_auth()
    require_role(role, {"MedicalDirector", "CredentialingSpecialist",
                        "ComplianceOfficer", "SystemAdmin"})
    get_credentialing_file(rid)
    limit, offset = parse_pagination()
    rows = [v for v in store.peer_review_votes.values()
            if v["credentialing_file_id"] == rid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/votes/<rid>", methods=["GET"])
def get_vote_route(rid):
    _, role = require_auth()
    require_role(role, {"MedicalDirector", "CredentialingSpecialist",
                        "ComplianceOfficer", "SystemAdmin"})
    rec = get_vote(rid)
    return success_object(serialize(rec), 200)


@bp.route("/votes", methods=["GET"])
def list_votes():
    _, role = require_auth()
    require_role(role, {"MedicalDirector", "CredentialingSpecialist",
                        "ComplianceOfficer", "SystemAdmin"})
    reviewer_id = request.args.get("reviewer_id")
    file_id = request.args.get("credentialing_file_id")
    limit, offset = parse_pagination()
    rows = []
    for v in store.peer_review_votes.values():
        if reviewer_id is not None and v["reviewer_id"] != reviewer_id:
            continue
        if file_id is not None and v["credentialing_file_id"] != file_id:
            continue
        rows.append(v)
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------
@bp.route("/credentialing-files/<rid>/finalize", methods=["POST"])
def finalize_file(rid):
    _, role = require_auth()
    require_role(role, {"MedicalDirector"})
    file = get_credentialing_file(rid)
    body = require_body()

    decision = body.get("decision")
    if decision not in ("APPROVE", "DENY"):
        raise err("ERR_INVALID_REQUEST", "decision must be APPROVE or DENY.")
    expected = body.get("expected_credentialing_file_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_credentialing_file_version is required and must be an integer.")
    decision_reason = body.get("decision_reason")
    if decision_reason is not None and not isinstance(decision_reason, str):
        raise err("ERR_INVALID_REQUEST", "decision_reason must be a string.")

    # priority 6: OCC version check runs BEFORE any state/business check (PRD §2.10)
    if expected != file["version"]:
        raise err("ERR_STALE_VERSION", "expected_credentialing_file_version does not match current version.")

    # priority 7: state
    if file["review_status"] != "UNDER_REVIEW":
        raise err("ERR_FILE_NOT_UNDER_REVIEW", "File is not UNDER_REVIEW.")

    # priority 13: quorum (>= 3 non-ABSTAIN votes)
    non_abstain = [v for v in store.peer_review_votes.values()
                   if v["credentialing_file_id"] == rid and v["ballot"] in ("YES", "NO")]
    if len(non_abstain) < 3:
        raise err("ERR_QUORUM_NOT_MET", "Fewer than 3 non-ABSTAIN votes.")

    # priority 14: decision must match tally outcome
    _, _, outcome = compute_tally(file)
    if decision == "APPROVE" and outcome != "YES":
        raise err("ERR_REVIEW_OUTCOME_MISMATCH", "APPROVE requires a YES outcome.")
    if decision == "DENY" and outcome != "NO":
        raise err("ERR_REVIEW_OUTCOME_MISMATCH", "DENY requires a NO outcome.")

    if decision_reason is not None:
        file["decision_reason"] = decision_reason

    prov = store.providers.get(file["provider_id"])

    if decision == "APPROVE":
        file["review_status"] = "APPROVED"
        touch(file)
        _clear_provider(prov, file)
    else:
        file["review_status"] = "DENIED"
        touch(file)
        _deny_provider(prov)

    return success_object(serialize(file), 200)


def _clear_provider(prov, file):
    """On APPROVE: provider cleared; recred loop advances; due date computed."""
    if prov is None:
        return
    org = store.orgs.get(prov["org_id"])
    was_recredentialing = prov["recred_state"] == "IN_RECREDENTIALING"

    prov["credentialing_status"] = "CLEARED"
    prov["credentialing_completed_date"] = org["current_utc"]
    if prov.get("original_completed_date") is None:
        prov["original_completed_date"] = org["current_utc"]
    prov["recred_state"] = "CURRENT"
    # anniversary variant when this clearing closes a re-credentialing cycle
    prov["recred_due_date"] = compute_recred_due_date(prov, org, anniversary=was_recredentialing)
    touch(prov)


def _deny_provider(prov):
    """On DENY: provider CONDITIONAL; REQUESTED/SUBMITTED enrollments -> REJECTED."""
    if prov is None:
        return
    prov["credentialing_status"] = "CONDITIONAL"
    touch(prov)
    for enr in store.payer_enrollments.values():
        if enr["provider_id"] == prov["id"] and enr["status"] in ("REQUESTED", "SUBMITTED"):
            enr["status"] = "REJECTED"
            touch(enr)
