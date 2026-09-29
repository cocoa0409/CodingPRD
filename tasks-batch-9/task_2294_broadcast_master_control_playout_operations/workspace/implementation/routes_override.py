"""Emergency override authority: request, activate, escalate, release and reject (PRD 3.8)."""
from flask import Blueprint, request

import auth
import calc
import cascades
import store
import timeutil
import views
from constants import (ALERT_CLASSES, EAS_MIN_ON_AIR_SECONDS, OVERRIDE_MODES, OVERRIDE_STATES)
from errors import fail
from response import created, listing, ok
from validate import F, validate

bp = Blueprint("override", __name__)

DRIVERS = ["MasterControlOperator", "ProgramDirector", "StationAdmin"]
OVERRIDE_READERS = ["MasterControlOperator", "ProgramDirector", "TrafficCoordinator",
                    "ComplianceOfficer", "StationAdmin"]
AUTHORITY_FOR_MODE = {
    "CRAWL": ("CRAWL_ONLY", "CRAWL_AND_CUTIN", "FULL"),
    "CUT_IN": ("CRAWL_AND_CUTIN", "FULL"),
}


def _playing_item(channel):
    playlist = store.on_air_playlist(channel["id"])
    if playlist is None:
        return None, None
    for item in store.items_of(playlist["id"]):
        if item["playout_status"] == "PLAYING":
            return playlist, item
    return playlist, None


@bp.post("/emergency-overrides")
def create_override():
    auth.authorize(DRIVERS, cert=True)
    body = validate(request.get_json(silent=True), [
        F("channel_id", "str", required=True),
        F("requested_by_operator_id", "str", required=True),
        F("alert_class", "enum", required=True, values=ALERT_CLASSES),
        F("override_mode", "enum", required=True, values=OVERRIDE_MODES),
        F("requested_start_utc", "ts", required=True),
        F("expected_duration_seconds", "int", required=True, minimum=1),
        F("crawl_text", "str", min_len=1, max_len=512),
    ])
    channel = auth.channel(body["channel_id"])
    requester = auth.operator_ref(body["requested_by_operator_id"])
    if body["override_mode"] == "CRAWL" and not body.get("crawl_text"):
        fail("ERR_CRAWL_TEXT_REQUIRED", "A crawl override requires crawl_text.")
    for other in store.overrides_of(channel["id"]):
        if other["state"] in ("PENDING", "ACTIVE_CRAWL", "ACTIVE_CUTIN"):
            fail("ERR_OVERRIDE_WINDOW_OVERLAP",
                 "The channel already carries a non-terminal override.")
    rec = store.base()
    rec.update({
        "channel_id": channel["id"],
        "requested_by_operator_id": requester["id"],
        "authorized_by_operator_id": None,
        "alert_class": body["alert_class"],
        "override_mode": body["override_mode"],
        "active_mode": None,
        "crawl_text": body.get("crawl_text"),
        "requested_start_utc": body["requested_start_utc"],
        "expected_duration_seconds": int(body["expected_duration_seconds"]),
        "activated_utc": None,
        "released_utc": None,
        "truncated_item_count": 0,
        "preempted_item_count": 0,
        "state": "PENDING",
        "rejection_reason": None,
    })
    store.add(store.overrides, rec)
    return created(views.plain(rec))


@bp.get("/emergency-overrides/<ident>")
def read_override(ident):
    auth.authorize(OVERRIDE_READERS, mutating=False)
    return ok(views.plain(auth.override(ident)))


@bp.get("/emergency-overrides")
def list_overrides():
    auth.authorize(OVERRIDE_READERS, mutating=False)
    rows = store.rows(store.overrides)
    for name in ("channel_id", "requested_by_operator_id", "authorized_by_operator_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    state = request.args.get("state")
    if state:
        if state not in OVERRIDE_STATES:
            fail("ERR_INVALID_ENUM_VALUE", "state '%s' is not recognised." % state)
        rows = [r for r in rows if r["state"] == state]
    return listing(rows, views.plain)


@bp.post("/emergency-overrides/<ident>/activate")
def activate(ident):
    auth.authorize(DRIVERS, cert=True)
    body = validate(request.get_json(silent=True), [
        F("authorized_by_operator_id", "str", required=True),
        F("override_mode", "enum", required=True, values=OVERRIDE_MODES),
        F("activated_utc", "ts"),
        F("crawl_text", "str", min_len=1, max_len=512),
        F("force_preempt_guaranteed", "bool"),
    ])
    override = auth.override(ident)
    authorizer = auth.operator_ref(body["authorized_by_operator_id"])
    channel = store.channels.get(override["channel_id"])
    mode = body["override_mode"]
    if override["state"] not in ("PENDING", "ACTIVE_CRAWL", "ACTIVE_CUTIN"):
        fail("ERR_OVERRIDE_INVALID_STATE", "The override is terminal.")
    if override["state"] != "PENDING" and mode == override["active_mode"]:
        fail("ERR_OVERRIDE_INVALID_STATE",
             "The requested mode must differ from the mode already on air.")
    if channel is not None and channel["posture"] == "SUSPENDED":
        fail("ERR_CHANNEL_SUSPENDED_POSTURE", "A suspended channel cannot carry an alert.")
    requester = override["requested_by_operator_id"]
    if requester in (auth.actor_id(), authorizer["id"]):
        fail("ERR_SELF_AUTHORIZATION_FORBIDDEN",
             "An operator may not authorize their own override request.")
    authority = authorizer.get("override_authority")
    if authority not in AUTHORITY_FOR_MODE[mode] or \
            (override["alert_class"] == "EAS_MANDATORY" and authority != "FULL"):
        fail("ERR_OVERRIDE_AUTHORITY_INSUFFICIENT",
             "The authorizing operator does not hold sufficient override authority.")
    text = body.get("crawl_text") or override.get("crawl_text")
    if mode == "CRAWL" and not text:
        fail("ERR_CRAWL_TEXT_REQUIRED", "A crawl requires crawl_text.")
    if mode == "CRAWL" and override["state"] == "ACTIVE_CUTIN" \
            and override["alert_class"] == "EAS_MANDATORY":
        elapsed = timeutil.delta_seconds(override["activated_utc"], store.clock()) \
            if override.get("activated_utc") else 0
        if elapsed < EAS_MIN_ON_AIR_SECONDS:
            fail("ERR_EAS_MINIMUM_DURATION_NOT_MET",
                 "A mandatory alert must run at least %d seconds." % EAS_MIN_ON_AIR_SECONDS)
    if authorizer["role_class"] not in ("PROGRAM_DIRECTOR", "MASTER_CONTROL"):
        fail("ERR_OPERATOR_ROLE_CLASS_INVALID",
             "The authorizing operator holds the wrong role class.")
    if auth.certification_state(authorizer) == "EXPIRED":
        fail("ERR_OPERATOR_CERTIFICATION_EXPIRED",
             "The authorizing operator's certification has expired.")
    now = store.clock()
    if body.get("activated_utc") and timeutil.sec(body["activated_utc"]) > timeutil.sec(now):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "activated_utc may not lie in the future.")

    user = auth.actor_id()
    override["authorized_by_operator_id"] = authorizer["id"]
    if body.get("crawl_text"):
        override["crawl_text"] = body["crawl_text"]
    if override.get("activated_utc") is None:
        override["activated_utc"] = now
    playlist, playing = _playing_item(channel) if channel else (None, None)

    if mode == "CRAWL":
        override["active_mode"] = "CRAWL"
        override["state"] = "ACTIVE_CRAWL"
        if channel is not None and channel["air_status"] == "EAS_OVERRIDE":
            channel["air_status"] = "ON_AIR"
        store.bump(override)
        if channel is not None:
            calc.recompute_posture(channel, bump=True)
        if playlist is not None:
            cascades.append_asrun(playlist, playing, "OVERRIDE_IN", now, measured=0,
                                  source="OPERATOR", recorded_by=user)
    else:
        override["active_mode"] = "CUT_IN"
        override["state"] = "ACTIVE_CUTIN"
        store.bump(override)
        if channel is not None:
            channel["air_status"] = "EAS_OVERRIDE"
            calc.recompute_posture(channel, bump=False)
            store.bump(channel)
            cascades.cutin_cascade(override, channel, now,
                                   bool(body.get("force_preempt_guaranteed")), user)
            store.bump(override)
        if playlist is not None:
            cascades.append_asrun(playlist, playing, "OVERRIDE_IN", now, measured=0,
                                  source="OPERATOR", recorded_by=user)
    return ok(views.plain(override))


@bp.post("/emergency-overrides/<ident>/release")
def release(ident):
    auth.authorize(DRIVERS, cert=True)
    body = validate(request.get_json(silent=True), [
        F("released_utc", "ts"),
        F("rejection_reason", "str"),
    ])
    override = auth.override(ident)
    channel = store.channels.get(override["channel_id"])
    role = request.headers.get("X-User-Role")
    if override["state"] not in ("PENDING", "ACTIVE_CRAWL", "ACTIVE_CUTIN"):
        fail("ERR_OVERRIDE_INVALID_STATE", "The override is already terminal.")

    now = store.clock()
    if override["state"] == "PENDING":
        if role not in ("ProgramDirector", "StationAdmin"):
            fail("ERR_OVERRIDE_INVALID_STATE",
                 "A pending request may only be rejected by a program director.")
        if not body.get("rejection_reason"):
            fail("ERR_REJECTION_REASON_REQUIRED", "A rejection requires a rejection_reason.")
        override["rejection_reason"] = body["rejection_reason"]
        override["state"] = "REJECTED"
        store.bump(override)
        return ok(views.plain(override))

    if override["alert_class"] == "EAS_MANDATORY":
        elapsed = timeutil.delta_seconds(override["activated_utc"], now) \
            if override.get("activated_utc") else 0
        if elapsed < EAS_MIN_ON_AIR_SECONDS:
            fail("ERR_EAS_MINIMUM_DURATION_NOT_MET",
                 "A mandatory alert must run at least %d seconds." % EAS_MIN_ON_AIR_SECONDS)
    if body.get("released_utc") and timeutil.sec(body["released_utc"]) > timeutil.sec(now):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "released_utc may not lie in the future.")

    was_cutin = override["state"] == "ACTIVE_CUTIN"
    override["released_utc"] = now
    override["active_mode"] = None
    override["state"] = "RELEASED"
    store.bump(override)
    playlist, playing = _playing_item(channel) if channel else (None, None)
    if channel is not None:
        if was_cutin and channel["air_status"] == "EAS_OVERRIDE":
            remaining = [o for o in store.overrides_of(channel["id"])
                         if o["state"] == "ACTIVE_CUTIN"]
            if not remaining:
                channel["air_status"] = "ON_AIR"
        calc.recompute_posture(channel, bump=False)
        store.bump(channel)
    if playlist is not None:
        cascades.append_asrun(playlist, playing, "OVERRIDE_OUT", now, measured=0,
                              source="OPERATOR", recorded_by=auth.actor_id())
    return ok(views.plain(override))
