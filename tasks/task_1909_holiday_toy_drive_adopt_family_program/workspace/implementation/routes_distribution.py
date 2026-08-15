"""Distribution events and pickup slots."""

from datetime import datetime, timezone, timedelta

from flask import Blueprint, request

import clock
import db
from domain import (
    make_row, touch, sort_rows, family_rollup, recompute_adoptions_for_family,
    ser_event, ser_slot, ser_gift,
)
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, err_stale_version,
    err_invalid_window, err_slot_overlap, err_lane_capacity, err_slot_family,
    err_outside_window,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, as_int, as_str, as_enum, parse_datetime

bp = Blueprint("distribution", __name__)

LANES = ("A", "B", "C", "D")
LANE_BUCKET_CAPACITY = 4
BUCKET_MINUTES = 30
SLOT_FAMILY_OK = ("MATCHED", "PARTIALLY_FULFILLED", "FULFILLED", "BACKFILLED")


def _get_event(eid):
    row = db.distribution_events.get(eid)
    if row is None:
        raise err_not_found("DistributionEvent not found")
    return row


def _get_slot(sid):
    row = db.distribution_slots.get(sid)
    if row is None:
        raise err_not_found("DistributionSlot not found")
    return row


# ---------------------------------------------------------------------------
# DistributionEvent
# ---------------------------------------------------------------------------

@bp.route("/distribution-events", methods=["POST"])
@require_roles("PlatformAdmin")
def create_event(actor):
    body = get_body(required=True)
    campaign_id = as_str(req_field(body, "campaign_id"), "campaign_id")
    site_name = as_str(req_field(body, "site_name"), "site_name")
    start_at = parse_datetime(req_field(body, "start_at"), "start_at")
    end_at = parse_datetime(req_field(body, "end_at"), "end_at")
    capacity = as_int(req_field(body, "capacity_slots"), "capacity_slots")
    if capacity < 1 or capacity > 1000:
        raise err_invalid_request("capacity_slots must be between 1 and 1000")
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err_not_found("Campaign not found")
    if end_at <= start_at:
        raise err_invalid_window("event.end_at must be strictly greater than event.start_at")
    row = make_row()
    row.update(
        campaign_id=campaign_id,
        site_name=site_name,
        start_at=start_at,
        end_at=end_at,
        status="PLANNED",
        capacity_slots=capacity,
    )
    db.distribution_events[row["id"]] = row
    return success_created(ser_event(row))


@bp.route("/distribution-events", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def list_events(actor):
    rows = list(db.distribution_events.values())
    for param in ("campaign_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [e for e in rows if str(e.get(param)) == val]
    return success_list(sort_rows(rows), ser_event)


@bp.route("/distribution-events/<eid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def get_event(actor, eid):
    return success_object(ser_event(_get_event(eid)))


@bp.route("/distribution-events/<eid>/slots", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def event_slots(actor, eid):
    _get_event(eid)
    rows = [s for s in db.distribution_slots.values() if s["event_id"] == eid]
    for param in ("status", "family_id"):
        val = request.args.get(param)
        if val is not None:
            rows = [s for s in rows if str(s.get(param)) == val]
    return success_list(sort_rows(rows), ser_slot)


@bp.route("/distribution-events/<eid>/open-slots", methods=["POST"])
@require_roles("PlatformAdmin")
def open_slots(actor, eid):
    event = _get_event(eid)
    get_body()
    if event["status"] != "PLANNED":
        raise err_invalid_state("open-slots requires event in PLANNED")
    campaign = db.campaigns[event["campaign_id"]]
    if campaign["status"] != "DISTRIBUTION_PREP":
        raise err_invalid_state("Campaign must be in DISTRIBUTION_PREP to open slots")
    event["status"] = "OPEN_FOR_SLOTS"
    touch(event)
    return success_object(ser_event(event))


@bp.route("/distribution-events/<eid>/begin-sorting", methods=["POST"])
@require_roles("PlatformAdmin")
def begin_sorting(actor, eid):
    event = _get_event(eid)
    get_body()
    if event["status"] != "OPEN_FOR_SLOTS":
        raise err_invalid_state("begin-sorting requires event in OPEN_FOR_SLOTS")
    for s in db.distribution_slots.values():
        if s["event_id"] == eid:
            if s["window_start"] < event["start_at"] or s["window_end"] > event["end_at"]:
                raise err_invalid_state("Every slot window must lie within the event window")
    event["status"] = "SORTING"
    touch(event)
    return success_object(ser_event(event))


@bp.route("/distribution-events/<eid>/lock", methods=["POST"])
@require_roles("PlatformAdmin")
def lock_event(actor, eid):
    event = _get_event(eid)
    get_body()
    if event["status"] != "SORTING":
        raise err_invalid_state("lock requires event in SORTING")
    slot_ids = {s["id"] for s in db.distribution_slots.values() if s["event_id"] == eid}
    for g in db.gifts.values():
        if g.get("slot_id") in slot_ids and g["status"] == "RECEIVED":
            raise err_invalid_state("Gifts staged into this event must not remain RECEIVED")
    event["status"] = "LOCKED"
    touch(event)
    return success_object(ser_event(event))


@bp.route("/distribution-events/<eid>/complete", methods=["POST"])
@require_roles("PlatformAdmin")
def complete_event(actor, eid):
    event = _get_event(eid)
    get_body()
    if event["status"] != "LOCKED":
        raise err_invalid_state("complete requires event in LOCKED")
    for s in db.distribution_slots.values():
        if s["event_id"] == eid and s["status"] not in ("COMPLETED", "NO_SHOW", "CANCELLED"):
            raise err_invalid_state("Every slot must be COMPLETED, NO_SHOW, or CANCELLED")
    event["status"] = "COMPLETED"
    touch(event)
    return success_object(ser_event(event))


@bp.route("/distribution-events/<eid>/cancel", methods=["POST"])
@require_roles("PlatformAdmin")
def cancel_event(actor, eid):
    event = _get_event(eid)
    get_body()
    if event["status"] not in ("PLANNED", "OPEN_FOR_SLOTS"):
        raise err_invalid_state("cancel requires event in PLANNED or OPEN_FOR_SLOTS")
    event["status"] = "CANCELLED"
    touch(event)
    for s in db.distribution_slots.values():
        if s["event_id"] == eid and s["status"] in ("RESERVED", "CHECKED_IN"):
            s["status"] = "CANCELLED"
            touch(s)
            for g in db.gifts.values():
                if g.get("slot_id") == s["id"] and g["status"] == "STAGED":
                    g["status"] = "SORTED"
                    g["slot_id"] = None
                    touch(g)
    return success_object(ser_event(event))


# ---------------------------------------------------------------------------
# DistributionSlot
# ---------------------------------------------------------------------------

def _buckets_for(window_start, window_end):
    """All 30-minute buckets (aligned to :00/:30 UTC) overlapped by [start, end)."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    bucket_secs = BUCKET_MINUTES * 60
    first = int((window_start - epoch).total_seconds()) // bucket_secs
    # last bucket overlapped: window_end is exclusive
    last_second = int((window_end - epoch).total_seconds()) - 1
    last = last_second // bucket_secs
    return range(first, last + 1)


def _check_slot_rules(event, family_id, lane, window_start, window_end, exclude_slot_id=None):
    # family-axis overlap (priority 19): half-open interval overlap, same event
    for s in db.distribution_slots.values():
        if s["event_id"] != event["id"] or s["id"] == exclude_slot_id:
            continue
        if s["family_id"] != family_id or s["status"] == "CANCELLED":
            continue
        if s["window_start"] < window_end and window_start < s["window_end"]:
            raise err_slot_overlap()
    # lane bucket capacity (priority 20)
    buckets = _buckets_for(window_start, window_end)
    for b in buckets:
        count = 0
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        b_start = epoch + timedelta(seconds=b * BUCKET_MINUTES * 60)
        b_end = b_start + timedelta(minutes=BUCKET_MINUTES)
        for s in db.distribution_slots.values():
            if s["event_id"] != event["id"] or s["id"] == exclude_slot_id:
                continue
            if s["lane"] != lane or s["status"] == "CANCELLED":
                continue
            if s["window_start"] < b_end and b_start < s["window_end"]:
                count += 1
        if count + 1 > LANE_BUCKET_CAPACITY:
            raise err_lane_capacity()


@bp.route("/distribution-slots", methods=["POST"])
@require_roles("PlatformAdmin", "DistributionVolunteer")
def create_slot(actor):
    body = get_body(required=True)
    event_id = as_str(req_field(body, "event_id"), "event_id")
    family_id = as_str(req_field(body, "family_id"), "family_id")
    window_start = parse_datetime(req_field(body, "window_start"), "window_start")
    window_end = parse_datetime(req_field(body, "window_end"), "window_end")
    lane = as_enum(req_field(body, "lane"), "lane", LANES)
    expected_event_version = req_field(body, "expected_event_version")
    if isinstance(expected_event_version, bool) or not isinstance(expected_event_version, int):
        raise err_invalid_request("expected_event_version must be an integer")

    event = db.distribution_events.get(event_id)
    if event is None:
        raise err_not_found("DistributionEvent not found")
    family = db.families.get(family_id)
    if family is None:
        raise err_not_found("Family not found")

    if event["status"] != "OPEN_FOR_SLOTS":
        raise err_invalid_state("Slots may only be booked while the event is OPEN_FOR_SLOTS")
    if expected_event_version != event["version"]:
        raise err_stale_version("expected_event_version does not match current event version")

    live_slots = [
        s for s in db.distribution_slots.values()
        if s["event_id"] == event_id and s["status"] != "CANCELLED"
    ]
    if len(live_slots) >= event["capacity_slots"]:
        raise err_invalid_state("Event slot capacity reached")

    # priority 19/20: overlap + lane capacity
    _check_slot_rules(event, family_id, lane, window_start, window_end)

    # priority 23: slot family consistency
    if family["campaign_id"] != event["campaign_id"] or family["status"] not in SLOT_FAMILY_OK:
        raise err_slot_family()

    # priority 28: window sanity
    if window_end <= window_start:
        raise err_invalid_window("window_end must be strictly greater than window_start")
    if window_start < event["start_at"] or window_end > event["end_at"]:
        raise err_invalid_window("Slot window must lie within the parent event window")

    row = make_row()
    row.update(
        event_id=event_id,
        family_id=family_id,
        window_start=window_start,
        window_end=window_end,
        lane=lane,
        status="RESERVED",
    )
    db.distribution_slots[row["id"]] = row
    touch(event)  # booking bumps the parent event version (OCC anchor)
    return success_created(ser_slot(row))


@bp.route("/distribution-slots/<sid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def get_slot(actor, sid):
    return success_object(ser_slot(_get_slot(sid)))


@bp.route("/distribution-slots/<sid>/gifts", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def slot_gifts(actor, sid):
    _get_slot(sid)
    rows = [g for g in db.gifts.values() if g.get("slot_id") == sid]
    status = request.args.get("status")
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    return success_list(sort_rows(rows), ser_gift)


@bp.route("/families/<fid>/distribution-slots", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def family_slots(actor, fid):
    if fid not in db.families:
        raise err_not_found("Family not found")
    rows = [s for s in db.distribution_slots.values() if s["family_id"] == fid]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return success_list(sort_rows(rows), ser_slot)


@bp.route("/distribution-slots/<sid>/check-in", methods=["POST"])
@require_roles("DistributionVolunteer")
def check_in_slot(actor, sid):
    slot = _get_slot(sid)
    get_body()
    now = clock.now()
    if slot["status"] == "RESERVED" and now > slot["window_end"]:
        # lazy no-show transition, surfaced with the dedicated error
        slot["status"] = "NO_SHOW"
        touch(slot)
        for g in db.gifts.values():
            if g.get("slot_id") == sid and g["status"] == "STAGED":
                g["status"] = "SORTED"
                g["slot_id"] = None
                touch(g)
        raise err_outside_window()
    if slot["status"] != "RESERVED":
        raise err_invalid_state("check-in requires slot in RESERVED")
    if now < slot["window_start"]:
        raise err_outside_window("Check-in attempted before window_start")
    slot["status"] = "CHECKED_IN"
    touch(slot)
    return success_object(ser_slot(slot))


@bp.route("/distribution-slots/<sid>/complete", methods=["POST"])
@require_roles("DistributionVolunteer")
def complete_slot(actor, sid):
    slot = _get_slot(sid)
    get_body()
    if slot["status"] != "CHECKED_IN":
        raise err_invalid_state("complete requires slot in CHECKED_IN")
    staged = [g for g in db.gifts.values() if g.get("slot_id") == sid]
    if any(g["status"] != "STAGED" for g in staged):
        raise err_invalid_state("Every gift assigned to the slot must be STAGED")

    slot["status"] = "COMPLETED"
    touch(slot)
    family = db.families.get(slot["family_id"])

    for g in staged:
        g["status"] = "DELIVERED"
        touch(g)
        if g.get("wish_item_id"):
            item = db.wish_items.get(g["wish_item_id"])
            if item is not None and item["status"] == "RECEIVED":
                item["status"] = "DELIVERED"
                touch(item)

    for child in db.children.values():
        if child["family_id"] == slot["family_id"] and child["status"] == "GIFT_RECEIVED":
            child["status"] = "DELIVERED"
            touch(child)

    for p in db.backfill_purchases.values():
        child = db.children.get(p["child_id"])
        if (
            child is not None
            and child["family_id"] == slot["family_id"]
            and p["status"] == "SORTED"
        ):
            p["status"] = "DELIVERED"
            touch(p)

    if family is not None:
        family_rollup(family, adjust_status=True)
        recompute_adoptions_for_family(family)
    return success_object(ser_slot(slot))


@bp.route("/distribution-slots/<sid>/cancel", methods=["POST"])
@require_roles("PlatformAdmin")
def cancel_slot(actor, sid):
    slot = _get_slot(sid)
    get_body()
    if slot["status"] != "RESERVED":
        raise err_invalid_state("cancel requires slot in RESERVED")
    slot["status"] = "CANCELLED"
    touch(slot)
    for g in db.gifts.values():
        if g.get("slot_id") == sid and g["status"] == "STAGED":
            g["status"] = "SORTED"
            g["slot_id"] = None
            touch(g)
    return success_object(ser_slot(slot))
