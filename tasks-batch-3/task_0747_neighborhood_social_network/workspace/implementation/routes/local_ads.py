"""LocalAd endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from clock import CLOCK, parse_iso, iso_format
from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    InvalidState,
    InvalidTimeWindow,
    InvalidBudget,
    NeighborhoodEmergencyLockdown,
    AdExhausted,
)
from middleware import require_roles
from paging import apply_pagination
from response import success
from validators import as_str, as_int, as_list


bp = Blueprint("local_ads", __name__)


@bp.post("/neighborhood/local-ads")
@require_roles("BusinessOwner")
def create_ad():
    payload = request.get_json(silent=True) or {}
    business_id = as_str(payload, "business_id")
    target_neighborhood_ids = as_list(payload, "target_neighborhood_ids")
    budget_cents = as_int(payload, "budget_cents")
    bid_cents_per_impression = as_int(payload, "bid_cents_per_impression")
    start_at_str = as_str(payload, "start_at")
    end_at_str = as_str(payload, "end_at")

    b = DB.businesses.get(business_id)
    if b is None:
        raise ReferenceNotFound(f"Business {business_id} not found")
    if b["state"] != "VERIFIED_BUSINESS":
        raise InvalidState("business must be VERIFIED_BUSINESS to run ads")
    if b["id"] != g.user_id:
        raise Forbidden("Acting BusinessOwner does not own the specified business")

    # Validate every target neighborhood exists (body-carried FK)
    for tnid in target_neighborhood_ids:
        if not isinstance(tnid, str) or DB.neighborhoods.get(tnid) is None:
            raise ReferenceNotFound(f"Neighborhood {tnid} not found")

    try:
        start_at = parse_iso(start_at_str)
        end_at = parse_iso(end_at_str)
    except ValueError:
        raise InvalidRequest("start_at/end_at must be ISO 8601 timestamps")

    # Time window (priority 123)
    if not (end_at > start_at):
        raise InvalidTimeWindow("end_at must be strictly greater than start_at")

    # Fiscal (priority 160)
    if budget_cents < 1000 or bid_cents_per_impression < 1:
        raise InvalidBudget("budget_cents < 1000 or bid_cents_per_impression < 1")

    ad = {
        "business_id": business_id,
        "target_neighborhood_ids": list(target_neighborhood_ids),
        "budget_cents": budget_cents,
        "spend_cents": 0,
        "bid_cents_per_impression": bid_cents_per_impression,
        "state": "DRAFT",
        "start_at": iso_format(start_at),
        "end_at": iso_format(end_at),
    }
    stamp_new(ad)
    DB.local_ads[ad["id"]] = ad
    return success(ad, status=201)


@bp.get("/neighborhood/local-ads/<aid>")
@require_roles("BusinessOwner", "PlatformAdmin", "Moderator")
def get_ad(aid: str):
    ad = DB.local_ads.get(aid)
    if ad is None:
        raise NotFound(f"LocalAd {aid} not found")
    return success(ad)


@bp.get("/neighborhood/local-ads")
@require_roles("BusinessOwner", "PlatformAdmin", "Moderator")
def list_ads():
    bid = request.args.get("business_id")
    state = request.args.get("state")
    rows = list(DB.local_ads.values())
    if bid is not None:
        rows = [r for r in rows if r["business_id"] == bid]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/local-ads/<aid>/start")
@require_roles("BusinessOwner")
def start_ad(aid: str):
    ad = DB.local_ads.get(aid)
    if ad is None:
        raise NotFound(f"LocalAd {aid} not found")
    if ad["state"] != "DRAFT":
        raise InvalidState(f"LocalAd.state is {ad['state']}, expected DRAFT")
    if ad["business_id"] != g.user_id:
        raise Forbidden("Only the owning business may start the ad")
    now = CLOCK.now()
    start_at = parse_iso(ad["start_at"])
    end_at = parse_iso(ad["end_at"])
    if now < start_at:
        raise InvalidState("current clock < start_at")
    if now >= end_at:
        raise InvalidState("current clock >= end_at")
    if ad["spend_cents"] >= ad["budget_cents"]:
        raise InvalidState("spend_cents >= budget_cents; cannot start")

    # EMERGENCY posture check on any target neighborhood (priority 110)
    for tnid in ad["target_neighborhood_ids"]:
        n = DB.neighborhoods.get(tnid)
        if n is not None and n.get("safety_posture") == "EMERGENCY":
            raise NeighborhoodEmergencyLockdown(
                f"Neighborhood {tnid} is under EMERGENCY posture"
            )

    ad["state"] = "RUNNING"
    bump(ad)
    return success(ad)


@bp.post("/neighborhood/local-ads/<aid>/pause")
@require_roles("BusinessOwner")
def pause_ad(aid: str):
    ad = DB.local_ads.get(aid)
    if ad is None:
        raise NotFound(f"LocalAd {aid} not found")
    if ad["state"] != "RUNNING":
        raise InvalidState(f"LocalAd.state is {ad['state']}, expected RUNNING")
    if ad["business_id"] != g.user_id:
        raise Forbidden("Only the owning business may pause the ad")
    ad["state"] = "PAUSED"
    bump(ad)
    return success(ad)


@bp.post("/neighborhood/local-ads/<aid>/resume")
@require_roles("BusinessOwner")
def resume_ad(aid: str):
    ad = DB.local_ads.get(aid)
    if ad is None:
        raise NotFound(f"LocalAd {aid} not found")
    if ad["state"] != "PAUSED":
        raise InvalidState(f"LocalAd.state is {ad['state']}, expected PAUSED")
    if ad["business_id"] != g.user_id:
        raise Forbidden("Only the owning business may resume the ad")
    now = CLOCK.now()
    if now >= parse_iso(ad["end_at"]):
        raise InvalidState("current clock >= end_at")
    if ad["spend_cents"] >= ad["budget_cents"]:
        raise InvalidState("spend_cents >= budget_cents; cannot resume")
    ad["state"] = "RUNNING"
    bump(ad)
    return success(ad)


@bp.post("/neighborhood/local-ads/<aid>/serve-impression")
@require_roles("PlatformAdmin")
def serve_impression(aid: str):
    ad = DB.local_ads.get(aid)
    if ad is None:
        raise NotFound(f"LocalAd {aid} not found")
    payload = request.get_json(silent=True) or {}
    neighborhood_id = as_str(payload, "neighborhood_id")
    if DB.neighborhoods.get(neighborhood_id) is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")
    if neighborhood_id not in ad["target_neighborhood_ids"]:
        raise InvalidState("Neighborhood not in ad's target list")
    if ad["state"] != "RUNNING":
        raise InvalidState(f"LocalAd.state is {ad['state']}, expected RUNNING")

    now = CLOCK.now()
    if not (parse_iso(ad["start_at"]) <= now < parse_iso(ad["end_at"])):
        raise InvalidState("current clock outside [start_at, end_at)")

    remaining = ad["budget_cents"] - ad["spend_cents"]
    if remaining <= 0:
        raise AdExhausted("LocalAd already exhausted its budget")

    charge = min(ad["bid_cents_per_impression"], remaining)
    ad["spend_cents"] = ad["spend_cents"] + charge
    if ad["spend_cents"] >= ad["budget_cents"]:
        ad["state"] = "EXHAUSTED"
    bump(ad)
    return success(ad)
