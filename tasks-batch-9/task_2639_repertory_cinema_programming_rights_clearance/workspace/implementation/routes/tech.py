"""Print traffic, ingest lanes and KDM keys (PRD 3.4)."""
from flask import Blueprint

import serialize
from auth import ROLE_EXEC, ROLE_PROGRAMMER, ROLE_TECH, authorize
from calc import (ASSET_CHAIN, find_key_overlap, ingest_lane_admits, key_covers)
from cascade import Ledger, refresh_showtime_rollup, void_reserved_orders
from errors import ApiError
from response import object_response, paged
from store import new_record, now, ordered, touch
from validate import (FORMATS, bad, body, find, insert, must_find, opt_str, query_str,
                      req_bool, req_enum, req_id, req_instant, req_str, rows)

bp = Blueprint("tech", __name__)

ASSET_READ = (ROLE_PROGRAMMER, ROLE_TECH, ROLE_EXEC)
KEY_READ = (ROLE_TECH, ROLE_EXEC)


def arm_showtimes_for_key(key, ledger):
    """A fresh covering key arms the calendar (PRD 3.4)."""
    for showtime in ordered(rows("showtimes")):
        if showtime["venue_id"] != key["venue_id"]:
            continue
        if showtime["dcp_asset_id"] != key["dcp_asset_id"]:
            continue
        if showtime["status"] != "SCHEDULED":
            continue
        if showtime["playback_status"] not in ("UNVERIFIED", "PLAYBACK_FAILED"):
            continue
        if key_covers(key, showtime):
            showtime["playback_status"] = "KEY_PENDING"
            ledger.mark(showtime)


@bp.post("/dcp-assets")
def create_asset():
    authorize((ROLE_TECH,))
    payload = body()
    fmt = req_enum(payload, "format", FORMATS)
    is_encrypted = req_bool(payload, "is_encrypted")
    carrier_ref = opt_str(payload, "carrier_ref")
    window_start = req_instant(payload, "ingest_window_start_at")
    window_end = req_instant(payload, "ingest_window_end_at")
    if window_end <= window_start:
        raise bad("ingest_window_end_at must be strictly after ingest_window_start_at.")
    title_id = req_id(payload, "title_id")
    distributor_id = req_id(payload, "source_distributor_id")
    venue_id = req_id(payload, "venue_id")
    must_find("titles", title_id)
    must_find("distributors", distributor_id)
    venue = must_find("venues", venue_id)
    if fmt not in venue["supported_formats"]:
        raise ApiError("ERR_FORMAT_INCOMPATIBLE",
                       "The booth cannot run format %s." % fmt)
    if not ingest_lane_admits(venue, window_start, window_end):
        raise ApiError("ERR_INGEST_LANE_CAPACITY_EXCEEDED",
                       "The ingest window exceeds the venue's lane count.")
    row = new_record(
        title_id=title_id,
        source_distributor_id=distributor_id,
        venue_id=venue_id,
        format=fmt,
        is_encrypted=is_encrypted,
        carrier_ref=carrier_ref,
        ingest_window_start_at=window_start,
        ingest_window_end_at=window_end,
        status="REQUESTED",
        received_at=None,
        ingested_at=None,
    )
    insert("assets", row)
    return object_response(serialize.asset(row), 201)


@bp.get("/dcp-assets/<asset_id>")
def read_asset(asset_id):
    authorize(ASSET_READ)
    return object_response(serialize.asset(must_find("assets", asset_id)))


@bp.get("/dcp-assets")
def list_assets():
    authorize(ASSET_READ)
    found = rows("assets")
    for name in ("title_id", "source_distributor_id", "venue_id", "status"):
        value = query_str(name)
        if value is not None:
            found = [a for a in found if a[name] == value]
    return paged(ordered(found), serialize.asset)


@bp.post("/dcp-assets/<asset_id>/traffic-update")
def traffic_update(asset_id):
    authorize((ROLE_TECH,))
    payload = body()
    new_status = req_enum(payload, "new_status", ASSET_CHAIN)
    carrier_ref = opt_str(payload, "carrier_ref")
    asset = must_find("assets", asset_id)
    current = asset["status"]
    index = ASSET_CHAIN.index(current)
    expected = ASSET_CHAIN[index + 1] if index + 1 < len(ASSET_CHAIN) else None
    if new_status != expected:
        raise ApiError("ERR_DCP_ASSET_INVALID_STATE",
                       "Print traffic advances one step at a time from %s." % current)
    if new_status == "INGESTING" and now() < asset["ingest_window_start_at"]:
        raise ApiError("ERR_DCP_ASSET_INVALID_STATE",
                       "The booked server ingest window has not opened yet.")
    if new_status == "RETURNED":
        for showtime in rows("showtimes"):
            if showtime["dcp_asset_id"] == asset["id"] and showtime["status"] == "SCHEDULED":
                raise ApiError("ERR_DCP_ASSET_INVALID_STATE",
                               "A screening is still booked to play this package.")
    asset["status"] = new_status
    if new_status in ("IN_TRANSIT", "RETURNED") and carrier_ref is not None:
        asset["carrier_ref"] = carrier_ref
    if new_status == "RECEIVED":
        asset["received_at"] = now()
    if new_status == "INGESTED":
        asset["ingested_at"] = now()
    touch(asset)
    return object_response(serialize.asset(asset))


@bp.post("/kdm-keys")
def issue_key():
    authorize((ROLE_TECH,))
    payload = body()
    server_ref = req_str(payload, "server_ref")
    valid_from = req_instant(payload, "valid_from")
    valid_until = req_instant(payload, "valid_until")
    if valid_until <= valid_from:
        raise bad("valid_until must be strictly after valid_from.")
    asset_id = req_id(payload, "dcp_asset_id")
    venue_id = req_id(payload, "venue_id")
    asset = must_find("assets", asset_id)
    must_find("venues", venue_id)
    if not asset["is_encrypted"]:
        raise bad("A KDM cannot be cut for an unencrypted package.")
    if find_key_overlap(asset_id, venue_id, valid_from, valid_until) is not None:
        raise ApiError("ERR_KDM_WINDOW_OVERLAP",
                       "An issued key for this package and venue already covers that span.")
    if asset["venue_id"] != venue_id:
        raise ApiError("ERR_REFERENCE_MISMATCH",
                       "The package belongs to a different auditorium.")
    row = new_record(
        dcp_asset_id=asset_id,
        venue_id=venue_id,
        server_ref=server_ref,
        valid_from=valid_from,
        valid_until=valid_until,
        status="ISSUED",
        revoked_reason=None,
    )
    insert("keys", row)
    ledger = Ledger()
    arm_showtimes_for_key(row, ledger)
    ledger.flush()
    return object_response(serialize.key(row), 201)


@bp.get("/kdm-keys/<key_id>")
def read_key(key_id):
    authorize(KEY_READ)
    return object_response(serialize.key(must_find("keys", key_id)))


@bp.get("/kdm-keys")
def list_keys():
    authorize(KEY_READ)
    found = rows("keys")
    for name in ("dcp_asset_id", "venue_id", "status"):
        value = query_str(name)
        if value is not None:
            found = [k for k in found if k[name] == value]
    return paged(ordered(found), serialize.key)


@bp.post("/kdm-keys/<key_id>/revoke")
def revoke_key(key_id):
    authorize((ROLE_TECH, ROLE_EXEC))
    payload = body()
    revoked_reason = req_str(payload, "revoked_reason")
    key = must_find("keys", key_id)
    if key["status"] != "ISSUED":
        raise ApiError("ERR_KDM_KEY_INVALID_STATE",
                       "A key in %s cannot be revoked." % key["status"])
    ledger = Ledger()
    key["status"] = "REVOKED"
    key["revoked_reason"] = revoked_reason
    ledger.mark(key)
    for showtime in ordered(rows("showtimes")):
        if showtime["venue_id"] != key["venue_id"]:
            continue
        if showtime["dcp_asset_id"] != key["dcp_asset_id"]:
            continue
        if showtime["status"] != "SCHEDULED":
            continue
        if showtime["playback_status"] not in ("KEY_PENDING", "PLAYBACK_VERIFIED"):
            continue
        still_covered = any(other["id"] != key["id"] and other["status"] == "ISSUED"
                            and key_covers(other, showtime) for other in rows("keys"))
        if still_covered:
            continue
        showtime["playback_status"] = "UNVERIFIED"
        if showtime["sale_status"] in ("ON_SALE", "SOLD_OUT"):
            showtime["sale_status"] = "SALES_CLOSED"
        ledger.mark(showtime)
        void_reserved_orders(showtime, ledger)
        refresh_showtime_rollup(showtime, ledger)
    ledger.flush()
    return object_response(serialize.key(key))
