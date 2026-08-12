"""Listing endpoints: CRUD, policy (OCC), lifecycle (pause/resume/withdraw),
blackout windows, activity events, activity report."""

from datetime import timedelta

from flask import Blueprint, request as flask_request

import db
import errors
import middleware as mw
import response
from services import calc, core

bp = Blueprint("listings", __name__)


def get_listing_or_404(listing_id):
    listing = db.listings.get(listing_id)
    if listing is None:
        raise errors.err(errors.ERR_LISTING_NOT_FOUND, "Listing not found.", 404)
    return listing


def _require_owning_listing_agent(caller, listing):
    if caller.user_id != listing["listing_agent_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the listing agent of this listing.", 403)


def _require_owning_seller(caller, listing):
    if caller.user_id != listing["seller_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the seller who owns this listing.", 403)


def _validate_policy_value(name, value, lo, hi):
    if value < lo or value > hi:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         f"{name} must be between {lo} and {hi}.", 400)


@bp.post("/showing-desk/listings")
def create_listing():
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "seller_id": ("string", True),
        "address": ("string", True),
        "occupancy_type": (("enum", ["VACANT", "OCCUPIED"]), True),
        "buffer_minutes": ("integer", False),
        "max_showings_per_day": ("integer", False),
        "min_notice_minutes": ("integer", False),
    })
    mw.require_roles(caller, ["ListingAgent"])
    # Body FK existence (stage 4)
    seller = db.sellers.get(fields["seller_id"])
    if seller is None:
        raise errors.err(errors.ERR_SELLER_NOT_FOUND, "Seller not found.", 404)
    buffer_minutes = fields.get("buffer_minutes", 30)
    max_showings = fields.get("max_showings_per_day", 5)
    min_notice = fields.get("min_notice_minutes", 120)
    _validate_policy_value("buffer_minutes", buffer_minutes, 0, 240)
    _validate_policy_value("max_showings_per_day", max_showings, 1, 20)
    _validate_policy_value("min_notice_minutes", min_notice, 0, 4320)
    listing = core.stamp_new({
        "seller_id": seller["id"],
        "listing_agent_id": caller.user_id,
        "address": fields["address"],
        "occupancy_type": fields["occupancy_type"],
        "status": "ACTIVE",
        "buffer_minutes": buffer_minutes,
        "max_showings_per_day": max_showings,
        "min_notice_minutes": min_notice,
        "confirmed_showing_count": 0,
        "avg_feedback_score": 0.0,
    })
    db.listings[listing["id"]] = listing
    return response.success_object(core.listing_view(listing), status=201)


@bp.get("/showing-desk/listings/<listing_id>")
def get_listing(listing_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "Seller", "ListingAgent", "BuyerAgent"])
    listing = get_listing_or_404(listing_id)
    return response.success_object(core.listing_view(listing))


@bp.get("/showing-desk/listings")
def list_listings():
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "Seller", "ListingAgent", "BuyerAgent"])
    limit, offset = mw.parse_pagination()
    q = flask_request.args
    unknown = set(q.keys()) - {"seller_id", "listing_agent_id", "status", "limit", "offset"}
    if unknown:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         f"Unknown query parameter(s): {', '.join(sorted(unknown))}.", 400)
    status = q.get("status")
    if status is not None and status not in ("ACTIVE", "PAUSED", "WITHDRAWN"):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "status filter must be ACTIVE, PAUSED, or WITHDRAWN.", 400)
    items = sorted(db.listings.values(), key=lambda l: l["created_at"])
    if q.get("seller_id") is not None:
        items = [l for l in items if l["seller_id"] == q["seller_id"]]
    if q.get("listing_agent_id") is not None:
        items = [l for l in items if l["listing_agent_id"] == q["listing_agent_id"]]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.listing_view(l) for l in page],
                                 limit, offset, total)


@bp.patch("/showing-desk/listings/<listing_id>/policy")
def update_policy(listing_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "buffer_minutes": ("integer", False),
        "max_showings_per_day": ("integer", False),
        "min_notice_minutes": ("integer", False),
        "expected_listing_version": ("integer", True),
    })
    mw.require_roles(caller, ["ListingAgent"])
    listing = get_listing_or_404(listing_id)
    _require_owning_listing_agent(caller, listing)
    if fields["expected_listing_version"] != listing["version"]:
        raise errors.err(errors.ERR_STALE_LISTING_VERSION,
                         "expected_listing_version does not match the listing's current version.",
                         412)
    if "buffer_minutes" in fields:
        _validate_policy_value("buffer_minutes", fields["buffer_minutes"], 0, 240)
        listing["buffer_minutes"] = fields["buffer_minutes"]
    if "max_showings_per_day" in fields:
        _validate_policy_value("max_showings_per_day",
                               fields["max_showings_per_day"], 1, 20)
        listing["max_showings_per_day"] = fields["max_showings_per_day"]
    if "min_notice_minutes" in fields:
        _validate_policy_value("min_notice_minutes", fields["min_notice_minutes"], 0, 4320)
        listing["min_notice_minutes"] = fields["min_notice_minutes"]
    core.touch(listing)
    return response.success_object(core.listing_view(listing))


@bp.post("/showing-desk/listings/<listing_id>/pause")
def pause_listing(listing_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["ListingAgent"])
    listing = get_listing_or_404(listing_id)
    _require_owning_listing_agent(caller, listing)
    if listing["status"] == "WITHDRAWN":
        raise errors.err(errors.ERR_LISTING_ALREADY_WITHDRAWN,
                         "Listing is WITHDRAWN; no further lifecycle actions.", 409)
    if listing["status"] != "ACTIVE":
        raise errors.err(errors.ERR_LISTING_NOT_ACTIVE,
                         "Only an ACTIVE listing can be paused.", 409)
    listing["status"] = "PAUSED"
    core.touch(listing)
    core.add_activity(listing["id"], None, "LISTING_PAUSED", "ListingAgent",
                      "Listing paused by listing agent.")
    return response.success_object(core.listing_view(listing))


@bp.post("/showing-desk/listings/<listing_id>/resume")
def resume_listing(listing_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["ListingAgent"])
    listing = get_listing_or_404(listing_id)
    _require_owning_listing_agent(caller, listing)
    if listing["status"] == "WITHDRAWN":
        raise errors.err(errors.ERR_LISTING_ALREADY_WITHDRAWN,
                         "Listing is WITHDRAWN; no further lifecycle actions.", 409)
    if listing["status"] != "PAUSED":
        raise errors.err(errors.ERR_LISTING_NOT_ACTIVE,
                         "Only a PAUSED listing can be resumed.", 409)
    listing["status"] = "ACTIVE"
    core.touch(listing)
    core.add_activity(listing["id"], None, "LISTING_RESUMED", "ListingAgent",
                      "Listing resumed by listing agent.")
    return response.success_object(core.listing_view(listing))


@bp.post("/showing-desk/listings/<listing_id>/withdraw")
def withdraw_listing(listing_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["ListingAgent"])
    listing = get_listing_or_404(listing_id)
    _require_owning_listing_agent(caller, listing)
    if listing["status"] == "WITHDRAWN":
        raise errors.err(errors.ERR_LISTING_ALREADY_WITHDRAWN,
                         "Listing is WITHDRAWN; no further lifecycle actions.", 409)
    listing["status"] = "WITHDRAWN"
    calc.cascade_withdraw_listing(listing)
    core.touch(listing)
    core.add_activity(listing["id"], None, "LISTING_WITHDRAWN", "ListingAgent",
                      "Listing withdrawn by listing agent.")
    return response.success_object(core.listing_view(listing))


# ---------------------------------------------------------------------------
# Blackout windows
# ---------------------------------------------------------------------------

@bp.post("/showing-desk/listings/<listing_id>/blackout-windows")
def create_blackout_window(listing_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "start_at": ("datetime", True),
        "end_at": ("datetime", True),
        "reason": ("string", False),
    })
    mw.require_roles(caller, ["Seller"])
    listing = get_listing_or_404(listing_id)
    _require_owning_seller(caller, listing)
    start_at, end_at = fields["start_at"], fields["end_at"]
    if end_at <= start_at or (end_at - start_at) > timedelta(minutes=120):
        raise errors.err(errors.ERR_INVALID_TIME_RANGE,
                         "end_at must be later than start_at and span <= 120 minutes.", 422)
    window = core.stamp_new({
        "listing_id": listing["id"],
        "start_at": start_at,
        "end_at": end_at,
        "reason": fields.get("reason"),
    })
    db.blackout_windows[window["id"]] = window
    return response.success_object(core.blackout_window_view(window), status=201)


@bp.get("/showing-desk/listings/<listing_id>/blackout-windows")
def list_blackout_windows(listing_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["Seller", "ListingAgent"])
    listing = get_listing_or_404(listing_id)
    limit, offset = mw.parse_pagination()
    items = sorted((w for w in db.blackout_windows.values()
                    if w["listing_id"] == listing["id"]),
                   key=lambda w: w["created_at"])
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.blackout_window_view(w) for w in page],
                                 limit, offset, total)


@bp.delete("/showing-desk/blackout-windows/<window_id>")
def delete_blackout_window(window_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["Seller"])
    window = db.blackout_windows.get(window_id)
    if window is None:
        raise errors.err(errors.ERR_BLACKOUT_WINDOW_NOT_FOUND,
                         "Blackout window not found.", 404)
    listing = db.listings.get(window["listing_id"])
    if listing is None or caller.user_id != listing["seller_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the seller who owns this listing.", 403)
    del db.blackout_windows[window_id]
    return "", 204


# ---------------------------------------------------------------------------
# Activity events / report
# ---------------------------------------------------------------------------

def _filter_events(events):
    event_type = flask_request.args.get("event_type")
    if event_type is not None:
        allowed = {"REQUEST_CREATED", "APPROVED", "DECLINED", "RESCHEDULED",
                   "CONFIRMED", "CANCELLED", "EXPIRED", "COMPLETED", "NO_SHOW",
                   "CREDENTIAL_ISSUED", "CREDENTIAL_REDEEMED", "CREDENTIAL_REVOKED",
                   "CREDENTIAL_EXPIRED", "FEEDBACK_SENT", "FEEDBACK_SUBMITTED",
                   "STRIKE_ISSUED", "LISTING_PAUSED", "LISTING_RESUMED",
                   "LISTING_WITHDRAWN"}
        if event_type not in allowed:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "event_type filter is not a recognized event type.", 400)
        events = [e for e in events if e["event_type"] == event_type]
    return events


@bp.get("/showing-desk/listings/<listing_id>/activity-events")
def list_listing_activity(listing_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["Seller", "ListingAgent"])
    listing = get_listing_or_404(listing_id)
    limit, offset = mw.parse_pagination()
    items = sorted((e for e in db.activity_events.values()
                    if e["listing_id"] == listing["id"]),
                   key=lambda e: e["created_at"])
    items = _filter_events(items)
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.activity_event_view(e) for e in page],
                                 limit, offset, total)


@bp.get("/showing-desk/listings/<listing_id>/activity-report")
def activity_report(listing_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["Seller", "ListingAgent"])
    listing = get_listing_or_404(listing_id)
    mode = flask_request.args.get("mode", "FINAL")
    if mode not in ("FINAL", "PROVISIONAL"):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "mode must be FINAL or PROVISIONAL.", 400)
    return response.success_object(calc.seller_report(listing, mode))
