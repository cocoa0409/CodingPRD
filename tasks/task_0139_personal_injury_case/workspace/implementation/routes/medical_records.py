"""MedicalRecordRequest endpoints (PRD §3.3)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from config import (
    ROLE_ATTORNEY,
    ROLE_MANAGING_PARTNER,
    ROLE_PARALEGAL,
    SOL_MIN_BUFFER_DAYS_FOR_RECORDS,
)
from db import store
from errors import raise_error
from middleware import require_auth
from response import list_success, no_content, success
from routes._helpers import (
    get_json_body,
    get_pagination_args,
    paginate,
    require_field,
)
from services.case_engine import (
    assert_case_not_closed,
    assert_case_sol_not_expired,
    check_version_match,
    get_case_or_404,
    now,
    recompute_damages_for_case,
    touch,
)
from services.serializers import case_to_dict, medical_request_to_dict
from utils import new_uuid, parse_iso_date


bp = Blueprint("medical_records", __name__)

ALL_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER]
RW_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY]


def _get_request_or_404(cid: str, rid: str) -> dict:
    get_case_or_404(cid)
    req = store.medical_requests.get(rid)
    if not req or req["case_id"] != cid:
        raise_error("ERR_NOT_FOUND", f"MedicalRecordRequest {rid} not found on case {cid}.")
    return req


def _has_active_or_open_request(cid: str) -> bool:
    for r in store.medical_requests.values():
        if r["case_id"] == cid and r["status"] in ("DRAFT", "SENT"):
            return True
    return False


# ── POST /pi-cases/{cid}/medical-record-requests ──────────────────────────


@bp.post("/pi-cases/<cid>/medical-record-requests")
@require_auth(RW_ROLES)
def create_request(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    provider_name = require_field(body, "provider_name")
    if not isinstance(provider_name, str):
        raise_error("ERR_VALIDATION", "provider_name must be a string.")

    dss_raw = require_field(body, "date_of_service_start")
    dse_raw = require_field(body, "date_of_service_end")
    dss = parse_iso_date(dss_raw)
    dse = parse_iso_date(dse_raw)
    if dss is None or dse is None:
        raise_error("ERR_DATE_OF_SERVICE_INVALID", "Dates of service must be valid YYYY-MM-DD.")

    incident = parse_iso_date(case_row["incident_date"])
    if dse < dss or dse < incident:
        raise_error(
            "ERR_DATE_OF_SERVICE_INVALID",
            "date_of_service_end must be on/after date_of_service_start AND on/after Case.incident_date.",
        )

    # SoL guard precedence: existence/state first.
    if case_row["status"] not in ("INTAKE", "RECORDS_PENDING"):
        raise_error(
            "ERR_INVALID_STATE",
            f"Cannot add medical-record request in case status {case_row['status']}.",
        )

    # Transitioning INTAKE → RECORDS_PENDING requires fee agreement + 30-day SoL buffer.
    if case_row["status"] == "INTAKE":
        if cid not in store.fee_agreement_by_case:
            raise_error(
                "ERR_INVALID_STATE",
                "ContingencyFeeAgreement must be recorded before opening medical-record work.",
            )
        # SoL must be more than 30 days into the future at the request moment.
        deadline_date = parse_iso_date(case_row["sol_deadline"])
        if deadline_date is None:
            raise_error("ERR_INVALID_STATE", "Case has no SoL deadline.")
        cutoff = (now() + timedelta(days=SOL_MIN_BUFFER_DAYS_FOR_RECORDS)).date()
        if deadline_date <= cutoff:
            raise_error(
                "ERR_STATUTE_OF_LIMITATIONS_EXPIRED",
                "Case.sol_deadline is within 30 days; cannot begin records work.",
            )

    with store.lock:
        row = {
            "id": new_uuid(),
            "case_id": cid,
            **{"created_at": now(), "updated_at": now(), "version": 1},
            "provider_name": provider_name,
            "date_of_service_start": dss_raw,
            "date_of_service_end": dse_raw,
            "status": "DRAFT",
            "sent_at": None,
            "received_at": None,
            "billed_amount_cents": 0,
        }
        store.medical_requests[row["id"]] = row

        if case_row["status"] == "INTAKE":
            case_row["status"] = "RECORDS_PENDING"
            touch(case_row)

    return success(medical_request_to_dict(row), 201)


# ── POST /pi-cases/{cid}/medical-record-requests/{rid}/send ──────────────


@bp.post("/pi-cases/<cid>/medical-record-requests/<rid>/send")
@require_auth(RW_ROLES)
def send_request(cid, rid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    req = _get_request_or_404(cid, rid)
    assert_case_not_closed(case_row)

    if req["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", f"Request must be DRAFT (was {req['status']}).")
    if case_row["status"] != "RECORDS_PENDING":
        raise_error(
            "ERR_INVALID_STATE",
            f"Case must be RECORDS_PENDING (was {case_row['status']}).",
        )

    check_version_match(req, body.get("version"))

    with store.lock:
        req["status"] = "SENT"
        req["sent_at"] = now()
        touch(req)

    return success(medical_request_to_dict(req), 200)


# ── PATCH /pi-cases/{cid}/medical-record-requests/{rid} ──────────────────


@bp.patch("/pi-cases/<cid>/medical-record-requests/<rid>")
@require_auth(RW_ROLES)
def patch_request(cid, rid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    req = _get_request_or_404(cid, rid)
    assert_case_not_closed(case_row)

    if "status" not in body:
        raise_error("ERR_VALIDATION", "status is required.")
    new_status = body["status"]
    if new_status not in ("RECEIVED", "REJECTED"):
        raise_error(
            "ERR_VALIDATION",
            "status must be one of {RECEIVED, REJECTED}.",
        )

    check_version_match(req, body.get("version"))

    if req["status"] != "SENT":
        raise_error("ERR_INVALID_STATE", f"Request must be SENT (was {req['status']}).")

    billed = body.get("billed_amount_cents")
    if new_status == "RECEIVED":
        if billed is None:
            raise_error("ERR_VALIDATION", "billed_amount_cents required for RECEIVED.")
        if not isinstance(billed, int) or isinstance(billed, bool) or billed < 0:
            raise_error("ERR_VALIDATION", "billed_amount_cents must be >= 0 integer.")

    with store.lock:
        if new_status == "RECEIVED":
            req["status"] = "RECEIVED"
            req["received_at"] = now()
            req["billed_amount_cents"] = int(billed)
            touch(req)
            recompute_damages_for_case(cid)
        else:  # REJECTED
            req["status"] = "REJECTED"
            touch(req)
            recompute_damages_for_case(cid)

        _maybe_advance_to_ready_for_demand(case_row)

    return success(medical_request_to_dict(req), 200)


def _maybe_advance_to_ready_for_demand(case_row: dict) -> None:
    """Cascade: if all requests are terminal, attorney assigned, and damages > 0,
    flip case from RECORDS_PENDING → READY_FOR_DEMAND.
    """
    if case_row["status"] != "RECORDS_PENDING":
        return
    case_id = case_row["id"]
    case_requests = [r for r in store.medical_requests.values() if r["case_id"] == case_id]
    if not case_requests:
        return
    if any(r["status"] in ("DRAFT", "SENT") for r in case_requests):
        return
    if not any(r["status"] == "RECEIVED" for r in case_requests):
        return
    if not case_row.get("assigned_attorney_id"):
        return
    damages_id = store.damages_by_case.get(case_id)
    if not damages_id:
        return
    damages = store.damages[damages_id]
    if int(damages.get("total_damages_cents", 0)) <= 0:
        return
    case_row["status"] = "READY_FOR_DEMAND"
    touch(case_row)


# ── GET /pi-cases/{cid}/medical-record-requests ──────────────────────────


@bp.get("/pi-cases/<cid>/medical-record-requests")
@require_auth(ALL_ROLES)
def list_requests(cid):
    get_case_or_404(cid)
    limit, offset = get_pagination_args()
    status_filter = request.args.get("status")

    rows = [r for r in store.medical_requests.values() if r["case_id"] == cid]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_success(
        [medical_request_to_dict(r) for r in page], limit, offset, total,
    )


# ── DELETE /pi-cases/{cid}/medical-record-requests/{rid} ─────────────────


@bp.delete("/pi-cases/<cid>/medical-record-requests/<rid>")
@require_auth(RW_ROLES)
def cancel_request(cid, rid):
    case_row = get_case_or_404(cid)
    req = _get_request_or_404(cid, rid)
    assert_case_not_closed(case_row)

    if req["status"] != "DRAFT":
        raise_error(
            "ERR_INVALID_STATE",
            f"Only DRAFT requests can be canceled (was {req['status']}).",
        )

    with store.lock:
        req["status"] = "CANCELED"
        touch(req)

    return no_content()
