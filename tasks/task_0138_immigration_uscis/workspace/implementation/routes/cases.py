"""Case CRUD + state-machine trigger endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from config import CASE_TYPES, OFFICER_DENIAL_REASONS
from db import store
from errors import (
    err_forbidden,
    err_i485_missing_approved_i130,
    err_invalid_state,
    err_priority_date_not_current,
    err_referenced_not_found,
    err_validation,
)
from middleware import require_auth
from response import list_success, success
from services.calculations import case_completeness_score, mint_receipt_number
from services.case_engine import (
    cascade_i130_approval,
    cascade_i130_denial,
    emit_case_event,
    refresh_priority_date_status,
    stamp_create,
    stamp_update,
)
from services.serializers import (
    serialize_case,
    serialize_case_event,
)
from utils import date_iso

from routes._helpers import (
    enforce_case_ownership,
    get_case_or_404,
    get_json,
    parse_pagination,
    paginate_and_sort,
    require_enum,
    require_string,
)


bp = Blueprint("cases", __name__)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases — create a new case in DRAFT
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases")
@require_auth(["Petitioner", "Officer"])
def create_case():
    body = get_json()

    petitioner_id = require_string(body, "petitioner_id")
    beneficiary_id = require_string(body, "beneficiary_id")
    case_type = require_enum(body, "case_type", CASE_TYPES)
    linked_i130_case_id = body.get("linked_i130_case_id")
    if linked_i130_case_id is not None and not isinstance(linked_i130_case_id, str):
        raise err_validation("linked_i130_case_id must be a string when provided.")

    # Ownership: Petitioner can only create cases for own petitioner_id.
    if g.role == "Petitioner" and petitioner_id != g.user_id:
        raise err_forbidden("Petitioner may only create cases under own petitioner_id.")

    # FK existence (PRD §2.4 priority 5).
    if petitioner_id not in store.petitioners:
        raise err_referenced_not_found(f"Petitioner {petitioner_id} not found.")
    if beneficiary_id not in store.beneficiaries:
        raise err_referenced_not_found(f"Beneficiary {beneficiary_id} not found.")
    if linked_i130_case_id is not None and linked_i130_case_id not in store.cases:
        raise err_referenced_not_found(f"linked_i130_case_id {linked_i130_case_id} not found.")

    with store.lock:
        now = store.now()
        entity = {
            "petitioner_id": petitioner_id,
            "beneficiary_id": beneficiary_id,
            "case_type": case_type,
            "linked_i130_case_id": linked_i130_case_id,
            "receipt_number": None,
            "priority_date": None,
            "filing_date": None,
            "status": "DRAFT",
            "priority_date_status": "NOT_APPLICABLE",
            "rfe_deadline": None,
            "decision_at": None,
            "denial_reason": None,
        }
        stamp_create(entity, now)
        store.cases[entity["id"]] = entity

    return success(serialize_case(entity), 201)


# ────────────────────────────────────────────────────────────────────────────
# GET /cases/{case_id}
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/cases/<case_id>")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def get_case(case_id: str):
    case = get_case_or_404(case_id)
    enforce_case_ownership(case)
    return success(serialize_case(case), 200)


# ────────────────────────────────────────────────────────────────────────────
# GET /cases — list with filters
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/cases")
@require_auth(["Officer", "Supervisor"])
def list_cases():
    limit, offset = parse_pagination()

    status = request.args.get("status")
    case_type = request.args.get("case_type")
    petitioner_id = request.args.get("petitioner_id")
    beneficiary_id = request.args.get("beneficiary_id")
    priority_date_status = request.args.get("priority_date_status")

    rows = list(store.cases.values())

    def matches(c):
        if status and c["status"] != status:
            return False
        if case_type and c["case_type"] != case_type:
            return False
        if petitioner_id and c["petitioner_id"] != petitioner_id:
            return False
        if beneficiary_id and c["beneficiary_id"] != beneficiary_id:
            return False
        if priority_date_status and c["priority_date_status"] != priority_date_status:
            return False
        return True

    filtered = [c for c in rows if matches(c)]
    page, total = paginate_and_sort(filtered, limit, offset)
    return list_success([serialize_case(c) for c in page], limit, offset, total, 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/file — DRAFT → FILED
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/file")
@require_auth(["Petitioner"])
def file_case(case_id: str):
    case = get_case_or_404(case_id)
    enforce_case_ownership(case)

    if case["status"] != "DRAFT":
        raise err_invalid_state(f"Case is in {case['status']}; cannot file.")

    # Body-reference existence is rechecked here per PRD §2.4 priority 5.
    if case["petitioner_id"] not in store.petitioners:
        raise err_referenced_not_found("Petitioner does not exist.")
    beneficiary = store.beneficiaries.get(case["beneficiary_id"])
    if beneficiary is None:
        raise err_referenced_not_found("Beneficiary does not exist.")

    # I-485 specific check (priority 7).
    if case["case_type"] == "I-485":
        if beneficiary["preference_category"] != "IR":
            linked_id = case.get("linked_i130_case_id")
            linked = store.cases.get(linked_id) if linked_id else None
            if linked is None or linked.get("status") != "APPROVED":
                raise err_i485_missing_approved_i130()

    config = store.case_type_configs_by_type.get(case["case_type"])
    if config is None:
        raise err_invalid_state(f"No CaseTypeConfig configured for {case['case_type']}.")

    with store.lock:
        now = store.now()
        # Mint receipt number under the lock so the sequence is atomic.
        receipt_number = mint_receipt_number(config["receipt_prefix"], now)
        case["receipt_number"] = receipt_number
        case["filing_date"] = now

        # Priority-date pinning by case_type.
        if case["case_type"] == "I-130":
            case["priority_date"] = date_iso(now)
        elif case["case_type"] == "I-485":
            linked_id = case.get("linked_i130_case_id")
            linked = store.cases.get(linked_id) if linked_id else None
            if linked is not None and linked.get("priority_date") is not None:
                case["priority_date"] = linked["priority_date"]
            # If IR (no link required) priority_date stays null until link.

        previous_status = case["status"]
        case["status"] = "FILED"
        stamp_update(case, now)
        emit_case_event(
            case["id"], "STATUS_CHANGED", g.role, now,
            from_value=previous_status, to_value="FILED",
        )

        # Recompute priority_date_status if applicable.
        refresh_priority_date_status(case, g.role, now, emit_event=False)

    return success(serialize_case(case), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/ready-for-decision
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/ready-for-decision")
@require_auth(["Officer"])
def mark_ready_for_decision(case_id: str):
    case = get_case_or_404(case_id)

    config = store.case_type_configs_by_type.get(case["case_type"])
    if config is None or config.get("requires_interview"):
        raise err_invalid_state("ready-for-decision is only valid when CaseTypeConfig.requires_interview is false.")

    # PRD §3.6: "For non-I-485 cases... Once biometrics are complete (and no
    # RFE is outstanding), an officer manually advances the case to
    # READY_FOR_DECISION." When the case-type does not require biometrics,
    # biometrics are trivially "complete" so FILED is a valid source.
    requires_bio = bool(config.get("requires_biometrics"))
    valid_sources = {"BIOMETRICS_COMPLETED", "RFE_RESPONDED"}
    if not requires_bio:
        valid_sources.add("FILED")
    if case["status"] not in valid_sources:
        raise err_invalid_state(f"Case is in {case['status']}; cannot mark ready-for-decision.")

    # No OUTSTANDING RFE.
    outstanding_rfes = [r for r in store.rfes.values() if r["case_id"] == case_id and r["status"] == "OUTSTANDING"]
    if outstanding_rfes:
        raise err_invalid_state("An OUTSTANDING RFE prevents ready-for-decision.")

    with store.lock:
        now = store.now()
        previous = case["status"]
        case["status"] = "READY_FOR_DECISION"
        stamp_update(case, now)
        emit_case_event(case["id"], "STATUS_CHANGED", g.role, now, from_value=previous, to_value="READY_FOR_DECISION")

    return success(serialize_case(case), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/decide
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/decide")
@require_auth(["Officer", "Supervisor"])
def decide_case(case_id: str):
    case = get_case_or_404(case_id)
    body = get_json()

    decision = require_string(body, "decision")
    if decision not in {"APPROVE", "DENY"}:
        raise err_validation("decision must be APPROVE or DENY.")

    if case["status"] != "READY_FOR_DECISION":
        raise err_invalid_state(f"Case is in {case['status']}; cannot decide.")

    config = store.case_type_configs_by_type.get(case["case_type"])

    if decision == "APPROVE":
        # Priority-date currency gate (PRD §3.7).
        if config and config.get("requires_priority_date_current"):
            if case["priority_date_status"] != "CURRENT":
                raise err_priority_date_not_current()
        # Interview-outcome gate.
        if config and config.get("requires_interview"):
            completed_interviews = [
                i for i in store.interviews.values()
                if i["case_id"] == case_id and i["status"] == "COMPLETED"
            ]
            if not completed_interviews:
                raise err_invalid_state("APPROVE requires a completed interview.")
            # Use the most-recent completed interview.
            latest = max(completed_interviews, key=lambda i: i["updated_at"])
            if latest.get("outcome") == "RECOMMEND_DENIAL":
                raise err_invalid_state("Interview outcome RECOMMEND_DENIAL — must deny.")

        with store.lock:
            now = store.now()
            previous = case["status"]
            case["status"] = "APPROVED"
            case["decision_at"] = now
            stamp_update(case, now)
            emit_case_event(case["id"], "DECISION_RECORDED", g.role, now, from_value=previous, to_value="APPROVED")
            if case["case_type"] == "I-130":
                cascade_i130_approval(case, g.role, now)
        return success(serialize_case(case), 200)

    # DENY branch.
    denial_reason = body.get("denial_reason")
    if denial_reason not in OFFICER_DENIAL_REASONS:
        raise err_validation("denial_reason must be OFFICER_DENIAL or INELIGIBLE.")

    with store.lock:
        now = store.now()
        previous = case["status"]
        case["status"] = "DENIED"
        case["denial_reason"] = denial_reason
        case["decision_at"] = now
        stamp_update(case, now)
        emit_case_event(case["id"], "DECISION_RECORDED", g.role, now, from_value=previous, to_value="DENIED")
        if case["case_type"] == "I-130":
            cascade_i130_denial(case, g.role, now)

    return success(serialize_case(case), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/withdraw
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/withdraw")
@require_auth(["Petitioner"])
def withdraw_case(case_id: str):
    case = get_case_or_404(case_id)
    enforce_case_ownership(case)

    allowed_sources = {"DRAFT", "FILED", "BIOMETRICS_SCHEDULED"}
    if case["status"] not in allowed_sources:
        raise err_invalid_state(f"Case is in {case['status']}; cannot withdraw.")

    # FILED → WITHDRAWN: no COMPLETED biometrics.
    if case["status"] == "FILED":
        completed = [
            b for b in store.biometrics.values()
            if b["case_id"] == case_id and b["status"] == "COMPLETED"
        ]
        if completed:
            raise err_invalid_state("Cannot withdraw a FILED case with completed biometrics.")

    with store.lock:
        now = store.now()
        previous = case["status"]
        case["status"] = "WITHDRAWN"
        case["decision_at"] = now
        stamp_update(case, now)
        # Cancel any still-SCHEDULED biometrics on this case.
        for bio in store.biometrics.values():
            if bio["case_id"] == case_id and bio["status"] == "SCHEDULED":
                bio["status"] = "CANCELLED"
                stamp_update(bio, now)
        emit_case_event(case["id"], "STATUS_CHANGED", g.role, now, from_value=previous, to_value="WITHDRAWN")

    return success(serialize_case(case), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/refresh-priority-date
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/refresh-priority-date")
@require_auth(["Officer", "Supervisor"])
def refresh_priority_date(case_id: str):
    case = get_case_or_404(case_id)
    with store.lock:
        now = store.now()
        refresh_priority_date_status(case, g.role, now, emit_event=True)
    return success(serialize_case(case), 200)


# ────────────────────────────────────────────────────────────────────────────
# GET /cases/{case_id}/summary — live completeness score + counters
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/cases/<case_id>/summary")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def case_summary(case_id: str):
    case = get_case_or_404(case_id)
    enforce_case_ownership(case)

    biometrics_count = sum(1 for b in store.biometrics.values() if b["case_id"] == case_id)
    rfe_count = sum(1 for r in store.rfes.values() if r["case_id"] == case_id)
    interview_count = sum(1 for i in store.interviews.values() if i["case_id"] == case_id)
    event_count = sum(1 for e in store.case_events.values() if e["case_id"] == case_id)

    score = case_completeness_score(case)
    data = serialize_case(case)
    data["case_completeness_score"] = score
    data["biometrics_count"] = biometrics_count
    data["rfe_count"] = rfe_count
    data["interview_count"] = interview_count
    data["event_count"] = event_count
    return success(data, 200)


# ────────────────────────────────────────────────────────────────────────────
# GET /cases/{case_id}/events — audit feed
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/cases/<case_id>/events")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def list_case_events(case_id: str):
    case = get_case_or_404(case_id)
    enforce_case_ownership(case)
    limit, offset = parse_pagination()
    rows = [e for e in store.case_events.values() if e["case_id"] == case_id]
    page, total = paginate_and_sort(rows, limit, offset, sort_key=lambda e: e["occurred_at"])
    return list_success([serialize_case_event(e) for e in page], limit, offset, total, 200)
