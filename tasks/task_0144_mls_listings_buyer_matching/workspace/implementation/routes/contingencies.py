"""/listings/{listing_id}/contingencies* endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import (
    err_contingency_already_failed,
    err_contingency_deadline_invalid,
    err_invalid_state,
    err_not_found,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    enforce_buyer_side_ownership,
    get_buyer_or_404,
    get_contingency_in_listing_or_404,
    get_json,
    get_listing_or_404,
    parse_required_iso,
)
from services.serializers import contingency as serialize_contingency
from services.state_machine import bump_version, fail_contingency_cascade
from utils import new_uuid


bp = Blueprint("contingencies", __name__)


VALID_KINDS = {"INSPECTION", "APPRAISAL", "FINANCING"}


@bp.post("/listings/<listing_id>/contingencies")
@require_auth(["BuyerAgent"])
def create_contingency(listing_id):
    body = get_json()
    listing = get_listing_or_404(listing_id)

    offer_id = body.get("offer_id")
    kind = body.get("kind")
    if not isinstance(offer_id, str):
        raise err_contingency_deadline_invalid("offer_id is required.")
    if kind not in VALID_KINDS:
        raise err_contingency_deadline_invalid("kind is invalid.")
    if listing.get("accepted_offer_id") != offer_id:
        # Only the accepted offer carries active contingencies.
        raise err_invalid_state(
            "offer_id must equal the listing's accepted_offer_id."
        )
    offer = store.offers.get(offer_id)
    if offer is None or offer["listing_id"] != listing_id:
        raise err_not_found("Offer not found on this listing.")

    # Ownership: the buyer behind the accepted offer.
    buyer = store.buyers.get(offer["buyer_id"])
    if buyer is None:
        raise err_not_found("Buyer not found.")
    enforce_buyer_side_ownership(buyer)

    if listing["status"] != "UNDER_CONTRACT":
        raise err_invalid_state(
            "Listing must be UNDER_CONTRACT to attach contingencies."
        )

    deadline_at = parse_required_iso(
        body, "deadline_at",
        err_contingency_deadline_invalid("deadline_at is required."),
    )
    now = store.now()
    if deadline_at <= now:
        raise err_contingency_deadline_invalid(
            "deadline_at must be strictly in the future."
        )
    # Strictly after the accepted offer's acceptance time (updated_at at the
    # moment of cascade represents the acceptance time on the offer row).
    acceptance_time = offer.get("updated_at")
    if acceptance_time is not None and deadline_at <= acceptance_time:
        raise err_contingency_deadline_invalid(
            "deadline_at must be strictly after the offer's acceptance time."
        )

    c = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "offer_id": offer_id,
        "kind": kind,
        "deadline_at": deadline_at,
        "status": "PENDING",
    }
    store.contingencies[c["id"]] = c
    return success(serialize_contingency(c), 201)


def _common_setup_for_action(listing_id, contingency_id):
    listing = get_listing_or_404(listing_id)
    c = get_contingency_in_listing_or_404(listing_id, contingency_id)
    offer = store.offers.get(c["offer_id"])
    if offer is None:
        raise err_not_found("Offer not found.")
    buyer = store.buyers.get(offer["buyer_id"])
    if buyer is None:
        raise err_not_found("Buyer not found.")
    enforce_buyer_side_ownership(buyer)
    return listing, c, offer


@bp.post("/listings/<listing_id>/contingencies/<contingency_id>/satisfy")
@require_auth(["BuyerAgent"])
def satisfy_contingency(listing_id, contingency_id):
    with store.lock:
        listing, c, _offer = _common_setup_for_action(listing_id, contingency_id)
        if c["status"] != "PENDING":
            raise err_invalid_state("Contingency must be PENDING to satisfy.")
        if listing["status"] != "UNDER_CONTRACT":
            raise err_invalid_state("Listing must be UNDER_CONTRACT to satisfy.")
        now = store.now()
        if now >= c["deadline_at"]:
            raise err_invalid_state(
                "Cannot satisfy a contingency past its deadline_at."
            )
        c["status"] = "SATISFIED"
        bump_version(c, now)
    return success(serialize_contingency(c), 200)


@bp.post("/listings/<listing_id>/contingencies/<contingency_id>/waive")
@require_auth(["BuyerAgent"])
def waive_contingency(listing_id, contingency_id):
    with store.lock:
        listing, c, _offer = _common_setup_for_action(listing_id, contingency_id)
        if c["status"] != "PENDING":
            raise err_invalid_state("Contingency must be PENDING to waive.")
        if listing["status"] != "UNDER_CONTRACT":
            raise err_invalid_state("Listing must be UNDER_CONTRACT to waive.")
        c["status"] = "WAIVED"
        bump_version(c, store.now())
    return success(serialize_contingency(c), 200)


@bp.post("/listings/<listing_id>/contingencies/<contingency_id>/fail")
@require_auth(["BuyerAgent"])
def fail_contingency(listing_id, contingency_id):
    with store.lock:
        listing, c, offer = _common_setup_for_action(listing_id, contingency_id)
        if c["status"] == "FAILED":
            raise err_contingency_already_failed()
        if c["status"] != "PENDING":
            raise err_invalid_state("Contingency must be PENDING to fail.")
        now = store.now()
        c["status"] = "FAILED"
        bump_version(c, now)
        # Cascade only if listing is UNDER_CONTRACT and this is on accepted offer.
        if (
            listing["status"] == "UNDER_CONTRACT"
            and listing.get("accepted_offer_id") == offer["id"]
        ):
            fail_contingency_cascade(c, listing, offer, now)
    return success(serialize_contingency(c), 200)
