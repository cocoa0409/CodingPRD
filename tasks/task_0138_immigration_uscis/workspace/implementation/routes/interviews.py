"""Interview endpoints — schedule, fetch, complete, no-show."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from config import INTERVIEW_OUTCOMES
from db import store
from errors import (
    err_forbidden,
    err_interview_not_applicable,
    err_interview_too_soon,
    err_invalid_state,
    err_not_found,
    err_validation,
)
from middleware import require_auth
from response import success
from services.case_engine import emit_case_event, stamp_create, stamp_update
from services.serializers import serialize_interview
from utils import is_valid_field_office_code, parse_iso_datetime

from routes._helpers import (
    get_case_or_404,
    get_interview_or_404,
    get_json,
    require_enum,
    require_string,
)


bp = Blueprint("interviews", __name__)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/interview
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/interview")
@require_auth(["Officer"])
def schedule_interview(case_id: str):
    case = get_case_or_404(case_id)
    body = get_json()

    scheduled_at_str = require_string(body, "scheduled_at")
    scheduled_at = parse_iso_datetime(scheduled_at_str)
    if scheduled_at is None:
        raise err_validation("scheduled_at must be a valid ISO 8601 timestamp.")
    field_office_code = require_string(body, "field_office_code")
    if not is_valid_field_office_code(field_office_code):
        raise err_validation("field_office_code must be 3-5 uppercase letters.")

    # Interview-applicability gate (PRD §3.6, validation priority 16 in the
    # business-rule band). PRD §3.6 explicitly says "Scheduling an
    # interview against any other case type is rejected with
    # ERR_INTERVIEW_NOT_APPLICABLE", so this check fires before any
    # generic source-state rejection.
    if case["case_type"] != "I-485":
        raise err_interview_not_applicable()
    config = store.case_type_configs_by_type.get(case["case_type"])
    if config is None or not config.get("requires_interview"):
        raise err_interview_not_applicable()

    # State precondition: RFE_RESPONDED or BIOMETRICS_COMPLETED (no outstanding RFE).
    allowed_sources = {"RFE_RESPONDED", "BIOMETRICS_COMPLETED"}
    if case["status"] not in allowed_sources:
        raise err_invalid_state(f"Case is in {case['status']}; cannot schedule interview.")
    if case["status"] == "BIOMETRICS_COMPLETED":
        outstanding = [
            r for r in store.rfes.values()
            if r["case_id"] == case_id and r["status"] == "OUTSTANDING"
        ]
        if outstanding:
            raise err_invalid_state("Outstanding RFE prevents interview scheduling.")

    # Lead time gate (priority 12). PRD §3.6: "at least 14 days into the
    # future" — inclusive boundary. Truncate logical clock to ms precision
    # (matching the wire-format observable via /_clock + iso_now) so a
    # client submitting logical_now + 14 days exactly lands on the boundary.
    now = store.now()
    logical = store.clock.logical_now().replace(
        microsecond=(store.clock.logical_now().microsecond // 1000) * 1000,
    )
    if scheduled_at < logical + timedelta(days=14):
        raise err_interview_too_soon()

    with store.lock:
        entity = {
            "case_id": case_id,
            "scheduled_at": scheduled_at,
            "field_office_code": field_office_code,
            "status": "SCHEDULED",
            "outcome": None,
        }
        stamp_create(entity, now)
        store.interviews[entity["id"]] = entity
        previous = case["status"]
        case["status"] = "INTERVIEW_SCHEDULED"
        stamp_update(case, now)
        emit_case_event(case_id, "INTERVIEW_SCHEDULED", g.role, now,
                        from_value=previous, to_value="INTERVIEW_SCHEDULED")

    return success(serialize_interview(entity), 201)


# ────────────────────────────────────────────────────────────────────────────
# GET /interviews/{id}
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/interviews/<interview_id>")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def get_interview(interview_id: str):
    i = get_interview_or_404(interview_id)
    role = g.role
    uid = g.user_id
    if role in {"Petitioner", "Beneficiary"}:
        case = store.cases.get(i["case_id"])
        if case is None:
            raise err_not_found("Parent case not found.")
        if role == "Petitioner" and case["petitioner_id"] != uid:
            raise err_forbidden("Petitioner may only view interviews on own cases.")
        if role == "Beneficiary" and case["beneficiary_id"] != uid:
            raise err_forbidden("Beneficiary may only view interviews on own cases.")
    return success(serialize_interview(i), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /interviews/{id}/complete
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/interviews/<interview_id>/complete")
@require_auth(["Officer"])
def complete_interview(interview_id: str):
    i = get_interview_or_404(interview_id)
    body = get_json()
    outcome = require_enum(body, "outcome", INTERVIEW_OUTCOMES)

    if i["status"] != "SCHEDULED":
        raise err_invalid_state(f"Interview is in {i['status']}; cannot complete.")

    now = store.now()
    if now < i["scheduled_at"]:
        raise err_invalid_state("Cannot complete interview before scheduled_at.")

    with store.lock:
        i["status"] = "COMPLETED"
        i["outcome"] = outcome
        stamp_update(i, now)
        case = store.cases.get(i["case_id"])
        if case is not None and case["status"] == "INTERVIEW_SCHEDULED":
            previous = case["status"]
            case["status"] = "READY_FOR_DECISION"
            stamp_update(case, now)
            emit_case_event(case["id"], "STATUS_CHANGED", g.role, now,
                            from_value=previous, to_value="READY_FOR_DECISION")

    return success(serialize_interview(i), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /interviews/{id}/no-show
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/interviews/<interview_id>/no-show")
@require_auth(["Officer"])
def no_show_interview(interview_id: str):
    i = get_interview_or_404(interview_id)
    if i["status"] != "SCHEDULED":
        raise err_invalid_state(f"Interview is in {i['status']}; cannot mark NO_SHOW.")
    now = store.now()
    grace = i["scheduled_at"] + timedelta(hours=24)
    if now <= grace:
        raise err_invalid_state("NO_SHOW requires more than 24 hours past scheduled_at.")
    with store.lock:
        i["status"] = "NO_SHOW"
        stamp_update(i, now)
    return success(serialize_interview(i), 200)
