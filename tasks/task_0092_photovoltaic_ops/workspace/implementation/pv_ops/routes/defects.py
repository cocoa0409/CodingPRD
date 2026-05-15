"""Defect endpoints (open / list / close / reopen). Work-order endpoints live alongside."""
from __future__ import annotations

from flask import Blueprint, current_app, g, request

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_DEFECT_PARENT_SUBJECT_MISMATCH,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)
from pv_ops.responses import created, listed, success
from pv_ops.services import serializers
from pv_ops.store import paginate
from pv_ops.utils import (
    get_body,
    opt_int,
    opt_str,
    parse_dt,
    parse_pagination,
    require_enum,
    require_str,
)


bp = Blueprint("defects", __name__)


SUBJECT_TYPES = {"INVERTER", "MODULE", "TRANSFORMER", "STRING", "ARRAY"}
DEFECT_SOURCES = {"ALARM", "PATROL", "DATA_ANOMALY", "EXTERNAL_INSPECTION"}
DEFECT_SEVERITIES = {"MINOR", "MODERATE", "MAJOR", "CRITICAL"}
SEVERITY_RANK = {"MINOR": 1, "MODERATE": 2, "MAJOR": 3, "CRITICAL": 4}


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


def _max_severity(a: str, b: str) -> str:
    return a if SEVERITY_RANK[a] >= SEVERITY_RANK[b] else b


@bp.route("/pv-ops/defects", methods=["POST"])
@require_roles("O&MEngineer")
def open_defect():
    body = get_body()
    station_id = require_str(body, "station_id")
    subject_type = require_enum(body, "subject_type", SUBJECT_TYPES)
    subject_id = require_str(body, "subject_id")
    source = require_enum(body, "source", DEFECT_SOURCES)
    source_ref_id = opt_str(body, "source_ref_id")
    severity = require_enum(body, "severity", DEFECT_SEVERITIES)
    parent_defect_id = opt_str(body, "parent_defect_id")

    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        if not _subject_exists(store, subject_type, subject_id):
            raise APIError(ERR_NOT_FOUND, 404, "Subject not found")

        # Validate parent chain
        recurrence_index = 1
        if parent_defect_id is not None:
            cur = parent_defect_id
            while cur is not None:
                parent = store.defects.get(cur)
                if parent is None:
                    raise APIError(ERR_NOT_FOUND, 404, "Parent defect not found")
                if parent.get("subject_type") != subject_type or parent.get("subject_id") != subject_id:
                    raise APIError(
                        ERR_DEFECT_PARENT_SUBJECT_MISMATCH,
                        422,
                        "Parent defect subject mismatch",
                    )
                if parent.get("state") == "CLOSED":
                    recurrence_index += 1
                cur = parent.get("parent_defect_id")

        if recurrence_index >= 3:
            severity = _max_severity(severity, "MAJOR")

        row = {
            "station_id": station_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "source": source,
            "source_ref_id": source_ref_id,
            "severity": severity,
            "parent_defect_id": parent_defect_id,
            "state": "OPEN",
            "opened_at": store.clock.now_iso(),
            "resolved_at": None,
            "recurrence_index": recurrence_index,
        }
        store.insert_common(row)
        store.defects[row["id"]] = row
        return created(serializers.defect_view(row))


@bp.route("/pv-ops/defects", methods=["GET"])
@require_roles("PlatformAdmin", "O&MEngineer")
def list_defects():
    store = current_app.extensions["store"]
    limit, offset = parse_pagination(request.args)
    station_id = request.args.get("station_id")
    state = request.args.get("state")
    source = request.args.get("source")
    subject_type = request.args.get("subject_type")
    rec_min_raw = request.args.get("recurrence_index_min")
    rec_min = None
    if rec_min_raw is not None:
        try:
            rec_min = int(rec_min_raw)
        except ValueError:
            raise APIError(ERR_VALIDATION, 422, "recurrence_index_min must be an integer")
    with store.lock:
        rows = list(store.defects.values())
        if station_id:
            rows = [r for r in rows if r.get("station_id") == station_id]
        if state:
            rows = [r for r in rows if r.get("state") == state]
        if source:
            rows = [r for r in rows if r.get("source") == source]
        if subject_type:
            rows = [r for r in rows if r.get("subject_type") == subject_type]
        if rec_min is not None:
            rows = [r for r in rows if int(r.get("recurrence_index", 1)) >= rec_min]
        rows.sort(key=lambda r: r["created_at"])
        page, total, has_more = paginate(rows, limit, offset)
        return listed(
            [serializers.defect_view(r) for r in page],
            limit=limit,
            offset=offset,
            total_count=total,
            has_more=has_more,
        )


@bp.route("/pv-ops/defects/<defect_id>/close", methods=["POST"])
@require_roles("O&MEngineer")
def close_defect(defect_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        defect = store.defects.get(defect_id)
        if not defect:
            raise APIError(ERR_NOT_FOUND, 404, "Defect not found")
        if defect.get("state") != "RESOLVED":
            raise APIError(ERR_INVALID_STATE, 409, "Defect must be RESOLVED to close")
        defect["state"] = "CLOSED"
        store.bump(defect)
        return success(serializers.defect_view(defect))


@bp.route("/pv-ops/defects/<defect_id>/reopen", methods=["POST"])
@require_roles("O&MEngineer")
def reopen_defect(defect_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        defect = store.defects.get(defect_id)
        if not defect:
            raise APIError(ERR_NOT_FOUND, 404, "Defect not found")
        if defect.get("state") != "RESOLVED":
            raise APIError(ERR_INVALID_STATE, 409, "Defect must be RESOLVED to reopen")
        resolved_at_raw = defect.get("resolved_at")
        if not resolved_at_raw:
            raise APIError(ERR_INVALID_STATE, 409, "Defect has no resolved_at")
        resolved_at = parse_dt(resolved_at_raw, "resolved_at")
        now = store.clock.now()
        delta = now - resolved_at
        if delta.total_seconds() > 30 * 86400:
            raise APIError(ERR_INVALID_STATE, 409, "Defect resolved more than 30 days ago")
        defect["state"] = "REOPENED"
        store.bump(defect)
        return success(serializers.defect_view(defect))
