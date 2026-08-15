"""RemediationAction endpoints (PRD §3.9)."""

from flask import Blueprint, g, request

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list

bp = Blueprint("remediation_actions", __name__)

CO = "ComplianceOfficer"
READ_ROLES = ("TenantAdmin", "ComplianceOfficer", "Auditor")


@bp.route("/tenants/<tid>/remediation_actions/<rid>", methods=["GET"])
def get_action(tid, rid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    action = domain.get_scoped("remediation_actions", rid, tenant["id"])
    return ok(db.pub(action))


@bp.route("/tenants/<tid>/audit_samples/<sid>/remediation_actions", methods=["GET"])
def list_actions(tid, sid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    sample = domain.get_scoped("audit_samples", sid, tenant["id"])
    items = [a for a in db.stores["remediation_actions"].values() if a["sample_id"] == sample["id"]]
    items.sort(key=lambda a: a["_seq"])
    return ok_list([db.pub(a) for a in items])


@bp.route("/tenants/<tid>/audit_samples/<sid>/remediation_actions", methods=["POST"])
def create_action(tid, sid):
    require_role("Auditor")
    tenant = domain.get_tenant(tid)
    sample = domain.get_scoped("audit_samples", sid, tenant["id"])
    body = request.get_json(silent=True) or {}
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "sample_id": sample["id"],
        "customer_id": sample["customer_id"],
        "action_type": body.get("action_type"),
        "assigned_to_user_id": body.get("assigned_to_user_id"),
        "resolved_by_user_id": None,
        "assessment_amount_cents": body.get("assessment_amount_cents"),
        "status": "OPEN",
    })
    db.stores["remediation_actions"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/remediation_actions/<rid>/begin", methods=["POST"])
def begin_action(tid, rid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    action = domain.get_scoped("remediation_actions", rid, tenant["id"])
    if action["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an OPEN or ESCALATED action can be begun", 409)
    # Assignee-only: a different actor fails as an invalid transition.
    if g.user_id != action["assigned_to_user_id"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only the assigned compliance officer may begin this action", 409)
    action["status"] = "IN_PROGRESS"
    bump(action)
    return ok(db.pub(action))


@bp.route("/tenants/<tid>/remediation_actions/<rid>/escalate", methods=["POST"])
def escalate_action(tid, rid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    action = domain.get_scoped("remediation_actions", rid, tenant["id"])
    if action["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an IN_PROGRESS action can be escalated", 409)
    action["status"] = "ESCALATED"
    bump(action)
    return ok(db.pub(action))


@bp.route("/tenants/<tid>/remediation_actions/<rid>/resolve", methods=["POST"])
def resolve_action(tid, rid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    action = domain.get_scoped("remediation_actions", rid, tenant["id"])
    # Priority 5: RESOLVED is reached only from IN_PROGRESS.
    if action["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an IN_PROGRESS action can be resolved", 409)
    sample = db.stores["audit_samples"].get(action["sample_id"])
    campaign = db.stores["audit_campaigns"].get(sample["campaign_id"]) if sample else None
    body = request.get_json(silent=True) or {}
    # Priority 6: OCC on the parent AuditCampaign (PRD §2.8).
    expected = body.get("expected_campaign_version")
    if campaign is not None and expected is not None and expected != campaign["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_campaign_version does not match the campaign's current version", 412)
    if action["action_type"] == "ASSESS_TAX":
        # Priority 9: the assignee may never close their own assessment.
        if g.user_id == action["assigned_to_user_id"]:
            raise ApiError(
                "ERR_SOD_ASSESSOR_IS_RESOLVER",
                "An ASSESS_TAX action may not be resolved by the officer it is assigned to",
                409,
            )
        # Priority 28: positive assessment amount.
        amount = action.get("assessment_amount_cents")
        if not isinstance(amount, int) or amount <= 0:
            raise ApiError(
                "ERR_ASSESSMENT_AMOUNT_INVALID",
                "Resolving an ASSESS_TAX action requires assessment_amount_cents > 0",
                422,
            )
    elif action["action_type"] == "COLLECT_NEW_CERT":
        # A new certificate for the same customer and state must be APPROVED.
        cert = db.stores["certificates"].get(sample["certificate_id"]) if sample else None
        target_state = cert["ship_to_state"] if cert else None
        found = any(
            c["customer_id"] == action["customer_id"]
            and c["ship_to_state"] == target_state
            and c["status"] == "APPROVED"
            and c["id"] != (sample["certificate_id"] if sample else None)
            for c in db.stores["certificates"].values()
            if c["tenant_id"] == tenant["id"]
        )
        if not found:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Resolving a COLLECT_NEW_CERT action requires a new APPROVED certificate for the customer and state",
                409,
            )
    action["status"] = "RESOLVED"
    action["resolved_by_user_id"] = g.user_id
    bump(action)
    if campaign is not None:
        bump(campaign)
    # When every FAILED sample for the customer has a RESOLVED remediation,
    # the customer moves to REMEDIATED and the tenant posture recomputes.
    cust = db.stores["customers"].get(action["customer_id"])
    if cust:
        domain.recompute_audit_standing(cust)
        bump(cust)
    domain.recompute_audit_posture(tenant)
    return ok(db.pub(action))
