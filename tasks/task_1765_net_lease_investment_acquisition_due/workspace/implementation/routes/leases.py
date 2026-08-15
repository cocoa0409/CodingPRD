"""Lease routes (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import (body, opt_int, ref_not_found, req_dt, req_enum,
                           req_int, req_str)
from services import domain

bp = Blueprint("leases", __name__)

ALL_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
             "CapitalMarketsOfficer", "EscrowOfficer", "AssetManager", "PlatformAdmin")
LEASE_TYPES = {"NNN", "NN", "GROSS", "ABSOLUTE_NET"}


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>/leases", methods=["POST"])
def create_lease(deal_id, property_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    prop = domain.get_property_scoped(deal, property_id)
    data = body()
    tenant_id = req_str(data, "tenant_id")
    # Body FK existence (priority 4) before value constraints (priority 11).
    if tenant_id not in db.stores["tenants"]:
        ref_not_found("tenant_id references a non-existent tenant")
    lease_type = req_enum(data, "lease_type", LEASE_TYPES)
    annual_rent = req_int(data, "annual_base_rent_cents")
    commencement = req_dt(data, "lease_commencement_date")
    expiration = req_dt(data, "lease_expiration_date")
    if db.parse_dt(expiration) <= db.parse_dt(commencement):
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "lease_expiration_date must be later than lease_commencement_date", 400)
    renewal_options = opt_int(data, "renewal_options_count", 0)
    lease = db.make_record({
        "property_id": prop["id"],
        "tenant_id": tenant_id,
        "lease_type": lease_type,
        "annual_base_rent_cents": annual_rent,
        "lease_commencement_date": commencement,
        "lease_expiration_date": expiration,
        "remaining_term_months": None,
        "renewal_options_count": renewal_options,
        "rollover_risk_tier": None,
        "status": "DRAFT",
    })
    db.stores["leases"][lease["id"]] = lease
    return created(db.pub(lease))


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>/leases", methods=["GET"])
def list_leases(deal_id, property_id):
    require_role(*ALL_ROLES)
    deal = domain.get_deal(deal_id)
    prop = domain.get_property_scoped(deal, property_id)
    items = domain.leases_of_property(prop["id"])
    for param in ("status", "tenant_id"):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if str(l.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>/leases/<lease_id>", methods=["GET"])
def get_lease(deal_id, property_id, lease_id):
    require_role(*ALL_ROLES)
    deal = domain.get_deal(deal_id)
    prop = domain.get_property_scoped(deal, property_id)
    return ok(db.pub(domain.get_lease_scoped(prop, lease_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>/leases/<lease_id>/verify", methods=["POST"])
def verify_lease(deal_id, property_id, lease_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    prop = domain.get_property_scoped(deal, property_id)
    lease = domain.get_lease_scoped(prop, lease_id)
    if lease["status"] != "DRAFT":
        raise ApiError("ERR_LEASE_INVALID_STATE",
                       "verify requires lease status DRAFT", 409)
    tenant = db.stores["tenants"].get(lease["tenant_id"])
    if tenant is None or tenant["credit_assessment_status"] != "APPROVED":
        raise ApiError("ERR_TENANT_CREDIT_NOT_APPROVED",
                       "Tenant credit assessment must be APPROVED before lease verification", 422)
    expiry = db.parse_dt(lease["lease_expiration_date"])
    months = domain.compute_remaining_term_months(db.clock_now(), expiry)
    lease["remaining_term_months"] = months
    lease["rollover_risk_tier"] = domain.rollover_risk_tier(months)
    lease["status"] = "VERIFIED"
    bump(lease)
    return ok(db.pub(lease))
