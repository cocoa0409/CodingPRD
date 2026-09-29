"""Clock, transmitters, regulatory notifications, multiplexes and operators."""
from flask import Blueprint, request

import auth
import calc
import cascades
import clockops
import plcalc
import store
import timeutil
import views
from constants import (NOTIFICATION_KINDS, NOTIFICATION_STATUSES, NOTIFY_WINDOW_SECONDS,
                       OPEN_FAULT_STATES, OPERATOR_STATUSES,
                       OUTAGE_NOTIFY_AFTER_SECONDS, OVERRIDE_AUTHORITIES,
                       POWER_REDUCTION_THRESHOLD_PCT, REDUCED_DERATE_THRESHOLD_PCT,
                       ROLE_CLASSES, ROLES, TRANSMITTER_STATES)
from errors import fail
from response import created, listing, ok
from validate import F, enum_filter, validate

bp = Blueprint("plant", __name__)

ENGINEER = ["BroadcastEngineer", "StationAdmin"]
COMPLIANCE = ["ComplianceOfficer", "StationAdmin"]


# --- logical clock ---------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authorize(ROLES)
    body = validate(request.get_json(silent=True), [F("current_utc", "ts", required=True)])
    value = body["current_utc"]
    if timeutil.sec(value) <= timeutil.sec(store.clock()):
        fail("ERR_CLOCK_NOT_MONOTONIC", "The logical clock must move strictly forward.")
    store.set_clock(value)
    clockops.run_checkpoint(value)
    return ok({"current_utc": store.clock()})


# --- transmitters ----------------------------------------------------------

@bp.post("/transmitters")
def create_transmitter():
    auth.authorize(ENGINEER)
    body = validate(request.get_json(silent=True), [
        F("facility_id", "str", required=True, min_len=1, max_len=32),
        F("call_sign", "str", required=True, min_len=1),
        F("authorized_erp_kw", "num", required=True, gt=0),
    ])
    for existing in store.rows(store.transmitters):
        if existing["facility_id"] == body["facility_id"]:
            fail("ERR_INVALID_FIELD_VALUE", "facility_id is already registered.")
    rec = store.base()
    rec.update({
        "facility_id": body["facility_id"],
        "call_sign": body["call_sign"],
        "authorized_erp_kw": body["authorized_erp_kw"],
        "current_power_pct": 100,
        "operational_state": "FULL_POWER",
        "derate_factor": 1.0,
        "outage_started_utc": None,
        "last_outage_seconds": 0,
        "cumulative_outage_seconds": 0,
        "notification_pending_count": 0,
    })
    store.add(store.transmitters, rec)
    return created(views.plain(rec))


@bp.get("/transmitters/<ident>")
def read_transmitter(ident):
    auth.authorize(["MasterControlOperator", "ProgramDirector", "BroadcastEngineer",
                    "ComplianceOfficer", "StationAdmin"], mutating=False)
    return ok(views.plain(auth.transmitter(ident)))


@bp.post("/transmitters/<ident>/power-state")
def power_state(ident):
    auth.authorize(ENGINEER, cert=True)
    body = validate(request.get_json(silent=True), [
        F("target_state", "enum", required=True, values=TRANSMITTER_STATES),
        F("power_pct", "int", minimum=0, maximum=100),
        F("reason", "str"),
    ])
    target = body["target_state"]
    if target == "REDUCED_POWER":
        if body.get("power_pct") is None:
            fail("ERR_MISSING_REQUIRED_FIELD", "power_pct is required for a reduced-power move.")
        pct = int(body["power_pct"])
        if pct < 1 or pct >= 100:
            fail("ERR_INVALID_FIELD_VALUE", "power_pct must be at least 1 and below 100.")
    if target == "OFF_AIR" and not body.get("reason"):
        fail("ERR_MISSING_REQUIRED_FIELD", "reason is required for an off-air move.")
    tx = auth.transmitter(ident)
    now = store.clock()
    legal = {
        "FULL_POWER": ("REDUCED_POWER", "OFF_AIR"),
        "REDUCED_POWER": ("FULL_POWER", "REDUCED_POWER", "OFF_AIR"),
        "OFF_AIR": ("FULL_POWER", "REDUCED_POWER"),
    }
    if target not in legal[tx["operational_state"]]:
        fail("ERR_TRANSMITTER_INVALID_STATE",
             "%s to %s is not a declared transition." % (tx["operational_state"], target))
    if target == "FULL_POWER":
        for fault in store.faults_of_transmitter(tx["id"]):
            if fault["fault_code"] == "RF_POWER_FAULT" and fault["state"] in OPEN_FAULT_STATES:
                fail("ERR_RF_FAULT_BLOCKS_RESTORE",
                     "An open RF power fault blocks restoration to full power.")

    leaving_off_air = tx["operational_state"] == "OFF_AIR" and target in ("FULL_POWER", "REDUCED_POWER")
    if target == "OFF_AIR":
        tx["current_power_pct"] = 0
        tx["derate_factor"] = 0.0
        tx["operational_state"] = "OFF_AIR"
        tx["outage_started_utc"] = now
    elif target == "FULL_POWER":
        tx["current_power_pct"] = 100
        tx["operational_state"] = "FULL_POWER"
        tx["derate_factor"] = 1.0
    else:
        pct = int(body["power_pct"])
        tx["current_power_pct"] = pct
        tx["operational_state"] = "REDUCED_POWER"
        tx["derate_factor"] = 0.75 if pct >= REDUCED_DERATE_THRESHOLD_PCT else 0.5

    if leaving_off_air:
        started = tx["outage_started_utc"]
        elapsed = timeutil.delta_seconds(started, now) if started else 0
        tx["last_outage_seconds"] = elapsed
        tx["cumulative_outage_seconds"] = int(tx["cumulative_outage_seconds"]) + elapsed
        tx["outage_started_utc"] = None
        if elapsed >= OUTAGE_NOTIFY_AFTER_SECONDS and started:
            already = [n for n in store.notifications_of(tx["id"])
                       if n["kind"] == "OUTAGE"
                       and timeutil.sec(n["triggering_utc"]) == timeutil.sec(started)]
            if not already:
                clockops.create_notification(
                    tx, "OUTAGE", started, timeutil.plus(now, NOTIFY_WINDOW_SECONDS),
                    outage_seconds=elapsed)
        clockops.create_notification(tx, "RESUMPTION", now,
                                     timeutil.plus(now, NOTIFY_WINDOW_SECONDS),
                                     outage_seconds=tx["last_outage_seconds"])
    if target == "REDUCED_POWER" and int(body["power_pct"]) < POWER_REDUCTION_THRESHOLD_PCT:
        clockops.create_notification(
            tx, "POWER_REDUCTION", now, timeutil.plus(now, NOTIFY_WINDOW_SECONDS),
            observed_power_pct=int(body["power_pct"]))
    clockops.refresh_pending_count(tx)
    store.bump(tx)
    cascades.transmitter_cascade(tx, now, off_air=(target == "OFF_AIR"))
    return ok(views.plain(tx))


@bp.get("/transmitters/<ident>/notifications")
def list_notifications(ident):
    auth.authorize(["BroadcastEngineer", "ComplianceOfficer", "StationAdmin"], mutating=False)
    tx = auth.transmitter(ident)
    rows = store.notifications_of(tx["id"])
    status = enum_filter("status", NOTIFICATION_STATUSES)
    kind = enum_filter("kind", NOTIFICATION_KINDS)
    if status:
        rows = [r for r in rows if r["status"] == status]
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    rows.sort(key=lambda r: (timeutil.sec(r["triggering_utc"]), r["_seq"]), reverse=True)
    return listing(rows, views.plain)


@bp.get("/regulatory-notifications/<ident>")
def read_notification(ident):
    auth.authorize(["BroadcastEngineer", "ComplianceOfficer", "StationAdmin"], mutating=False)
    return ok(views.plain(auth.notification(ident)))


@bp.post("/regulatory-notifications/<ident>/file")
def file_notification(ident):
    auth.authorize(COMPLIANCE)
    body = validate(request.get_json(silent=True), [
        F("filed_reference", "str"),
        F("narrative", "str"),
        F("filed_utc", "ts"),
    ])
    if not body.get("filed_reference") or not body.get("narrative"):
        fail("ERR_FILING_DETAILS_REQUIRED", "filed_reference and narrative are both required.")
    notification = auth.notification(ident)
    if notification["status"] not in ("PENDING", "OVERDUE"):
        fail("ERR_NOTIFICATION_INVALID_STATE", "The notification has already been filed.")
    now = store.clock()
    if body.get("filed_utc") and timeutil.sec(body["filed_utc"]) > timeutil.sec(now):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "filed_utc may not exceed the logical clock.")
    late = notification["status"] == "OVERDUE" or timeutil.sec(now) > timeutil.sec(notification["due_utc"])
    notification["status"] = "LATE_FILED" if late else "FILED"
    notification["filed_reference"] = body["filed_reference"]
    notification["narrative"] = body["narrative"]
    notification["filed_utc"] = now
    store.bump(notification)
    tx = store.transmitters.get(notification["transmitter_id"])
    if tx is not None:
        clockops.refresh_pending_count(tx)
        store.bump(tx)
    return ok(views.plain(notification))


# --- multiplexes -----------------------------------------------------------

@bp.post("/multiplexes")
def create_multiplex():
    auth.authorize(ENGINEER)
    body = validate(request.get_json(silent=True), [
        F("transmitter_id", "str", required=True),
        F("name", "str", required=True, min_len=1),
        F("total_capacity_kbps", "int", required=True, minimum=1000),
        F("pilot_reserved_kbps", "int", minimum=0),
        F("live_encoder_units_total", "int", minimum=1),
    ])
    tx = auth.transmitter(body["transmitter_id"])
    pilot = 500 if body.get("pilot_reserved_kbps") is None else int(body["pilot_reserved_kbps"])
    if pilot >= int(body["total_capacity_kbps"]):
        fail("ERR_INVALID_FIELD_VALUE", "pilot_reserved_kbps must be below total_capacity_kbps.")
    units = 2 if body.get("live_encoder_units_total") is None else int(body["live_encoder_units_total"])
    rec = store.base()
    rec.update({
        "transmitter_id": tx["id"],
        "name": body["name"],
        "total_capacity_kbps": int(body["total_capacity_kbps"]),
        "pilot_reserved_kbps": pilot,
        "live_encoder_units_total": units,
        "effective_capacity_kbps": 0,
        "assigned_kbps": 0,
        "available_kbps": 0,
        "starved_channel_count": 0,
        "live_encoder_units_peak": 0,
    })
    store.add(store.multiplexes, rec)
    calc.run_waterfall(rec)
    return created(views.plain(rec))


@bp.get("/multiplexes/<ident>")
def read_multiplex(ident):
    auth.authorize(["MasterControlOperator", "ProgramDirector", "BroadcastEngineer",
                    "StationAdmin"], mutating=False)
    return ok(views.plain(auth.multiplex(ident)))


@bp.get("/multiplexes")
def list_multiplexes():
    auth.authorize(["MasterControlOperator", "ProgramDirector", "BroadcastEngineer",
                    "ComplianceOfficer", "StationAdmin"], mutating=False)
    rows = store.rows(store.multiplexes)
    transmitter_id = request.args.get("transmitter_id")
    if transmitter_id:
        rows = [r for r in rows if r["transmitter_id"] == transmitter_id]
    return listing(rows, views.plain)


@bp.post("/multiplexes/<ident>/rebalance")
def rebalance(ident):
    auth.authorize(ENGINEER)
    body = validate(request.get_json(silent=True), [
        F("expected_multiplex_version", "int", required=True, minimum=0),
        F("clear_pins", "bool"),
    ])
    mux = auth.multiplex(ident)
    if int(body["expected_multiplex_version"]) != int(mux["version"]):
        fail("ERR_STALE_MULTIPLEX_VERSION", "The multiplex version has moved on.")
    calc.run_waterfall(mux, clear_pins=bool(body.get("clear_pins")))
    calc.refresh_encoder_peak(mux)
    store.bump(mux)
    return ok(views.plain(mux))


# --- operators -------------------------------------------------------------

@bp.post("/operators")
def create_operator():
    auth.authorize(["StationAdmin"])
    body = validate(request.get_json(silent=True), [
        F("full_name", "str", required=True, min_len=1),
        F("role_class", "enum", required=True, values=ROLE_CLASSES),
        F("override_authority", "enum", required=True, values=OVERRIDE_AUTHORITIES),
        F("certification_expires_utc", "ts", required=True),
    ])
    rec = store.base()
    rec.update({
        "full_name": body["full_name"],
        "role_class": body["role_class"],
        "override_authority": body["override_authority"],
        "certification_expires_utc": body["certification_expires_utc"],
        "certification_state": "VALID",
        "status": "ACTIVE",
    })
    auth.refresh_certification(rec)
    store.add(store.operators, rec)
    return created(views.plain(rec))


@bp.get("/operators/<ident>")
def read_operator(ident):
    auth.authorize(["MasterControlOperator", "QCTechnician", "ProgramDirector",
                    "BroadcastEngineer", "ComplianceOfficer", "StationAdmin"], mutating=False)
    operator = auth.operator_ref(ident)
    auth.refresh_certification(operator)
    return ok(views.plain(operator))


@bp.post("/operators/<ident>/status")
def operator_status(ident):
    auth.authorize(["StationAdmin"])
    body = validate(request.get_json(silent=True), [
        F("status", "enum", values=OPERATOR_STATUSES),
        F("certification_expires_utc", "ts"),
        F("override_authority", "enum", values=OVERRIDE_AUTHORITIES),
    ])
    operator = auth.operator_ref(ident)
    if body.get("status") is not None:
        operator["status"] = body["status"]
    if body.get("certification_expires_utc") is not None:
        operator["certification_expires_utc"] = body["certification_expires_utc"]
    if body.get("override_authority") is not None:
        operator["override_authority"] = body["override_authority"]
    auth.refresh_certification(operator)
    store.bump(operator)
    return ok(views.plain(operator))
