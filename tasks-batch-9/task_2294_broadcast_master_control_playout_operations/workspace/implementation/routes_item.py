"""Playlist elements: reads, playout events, substitution and the per-element as-run log."""
from flask import Blueprint, request

import auth
import calc
import cascades
import plcalc
import store
import timeutil
import views
from constants import (ASRUN_SOURCES, CLEARANCE_REQUIRED_KINDS, HOUR_SECONDS, PLAYOUT_STATUSES)
from errors import fail
from response import created, listing, ok
from routes_playlist import build_item, derive_clearance
from validate import F, validate

bp = Blueprint("item", __name__)

ITEM_READERS = ["MasterControlOperator", "QCTechnician", "ProgramDirector",
                "TrafficCoordinator", "ComplianceOfficer", "StationAdmin"]
ASRUN_READERS = ["MasterControlOperator", "ProgramDirector", "TrafficCoordinator",
                 "ComplianceOfficer", "StationAdmin"]
DIRECT_EVENT_KINDS = ["CUE", "START", "END", "TRUNCATION", "SKIP", "PREEMPTION"]
EVENT_PRECONDITION = {
    "CUE": ("SCHEDULED",),
    "START": ("CUED",),
    "END": ("PLAYING",),
    "TRUNCATION": ("PLAYING",),
    "SKIP": ("SCHEDULED", "CUED"),
    "PREEMPTION": ("SCHEDULED", "CUED"),
}


def hour_index(playlist, instant):
    offset = timeutil.delta_seconds(playlist["schedule_start_utc"], instant)
    return offset // HOUR_SECONDS


@bp.get("/playlist-items/<ident>")
def read_item(ident):
    auth.authorize(ITEM_READERS, mutating=False)
    return ok(views.item_view(auth.playlist_item(ident)))


@bp.get("/playlist-items")
def list_all_items():
    auth.authorize(ITEM_READERS, mutating=False)
    rows = store.rows(store.items)
    for name in ("playlist_id", "asset_id", "spot_order_id", "feed_window_id", "replaces_item_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    status = request.args.get("playout_status")
    if status:
        if status not in PLAYOUT_STATUSES:
            fail("ERR_INVALID_ENUM_VALUE", "playout_status '%s' is not recognised." % status)
        rows = [r for r in rows if r["playout_status"] == status]
    rows.sort(key=lambda r: (r["playlist_id"], int(r["sequence_number"]), r["_seq"]))
    return listing(rows, views.item_view)


@bp.get("/playlist-items/<ident>/as-run")
def item_asrun(ident):
    auth.authorize(ASRUN_READERS, mutating=False)
    item = auth.playlist_item(ident)
    return listing(store.asrun_of_item(item["id"]), views.plain)


# --- playout events --------------------------------------------------------

@bp.post("/playlist-items/<ident>/playout-events")
def playout_event(ident):
    auth.authorize(["MasterControlOperator", "StationAdmin"], cert=True)
    body = validate(request.get_json(silent=True), [
        F("event_kind", "enum", required=True, values=DIRECT_EVENT_KINDS),
        F("event_utc", "ts", required=True),
        F("measured_duration_seconds", "int", minimum=0),
        F("source", "enum", values=ASRUN_SOURCES),
        F("force_preempt_guaranteed", "bool"),
    ])
    kind = body["event_kind"]
    if kind == "END" and body.get("measured_duration_seconds") is None:
        fail("ERR_MISSING_REQUIRED_FIELD", "measured_duration_seconds is required on an end event.")
    item = auth.playlist_item(ident)
    playlist = store.playlists.get(item["playlist_id"])
    channel = store.channels.get(playlist["channel_id"]) if playlist else None

    if item["playout_status"] not in EVENT_PRECONDITION[kind]:
        fail("ERR_ITEM_INVALID_PLAYOUT_STATE",
             "A %s event is not legal for an element in %s." % (kind, item["playout_status"]))
    if kind == "CUE" and playlist["status"] != "ON_AIR":
        fail("ERR_PLAYLIST_NOT_ON_AIR", "The owning playlist is not on air.")
    if kind in ("CUE", "START") and channel is not None and channel["posture"] == "SUSPENDED":
        fail("ERR_CHANNEL_SUSPENDED_POSTURE", "The channel posture is suspended.")
    if kind == "START" and channel is not None and channel["allocation_state"] == "STARVED":
        fail("ERR_CHANNEL_ALLOCATION_STARVED",
             "A starved channel cannot start an element.")
    if kind == "CUE" and item["element_kind"] in CLEARANCE_REQUIRED_KINDS \
            and item["clearance_status"] != "CLEARED":
        fail("ERR_UNCLEARED_CONTENT_ON_AIR", "The element is not cleared for air.")
    if kind in ("CUE", "START") and channel is not None \
            and channel["air_status"] == "EAS_OVERRIDE":
        fail("ERR_EAS_OVERRIDE_ACTIVE", "An emergency override owns the channel output.")
    if kind == "CUE":
        for other in store.items_of(playlist["id"]):
            if other["id"] != item["id"] and other["playout_status"] == "CUED":
                fail("ERR_ITEM_INVALID_PLAYOUT_STATE",
                     "Another element of this playlist is already cued.")
    if kind == "START":
        for other in store.items_of(playlist["id"]):
            if other["id"] != item["id"] and other["playout_status"] == "PLAYING":
                fail("ERR_ITEM_INVALID_PLAYOUT_STATE",
                     "Another element of this playlist is already playing.")

    event_utc = body["event_utc"]
    entries = store.asrun_of(playlist["id"])
    if entries and timeutil.sec(event_utc) < timeutil.sec(entries[-1]["event_utc"]):
        fail("ERR_PLAYOUT_EVENT_OUT_OF_ORDER",
             "The as-run log is append-only in event time order.")
    if timeutil.sec(event_utc) > timeutil.sec(store.clock()):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "event_utc may not lie ahead of the logical clock.")
    if kind == "PREEMPTION":
        cascades.guard_preemption([item], bool(body.get("force_preempt_guaranteed")))

    user = auth.actor_id()
    source = body.get("source") or "AUTOMATION"
    entry = None
    if kind == "CUE":
        item["playout_status"] = "CUED"
        store.bump(item)
        entry = cascades.append_asrun(playlist, item, "CUE", event_utc, measured=0,
                                      source=source, recorded_by=user)
    elif kind == "START":
        item["playout_status"] = "PLAYING"
        item["actual_start_utc"] = event_utc
        store.bump(item)
        entry = cascades.append_asrun(playlist, item, "START", event_utc, measured=0,
                                      source=source, recorded_by=user)
    elif kind == "END":
        measured = int(body["measured_duration_seconds"])
        item["playout_status"] = "PLAYED"
        item["measured_duration_seconds"] = measured
        store.bump(item)
        entry = cascades.append_asrun(playlist, item, "END", event_utc, measured=measured,
                                      source=source, recorded_by=user)
        cascades.credit_end_event(item)
    elif kind == "TRUNCATION":
        if not item.get("actual_start_utc"):
            fail("ERR_ITEM_INVALID_PLAYOUT_STATE",
                 "A truncation requires the element to have started.")
        measured = body.get("measured_duration_seconds")
        cascades.truncate_item(item, event_utc, source=source, recorded_by=user,
                               measured=None if measured is None else int(measured))
        entry = store.asrun_of_item(item["id"])[-1]
    elif kind == "SKIP":
        cascades.skip_item(item, event_utc, source=source, recorded_by=user)
        entry = store.asrun_of_item(item["id"])[-1]
    else:
        cascades.preempt_item(item, event_utc, source=body.get("source") or "SYSTEM",
                              recorded_by=user)
        entry = store.asrun_of_item(item["id"])[-1]

    plcalc.recompute_playlist(playlist, bump=True)
    if channel is not None:
        calc.recompute_posture(channel, bump=True)
    return created(views.plain(entry))


# --- substitution ----------------------------------------------------------

@bp.post("/playlist-items/<ident>/substitute")
def substitute(ident):
    auth.authorize(["MasterControlOperator", "ProgramDirector", "StationAdmin"], cert=True)
    body = validate(request.get_json(silent=True), [
        F("replacement_asset_id", "str", required=True),
        F("scheduled_duration_seconds", "int", minimum=1),
        F("reason", "str"),
    ])
    item = auth.playlist_item(ident)
    replacement = auth.asset(body["replacement_asset_id"])
    playlist = store.playlists.get(item["playlist_id"])
    channel = store.channels.get(playlist["channel_id"]) if playlist else None
    if item["playout_status"] not in ("SCHEDULED", "CUED"):
        fail("ERR_ITEM_INVALID_PLAYOUT_STATE",
             "Only a scheduled or cued element may be substituted.")
    if channel is not None and channel["air_status"] == "EAS_OVERRIDE":
        fail("ERR_EAS_OVERRIDE_ACTIVE", "An emergency override owns the channel output.")

    outgoing_asset = store.assets.get(item["asset_id"]) if item.get("asset_id") else None
    required = outgoing_asset["required_resolution_class"] if outgoing_asset \
        else replacement["required_resolution_class"]
    if replacement.get("delivered_resolution_class") != required:
        fail("ERR_SUBSTITUTE_RESOLUTION_MISMATCH",
             "The replacement was delivered in the wrong resolution class.")
    measured = replacement.get("measured_duration_seconds")
    scheduled = int(item["scheduled_duration_seconds"])
    allowance = int(item.get("max_trim_seconds") or 0)
    if measured is None or abs(int(measured) - scheduled) > allowance:
        fail("ERR_SUBSTITUTE_RESOLUTION_MISMATCH",
             "The replacement duration lies outside the element's trim allowance.")

    target_hour = hour_index(playlist, item["scheduled_start_utc"])
    for other in store.items_of(playlist["id"]):
        if other["id"] == item["id"] or other.get("asset_id") != replacement["id"]:
            continue
        if other["playout_status"] not in ("SCHEDULED", "CUED"):
            continue
        if hour_index(playlist, other["scheduled_start_utc"]) == target_hour:
            fail("ERR_ITEM_PLAYLIST_MISMATCH",
                 "The replacement is already placed in this hour of the playlist.")

    duration = int(body["scheduled_duration_seconds"]) \
        if body.get("scheduled_duration_seconds") is not None else scheduled
    trim = scheduled - duration
    if trim < 0:
        trim = 0
    if trim > allowance:
        fail("ERR_TRIM_EXCEEDS_MAX",
             "The substitution would trim more than max_trim_seconds allows.")

    now = store.clock()
    user = auth.actor_id()
    cascades.skip_item(item, now, source="OPERATOR", recorded_by=user)
    spec = {
        "sequence_number": int(item["sequence_number"]),
        "element_kind": item["element_kind"],
        "scheduled_start_utc": item["scheduled_start_utc"],
        "scheduled_duration_seconds": duration,
        "asset_id": replacement["id"],
        "spot_order_id": None,
        "feed_window_id": item.get("feed_window_id"),
        "max_trim_seconds": allowance,
    }
    new_item = build_item(playlist, spec, replaces_item_id=item["id"])
    new_item["trim_applied_seconds"] = trim
    new_item["clearance_status"] = derive_clearance(replacement)
    plcalc.check_timeline(playlist)
    plcalc.recompute_playlist(playlist, bump=True)
    return created(views.item_view(new_item))
