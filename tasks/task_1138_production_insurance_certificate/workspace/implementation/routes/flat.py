"""Cross-production flat read aliases (reverse reachability views)."""

from flask import request

from db import db
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from util import get_or_404, paginate, serialize

ENDORSEMENT_ROLES = {"BrokerAgent", "ProductionManager", "UnderwriterAgent", "PlatformOperator"}
CLAIM_ROLES = {"BrokerAgent", "ProductionManager", "ClaimsAdjuster", "PlatformOperator"}
AUDIT_ROLES = {"BrokerAgent", "ProductionManager", "ExternalAuditor", "PlatformOperator"}
RENEWAL_ROLES = {"BrokerAgent", "ProductionManager", "UnderwriterAgent", "PlatformOperator"}


@bp.route("/cast-endorsements", methods=["GET"])
def flat_list_cast_endorsements():
    require_roles(ENDORSEMENT_ROLES)
    cm_id = request.args.get("cast_member_id")
    pol_id = request.args.get("policy_id")
    status = request.args.get("status")
    records = list(db.cast_endorsements.values())
    if cm_id is not None:
        records = [r for r in records if r["cast_member_id"] == cm_id]
    if pol_id is not None:
        records = [r for r in records if r["policy_id"] == pol_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/cast-endorsements/<id>", methods=["GET"])
def flat_get_cast_endorsement(id):
    require_roles(ENDORSEMENT_ROLES)
    rec = get_or_404(db.cast_endorsements, id, "CastEndorsement")
    return success_object(serialize(rec))


@bp.route("/claims", methods=["GET"])
def flat_list_claims():
    require_roles(CLAIM_ROLES)
    pol_id = request.args.get("policy_id")
    ctype = request.args.get("claim_type")
    status = request.args.get("status")
    records = list(db.claims.values())
    if pol_id is not None:
        records = [r for r in records if r["policy_id"] == pol_id]
    if ctype is not None:
        records = [r for r in records if r["claim_type"] == ctype]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/claims/<id>", methods=["GET"])
def flat_get_claim(id):
    require_roles(CLAIM_ROLES)
    rec = get_or_404(db.claims, id, "Claim")
    return success_object(serialize(rec))


@bp.route("/claim-events", methods=["GET"])
def flat_list_claim_events():
    require_roles(CLAIM_ROLES)
    claim_id = request.args.get("claim_id")
    records = list(db.claim_events.values())
    if claim_id is not None:
        records = [r for r in records if r["claim_id"] == claim_id]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/claim-events/<id>", methods=["GET"])
def flat_get_claim_event(id):
    require_roles(CLAIM_ROLES)
    rec = get_or_404(db.claim_events, id, "ClaimEvent")
    return success_object(serialize(rec))


@bp.route("/payroll-audits", methods=["GET"])
def flat_list_payroll_audits():
    require_roles(AUDIT_ROLES)
    pol_id = request.args.get("policy_id")
    status = request.args.get("status")
    records = list(db.payroll_audits.values())
    if pol_id is not None:
        records = [r for r in records if r["policy_id"] == pol_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/payroll-audits/<id>", methods=["GET"])
def flat_get_payroll_audit(id):
    require_roles(AUDIT_ROLES)
    rec = get_or_404(db.payroll_audits, id, "PayrollAudit")
    return success_object(serialize(rec))


@bp.route("/renewal-offers", methods=["GET"])
def flat_list_renewal_offers():
    require_roles(RENEWAL_ROLES)
    pol_id = request.args.get("policy_id")
    status = request.args.get("status")
    records = list(db.renewal_offers.values())
    if pol_id is not None:
        records = [r for r in records if r["policy_id"] == pol_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/renewal-offers/<id>", methods=["GET"])
def flat_get_renewal_offer(id):
    require_roles(RENEWAL_ROLES)
    rec = get_or_404(db.renewal_offers, id, "RenewalOffer")
    return success_object(serialize(rec))
