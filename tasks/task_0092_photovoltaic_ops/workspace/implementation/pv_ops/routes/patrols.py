"""Patrol plan + record endpoints."""
from __future__ import annotations

from copy import deepcopy

from flask import Blueprint, current_app, g

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_UNIQUE_VIOLATION,
    ERR_VALIDATION,
)
from pv_ops.responses import created, success
from pv_ops.services import serializers
from pv_ops.utils import (
    fmt_dt,
    get_body,
    opt_int,
    parse_dt,
    require_enum,
    require_field,
    require_list,
    require_str,
)


bp = Blueprint("patrols", __name__)


@bp.route("/pv-ops/stations/<station_id>/patrol-plans", methods=["POST"])
@require_roles("O&MEngineer")
def create_patrol_plan(station_id: str):
    body = get_body()
    name = require_str(body, "name", min_len=1, max_len=120)
    zone_route = require_list(body, "zone_route", min_len=1, max_len=50)
    for z in zone_route:
        if not isinstance(z, str):
            raise APIError(ERR_VALIDATION, 422, "zone_route entries must be strings")
    if len(set(zone_route)) != len(zone_route):
        raise APIError(ERR_VALIDATION, 422, "zone_route must not contain duplicates")
    kind = require_enum(body, "kind", {"PERIODIC", "SPECIAL_POST_STORM"})
    cadence_days = opt_int(body, "cadence_days", ge=1, le=180)
    if kind == "PERIODIC" and cadence_days is None:
        raise APIError(ERR_VALIDATION, 422, "cadence_days is required for PERIODIC plans")
    if kind == "SPECIAL_POST_STORM" and cadence_days is not None:
        raise APIError(ERR_VALIDATION, 422, "cadence_days must be null for SPECIAL_POST_STORM plans")
    if "checklist" not in body:
        raise APIError(ERR_VALIDATION, 422, "checklist is required")
    checklist = body["checklist"]
    if not isinstance(checklist, dict):
        raise APIError(ERR_VALIDATION, 422, "checklist must be an object keyed by equipment type")

    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        for p in store.patrol_plans.values():
            if p.get("station_id") == station_id and p.get("name") == name:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Patrol plan name not unique in station")
        row = {
            "station_id": station_id,
            "name": name,
            "zone_route": list(zone_route),
            "kind": kind,
            "cadence_days": cadence_days,
            "checklist": deepcopy(checklist),
            "lifecycle_state": "ACTIVE",
        }
        store.insert_common(row)
        store.patrol_plans[row["id"]] = row
        return created(serializers.patrol_plan_view(row))


@bp.route("/pv-ops/patrol-plans/<plan_id>/schedule", methods=["POST"])
@require_roles("O&MEngineer")
def schedule_patrol(plan_id: str):
    body = get_body()
    scheduled_for = parse_dt(body.get("scheduled_for"), "scheduled_for")
    store = current_app.extensions["store"]
    with store.lock:
        plan = store.patrol_plans.get(plan_id)
        if not plan:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol plan not found")
        if plan.get("lifecycle_state") != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Patrol plan is not ACTIVE")
        row = {
            "patrol_plan_id": plan_id,
            "station_id": plan["station_id"],
            "scheduled_for": fmt_dt(scheduled_for),
            "actor_id": None,
            "zone_progress": [],
            "completed_zone_count": 0,
            "state": "SCHEDULED",
            "verification_notes": None,
        }
        store.insert_common(row)
        store.patrol_records[row["id"]] = row
        return created(serializers.patrol_record_view(row))


@bp.route("/pv-ops/patrol-records/<record_id>/start", methods=["POST"])
@require_roles("FieldOperator")
def start_patrol(record_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        rec = store.patrol_records.get(record_id)
        if not rec:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol record not found")
        if rec.get("state") != "SCHEDULED":
            raise APIError(ERR_INVALID_STATE, 409, "Patrol record not in SCHEDULED")
        plan = store.patrol_plans.get(rec["patrol_plan_id"])
        if not plan or plan.get("lifecycle_state") != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Patrol plan no longer active")
        rec["state"] = "IN_PROGRESS"
        rec["actor_id"] = g.user_id
        store.bump(rec)
        return success(serializers.patrol_record_view(rec))


@bp.route("/pv-ops/patrol-records/<record_id>/zones/<zone>/log", methods=["POST"])
@require_roles("FieldOperator")
def log_zone(record_id: str, zone: str):
    body = get_body()
    photo_url = require_str(body, "photo_url")
    if "gps" not in body or not isinstance(body["gps"], dict):
        raise APIError(ERR_VALIDATION, 422, "gps {lat, lng} required")
    gps = body["gps"]
    if "lat" not in gps or "lng" not in gps:
        raise APIError(ERR_VALIDATION, 422, "gps must include lat and lng")
    if "checklist_findings" not in body:
        raise APIError(ERR_VALIDATION, 422, "checklist_findings required")
    findings = body["checklist_findings"]

    store = current_app.extensions["store"]
    with store.lock:
        rec = store.patrol_records.get(record_id)
        if not rec:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol record not found")
        if rec.get("state") != "IN_PROGRESS":
            raise APIError(ERR_INVALID_STATE, 409, "Patrol record not in IN_PROGRESS")
        if rec.get("actor_id") != g.user_id:
            raise APIError(ERR_SOD_VIOLATION, 403, "Only the patrol's actor may log zones")
        plan = store.patrol_plans.get(rec["patrol_plan_id"])
        if not plan:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol plan not found")
        if zone not in plan["zone_route"]:
            raise APIError(ERR_VALIDATION, 422, "Zone not in plan zone_route")

        # Replace or append
        progress = rec["zone_progress"]
        replaced = False
        zone_entry = {
            "zone": zone,
            "photo_url": photo_url,
            "gps": {"lat": gps["lat"], "lng": gps["lng"]},
            "checklist_findings": deepcopy(findings),
        }
        for i, entry in enumerate(progress):
            if entry.get("zone") == zone:
                progress[i] = zone_entry
                replaced = True
                break
        if not replaced:
            progress.append(zone_entry)

        # Recompute completed_zone_count: a zone is "complete" if findings cover the
        # required checklist items for that zone's equipment-type group. We treat any
        # non-empty checklist_findings list/dict as completing the zone.
        completed = 0
        for entry in progress:
            f = entry.get("checklist_findings")
            if isinstance(f, list) and len(f) > 0:
                completed += 1
            elif isinstance(f, dict) and len(f) > 0:
                completed += 1
        rec["completed_zone_count"] = completed
        store.bump(rec)
        return success(serializers.patrol_record_view(rec))


@bp.route("/pv-ops/patrol-records/<record_id>/submit", methods=["POST"])
@require_roles("FieldOperator")
def submit_patrol(record_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        rec = store.patrol_records.get(record_id)
        if not rec:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol record not found")
        if rec.get("state") != "IN_PROGRESS":
            raise APIError(ERR_INVALID_STATE, 409, "Patrol record not in IN_PROGRESS")
        if rec.get("actor_id") != g.user_id:
            raise APIError(ERR_SOD_VIOLATION, 403, "Only the patrol's actor may submit")
        plan = store.patrol_plans.get(rec["patrol_plan_id"])
        if not plan:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol plan not found")
        if rec.get("completed_zone_count", 0) != len(plan["zone_route"]):
            raise APIError(ERR_INVALID_STATE, 409, "Not all zones completed")
        rec["state"] = "SUBMITTED"
        store.bump(rec)
        return success(serializers.patrol_record_view(rec))


@bp.route("/pv-ops/patrol-records/<record_id>/verify", methods=["POST"])
@require_roles("O&MEngineer")
def verify_patrol(record_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        rec = store.patrol_records.get(record_id)
        if not rec:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol record not found")
        if rec.get("state") != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE, 409, "Patrol record not in SUBMITTED")
        if rec.get("actor_id") == g.user_id:
            raise APIError(ERR_SOD_VIOLATION, 403, "Verifier must differ from actor")
        rec["state"] = "VERIFIED"
        store.bump(rec)

        # Side effect: scan zone_progress findings for defect: true entries
        for entry in rec.get("zone_progress", []):
            findings = entry.get("checklist_findings")
            flagged_entries = []
            if isinstance(findings, list):
                flagged_entries = [f for f in findings if isinstance(f, dict) and f.get("defect")]
            elif isinstance(findings, dict):
                # Single finding object
                if findings.get("defect"):
                    flagged_entries = [findings]
            for f in flagged_entries:
                subject_type = f.get("subject_type")
                subject_id = f.get("subject_id")
                if not subject_type or not subject_id:
                    continue
                if subject_type not in ("INVERTER", "MODULE", "TRANSFORMER", "STRING", "ARRAY"):
                    continue
                # Verify subject existence
                if not _subject_exists(store, subject_type, subject_id):
                    continue
                severity = f.get("severity", "MINOR")
                if severity not in ("MINOR", "MODERATE", "MAJOR", "CRITICAL"):
                    severity = "MINOR"
                defect = {
                    "station_id": rec["station_id"],
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "source": "PATROL",
                    "source_ref_id": rec["id"],
                    "severity": severity,
                    "parent_defect_id": None,
                    "state": "OPEN",
                    "opened_at": store.clock.now_iso(),
                    "resolved_at": None,
                    "recurrence_index": 1,
                }
                store.insert_common(defect)
                store.defects[defect["id"]] = defect
        return success(serializers.patrol_record_view(rec))


@bp.route("/pv-ops/patrol-records/<record_id>/reject", methods=["POST"])
@require_roles("O&MEngineer")
def reject_patrol(record_id: str):
    body = get_body()
    notes = require_str(body, "notes")
    store = current_app.extensions["store"]
    with store.lock:
        rec = store.patrol_records.get(record_id)
        if not rec:
            raise APIError(ERR_NOT_FOUND, 404, "Patrol record not found")
        if rec.get("state") != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE, 409, "Patrol record not in SUBMITTED")
        if rec.get("actor_id") == g.user_id:
            raise APIError(ERR_SOD_VIOLATION, 403, "Rejecter must differ from actor")
        rec["state"] = "REJECTED"
        rec["verification_notes"] = notes
        store.bump(rec)
        return success(serializers.patrol_record_view(rec))


def _subject_exists(store, subject_type: str, subject_id: str) -> bool:
    if subject_type == "INVERTER":
        return subject_id in store.inverters
    if subject_type == "MODULE":
        return subject_id in store.modules
    if subject_type == "TRANSFORMER":
        return subject_id in store.transformers
    if subject_type == "STRING":
        return subject_id in store.strings
    if subject_type == "ARRAY":
        return subject_id in store.arrays
    return False
