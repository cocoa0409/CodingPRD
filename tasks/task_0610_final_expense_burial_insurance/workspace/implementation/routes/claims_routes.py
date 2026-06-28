"""Claim and DeathCertificate endpoints (PRD §3.11-§3.14)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import get_now, parse_iso
from errors import err
from helpers import get_body, require_fields, serialize, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success
from services import claims as claims_svc

bp = Blueprint("claims", __name__)

MANNERS = {"NATURAL", "ACCIDENTAL"}
CAUSES = {"ILLNESS", "ACCIDENT", "HOMICIDE", "SUICIDE", "UNDETERMINED"}


def _policy_in_force(policy):
    """ACTIVE, or LAPSED still inside its reinstatement window (PRD §3.11)."""
    if policy["coverage_status"] == "ACTIVE":
        return True
    if policy["coverage_status"] == "LAPSED":
        plan = db.product_plans.get(policy["product_plan_id"])
        lapse_instant = parse_iso(policy.get("_lapse_instant"))
        if lapse_instant is None:
            return False
        window_end = lapse_instant + timedelta(days=plan["reinstatement_window_days"])
        return get_now() <= window_end
    return False


@bp.route("/claims", methods=["POST"])
def file_claim():
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer", "PolicyAdmin"})
    body = get_body()
    require_fields(body, ["policy_id", "date_of_death", "manner_of_death"])
    policy = db.policies.get(body["policy_id"])
    if policy is None:
        raise err("ERR_NOT_FOUND", "Policy not found")
    if body["manner_of_death"] not in MANNERS:
        raise err("ERR_VALIDATION", "Invalid manner_of_death")
    dod = parse_iso(body["date_of_death"])
    if dod is None:
        raise err("ERR_VALIDATION", "date_of_death must be a valid ISO 8601 date")

    # Ordered: in-force coverage check (priority 7) before death-before-issue (priority 8).
    if not _policy_in_force(policy):
        raise err("ERR_POLICY_NOT_IN_FORCE", "Policy coverage is not in force")
    if dod < parse_iso(policy["issue_date"]):
        raise err("ERR_DEATH_BEFORE_ISSUE", "date_of_death precedes issue_date")

    claim = {
        "policy_id": policy["id"],
        "date_of_death": body["date_of_death"],
        "manner_of_death": body["manner_of_death"],
        "gross_benefit_cents": 0,
        "loan_offset_cents": 0,
        "net_payout_cents": 0,
        "payout_basis": None,
        "denial_reason": None,
        "status": "FILED",
    }
    with db.LOCK:
        db.stamp_full(claim)
        db.claims[claim["id"]] = claim
    return success(serialize(claim), status=201, response_type="object")


@bp.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer", "PolicyAdmin", "Policyholder"})
    claim = db.claims.get(claim_id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    with db.LOCK:
        claims_svc.recompute_provisional(claim)
    return success(serialize(claim), status=200, response_type="object")


@bp.route("/claims", methods=["GET"])
def list_claims():
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer", "PolicyAdmin"})
    items = list(db.claims.values())
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    if policy_id:
        items = [c for c in items if c["policy_id"] == policy_id]
    if status:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(c) for c in page], status=200, response_type="array", pagination=meta)


@bp.route("/claims/<claim_id>/death-certificate", methods=["POST"])
def attach_certificate(claim_id):
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer", "PolicyAdmin"})
    claim = db.claims.get(claim_id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    body = get_body()
    require_fields(body, ["certificate_number", "certified_cause", "verified"])
    if body["certified_cause"] not in CAUSES:
        raise err("ERR_VALIDATION", "Invalid certified_cause")
    if not isinstance(body["verified"], bool):
        raise err("ERR_VALIDATION", "verified must be a boolean")

    certificate = {
        "claim_id": claim_id,
        "certificate_number": body["certificate_number"],
        "certified_cause": body["certified_cause"],
        "verified": body["verified"],
    }
    with db.LOCK:
        db.stamp_light(certificate)
        db.death_certificates[certificate["id"]] = certificate
    return success(serialize(certificate), status=201, response_type="object")


@bp.route("/death-certificates/<cert_id>", methods=["GET"])
def get_certificate(cert_id):
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer", "PolicyAdmin"})
    cert = db.death_certificates.get(cert_id)
    if cert is None:
        raise err("ERR_NOT_FOUND", "DeathCertificate not found")
    return success(serialize(cert), status=200, response_type="object")


@bp.route("/death-certificates", methods=["GET"])
def list_certificates():
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer", "PolicyAdmin"})
    items = list(db.death_certificates.values())
    claim_id = request.args.get("claim_id")
    if claim_id:
        items = [c for c in items if c["claim_id"] == claim_id]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(c) for c in page], status=200, response_type="array", pagination=meta)


@bp.route("/claims/<claim_id>/start-review", methods=["POST"])
def start_review(claim_id):
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer"})
    claim = db.claims.get(claim_id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    with db.LOCK:
        claims_svc.start_review(claim)
    return success(serialize(claim), status=200, response_type="object")


@bp.route("/claims/<claim_id>/contest", methods=["POST"])
def contest_claim(claim_id):
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer"})
    claim = db.claims.get(claim_id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    with db.LOCK:
        claims_svc.contest(claim)
    return success(serialize(claim), status=200, response_type="object")


@bp.route("/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer"})
    claim = db.claims.get(claim_id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    with db.LOCK:
        claims_svc.approve(claim)
    return success(serialize(claim), status=200, response_type="object")


@bp.route("/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    _, role = get_identity()
    require_roles(role, {"ClaimsExaminer"})
    claim = db.claims.get(claim_id)
    if claim is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    body = get_body()
    denial_reason = body.get("denial_reason")
    with db.LOCK:
        claims_svc.deny(claim, denial_reason)
    return success(serialize(claim), status=200, response_type="object")
