"""Listings, tracts, packaging/marketing/withdrawal, comparables, valuation."""

from decimal import Decimal

from flask import Blueprint, request

import db
import serializers
from errors import (
    raise_err, ERR_INVALID_LISTING_STATE, ERR_STALE_LISTING_VERSION,
    ERR_ACREAGE_MISMATCH, ERR_RESERVE_BELOW_FLOOR, ERR_RIGHTS_NOT_DECLARED,
    ERR_VALIDATION,
)
from middleware import auth, require_roles, forbid
from response import (
    success_object, success_list, get_body, as_str, as_enum, as_decimal,
    as_int, as_datetime, new_common, touch, paginate, fmt_dt, jn,
)
from services.valuation import compute_valuation
from .clock import get_or_404, new_id

bp = Blueprint("listings", __name__)

ALL_ROLES = {"Seller", "BrokerAgent", "Buyer", "PlatformAdmin"}
STRATEGIES = ("WHOLE", "SPLIT", "COMBINATION")


def own_listing_or_forbid(listing, user_id, role):
    if role == "BrokerAgent" and listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

@bp.post("/api/listings")
def create_listing():
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    body = get_body()
    seller_id = body.get("seller_id")
    if seller_id is not None:
        get_or_404(db.sellers, seller_id, "seller")
    seller_id = as_str(body, "seller_id")
    get_or_404(db.sellers, seller_id, "seller")
    title = as_str(body, "title")
    county = as_str(body, "county")
    state_code = as_str(body, "state_code")
    total = as_decimal(body, "total_gross_acres", gt=0)
    strategy = as_enum(body, "packaging_strategy", STRATEGIES)
    reserve = as_decimal(body, "reserve_price_total")
    l = new_common({
        "id": new_id(),
        "seller_id": seller_id,
        "agent_id": user_id,
        "title": title,
        "county": county,
        "state_code": state_code,
        "total_gross_acres": total,
        "packaging_strategy": strategy,
        "reserve_price_total": reserve,
        "status": "DRAFT",
    })
    db.listings[l["id"]] = l
    return success_object(serializers.listing(l), status=201)


@bp.get("/api/listings/<lid>")
def get_listing(lid):
    auth()
    l = get_or_404(db.listings, lid, "listing")
    return success_object(serializers.listing(l))


@bp.get("/api/listings")
def list_listings():
    auth()
    items = list(db.listings.values())
    seller_id = request.args.get("seller_id")
    agent_id = request.args.get("agent_id")
    status = request.args.get("status")
    if seller_id is not None:
        items = [l for l in items if l["seller_id"] == seller_id]
    if agent_id is not None:
        items = [l for l in items if l["agent_id"] == agent_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.listing(l) for l in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Tracts
# ---------------------------------------------------------------------------

@bp.post("/api/tracts")
def create_tract():
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    body = get_body()
    listing_id = body.get("listing_id")
    if listing_id is None:
        raise_err(ERR_VALIDATION, "missing required field: listing_id")
    listing = get_or_404(db.listings, listing_id, "listing")
    own_listing_or_forbid(listing, user_id, role)

    tract_number = as_int(body, "tract_number")
    gross = as_decimal(body, "gross_acres", gt=0)
    tillable = as_decimal(body, "tillable_acres", ge=0)
    if tillable > gross:
        raise_err(ERR_VALIDATION, "tillable_acres must not exceed gross_acres")
    spi = as_decimal(body, "soil_productivity_index", gt=0)
    if spi > Decimal("100"):
        raise_err(ERR_VALIDATION, "soil_productivity_index must be <= 100")
    min_price = as_decimal(body, "min_price", ge=0)
    expected = as_int(body, "expected_listing_version")

    if listing["status"] != "DRAFT":
        raise_err(ERR_INVALID_LISTING_STATE, "tracts may be added only to a DRAFT listing")
    if expected != listing["version"]:
        raise_err(ERR_STALE_LISTING_VERSION, "expected_listing_version is stale")

    existing = [t for t in db.tracts.values() if t["listing_id"] == listing["id"]]
    running = sum((t["gross_acres"] for t in existing), Decimal("0"))
    if running + gross > listing["total_gross_acres"]:
        raise_err(ERR_ACREAGE_MISMATCH, "tract acreage would exceed total_gross_acres")

    t = new_common({
        "id": new_id(),
        "listing_id": listing["id"],
        "tract_number": tract_number,
        "gross_acres": gross,
        "tillable_acres": tillable,
        "soil_productivity_index": spi,
        "min_price": min_price,
        "status": "REGISTERED",
    })
    db.tracts[t["id"]] = t
    touch(listing)
    return success_object(serializers.tract(t), status=201)


@bp.get("/api/tracts/<tid>")
def get_tract(tid):
    auth()
    t = get_or_404(db.tracts, tid, "tract")
    return success_object(serializers.tract(t))


@bp.get("/api/listings/<lid>/tracts")
def list_tracts(lid):
    auth()
    listing = get_or_404(db.listings, lid, "listing")
    items = [t for t in db.tracts.values() if t["listing_id"] == listing["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serializers.tract(t) for t in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Packaging / marketing / withdrawal
# ---------------------------------------------------------------------------

@bp.post("/api/listings/<lid>/package")
def package_listing(lid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    listing = get_or_404(db.listings, lid, "listing")
    own_listing_or_forbid(listing, user_id, role)
    if listing["status"] != "DRAFT":
        raise_err(ERR_INVALID_LISTING_STATE, "only a DRAFT listing can be packaged")

    tracts = [t for t in db.tracts.values() if t["listing_id"] == listing["id"]]
    running = sum((t["gross_acres"] for t in tracts), Decimal("0"))
    if not tracts or running != listing["total_gross_acres"]:
        raise_err(ERR_ACREAGE_MISMATCH,
                  "tract acreage must reconcile exactly to total_gross_acres")

    # Reserve floor: reserve >= 0.85 * sum of PROVISIONAL valuations over all tracts.
    total_value = Decimal("0")
    for t in sorted(tracts, key=lambda x: x["_seq"]):
        _, _, est = compute_valuation(t, "PROVISIONAL")
        total_value += est
    floor = Decimal("0.85") * total_value
    if listing["reserve_price_total"] < floor:
        raise_err(ERR_RESERVE_BELOW_FLOOR,
                  "reserve_price_total is below 85% of the provisional valuation sum")

    listing["status"] = "PACKAGED"
    touch(listing)
    return success_object(serializers.listing(listing))


@bp.post("/api/listings/<lid>/market")
def market_listing(lid):
    user_id, role = auth()
    require_roles(role, {"BrokerAgent"})
    listing = get_or_404(db.listings, lid, "listing")
    own_listing_or_forbid(listing, user_id, role)
    if listing["status"] != "PACKAGED":
        raise_err(ERR_INVALID_LISTING_STATE, "only a PACKAGED listing can be marketed")

    tracts = [t for t in db.tracts.values() if t["listing_id"] == listing["id"]]
    for t in tracts:
        declared = any(
            r["tract_id"] == t["id"] and r["status"] == "DECLARED"
            for r in db.rights.values()
        )
        if not declared:
            raise_err(ERR_RIGHTS_NOT_DECLARED,
                      "every tract must carry a DECLARED rights disposition")

    for t in tracts:
        if t["status"] == "REGISTERED":
            t["status"] = "OFFERED"
            touch(t)
    listing["status"] = "MARKETED"
    touch(listing)
    return success_object(serializers.listing(listing))


@bp.post("/api/listings/<lid>/withdraw")
def withdraw_listing(lid):
    user_id, role = auth()
    require_roles(role, {"Seller", "BrokerAgent"})
    listing = get_or_404(db.listings, lid, "listing")
    if role == "Seller" and listing["seller_id"] != user_id:
        forbid("caller is not the listing's seller")
    if role == "BrokerAgent" and listing["agent_id"] != user_id:
        forbid("caller is not the listing's agent")
    if listing["status"] not in ("DRAFT", "PACKAGED", "MARKETED", "AUCTION_SCHEDULED"):
        raise_err(ERR_INVALID_LISTING_STATE,
                  f"listing in {listing['status']} cannot be withdrawn")

    listing_tract_ids = {t["id"] for t in db.tracts.values() if t["listing_id"] == lid}
    # Auctions SCHEDULED/OPEN/EXTENDED -> CANCELLED; their PLACED/SEALED bids -> VOIDED.
    for a in sorted(db.auctions.values(), key=lambda x: x["_seq"]):
        if a["listing_id"] != lid or a["status"] not in ("SCHEDULED", "OPEN", "EXTENDED"):
            continue
        a["status"] = "CANCELLED"
        touch(a)
        for b in db.bids.values():
            if b["auction_id"] == a["id"] and b["status"] in ("PLACED", "SEALED"):
                b["status"] = "VOIDED"
                touch(b)
    # Rights LOCKED -> DECLARED.
    for r in db.rights.values():
        if r["tract_id"] in listing_tract_ids and r["status"] == "LOCKED":
            r["status"] = "DECLARED"
            touch(r)
    # Tracts REGISTERED/OFFERED/UNSOLD -> WITHDRAWN.
    for t in db.tracts.values():
        if t["listing_id"] == lid and t["status"] in ("REGISTERED", "OFFERED", "UNSOLD"):
            t["status"] = "WITHDRAWN"
            touch(t)
    listing["status"] = "WITHDRAWN"
    touch(listing)
    return success_object(serializers.listing(listing))


# ---------------------------------------------------------------------------
# Comparables and valuation
# ---------------------------------------------------------------------------

@bp.post("/api/comparables")
def create_comparable():
    _, role = auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    county = as_str(body, "county")
    state_code = as_str(body, "state_code")
    sale_dt = as_datetime(body, "sale_date")
    price = as_decimal(body, "sale_price_total", gt=0)
    gross = as_decimal(body, "gross_acres", gt=0)
    tillable = as_decimal(body, "tillable_acres", ge=0)
    if tillable > gross:
        raise_err(ERR_VALIDATION, "tillable_acres must not exceed gross_acres")
    spi = as_decimal(body, "soil_productivity_index", gt=0)
    c = {
        "id": new_id(),
        "created_at": fmt_dt(db.clock_now()),
        "_seq": db.next_seq(),
        "county": county,
        "state_code": state_code,
        "sale_date": fmt_dt(sale_dt),
        "_sale_date_dt": sale_dt,
        "sale_price_total": price,
        "gross_acres": gross,
        "tillable_acres": tillable,
        "soil_productivity_index": spi,
    }
    db.comparables[c["id"]] = c
    return success_object(serializers.comparable(c), status=201)


@bp.get("/api/tracts/<tid>/valuation")
def tract_valuation(tid):
    auth()
    t = get_or_404(db.tracts, tid, "tract")
    variant = request.args.get("variant")
    if variant is None or variant not in ("PROVISIONAL", "APPRAISAL"):
        raise_err(ERR_VALIDATION, "variant must be PROVISIONAL or APPRAISAL")
    count, vpa, est = compute_valuation(t, variant)
    return success_object({
        "tract_id": t["id"],
        "variant": variant,
        "comparable_count": count,
        "value_per_acre": float(vpa),
        "estimated_value": int(est),
    })
