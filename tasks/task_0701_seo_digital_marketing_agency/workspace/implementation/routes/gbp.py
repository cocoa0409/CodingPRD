"""GbpListing routes."""
from flask import Blueprint, request

import calc
from auth import require_auth, require_role
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, find, assert_owns_client, paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("gbp", __name__)


def _recompute_score(listing):
    client = store.clients.get(listing["client_id"])
    client_status = client["status"] if client else None
    listing["optimization_score"] = calc.gbp_optimization_score(
        listing["location_name"], listing["service_area"],
        listing["status"], client_status,
    )


@bp.route("/gbp-listings", methods=["POST"])
def create_listing():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    body = get_body()
    client_id = require_str(body, "client_id")
    client = find("client", client_id)
    location_name = require_str(body, "location_name")
    service_area = require_str(body, "service_area")

    rec = base_record(versioned=True)
    rec.update({
        "client_id": client_id,
        "location_name": location_name,
        "service_area": service_area,
        "optimization_score": 0,
        "status": "UNVERIFIED",
    })
    _recompute_score(rec)
    store.gbp_listings[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/gbp-listings/<lid>", methods=["GET"])
def get_listing(lid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    listing = find("gbp_listing", lid)
    client = find("client", listing["client_id"])
    assert_owns_client(principal, client)
    _recompute_score(listing)
    return ok_object(listing, 200)


@bp.route("/gbp-listings", methods=["GET"])
def list_listings():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    parse_pagination()
    client_filter = request.args.get("client_id")
    status_filter = request.args.get("status")
    records = list(store.gbp_listings.values())
    if principal.role == "Client":
        records = [l for l in records if l["client_id"] == principal.user_id]
    if client_filter is not None:
        records = [l for l in records if l["client_id"] == client_filter]
    if status_filter is not None:
        records = [l for l in records if l["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/gbp-listings/<lid>/verify", methods=["POST"])
def verify_listing(lid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    listing = find("gbp_listing", lid)
    if listing["status"] != "UNVERIFIED":
        raise err("ERR_INVALID_STATE", "Listing must be UNVERIFIED to verify")
    # service_area unique per client among VERIFIED/OPTIMIZED
    for other in store.gbp_listings.values():
        if other["id"] == lid:
            continue
        if other["client_id"] != listing["client_id"]:
            continue
        if other["service_area"] == listing["service_area"] and other["status"] in ("VERIFIED", "OPTIMIZED"):
            raise err("ERR_DUPLICATE_RESOURCE", "service_area already verified/optimized for this client")
    listing["status"] = "VERIFIED"
    _recompute_score(listing)
    touch(listing)
    return ok_object(listing, 200)


@bp.route("/gbp-listings/<lid>/optimize", methods=["POST"])
def optimize_listing(lid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    listing = find("gbp_listing", lid)
    if listing["status"] != "VERIFIED":
        raise err("ERR_INVALID_STATE", "Listing must be VERIFIED to optimize")
    _recompute_score(listing)
    if listing["optimization_score"] < 80:
        raise err("ERR_OPTIMIZATION_THRESHOLD_NOT_MET", "optimization_score must be >= 80")
    listing["status"] = "OPTIMIZED"
    touch(listing)
    return ok_object(listing, 200)


@bp.route("/gbp-listings/<lid>/suspend", methods=["POST"])
def suspend_listing(lid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    listing = find("gbp_listing", lid)
    if listing["status"] not in ("UNVERIFIED", "VERIFIED", "OPTIMIZED"):
        raise err("ERR_INVALID_STATE", "Listing must be UNVERIFIED/VERIFIED/OPTIMIZED to suspend")
    listing["status"] = "SUSPENDED"
    touch(listing)
    return ok_object(listing, 200)
