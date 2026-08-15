"""Reel slots and reel lifecycle (PRD 3.3, 3.4)."""
import db
import calc
from auth import require, check_theater_scope, ALL_ROLES
from envelope import success_object, success_list
from errors import (ApiError, not_found, bad_request, conflict, unprocessable,
                    ERR_STALE_VERSION, ERR_REEL_NOT_ASSEMBLING,
                    ERR_CAMPAIGN_NOT_BOOKABLE, ERR_RATING_PLACEMENT_VIOLATION,
                    ERR_CATEGORY_EXCLUSIVITY_CONFLICT, ERR_SLOT_INTERVAL_OVERLAP,
                    ERR_POOL_CAPACITY_EXCEEDED, ERR_OUTSIDE_FLIGHT_WINDOW,
                    ERR_BUDGET_EXCEEDED, ERR_INVALID_STATE_TRANSITION,
                    ERR_REEL_NOT_LOCKABLE, ERR_DELIVERY_LATE,
                    ERR_REEL_NOT_RECONCILABLE)
from serializers import ser_slot, ser_reel
from validate import (get_body, req_str, req_int, req_enum, pagination)

from . import bp

SALES = {"SalesManager"}
OPS = {"NetworkOps"}
THEATER = {"TheaterOps"}

# Rating-based placement (PRD 3.3).
RATING_GATES = {
    "ALCOHOL": {"R", "NC17"},
    "POLITICAL": {"PG13", "R", "NC17"},
}


def _pool_of(campaign):
    advertiser = db.advertisers[campaign["advertiser_id"]]
    return ("national" if advertiser["advertiser_type"] == "NATIONAL"
            else "local")


def _get_slot_or_404(slot_id):
    s = db.slots.get(slot_id)
    if s is None:
        raise not_found("slot not found")
    return s


def _get_reel_or_404(reel_id):
    r = db.reels.get(reel_id)
    if r is None:
        raise not_found("reel not found")
    return r


def _theater_id_of_showtime(showtime):
    screen = db.screens[showtime["screen_id"]]
    return screen["theater_id"]


# ------------------------------ Slot reserve --------------------------------

@bp.post("/network/reels/<reel_id>/slots")
def create_slot(reel_id):
    require(SALES)
    body = get_body()
    # Priority 4: request shape.
    campaign_id = req_str(body, "campaign_id")
    start = req_int(body, "start_offset_seconds", minimum=0)
    duration = req_int(body, "duration_seconds", minimum=1)
    expected_version = req_int(body, "expected_reel_version")

    # Priority 5: path id first, then body FK.
    reel = _get_reel_or_404(reel_id)
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise not_found("campaign not found")

    # Priority 7: state — path resource (reel) before body resource (campaign).
    if reel["reel_status"] != "ASSEMBLING":
        raise conflict(ERR_REEL_NOT_ASSEMBLING,
                       "reel is no longer ASSEMBLING")
    if campaign["campaign_status"] != "APPROVED":
        raise conflict(ERR_CAMPAIGN_NOT_BOOKABLE,
                       "campaign is not APPROVED")
    # OCC (PRD 3.3 prose order: after the state tier).
    if expected_version != reel["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_reel_version does not match the reel's "
                       "current version")

    showtime = db.showtimes[reel["showtime_id"]]
    feature = db.features[showtime["feature_id"]]
    advertiser = db.advertisers[campaign["advertiser_id"]]

    # Priority 8: rating-based placement.
    gate = RATING_GATES.get(advertiser["category"])
    if gate is not None and feature["content_rating"] not in gate:
        raise unprocessable(
            ERR_RATING_PLACEMENT_VIOLATION,
            f"advertiser category {advertiser['category']} may not be placed "
            f"on a {feature['content_rating']} feature")

    # Priority 9: constraint tier, fixed order.
    live_slots = [s for s in calc.slots_of_reel(reel_id)
                  if s["slot_status"] != "CANCELED"]
    # (a) category exclusivity — no OTHER campaign's non-CANCELED slot in the
    # reel whose advertiser shares this category.
    for s in live_slots:
        if s["campaign_id"] == campaign_id:
            continue
        other_campaign = db.campaigns[s["campaign_id"]]
        other_advertiser = db.advertisers[other_campaign["advertiser_id"]]
        if other_advertiser["category"] == advertiser["category"]:
            raise conflict(ERR_CATEGORY_EXCLUSIVITY_CONFLICT,
                           "another non-CANCELED slot in this reel carries "
                           "the same advertiser category")
    # (b) half-open interval overlap (touching endpoints allowed)
    new_end = start + duration
    for s in live_slots:
        ex_start = s["start_offset_seconds"]
        ex_end = ex_start + s["duration_seconds"]
        if start < ex_end and ex_start < new_end:
            raise conflict(ERR_SLOT_INTERVAL_OVERLAP,
                           "slot interval intersects an existing slot")
    # (c) pool capacity (strict > rejects; exactly equal is allowed)
    pool = _pool_of(campaign)
    used_key = f"{pool}_used_seconds"
    cap_key = f"{pool}_pool_seconds"
    if reel[used_key] + duration > reel[cap_key]:
        raise unprocessable(ERR_POOL_CAPACITY_EXCEEDED,
                            f"slot would push the {pool} pool beyond its "
                            f"{reel[cap_key]} seconds")

    # Priority 10: temporal — showtime date within the flight window.
    d = calc.showtime_date(showtime)
    if not (campaign["_flight_start"] <= d <= campaign["_flight_end"]):
        raise unprocessable(ERR_OUTSIDE_FLIGHT_WINDOW,
                            "slot's showtime date is outside the campaign "
                            "flight window")

    # Priority 11: fiscal — budget cap (always last).
    estimated = calc.line_amount_cents(showtime["forecast_attendance"],
                                       campaign["cpm_cents"])
    if campaign["reserved_estimated_cents"] + estimated > campaign["budget_cents"]:
        raise unprocessable(ERR_BUDGET_EXCEEDED,
                            "slot's estimated cost would exceed the campaign "
                            "budget")

    rec = db.new_record()
    rec.update({"reel_id": reel_id, "campaign_id": campaign_id,
                "start_offset_seconds": start, "duration_seconds": duration,
                "slot_status": "RESERVED", "estimated_cost_cents": estimated,
                "play_factor": None, "attributed_impressions": None})
    db.slots[rec["id"]] = rec

    # Side effects: pool usage, campaign reserved spend, reel version bump.
    reel[used_key] += duration
    db.touch(reel)
    calc.recompute_campaign_reserved(campaign)
    return success_object(ser_slot(rec), 201)


@bp.get("/network/slots/<slot_id>")
def get_slot(slot_id):
    require(ALL_ROLES)
    s = _get_slot_or_404(slot_id)
    return success_object(ser_slot(s))


@bp.get("/network/slots")
def list_slots():
    require(ALL_ROLES)
    from flask import request
    limit, offset = pagination()
    reel_id = request.args.get("reel_id")
    campaign_id = request.args.get("campaign_id")
    items = sorted(db.slots.values(), key=lambda r: r["_seq"])
    if reel_id is not None:
        items = [s for s in items if s["reel_id"] == reel_id]
    if campaign_id is not None:
        items = [s for s in items if s["campaign_id"] == campaign_id]
    total = len(items)
    page = [ser_slot(s) for s in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@bp.post("/network/slots/<slot_id>/cancel")
def cancel_slot(slot_id):
    require(SALES)
    slot = _get_slot_or_404(slot_id)
    reel = db.reels[slot["reel_id"]]
    # State tier: locked reels cannot have slots canceled.
    if reel["reel_status"] != "ASSEMBLING":
        raise conflict(ERR_REEL_NOT_ASSEMBLING,
                       "reel is no longer ASSEMBLING; locked slots cannot be "
                       "canceled")
    if slot["slot_status"] != "RESERVED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a RESERVED slot can be canceled")
    slot["slot_status"] = "CANCELED"
    db.touch(slot)
    campaign = db.campaigns[slot["campaign_id"]]
    pool = _pool_of(campaign)
    reel[f"{pool}_used_seconds"] -= slot["duration_seconds"]
    db.touch(reel)
    calc.recompute_campaign_reserved(campaign)
    return success_object(ser_slot(slot))


# ---------------------------- Reel lifecycle --------------------------------

@bp.post("/network/reels/<reel_id>/lock")
def lock_reel(reel_id):
    require(OPS)
    body = get_body()
    expected_version = req_int(body, "expected_reel_version")
    reel = _get_reel_or_404(reel_id)
    # PRD 3.4 prose order: OCC precondition, then lockability.
    if expected_version != reel["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_reel_version does not match the reel's "
                       "current version")
    reserved = [s for s in calc.slots_of_reel(reel_id)
                if s["slot_status"] == "RESERVED"]
    if reel["reel_status"] != "ASSEMBLING" or not reserved:
        raise conflict(ERR_REEL_NOT_LOCKABLE,
                       "reel is not ASSEMBLING or holds zero RESERVED slots")
    for s in reserved:
        s["slot_status"] = "CONFIRMED"
        db.touch(s)
    reel["reel_status"] = "LOCKED"
    db.touch(reel)
    return success_object(ser_reel(reel))


@bp.post("/network/reels/<reel_id>/dispatch")
def dispatch_reel(reel_id):
    require(OPS)
    reel = _get_reel_or_404(reel_id)
    if reel["reel_status"] not in ("LOCKED", "DELIVERY_FAILED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a LOCKED or DELIVERY_FAILED reel can be "
                       "dispatched")
    reel["reel_status"] = "IN_TRANSIT"
    db.touch(reel)
    return success_object(ser_reel(reel))


@bp.post("/network/reels/<reel_id>/acknowledge-delivery")
def acknowledge_delivery(reel_id):
    user_id = require(THEATER)
    reel = _get_reel_or_404(reel_id)
    showtime = db.showtimes[reel["showtime_id"]]
    # Priority 3: theater scope (resolved through the showtime's screen).
    check_theater_scope(user_id, _theater_id_of_showtime(showtime))
    # Priority 4: shape.
    body = get_body()
    outcome = req_enum(body, "outcome", {"DELIVERED", "FAILED"})
    # Priority 7: state.
    if reel["reel_status"] != "IN_TRANSIT":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only an IN_TRANSIT reel can be acknowledged")
    # Priority 10: delivery deadline applies to DELIVERED acknowledgments.
    if outcome == "DELIVERED":
        clock_dt, _ = db.get_clock()
        if not clock_dt < showtime["_starts_dt"]:
            raise unprocessable(ERR_DELIVERY_LATE,
                                "delivery acknowledgment at or after the "
                                "showtime start")
        reel["reel_status"] = "DELIVERED"
    else:
        reel["reel_status"] = "DELIVERY_FAILED"
    db.touch(reel)
    return success_object(ser_reel(reel))


@bp.post("/network/reels/<reel_id>/reconcile")
def reconcile_reel(reel_id):
    require(OPS)
    reel = _get_reel_or_404(reel_id)
    if reel["reel_status"] != "DELIVERED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a DELIVERED reel can be reconciled")
    for s in calc.slots_of_reel(reel_id):
        if s["slot_status"] == "CONFIRMED":
            raise conflict(ERR_REEL_NOT_RECONCILABLE,
                           "a CONFIRMED slot still lacks a playback record")
    reel["reel_status"] = "RECONCILED"
    db.touch(reel)
    return success_object(ser_reel(reel))
