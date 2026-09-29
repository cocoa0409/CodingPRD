"""Competitor endpoints and the competitor lifecycle (PRD 3.1, 3.4)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import (ALL_ROLES, COMPLIANCE_OFFICER, PLATFORM_ADMIN, body,
                        endpoint)
from response import object_response
from routes.common import FK_MARKET, filtered, list_page, path_lookup, resolve_fks
from services import cascades, serialize
from util import as_bool, as_enum, as_str, get_required

bp = Blueprint("competitors", __name__)

COLLECTION_METHODS = ("ONLINE", "STORE_AUDIT", "HYBRID")
TIERS = ("PRIMARY", "SECONDARY")
TO_STATUSES = ("SUSPENDED", "ACTIVE", "RETIRED")


@bp.post("/competitors")
@endpoint([PLATFORM_ADMIN])
def create_competitor(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_MARKET])

    market = fks["market_id"]
    if market is None:
        get_required(payload, "market_id")
    competitor_code = as_str(get_required(payload, "competitor_code"),
                             "competitor_code", min_len=1)
    name = as_str(get_required(payload, "name"), "name", min_len=1)
    method_raw = as_str(get_required(payload, "collection_method"),
                        "collection_method", min_len=1)
    tier_raw = as_str(get_required(payload, "tier"), "tier", min_len=1)
    price_match_eligible = False
    if payload.get("price_match_eligible") is not None:
        price_match_eligible = as_bool(payload["price_match_eligible"],
                                       "price_match_eligible")

    collection_method = as_enum(method_raw, "collection_method", COLLECTION_METHODS)
    tier = as_enum(tier_raw, "tier", TIERS)

    for existing in db.competitors.values():
        if (existing["market_id"] == market["id"]
                and existing["competitor_code"] == competitor_code):
            raise err("ERR_DUPLICATE_RESOURCE",
                      "competitor_code '%s' is already used in this market."
                      % competitor_code)

    record = db.new_record()
    record.update({
        "market_id": market["id"],
        "competitor_code": competitor_code,
        "name": name,
        "collection_method": collection_method,
        "tier": tier,
        "price_match_eligible": price_match_eligible,
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    db.competitors[record["id"]] = record
    return object_response(serialize.competitor(record), 201)


@bp.patch("/competitors/<competitor_id>/status")
@endpoint([PLATFORM_ADMIN, COMPLIANCE_OFFICER])
def patch_competitor_status(user_id, role, competitor_id):
    competitor = path_lookup("competitors", competitor_id,
                             "ERR_COMPETITOR_NOT_FOUND")
    payload = body()
    to_status_raw = as_str(get_required(payload, "to_status"), "to_status",
                           min_len=1)
    reason = None
    if payload.get("reason") is not None:
        reason = as_str(payload["reason"], "reason", min_len=1)
    to_status = as_enum(to_status_raw, "to_status", TO_STATUSES)

    current = competitor["status"]
    if to_status == "SUSPENDED":
        if current != "ACTIVE":
            raise err("ERR_INVALID_STATE",
                      "Only an ACTIVE competitor may be suspended.")
        cascades.suspend_competitor(competitor, reason)
    elif to_status == "ACTIVE":
        if current != "SUSPENDED":
            raise err("ERR_INVALID_STATE",
                      "Only a SUSPENDED competitor may be reinstated.")
        competitor["status"] = "ACTIVE"
        competitor["suspension_reason"] = None
        db.touch(competitor)
    else:
        if current not in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_INVALID_STATE",
                      "Only a live competitor may be retired.")
        cascades.retire_competitor(competitor, void_observations=current == "ACTIVE")

    return object_response(serialize.competitor(competitor))


@bp.get("/competitors/<competitor_id>")
@endpoint(ALL_ROLES)
def read_competitor(user_id, role, competitor_id):
    competitor = path_lookup("competitors", competitor_id,
                             "ERR_COMPETITOR_NOT_FOUND")
    return object_response(serialize.competitor(competitor))


@bp.get("/competitors")
@endpoint(ALL_ROLES)
def list_competitors(user_id, role):
    rows = filtered(db.ordered(db.competitors), request.args,
                    [("market_id", "market_id"), ("status", "status"),
                     ("tier", "tier"), ("collection_method", "collection_method")])
    return list_page(rows, serialize.competitor)
