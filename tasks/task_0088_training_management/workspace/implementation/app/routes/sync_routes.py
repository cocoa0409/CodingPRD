"""SyncEvent endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..store import bump_version, common_fields_append_only, get_store, now_iso
from ..services.serializers import serialize_sync_event
from ._helpers import created, get_json_body, with_lock


def _apply_event(row: dict) -> None:
    """Apply a sync event. Mutates row['outcome'] and row['processed_at']."""
    store = get_store()
    src = row["source_system"]
    et = row["event_type"]
    payload = row.get("payload") or {}
    try:
        if src == "HR" and et == "employee.updated":
            emp_no = payload.get("employee_no")
            tid = store.trainee_employee_no_uniq.get(emp_no) if emp_no else None
            if not tid:
                row["outcome"] = "REJECTED"
            else:
                t = store.trainees.get(tid)
                if t is None:
                    row["outcome"] = "REJECTED"
                else:
                    for k in ("full_name", "department", "job_level", "status"):
                        if k in payload:
                            t[k] = payload[k]
                    bump_version(t)
                    row["outcome"] = "APPLIED"
        else:
            # Other event types are simply recorded as APPLIED
            row["outcome"] = "APPLIED"
    except Exception:
        row["outcome"] = "REJECTED"
    row["processed_at"] = now_iso()


def register(app: Flask) -> None:
    @app.post("/training/_events/emit")
    @require_auth("TrainingAdmin")
    @with_lock
    def emit_event():
        body = get_json_body()
        src = body.get("source_system")
        if src not in ("HR", "IM", "LCP"):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "source_system must be HR/IM/LCP.", http_status=422)
        et = body.get("event_type")
        if not isinstance(et, str) or not et:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "event_type required.", http_status=422)
        payload = body.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "payload must be object.", http_status=422)

        base = common_fields_append_only()
        row = {
            **base,
            "source_system": src,
            "event_type": et,
            "payload": payload or {},
            "processed_at": None,
            "outcome": "PENDING",
        }
        get_store().sync_events[base["id"]] = row
        _apply_event(row)
        return created(serialize_sync_event(row))
