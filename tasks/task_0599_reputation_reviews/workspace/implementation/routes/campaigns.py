"""Campaigns: scheduling, credits, sending, attribution metrics."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import calc
import store
import validation as v
from auth import endpoint, resolve_campaign, resolve_location
from envelope import created, ok, paginate
from errors import err
from services import (add_alert, assert_not_frozen, assert_open,
                      business_of_location, refresh_campaign_billing,
                      suppress_queued_requests, touch)

bp = Blueprint("campaigns", __name__)

CAMPAIGN_STATUSES = ("DRAFT", "SCHEDULED", "RUNNING", "PAUSED", "COMPLETED")
CHANNEL_BUFFER_MINUTES = 15


@bp.post("/reputation/locations/<location_id>/campaigns")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def create_campaign(location_id):
    loc = resolve_location(location_id)
    data = v.body()
    name = v.req_str(data, "name")
    channel = v.req_enum(data, "channel", v.CHANNELS)
    message_body = v.req_str(data, "message_body")
    window_start = v.req_hhmm(data, "send_window_start")
    window_end = v.req_hhmm(data, "send_window_end")
    if v.minutes(window_end) <= v.minutes(window_start):
        raise err("ERR_INVALID_REQUEST", "send_window_end must be later than send_window_start.")
    daily_send_cap = v.req_int(data, "daily_send_cap", minimum=1)
    credits_allocated = v.req_int(data, "credits_allocated", minimum=0)
    expected_version = v.req_int(data, "expected_location_version")

    # priority 7 -- OCC (before the FROZEN gate)
    if expected_version != loc["version"]:
        raise err("ERR_STALE_VERSION")

    assert_not_frozen(loc)

    rec = store.base_record()
    rec.update({
        "location_id": location_id,
        "name": name,
        "channel": channel,
        "message_body": message_body,
        "send_window_start": window_start,
        "send_window_end": window_end,
        "daily_send_cap": daily_send_cap,
        "credits_allocated": credits_allocated,
        "credits_reserved": 0,
        "credits_consumed": 0,
        "credits_released": 0,
        "status": "DRAFT",
        "activated_at": None,
        "sent_count": 0,
        "billing_cost": Decimal("0.00"),
    })
    store.campaigns[rec["id"]] = rec

    touch(loc)
    return created(store.campaign_out(rec))


@bp.get("/reputation/locations/<location_id>/campaigns")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def list_campaigns(location_id):
    resolve_location(location_id)
    status = v.enum_filter("status", CAMPAIGN_STATUSES)
    rows = [c for c in store.campaigns.values() if c["location_id"] == location_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return paginate(store.by_created(rows), store.campaign_out)


@bp.get("/reputation/campaigns/<campaign_id>")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def get_campaign(campaign_id):
    campaign, _loc = resolve_campaign(campaign_id)
    return ok(store.campaign_out(campaign))


@bp.post("/reputation/campaigns/<campaign_id>/schedule")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def schedule_campaign(campaign_id):
    campaign, loc = resolve_campaign(campaign_id)
    assert_not_frozen(loc)
    if campaign["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")

    a_start = v.minutes(campaign["send_window_start"])
    a_end = v.minutes(campaign["send_window_end"])
    for other in store.campaigns.values():
        if other["id"] == campaign["id"]:
            continue
        if other["location_id"] != campaign["location_id"]:
            continue
        if other["channel"] != campaign["channel"]:
            continue
        if other["status"] not in ("SCHEDULED", "RUNNING", "PAUSED"):
            continue
        b_start = v.minutes(other["send_window_start"])
        b_end = v.minutes(other["send_window_end"])
        if (a_start - CHANNEL_BUFFER_MINUTES) <= b_end and (a_end + CHANNEL_BUFFER_MINUTES) >= b_start:
            raise err("ERR_SEND_WINDOW_CONFLICT")

    campaign["status"] = "SCHEDULED"
    touch(campaign)
    return ok(store.campaign_out(campaign))


@bp.post("/reputation/campaigns/<campaign_id>/activate")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def activate_campaign(campaign_id):
    campaign, loc = resolve_campaign(campaign_id)
    # priority 8 (FROZEN) then priority 9 (RESTRICTED), both before state legality.
    assert_open(loc)
    if campaign["status"] not in ("SCHEDULED", "PAUSED"):
        raise err("ERR_INVALID_STATE")

    campaign["status"] = "RUNNING"
    if campaign["activated_at"] is None:
        campaign["activated_at"] = store.now()
    touch(campaign)
    return ok(store.campaign_out(campaign))


@bp.post("/reputation/campaigns/<campaign_id>/pause")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def pause_campaign(campaign_id):
    campaign, loc = resolve_campaign(campaign_id)
    assert_not_frozen(loc)
    if campaign["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE")

    # Manual pause leaves the queue intact and the credits reserved.
    campaign["status"] = "PAUSED"
    touch(campaign)
    return ok(store.campaign_out(campaign))


@bp.post("/reputation/campaigns/<campaign_id>/complete")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def complete_campaign(campaign_id):
    campaign, loc = resolve_campaign(campaign_id)
    assert_not_frozen(loc)
    if campaign["status"] not in ("RUNNING", "PAUSED"):
        raise err("ERR_INVALID_STATE")

    campaign["status"] = "COMPLETED"
    suppress_queued_requests(campaign)
    refresh_campaign_billing(campaign)
    touch(campaign)
    return ok(store.campaign_out(campaign))


@bp.post("/reputation/campaigns/<campaign_id>/requests")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def enqueue_request(campaign_id):
    campaign, loc = resolve_campaign(campaign_id)
    business = business_of_location(loc)
    data = v.body()

    # priority 5 -- body-reference existence and tenancy
    contact = None
    raw_contact_id = data.get("contact_id")
    if isinstance(raw_contact_id, str):
        contact = store.contacts.get(raw_contact_id)
        if contact is None or contact["business_id"] != business["id"]:
            raise err("ERR_CONTACT_NOT_FOUND")

    # priority 6 -- well-formedness
    v.req_str(data, "contact_id")
    if contact is None:
        raise err("ERR_INVALID_REQUEST", "Field 'contact_id' must be a string.")

    # priority 8 -- FROZEN
    assert_not_frozen(loc)

    # priority 12 -- consent (compliance beats commerce)
    if contact["opted_out"]:
        raise err("ERR_CONTACT_OPTED_OUT")
    if campaign["channel"] == "SMS":
        if not contact["sms_consent"] or not contact["phone"]:
            raise err("ERR_CONTACT_OPTED_OUT")
    else:
        if not contact["email_consent"] or not contact["email"]:
            raise err("ERR_CONTACT_OPTED_OUT")

    # priority 21 -- per-contact frequency cap, half-open [T, T + cap_days)
    anchor = contact["last_requested_at"]
    if anchor is not None:
        cap = timedelta(days=business["default_frequency_cap_days"])
        if anchor <= store.now() < anchor + cap:
            raise err("ERR_FREQUENCY_CAP_ACTIVE")

    # priority 22 -- credit availability
    available = campaign["credits_allocated"] - campaign["credits_reserved"] - campaign["credits_consumed"]
    if available < 1:
        raise err("ERR_INSUFFICIENT_CREDITS")

    rec = store.base_record()
    rec.update({
        "campaign_id": campaign["id"],
        "contact_id": contact["id"],
        "channel": campaign["channel"],
        "status": "QUEUED",
        "send_index": None,
        "unit_cost": None,
        "sent_at": None,
        "converted_review_id": None,
    })
    store.review_requests[rec["id"]] = rec

    campaign["credits_reserved"] += 1
    touch(campaign)

    contact["last_requested_at"] = store.now()
    contact["request_count"] += 1
    touch(contact)

    return created(store.request_out(rec))


@bp.post("/reputation/campaigns/<campaign_id>/send-batch")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def send_batch(campaign_id):
    campaign, loc = resolve_campaign(campaign_id)
    data = v.body()
    batch_size = v.req_int(data, "batch_size", minimum=1)

    assert_not_frozen(loc)
    if campaign["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE")

    if campaign["credits_allocated"] - campaign["credits_consumed"] < 1:
        raise err("ERR_INSUFFICIENT_CREDITS")

    all_requests = calc.campaign_requests(campaign)
    queued = [r for r in all_requests if r["status"] == "QUEUED"]
    to_send = queued[:batch_size]

    today = store.now().date()
    sent_today = sum(
        1 for r in all_requests
        if r["sent_at"] is not None and r["sent_at"].date() == today
    )
    if sent_today + len(to_send) > campaign["daily_send_cap"]:
        raise err("ERR_SEND_CAP_EXCEEDED")

    max_index = max([r["send_index"] for r in all_requests if r["send_index"] is not None] or [0])
    now = store.now()
    for req in to_send:
        max_index += 1
        req["send_index"] = max_index
        req["unit_cost"] = calc.unit_cost(campaign["channel"], max_index)
        req["sent_at"] = now
        req["status"] = "SENT"
        touch(req)
        campaign["credits_reserved"] -= 1
        campaign["credits_consumed"] += 1

    refresh_campaign_billing(campaign)
    touch(campaign)

    if to_send and sent_today + len(to_send) == campaign["daily_send_cap"]:
        add_alert(loc["id"], "SEND_CAP_REACHED",
                  "daily send cap reached for campaign %s" % campaign["id"], campaign["id"])

    remaining = sum(1 for r in calc.campaign_requests(campaign) if r["status"] == "QUEUED")
    return ok({
        "sent_count": len(to_send),
        "remaining_queued": remaining,
        "billing_cost": store.num(campaign["billing_cost"]),
        "campaign_status": campaign["status"],
    })


@bp.get("/reputation/campaigns/<campaign_id>/metrics")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def campaign_metrics(campaign_id):
    campaign, _loc = resolve_campaign(campaign_id)
    strict, broad = calc.campaign_conversion_rates(campaign)
    available = campaign["credits_allocated"] - campaign["credits_reserved"] - campaign["credits_consumed"]
    return ok({
        "sent_count": campaign["sent_count"],
        "conversion_rate_strict": store.num(strict),
        "conversion_rate_broad": store.num(broad),
        "billing_cost": store.num(campaign["billing_cost"]),
        "credits_available": available,
    })
