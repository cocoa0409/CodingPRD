"""RFE endpoints — issue (under /cases/<id>/rfe), fetch, respond."""
from __future__ import annotations

from flask import Blueprint, g

from config import RFE_REASON_CODES
from db import store
from errors import (
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_rfe_already_outstanding,
    err_rfe_deadline_passed,
    err_validation,
)
from middleware import require_auth
from response import success
from services.calculations import rfe_response_deadline
from services.case_engine import emit_case_event, stamp_create, stamp_update
from services.serializers import serialize_rfe

from routes._helpers import (
    get_case_or_404,
    get_json,
    get_rfe_or_404,
    require_enum,
    require_string,
)


bp = Blueprint("rfe", __name__)


# ────────────────────────────────────────────────────────────────────────────
# POST /cases/{case_id}/rfe — issue
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/cases/<case_id>/rfe")
@require_auth(["Officer"])
def issue_rfe(case_id: str):
    case = get_case_or_404(case_id)
    body = get_json()

    reason_code = require_enum(body, "reason_code", RFE_REASON_CODES)
    officer_notes = require_string(body, "officer_notes", min_len=1, max_len=2000)

    config = store.case_type_configs_by_type.get(case["case_type"])

    # PRD §2.4 priority 7 — Outstanding-RFE uniqueness fires within the
    # business-rule band, BEFORE deeper state/source-state rejections, so
    # a double-issue while the case sits in RFE_ISSUED still returns the
    # named ERR_RFE_ALREADY_OUTSTANDING rather than a generic state error.
    outstanding = [r for r in store.rfes.values() if r["case_id"] == case_id and r["status"] == "OUTSTANDING"]
    if outstanding:
        raise err_rfe_already_outstanding()

    # Allowed source states: FILED (when no biometrics required),
    # BIOMETRICS_COMPLETED, INTERVIEW_SCHEDULED.
    if case["status"] == "FILED":
        if config and config.get("requires_biometrics"):
            raise err_invalid_state("Biometrics must be completed before issuing an RFE.")
    elif case["status"] not in {"BIOMETRICS_COMPLETED", "INTERVIEW_SCHEDULED"}:
        raise err_invalid_state(f"Case is in {case['status']}; cannot issue RFE.")

    if config is None:
        raise err_invalid_state(f"No CaseTypeConfig for {case['case_type']}.")
    window_days = config["rfe_response_window_days"]

    with store.lock:
        now = store.now()
        deadline_at = rfe_response_deadline(now, window_days)
        rfe = {
            "case_id": case_id,
            "issued_at": now,
            "deadline_at": deadline_at,
            "reason_code": reason_code,
            "officer_notes": officer_notes,
            "response_received_at": None,
            "status": "OUTSTANDING",
        }
        stamp_create(rfe, now)
        store.rfes[rfe["id"]] = rfe

        previous = case["status"]
        case["status"] = "RFE_ISSUED"
        case["rfe_deadline"] = deadline_at
        stamp_update(case, now)
        emit_case_event(case_id, "RFE_ISSUED", g.role, now, from_value=previous, to_value="RFE_ISSUED")

    return success(serialize_rfe(rfe), 201)


# ────────────────────────────────────────────────────────────────────────────
# GET /rfes/{rfe_id}
# ────────────────────────────────────────────────────────────────────────────


@bp.get("/rfes/<rfe_id>")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def get_rfe(rfe_id: str):
    r = get_rfe_or_404(rfe_id)
    role = g.role
    uid = g.user_id
    if role in {"Petitioner", "Beneficiary"}:
        case = store.cases.get(r["case_id"])
        if case is None:
            raise err_not_found("Parent case not found.")
        if role == "Petitioner" and case["petitioner_id"] != uid:
            raise err_forbidden("Petitioner may only view RFEs on own cases.")
        if role == "Beneficiary" and case["beneficiary_id"] != uid:
            raise err_forbidden("Beneficiary may only view RFEs on own cases.")
    return success(serialize_rfe(r), 200)


# ────────────────────────────────────────────────────────────────────────────
# POST /rfes/{rfe_id}/respond
# ────────────────────────────────────────────────────────────────────────────


@bp.post("/rfes/<rfe_id>/respond")
@require_auth(["Beneficiary", "Petitioner"])
def respond_rfe(rfe_id: str):
    r = get_rfe_or_404(rfe_id)
    case = store.cases.get(r["case_id"])
    if case is None:
        raise err_not_found("Parent case not found.")

    # Ownership: Petitioner must own the case; Beneficiary must be the case's beneficiary.
    role = g.role
    uid = g.user_id
    if role == "Petitioner" and case["petitioner_id"] != uid:
        raise err_forbidden("Petitioner may only respond on own cases.")
    if role == "Beneficiary" and case["beneficiary_id"] != uid:
        raise err_forbidden("Beneficiary may only respond on own cases.")

    # PRD §3.5: "A race between a beneficiary response and a clock-driven
    # expiry is resolved first-writer-wins on RFE.status: if expiry won,
    # the response is rejected with ERR_RFE_DEADLINE_PASSED and the loser
    # sees the RFE already in EXPIRED." Treat an EXPIRED RFE as a
    # deadline-passed rejection, not a generic invalid-state rejection.
    if r["status"] == "EXPIRED":
        raise err_rfe_deadline_passed()
    if r["status"] != "OUTSTANDING":
        raise err_invalid_state(f"RFE is in {r['status']}; cannot respond.")

    now = store.now()
    if now > r["deadline_at"]:
        raise err_rfe_deadline_passed()

    with store.lock:
        r["status"] = "RESPONDED"
        r["response_received_at"] = now
        stamp_update(r, now)
        previous = case["status"]
        case["status"] = "RFE_RESPONDED"
        case["rfe_deadline"] = None
        stamp_update(case, now)
        emit_case_event(case["id"], "RFE_RESPONDED", g.role, now, from_value=previous, to_value="RFE_RESPONDED")

    return success(serialize_rfe(r), 200)
