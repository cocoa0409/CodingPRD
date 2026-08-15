"""Quotes (full lifecycle with SPOT/LOCKED pricing, OCC, expiry sweep) and
Contracts (reservation, cancel, declare-default)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import authorize
from db import store, new_id, stamp_new, touch, get_clock
from domain import (
    FORAGE_TYPES, QUOTE_TIERS, compute_quote_pricing, select_spot_index,
    find_freight_lane, sweep_quote_if_expired, sweep_all_quotes,
    contract_close_side_effects,
)
from errors import (
    ApiError, ERR_BUYER_NOT_FOUND, ERR_QUOTE_NOT_FOUND, ERR_CONTRACT_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP, ERR_BUYER_SUSPENDED, ERR_TONS_NOT_POSITIVE,
    ERR_UNGRADED_TIER, ERR_NO_MARKET_INDEX, ERR_NO_FREIGHT_LANE,
    ERR_QUOTE_NOT_ISSUABLE, ERR_QUOTE_EXPIRED, ERR_STALE_VERSION,
    ERR_CREDIT_LIMIT_EXCEEDED, ERR_CONTRACT_NOT_ACTIVE, ERR_DEADLINE_NOT_PASSED,
)
from response import success
from serializers import quote_out, contract_out
from util import (
    req, as_str, as_int, as_enum, as_number, as_date,
    get_body, paginate, sorted_by_created,
)

bp = Blueprint("trade", __name__)


# --- Quote -------------------------------------------------------------------

@bp.post("/api/quotes")
def create_quote():
    uid, _ = authorize(["Buyer"])
    body = get_body()
    buyer_id = as_str(req(body, "buyer_id"), "buyer_id")
    forage_type = as_enum(req(body, "forage_type"), "forage_type", FORAGE_TYPES)
    quality_tier = as_enum(req(body, "quality_tier"), "quality_tier", QUOTE_TIERS)
    tons = as_number(req(body, "tons"), "tons")
    origin = as_str(req(body, "origin_region_code"), "origin_region_code")
    dest = as_str(req(body, "dest_region_code"), "dest_region_code")
    delivery_by = as_date(req(body, "requested_delivery_by"), "requested_delivery_by")
    # Priority 4: existence.
    buyer = store["buyers"].get(buyer_id)
    if buyer is None:
        raise ApiError(ERR_BUYER_NOT_FOUND, 404, "buyer not found")
    # Priority 5: ownership.
    if buyer_id != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "buyers may only create quotes for themselves")
    # Priority 9: buyer must be ACTIVE.
    if buyer["status"] != "ACTIVE":
        raise ApiError(ERR_BUYER_SUSPENDED, 422, "buyer is suspended")
    # Priority 10: business constraints in catalog order.
    if tons <= 0:
        raise ApiError(ERR_TONS_NOT_POSITIVE, 422, "tons must be greater than zero")
    if quality_tier == "UNGRADED":
        raise ApiError(ERR_UNGRADED_TIER, 422, "UNGRADED hay cannot be quoted")
    quote = stamp_new({
        "id": new_id(),
        "buyer_id": buyer_id,
        "forage_type": forage_type,
        "quality_tier": quality_tier,
        "tons": tons,
        "origin_region_code": origin,
        "dest_region_code": dest,
        "requested_delivery_by": delivery_by,
        "pinned_market_index_id": None,
        "unit_price_cents": None,
        "commodity_cents": None,
        "freight_cents": None,
        "total_cents": None,
        "issued_at": None,
        "expires_at": None,
        "status": "DRAFT",
    })
    # SPOT pricing at creation (raises ERR_NO_MARKET_INDEX / ERR_NO_FREIGHT_LANE).
    pricing = compute_quote_pricing(quote, "SPOT")
    quote["unit_price_cents"] = pricing["unit_price_cents"]
    quote["commodity_cents"] = pricing["commodity_cents"]
    quote["freight_cents"] = pricing["freight_cents"]
    quote["total_cents"] = pricing["total_cents"]
    store["quotes"][quote["id"]] = quote
    return success(quote_out(quote), "object", 201)


@bp.get("/api/quotes")
def list_quotes():
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Buyer"])
    sweep_all_quotes()
    items = list(store["quotes"].values())
    buyer_filter = request.args.get("buyer_id")
    if role == "Buyer":
        buyer_filter = uid  # buyers see only their own quotes
    status_filter = request.args.get("status")
    pin_filter = request.args.get("pinned_market_index_id")
    if buyer_filter is not None:
        items = [q for q in items if q["buyer_id"] == buyer_filter]
    if status_filter is not None:
        items = [q for q in items if q["status"] == status_filter]
    if pin_filter is not None:
        items = [q for q in items if q["pinned_market_index_id"] == pin_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([quote_out(q) for q in page], "array", 200, meta)


def _load_quote(quote_id):
    quote = store["quotes"].get(quote_id)
    if quote is None:
        raise ApiError(ERR_QUOTE_NOT_FOUND, 404, "quote not found")
    return quote


def _check_quote_owner(quote, uid):
    if quote["buyer_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "buyers may only act on their own quotes")


@bp.get("/api/quotes/<quote_id>")
def get_quote(quote_id):
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Buyer"])
    quote = _load_quote(quote_id)
    sweep_quote_if_expired(quote)
    if role == "Buyer":
        _check_quote_owner(quote, uid)
    return success(quote_out(quote), "object", 200)


@bp.patch("/api/quotes/<quote_id>")
def patch_quote(quote_id):
    uid, _ = authorize(["Buyer"])
    body = get_body()
    expected_version = as_int(req(body, "expected_quote_version"), "expected_quote_version")
    new_tons = None
    new_dest = None
    new_delivery_by = None
    if "tons" in body and body["tons"] is not None:
        new_tons = as_number(body["tons"], "tons")
    if "dest_region_code" in body and body["dest_region_code"] is not None:
        new_dest = as_str(body["dest_region_code"], "dest_region_code")
    if "requested_delivery_by" in body and body["requested_delivery_by"] is not None:
        new_delivery_by = as_date(body["requested_delivery_by"], "requested_delivery_by")
    quote = _load_quote(quote_id)
    sweep_quote_if_expired(quote)
    _check_quote_owner(quote, uid)
    if expected_version != quote["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_quote_version does not match the quote's current version")
    if quote["status"] != "DRAFT":
        raise ApiError(ERR_QUOTE_NOT_ISSUABLE, 409, "only DRAFT quotes may be updated")
    if new_tons is not None and new_tons <= 0:
        raise ApiError(ERR_TONS_NOT_POSITIVE, 422, "tons must be greater than zero")
    if new_tons is not None:
        quote["tons"] = new_tons
    if new_dest is not None:
        quote["dest_region_code"] = new_dest
    if new_delivery_by is not None:
        quote["requested_delivery_by"] = new_delivery_by
    # SPOT reprice against the current clock (raises ERR_NO_MARKET_INDEX /
    # ERR_NO_FREIGHT_LANE when the lookups fail).
    pricing = compute_quote_pricing(quote, "SPOT")
    quote["unit_price_cents"] = pricing["unit_price_cents"]
    quote["commodity_cents"] = pricing["commodity_cents"]
    quote["freight_cents"] = pricing["freight_cents"]
    quote["total_cents"] = pricing["total_cents"]
    touch(quote)
    return success(quote_out(quote), "object", 200)


@bp.post("/api/quotes/<quote_id>/issue")
def issue_quote(quote_id):
    uid, _ = authorize(["Buyer"])
    quote = _load_quote(quote_id)
    sweep_quote_if_expired(quote)
    _check_quote_owner(quote, uid)
    if quote["status"] != "DRAFT":
        raise ApiError(ERR_QUOTE_NOT_ISSUABLE, 409, "only a DRAFT quote can be issued")
    buyer = store["buyers"].get(quote["buyer_id"])
    if buyer is None or buyer["status"] != "ACTIVE":
        raise ApiError(ERR_BUYER_SUSPENDED, 422, "buyer is suspended")
    # LOCKED variant: pin the latest index effective on/before the clock date.
    idx = select_spot_index(quote["origin_region_code"], quote["forage_type"])
    quote["pinned_market_index_id"] = idx["id"]
    pricing = compute_quote_pricing(quote, "LOCKED")
    quote["unit_price_cents"] = pricing["unit_price_cents"]
    quote["commodity_cents"] = pricing["commodity_cents"]
    quote["freight_cents"] = pricing["freight_cents"]
    quote["total_cents"] = pricing["total_cents"]
    quote["issued_at"] = get_clock()
    quote["expires_at"] = get_clock() + timedelta(hours=72)
    quote["status"] = "ISSUED"
    touch(quote)
    return success(quote_out(quote), "object", 200)


@bp.post("/api/quotes/<quote_id>/revise")
def revise_quote(quote_id):
    uid, _ = authorize(["Buyer"])
    body = get_body()
    expected_version = as_int(req(body, "expected_quote_version"), "expected_quote_version")
    quote = _load_quote(quote_id)
    sweep_quote_if_expired(quote)
    _check_quote_owner(quote, uid)
    if quote["status"] != "ISSUED":
        raise ApiError(ERR_QUOTE_NOT_ISSUABLE, 409, "only an ISSUED quote can be revised")
    if expected_version != quote["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_quote_version does not match the quote's current version")
    quote["pinned_market_index_id"] = None
    quote["issued_at"] = None
    quote["expires_at"] = None
    quote["status"] = "DRAFT"
    # Pricing fields recompute SPOT on next read.
    pricing = compute_quote_pricing(quote, "SPOT")
    quote["unit_price_cents"] = pricing["unit_price_cents"]
    quote["commodity_cents"] = pricing["commodity_cents"]
    quote["freight_cents"] = pricing["freight_cents"]
    quote["total_cents"] = pricing["total_cents"]
    touch(quote)
    return success(quote_out(quote), "object", 200)


@bp.post("/api/quotes/<quote_id>/accept")
def accept_quote(quote_id):
    uid, _ = authorize(["Buyer"])
    body = get_body()
    expected_version = as_int(req(body, "expected_quote_version"), "expected_quote_version")
    quote = _load_quote(quote_id)
    # Expiry auto-transition fires before any other accept-time check.
    sweep_quote_if_expired(quote)
    if quote["status"] == "EXPIRED":
        raise ApiError(ERR_QUOTE_EXPIRED, 409, "the quote has expired")
    if expected_version != quote["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_quote_version does not match the quote's current version")
    if quote["status"] != "ISSUED":
        raise ApiError(ERR_QUOTE_NOT_ISSUABLE, 409, "only an ISSUED quote can be accepted")
    _check_quote_owner(quote, uid)
    buyer = store["buyers"].get(quote["buyer_id"])
    if buyer is None or buyer["status"] != "ACTIVE":
        raise ApiError(ERR_BUYER_SUSPENDED, 422, "buyer is suspended")
    # Fiscal check, evaluated last; equality with the limit is allowed.
    if buyer["credit_used_cents"] + quote["total_cents"] > buyer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402,
                       "acceptance would push credit_used_cents above credit_limit_cents")
    quote["status"] = "ACCEPTED"
    touch(quote)
    # Cascade hop 1: create the Contract from the accepted quote.
    contract = stamp_new({
        "id": new_id(),
        "quote_id": quote["id"],
        "buyer_id": quote["buyer_id"],
        "quality_tier": quote["quality_tier"],
        "forage_type": quote["forage_type"],
        "committed_tons": quote["tons"],
        "unit_price_cents": quote["unit_price_cents"],
        "total_reserved_cents": quote["total_cents"],
        "delivery_deadline": quote["requested_delivery_by"],
        "delivered_tons": Decimal("0.0"),
        "open_allocated_tons": Decimal("0.0"),
        "status": "ACTIVE",
    })
    store["contracts"][contract["id"]] = contract
    # Cascade hop 2: reserve the buyer's credit.
    buyer["credit_used_cents"] = buyer["credit_used_cents"] + quote["total_cents"]
    touch(buyer)
    return success(quote_out(quote), "object", 200)


@bp.post("/api/quotes/<quote_id>/decline")
def decline_quote(quote_id):
    uid, _ = authorize(["Buyer"])
    quote = _load_quote(quote_id)
    sweep_quote_if_expired(quote)
    _check_quote_owner(quote, uid)
    if quote["status"] != "ISSUED":
        raise ApiError(ERR_QUOTE_NOT_ISSUABLE, 409, "only an ISSUED quote can be declined")
    quote["status"] = "DECLINED"
    touch(quote)
    return success(quote_out(quote), "object", 200)


# --- Contract -----------------------------------------------------------------

@bp.get("/api/contracts")
def list_contracts():
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Buyer"])
    items = list(store["contracts"].values())
    buyer_filter = request.args.get("buyer_id")
    if role == "Buyer":
        buyer_filter = uid
    quote_filter = request.args.get("quote_id")
    status_filter = request.args.get("status")
    if buyer_filter is not None:
        items = [c for c in items if c["buyer_id"] == buyer_filter]
    if quote_filter is not None:
        items = [c for c in items if c["quote_id"] == quote_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([contract_out(c) for c in page], "array", 200, meta)


@bp.get("/api/contracts/<contract_id>")
def get_contract(contract_id):
    uid, role = authorize(["PlatformAdmin", "BrokerOps", "Buyer"])
    contract = store["contracts"].get(contract_id)
    if contract is None:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, 404, "contract not found")
    if role == "Buyer" and contract["buyer_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "buyers may only read their own contracts")
    return success(contract_out(contract), "object", 200)


@bp.post("/api/contracts/<contract_id>/cancel")
def cancel_contract(contract_id):
    authorize(["PlatformAdmin"])
    contract = store["contracts"].get(contract_id)
    if contract is None:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, 404, "contract not found")
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "contract must be ACTIVE or SUSPENDED to cancel")
    contract["status"] = "CANCELLED"
    touch(contract)
    contract_close_side_effects(contract)
    return success(contract_out(contract), "object", 200)


@bp.post("/api/contracts/<contract_id>/declare-default")
def declare_default(contract_id):
    authorize(["PlatformAdmin"])
    contract = store["contracts"].get(contract_id)
    if contract is None:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, 404, "contract not found")
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "contract must be ACTIVE or SUSPENDED to declare default")
    if get_clock().date() <= contract["delivery_deadline"]:
        raise ApiError(ERR_DEADLINE_NOT_PASSED, 422, "delivery_deadline has not passed")
    contract["status"] = "DEFAULTED"
    touch(contract)
    contract_close_side_effects(contract)
    return success(contract_out(contract), "object", 200)
