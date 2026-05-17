"""Visit endpoints — scheduling, completion, mark-missed, delete-cancel."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Blueprint

from ..auth import (
    ROLE_COORD,
    ROLE_PARTICIPANT_SELF,
    ROLE_PI,
    enforce_self_ownership,
    require_roles,
)
from ..clock import now
from ..errors import (
    err_ae_blocking,
    err_consent_version_stale,
    err_draw_outside_window,
    err_duplicate_visit_sequence,
    err_invalid_state,
    err_window_not_yet_passed,
)
from ..helpers import (
    assert_integer,
    new_uuid,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, no_content, ok
from ..services.calculations import (
    day_offset,
    visit_provisional_cents,
)
from ..services.lookups import (
    get_participant,
    get_trial,
    get_visit,
    open_ae_count_for,
    visits_for_participant,
)
from ..services.serialize import serialize_visit
from ..store import store

bp = Blueprint("visits", __name__)


def _bump(v: dict[str, Any]) -> None:
    v["updated_at"] = now()
    v["version"] = v["version"] + 1


# =====================================================================
# POST /participants/<id>/visits  — schedule a visit
# =====================================================================

@bp.post("/participants/<participant_id>/visits")
@require_roles(ROLE_COORD)
def create_visit(participant_id: str, **_caller):
    body = require_json_object()
    sequence_no = assert_integer(body.get("sequence_no"), "sequence_no", required=True, minimum=1, maximum=50)
    target_date = parse_iso8601(body.get("target_date"), "target_date", required=True)

    with store().lock:
        p = get_participant(participant_id)
        # sequence_no must be unique within the participant.
        for v in visits_for_participant(participant_id):
            if v["sequence_no"] == sequence_no:
                raise err_duplicate_visit_sequence()

        ts = now()
        vid = new_uuid()
        v = {
            "id": vid,
            "participant_id": participant_id,
            "sequence_no": sequence_no,
            "target_date": target_date,
            "status": "SCHEDULED",
            "actual_draw_at": None,
            "compensation_cents": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        store().visits[vid] = v
    return created(serialize_visit(v))


# =====================================================================
# GET /participants/<id>/visits
# =====================================================================

@bp.get("/participants/<participant_id>/visits")
@require_roles(ROLE_PI, ROLE_COORD, ROLE_PARTICIPANT_SELF)
def list_visits(participant_id: str, **caller):
    enforce_self_ownership(participant_id, caller["_caller_id"], caller["_caller_role"])
    limit, offset = parse_pagination()
    with store().lock:
        get_participant(participant_id)
        rows = visits_for_participant(participant_id)
        total = len(rows)
        page = paginate(rows, limit, offset)
        items = [serialize_visit(v) for v in page]
    return listing(items, total, limit, offset)


# =====================================================================
# POST /visits/<id>/complete
# =====================================================================

@bp.post("/visits/<visit_id>/complete")
@require_roles(ROLE_COORD)
def complete_visit(visit_id: str, **_caller):
    body = require_json_object()

    with store().lock:
        # Order: existence → state → AE gate → consent stale → window. Per PRD §2.8,
        # generic input validation has the lowest priority, so we parse actual_draw_at
        # only after the higher-priority gates have been satisfied.
        v = get_visit(visit_id)
        if v["status"] != "SCHEDULED":
            raise err_invalid_state("Visit is not SCHEDULED")
        p = get_participant(v["participant_id"])
        if p["status"] != "ENROLLED":
            raise err_invalid_state("Participant is not ENROLLED")
        if open_ae_count_for(p["id"]) > 0:
            raise err_ae_blocking()
        trial = get_trial(p["trial_id"])
        if (
            p["signed_consent_version"] is None
            or trial["active_consent_version"] is None
            or p["signed_consent_version"] != trial["active_consent_version"]
        ):
            raise err_consent_version_stale(
                "Participant must re-consent before further visits may complete"
            )
        # Now parse and validate actual_draw_at; then apply window gate.
        actual_draw_at = parse_iso8601(body.get("actual_draw_at"), "actual_draw_at", required=True)
        d = day_offset(actual_draw_at, v["target_date"])
        if d > trial["blood_draw_window_days"]:
            raise err_draw_outside_window()

        comp = visit_provisional_cents(actual_draw_at, v["target_date"], trial["blood_draw_window_days"])

        ts = now()
        v["status"] = "COMPLETED"
        v["actual_draw_at"] = actual_draw_at
        v["compensation_cents"] = comp
        _bump(v)

        # Write a PROVISIONAL Payment row.
        pmt_id = new_uuid()
        store().payments[pmt_id] = {
            "id": pmt_id,
            "participant_id": p["id"],
            "visit_id": v["id"],
            "kind": "PROVISIONAL",
            "amount_cents": comp,
            "paid_at": None,
            "created_at": ts,
        }
        return ok(serialize_visit(v))


# =====================================================================
# POST /visits/<id>/mark-missed
# =====================================================================

@bp.post("/visits/<visit_id>/mark-missed")
@require_roles(ROLE_COORD)
def mark_missed(visit_id: str, **_caller):
    with store().lock:
        v = get_visit(visit_id)
        if v["status"] != "SCHEDULED":
            raise err_invalid_state("Visit is not SCHEDULED")
        p = get_participant(v["participant_id"])
        trial = get_trial(p["trial_id"])
        # §2.9: "the current logical clock time has strictly passed target_date + window_days".
        # Project both to UTC calendar dates and require strict day-level greater-than.
        from datetime import timezone as _tz
        target_date = v["target_date"]
        boundary_date = (target_date.astimezone(_tz.utc)).date() + timedelta(
            days=trial["blood_draw_window_days"]
        )
        current_date = now().astimezone(_tz.utc).date()
        if current_date <= boundary_date:
            raise err_window_not_yet_passed()
        v["status"] = "MISSED"
        _bump(v)
        return ok(serialize_visit(v))


# =====================================================================
# DELETE /visits/<id>
# =====================================================================

@bp.delete("/visits/<visit_id>")
@require_roles(ROLE_COORD)
def cancel_visit(visit_id: str, **_caller):
    with store().lock:
        v = get_visit(visit_id)
        if v["status"] != "SCHEDULED":
            raise err_invalid_state("Only SCHEDULED visits may be cancelled")
        v["status"] = "CANCELLED"
        _bump(v)
    return no_content()
