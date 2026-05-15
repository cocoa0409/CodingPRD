"""Alarm code map, alarm ingestion, alarm workflow."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from flask import Blueprint, current_app, g, request

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_ALARM_ALREADY_ACKED,
    ERR_ALARM_CODE_UNMAPPED,
    ERR_ALARM_INFO_NOT_ACKABLE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_UNIQUE_VIOLATION,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
)
from pv_ops.responses import created, listed, success
from pv_ops.services import serializers
from pv_ops.services.cascades import recompute_station_operational_status
from pv_ops.store import paginate
from pv_ops.utils import (
    fmt_dt,
    get_body,
    opt_enum,
    opt_int,
    opt_str,
    parse_dt,
    parse_pagination,
    require_enum,
    require_str,
)


bp = Blueprint("alarms", __name__)

DEDUP_WINDOW_SECONDS = 300


# ---- Alarm code map ----
@bp.route("/pv-ops/alarm-code-map", methods=["POST"])
@require_roles("PlatformAdmin")
def create_alarm_code_map():
    body = get_body()
    vendor = require_str(body, "vendor")
    model = require_str(body, "model")
    vendor_code = require_str(body, "vendor_code")
    canonical_code = require_str(body, "canonical_code")
    severity = require_enum(body, "severity", {"INFO", "WARN", "MAJOR", "CRITICAL"})
    root_cause_hint = require_str(body, "root_cause_hint")
    store = current_app.extensions["store"]
    with store.lock:
        for m in store.alarm_code_maps.values():
            if (
                m.get("vendor") == vendor
                and m.get("model") == model
                and m.get("vendor_code") == vendor_code
            ):
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Alarm code map already exists")
        row = {
            "vendor": vendor,
            "model": model,
            "vendor_code": vendor_code,
            "canonical_code": canonical_code,
            "severity": severity,
            "root_cause_hint": root_cause_hint,
        }
        store.insert_lite(row)
        store.alarm_code_maps[row["id"]] = row
        return created(serializers.alarm_code_view(row))


# ---- Alarm ingestion ----
@bp.route("/pv-ops/alarms", methods=["POST"])
@require_roles("PlatformAdmin")
def ingest_alarm():
    body = get_body()
    inverter_id = require_str(body, "inverter_id")
    vendor_code = require_str(body, "vendor_code")
    first_seen_at = parse_dt(body.get("first_seen_at"), "first_seen_at")
    store = current_app.extensions["store"]
    with store.lock:
        inv = store.inverters.get(inverter_id)
        if not inv:
            raise APIError(ERR_NOT_FOUND, 404, "Inverter not found")

        # Resolve the alarm code map
        mapping = None
        for m in store.alarm_code_maps.values():
            if (
                m.get("vendor") == inv.get("vendor")
                and m.get("model") == inv.get("model")
                and m.get("vendor_code") == vendor_code
            ):
                mapping = m
                break
        if mapping is None:
            raise APIError(ERR_ALARM_CODE_UNMAPPED, 422, "vendor_code not mapped")

        canonical_code = mapping["canonical_code"]
        severity = mapping["severity"]

        # Look for existing OPEN AlarmEvent on same (inverter_id, canonical_code)
        existing = None
        for ev in store.alarm_events.values():
            if (
                ev.get("inverter_id") == inverter_id
                and ev.get("canonical_code") == canonical_code
                and ev.get("state") == "OPEN"
            ):
                existing = ev
                break

        if existing is not None:
            ls = parse_dt(existing["last_seen_at"], "last_seen_at")
            delta = abs((first_seen_at - ls).total_seconds())
            if delta <= DEDUP_WINDOW_SECONDS:
                existing["occurrence_count"] = int(existing.get("occurrence_count", 1)) + 1
                existing["last_seen_at"] = fmt_dt(first_seen_at)
                store.bump(existing)
                return created(serializers.alarm_event_view(existing))

        # Otherwise create a new event
        row = {
            "inverter_id": inverter_id,
            "station_id": inv.get("station_id"),
            "vendor_code": vendor_code,
            "canonical_code": canonical_code,
            "severity": severity,
            "first_seen_at": fmt_dt(first_seen_at),
            "last_seen_at": fmt_dt(first_seen_at),
            "occurrence_count": 1,
            "state": "OPEN",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "defect_id": None,
            "root_cause_hint": mapping.get("root_cause_hint"),
        }
        store.insert_common(row)
        store.alarm_events[row["id"]] = row
        return created(serializers.alarm_event_view(row))


@bp.route("/pv-ops/alarms", methods=["GET"])
@require_roles("PlatformAdmin", "O&MEngineer")
def list_alarms():
    store = current_app.extensions["store"]
    limit, offset = parse_pagination(request.args)
    station_id = request.args.get("station_id")
    inverter_id = request.args.get("inverter_id")
    state = request.args.get("state")
    severity = request.args.get("severity")
    with store.lock:
        rows = list(store.alarm_events.values())
        if station_id:
            rows = [r for r in rows if r.get("station_id") == station_id]
        if inverter_id:
            rows = [r for r in rows if r.get("inverter_id") == inverter_id]
        if state:
            rows = [r for r in rows if r.get("state") == state]
        if severity:
            rows = [r for r in rows if r.get("severity") == severity]
        rows.sort(key=lambda r: r["created_at"])
        page, total, has_more = paginate(rows, limit, offset)
        return listed(
            [serializers.alarm_event_view(r) for r in page],
            limit=limit,
            offset=offset,
            total_count=total,
            has_more=has_more,
        )


# ---- Alarm workflow: ack / clear / archive ----
@bp.route("/pv-ops/alarms/<alarm_id>/ack", methods=["POST"])
@require_roles("O&MEngineer")
def ack_alarm(alarm_id: str):
    body = get_body()
    version = opt_int(body, "version")
    store = current_app.extensions["store"]
    with store.lock:
        alarm = store.alarm_events.get(alarm_id)
        if not alarm:
            raise APIError(ERR_NOT_FOUND, 404, "Alarm not found")
        if alarm.get("state") != "OPEN":
            # Already-acked race
            if alarm.get("state") in ("ACKNOWLEDGED", "CLEARED", "ARCHIVED"):
                raise APIError(ERR_ALARM_ALREADY_ACKED, 409, "Alarm already acknowledged")
            raise APIError(ERR_INVALID_STATE, 409, "Alarm not in OPEN state")
        if version is not None and version != alarm.get("version"):
            raise APIError(ERR_VERSION_CONFLICT, 409, "Version mismatch")
        if alarm.get("severity") == "INFO":
            raise APIError(ERR_ALARM_INFO_NOT_ACKABLE, 422, "INFO alarms cannot be ack'd")

        before = deepcopy(alarm)

        alarm["state"] = "ACKNOWLEDGED"
        alarm["acknowledged_by"] = g.user_id
        alarm["acknowledged_at"] = store.clock.now_iso()
        store.bump(alarm)

        # Defect creation for MAJOR/CRITICAL
        if alarm["severity"] in ("MAJOR", "CRITICAL"):
            defect = {
                "station_id": alarm.get("station_id"),
                "subject_type": "INVERTER",
                "subject_id": alarm.get("inverter_id"),
                "source": "ALARM",
                "source_ref_id": alarm["id"],
                "severity": alarm["severity"],
                "parent_defect_id": None,
                "state": "OPEN",
                "opened_at": store.clock.now_iso(),
                "resolved_at": None,
                "recurrence_index": 1,
            }
            store.insert_common(defect)
            store.defects[defect["id"]] = defect
            alarm["defect_id"] = defect["id"]
            store.bump(alarm)

            # Cascade hop 2: CRITICAL defects lock inverter
            if alarm["severity"] == "CRITICAL":
                inv = store.inverters.get(alarm.get("inverter_id"))
                if inv and inv.get("lifecycle_state") == "OPERATING":
                    inv["lifecycle_state"] = "UNDER_REPAIR"
                    store.bump(inv)
                    # Cascade hop 3: station status
                    station = store.stations.get(inv.get("station_id"))
                    if station:
                        recompute_station_operational_status(store, station)

        # Audit entry
        after = deepcopy(alarm)
        _write_audit(
            store,
            actor_id=g.user_id,
            actor_role=g.user_role,
            target_type="ALARM",
            target_id=alarm["id"],
            action="ALARM_ACK",
            before_value={"state": before["state"], "version": before["version"]},
            after_value={"state": after["state"], "version": after["version"], "defect_id": after.get("defect_id")},
        )
        return success(serializers.alarm_event_view(alarm))


@bp.route("/pv-ops/alarms/<alarm_id>/clear", methods=["POST"])
@require_roles("O&MEngineer")
def clear_alarm(alarm_id: str):
    body = get_body()
    version = opt_int(body, "version")
    store = current_app.extensions["store"]
    with store.lock:
        alarm = store.alarm_events.get(alarm_id)
        if not alarm:
            raise APIError(ERR_NOT_FOUND, 404, "Alarm not found")
        if alarm.get("state") != "ACKNOWLEDGED":
            raise APIError(ERR_INVALID_STATE, 409, "Alarm must be ACKNOWLEDGED")
        if version is not None and version != alarm.get("version"):
            raise APIError(ERR_VERSION_CONFLICT, 409, "Version mismatch")
        if alarm.get("defect_id"):
            defect = store.defects.get(alarm["defect_id"])
            if defect and defect.get("state") not in ("RESOLVED", "CLOSED"):
                raise APIError(ERR_INVALID_STATE, 409, "Linked defect not resolved or closed")
        before = deepcopy(alarm)
        alarm["state"] = "CLEARED"
        store.bump(alarm)
        _write_audit(
            store,
            actor_id=g.user_id,
            actor_role=g.user_role,
            target_type="ALARM",
            target_id=alarm["id"],
            action="ALARM_CLEAR",
            before_value={"state": before["state"]},
            after_value={"state": alarm["state"]},
        )
        return success(serializers.alarm_event_view(alarm))


@bp.route("/pv-ops/alarms/<alarm_id>/archive", methods=["POST"])
@require_roles("O&MEngineer")
def archive_alarm(alarm_id: str):
    body = get_body()
    version = opt_int(body, "version")
    store = current_app.extensions["store"]
    with store.lock:
        alarm = store.alarm_events.get(alarm_id)
        if not alarm:
            raise APIError(ERR_NOT_FOUND, 404, "Alarm not found")
        state = alarm.get("state")
        if state == "OPEN":
            if alarm.get("severity") != "INFO":
                raise APIError(ERR_INVALID_STATE, 409, "Only INFO alarms can be archived from OPEN")
        elif state == "CLEARED":
            pass
        else:
            raise APIError(ERR_INVALID_STATE, 409, "Alarm cannot be archived from current state")
        if version is not None and version != alarm.get("version"):
            raise APIError(ERR_VERSION_CONFLICT, 409, "Version mismatch")
        before = deepcopy(alarm)
        alarm["state"] = "ARCHIVED"
        store.bump(alarm)
        _write_audit(
            store,
            actor_id=g.user_id,
            actor_role=g.user_role,
            target_type="ALARM",
            target_id=alarm["id"],
            action="ALARM_ARCHIVE",
            before_value={"state": before["state"]},
            after_value={"state": alarm["state"]},
        )
        return success(serializers.alarm_event_view(alarm))


def _write_audit(
    store,
    *,
    actor_id: str,
    actor_role: str,
    target_type: str,
    target_id: str,
    action: str,
    before_value: dict,
    after_value: dict,
) -> dict:
    row = {
        "actor_id": actor_id,
        "actor_role": actor_role,
        "target_type": target_type,
        "target_id": target_id,
        "action": action,
        "before_value": before_value,
        "after_value": after_value,
    }
    store.insert_lite(row)
    store.audit_entries[row["id"]] = row
    return row
