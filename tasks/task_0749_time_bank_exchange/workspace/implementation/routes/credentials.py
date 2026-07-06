"""VerificationCredential routes — peer verification."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ADMIN
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                    ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE,
                    ERR_VERIFIER_INELIGIBLE)
from response import envelope_object, envelope_array
from services import validators, pagination, balance
from services.serializers import credential_dto

bp = Blueprint("credentials", __name__)

CRED_TYPES = {"ID_CHECK", "SKILL_ATTEST", "REFERENCE_ATTEST"}
VERIFIER_TIERS = {"TRUSTED", "ANCHOR"}


@bp.route("/credentials", methods=["POST"])
def create_credential():
    user_id, _ = require_role({ROLE_MEMBER})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, [
        "subject_member_id", "verifier_member_id", "credential_type", "evidence_url"
    ])
    subject_id = validators.require_str(payload, "subject_member_id")
    verifier_id = validators.require_str(payload, "verifier_member_id")
    ctype = validators.require_enum(payload, "credential_type", CRED_TYPES)
    evidence = validators.require_str(payload, "evidence_url")
    skill_code = validators.optional_str(payload, "skill_code")

    if ctype == "SKILL_ATTEST":
        if not skill_code:
            raise_err(ERR_INVALID_REQUEST, "skill_code required for SKILL_ATTEST")
    else:
        if skill_code is not None:
            raise_err(ERR_INVALID_REQUEST, "skill_code must be absent for non-SKILL_ATTEST")

    # existence
    if db.members.get(subject_id) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "subject member not found")
    if db.members.get(verifier_id) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "verifier member not found")
    # ownership: subject must be acting member. PRD §2.9: submission is by the
    # subject. The subject-not-verifier rule is enforced only on verify/reject/
    # request-revision (§2.7), not at submission time.
    if subject_id != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be credential.subject_member_id")

    c = {
        "subject_member_id": subject_id,
        "verifier_member_id": verifier_id,
        "credential_type": ctype,
        "skill_code": skill_code,
        "evidence_url": evidence,
        "status": "SUBMITTED",
        "revision_round": 0,
    }
    db.stamp_new(c)
    db.verification_credentials[c["id"]] = c
    return envelope_object(credential_dto(c), status=201)


@bp.route("/credentials", methods=["GET"])
def list_credentials():
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.verification_credentials.values())
    for k in ("subject_member_id", "verifier_member_id", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x.get(k) == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([credential_dto(x) for x in window], limit, offset, total)


@bp.route("/credentials/<cid>", methods=["GET"])
def get_credential(cid):
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    c = db.verification_credentials.get(cid)
    if c is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Credential not found")
    return envelope_object(credential_dto(c), status=200)


def _verifier_gate(c, actor_id, require_tier: bool):
    """§1.4 priority 13 verifier-eligibility gate for verify/reject/request-revision.
    For a bare 'is verifier' ownership check use the ownership check separately."""
    if c["verifier_member_id"] != actor_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be credential.verifier_member_id")
    if c["subject_member_id"] == actor_id:
        raise_err(ERR_VERIFIER_INELIGIBLE, "verifier cannot be credential's subject")
    if require_tier:
        actor = db.members.get(actor_id)
        if actor is None:
            raise_err(ERR_VERIFIER_INELIGIBLE, "acting member not found")
        # ensure snapshot fresh
        balance.recompute_member_snapshot(actor_id, bump_version=False)
        if actor["trust_tier"] not in VERIFIER_TIERS:
            raise_err(ERR_VERIFIER_INELIGIBLE, "verifier trust_tier must be TRUSTED or ANCHOR")


@bp.route("/credentials/<cid>/verify", methods=["POST"])
def verify_credential(cid):
    user_id, _ = require_role({ROLE_MEMBER})
    c = db.verification_credentials.get(cid)
    if c is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Credential not found")
    if c["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Credential.status must be SUBMITTED")
    _verifier_gate(c, user_id, require_tier=True)
    c["status"] = "VERIFIED"
    db.touch(c)
    # subject's counters / trust / version
    balance.recompute_member_snapshot(c["subject_member_id"], bump_version=True)
    return envelope_object(credential_dto(c), status=200)


@bp.route("/credentials/<cid>/reject", methods=["POST"])
def reject_credential(cid):
    user_id, _ = require_role({ROLE_MEMBER})
    c = db.verification_credentials.get(cid)
    if c is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Credential not found")
    if c["status"] not in ("SUBMITTED", "REVISION_REQUESTED"):
        raise_err(ERR_INVALID_STATE, "Credential.status must be SUBMITTED or REVISION_REQUESTED")
    # Per PRD §3.1: the reject from REVISION_REQUESTED does not require the
    # trust-tier gate; the tier gate only applies to transitions out of
    # SUBMITTED.
    require_tier = (c["status"] == "SUBMITTED")
    _verifier_gate(c, user_id, require_tier=require_tier)
    c["status"] = "REJECTED"
    db.touch(c)
    return envelope_object(credential_dto(c), status=200)


@bp.route("/credentials/<cid>/request-revision", methods=["POST"])
def request_revision(cid):
    user_id, _ = require_role({ROLE_MEMBER})
    c = db.verification_credentials.get(cid)
    if c is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Credential not found")
    if c["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Credential.status must be SUBMITTED")
    if c["revision_round"] >= 2:
        raise_err(ERR_INVALID_STATE, "revision_round cap (2) reached")
    _verifier_gate(c, user_id, require_tier=True)
    c["status"] = "REVISION_REQUESTED"
    db.touch(c)
    return envelope_object(credential_dto(c), status=200)


@bp.route("/credentials/<cid>/resubmit", methods=["POST"])
def resubmit(cid):
    user_id, _ = require_role({ROLE_MEMBER})
    c = db.verification_credentials.get(cid)
    if c is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Credential not found")
    if c["status"] != "REVISION_REQUESTED":
        raise_err(ERR_INVALID_STATE, "Credential.status must be REVISION_REQUESTED")
    if c["revision_round"] >= 2:
        raise_err(ERR_INVALID_STATE, "revision_round cap (2) reached")
    if c["subject_member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must be credential.subject_member_id")
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["evidence_url"])
    c["evidence_url"] = validators.require_str(payload, "evidence_url")
    c["status"] = "SUBMITTED"
    c["revision_round"] += 1
    db.touch(c)
    return envelope_object(credential_dto(c), status=200)
