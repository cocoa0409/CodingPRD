"""Device provisioning, install verification, telemetry, valve, mode, firmware."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import db
import serializers as ser
import services
from config import (
    CLASSIFICATIONS,
    INSTALL_MAX_DROP_PSI,
    INSTALL_MAX_STATIC_PSI,
    INSTALL_MIN_STATIC_PSI,
    LEARNING_STATES,
    MAX_READING_BACKDATE_HOURS,
    MAX_SNOOZE_MINUTES,
    MAX_VACATION_DAYS,
    MIN_SNOOZE_MINUTES,
    MODEL_CODES,
    MONITOR_MODES,
    READING_SOURCES,
    ROLE_ADJUSTER,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_GATEWAY,
    ROLE_HOMEOWNER,
    ROLE_INSTALLER,
    SNOOZE_COOLDOWN_MINUTES,
    VALVE_COMMANDS,
)
from errors import ApiError, bad_request
from response import (
    bool_filter,
    created,
    enum_filter,
    listing,
    ok,
    page_params,
)
from util import (
    fmt_dt,
    get_body,
    num,
    opt_bool_default,
    opt_enum,
    opt_int,
    opt_string,
    parse_dt,
    req_datetime,
    req_enum,
    req_int,
    req_number,
    req_string,
    to_dec,
)

bp = Blueprint("devices", __name__)


def _device(did):
    row = db.devices.get(did)
    if row is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND", "No device exists with id %s." % did)
    return row


# ---------------------------------------------------------------- reads
@bp.get("/devices/<did>")
def get_device(did):
    actor = auth.guard(
        ROLE_HOMEOWNER,
        ROLE_INSTALLER,
        ROLE_GATEWAY,
        ROLE_ANALYST,
        ROLE_ADJUSTER,
        ROLE_ADMIN,
    )
    row = _device(did)
    auth.own_device(actor, row)
    return ok(ser.device(row))


@bp.get("/devices/<did>/baseline-profiles")
def list_profiles(did):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_INSTALLER, ROLE_ANALYST, ROLE_ADMIN)
    row = _device(did)
    limit, offset = page_params()
    auth.own_device(actor, row)
    state = enum_filter("learning_state", LEARNING_STATES)
    rows = [p for p in db.baseline_profiles.values() if p["device_id"] == did]
    if state is not None:
        rows = [p for p in rows if p["learning_state"] == state]
    rows = db.sort_rows(rows, lambda p: p["learning_cycle_no"])
    return listing(rows, ser.baseline_profile, limit, offset)


@bp.get("/devices/<did>/telemetry")
def list_telemetry(did):
    actor = auth.guard(
        ROLE_HOMEOWNER, ROLE_GATEWAY, ROLE_ANALYST, ROLE_ADJUSTER, ROLE_ADMIN
    )
    row = _device(did)
    limit, offset = page_params()
    auth.own_device(actor, row)
    classification = enum_filter("classification_at_ingest", CLASSIFICATIONS)
    eligible = bool_filter("baseline_eligible")
    rows = db.readings_for_device(did)
    if classification is not None:
        rows = [r for r in rows if r["classification_at_ingest"] == classification]
    if eligible is not None:
        rows = [r for r in rows if bool(r["baseline_eligible"]) is eligible]
    rows = db.sort_rows(rows, lambda r: r["reading_at"])
    return listing(rows, ser.telemetry_reading, limit, offset)


@bp.get("/devices/<did>/health-summary")
def health_summary(did):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ANALYST, ROLE_ADMIN)
    row = _device(did)
    auth.own_device(actor, row)
    raw_start = request.args.get("window_start_at")
    raw_end = request.args.get("window_end_at")
    if (raw_start is None) != (raw_end is None):
        raise bad_request(
            "window_start_at and window_end_at must both be supplied or both omitted."
        )
    if raw_start is not None:
        try:
            start_at = parse_dt(raw_start)
            end_at = parse_dt(raw_end)
        except ValueError:
            raise bad_request("The supplied window bounds must be ISO-8601 UTC instants.")
        if end_at <= start_at:
            raise bad_request("window_end_at must be strictly after window_start_at.")
    else:
        start_at = end_at = None
        candidates = []
        for policy_row in db.policies_for_property(row["property_id"]):
            for att in db.attestations_for_policy(policy_row["id"]):
                if att["status"] == "OPEN":
                    candidates.append(att)
        if candidates:
            candidates.sort(key=lambda a: (a["created_at"], a["_seq"]))
            newest = candidates[-1]
            start_at = newest["period_start_at"]
            end_at = newest["period_end_at"]

    profile = db.profile_for_device(did)
    if start_at is None:
        stats = {
            "covered_minutes": 0,
            "period_minutes": 0,
            "uptime_pct": to_dec("0.00"),
            "offline_gap_count": 0,
        }
    else:
        stats = services.uptime_for_window(row, start_at, end_at)
    data = {
        "device_id": did,
        "lifecycle_state": row["lifecycle_state"],
        "uptime_pct": num(stats["uptime_pct"], 2),
        "covered_minutes": stats["covered_minutes"],
        "period_minutes": stats["period_minutes"],
        "offline_gap_count": stats["offline_gap_count"],
        "false_positive_count": profile["false_positive_count"] if profile else 0,
        "drip_threshold_gpm": num(profile.get("drip_threshold_gpm"), 2) if profile else None,
    }
    return ok(data)


# ---------------------------------------------------------------- writes
@bp.post("/devices")
def create_device():
    auth.guard(ROLE_INSTALLER, ROLE_ADMIN)
    body = get_body(request)
    property_id = req_string(body, "property_id")
    serial = req_string(body, "serial_number", 6, 32)
    model = req_enum(body, "model_code", MODEL_CODES)
    firmware = opt_string(body, "firmware_version", 1, 40, default="1.0.0")
    prop = db.properties.get(property_id)
    if prop is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "No property exists with id %s." % property_id)
    auth.alive_property(prop)
    for existing in db.devices.values():
        if existing["serial_number"] == serial:
            raise ApiError(
                "ERR_DEVICE_SERIAL_TAKEN", "Serial number %s is already registered." % serial
            )
    row = {
        "property_id": property_id,
        "serial_number": serial,
        "model_code": model,
        "firmware_version": firmware,
        "lifecycle_state": "REGISTERED",
        "valve_state": "OPEN",
        "monitor_mode": "NORMAL",
        "install_verified_by_user_id": None,
        "install_verified_at": None,
        "installed_static_pressure_psi": None,
        "close_count": 0,
        "reopen_count": 0,
        "last_shutoff_at": None,
        "last_reading_at": None,
        "vacation_started_at": None,
        "vacation_ends_at": None,
        "snooze_window_start_at": None,
        "snooze_window_end_at": None,
        "baseline_ready": False,
        "decommissioned_at": None,
    }
    db.insert(db.devices, row)
    row["monitor_mode_updated_at"] = row["created_at"]
    return created(ser.device(row))


@bp.post("/devices/<did>/verify-install")
def verify_install(did):
    actor = auth.guard(ROLE_INSTALLER)
    device_row = _device(did)
    body = get_body(request)
    pressure = req_number(body, "installed_static_pressure_psi", minimum=0)
    drop = req_number(body, "pressure_drop_psi", minimum=0)
    auth.alive_device(device_row)
    if device_row["lifecycle_state"] != "REGISTERED":
        raise ApiError(
            "ERR_INSTALL_ALREADY_VERIFIED",
            "This device has already passed install verification.",
        )
    if (
        pressure < INSTALL_MIN_STATIC_PSI
        or pressure > INSTALL_MAX_STATIC_PSI
        or drop > INSTALL_MAX_DROP_PSI
    ):
        raise ApiError(
            "ERR_INSTALL_PRESSURE_TEST_FAILED",
            "The static-pressure hold test did not pass its bounds.",
        )
    now = clock.now()
    device_row["install_verified_by_user_id"] = actor.user_id
    device_row["install_verified_at"] = now
    device_row["installed_static_pressure_psi"] = pressure
    device_row["lifecycle_state"] = "LEARNING"
    db.touch(device_row)
    profile = {
        "device_id": did,
        "learning_state": "COLLECTING",
        "learning_started_at": now,
        "learning_cycle_no": 1,
        "baseline_static_pressure_psi": None,
        "baseline_peak_flow_gpm": None,
        "drip_threshold_gpm": None,
        "baseline_version": 0,
        "false_positive_count": 0,
        "last_false_positive_at": None,
        "invalidated_reason": None,
        "completed_at": None,
    }
    db.insert(db.baseline_profiles, profile)
    return ok(ser.device(device_row))


@bp.post("/devices/<did>/telemetry")
def ingest(did):
    auth.guard(ROLE_GATEWAY)
    device_row = _device(did)
    body = get_body(request)
    reading_at = req_datetime(body, "reading_at")
    pressure = req_number(body, "static_pressure_psi", minimum=0, maximum=200)
    flow = req_number(body, "flow_gpm", minimum=0)
    duration = req_number(body, "duration_minutes", minimum=0)
    gallons = req_number(body, "total_gallons", minimum=0)
    source = opt_enum(body, "reading_source", READING_SOURCES, "DEVICE")
    # Step 7 applies to "every write endpoint that resolves a homeowner"; the
    # device-side ingest identity resolves a device and no account behind it.
    if device_row["lifecycle_state"] not in ("LEARNING", "ARMED", "TRANSFER_PENDING"):
        raise ApiError(
            "ERR_DEVICE_NOT_ACCEPTING_TELEMETRY",
            "A device in %s does not accept telemetry." % device_row["lifecycle_state"],
        )
    now = clock.now()
    if reading_at > now:
        raise ApiError("ERR_READING_IN_FUTURE", "The sample is stamped after the clock.")
    if reading_at < now - timedelta(hours=MAX_READING_BACKDATE_HOURS):
        raise ApiError("ERR_READING_TOO_OLD", "The sample is backdated beyond the limit.")
    last = device_row.get("last_reading_at")
    if last is not None and reading_at <= last:
        raise ApiError(
            "ERR_READING_OUT_OF_ORDER", "The telemetry stream must be strictly increasing."
        )
    reading = services.ingest_reading(
        device_row, reading_at, pressure, flow, duration, gallons, source
    )
    return created(ser.telemetry_reading(reading))


@bp.post("/devices/<did>/valve-commands")
def valve_command(did):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    device_row = _device(did)
    body = get_body(request)
    command = req_enum(body, "command", VALVE_COMMANDS)
    expected = req_int(body, "expected_device_version", minimum=0)
    reason = opt_string(body, "override_reason", 1, 280)
    acknowledge = opt_bool_default(body, "acknowledge_water_damage_risk", False)
    auth.own_device(actor, device_row)
    auth.alive_device(device_row)
    if expected != device_row["version"]:
        raise ApiError(
            "ERR_STALE_DEVICE_VERSION",
            "expected_device_version does not match the device's current version.",
        )
    if command == "CLOSE" and device_row["valve_state"] == "CLOSED":
        raise ApiError("ERR_VALVE_ALREADY_IN_STATE", "The valve is already CLOSED.")
    if command == "OPEN" and device_row["valve_state"] == "OPEN":
        raise ApiError("ERR_VALVE_ALREADY_IN_STATE", "The valve is already OPEN.")
    if command == "OPEN":
        blocking = [
            e
            for e in db.events_for_device(did)
            if e["classification"] == "CATASTROPHIC_BURST"
            and e["event_state"] in ("ALERTED", "ESCALATED")
        ]
        if blocking and not (acknowledge and reason):
            raise ApiError(
                "ERR_UNRESOLVED_BURST_BLOCKS_REOPEN",
                "An unresolved catastrophic burst blocks reopening the valve.",
            )
    if device_row["lifecycle_state"] == "TRANSFER_PENDING":
        raise ApiError(
            "ERR_DEVICE_TRANSFER_LOCKED", "Valve control is frozen during a pending transfer."
        )
    if command == "CLOSE" and device_row["lifecycle_state"] not in ("LEARNING", "ARMED"):
        raise ApiError(
            "ERR_DEVICE_NOT_ARMED",
            "A manual CLOSE requires the device to be LEARNING or ARMED.",
        )

    now = clock.now()
    if command == "CLOSE":
        device_row["valve_state"] = "CLOSED"
        device_row["close_count"] = device_row["close_count"] + 1
        device_row["last_shutoff_at"] = now
        db.touch(device_row)
        services.suspend_irrigation(device_row["property_id"])
    else:
        device_row["valve_state"] = "OPEN"
        device_row["reopen_count"] = device_row["reopen_count"] + 1
        db.touch(device_row)
        services.restore_irrigation(device_row["property_id"])
        for event in db.events_for_device(did):
            if event["event_state"] in ("ALERTED", "ESCALATED"):
                event["override_reopen_at"] = now
                db.touch(event)
    return ok(ser.device(device_row))


@bp.post("/devices/<did>/monitor-mode")
def monitor_mode(did):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    device_row = _device(did)
    body = get_body(request)
    mode = req_enum(body, "mode", MONITOR_MODES)
    now = clock.now()
    vacation_ends_at = None
    snooze_minutes = None
    if mode == "VACATION":
        vacation_ends_at = req_datetime(body, "vacation_ends_at")
        if vacation_ends_at <= now or vacation_ends_at > now + timedelta(days=MAX_VACATION_DAYS):
            raise bad_request(
                "vacation_ends_at must be after the clock and within %d days of it."
                % MAX_VACATION_DAYS
            )
    if mode == "SNOOZE":
        snooze_minutes = req_int(body, "snooze_minutes", MIN_SNOOZE_MINUTES, MAX_SNOOZE_MINUTES)
    auth.own_device(actor, device_row)
    auth.alive_device(device_row)
    if mode in ("VACATION", "SNOOZE") and device_row["lifecycle_state"] != "ARMED":
        raise ApiError(
            "ERR_DEVICE_NOT_ARMED", "Entering %s requires an ARMED device." % mode
        )
    if device_row["lifecycle_state"] == "TRANSFER_PENDING":
        raise ApiError(
            "ERR_DEVICE_TRANSFER_LOCKED", "Mode changes are frozen during a pending transfer."
        )
    current = device_row["monitor_mode"]
    legal = {
        ("NORMAL", "VACATION"),
        ("VACATION", "NORMAL"),
        ("NORMAL", "SNOOZE"),
        ("SNOOZE", "NORMAL"),
        ("NORMAL", "NORMAL"),
        ("VACATION", "VACATION"),
        ("SNOOZE", "SNOOZE"),
    }
    if (current, mode) not in legal:
        raise ApiError(
            "ERR_MODE_TRANSITION_FORBIDDEN",
            "%s -> %s is not a transition; return to NORMAL first." % (current, mode),
        )
    if mode == "SNOOZE" and device_row.get("snooze_window_end_at") is not None:
        available_at = device_row["snooze_window_end_at"] + timedelta(
            minutes=SNOOZE_COOLDOWN_MINUTES
        )
        if now < available_at:
            raise ApiError(
                "ERR_SNOOZE_COOLDOWN_ACTIVE", "The snooze cooldown has not yet elapsed."
            )

    device_row["monitor_mode"] = mode
    device_row["monitor_mode_updated_at"] = now
    if mode == "VACATION":
        device_row["vacation_started_at"] = now
        device_row["vacation_ends_at"] = vacation_ends_at
    elif mode == "SNOOZE":
        device_row["snooze_window_start_at"] = now
        device_row["snooze_window_end_at"] = now + timedelta(minutes=snooze_minutes)
    else:
        device_row["vacation_started_at"] = None
        device_row["vacation_ends_at"] = None
    db.touch(device_row)
    return ok(ser.device(device_row))


@bp.post("/devices/<did>/firmware-updates")
def firmware_update(did):
    auth.guard(ROLE_INSTALLER, ROLE_ADMIN)
    device_row = _device(did)
    body = get_body(request)
    target = req_string(body, "target_firmware_version", 1, 40)
    if target == device_row["firmware_version"]:
        raise bad_request("target_firmware_version must differ from the current firmware.")
    auth.alive_device(device_row)
    if device_row["lifecycle_state"] == "TRANSFER_PENDING":
        raise ApiError(
            "ERR_DEVICE_TRANSFER_LOCKED",
            "Firmware pushes are frozen during a pending transfer.",
        )
    was_armed = device_row["lifecycle_state"] == "ARMED"
    device_row["firmware_version"] = target
    db.touch(device_row)
    if was_armed:
        services.demote_device(device_row, "FIRMWARE_UPDATE")
    return ok(ser.device(device_row))
