"""MobilePaymentToken routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..common import bump, check_occ, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import mobile_token_view
from ..store import store


bp = Blueprint("mobile_tokens", __name__, url_prefix="/transit/mobile-tokens")


VALID_PROVIDERS = {"APPLE_PAY", "GOOGLE_PAY", "SAMSUNG_PAY"}


@bp.post("")
@require_auth("Rider")
def create_token():
    body = get_json_body()
    require_fields(body, "rider_id", "wallet_provider", "device_fingerprint")
    rider_id = body["rider_id"]
    provider = body["wallet_provider"]
    fingerprint = body["device_fingerprint"]
    bound_card_id = body.get("bound_card_id")
    if provider not in VALID_PROVIDERS:
        raise ApiError("ERR_VALIDATION", "invalid wallet_provider")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ApiError("ERR_VALIDATION", "device_fingerprint is required")

    with store.lock:
        if g.user_id != rider_id:
            raise ApiError("ERR_FORBIDDEN", "Riders may only register tokens on their own rider_id")
        if rider_id not in store.riders:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Rider not found")
        if bound_card_id is not None:
            card = store.cards.get(bound_card_id)
            if card is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "FareCard not found")
            if card["rider_id"] != rider_id:
                raise ApiError("ERR_FORBIDDEN", "Card does not belong to this rider")
        # (rider_id, device_fingerprint) uniqueness
        for tok in store.mobile_tokens.values():
            if tok["rider_id"] == rider_id and tok["device_fingerprint"] == fingerprint:
                raise ApiError("ERR_DEVICE_ALREADY_BOUND", "Device already bound for this rider")
        token = {
            "rider_id": rider_id,
            "wallet_provider": provider,
            "device_fingerprint": fingerprint,
            "status": "ACTIVE",
            "bound_card_id": bound_card_id,
        }
        stamp_new(token)
        store.mobile_tokens[token["id"]] = token
        if bound_card_id is not None:
            card = store.cards[bound_card_id]
            card["mobile_token_id"] = token["id"]
            bump(card)
    return respond(mobile_token_view(token), 201)


@bp.post("/<token_id>/revoke")
@require_auth("Rider", "AgencyOfficer")
def revoke_token(token_id: str):
    body = get_json_body()
    with store.lock:
        token = store.mobile_tokens.get(token_id)
        if token is None:
            raise ApiError("ERR_NOT_FOUND", "Mobile token not found")
        if g.user_role == "Rider" and token["rider_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Riders may only revoke their own tokens")
        if token["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Token is not ACTIVE")
        check_occ(token, body.get("version"))
        token["status"] = "REVOKED"
        bump(token)
    return respond(mobile_token_view(token), 200)
