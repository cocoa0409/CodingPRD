"""MarketplaceListing endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from clock import CLOCK, iso_format
from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    InvalidPrice,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    ResidentSuspended,
    NotVerifiedInNeighborhood,
    NeighborhoodEmergencyLockdown,
    InvalidState,
    CannotReserveOwn,
    NotOwner,
)
from middleware import require_roles
from paging import apply_pagination
from response import success
from services import RESERVATION_HOURS
from validators import as_str, as_int, as_enum


bp = Blueprint("marketplace", __name__)

KINDS = {"FOR_SALE", "FREE", "WANTED", "RECOMMENDATION"}
ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


def _resident_verified_in(neighborhood_id: str, resident_id: str) -> bool:
    for m in DB.resident_memberships.values():
        if (
            m["resident_id"] == resident_id
            and m["neighborhood_id"] == neighborhood_id
            and m["status"] == "VERIFIED"
        ):
            return True
    return False


@bp.post("/neighborhood/marketplace-listings")
@require_roles("Resident", "BusinessOwner")
def create_listing():
    payload = request.get_json(silent=True) or {}
    seller_resident_id = as_str(payload, "seller_resident_id")
    neighborhood_id = as_str(payload, "neighborhood_id")
    title = as_str(payload, "title")
    price_cents = as_int(payload, "price_cents")
    kind = as_enum(payload, "kind", KINDS)

    seller = DB.residents.get(seller_resident_id)
    if seller is None:
        raise ReferenceNotFound(f"Resident {seller_resident_id} not found")
    n = DB.neighborhoods.get(neighborhood_id)
    if n is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")

    # Suspension check (priority 90) — applies to acting Resident
    if g.user_role == "Resident":
        acting = DB.residents.get(g.user_id)
        if acting is not None and acting.get("is_suspended", False):
            raise ResidentSuspended("Resident is suspended")

    # Verified-in-neighborhood (priority 100) — applies to acting Resident
    if g.user_role == "Resident":
        if not _resident_verified_in(neighborhood_id, g.user_id):
            raise NotVerifiedInNeighborhood(
                "Acting resident is not verified in the target neighborhood"
            )

    # EMERGENCY posture lockdown (priority 110)
    if n.get("safety_posture") == "EMERGENCY":
        raise NeighborhoodEmergencyLockdown(
            "Neighborhood is under EMERGENCY posture; marketplace creation blocked"
        )

    # Fiscal check (priority 161)
    if price_cents < 0 or price_cents > 100_000_000:
        raise InvalidPrice("price_cents outside [0, 100000000]")

    m = {
        "seller_resident_id": seller_resident_id,
        "neighborhood_id": neighborhood_id,
        "title": title,
        "price_cents": price_cents,
        "kind": kind,
        "state": "ACTIVE",
        "reserved_for_resident_id": None,
        "reserved_until": None,
    }
    stamp_new(m)
    DB.marketplace_listings[m["id"]] = m
    return success(m, status=201)


@bp.get("/neighborhood/marketplace-listings/<mid>")
@require_roles(*ALL_ROLES)
def get_listing(mid: str):
    m = DB.marketplace_listings.get(mid)
    if m is None:
        raise NotFound(f"MarketplaceListing {mid} not found")
    return success(m)


@bp.get("/neighborhood/marketplace-listings")
@require_roles(*ALL_ROLES)
def list_listings():
    nid = request.args.get("neighborhood_id")
    sid = request.args.get("seller_resident_id")
    rid = request.args.get("reserved_for_resident_id")
    state = request.args.get("state")
    kind = request.args.get("kind")
    rows = list(DB.marketplace_listings.values())
    if nid is not None:
        rows = [r for r in rows if r["neighborhood_id"] == nid]
    if sid is not None:
        rows = [r for r in rows if r["seller_resident_id"] == sid]
    if rid is not None:
        rows = [r for r in rows if r.get("reserved_for_resident_id") == rid]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/marketplace-listings/<mid>/reserve")
@require_roles("Resident")
def reserve_listing(mid: str):
    m = DB.marketplace_listings.get(mid)
    if m is None:
        raise NotFound(f"MarketplaceListing {mid} not found")
    if m["state"] != "ACTIVE":
        raise InvalidState(f"MarketplaceListing.state is {m['state']}, expected ACTIVE")

    # verified-in-neighborhood
    if not _resident_verified_in(m["neighborhood_id"], g.user_id):
        raise NotVerifiedInNeighborhood(
            "Acting resident is not verified in this listing's neighborhood"
        )

    if m["seller_resident_id"] == g.user_id:
        raise CannotReserveOwn("Cannot reserve your own listing")

    now = CLOCK.now()
    m["state"] = "RESERVED"
    m["reserved_for_resident_id"] = g.user_id
    m["reserved_until"] = iso_format(now + timedelta(hours=RESERVATION_HOURS))
    bump(m)
    return success(m)


@bp.post("/neighborhood/marketplace-listings/<mid>/confirm-sold")
@require_roles("Resident", "BusinessOwner")
def confirm_sold(mid: str):
    m = DB.marketplace_listings.get(mid)
    if m is None:
        raise NotFound(f"MarketplaceListing {mid} not found")
    if m["state"] != "RESERVED":
        raise InvalidState(f"MarketplaceListing.state is {m['state']}, expected RESERVED")
    if m["seller_resident_id"] != g.user_id:
        raise NotOwner("Only the seller may confirm the sale")
    m["state"] = "SOLD"
    bump(m)

    # Recompute business.recommendation_count if kind=RECOMMENDATION
    # (Recommendation counts recommendation listings that are SOLD)
    if m["kind"] == "RECOMMENDATION":
        # SCAFFOLD says recommendation_count is derived from listings. Not tied to a specific business FK,
        # so this is a no-op at listing-level; we leave the business's count as-is (no business_id on listing).
        pass
    return success(m)


@bp.post("/neighborhood/marketplace-listings/<mid>/withdraw")
@require_roles("Resident", "BusinessOwner")
def withdraw_listing(mid: str):
    m = DB.marketplace_listings.get(mid)
    if m is None:
        raise NotFound(f"MarketplaceListing {mid} not found")
    if m["state"] != "ACTIVE":
        raise InvalidState(f"MarketplaceListing.state is {m['state']}, expected ACTIVE")
    if m["seller_resident_id"] != g.user_id:
        raise NotOwner("Only the seller may withdraw")
    m["state"] = "WITHDRAWN"
    m["reserved_for_resident_id"] = None
    m["reserved_until"] = None
    bump(m)
    return success(m)
