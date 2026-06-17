"""Listing endpoints + Listing state machine (PRD §3.2)."""
from flask import Blueprint, request

from db import db, new_full_record, touch
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from serialize import serialize, serialize_many
from services.access import resolve, resolve_fk, owns_listing
from services.recompute import (recompute_all_requirement_match_counts,
                                recompute_listing_open_deal_count)
from validate import (parse_body, check_str_type, check_int_type,
                      check_number_type, parse_pagination, paginate)

bp = Blueprint("listings", __name__)


@bp.post("/listings")
def create_listing():
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    body = parse_body()
    space_id = check_str_type(body, "space_id", required=True)
    listing_broker_id = check_str_type(body, "listing_broker_id", required=True)
    term_months = check_int_type(body, "term_months", required=True)
    escalation = check_number_type(body, "annual_escalation_pct",
                                   required=False, default=0.03)
    co_broke = check_number_type(body, "co_broke_offered_pct",
                                 required=False, default=0.5)
    sp = resolve_fk(db.spaces, space_id)
    broker = resolve_fk(db.brokers, listing_broker_id)
    # Ownership: acting broker controls the space and is the named broker
    from services.access import owns_space
    owns_space(user_id, sp)
    if listing_broker_id != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker mismatch")
    # constraints
    if term_months < 1:
        raise err("ERR_INVALID_REQUEST", "term_months must be >= 1")
    if not (0 <= escalation <= 0.20):
        raise err("ERR_INVALID_REQUEST", "annual_escalation_pct out of range")
    if not (0 <= co_broke <= 1):
        raise err("ERR_INVALID_REQUEST", "co_broke_offered_pct out of range")
    rec = new_full_record({
        "space_id": space_id,
        "listing_broker_id": listing_broker_id,
        "term_months": term_months,
        "annual_escalation_pct": escalation,
        "co_broke_offered_pct": co_broke,
        "status": "DRAFT",
        "open_deal_count": 0,
    })
    db.listings[rec["id"]] = rec
    return success(serialize("Listing", rec), status=201)


@bp.get("/listings/<listing_id>")
def get_listing(listing_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.listings, listing_id)
    return success(serialize("Listing", rec), status=200)


@bp.get("/listings")
def list_listings():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    space_id = request.args.get("space_id")
    listing_broker_id = request.args.get("listing_broker_id")
    status = request.args.get("status")
    items = list(db.listings.values())
    if space_id is not None:
        items = [l for l in items if l["space_id"] == space_id]
    if listing_broker_id is not None:
        items = [l for l in items if l["listing_broker_id"] == listing_broker_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Listing", page), limit, offset, total)


@bp.post("/listings/<listing_id>/activate")
def activate_listing(listing_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    lst = resolve(db.listings, listing_id)
    owns_listing(user_id, lst)
    if lst["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Listing not in DRAFT")
    sp = db.spaces.get(lst["space_id"])
    if sp is None or sp["status"] != "AVAILABLE":
        raise err("ERR_SPACE_NOT_AVAILABLE", "Parent space not AVAILABLE")
    lst["status"] = "ACTIVE"
    touch(lst)
    recompute_all_requirement_match_counts()
    return success(serialize("Listing", lst), status=200)


@bp.post("/listings/<listing_id>/withdraw")
def withdraw_listing(listing_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    lst = resolve(db.listings, listing_id)
    owns_listing(user_id, lst)
    if lst["status"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Listing cannot be withdrawn from current state")
    if lst["status"] == "DRAFT":
        lst["status"] = "WITHDRAWN"
        touch(lst)
        recompute_all_requirement_match_counts()
        return success(serialize("Listing", lst), status=200)
    # ACTIVE: blocked if any child deal in LOI_ACCEPTED or LEASE_OUT
    for d in db.deals.values():
        if d["listing_id"] == listing_id and d["stage"] in ("LOI_ACCEPTED", "LEASE_OUT"):
            raise err("ERR_LISTING_HAS_LIVE_DEAL", "Listing has a live deal")
    lst["status"] = "WITHDRAWN"
    touch(lst)
    # cascade child deals NOT IN {EXECUTED, DEAD} -> DEAD
    from services.deal_engine import kill_deal_cascade
    for d in list(db.deals.values()):
        if d["listing_id"] == listing_id and d["stage"] not in ("EXECUTED", "DEAD"):
            kill_deal_cascade(d, reconcile_parents=False)
    recompute_all_requirement_match_counts()
    return success(serialize("Listing", lst), status=200)
