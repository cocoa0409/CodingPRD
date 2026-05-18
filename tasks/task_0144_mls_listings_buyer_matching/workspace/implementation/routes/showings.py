"""/listings/{listing_id}/showings* endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from config import MAX_SHOWING_DURATION_SEC, MIN_SHOWING_DURATION_SEC
from db import store
from errors import (
    err_forbidden_not_owner,
    err_invalid_showing_window,
    err_invalid_state,
    err_lockbox_not_armed,
    err_not_found,
    err_showing_time_overlap,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    enforce_buyer_side_ownership,
    enforce_listing_side_ownership,
    get_buyer_or_404,
    get_json,
    get_listing_or_404,
    get_showing_in_listing_or_404,
    parse_required_iso,
)
from services.serializers import showing as serialize_showing
from services.state_machine import (
    bump_version,
    recompute_showing_count,
)
from utils import new_uuid


bp = Blueprint("showings", __name__)


@bp.post("/listings/<listing_id>/showings")
@require_auth(["BuyerAgent"])
def request_showing(listing_id):
    body = get_json()
    listing = get_listing_or_404(listing_id)

    buyer_agent_id = body.get("buyer_agent_id")
    buyer_id = body.get("buyer_id")

    if buyer_agent_id != g.user_id:
        raise err_forbidden_not_owner(
            "buyer_agent_id must equal the authenticated BuyerAgent's X-User-ID."
        )
    if not isinstance(buyer_id, str):
        raise err_invalid_showing_window("buyer_id is required.")
    buyer = get_buyer_or_404(buyer_id)
    enforce_buyer_side_ownership(buyer)

    start_at = parse_required_iso(
        body, "start_at", err_invalid_showing_window("start_at is required.")
    )
    end_at = parse_required_iso(
        body, "end_at", err_invalid_showing_window("end_at is required.")
    )
    if end_at <= start_at:
        raise err_invalid_showing_window("end_at must be strictly after start_at.")
    duration = (end_at - start_at).total_seconds()
    if duration < MIN_SHOWING_DURATION_SEC or duration > MAX_SHOWING_DURATION_SEC:
        raise err_invalid_showing_window(
            "Showing duration must be between 15 minutes and 4 hours."
        )
    now = store.now()
    if start_at <= now:
        raise err_invalid_showing_window("start_at must be strictly in the future.")

    s = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "listing_id": listing_id,
        "buyer_agent_id": buyer_agent_id,
        "buyer_id": buyer_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "REQUESTED",
        "lockbox_access_granted_at": None,
    }
    store.showings[s["id"]] = s
    return success(serialize_showing(s), 201)


def _interval_overlaps(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end) overlap. Adjacency at boundary is allowed."""
    return a_start < b_end and b_start < a_end


@bp.post("/listings/<listing_id>/showings/<showing_id>/approve")
@require_auth(["ListingAgent"])
def approve_showing(listing_id, showing_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        s = get_showing_in_listing_or_404(listing_id, showing_id)

        if s["status"] != "REQUESTED":
            raise err_invalid_state("Showing must be REQUESTED to approve.")
        if listing["status"] != "ACTIVE":
            raise err_invalid_state("Listing must be ACTIVE to approve showings.")

        # Lockbox must exist + be ARMED.
        lb_id = store.lockbox_by_listing.get(listing_id)
        lb = store.lockboxes.get(lb_id) if lb_id else None
        if lb is None or lb["status"] != "ARMED":
            raise err_lockbox_not_armed(
                "Lockbox must be ARMED before a showing can be approved."
            )

        # Overlap check against SCHEDULED siblings on the same listing.
        for other in store.showings.values():
            if other["id"] == s["id"]:
                continue
            if other["listing_id"] != listing_id:
                continue
            if other["status"] != "SCHEDULED":
                continue
            if _interval_overlaps(s["start_at"], s["end_at"], other["start_at"], other["end_at"]):
                raise err_showing_time_overlap()

        now = store.now()
        s["status"] = "SCHEDULED"
        s["lockbox_access_granted_at"] = now
        bump_version(s, now)

        # Lockbox: rotate access_code on grant (PRD §2.8 "regenerated on every
        # successful access grant").
        lb["access_code"] = __import__("utils").new_access_code()
        lb["code_rotated_at"] = now
        bump_version(lb, now)

        # Refresh showing_count.
        recompute_showing_count(listing, now)

        payload = serialize_showing(s)
        payload["access_code"] = lb["access_code"]
    return success(payload, 200)


@bp.post("/listings/<listing_id>/showings/<showing_id>/complete")
@require_auth(["BuyerAgent"])
def complete_showing(listing_id, showing_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        s = get_showing_in_listing_or_404(listing_id, showing_id)
        buyer = store.buyers.get(s["buyer_id"])
        if buyer is None:
            raise err_not_found("Buyer not found.")
        enforce_buyer_side_ownership(buyer)

        if s["status"] != "SCHEDULED":
            raise err_invalid_state("Showing must be SCHEDULED to complete.")
        if s.get("lockbox_access_granted_at") is None:
            raise err_invalid_state("Lockbox access was not granted for this showing.")
        now = store.now()
        if now < s["end_at"]:
            raise err_invalid_state(
                "Showing cannot be completed before its end_at."
            )

        s["status"] = "COMPLETED"
        bump_version(s, now)
        recompute_showing_count(listing, now)
    return success(serialize_showing(s), 200)


@bp.post("/listings/<listing_id>/showings/<showing_id>/cancel")
@require_auth(["ListingAgent", "BuyerAgent"])
def cancel_showing(listing_id, showing_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        s = get_showing_in_listing_or_404(listing_id, showing_id)

        # Ownership: ListingAgent must own the listing OR BuyerAgent must own the buyer.
        if g.role == "ListingAgent":
            enforce_listing_side_ownership(listing)
        else:  # BuyerAgent
            buyer = store.buyers.get(s["buyer_id"])
            if buyer is None:
                raise err_not_found("Buyer not found.")
            enforce_buyer_side_ownership(buyer)

        if s["status"] not in ("REQUESTED", "SCHEDULED"):
            raise err_invalid_state(
                "Only REQUESTED or SCHEDULED showings can be cancelled."
            )
        now = store.now()
        if s["status"] == "SCHEDULED":
            if now >= s["start_at"]:
                raise err_invalid_state(
                    "Cannot cancel a SCHEDULED showing at or after start_at."
                )
        was_scheduled = s["status"] == "SCHEDULED"
        s["status"] = "CANCELLED"
        bump_version(s, now)
        if was_scheduled:
            recompute_showing_count(listing, now)
    return success(serialize_showing(s), 200)
