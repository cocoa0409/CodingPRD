"""Property, LeaseSpace, Tenant, Lease endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_tenant_ownership
from response import success_object, success_created, success_list
from errors import not_found, invalid_request, invalid_state
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_int, is_str, parse_iso8601, to_iso_z,
)

bp = Blueprint("portfolio", __name__)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@bp.route("/api/properties", methods=["POST"])
def create_property():
    require_roles("LandlordPM")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "address"])
    if not is_str(body["name"]):
        raise invalid_request("name must be a string")
    if not is_str(body["address"]):
        raise invalid_request("address must be a string")
    max_concurrent = body.get("max_concurrent_construction_projects", 2)
    if not is_int(max_concurrent) or max_concurrent < 1:
        raise invalid_request("max_concurrent_construction_projects must be integer >= 1")

    rec = make_common_fields()
    rec.update({
        "name": body["name"],
        "address": body["address"],
        "max_concurrent_construction_projects": max_concurrent,
    })
    store.properties[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/properties/<id>", methods=["GET"])
def get_property(id):
    require_roles("LandlordPM", "LandlordApprover", "BuildingEngineer")
    rec = store.properties.get(id)
    if not rec:
        raise not_found("Property not found")
    return success_object(rec)


@bp.route("/api/properties/<id>/lease-spaces", methods=["POST"])
def create_lease_space(id):
    require_roles("LandlordPM")
    prop = store.properties.get(id)
    if not prop:
        raise not_found("Property not found")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["suite_number", "floor", "rentable_sqft"])
    if not is_str(body["suite_number"]):
        raise invalid_request("suite_number must be a string")
    if not is_int(body["floor"]):
        raise invalid_request("floor must be an integer")
    if not is_int(body["rentable_sqft"]) or body["rentable_sqft"] <= 0:
        raise invalid_request("rentable_sqft must be integer > 0")

    rec = make_common_fields()
    rec.update({
        "property_id": id,
        "suite_number": body["suite_number"],
        "floor": body["floor"],
        "rentable_sqft": body["rentable_sqft"],
        "status": "VACANT",
    })
    store.lease_spaces[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/properties/<id>/lease-spaces", methods=["GET"])
def list_lease_spaces(id):
    require_roles("LandlordPM", "LandlordApprover", "BuildingEngineer")
    prop = store.properties.get(id)
    if not prop:
        raise not_found("Property not found")
    limit, offset = get_pagination_params()
    items = [s for s in store.lease_spaces.values() if s["property_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# LeaseSpace standalone reads
# ---------------------------------------------------------------------------

@bp.route("/api/lease-spaces/<id>", methods=["GET"])
def get_lease_space(id):
    require_roles("LandlordPM", "LandlordApprover", "BuildingEngineer")
    rec = store.lease_spaces.get(id)
    if not rec:
        raise not_found("LeaseSpace not found")
    return success_object(rec)


@bp.route("/api/lease-spaces/<id>/leases", methods=["GET"])
def list_space_leases(id):
    require_roles("LandlordPM", "LandlordApprover")
    rec = store.lease_spaces.get(id)
    if not rec:
        raise not_found("LeaseSpace not found")
    limit, offset = get_pagination_params()
    items = [l for l in store.leases.values() if l["space_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

@bp.route("/api/tenants", methods=["POST"])
def create_tenant():
    require_roles("LandlordPM")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["legal_name", "contact_email", "tax_id"])
    for f in ("legal_name", "contact_email", "tax_id"):
        if not is_str(body[f]):
            raise invalid_request(f"{f} must be a string")

    rec = make_common_fields()
    rec.update({
        "legal_name": body["legal_name"],
        "contact_email": body["contact_email"],
        "tax_id": body["tax_id"],
    })
    store.tenants[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/tenants/<id>", methods=["GET"])
def get_tenant(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    rec = store.tenants.get(id)
    if not rec:
        raise not_found("Tenant not found")
    if role == "TenantRep" and rec["id"] != user_id:
        from errors import APIError, ERR_FORBIDDEN_SCOPE
        raise APIError(ERR_FORBIDDEN_SCOPE, 403, "TenantRep may only read own record")
    return success_object(rec)


@bp.route("/api/tenants/<id>/leases", methods=["GET"])
def list_tenant_leases(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    rec = store.tenants.get(id)
    if not rec:
        raise not_found("Tenant not found")
    if role == "TenantRep" and rec["id"] != user_id:
        from errors import APIError, ERR_FORBIDDEN_SCOPE
        raise APIError(ERR_FORBIDDEN_SCOPE, 403, "TenantRep may only read own leases")
    limit, offset = get_pagination_params()
    items = [l for l in store.leases.values() if l["tenant_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

@bp.route("/api/leases", methods=["POST"])
def create_lease():
    require_roles("LandlordPM")
    body = request.get_json(silent=True) or {}
    require_fields(body, [
        "space_id", "tenant_id", "base_rent_annual_cents",
        "scheduled_rent_commencement_date", "lease_term_months",
    ])
    if not is_str(body["space_id"]):
        raise invalid_request("space_id must be a string")
    if not is_str(body["tenant_id"]):
        raise invalid_request("tenant_id must be a string")
    if not is_int(body["base_rent_annual_cents"]) or body["base_rent_annual_cents"] <= 0:
        raise invalid_request("base_rent_annual_cents must be integer > 0")
    try:
        src = parse_iso8601(body["scheduled_rent_commencement_date"])
    except Exception:
        raise invalid_request("scheduled_rent_commencement_date must be a valid ISO8601 datetime")
    if not is_int(body["lease_term_months"]) or body["lease_term_months"] <= 0:
        raise invalid_request("lease_term_months must be integer > 0")
    abatement_basis = body.get("abatement_basis", "CALENDAR")
    if abatement_basis not in ("CALENDAR", "BUSINESS"):
        raise invalid_request("abatement_basis must be CALENDAR or BUSINESS")

    # Existence: space and tenant must exist
    if body["space_id"] not in store.lease_spaces:
        raise not_found("LeaseSpace not found")
    if body["tenant_id"] not in store.tenants:
        raise not_found("Tenant not found")

    rec = make_common_fields()
    rec.update({
        "space_id": body["space_id"],
        "tenant_id": body["tenant_id"],
        "base_rent_annual_cents": body["base_rent_annual_cents"],
        "scheduled_rent_commencement_date": to_iso_z(src),
        "actual_rent_commencement_date": None,
        "abatement_basis": abatement_basis,
        "delay_responsibility": "NONE",
        "rent_abatement_credit_cents": 0,
        "lease_term_months": body["lease_term_months"],
        "status": "DRAFT",
    })
    store.leases[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/leases/<id>", methods=["GET"])
def get_lease(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    rec = store.leases.get(id)
    if not rec:
        raise not_found("Lease not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, id)
    return success_object(rec)


@bp.route("/api/leases/<id>/activate", methods=["POST"])
def activate_lease(id):
    require_roles("LandlordPM")
    lease = store.leases.get(id)
    if not lease:
        raise not_found("Lease not found")
    if lease["status"] != "DRAFT":
        raise invalid_state("Lease is not in DRAFT state")
    space = store.lease_spaces.get(lease["space_id"])
    if not space:
        raise not_found("LeaseSpace not found")
    if space["status"] != "VACANT":
        raise invalid_state("LeaseSpace is not VACANT")

    lease["status"] = "ACTIVE"
    bump_version(lease)
    space["status"] = "LEASED"
    bump_version(space)
    return success_object(lease)


@bp.route("/api/leases/<id>/ti-projects", methods=["GET"])
def list_lease_projects(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    lease = store.leases.get(id)
    if not lease:
        raise not_found("Lease not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, id)
    limit, offset = get_pagination_params()
    items = [p for p in store.ti_projects.values() if p["lease_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
