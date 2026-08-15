"""DropShipLink endpoints (PRD §3.6)."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role
from response import created, ok

bp = Blueprint("drop_ship_links", __name__)

CO = "ComplianceOfficer"
READ_ROLES = ("TenantAdmin", "ComplianceOfficer", "Auditor")


@bp.route("/tenants/<tid>/drop_ship_links", methods=["POST"])
def create_link(tid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    body = request.get_json(silent=True) or {}
    # Priority 4: body FKs resolve within the tenant.
    retailer_id = body.get("retailer_customer_id")
    retailer = db.stores["customers"].get(retailer_id)
    if not retailer or retailer["tenant_id"] != tenant["id"]:
        raise ApiError(
            "ERR_CROSS_TENANT_REFERENCE",
            "retailer_customer_id does not resolve to a record of this tenant",
            404,
        )
    cert_id = body.get("resale_certificate_id")
    cert = db.stores["certificates"].get(cert_id)
    if not cert or cert["tenant_id"] != tenant["id"]:
        raise ApiError(
            "ERR_CROSS_TENANT_REFERENCE",
            "resale_certificate_id does not resolve to a record of this tenant",
            404,
        )
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "retailer_customer_id": retailer_id,
        "ship_to_state": body.get("ship_to_state"),
        "resale_certificate_id": cert_id,
        "is_out_of_state_resale_accepted": None,
        "status": "PENDING_VERIFICATION",
    })
    db.stores["drop_ship_links"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/drop_ship_links/<lid>", methods=["GET"])
def get_link(tid, lid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    link = domain.get_scoped("drop_ship_links", lid, tenant["id"])
    return ok(db.pub(link))


@bp.route("/tenants/<tid>/drop_ship_links/<lid>/verify", methods=["POST"])
def verify_link(tid, lid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    link = domain.get_scoped("drop_ship_links", lid, tenant["id"])
    if link["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a PENDING_VERIFICATION link can be verified", 409)
    # Priority 17: resale certificate must be APPROVED.
    cert = db.stores["certificates"].get(link["resale_certificate_id"])
    if not cert or cert["status"] != "APPROVED":
        raise ApiError("ERR_RESALE_CERT_NOT_APPROVED", "Resale certificate is not APPROVED", 409)
    # Priority 18: state alignment when the jurisdiction disallows
    # out-of-state resale.
    rule = domain.find_rule(tenant["id"], link["ship_to_state"])
    allows = bool(rule and rule["allows_drop_ship_resale"])
    if not allows and cert["ship_to_state"] != link["ship_to_state"]:
        raise ApiError(
            "ERR_DROP_SHIP_STATE_MISMATCH",
            "Resale certificate ship_to_state must equal the link's ship_to_state when the jurisdiction disallows out-of-state resale",
            422,
        )
    link["is_out_of_state_resale_accepted"] = allows
    link["status"] = "VERIFIED"
    bump(link)
    return ok(db.pub(link))


@bp.route("/tenants/<tid>/drop_ship_links/<lid>/reject", methods=["POST"])
def reject_link(tid, lid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    link = domain.get_scoped("drop_ship_links", lid, tenant["id"])
    if link["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a PENDING_VERIFICATION link can be rejected", 409)
    link["status"] = "REJECTED"
    bump(link)
    return ok(db.pub(link))
