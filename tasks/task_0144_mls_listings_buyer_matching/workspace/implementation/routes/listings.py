"""/listings CRUD + ranked buyer-matches endpoint."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from config import (
    MAX_CO_OP_PCT,
    MAX_TOTAL_COMMISSION_PCT,
    MIN_LIST_PRICE_CENTS,
)
from db import store
from errors import (
    err_forbidden_not_owner,
    err_invalid_listing_fields,
    err_invalid_state,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    check_version_if_present,
    enforce_listing_side_ownership,
    get_int,
    get_json,
    get_listing_or_404,
    parse_pagination,
    sort_by_created_at,
)
from services.calculations import buyer_match_score, rank_candidates
from services.serializers import buyer as serialize_buyer
from services.serializers import listing as serialize_listing
from services.state_machine import (
    bump_version,
    withdraw_listing_cascade,
    close_listing_cascade,
)
from utils import is_half_step, new_uuid, to_decimal


bp = Blueprint("listings", __name__)


def _validate_listing_payload(
    list_price_cents,
    bedrooms,
    bathrooms,
    co_op_pct,
    total_commission_pct,
    zip_code,
):
    if not isinstance(list_price_cents, int) or isinstance(list_price_cents, bool):
        raise err_invalid_listing_fields("list_price_cents must be an integer.")
    if list_price_cents < MIN_LIST_PRICE_CENTS:
        raise err_invalid_listing_fields("list_price_cents below minimum.")
    if not isinstance(bedrooms, int) or isinstance(bedrooms, bool) or bedrooms < 0 or bedrooms > 20:
        raise err_invalid_listing_fields("bedrooms must be int 0..20.")
    if not is_half_step(bathrooms) or to_decimal(bathrooms) > 20:
        raise err_invalid_listing_fields("bathrooms must be a multiple of 0.5 in [0, 20].")
    if not isinstance(zip_code, str) or not zip_code.isdigit() or len(zip_code) != 5:
        raise err_invalid_listing_fields("zip_code must be exactly 5 digits.")
    co_op_d = to_decimal(co_op_pct)
    total_d = to_decimal(total_commission_pct)
    if co_op_d < 0 or co_op_d > to_decimal(MAX_CO_OP_PCT):
        raise err_invalid_listing_fields("co_op_pct must be in [0, 0.06].")
    if total_d < co_op_d or total_d > to_decimal(MAX_TOTAL_COMMISSION_PCT):
        raise err_invalid_listing_fields(
            "total_commission_pct must be in [co_op_pct, 0.10]."
        )
    return co_op_d, total_d


@bp.post("/listings")
@require_auth(["ListingAgent"])
def create_listing():
    body = get_json()
    listing_agent_id = body.get("listing_agent_id")
    address_line = body.get("address_line")
    zip_code = body.get("zip_code")
    list_price_cents = body.get("list_price_cents")
    bedrooms = body.get("bedrooms")
    bathrooms = body.get("bathrooms")
    features = body.get("features") or []
    co_op_pct = body.get("co_op_pct")
    total_commission_pct = body.get("total_commission_pct")

    if not isinstance(listing_agent_id, str) or listing_agent_id != g.user_id:
        raise err_forbidden_not_owner(
            "listing_agent_id must equal the authenticated ListingAgent's X-User-ID."
        )
    if not isinstance(address_line, str) or not address_line:
        raise err_invalid_listing_fields("address_line is required.")
    if not isinstance(features, list):
        raise err_invalid_listing_fields("features must be an array.")

    co_op_d, total_d = _validate_listing_payload(
        list_price_cents, bedrooms, bathrooms, co_op_pct, total_commission_pct, zip_code
    )

    now = store.now()
    listing = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "listing_agent_id": listing_agent_id,
        "address_line": address_line,
        "zip_code": zip_code,
        "list_price_cents": int(list_price_cents),
        "bedrooms": int(bedrooms),
        "bathrooms": float(bathrooms),
        "features": list(features),
        "co_op_pct": co_op_d,
        "total_commission_pct": total_d,
        "status": "ACTIVE",
        "accepted_offer_id": None,
        "showing_count": 0,
    }
    store.listings[listing["id"]] = listing
    return success(serialize_listing(listing), 201)


@bp.get("/listings/<listing_id>")
@require_auth(["ListingAgent", "BuyerAgent", "MlsAdmin"])
def get_listing(listing_id):
    l = get_listing_or_404(listing_id)
    return success(serialize_listing(l), 200)


@bp.get("/listings")
@require_auth(["ListingAgent", "BuyerAgent", "MlsAdmin"])
def list_listings():
    status = request.args.get("status")
    zip_code = request.args.get("zip_code")
    min_price = request.args.get("min_price_cents")
    max_price = request.args.get("max_price_cents")
    limit, offset = parse_pagination()

    try:
        min_price_i = int(min_price) if min_price is not None else None
    except ValueError:
        min_price_i = None
    try:
        max_price_i = int(max_price) if max_price is not None else None
    except ValueError:
        max_price_i = None

    rows = list(store.listings.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if zip_code:
        rows = [r for r in rows if r["zip_code"] == zip_code]
    if min_price_i is not None:
        rows = [r for r in rows if r["list_price_cents"] >= min_price_i]
    if max_price_i is not None:
        rows = [r for r in rows if r["list_price_cents"] <= max_price_i]

    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([serialize_listing(r) for r in page], limit, offset, total, 200)


@bp.patch("/listings/<listing_id>")
@require_auth(["ListingAgent"])
def patch_listing(listing_id):
    body = get_json()
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        check_version_if_present(listing, body)

        # Optional fields.
        new_price = body.get("list_price_cents", listing["list_price_cents"])
        new_features = body.get("features", listing["features"])
        new_co_op = body.get("co_op_pct", listing["co_op_pct"])
        new_total = body.get("total_commission_pct", listing["total_commission_pct"])

        if not isinstance(new_features, list):
            raise err_invalid_listing_fields("features must be an array.")

        # Validate using existing zip / bed / bath since they're not patchable here.
        co_op_d, total_d = _validate_listing_payload(
            new_price,
            listing["bedrooms"],
            listing["bathrooms"],
            new_co_op,
            new_total,
            listing["zip_code"],
        )

        listing["list_price_cents"] = int(new_price)
        listing["features"] = list(new_features)
        listing["co_op_pct"] = co_op_d
        listing["total_commission_pct"] = total_d
        bump_version(listing, store.now())
    return success(serialize_listing(listing), 200)


@bp.post("/listings/<listing_id>/withdraw")
@require_auth(["ListingAgent"])
def withdraw_listing(listing_id):
    body = get_json()
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        check_version_if_present(listing, body)
        if listing["status"] != "ACTIVE":
            raise err_invalid_state("Listing must be ACTIVE to withdraw.")
        # No SUBMITTED offer must exist.
        has_submitted = any(
            o["status"] == "SUBMITTED" and o["listing_id"] == listing_id
            for o in store.offers.values()
        )
        if has_submitted:
            raise err_invalid_state(
                "Cannot withdraw a listing while SUBMITTED offers exist."
            )
        withdraw_listing_cascade(listing, store.now())
    return success(serialize_listing(listing), 200)


@bp.post("/listings/<listing_id>/close")
@require_auth(["ListingAgent"])
def close_listing(listing_id):
    body = get_json()
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        check_version_if_present(listing, body)
        if listing["status"] != "UNDER_CONTRACT":
            raise err_invalid_state("Listing must be UNDER_CONTRACT to close.")
        accepted_id = listing.get("accepted_offer_id")
        if accepted_id is None:
            raise err_invalid_state("No accepted offer on this listing.")
        # All contingencies on the accepted offer must be SATISFIED or WAIVED.
        for c in store.contingencies.values():
            if c["offer_id"] == accepted_id and c["status"] not in ("SATISFIED", "WAIVED"):
                raise err_invalid_state(
                    "All contingencies must be SATISFIED or WAIVED to close."
                )
        close_listing_cascade(listing, store.now())
    return success(serialize_listing(listing), 200)


@bp.get("/listings/<listing_id>/buyer-matches")
@require_auth(["ListingAgent", "MlsAdmin"])
def listing_buyer_matches(listing_id):
    listing = get_listing_or_404(listing_id)
    limit, offset = parse_pagination()
    if listing["status"] != "ACTIVE":
        # Per PRD §3.4: "draw from active rows only — a candidate must have
        # status of ACTIVE to enter the pool". For listing-side query the
        # candidate set is buyers; the listing itself being non-ACTIVE means
        # the score still uses the listing — but the buyer pool must be
        # ACTIVE. Empty pool returns empty array, not an error.
        pass
    candidates = [b for b in store.buyers.values() if b["status"] == "ACTIVE"]
    pairs = [(b, buyer_match_score(listing, b)) for b in candidates]
    ranked = rank_candidates(pairs)
    payload = [{"buyer_id": b["id"], "score": float(s)} for b, s in ranked]
    total = len(payload)
    page = payload[offset : offset + limit]
    return list_success(page, limit, offset, total, 200)
