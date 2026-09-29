"""Playlists: ingest, traffic revisions, lifecycle, items, as-run and reconciliation."""
from flask import Blueprint, request

import auth
import calc
import cascades
import plcalc
import store
import timeutil
import views
from constants import (ARM_VARIANCE_TOLERANCE_SECONDS, CLEARANCE_STATUSES, ELEMENT_KINDS,
                       EVENT_KINDS, OPEN_FAULT_STATES, PLAYLIST_STATUSES, PLAYOUT_STATUSES,
                       PREROLL_TOLERANCE_SECONDS)
from errors import fail
from response import created, listing, ok
from validate import F, validate

bp = Blueprint("playlist", __name__)

TRAFFIC = ["TrafficCoordinator", "StationAdmin"]
PLAYLIST_READERS = ["MasterControlOperator", "ProgramDirector", "TrafficCoordinator",
                    "ComplianceOfficer", "StationAdmin"]
ITEM_READERS = ["MasterControlOperator", "QCTechnician", "ProgramDirector",
                "TrafficCoordinator", "ComplianceOfficer", "StationAdmin"]
DRIVERS = ["MasterControlOperator", "ProgramDirector", "StationAdmin"]

ITEM_FIELDS = [
    F("sequence_number", "int", required=True, minimum=1),
    F("element_kind", "enum", required=True, values=ELEMENT_KINDS),
    F("scheduled_start_utc", "ts", required=True),
    F("scheduled_duration_seconds", "int", required=True, minimum=1),
    F("house_number", "str"),
    F("asset_id", "str"),
    F("spot_order_id", "str"),
    F("feed_window_id", "str"),
    F("max_trim_seconds", "int", minimum=0),
]


def validate_item_specs(raw_items):
    """Field-shape pass over every submitted element, in submission order."""
    specs = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_FIELD_VALUE", "Every element of items must be an object.")
        spec = validate(entry, ITEM_FIELDS)
        trim = spec.get("max_trim_seconds")
        trim = 0 if trim is None else int(trim)
        if trim > int(spec["scheduled_duration_seconds"]):
            fail("ERR_INVALID_FIELD_VALUE",
                 "max_trim_seconds may not exceed the element's scheduled duration.")
        spec["max_trim_seconds"] = trim
        specs.append(spec)
    return specs


def resolve_item_refs(specs, channel_id):
    """Body reference resolution for every element, then the order/channel agreement rule."""
    for spec in specs:
        if spec.get("asset_id"):
            auth.asset(spec["asset_id"])
        if spec.get("spot_order_id"):
            auth.spot_order(spec["spot_order_id"])
        if spec.get("feed_window_id"):
            auth.feed_window(spec["feed_window_id"])
    for spec in specs:
        if spec.get("spot_order_id"):
            order = store.spot_orders[spec["spot_order_id"]]
            if order["channel_id"] != channel_id:
                fail("ERR_SPOT_ORDER_CHANNEL_MISMATCH",
                     "The spot order was sold on another channel.")


def check_dense_run(specs, retained=()):
    numbers = [int(s["sequence_number"]) for s in specs]
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        fail("ERR_SEQUENCE_NUMBER_CONFLICT",
             "Element sequence numbers must form a dense run from 1 with no duplicates.")
    taken = set(int(i["sequence_number"]) for i in retained)
    for number in numbers:
        if number in taken:
            fail("ERR_SEQUENCE_NUMBER_CONFLICT",
                 "sequence_number %d is held by an element automation already owns." % number)


def derive_clearance(asset):
    if asset is None:
        return "UNCLEARED"
    if asset["status"] in ("QC_PASSED", "QC_WAIVED"):
        return "CLEARED"
    if asset["status"] in ("RETRACTED", "EXPIRED", "QC_FAILED"):
        return "BLOCKED"
    return "UNCLEARED"


def build_item(playlist, spec, is_makegood=False, replaces_item_id=None):
    asset = store.assets.get(spec["asset_id"]) if spec.get("asset_id") else None
    rec = store.base()
    rec.update({
        "playlist_id": playlist["id"],
        "asset_id": asset["id"] if asset else None,
        "spot_order_id": spec.get("spot_order_id"),
        "feed_window_id": spec.get("feed_window_id"),
        "replaces_item_id": replaces_item_id,
        "sequence_number": int(spec["sequence_number"]),
        "element_kind": spec["element_kind"],
        "house_number": asset["house_number"] if asset else spec.get("house_number"),
        "scheduled_start_utc": spec["scheduled_start_utc"],
        "scheduled_duration_seconds": int(spec["scheduled_duration_seconds"]),
        "max_trim_seconds": int(spec.get("max_trim_seconds") or 0),
        "playout_status": "SCHEDULED",
        "clearance_status": derive_clearance(asset),
        "actual_start_utc": None,
        "measured_duration_seconds": None,
        "is_makegood": bool(is_makegood),
        "trim_applied_seconds": 0,
    })
    store.add(store.items, rec)
    if rec["spot_order_id"]:
        order = store.spot_orders.get(rec["spot_order_id"])
        if order is not None:
            order["scheduled_spots"] = int(order["scheduled_spots"]) + 1
            plcalc.recompute_unplaced(order)
            plcalc.refresh_order_status(order)
            store.bump(order)
    return rec


def drop_item(item):
    order = store.spot_orders.get(item["spot_order_id"]) if item.get("spot_order_id") else None
    store.items.pop(item["id"], None)
    if order is not None:
        order["scheduled_spots"] = max(0, int(order["scheduled_spots"]) - 1)
        plcalc.recompute_unplaced(order)
        plcalc.refresh_order_status(order)
        store.bump(order)


# --- ingest ----------------------------------------------------------------

@bp.post("/playlists")
def ingest():
    auth.authorize(TRAFFIC)
    body = validate(request.get_json(silent=True), [
        F("channel_id", "str", required=True),
        F("broadcast_day", "str", required=True, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        F("schedule_start_utc", "ts", required=True),
        F("items", "array", required=True),
        F("window_duration_seconds", "int", minimum=60),
    ])
    specs = validate_item_specs(body["items"])
    channel = auth.channel(body["channel_id"])
    resolve_item_refs(specs, channel["id"])
    for existing in store.playlists_of(channel["id"]):
        if existing["broadcast_day"] == body["broadcast_day"]:
            fail("ERR_INVALID_FIELD_VALUE",
                 "A playlist already exists for this channel and broadcast day.")
    if not specs:
        fail("ERR_PLAYLIST_EMPTY_INGEST", "At least one element must be supplied.")
    check_dense_run(specs)

    playlist = store.base()
    playlist.update({
        "channel_id": channel["id"],
        "broadcast_day": body["broadcast_day"],
        "schedule_start_utc": body["schedule_start_utc"],
        "window_duration_seconds": int(body["window_duration_seconds"])
        if body.get("window_duration_seconds") is not None else 86400,
        "traffic_revision": 1,
        "status": "IMPORTING",
        "item_count": 0,
        "blocked_item_count": 0,
        "scheduled_total_seconds": 0,
        "projected_end_variance_seconds": 0,
        "asrun_end_variance_seconds": 0,
        "commercial_seconds_by_hour": {},
        "reconciliation_credit_cents": 0,
        "armed_at_utc": None,
        "closed_at_utc": None,
    })
    store.add(store.playlists, playlist)
    for spec in sorted(specs, key=lambda s: int(s["sequence_number"])):
        build_item(playlist, spec)
    plcalc.check_timeline(playlist)
    plcalc.check_inventory(playlist)
    playlist["status"] = "IMPORTED"
    plcalc.recompute_playlist(playlist, bump=False)
    return created(views.plain(playlist))


@bp.post("/playlists/<ident>/traffic-revisions")
def revise(ident):
    auth.authorize(TRAFFIC)
    body = validate(request.get_json(silent=True), [
        F("expected_playlist_version", "int", required=True, minimum=0),
        F("items", "array", required=True),
        F("removed_sequence_numbers", "array"),
    ])
    specs = validate_item_specs(body["items"])
    playlist = auth.playlist(ident)
    resolve_item_refs(specs, playlist["channel_id"])
    if int(body["expected_playlist_version"]) != int(playlist["version"]):
        fail("ERR_STALE_PLAYLIST_VERSION", "The playlist version has moved on.")
    if playlist["status"] not in ("IMPORTING", "IMPORTED", "VALIDATED", "ARMED"):
        fail("ERR_PLAYLIST_INVALID_STATE",
             "A revision is only accepted before the playlist reaches air.")
    retained = [i for i in store.items_of(playlist["id"])
                if i["playout_status"] != "SCHEDULED"]
    check_dense_run(specs, retained=retained)

    removed = set(int(n) for n in (body.get("removed_sequence_numbers") or []))
    for item in list(store.items_of(playlist["id"])):
        if item["playout_status"] == "SCHEDULED":
            drop_item(item)
        elif int(item["sequence_number"]) in removed:
            fail("ERR_ITEM_INVALID_PLAYOUT_STATE",
                 "An element automation already owns cannot be removed by a revision.")
    for spec in sorted(specs, key=lambda s: int(s["sequence_number"])):
        build_item(playlist, spec)
    plcalc.check_timeline(playlist)
    plcalc.check_inventory(playlist)
    playlist["traffic_revision"] = int(playlist["traffic_revision"]) + 1
    if playlist["status"] in ("VALIDATED", "ARMED"):
        playlist["status"] = "IMPORTED"
        playlist["armed_at_utc"] = None
    plcalc.recompute_playlist(playlist, bump=False)
    store.bump(playlist)
    return ok(views.plain(playlist))


# --- reads -----------------------------------------------------------------

@bp.get("/playlists/<ident>")
def read_playlist(ident):
    auth.authorize(PLAYLIST_READERS, mutating=False)
    playlist = auth.playlist(ident)
    plcalc.recompute_playlist(playlist, bump=False)
    return ok(views.plain(playlist))


@bp.get("/playlists/<ident>/items")
def list_items(ident):
    auth.authorize(ITEM_READERS, mutating=False)
    playlist = auth.playlist(ident)
    rows = store.items_of(playlist["id"])
    for name, vocabulary in (("playout_status", PLAYOUT_STATUSES),
                             ("clearance_status", CLEARANCE_STATUSES),
                             ("element_kind", ELEMENT_KINDS)):
        value = request.args.get(name)
        if value:
            if value not in vocabulary:
                fail("ERR_INVALID_ENUM_VALUE", "%s '%s' is not a recognised value." % (name, value))
            rows = [r for r in rows if r[name] == value]
    return listing(rows, views.item_view)


@bp.get("/playlists/<ident>/as-run")
def playlist_asrun(ident):
    auth.authorize(PLAYLIST_READERS, mutating=False)
    playlist = auth.playlist(ident)
    rows = store.asrun_of(playlist["id"])
    kind = request.args.get("event_kind")
    if kind:
        if kind not in EVENT_KINDS:
            fail("ERR_INVALID_ENUM_VALUE", "event_kind '%s' is not a recognised value." % kind)
        rows = [r for r in rows if r["event_kind"] == kind]
    for name, keep in (("from_utc", True), ("to_utc", False)):
        value = request.args.get(name)
        if not value:
            continue
        if not timeutil.is_timestamp(value):
            fail("ERR_INVALID_FIELD_VALUE", "%s must be an RFC3339 UTC instant." % name)
        if keep:
            rows = [r for r in rows if timeutil.sec(r["event_utc"]) >= timeutil.sec(value)]
        else:
            rows = [r for r in rows if timeutil.sec(r["event_utc"]) <= timeutil.sec(value)]
    return listing(rows, views.plain)


@bp.get("/playlists/<ident>/reconciliation")
def reconciliation(ident):
    auth.authorize(["ProgramDirector", "TrafficCoordinator", "ComplianceOfficer", "StationAdmin"],
                   mutating=False)
    playlist = auth.playlist(ident)
    basis = request.args.get("basis") or "PRELIMINARY"
    if basis not in ("PRELIMINARY", "FINAL"):
        fail("ERR_INVALID_ENUM_VALUE", "basis must be PRELIMINARY or FINAL.")
    orders = {}
    for item in store.items_of(playlist["id"]):
        if item.get("spot_order_id"):
            order = store.spot_orders.get(item["spot_order_id"])
            if order is not None:
                orders[order["id"]] = order
    figures = []
    total = 0
    for order in sorted(orders.values(), key=lambda o: (o["created_at"], o["_seq"])):
        result = plcalc.settle(order, basis=basis, playlist_id=playlist["id"])
        total += result["playlist_credit_cents"]
        figures.append(result)
    return ok({
        "playlist_id": playlist["id"],
        "basis": basis,
        "orders": figures,
        "playlist_credit_cents": total,
        "projected_end_variance_seconds": plcalc.projected_variance(playlist),
        "asrun_end_variance_seconds": plcalc.asrun_variance(playlist),
    })


# --- lifecycle -------------------------------------------------------------

LEGAL_MOVES = {
    "IMPORTING": ("IMPORTED", "ABANDONED"),
    "IMPORTED": ("VALIDATED", "IMPORTING", "ABANDONED"),
    "VALIDATED": ("ARMED", "IMPORTED", "ABANDONED"),
    "ARMED": ("ON_AIR", "IMPORTED", "ABANDONED"),
    "ON_AIR": ("CLOSED",),
    "CLOSED": (),
    "ABANDONED": (),
}


def _validate_gates(playlist):
    rows = store.items_of(playlist["id"])
    if not rows or not any(i["element_kind"] == "PROGRAM" for i in rows):
        fail("ERR_PLAYLIST_NO_PROGRAM_CONTENT",
             "A broadcast day requires at least one PROGRAM element.")
    plcalc.check_timeline(playlist)
    plcalc.check_inventory(playlist)
    if len([i for i in rows if i["clearance_status"] == "BLOCKED"]) != 0:
        fail("ERR_UNCLEARED_CONTENT_ON_AIR", "The playlist still carries blocked elements.")


def _arm_gates(playlist, channel):
    if channel["posture"] != "NORMAL" and channel["posture"] != "DEGRADED":
        fail("ERR_CHANNEL_SUSPENDED_POSTURE",
             "The channel posture does not permit arming.")
    tx = store.transmitter_of_channel(channel)
    if tx is not None and tx["operational_state"] == "OFF_AIR":
        fail("ERR_TRANSMITTER_OFF_AIR", "The parent transmitter is off air.")
    for fault in calc.open_faults(channel["id"]):
        if fault["severity"] == "CRITICAL":
            fail("ERR_CRITICAL_FAULT_OPEN", "An open critical fault blocks arming.")
    for item in store.items_of(playlist["id"]):
        if item["element_kind"] in ("PROGRAM", "COMMERCIAL", "INTERSTITIAL", "PROMO") \
                and item["clearance_status"] != "CLEARED":
            fail("ERR_UNCLEARED_CONTENT_ON_AIR",
                 "Element %d is not cleared for air." % int(item["sequence_number"]))
    variance = plcalc.projected_variance(playlist)
    if abs(variance) > ARM_VARIANCE_TOLERANCE_SECONDS:
        fail("ERR_ARM_VARIANCE_EXCEEDED",
             "The projected end variance of %d seconds exceeds the arming tolerance." % variance)


@bp.post("/playlists/<ident>/state")
def drive_state(ident):
    auth.authorize(DRIVERS, cert=True)
    body = validate(request.get_json(silent=True), [
        F("target_status", "enum", required=True, values=PLAYLIST_STATUSES),
        F("reason", "str"),
    ])
    playlist = auth.playlist(ident)
    target = body["target_status"]
    current = playlist["status"]
    if target not in LEGAL_MOVES[current]:
        fail("ERR_PLAYLIST_INVALID_STATE",
             "%s to %s is not a declared playlist transition." % (current, target))
    channel = store.channels.get(playlist["channel_id"])
    if channel is not None and channel["air_status"] == "EAS_OVERRIDE":
        fail("ERR_EAS_OVERRIDE_ACTIVE",
             "An emergency override owns the channel; release it first.")
    now = store.clock()
    user = auth.actor_id()

    if target == "VALIDATED":
        _validate_gates(playlist)
        plcalc.recompute_playlist(playlist, bump=False)
    elif target == "ARMED":
        _arm_gates(playlist, channel)
        playlist["armed_at_utc"] = now
    elif target == "ON_AIR":
        if timeutil.sec(now) < timeutil.sec(
                timeutil.plus(playlist["schedule_start_utc"], -PREROLL_TOLERANCE_SECONDS)):
            fail("ERR_PLAYLIST_AIR_TOO_EARLY",
                 "The playlist may not go to air more than five minutes before its booked start.")
        if channel is None or channel["air_status"] != "ON_AIR":
            fail("ERR_CHANNEL_NOT_ON_AIR", "The channel itself is not on air.")
        for other in store.playlists_of(channel["id"]):
            if other["id"] != playlist["id"] and other["status"] == "ON_AIR":
                fail("ERR_CHANNEL_PLAYLIST_ALREADY_ON_AIR",
                     "Another playlist is already on air for this channel.")
    elif target == "CLOSED":
        if channel is not None and calc.active_overrides(channel["id"]):
            fail("ERR_EAS_OVERRIDE_ACTIVE",
                 "An active emergency override must be released before closing.")
        for item in store.items_of(playlist["id"]):
            if item["playout_status"] == "PLAYING":
                fail("ERR_PLAYLIST_ITEM_STILL_PLAYING",
                     "Element %d is still playing." % int(item["sequence_number"]))
    elif target == "ABANDONED":
        for item in store.items_of(playlist["id"]):
            if item["playout_status"] in ("CUED", "PLAYING", "PLAYED", "TRUNCATED"):
                fail("ERR_PLAYLIST_INVALID_STATE",
                     "The playlist may not be abandoned once automation has taken an element.")
    elif target == "IMPORTED":
        playlist["armed_at_utc"] = None

    playlist["status"] = target

    if target == "CLOSED":
        for item in store.items_of(playlist["id"]):
            if item["playout_status"] in ("SCHEDULED", "CUED"):
                item["playout_status"] = "SKIPPED"
                store.bump(item)
                cascades.append_asrun(playlist, item, "SKIP", now, measured=0, source="SYSTEM")
        cascades.close_settlement(playlist)
        playlist["closed_at_utc"] = now
    elif target == "ABANDONED":
        for item in store.items_of(playlist["id"]):
            if item["playout_status"] != "SKIPPED":
                item["playout_status"] = "SKIPPED"
                store.bump(item)
            order = store.spot_orders.get(item["spot_order_id"]) if item.get("spot_order_id") else None
            if order is not None:
                order["scheduled_spots"] = max(0, int(order["scheduled_spots"]) - 1)
                plcalc.recompute_unplaced(order)
                plcalc.refresh_order_status(order)
                store.bump(order)

    plcalc.recompute_playlist(playlist, bump=False)
    store.bump(playlist)
    return ok(views.plain(playlist))
