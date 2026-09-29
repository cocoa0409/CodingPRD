"""Channels: admission, bit-pool participation, air state and child collections."""
from flask import Blueprint, request

import auth
import calc
import cascades
import plcalc
import store
import timeutil
import views
from constants import (AIR_STATUSES, ALLOCATION_STATES, ALLOCATION_STATES_INPUT,
                       FEED_WINDOW_STATES, PLAYLIST_STATUSES, POSTURES,
                       RESOLUTION_CLASSES, RESOLUTION_FLOOR_MINIMUM, SERVICE_CLASSES)
from errors import fail
from response import created, listing, ok
from validate import F, enum_filter, validate

bp = Blueprint("channel", __name__)

ENGINEER = ["BroadcastEngineer", "StationAdmin"]
MASTER_CONTROL = ["MasterControlOperator", "StationAdmin"]
READERS = ["MasterControlOperator", "ProgramDirector", "BroadcastEngineer",
           "TrafficCoordinator", "ComplianceOfficer", "StationAdmin"]
PLAYLIST_READERS = ["MasterControlOperator", "ProgramDirector", "TrafficCoordinator",
                    "ComplianceOfficer", "StationAdmin"]
WINDOW_READERS = ["MasterControlOperator", "ProgramDirector", "BroadcastEngineer", "StationAdmin"]


# --- admission -------------------------------------------------------------

@bp.post("/channels")
def create_channel():
    auth.authorize(ENGINEER)
    body = validate(request.get_json(silent=True), [
        F("multiplex_id", "str", required=True),
        F("call_sign", "str", required=True, min_len=1, max_len=32),
        F("channel_number", "str", required=True, pattern=r"^[0-9]{1,3}\.[0-9]{1,2}$"),
        F("service_class", "enum", required=True, values=SERVICE_CLASSES),
        F("resolution_class", "enum", required=True, values=RESOLUTION_CLASSES),
        F("requested_bitrate_kbps", "int", required=True, minimum=1),
        F("floor_bitrate_kbps", "int", required=True, minimum=1),
        F("priority_rank", "int", required=True, minimum=1, maximum=99),
        F("parent_channel_id", "str"),
        F("allocation_state", "enum", values=ALLOCATION_STATES_INPUT),
        F("expected_multiplex_version", "int", minimum=0),
    ])
    mux = auth.multiplex(body["multiplex_id"])
    parent = None
    if body.get("parent_channel_id"):
        parent = auth.channel(body["parent_channel_id"])
    if body.get("expected_multiplex_version") is not None:
        if int(body["expected_multiplex_version"]) != int(mux["version"]):
            fail("ERR_STALE_MULTIPLEX_VERSION", "The multiplex version has moved on.")

    number = body["channel_number"]
    # channel_number is unique across the entire station and across all
    # multiplexes, not merely within one transport stream (PRD 3.2).
    for existing in store.rows(store.channels):
        if existing["channel_number"] == number:
            fail("ERR_DUPLICATE_CHANNEL_NUMBER",
                 "channel_number %s is already carried by this station." % number)

    service_class = body["service_class"]
    if service_class == "SUBCHANNEL" and parent is None:
        fail("ERR_SUBCHANNEL_PARENT_REQUIRED", "A SUBCHANNEL must name a parent channel.")
    if service_class == "PRIMARY" and parent is not None:
        fail("ERR_PRIMARY_CHANNEL_PARENT_FORBIDDEN", "A PRIMARY channel may not name a parent.")
    if parent is not None:
        if parent["service_class"] != "PRIMARY":
            fail("ERR_INVALID_CHANNEL_PARENT", "Only a PRIMARY channel may parent a subchannel.")
        if parent["multiplex_id"] != mux["id"]:
            fail("ERR_CROSS_MULTIPLEX_PARENT", "The parent channel sits on another multiplex.")

    floor = int(body["floor_bitrate_kbps"])
    requested = int(body["requested_bitrate_kbps"])
    if floor > requested:
        fail("ERR_BITRATE_FLOOR_EXCEEDS_REQUEST",
             "floor_bitrate_kbps may not exceed requested_bitrate_kbps.")
    minimum = RESOLUTION_FLOOR_MINIMUM[body["resolution_class"]]
    if floor < minimum:
        fail("ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM",
             "%s requires a floor of at least %d kbps." % (body["resolution_class"], minimum))

    state = body.get("allocation_state") or "ACTIVE"
    if state == "ACTIVE" and calc.floor_sum_unsatisfiable(mux, extra_floor=floor):
        fail("ERR_BITRATE_FLOOR_UNSATISFIABLE",
             "The floors of the channels that must be ACTIVE exceed effective capacity.")

    rec = store.base()
    rec.update({
        "multiplex_id": mux["id"],
        "parent_channel_id": parent["id"] if parent else None,
        "call_sign": body["call_sign"],
        "channel_number": number,
        "service_class": service_class,
        "resolution_class": body["resolution_class"],
        "requested_bitrate_kbps": requested,
        "floor_bitrate_kbps": floor,
        "priority_rank": int(body["priority_rank"]),
        "allocated_bitrate_kbps": 0,
        "allocation_state": state,
        "air_status": "DARK",
        "posture": "NORMAL",
        "open_fault_count": 0,
        "_pin_allocated_kbps": None,
    })
    store.add(store.channels, rec)
    calc.run_waterfall(mux, exempt_channel_id=rec["id"])
    store.bump(mux)
    return created(views.plain(rec))


@bp.get("/channels/<ident>")
def read_channel(ident):
    auth.authorize(READERS, mutating=False)
    return ok(views.plain(auth.channel(ident)))


@bp.get("/channels")
def list_channels():
    auth.authorize(READERS, mutating=False)
    rows = store.rows(store.channels)
    for name, vocabulary in (("service_class", SERVICE_CLASSES),
                             ("allocation_state", ALLOCATION_STATES),
                             ("air_status", AIR_STATUSES),
                             ("posture", POSTURES)):
        value = enum_filter(name, vocabulary)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    value = request.args.get("multiplex_id")
    if value:
        rows = [r for r in rows if r.get("multiplex_id") == value]
    parent = request.args.get("parent_channel_id")
    if parent:
        rows = [r for r in rows if r.get("parent_channel_id") == parent]
    rows.sort(key=lambda r: (r["priority_rank"], r["created_at"], r["_seq"]))
    return listing(rows, views.plain)


@bp.patch("/channels/<ident>/allocation")
def patch_allocation(ident):
    auth.authorize(ENGINEER)
    body = validate(request.get_json(silent=True), [
        F("expected_multiplex_version", "int", required=True, minimum=0),
        F("requested_bitrate_kbps", "int", minimum=1),
        F("floor_bitrate_kbps", "int", minimum=1),
        F("priority_rank", "int", minimum=1, maximum=99),
        F("allocation_state", "enum", values=ALLOCATION_STATES_INPUT),
        F("pin_allocated_kbps", "int", minimum=0),
    ])
    channel = auth.channel(ident)
    mux = store.multiplexes.get(channel["multiplex_id"])
    if int(body["expected_multiplex_version"]) != int(mux["version"]):
        fail("ERR_STALE_MULTIPLEX_VERSION", "The multiplex version has moved on.")

    # Safety band: suspended posture outranks every later band, capacity included
    # (PRD 2.8, "Suspended posture outranks capacity").
    if channel["posture"] == "SUSPENDED":
        fail("ERR_CHANNEL_SUSPENDED_POSTURE",
             "The channel's posture is SUSPENDED.")

    floor = int(body["floor_bitrate_kbps"]) if body.get("floor_bitrate_kbps") is not None \
        else int(channel["floor_bitrate_kbps"])
    requested = int(body["requested_bitrate_kbps"]) if body.get("requested_bitrate_kbps") is not None \
        else int(channel["requested_bitrate_kbps"])
    if floor > requested:
        fail("ERR_BITRATE_FLOOR_EXCEEDS_REQUEST",
             "floor_bitrate_kbps may not exceed requested_bitrate_kbps.")
    minimum = RESOLUTION_FLOOR_MINIMUM[channel["resolution_class"]]
    if floor < minimum:
        fail("ERR_BITRATE_FLOOR_BELOW_RESOLUTION_MINIMUM",
             "%s requires a floor of at least %d kbps." % (channel["resolution_class"], minimum))

    state = body.get("allocation_state") or (
        "STANDBY" if channel["allocation_state"] == "STANDBY" else "ACTIVE")
    if state == "ACTIVE" and calc.floor_sum_unsatisfiable(
            mux, extra_floor=floor, exclude_channel_id=channel["id"]):
        fail("ERR_BITRATE_FLOOR_UNSATISFIABLE",
             "The floors of the channels that must be ACTIVE exceed effective capacity.")

    pin = body.get("pin_allocated_kbps")
    if pin is not None:
        pin = int(pin)
        if calc.pinned_total(mux, extra_pin=pin, exclude_channel_id=channel["id"]) \
                > calc.effective_capacity(mux):
            fail("ERR_MULTIPLEX_CAPACITY_EXCEEDED",
                 "The pinned total would exceed the effective capacity of the multiplex.")

    channel["floor_bitrate_kbps"] = floor
    channel["requested_bitrate_kbps"] = requested
    if body.get("priority_rank") is not None:
        channel["priority_rank"] = int(body["priority_rank"])
    if body.get("allocation_state") is not None:
        channel["allocation_state"] = state
    elif channel["allocation_state"] == "STARVED":
        channel["allocation_state"] = "ACTIVE"
    if pin is not None:
        channel["_pin_allocated_kbps"] = pin
    store.bump(channel)
    calc.run_waterfall(mux)
    store.bump(mux)
    return ok(views.plain(channel))


# --- air state -------------------------------------------------------------

LEGAL_AIR_MOVES = {
    "DARK": ("ON_AIR",),
    "ON_AIR": ("BARS_AND_TONE", "DARK"),
    "BARS_AND_TONE": ("ON_AIR", "DARK"),
    "EAS_OVERRIDE": (),
}


@bp.post("/channels/<ident>/air-state")
def air_state(ident):
    auth.authorize(MASTER_CONTROL, cert=True)
    body = validate(request.get_json(silent=True), [
        F("target_air_status", "enum", required=True, values=AIR_STATUSES),
        F("reason", "str"),
    ])
    target = body["target_air_status"]
    channel = auth.channel(ident)
    current = channel["air_status"]
    if target == "EAS_OVERRIDE" or target not in LEGAL_AIR_MOVES[current]:
        fail("ERR_CHANNEL_INVALID_AIR_STATE",
             "%s to %s is not a declared air-state transition." % (current, target))
    if target == "ON_AIR":
        # Four independent conditions, each with its own refusal code (PRD 3.3).
        if channel["allocation_state"] != "ACTIVE" \
                or int(channel["allocated_bitrate_kbps"]) < int(channel["floor_bitrate_kbps"]):
            fail("ERR_CHANNEL_ALLOCATION_STARVED",
                 "The channel holds no usable allocation on its multiplex.")
        tx = store.transmitter_of_channel(channel)
        if tx is not None and tx["operational_state"] == "OFF_AIR":
            fail("ERR_TRANSMITTER_OFF_AIR", "The parent transmitter is off air.")
        if channel["posture"] == "SUSPENDED":
            fail("ERR_CHANNEL_SUSPENDED_POSTURE", "A suspended channel may not be lit.")
        if current == "BARS_AND_TONE":
            for fault in calc.open_faults(channel["id"]):
                if fault["severity"] == "CRITICAL":
                    fail("ERR_CRITICAL_FAULT_OPEN",
                         "An open critical fault blocks the return to air.")
    if calc.active_overrides(channel["id"]):
        fail("ERR_EAS_OVERRIDE_ACTIVE",
             "An active emergency override owns the channel output.")

    now = store.clock()
    user = auth.ctx().user_id
    playlist = store.on_air_playlist(channel["id"])
    if target in ("BARS_AND_TONE", "DARK") and playlist is not None:
        for item in store.items_of(playlist["id"]):
            if item["playout_status"] == "PLAYING":
                cascades.truncate_item(item, now, source="OPERATOR", recorded_by=user)
        if target == "DARK":
            for item in store.items_of(playlist["id"]):
                if item["playout_status"] in ("SCHEDULED", "CUED"):
                    cascades.preempt_item(item, now, source="OPERATOR", recorded_by=user)
        plcalc.recompute_playlist(playlist, bump=True)
    channel["air_status"] = target
    calc.recompute_posture(channel, bump=False)
    store.bump(channel)
    if target == "DARK":
        cascades.abandon_windows(channel)
    return ok(views.plain(channel))


# --- child collections -----------------------------------------------------

@bp.get("/channels/<ident>/playlists")
def channel_playlists(ident):
    auth.authorize(PLAYLIST_READERS, mutating=False)
    channel = auth.channel(ident)
    rows = store.playlists_of(channel["id"])
    status = enum_filter("status", PLAYLIST_STATUSES)
    day = request.args.get("broadcast_day")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if day:
        rows = [r for r in rows if r["broadcast_day"] == day]
    rows.sort(key=lambda r: (r["broadcast_day"], r["_seq"]), reverse=True)
    return listing(rows, views.plain)


@bp.get("/channels/<ident>/feed-windows")
def channel_windows(ident):
    auth.authorize(WINDOW_READERS, mutating=False)
    channel = auth.channel(ident)
    rows = store.windows_of(channel["id"])
    state = enum_filter("state", FEED_WINDOW_STATES)
    if state:
        rows = [r for r in rows if r["state"] == state]
    rows.sort(key=lambda r: (timeutil.sec(r["join_utc"]), r["_seq"]))
    return listing(rows, views.plain)
