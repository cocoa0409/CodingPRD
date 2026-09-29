"""Technical faults: reporting, targeting coherence, escalation and mitigation (PRD 3.6)."""
from flask import Blueprint, request

import auth
import calc
import cascades
import plcalc
import store
import timeutil
import views
from constants import (FAULT_CODES, FAULT_ESCALATION_SECONDS, FAULT_SEVERITY, FAULT_STATES,
                       MITIGATION_CODES, SEVERITY_ORDER)
from errors import fail
from response import created, listing, ok
from validate import F, validate

bp = Blueprint("fault", __name__)

REPORTERS = ["MasterControlOperator", "BroadcastEngineer", "StationAdmin"]
FAULT_READERS = ["MasterControlOperator", "QCTechnician", "BroadcastEngineer",
                 "ComplianceOfficer", "StationAdmin"]
TRANSMITTER_ONLY_CODES = ("RF_POWER_FAULT", "LOSS_OF_SIGNAL")
CHANNEL_ONLY_CODES = ("AUDIO_LOSS", "BLACK_FRAME", "CAPTION_LOSS")
LEGAL_FAULT_MOVES = {
    "DETECTED": ("ACKNOWLEDGED", "AUTO_CLEARED"),
    "ACKNOWLEDGED": ("ESCALATED", "MITIGATED"),
    "ESCALATED": ("MITIGATED",),
    "MITIGATED": ("RESOLVED", "DETECTED"),
    "RESOLVED": (),
    "AUTO_CLEARED": (),
}


def raise_one(severity):
    index = SEVERITY_ORDER.index(severity)
    return SEVERITY_ORDER[min(index + 1, len(SEVERITY_ORDER) - 1)]


def elapsed_seconds(fault, now=None):
    end = fault.get("cleared_utc") or (now or store.clock())
    return max(0, timeutil.delta_seconds(fault["detected_utc"], end))


def derived_severity(fault, duration):
    base = FAULT_SEVERITY[fault["fault_code"]]
    if duration >= FAULT_ESCALATION_SECONDS or fault["state"] == "ESCALATED":
        return raise_one(base)
    return base


def refresh(fault, now=None):
    """Recompute the fault's own derived pair; only called on explicit transitions."""
    duration = elapsed_seconds(fault, now)
    fault["duration_seconds"] = duration
    fault["severity"] = derived_severity(fault, duration)
    return fault


def touch_channel(fault):
    channel = store.channels.get(fault["channel_id"]) if fault.get("channel_id") else None
    if channel is not None:
        calc.recompute_posture(channel, bump=True)
    return channel


# --- reporting -------------------------------------------------------------

@bp.post("/technical-faults")
def report_fault():
    auth.authorize(REPORTERS)
    body = validate(request.get_json(silent=True), [
        F("fault_code", "enum", required=True, values=FAULT_CODES),
        F("severity", "enum", values=SEVERITY_ORDER),
        F("detected_utc", "ts", required=True),
        F("channel_id", "str"),
        F("transmitter_id", "str"),
        F("playlist_item_id", "str"),
        F("notes", "str"),
    ])
    channel = auth.channel(body["channel_id"]) if body.get("channel_id") else None
    tx = auth.transmitter(body["transmitter_id"]) if body.get("transmitter_id") else None
    item = auth.playlist_item(body["playlist_item_id"]) if body.get("playlist_item_id") else None
    code = body["fault_code"]
    if timeutil.sec(body["detected_utc"]) > timeutil.sec(store.clock()):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "detected_utc may not lie in the future.")
    if channel is None and tx is None and item is None:
        fail("ERR_FAULT_TARGET_MISMATCH",
             "A fault must name at least one of channel_id, transmitter_id or playlist_item_id.")
    if channel is not None and item is not None:
        playlist = store.playlists.get(item["playlist_id"])
        if playlist is None or playlist["channel_id"] != channel["id"]:
            fail("ERR_FAULT_TARGET_MISMATCH",
                 "The named element does not belong to a playlist of the named channel.")
    if tx is not None and channel is not None:
        carrier = store.transmitter_of_channel(channel)
        if carrier is None or carrier["id"] != tx["id"]:
            fail("ERR_FAULT_TARGET_MISMATCH",
                 "The named transmitter does not carry the named channel's multiplex.")
    if code in TRANSMITTER_ONLY_CODES and tx is None:
        fail("ERR_FAULT_TARGET_MISMATCH",
             "A %s fault is a plant condition and requires a transmitter_id." % code)
    if code in CHANNEL_ONLY_CODES and channel is None:
        fail("ERR_FAULT_TARGET_MISMATCH",
             "A %s fault is observed on a service and requires a channel_id." % code)

    rec = store.base()
    rec.update({
        "channel_id": channel["id"] if channel else None,
        "transmitter_id": tx["id"] if tx else None,
        "playlist_item_id": item["id"] if item else None,
        "fault_code": code,
        "severity": FAULT_SEVERITY[code],
        "detected_utc": body["detected_utc"],
        "cleared_utc": None,
        "duration_seconds": 0,
        "state": "DETECTED",
        "mitigation_code": None,
        "acknowledged_by_user_id": None,
    })
    store.add(store.faults, rec)
    touch_channel(rec)
    return created(views.fault_view(rec))


@bp.get("/technical-faults/<ident>")
def read_fault(ident):
    auth.authorize(FAULT_READERS, mutating=False)
    return ok(views.fault_view(auth.fault(ident)))


@bp.get("/technical-faults")
def list_faults():
    auth.authorize(FAULT_READERS, mutating=False)
    rows = store.rows(store.faults)
    for name in ("channel_id", "transmitter_id", "playlist_item_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    state = request.args.get("state")
    if state:
        if state not in FAULT_STATES:
            fail("ERR_INVALID_ENUM_VALUE", "state '%s' is not recognised." % state)
        rows = [r for r in rows if r["state"] == state]
    severity = request.args.get("severity")
    if severity:
        if severity not in SEVERITY_ORDER:
            fail("ERR_INVALID_ENUM_VALUE", "severity '%s' is not recognised." % severity)
        rows = [r for r in rows if r["severity"] == severity]
    return listing(rows, views.fault_view)


# --- transitions -----------------------------------------------------------

@bp.post("/technical-faults/<ident>/state")
def drive_fault(ident):
    auth.authorize(REPORTERS)
    body = validate(request.get_json(silent=True), [
        F("target_state", "enum", required=True, values=FAULT_STATES),
        F("mitigation_code", "enum", values=MITIGATION_CODES),
        F("cleared_utc", "ts"),
        F("notes", "str"),
    ])
    fault = auth.fault(ident)
    target = body["target_state"]
    current = fault["state"]
    if target not in LEGAL_FAULT_MOVES[current]:
        fail("ERR_FAULT_INVALID_STATE",
             "%s to %s is not a reachable fault transition." % (current, target))
    now = store.clock()
    duration = elapsed_seconds(fault, now)
    if target == "ESCALATED" and duration < FAULT_ESCALATION_SECONDS:
        fail("ERR_FAULT_ESCALATION_TOO_EARLY",
             "A fault may only be escalated once it has run for %d seconds."
             % FAULT_ESCALATION_SECONDS)
    if target == "MITIGATED" and not body.get("mitigation_code"):
        fail("ERR_MITIGATION_CODE_REQUIRED", "A mitigation requires a mitigation_code.")
    if body.get("cleared_utc") and timeutil.sec(body["cleared_utc"]) > timeutil.sec(now):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "cleared_utc may not lie in the future.")

    user = auth.actor_id()
    channel = store.channels.get(fault["channel_id"]) if fault.get("channel_id") else None
    fault["state"] = target

    if target == "ACKNOWLEDGED":
        fault["acknowledged_by_user_id"] = user
        refresh(fault, now)
    elif target == "ESCALATED":
        fault["duration_seconds"] = duration
        fault["severity"] = raise_one(fault["severity"])
    elif target == "MITIGATED":
        fault["mitigation_code"] = body["mitigation_code"]
        fault["duration_seconds"] = duration
        if body["mitigation_code"] == "BARS_AND_TONE" and channel is not None \
                and channel["air_status"] == "ON_AIR":
            channel["air_status"] = "BARS_AND_TONE"
            store.bump(channel)
            playlist = store.on_air_playlist(channel["id"])
            if playlist is not None:
                for element in store.items_of(playlist["id"]):
                    if element["playout_status"] == "PLAYING":
                        cascades.truncate_item(element, now, source="OPERATOR", recorded_by=user)
                plcalc.recompute_playlist(playlist, bump=True)
    elif target in ("RESOLVED", "AUTO_CLEARED"):
        fault["cleared_utc"] = now
        fault["duration_seconds"] = elapsed_seconds(fault, now)
    elif target == "DETECTED":
        fault["cleared_utc"] = None
        fault["duration_seconds"] = duration
        fault["severity"] = derived_severity(fault, duration)

    store.bump(fault)
    if channel is not None:
        calc.recompute_posture(channel, bump=True)
    return ok(views.fault_view(fault))
