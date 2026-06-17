"""Requirement endpoints + Requirement close (PRD §3.3)."""
from flask import Blueprint, request

from db import db, new_full_record, touch
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from serialize import serialize, serialize_many
from services.access import resolve, resolve_fk, owns_requirement
from services.recompute import (recompute_requirement_match_count,
                                matching_listings_for_requirement)
from validate import (parse_body, check_str_type, check_int_type,
                      check_number_type, parse_pagination, paginate)

bp = Blueprint("requirements", __name__)

VALID_ASSET_CLASSES = {"OFFICE", "RETAIL", "INDUSTRIAL", "FLEX"}


@bp.post("/requirements")
def create_requirement():
    user_id, role = authenticate()
    require_role(role, ["TenantBroker"])
    body = parse_body()
    tenant_broker_id = check_str_type(body, "tenant_broker_id", required=True)
    tenant_name = check_str_type(body, "tenant_name", required=True)
    market = check_str_type(body, "market", required=True)
    asset_class = check_str_type(body, "asset_class", required=True)
    min_sf = check_int_type(body, "min_sf", required=True)
    max_sf = check_int_type(body, "max_sf", required=True)
    max_rent = check_number_type(body, "max_rent_psf_yr", required=True)
    broker = resolve_fk(db.brokers, tenant_broker_id)
    if tenant_broker_id != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker mismatch")
    if not market or market.strip() == "":
        raise err("ERR_INVALID_REQUEST", "market must be non-empty")
    if asset_class not in VALID_ASSET_CLASSES:
        raise err("ERR_INVALID_REQUEST", "Invalid asset_class")
    if min_sf < 1:
        raise err("ERR_INVALID_REQUEST", "min_sf must be >= 1")
    if max_sf < min_sf:
        raise err("ERR_INVALID_REQUEST", "max_sf must be >= min_sf")
    if max_rent <= 0:
        raise err("ERR_INVALID_REQUEST", "max_rent_psf_yr must be > 0")
    rec = new_full_record({
        "tenant_broker_id": tenant_broker_id,
        "tenant_name": tenant_name,
        "market": market,
        "asset_class": asset_class,
        "min_sf": min_sf,
        "max_sf": max_sf,
        "max_rent_psf_yr": max_rent,
        "status": "OPEN",
        "match_count": 0,
    })
    db.requirements[rec["id"]] = rec
    # compute match_count at creation (PRD §3.3). The recompute may bump
    # updated_at/version; since this is part of initial construction, restore
    # the record to a fresh-creation state (version 1, updated_at == created_at).
    recompute_requirement_match_count(rec["id"])
    rec["version"] = 1
    rec["updated_at"] = rec["created_at"]
    return success(serialize("Requirement", rec), status=201)


@bp.get("/requirements/<requirement_id>")
def get_requirement(requirement_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.requirements, requirement_id)
    return success(serialize("Requirement", rec), status=200)


@bp.get("/requirements")
def list_requirements():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    tenant_broker_id = request.args.get("tenant_broker_id")
    status = request.args.get("status")
    items = list(db.requirements.values())
    if tenant_broker_id is not None:
        items = [r for r in items if r["tenant_broker_id"] == tenant_broker_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Requirement", page), limit, offset, total)


@bp.get("/requirements/<requirement_id>/matches")
def list_matches(requirement_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    req = resolve(db.requirements, requirement_id)
    limit, offset = parse_pagination()
    items = matching_listings_for_requirement(req)
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Listing", page), limit, offset, total)


@bp.post("/requirements/<requirement_id>/close")
def close_requirement(requirement_id):
    user_id, role = authenticate()
    require_role(role, ["TenantBroker"])
    req = resolve(db.requirements, requirement_id)
    owns_requirement(user_id, req)
    if req["status"] not in ("OPEN", "TOURING"):
        raise err("ERR_INVALID_STATE", "Requirement cannot be closed from current state")
    # blocked if any deal in LOI_ACCEPTED/LEASE_OUT/EXECUTED
    for d in db.deals.values():
        if d["requirement_id"] == requirement_id and \
                d["stage"] in ("LOI_ACCEPTED", "LEASE_OUT", "EXECUTED"):
            raise err("ERR_REQUIREMENT_HAS_LIVE_DEAL", "Requirement has a live deal")
    req["status"] = "CLOSED_LOST"
    touch(req)
    # cascade tours in REQUESTED/CONFIRMED -> CANCELLED
    from services.tour_engine import release_tour_hold
    for t in db.tours.values():
        if t["requirement_id"] == requirement_id and \
                t["status"] in ("REQUESTED", "CONFIRMED"):
            release_tour_hold(t)
            t["status"] = "CANCELLED"
            touch(t)
    return success(serialize("Requirement", req), status=200)
