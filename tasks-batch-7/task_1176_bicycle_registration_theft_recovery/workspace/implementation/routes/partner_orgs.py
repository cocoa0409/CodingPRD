"""PartnerOrg onboarding and lifecycle (PRD §3.1)."""
from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import partner_org_view
from response import list_response, ok_object
from routes.common import field, load

bp = Blueprint("partner_orgs", __name__)

ORG_TYPES = {"LAW_ENFORCEMENT", "BIKE_SHOP", "CAMPUS"}
ORG_STATUSES = {"PENDING", "ACTIVE", "SUSPENDED", "REVOKED"}


@bp.post("/registry/partner-orgs")
@require_roles("Admin")
def create_partner_org():
    data = body()
    name = field(data, "name", "string", required=True)
    org_type = field(data, "org_type", "string", required=True, enum=ORG_TYPES)
    jurisdiction_code = field(data, "jurisdiction_code", "string", required=True)
    contact_email = field(data, "contact_email", "string", required=True)
    rec = db.new_record({
        "name": name,
        "org_type": org_type,
        "jurisdiction_code": jurisdiction_code,
        "contact_email": contact_email,
        "status": "PENDING",
    })
    db.partner_orgs[rec["id"]] = rec
    return ok_object(partner_org_view(rec), status=201)


@bp.get("/registry/partner-orgs")
@require_roles("Registrar", "Admin")
def list_partner_orgs():
    org_type = request.args.get("org_type")
    status = request.args.get("status")
    recs = list(db.partner_orgs.values())
    if org_type is not None:
        recs = [r for r in recs if r["org_type"] == org_type]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_response(recs, partner_org_view)


@bp.get("/registry/partner-orgs/<org_id>")
@require_roles("Partner", "Registrar", "Admin")
def read_partner_org(org_id):
    # A partner reads only its own organization.
    if g.role == "Partner" and g.user_id != org_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Partners may read only their own organization")
    rec = load(db.partner_orgs, org_id, "ERR_PARTNER_ORG_NOT_FOUND")
    return ok_object(partner_org_view(rec))


def _transition(org_id, allowed_from, target):
    rec = load(db.partner_orgs, org_id, "ERR_PARTNER_ORG_NOT_FOUND")
    if rec["status"] not in allowed_from:
        fail("ERR_PARTNER_ORG_NOT_ACTIVE",
             f"Cannot move organization from {rec['status']} to {target}")
    rec["status"] = target
    db.bump(rec)
    return ok_object(partner_org_view(rec))


@bp.post("/registry/partner-orgs/<org_id>/activate")
@require_roles("Admin")
def activate_partner_org(org_id):
    return _transition(org_id, {"PENDING", "SUSPENDED"}, "ACTIVE")


@bp.post("/registry/partner-orgs/<org_id>/suspend")
@require_roles("Admin")
def suspend_partner_org(org_id):
    return _transition(org_id, {"ACTIVE"}, "SUSPENDED")


@bp.post("/registry/partner-orgs/<org_id>/revoke")
@require_roles("Admin")
def revoke_partner_org(org_id):
    return _transition(org_id, {"ACTIVE", "SUSPENDED"}, "REVOKED")
