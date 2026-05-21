"""Backcountry zone and permit routes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_PARK_ADMIN,
    ROLE_PARK_RANGER,
    ROLE_VISITOR,
    current_user_id,
    require_auth,
)
from ..clock import now_utc
from ..envelope import parse_pagination, success_array, success_object
from ..errors import APIError
from ..serializers import serialize_backcountry_permit, serialize_zone
from ..services.calculations import (
    BOOKING_FEE_CENTS,
    backcountry_refund,
)
from ..services.common import stamp_create, stamp_update
from ..services.wallet import debit_for_fee, refund as wallet_refund
from ..store import get_store
from ..timeutil import park_local_to_utc, parse_park_local_datetime
from ..util import format_iso8601, new_id, parse_iso8601
from ..validators import (
    get_json_body,
    optional_int,
    require_int,
    require_string,
)
from ._helpers import (
    filter_visitor_owned,
    lookup_park,
    lookup_visitor,
    lookup_zone,
    require_visitor_ownership,
)

bp = Blueprint("backcountry", __name__)


@bp.post("/parks/<park_id>/backcountry-zones")
@require_auth([ROLE_PARK_ADMIN])
def create_zone(park_id: str):
    lookup_park(park_id)
    body = get_json_body()
    name = require_string(body, "name", min_len=1, max_len=80)
    quota = require_int(body, "nightly_quota_people", min_val=0)
    buffer_minutes = optional_int(body, "ranger_buffer_minutes", default=30, min_val=0, max_val=720)
    per_party_fee = require_int(body, "per_party_fee_cents", min_val=0)
    store = get_store()
    key = (park_id, name.lower())
    with store.lock:
        if key in store.zone_names:
            raise APIError("ERR_VALIDATION", "zone name not unique within park", 422)
        zone = {
            "id": new_id(),
            "park_id": park_id,
            "name": name,
            "nightly_quota_people": quota,
            "ranger_buffer_minutes": buffer_minutes,
            "per_party_fee_cents": per_party_fee,
        }
        stamp_create(zone)
        store.backcountry_zones[zone["id"]] = zone
        store.zone_names[key] = zone["id"]
    return jsonify(success_object(serialize_zone(zone))), 201


@bp.get("/parks/<park_id>/backcountry-zones")
@require_auth([ROLE_PARK_ADMIN, ROLE_VISITOR, ROLE_PARK_RANGER])
def list_zones(park_id: str):
    lookup_park(park_id)
    limit, offset = parse_pagination()
    store = get_store()
    items = [z for z in store.backcountry_zones.values() if z["park_id"] == park_id]
    items.sort(key=lambda z: z["created_at"])
    total = len(items)
    page = [serialize_zone(z) for z in items[offset : offset + limit]]
    return jsonify(success_array(page, limit=limit, offset=offset, total_count=total)), 200


def _to_park_utc(tup, tz_name: str) -> datetime:
    y, mo, d, h, mi = tup
    return park_local_to_utc(y, mo, d, h, mi, tz_name)


@bp.post("/backcountry-zones/<zone_id>/permits")
@require_auth([ROLE_VISITOR])
def create_permit(zone_id: str):
    zone = lookup_zone(zone_id)
    park = get_store().parks[zone["park_id"]]
    visitor_id = current_user_id()
    lookup_visitor(visitor_id)
    body = get_json_body()

    # PRD §2.12 priority 5: park-posture checks fire BEFORE any business-
    # domain checks (e.g. party_size range). A RESTRICTED park must
    # surface ERR_PARK_RESTRICTED even when the request also has an
    # invalid party_size.
    if park["status"] == "FROZEN":
        raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)
    if park["status"] == "RESTRICTED":
        raise APIError("ERR_PARK_RESTRICTED", "Park is RESTRICTED", 409)

    party_size = require_int(body, "party_size", min_val=1, max_val=15)
    entry_local = require_string(body, "entry_datetime_local", min_len=1)
    exit_local = require_string(body, "exit_datetime_local", min_len=1)

    entry_tup = parse_park_local_datetime(entry_local)
    exit_tup = parse_park_local_datetime(exit_local)
    if entry_tup is None or exit_tup is None:
        raise APIError("ERR_VALIDATION", "entry/exit_datetime_local invalid", 422)

    # Reformat input strings with minute granularity for consistent storage
    entry_local_clean = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}".format(*entry_tup)
    exit_local_clean = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}".format(*exit_tup)

    entry_utc = _to_park_utc(entry_tup, park["timezone"])
    exit_utc = _to_park_utc(exit_tup, park["timezone"])
    if exit_utc <= entry_utc:
        raise APIError("ERR_VALIDATION", "exit must be after entry", 422)

    # Compute nights: difference between entry-date and exit-date in park-local days
    from datetime import date as _date
    nights = (_date(*exit_tup[:3]) - _date(*entry_tup[:3])).days
    if nights < 0:
        nights = 0
    fee_cents = zone["per_party_fee_cents"] + BOOKING_FEE_CENTS

    store = get_store()
    with store.lock:
        now = now_utc()
        held_until = now + timedelta(minutes=15)
        permit = {
            "id": new_id(),
            "zone_id": zone_id,
            "visitor_id": visitor_id,
            "party_size": party_size,
            "entry_datetime_local": entry_local_clean,
            "exit_datetime_local": exit_local_clean,
            "nights": nights,
            "fee_cents": fee_cents,
            "status": "HELD",
            "held_until": format_iso8601(held_until),
        }
        stamp_create(permit)
        store.backcountry_permits[permit["id"]] = permit
    return jsonify(success_object(serialize_backcountry_permit(permit))), 201


def _lookup_permit(zone_id: str, permit_id: str):
    lookup_zone(zone_id)
    store = get_store()
    p = store.backcountry_permits.get(permit_id)
    if p is None or p["zone_id"] != zone_id:
        raise APIError("ERR_NOT_FOUND", "Permit not found", 404)
    return p


def _date_range_inclusive_left_exclusive_right(entry_tup, exit_tup):
    from datetime import date as _date, timedelta as _td
    a = _date(*entry_tup[:3])
    b = _date(*exit_tup[:3])
    days = []
    cur = a
    while cur < b:
        days.append(cur)
        cur = cur + _td(days=1)
    return days


@bp.post("/backcountry-zones/<zone_id>/permits/<permit_id>/confirm")
@require_auth([ROLE_VISITOR])
def confirm_permit(zone_id: str, permit_id: str):
    p = _lookup_permit(zone_id, permit_id)
    require_visitor_ownership(p["visitor_id"])
    if p["status"] != "HELD":
        raise APIError("ERR_INVALID_STATE", "Permit not HELD", 409)
    held_until = parse_iso8601(p["held_until"])
    if held_until is None or now_utc() >= held_until:
        raise APIError("ERR_INVALID_STATE", "Hold expired", 409)
    zone = get_store().backcountry_zones[zone_id]
    park = get_store().parks[zone["park_id"]]
    if park["status"] != "OPEN":
        if park["status"] == "FROZEN":
            raise APIError("ERR_PARK_FROZEN", "Park is FROZEN", 409)
        raise APIError("ERR_PARK_RESTRICTED", "Park is RESTRICTED", 409)

    # Compute UTC bounds for the new permit
    entry_tup = parse_park_local_datetime(p["entry_datetime_local"])
    exit_tup = parse_park_local_datetime(p["exit_datetime_local"])
    if entry_tup is None or exit_tup is None:
        raise APIError("ERR_VALIDATION", "Bad permit times", 422)
    entry_utc = _to_park_utc(entry_tup, park["timezone"])
    exit_utc = _to_park_utc(exit_tup, park["timezone"])
    buffer_secs = zone["ranger_buffer_minutes"] * 60

    store = get_store()
    # Ranger-buffer check first
    for other in store.backcountry_permits.values():
        if other["id"] == p["id"]:
            continue
        if other["zone_id"] != zone_id:
            continue
        if other["status"] != "CONFIRMED":
            continue
        o_entry_tup = parse_park_local_datetime(other["entry_datetime_local"])
        o_exit_tup = parse_park_local_datetime(other["exit_datetime_local"])
        if o_entry_tup is None or o_exit_tup is None:
            continue
        o_entry_utc = _to_park_utc(o_entry_tup, park["timezone"])
        o_exit_utc = _to_park_utc(o_exit_tup, park["timezone"])
        # collision iff a < d + buffer AND c < b + buffer
        if (
            entry_utc.timestamp() < o_exit_utc.timestamp() + buffer_secs
            and o_entry_utc.timestamp() < exit_utc.timestamp() + buffer_secs
        ):
            raise APIError("ERR_RANGER_BUFFER_VIOLATION", "Ranger buffer collision", 409)

    # Nightly quota check
    quota = zone["nightly_quota_people"]
    new_nights = _date_range_inclusive_left_exclusive_right(entry_tup, exit_tup)
    night_counts = {d: 0 for d in new_nights}
    for other in store.backcountry_permits.values():
        if other["id"] == p["id"]:
            continue
        if other["zone_id"] != zone_id:
            continue
        if other["status"] != "CONFIRMED":
            continue
        o_entry_tup = parse_park_local_datetime(other["entry_datetime_local"])
        o_exit_tup = parse_park_local_datetime(other["exit_datetime_local"])
        if o_entry_tup is None or o_exit_tup is None:
            continue
        for night in _date_range_inclusive_left_exclusive_right(o_entry_tup, o_exit_tup):
            if night in night_counts:
                night_counts[night] += other["party_size"]
    for night, cnt in night_counts.items():
        if cnt + p["party_size"] > quota:
            raise APIError("ERR_BACKCOUNTRY_FULL", "Nightly quota exceeded", 409)

    # Wallet check
    visitor = store.visitors[p["visitor_id"]]
    if visitor["wallet_balance_cents"] < p["fee_cents"]:
        raise APIError("ERR_INSUFFICIENT_FUNDS", "Wallet too low", 402)

    with store.lock:
        debit_for_fee(visitor["id"], p["fee_cents"], "FEE_CHARGE", "BackcountryPermit", p["id"])
        p["status"] = "CONFIRMED"
        stamp_update(p)
    return jsonify(success_object(serialize_backcountry_permit(p))), 200


@bp.post("/backcountry-zones/<zone_id>/permits/<permit_id>/cancel")
@require_auth([ROLE_VISITOR])
def cancel_permit(zone_id: str, permit_id: str):
    p = _lookup_permit(zone_id, permit_id)
    require_visitor_ownership(p["visitor_id"])
    if p["status"] not in ("HELD", "CONFIRMED"):
        raise APIError("ERR_INVALID_STATE", "Permit cannot be cancelled", 409)
    zone = get_store().backcountry_zones[zone_id]
    park = get_store().parks[zone["park_id"]]
    refund_cents = 0
    if p["status"] == "CONFIRMED":
        entry_tup = parse_park_local_datetime(p["entry_datetime_local"])
        if entry_tup is None:
            raise APIError("ERR_INVALID_STATE", "Bad permit times", 409)
        entry_utc = _to_park_utc(entry_tup, park["timezone"])
        if now_utc() >= entry_utc:
            raise APIError("ERR_INVALID_STATE", "Past entry time", 409)
        hours = (entry_utc - now_utc()).total_seconds() / 3600.0
        refund_cents = backcountry_refund(p["fee_cents"], hours)
    store = get_store()
    with store.lock:
        if refund_cents > 0:
            wallet_refund(p["visitor_id"], refund_cents, "BackcountryPermit", p["id"])
        p["status"] = "CANCELLED"
        stamp_update(p)
    return jsonify(success_object(serialize_backcountry_permit(p))), 200


@bp.post("/backcountry-zones/<zone_id>/permits/<permit_id>/check-out")
@require_auth([ROLE_PARK_RANGER])
def checkout_permit(zone_id: str, permit_id: str):
    p = _lookup_permit(zone_id, permit_id)
    if p["status"] != "CONFIRMED":
        raise APIError("ERR_INVALID_STATE", "Permit not CONFIRMED", 409)
    zone = get_store().backcountry_zones[zone_id]
    park = get_store().parks[zone["park_id"]]
    exit_tup = parse_park_local_datetime(p["exit_datetime_local"])
    if exit_tup is None:
        raise APIError("ERR_INVALID_STATE", "Bad permit times", 409)
    exit_utc = _to_park_utc(exit_tup, park["timezone"])
    if now_utc() < exit_utc:
        raise APIError("ERR_INVALID_STATE", "Before exit time", 409)
    store = get_store()
    with store.lock:
        p["status"] = "USED"
        stamp_update(p)
    return jsonify(success_object(serialize_backcountry_permit(p))), 200
