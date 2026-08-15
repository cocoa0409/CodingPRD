"""Lease disclosures and rights dispositions."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    raise_err, ERR_INVALID_LISTING_STATE, ERR_INVALID_DISCLOSURE_STATE,
    ERR_RIGHTS_LOCKED, ERR_DUPLICATE_RECORD,
)
from middleware import auth, require_roles, forbid
from response import (
    success_object, success_list, get_body, as_str, as_enum, as_decimal,
    as_datetime, new_common, touch, paginate, fmt_dt,
)
from .clock import get_or_404, new_id

bp = Blueprint("compliance", __name__)

ALL_ROLES = {"Seller", "BrokerAgent", "Buyer", "PlatformAdmin"}
MINERAL = ("CONVEYED", "RESERVED", "PARTIALLY_CONVEYED")
WIND = ("CONVEYED", "RESERVED", "LEASED_TO_THIRD_PARTY")


def _listing_of_tract(tract):
    return get_or_404(db.listings, tract["listing_id"], "listing")


# ---------------------------------------------------------------------------
# Lease disclosures
# ---------------------------------------------------------------------------

@bp.post("/api/disclosures")
def create_disclosure():
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    body = get_body()
    tract_id = body.get("tract_id")
    if tract_id is None:
        from errors import ERR_VALIDATION
        raise_err(ERR_VALIDATION, "missing required field: tract_id")
    tract = get_or_404(db.tracts, tract_id, "tract")
    listing = _listing_of_tract(tract)
    if listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")

    tenant_name = as_str(body, "tenant_name")
    start = as_datetime(body, "lease_start_date")
    end = as_datetime(body, "lease_end_date")
    rent = as_decimal(body, "annual_rent", gt=0)

    if listing["status"] not in ("DRAFT", "PACKAGED"):
        raise_err(ERR_INVALID_LISTING_STATE,
                  "disclosures may be created only while the listing is DRAFT or PACKAGED")
    if any(d["tract_id"] == tract["id"] for d in db.disclosures.values()):
        raise_err(ERR_DUPLICATE_RECORD, "tract already has a lease disclosure")

    d = new_common({
        "id": new_id(),
        "tract_id": tract["id"],
        "tenant_name": tenant_name,
        "lease_start_date": fmt_dt(start),
        "lease_end_date": fmt_dt(end),
        "_lease_end_dt": end,
        "annual_rent": rent,
        "acknowledged_by_buyer_id": None,
        "status": "DISCLOSED",
    })
    db.disclosures[d["id"]] = d
    return success_object(serializers.disclosure(d), status=201)


@bp.post("/api/disclosures/<did>/acknowledge")
def acknowledge_disclosure(did):
    user_id, role = auth()
    require_roles(role, {"Buyer"})
    d = get_or_404(db.disclosures, did, "disclosure")
    # Caller must be the buyer of a CONFIRMED_WINNER bid covering this tract.
    eligible = any(
        b["buyer_id"] == user_id and b["status"] == "CONFIRMED_WINNER"
        and d["tract_id"] in b["tract_ids"]
        for b in db.bids.values()
    )
    if not eligible:
        forbid("caller is not a winning buyer of this disclosure's tract")
    if d["status"] != "DISCLOSED":
        raise_err(ERR_INVALID_DISCLOSURE_STATE,
                  "only a DISCLOSED disclosure can be acknowledged")
    d["status"] = "ACKNOWLEDGED"
    d["acknowledged_by_buyer_id"] = user_id
    touch(d)
    return success_object(serializers.disclosure(d))


@bp.get("/api/tracts/<tid>/disclosures")
def list_disclosures(tid):
    auth()
    tract = get_or_404(db.tracts, tid, "tract")
    items = [d for d in db.disclosures.values() if d["tract_id"] == tract["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.disclosure(d) for d in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Rights dispositions
# ---------------------------------------------------------------------------

@bp.post("/api/rights")
def create_rights():
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    body = get_body()
    tract_id = body.get("tract_id")
    if tract_id is None:
        from errors import ERR_VALIDATION
        raise_err(ERR_VALIDATION, "missing required field: tract_id")
    tract = get_or_404(db.tracts, tract_id, "tract")
    listing = _listing_of_tract(tract)
    if listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")

    mineral = as_enum(body, "mineral_rights", MINERAL)
    wind = as_enum(body, "wind_rights", WIND)

    # Blocked outright while any auction of the listing is OPEN or EXTENDED.
    if any(a["listing_id"] == listing["id"] and a["status"] in ("OPEN", "EXTENDED")
           for a in db.auctions.values()):
        raise_err(ERR_RIGHTS_LOCKED,
                  "rights cannot be declared while a listing auction is open")
    if listing["status"] not in ("DRAFT", "PACKAGED", "MARKETED"):
        raise_err(ERR_INVALID_LISTING_STATE,
                  "rights may be declared only while DRAFT, PACKAGED, or MARKETED")
    if any(r["tract_id"] == tract["id"] for r in db.rights.values()):
        raise_err(ERR_DUPLICATE_RECORD, "tract already has a rights disposition")

    r = new_common({
        "id": new_id(),
        "tract_id": tract["id"],
        "mineral_rights": mineral,
        "wind_rights": wind,
        "status": "DECLARED",
    })
    db.rights[r["id"]] = r
    return success_object(serializers.rights_disposition(r), status=201)


@bp.get("/api/tracts/<tid>/rights")
def list_rights(tid):
    auth()
    tract = get_or_404(db.tracts, tid, "tract")
    items = [r for r in db.rights.values() if r["tract_id"] == tract["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.rights_disposition(r) for r in page],
                        limit, offset, total)
