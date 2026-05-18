"""/listings/{listing_id}/lockbox* endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import (
    err_invalid_state,
    err_lockbox_state,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    enforce_listing_side_ownership,
    get_json,
    get_listing_or_404,
    get_lockbox_of_listing_or_404,
)
from services.serializers import lockbox as serialize_lockbox
from services.state_machine import bump_version
from utils import new_access_code, new_uuid


bp = Blueprint("lockboxes", __name__)


@bp.post("/listings/<listing_id>/lockbox")
@require_auth(["ListingAgent"])
def mount_lockbox(listing_id):
    body = get_json()
    serial = body.get("serial_number")
    if not isinstance(serial, str) or not serial:
        raise err_invalid_state("serial_number is required.")
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        if listing["status"] != "ACTIVE":
            raise err_invalid_state("Listing must be ACTIVE to mount a lockbox.")
        if serial in store.lockbox_serials:
            raise err_invalid_state("Lockbox serial_number must be unique.")
        if store.lockbox_by_listing.get(listing_id):
            # Already a lockbox on this listing — scaffold says exactly one
            # active per listing. If existing one is RETIRED we could allow
            # mounting another; otherwise reject.
            existing_id = store.lockbox_by_listing[listing_id]
            existing = store.lockboxes.get(existing_id)
            if existing and existing["status"] != "RETIRED":
                raise err_invalid_state(
                    "Listing already has an active lockbox."
                )
        now = store.now()
        lb = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "listing_id": listing_id,
            "serial_number": serial,
            "access_code": new_access_code(),
            "code_rotated_at": now,
            "status": "ARMED",
        }
        store.lockboxes[lb["id"]] = lb
        store.lockbox_by_listing[listing_id] = lb["id"]
        store.lockbox_serials.add(serial)
    return success(serialize_lockbox(lb), 201)


@bp.post("/listings/<listing_id>/lockbox/arm")
@require_auth(["ListingAgent"])
def arm_lockbox(listing_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        lb = get_lockbox_of_listing_or_404(listing_id)
        if lb["status"] != "DISARMED":
            raise err_lockbox_state(
                "Lockbox must be DISARMED to arm."
            )
        if listing["status"] != "ACTIVE":
            raise err_invalid_state("Listing must be ACTIVE to arm a lockbox.")
        lb["status"] = "ARMED"
        lb["access_code"] = new_access_code()
        lb["code_rotated_at"] = store.now()
        bump_version(lb, store.now())
    return success(serialize_lockbox(lb), 200)


@bp.post("/listings/<listing_id>/lockbox/disarm")
@require_auth(["ListingAgent"])
def disarm_lockbox(listing_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        lb = get_lockbox_of_listing_or_404(listing_id)
        if lb["status"] != "ARMED":
            raise err_lockbox_state(
                "Lockbox must be ARMED to disarm."
            )
        lb["status"] = "DISARMED"
        bump_version(lb, store.now())
    return success(serialize_lockbox(lb), 200)


@bp.post("/listings/<listing_id>/lockbox/retire")
@require_auth(["ListingAgent"])
def retire_lockbox(listing_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        lb = get_lockbox_of_listing_or_404(listing_id)
        if lb["status"] != "DISARMED":
            raise err_lockbox_state(
                "Lockbox must be DISARMED to retire."
            )
        lb["status"] = "RETIRED"
        bump_version(lb, store.now())
    return success(serialize_lockbox(lb), 200)
