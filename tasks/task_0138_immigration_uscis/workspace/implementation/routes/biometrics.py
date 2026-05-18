"""Biometrics endpoints — schedule, complete, no-show, reschedule."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from db import store
from errors import (
    err_biometrics_already_scheduled,
    err_biometrics_reschedule_limit,
    err_biometrics_reschedule_too_late,
    err_biometrics_too_soon,
    err_invalid_state,
    err_validation,
)
from middleware import require_auth
from response import success
from services.case_engine import emit_case_event, stamp_create, stamp_update
from services.serializers import serialize_biometrics
from utils import is_valid_location_code, new_uuid, parse_iso_datetime

from routes._helpers import (
    get_biometrics_or_404,
    get_case_or_404,
    get_json,
    require_string,
)


bp = Blueprint("biometrics", __name__)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/biometrics — schedule
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/biometrics")
@require_auth(["Officer"])
def schedule_biometrics(case_id: str):
    case = get_case_or_404(case_id)
    body = get_json()

    scheduled_at_str = require_string(body, "scheduled_at")
    scheduled_at = parse_iso_datetime(scheduled_at_str)
    if scheduled_at is None:
        raise err_validation("scheduled_at must be a valid ISO 8601 timestamp.")

    location_code = require_string(body, "location_code")
    if not is_valid_location_code(location_code):
        raise err_validation("location_code must be 4-6 uppercase alphanumeric characters.")

    config = store.case_type_configs_by_type.get(case["case_type"])
    if config is None or not config.get("requires_biometrics"):
        raise err_invalid_state("This case type does not require biometrics.")

    # PRD §2.4 priority 7 — business-rule band lists ERR_BIOMETRICS_ALREADY_SCHEDULED
    # as its own priority check, so the uniqueness gate fires before any
    # general state precondition can reject a duplicate-attempt while the
    # case is already in BIOMETRICS_SCHEDULED.
    existing_scheduled = [
        b for b in store.biometrics.values()
        if b["case_id"] == case_id and b["status"] == "SCHEDULED"
    ]
    if existing_scheduled:
        raise err_biometrics_already_scheduled()

    # State precondition (PRD §3.4).
    if case["status"] != "FILED":
        raise err_invalid_state(f"Case is in {case['status']}; biometrics may only be scheduled from FILED.")

    # Lead-time gate (priority 11). PRD §3.4: "at least seven days from
    # the present moment" — inclusive boundary. Truncate the logical
    # clock to millisecond precision (matching the wire format clients
    # observe via /_clock and iso_now()), so a client that submits
    # logical_now + exactly 7 days lands on the boundary and is accepted.
    now = store.now()
    logical = store.clock.logical_now().replace(
        microsecond=(store.clock.logical_now().microsecond // 1000) * 1000,
    )
    if scheduled_at < logical + timedelta(days=7):
        raise err_biometrics_too_soon()

    with store.lock:
        entity = {
            "case_id": case_id,
            "scheduled_at": scheduled_at,
            "location_code": location_code,
            "status": "SCHEDULED",
            "reschedule_count": 0,
            "completed_at": None,
        }
        stamp_create(entity, now)
        store.biometrics[entity["id"]] = entity

        previous_status = case["status"]
        case["status"] = "BIOMETRICS_SCHEDULED"
        stamp_update(case, now)
        emit_case_event(case_id, "BIOMETRICS_SCHEDULED", g.role, now,
                        from_value=previous_status, to_value="BIOMETRICS_SCHEDULED")

    return success(serialize_biometrics(entity), 201)


# ────────────────────────────────────────────────────────────────────────────
# GET /biometrics/{id}
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/biometrics/<biometrics_id>")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def get_biometrics(biometrics_id: str):
    b = get_biometrics_or_404(biometrics_id)
    # Ownership: petitioner/beneficiary may only see biometrics on own cases.
    role = g.role
    uid = g.user_id
    if role in {"Petitioner", "Beneficiary"}:
        case = store.cases.get(b["case_id"])
        if case is None:
            from errors import err_not_found
            raise err_not_found("Parent case not found.")
        if role == "Petitioner" and case["petitioner_id"] != uid:
            from errors import err_forbidden
            raise err_forbidden("Petitioner may only view biometrics on own cases.")
        if role == "Beneficiary" and case["beneficiary_id"] != uid:
            from errors import err_forbidden
            raise err_forbidden("Beneficiary may only view biometrics on own cases.")
    return success(serialize_biometrics(b), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /biometrics/{id}/complete
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/biometrics/<biometrics_id>/complete")
@require_auth(["Officer"])
def complete_biometrics(biometrics_id: str):
    b = get_biometrics_or_404(biometrics_id)

    if b["status"] != "SCHEDULED":
        raise err_invalid_state(f"Biometrics is in {b['status']}; cannot complete.")

    now = store.now()
    if now < b["scheduled_at"]:
        raise err_invalid_state("Cannot complete biometrics before scheduled_at.")

    with store.lock:
        b["status"] = "COMPLETED"
        b["completed_at"] = now
        stamp_update(b, now)
        case = store.cases.get(b["case_id"])
        if case is not None and case["status"] == "BIOMETRICS_SCHEDULED":
            previous = case["status"]
            case["status"] = "BIOMETRICS_COMPLETED"
            stamp_update(case, now)
            emit_case_event(case["id"], "BIOMETRICS_COMPLETED", g.role, now,
                            from_value=previous, to_value="BIOMETRICS_COMPLETED")

    return success(serialize_biometrics(b), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /biometrics/{id}/no-show
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/biometrics/<biometrics_id>/no-show")
@require_auth(["Officer"])
def no_show_biometrics(biometrics_id: str):
    b = get_biometrics_or_404(biometrics_id)
    if b["status"] != "SCHEDULED":
        raise err_invalid_state(f"Biometrics is in {b['status']}; cannot mark NO_SHOW.")
    now = store.now()
    grace = b["scheduled_at"] + timedelta(hours=24)
    if now <= grace:
        raise err_invalid_state("NO_SHOW requires more than 24 hours past scheduled_at.")
    with store.lock:
        b["status"] = "NO_SHOW"
        stamp_update(b, now)
    return success(serialize_biometrics(b), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /biometrics/{id}/reschedule
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/biometrics/<biometrics_id>/reschedule")
@require_auth(["Officer"])
def reschedule_biometrics(biometrics_id: str):
    b = get_biometrics_or_404(biometrics_id)
    body = get_json()

    new_scheduled_at_str = require_string(body, "new_scheduled_at")
    new_scheduled_at = parse_iso_datetime(new_scheduled_at_str)
    if new_scheduled_at is None:
        raise err_validation("new_scheduled_at must be a valid ISO 8601 timestamp.")
    location_code = require_string(body, "location_code")
    if not is_valid_location_code(location_code):
        raise err_validation("location_code must be 4-6 uppercase alphanumeric characters.")

    if b["status"] not in {"SCHEDULED", "NO_SHOW"}:
        raise err_invalid_state(f"Biometrics is in {b['status']}; cannot reschedule.")

    # Priority order from PRD §2.4 / SCAFFOLD validations (priorities 11, 14, 15):
    #   11. biometrics too soon
    #   14. reschedule limit
    #   15. reschedule too late
    now = store.now()
    logical = store.clock.logical_now().replace(
        microsecond=(store.clock.logical_now().microsecond // 1000) * 1000,
    )
    if new_scheduled_at < logical + timedelta(days=7):
        raise err_biometrics_too_soon()
    if b["reschedule_count"] >= 3:
        raise err_biometrics_reschedule_limit()
    # Only enforce blackout for SCHEDULED rows; a NO_SHOW row's scheduled_at
    # is already in the past so the 24h rule does not apply (PRD §3.4 — the
    # NO_SHOW reschedule "follows the same count-increment rule and leaves
    # the prior NO_SHOW row untouched for audit").
    if b["status"] == "SCHEDULED":
        if now > b["scheduled_at"] - timedelta(hours=24):
            raise err_biometrics_reschedule_too_late()

    with store.lock:
        # The old row becomes RESCHEDULED only when starting from SCHEDULED;
        # NO_SHOW rows stay in NO_SHOW for audit (PRD §3.4).
        if b["status"] == "SCHEDULED":
            b["status"] = "RESCHEDULED"
            stamp_update(b, now)
        new_row = {
            "case_id": b["case_id"],
            "scheduled_at": new_scheduled_at,
            "location_code": location_code,
            "status": "SCHEDULED",
            "reschedule_count": b["reschedule_count"] + 1,
            "completed_at": None,
        }
        stamp_create(new_row, now)
        store.biometrics[new_row["id"]] = new_row

    return success(serialize_biometrics(new_row), 201)
