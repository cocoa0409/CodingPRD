"""SupervisionAssignment routes (no version field; append-only ledger)."""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
)
from ..helpers import (
    assert_string,
    new_uuid,
    parse_iso8601,
    require_json_object,
)
from ..responses import created, ok
from ..services.serialize import serialize_supervision_assignment
from ..store import store

bp = Blueprint("supervision_assignments", __name__, url_prefix="/practice/supervision-assignments")


@bp.post("")
@require_roles("PracticeAdmin")
def create_assignment(**_):
    body = require_json_object()
    therapist_id = assert_string(body.get("therapist_id"), "therapist_id")
    supervisor_id = assert_string(body.get("supervisor_id"), "supervisor_id")
    started_on = parse_iso8601(body.get("started_on"), "started_on")
    s = store()
    with s.lock:
        if therapist_id not in s.therapists:
            raise err_reference_not_found("therapist_id does not resolve")
        if supervisor_id not in s.supervisors:
            raise err_reference_not_found("supervisor_id does not resolve")
        aid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": aid,
            "therapist_id": therapist_id,
            "supervisor_id": supervisor_id,
            "started_on": started_on,
            "ended_on": None,
            "status": "ACTIVE",
            "created_at": ts,
        }
        s.supervision_assignments[aid] = row
        return created(serialize_supervision_assignment(row))


@bp.post("/<aid>/terminate")
@require_roles("PracticeAdmin")
def terminate_assignment(aid: str, **_):
    s = store()
    with s.lock:
        row = s.supervision_assignments.get(aid)
        if row is None:
            raise err_not_found("SupervisionAssignment not found")
        if row["status"] != "ACTIVE":
            raise err_invalid_state("Only ACTIVE assignments may be terminated")
        row["status"] = "TERMINATED"
        row["ended_on"] = now()
        return ok(serialize_supervision_assignment(row))
