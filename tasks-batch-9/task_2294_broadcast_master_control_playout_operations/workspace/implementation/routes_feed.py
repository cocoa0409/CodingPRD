"""Network feed windows: planning, the backtiming plan, joining and breaking away (PRD 3.7)."""
from flask import Blueprint, request

import auth
import calc
import cascades
import plcalc
import store
import timeutil
import views
from constants import (BACKTIMING_MODES, FEED_SOURCES, LATE_JOIN_LIMIT_SECONDS)
from errors import fail
from response import created, listing, ok
from validate import F, validate

bp = Blueprint("feed", __name__)

PLANNERS = ["MasterControlOperator", "ProgramDirector", "StationAdmin"]
OPERATORS = ["MasterControlOperator", "StationAdmin"]
WINDOW_READERS = ["MasterControlOperator", "ProgramDirector", "BroadcastEngineer",
                  "ComplianceOfficer", "StationAdmin"]


def _guarded(window):
    guard = int(window.get("guard_seconds") or 0)
    return (timeutil.sec(timeutil.plus(window["join_utc"], -guard)),
            timeutil.sec(timeutil.plus(window["breakaway_utc"], guard)))


def check_overlap(candidate, channel_id, exclude_id=None):
    low, high = _guarded(candidate)
    for other in store.windows_of(channel_id):
        if other["id"] == exclude_id or other["state"] not in ("PLANNED", "JOINED"):
            continue
        other_low, other_high = _guarded(other)
        if low <= other_high and other_low <= high:
            fail("ERR_FEED_WINDOW_OVERLAP",
                 "The guarded interval intersects another window on this channel.")


def resolve_anchor(channel, anchor_sequence_number):
    playlist = plcalc.plan_playlist(channel)
    if playlist is None:
        fail("ERR_ANCHOR_ITEM_NOT_FOUND", "The channel has no armed or on-air playlist.")
    for item in store.items_of(playlist["id"]):
        if int(item["sequence_number"]) == int(anchor_sequence_number):
            if item["element_kind"] != "NETWORK_JOIN":
                fail("ERR_ANCHOR_ITEM_NOT_FOUND",
                     "The anchor element is not a NETWORK_JOIN element.")
            return playlist, item
    fail("ERR_ANCHOR_ITEM_NOT_FOUND", "No element carries that sequence number.")


def write_plan(window, plan):
    window["plan_action"] = plan["plan_action"]
    window["backtime_pad_seconds"] = plan["backtime_pad_seconds"]
    window["backtime_trim_seconds"] = plan["backtime_trim_seconds"]
    window["residual_dead_air_seconds"] = plan["residual_dead_air_seconds"]
    window["late_join_seconds"] = plan["late_join_seconds"]
    window["skipped_item_sequences"] = list(plan["skipped_item_sequences"])
    window["plan_computed_utc"] = store.clock()
    return window


@bp.post("/network-feed-windows")
def create_window():
    auth.authorize(PLANNERS)
    body = validate(request.get_json(silent=True), [
        F("channel_id", "str", required=True),
        F("feed_source", "enum", required=True, values=FEED_SOURCES),
        F("anchor_sequence_number", "int", required=True, minimum=1),
        F("join_utc", "ts", required=True),
        F("breakaway_utc", "ts", required=True),
        F("backtiming_mode", "enum", required=True, values=BACKTIMING_MODES),
        F("guard_seconds", "int", minimum=0, maximum=30),
        F("live_encoder_units", "int", minimum=1),
    ])
    if timeutil.sec(body["breakaway_utc"]) <= timeutil.sec(body["join_utc"]):
        fail("ERR_INVALID_FIELD_VALUE", "breakaway_utc must be strictly after join_utc.")
    channel = auth.channel(body["channel_id"])
    candidate = {
        "id": None,
        "join_utc": body["join_utc"],
        "breakaway_utc": body["breakaway_utc"],
        "guard_seconds": 2 if body.get("guard_seconds") is None else int(body["guard_seconds"]),
        "live_encoder_units": 1 if body.get("live_encoder_units") is None
        else int(body["live_encoder_units"]),
    }
    check_overlap(candidate, channel["id"])
    mux = store.multiplex_of_channel(channel)
    if mux is not None:
        peak = calc.encoder_peak(mux, extra_window=candidate)
        if peak > int(mux["live_encoder_units_total"]):
            fail("ERR_ENCODER_CAPACITY_EXCEEDED",
                 "The window would drive live-encoder occupancy to %d units." % peak)
    playlist, _anchor = resolve_anchor(channel, body["anchor_sequence_number"])

    rec = store.base()
    rec.update({
        "channel_id": channel["id"],
        "feed_source": body["feed_source"],
        "anchor_sequence_number": int(body["anchor_sequence_number"]),
        "join_utc": body["join_utc"],
        "breakaway_utc": body["breakaway_utc"],
        "guard_seconds": candidate["guard_seconds"],
        "live_encoder_units": candidate["live_encoder_units"],
        "backtiming_mode": body["backtiming_mode"],
        "plan_action": None,
        "backtime_pad_seconds": 0,
        "backtime_trim_seconds": 0,
        "residual_dead_air_seconds": 0,
        "late_join_seconds": 0,
        "skipped_item_sequences": [],
        "plan_computed_utc": None,
        "state": "PLANNED",
    })
    store.add(store.feed_windows, rec)
    plan = plcalc.compute_plan(rec, rec["join_utc"], store.clock(), playlist=playlist)
    write_plan(rec, plan)
    if mux is not None:
        calc.refresh_encoder_peak(mux)
    return created(views.plain(rec))


@bp.get("/network-feed-windows/<ident>")
def read_window(ident):
    auth.authorize(WINDOW_READERS, mutating=False)
    return ok(views.plain(auth.feed_window(ident)))


# --- join ------------------------------------------------------------------

@bp.post("/network-feed-windows/<ident>/join")
def join(ident):
    auth.authorize(OPERATORS, cert=True)
    body = validate(request.get_json(silent=True), [F("actual_join_utc", "ts")])
    window = auth.feed_window(ident)
    channel = store.channels.get(window["channel_id"])
    if window["state"] != "PLANNED":
        fail("ERR_FEED_WINDOW_INVALID_STATE", "Only a planned window may be joined.")
    if channel is not None and channel["air_status"] == "EAS_OVERRIDE":
        fail("ERR_EAS_OVERRIDE_ACTIVE", "An emergency override owns the channel output.")
    if channel is None or channel["air_status"] != "ON_AIR":
        fail("ERR_CHANNEL_NOT_ON_AIR", "The channel is not on air.")
    if channel["posture"] == "SUSPENDED":
        fail("ERR_CHANNEL_SUSPENDED_POSTURE", "The channel posture is suspended.")
    playlist = store.on_air_playlist(channel["id"])
    if playlist is None:
        fail("ERR_PLAYLIST_NOT_ON_AIR", "The channel has no playlist on air.")

    now = store.clock()
    guard = int(window["guard_seconds"] or 0)
    earliest = timeutil.plus(window["join_utc"], -guard)
    latest = timeutil.plus(window["join_utc"], LATE_JOIN_LIMIT_SECONDS)
    if timeutil.sec(now) < timeutil.sec(earliest) or timeutil.sec(now) > timeutil.sec(latest):
        fail("ERR_JOIN_OUTSIDE_GUARD_WINDOW",
             "The join must be issued inside the guard window.")

    plan = plcalc.compute_plan(window, window["join_utc"], now, playlist=playlist)
    tail = plan["_tail"]
    sequences = set(plan["skipped_item_sequences"])
    for item in tail:
        if int(item["sequence_number"]) in sequences and item["element_kind"] == "COMMERCIAL":
            fail("ERR_TRIM_EXCEEDS_MAX", "A commercial element may never be dropped by a plan.")
    for item_id, take in plan["_trims"].items():
        item = store.items.get(item_id)
        if item is None:
            continue
        if int(take) > int(item.get("max_trim_seconds") or 0):
            fail("ERR_TRIM_EXCEEDS_MAX", "The plan would trim more than max_trim_seconds allows.")

    at = body.get("actual_join_utc") or now
    if timeutil.sec(at) > timeutil.sec(now):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "actual_join_utc may not lie in the future.")
    user = auth.actor_id()
    write_plan(window, plan)

    action = plan["plan_action"]
    if action == "PAD_WITH_FILLER" and plan["backtime_pad_seconds"] > 0:
        numbers = [int(i["sequence_number"]) for i in store.items_of(playlist["id"])]
        rec = store.base()
        rec.update({
            "playlist_id": playlist["id"],
            "asset_id": None,
            "spot_order_id": None,
            "feed_window_id": window["id"],
            "replaces_item_id": None,
            "sequence_number": (max(numbers) + 1) if numbers else 1,
            "element_kind": "FILLER",
            "house_number": None,
            "scheduled_start_utc": timeutil.plus(window["join_utc"],
                                                 -int(plan["backtime_pad_seconds"])),
            "scheduled_duration_seconds": int(plan["backtime_pad_seconds"]),
            "max_trim_seconds": 0,
            "playout_status": "SCHEDULED",
            "clearance_status": "CLEARED",
            "actual_start_utc": None,
            "measured_duration_seconds": None,
            "is_makegood": False,
            "trim_applied_seconds": 0,
        })
        store.add(store.items, rec)
        cascades.append_asrun(playlist, rec, "FILLER_INSERT", at, measured=0,
                              source="OPERATOR", recorded_by=user)
    elif action in ("TRIM_TAIL", "SKIP_ELEMENTS"):
        for item_id, take in plan["_trims"].items():
            item = store.items.get(item_id)
            if item is None or not take:
                continue
            item["scheduled_duration_seconds"] = int(item["scheduled_duration_seconds"]) - int(take)
            item["trim_applied_seconds"] = int(item.get("trim_applied_seconds") or 0) + int(take)
            store.bump(item)
        for item in tail:
            if int(item["sequence_number"]) in sequences:
                cascades.skip_item(item, at, source="OPERATOR", recorded_by=user)
    if action in ("HARD_CUT", "JOIN_IN_PROGRESS"):
        for item in store.items_of(playlist["id"]):
            if item["playout_status"] == "PLAYING":
                cascades.truncate_item(item, at, source="OPERATOR", recorded_by=user)

    cascades.append_asrun(playlist, None, "JOIN", at, measured=0,
                          source="OPERATOR", recorded_by=user)
    window["state"] = "JOINED"
    store.bump(window)
    plcalc.recompute_playlist(playlist, bump=True)
    mux = store.multiplex_of_channel(channel)
    if mux is not None:
        calc.refresh_encoder_peak(mux)
    return ok(views.plain(window))


@bp.post("/network-feed-windows/<ident>/breakaway")
def breakaway(ident):
    auth.authorize(OPERATORS, cert=True)
    body = validate(request.get_json(silent=True), [F("actual_breakaway_utc", "ts")])
    window = auth.feed_window(ident)
    channel = store.channels.get(window["channel_id"])
    if window["state"] != "JOINED":
        fail("ERR_FEED_WINDOW_INVALID_STATE", "Only a joined window may break away.")
    now = store.clock()
    guard = int(window["guard_seconds"] or 0)
    earliest = timeutil.plus(window["breakaway_utc"], -guard)
    if timeutil.sec(now) < timeutil.sec(earliest):
        fail("ERR_BREAKAWAY_TOO_EARLY", "The breakaway may not be executed this early.")
    at = body.get("actual_breakaway_utc") or now
    if timeutil.sec(at) > timeutil.sec(now):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "actual_breakaway_utc may not lie in the future.")

    playlist = store.on_air_playlist(channel["id"]) if channel else None
    plan = plcalc.compute_plan(window, window["breakaway_utc"], now, playlist=playlist)
    for item_id, take in plan["_trims"].items():
        item = store.items.get(item_id)
        if item is None:
            continue
        if int(take) > int(item.get("max_trim_seconds") or 0):
            fail("ERR_TRIM_EXCEEDS_MAX", "The plan would trim more than max_trim_seconds allows.")
    window["residual_dead_air_seconds"] = plan["residual_dead_air_seconds"]
    window["plan_computed_utc"] = now
    if playlist is not None:
        cascades.append_asrun(playlist, None, "BREAKAWAY", at, measured=0,
                              source="OPERATOR", recorded_by=auth.actor_id())
        plcalc.recompute_playlist(playlist, bump=True)
    window["state"] = "BROKEN_AWAY"
    store.bump(window)
    mux = store.multiplex_of_channel(channel) if channel else None
    if mux is not None:
        calc.refresh_encoder_peak(mux)
    return ok(views.plain(window))
