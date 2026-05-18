"""/buyers endpoints + ranked listing-matches for a buyer."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import (
    err_forbidden_not_owner,
    err_invalid_buyer_fields,
    err_invalid_state,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    check_version_if_present,
    enforce_buyer_side_ownership,
    get_buyer_or_404,
    get_json,
    parse_pagination,
)
from services.calculations import buyer_match_score, rank_candidates
from services.serializers import buyer as serialize_buyer
from services.state_machine import bump_version
from utils import is_half_step, new_uuid, to_decimal


bp = Blueprint("buyers", __name__)


def _validate_buyer_fields(
    max_price_cents,
    min_price_cents,
    min_bedrooms,
    min_bathrooms,
    desired_zips,
):
    if not isinstance(min_price_cents, int) or isinstance(min_price_cents, bool):
        raise err_invalid_buyer_fields("min_price_cents must be an integer.")
    if not isinstance(max_price_cents, int) or isinstance(max_price_cents, bool):
        raise err_invalid_buyer_fields("max_price_cents must be an integer.")
    if min_price_cents > max_price_cents:
        raise err_invalid_buyer_fields(
            "min_price_cents must be <= max_price_cents."
        )
    if not isinstance(min_bedrooms, int) or isinstance(min_bedrooms, bool):
        raise err_invalid_buyer_fields("min_bedrooms must be an integer.")
    if min_bedrooms < 0 or min_bedrooms > 20:
        raise err_invalid_buyer_fields("min_bedrooms must be in [0, 20].")
    if not is_half_step(min_bathrooms):
        raise err_invalid_buyer_fields("min_bathrooms must be a multiple of 0.5.")
    if not isinstance(desired_zips, list) or len(desired_zips) == 0:
        raise err_invalid_buyer_fields("desired_zips must be a non-empty array.")
    for z in desired_zips:
        if not isinstance(z, str) or not z.isdigit() or len(z) != 5:
            raise err_invalid_buyer_fields("each desired_zip must be 5 digits.")


@bp.post("/buyers")
@require_auth(["BuyerAgent"])
def create_buyer():
    body = get_json()
    buyer_agent_id = body.get("buyer_agent_id")
    full_name = body.get("full_name")
    max_price_cents = body.get("max_price_cents")
    min_price_cents = body.get("min_price_cents")
    min_bedrooms = body.get("min_bedrooms")
    min_bathrooms = body.get("min_bathrooms")
    desired_zips = body.get("desired_zips")
    desired_features = body.get("desired_features") or []

    if not isinstance(buyer_agent_id, str) or buyer_agent_id != g.user_id:
        raise err_forbidden_not_owner(
            "buyer_agent_id must equal the authenticated BuyerAgent's X-User-ID."
        )
    if not isinstance(full_name, str) or not full_name:
        raise err_invalid_buyer_fields("full_name is required.")
    if not isinstance(desired_features, list):
        raise err_invalid_buyer_fields("desired_features must be an array.")

    _validate_buyer_fields(
        max_price_cents, min_price_cents, min_bedrooms, min_bathrooms, desired_zips
    )

    now = store.now()
    buyer = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "buyer_agent_id": buyer_agent_id,
        "full_name": full_name,
        "max_price_cents": int(max_price_cents),
        "min_price_cents": int(min_price_cents),
        "min_bedrooms": int(min_bedrooms),
        "min_bathrooms": float(min_bathrooms),
        "desired_zips": list(desired_zips),
        "desired_features": list(desired_features),
        "status": "ACTIVE",
    }
    store.buyers[buyer["id"]] = buyer
    return success(serialize_buyer(buyer), 201)


@bp.get("/buyers/<buyer_id>")
@require_auth(["BuyerAgent", "MlsAdmin"])
def get_buyer(buyer_id):
    b = get_buyer_or_404(buyer_id)
    return success(serialize_buyer(b), 200)


@bp.patch("/buyers/<buyer_id>")
@require_auth(["BuyerAgent"])
def patch_buyer(buyer_id):
    body = get_json()
    with store.lock:
        b = get_buyer_or_404(buyer_id)
        enforce_buyer_side_ownership(b)
        check_version_if_present(b, body)

        new_max = body.get("max_price_cents", b["max_price_cents"])
        new_min = body.get("min_price_cents", b["min_price_cents"])
        new_min_bed = body.get("min_bedrooms", b["min_bedrooms"])
        new_min_bath = body.get("min_bathrooms", b["min_bathrooms"])
        new_zips = body.get("desired_zips", b["desired_zips"])
        new_feats = body.get("desired_features", b["desired_features"])

        if not isinstance(new_feats, list):
            raise err_invalid_buyer_fields("desired_features must be an array.")

        _validate_buyer_fields(new_max, new_min, new_min_bed, new_min_bath, new_zips)

        b["max_price_cents"] = int(new_max)
        b["min_price_cents"] = int(new_min)
        b["min_bedrooms"] = int(new_min_bed)
        b["min_bathrooms"] = float(new_min_bath)
        b["desired_zips"] = list(new_zips)
        b["desired_features"] = list(new_feats)

        if "status" in body and body["status"] is not None:
            new_status = body["status"]
            if new_status not in ("ACTIVE", "WITHDRAWN", "SOLD"):
                raise err_invalid_state("status must be ACTIVE, WITHDRAWN, or SOLD.")
            b["status"] = new_status

        bump_version(b, store.now())
    return success(serialize_buyer(b), 200)


@bp.get("/buyers/<buyer_id>/matches")
@require_auth(["BuyerAgent", "MlsAdmin"])
def buyer_matches(buyer_id):
    buyer = get_buyer_or_404(buyer_id)
    limit, offset = parse_pagination()
    candidates = [l for l in store.listings.values() if l["status"] == "ACTIVE"]
    pairs = [(l, buyer_match_score(l, buyer)) for l in candidates]
    ranked = rank_candidates(pairs)
    payload = [{"listing_id": l["id"], "score": float(s)} for l, s in ranked]
    total = len(payload)
    page = payload[offset : offset + limit]
    return list_success(page, limit, offset, total, 200)
