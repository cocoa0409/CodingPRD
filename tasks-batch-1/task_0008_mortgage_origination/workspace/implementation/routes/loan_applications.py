"""LoanApplication routes and the central state machine."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from flask import Blueprint, g, request

import db
import response
from errors import (
    ApiError,
    ERR_APPLICANT_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_CD_REDISCLOSE_REQUIRED,
    ERR_DTI_FRONTEND_TOO_HIGH,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SOD_VIOLATION,
    ERR_TRID_WAITING_PERIOD,
    ERR_UDAAP_BLOCKED,
)
from middleware import require_auth
from services import calculations
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
    sorted_by_created_at,
)
from services.lookup import (
    get_application_or_404,
    get_applicant_or_404,
)

bp = Blueprint("loan_applications", __name__)


LOAN_STATUSES = {
    "DRAFT",
    "PREQUALIFIED",
    "UNDER_REVIEW",
    "APPROVED",
    "CLEAR_TO_CLOSE",
    "CLOSED",
    "DENIED",
    "WITHDRAWN",
}
TERMINAL_STATUSES = {"CLOSED", "DENIED", "WITHDRAWN"}
LOAN_PURPOSES = {"PURCHASE", "REFINANCE"}
LOAN_TERMS = {180, 360}


def loan_to_dict(la: dict[str, Any]) -> dict[str, Any]:
    def _dec_to_float(v):
        if isinstance(v, Decimal):
            return float(v)
        return v

    return {
        "id": la["id"],
        "applicant_id": la["applicant_id"],
        "property_address": la["property_address"],
        "property_state_code": la["property_state_code"],
        "loan_purpose": la["loan_purpose"],
        "requested_loan_amount_cents": la["requested_loan_amount_cents"],
        "property_value_cents": la["property_value_cents"],
        "loan_term_months": la["loan_term_months"],
        "status": la["status"],
        "prequal_decision": la.get("prequal_decision"),
        "front_end_dti": _dec_to_float(la.get("front_end_dti")),
        "back_end_dti": _dec_to_float(la.get("back_end_dti")),
        "ltv_ratio": _dec_to_float(la.get("ltv_ratio")),
        "provisional_apr": _dec_to_float(la.get("provisional_apr")),
        "final_apr": _dec_to_float(la.get("final_apr")),
        "clear_to_close_at": la.get("clear_to_close_at"),
        "earliest_consummation_at": la.get("earliest_consummation_at"),
        "created_at": la["created_at"],
        "updated_at": la["updated_at"],
        "version": la["version"],
    }


# --------------------------------------------------------------------------- #
# CREATE / READ / LIST
# --------------------------------------------------------------------------- #
@bp.post("/loan-applications")
@require_auth(roles=["LoanOfficer"])
def create_loan_application():
    body = get_json_body()
    applicant_id = require_str(body, "applicant_id")
    if applicant_id not in db.applicants:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "applicant_id does not refer to a known applicant.")
    property_address = require_str(body, "property_address")
    property_state_code = require_str(body, "property_state_code")
    loan_purpose = require_enum(body, "loan_purpose", LOAN_PURPOSES)
    requested_loan_amount_cents = require_int(body, "requested_loan_amount_cents")
    property_value_cents = require_int(body, "property_value_cents")
    loan_term_months = require_int(body, "loan_term_months")

    if not (len(property_state_code) == 2 and property_state_code.isalpha() and property_state_code.upper() == property_state_code):
        raise ApiError(ERR_INVALID_REQUEST, "property_state_code must be a 2-letter uppercase USPS code.")
    if requested_loan_amount_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "requested_loan_amount_cents must be positive.")
    if property_value_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "property_value_cents must be positive.")
    if loan_term_months not in LOAN_TERMS:
        raise ApiError(ERR_INVALID_REQUEST, "loan_term_months must be 180 or 360.")

    with db.lock:
        la = {
            **new_common_fields(),
            "applicant_id": applicant_id,
            "property_address": property_address,
            "property_state_code": property_state_code,
            "loan_purpose": loan_purpose,
            "requested_loan_amount_cents": requested_loan_amount_cents,
            "property_value_cents": property_value_cents,
            "loan_term_months": loan_term_months,
            "status": "DRAFT",
            "prequal_decision": None,
            "front_end_dti": None,
            "back_end_dti": None,
            "ltv_ratio": None,
            "provisional_apr": None,
            "final_apr": None,
            "clear_to_close_at": None,
            "earliest_consummation_at": None,
        }
        db.loan_applications[la["id"]] = la
        db.loan_application_creator[la["id"]] = g.user_id
    return response.ok(loan_to_dict(la), status=201)


@bp.get("/loan-applications/<la_id>")
@require_auth(roles=["LoanOfficer", "Underwriter", "Closer", "ComplianceOfficer"])
def read_loan_application(la_id: str):
    la = get_application_or_404(la_id)
    return response.ok(loan_to_dict(la))


@bp.get("/loan-applications")
@require_auth(roles=["LoanOfficer", "Underwriter", "Closer", "ComplianceOfficer"])
def list_loan_applications():
    limit, offset = parse_pagination()
    applicant_id = request.args.get("applicant_id")
    status_filter = request.args.get("status")
    property_state_code = request.args.get("property_state_code")

    items = list(db.loan_applications.values())
    if applicant_id is not None:
        items = [x for x in items if x["applicant_id"] == applicant_id]
    if status_filter is not None:
        items = [x for x in items if x["status"] == status_filter]
    if property_state_code is not None:
        items = [x for x in items if x["property_state_code"] == property_state_code]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([loan_to_dict(x) for x in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# State transitions
# --------------------------------------------------------------------------- #
def _udaap_most_recent(application_id: str):
    """Return the most recent UDAAPCheck for the application (by created_at ASC, last wins)."""
    candidates = [u for u in db.udaap_checks.values() if u["application_id"] == application_id]
    if not candidates:
        return None
    candidates.sort(key=lambda u: (u["created_at"], u.get("_seq", 0), u["id"]))
    return candidates[-1]


def _active_lock(application_id: str):
    """Return ACTIVE rate lock for the app, treating lazily-past-expiry as EXPIRED."""
    now = db.utcnow()
    for lk in db.rate_locks.values():
        if lk["application_id"] != application_id:
            continue
        if lk["status"] != "ACTIVE":
            continue
        expires = db.parse_ts(lk["expires_at"])
        if now >= expires:
            continue
        return lk
    return None


def _expire_due_locks(application_id: str | None = None):
    """Materialize lazy ACTIVE->EXPIRED for any expired locks (scoped or global).

    This is invoked at the start of state-machine entrypoints so downstream checks
    consistently see EXPIRED. We bump version on each transition.
    """
    now = db.utcnow()
    for lk in db.rate_locks.values():
        if application_id is not None and lk["application_id"] != application_id:
            continue
        if lk["status"] != "ACTIVE":
            continue
        expires = db.parse_ts(lk["expires_at"])
        if now >= expires:
            lk["status"] = "EXPIRED"
            bump(lk)


# -------- prequalify --------
@bp.post("/loan-applications/<la_id>/prequalify")
@require_auth(roles=["LoanOfficer"])
def prequalify(la_id: str):
    la = get_application_or_404(la_id)
    with db.lock:
        if la["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Application is not in DRAFT.")
        applicant = get_applicant_or_404(la["applicant_id"])
        # Eligibility preconditions per state machine.
        if int(applicant["credit_score"]) < 580:
            raise ApiError(ERR_INVALID_STATE, "Applicant credit_score below 580.")
        if int(la["requested_loan_amount_cents"]) > 4_000_000_00:
            raise ApiError(ERR_INVALID_STATE, "Requested loan amount exceeds conforming cap.")

        # Compute DTI ratios.
        front, back = calculations.compute_dti(la, applicant)
        ltv = calculations.compute_ltv_provisional(la)

        # Validation priority 10: front-end ceiling fires before approve/deny branching.
        if front > Decimal("0.31"):
            la["front_end_dti"] = front
            la["back_end_dti"] = back
            la["ltv_ratio"] = ltv
            # Note: don't transition status; the validation is a hard fail prior to branching.
            raise ApiError(ERR_DTI_FRONTEND_TOO_HIGH, "front_end_dti exceeds 0.31.")

        la["front_end_dti"] = front
        la["back_end_dti"] = back
        la["ltv_ratio"] = ltv

        # Record the prequalifying LoanOfficer for SoD.
        db.loan_application_creator[la_id] = g.user_id

        approved = back <= Decimal("0.43") and ltv <= Decimal("0.95")
        if approved:
            la["prequal_decision"] = "APPROVED"
            la["status"] = "PREQUALIFIED"
        else:
            la["prequal_decision"] = "DENIED"
            la["status"] = "DENIED"
        bump(la)

    return response.ok(loan_to_dict(la))


# -------- submit-for-review --------
@bp.post("/loan-applications/<la_id>/submit-for-review")
@require_auth(roles=["LoanOfficer"])
def submit_for_review(la_id: str):
    la = get_application_or_404(la_id)
    with db.lock:
        if la["status"] != "PREQUALIFIED":
            raise ApiError(ERR_INVALID_STATE, "Application is not in PREQUALIFIED.")
        # Has at least one DELIVERED Disclosure of type LOAN_ESTIMATE.
        has_le_delivered = any(
            d["application_id"] == la_id
            and d["disclosure_type"] == "LOAN_ESTIMATE"
            and d["status"] in ("DELIVERED", "ACKNOWLEDGED")
            for d in db.disclosures.values()
        )
        if not has_le_delivered:
            raise ApiError(ERR_INVALID_STATE, "No DELIVERED LOAN_ESTIMATE on file.")
        # Has at least one ACTIVE RateLock (live).
        if _active_lock(la_id) is None:
            raise ApiError(ERR_INVALID_STATE, "No ACTIVE rate lock on file.")
        la["status"] = "UNDER_REVIEW"
        bump(la)
    return response.ok(loan_to_dict(la))


# -------- approve --------
@bp.post("/loan-applications/<la_id>/approve")
@require_auth(roles=["Underwriter"])
def approve(la_id: str):
    la = get_application_or_404(la_id)
    with db.lock:
        if la["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "Application is not in UNDER_REVIEW.")

        # ---- UDAAP gate (validation priority 8) ----
        most_recent_udaap = _udaap_most_recent(la_id)
        if most_recent_udaap is None or most_recent_udaap["review_outcome"] != "CLEARED":
            raise ApiError(ERR_UDAAP_BLOCKED, "Most recent UDAAP check is not CLEARED.")

        # ---- Other state preconditions (fall under ERR_INVALID_STATE) ----
        has_income = any(
            iv["application_id"] == la_id and iv["status"] == "ACCEPTED"
            for iv in db.income_verifications.values()
        )
        if not has_income:
            raise ApiError(ERR_INVALID_STATE, "No accepted income verification.")
        has_asset = any(
            av["application_id"] == la_id and av["status"] == "ACCEPTED"
            for av in db.asset_verifications.values()
        )
        if not has_asset:
            raise ApiError(ERR_INVALID_STATE, "No accepted asset verification.")
        appraisal_count = [
            ap for ap in db.appraisals.values()
            if ap["application_id"] == la_id and ap["status"] in ("COMPLETED", "RECONSIDERED")
        ]
        if len(appraisal_count) != 1:
            raise ApiError(
                ERR_INVALID_STATE,
                "Must have exactly one COMPLETED/RECONSIDERED appraisal.",
            )
        has_title = any(
            ts["application_id"] == la_id and ts["status"] in ("CLEAR", "CURED")
            for ts in db.title_searches.values()
        )
        if not has_title:
            raise ApiError(ERR_INVALID_STATE, "No CLEAR/CURED title search.")

        # ---- Segregation of Duties (validation priority 16) ----
        originator = db.loan_application_creator.get(la_id)
        if originator is not None and originator == g.user_id:
            raise ApiError(ERR_SOD_VIOLATION, "Underwriter must differ from originating loan officer.")

        la["status"] = "APPROVED"
        bump(la)
    return response.ok(loan_to_dict(la))


# -------- deny --------
@bp.post("/loan-applications/<la_id>/deny")
@require_auth(roles=["Underwriter"])
def deny(la_id: str):
    la = get_application_or_404(la_id)
    with db.lock:
        if la["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "Application is not in UNDER_REVIEW.")
        # Body has optional 'reason' (free-text); accept anything.
        get_json_body()
        la["status"] = "DENIED"
        bump(la)
        # Cancel any ACTIVE rate lock.
        _cancel_active_locks(la_id)
    return response.ok(loan_to_dict(la))


# -------- withdraw --------
@bp.post("/loan-applications/<la_id>/withdraw")
@require_auth(roles=["LoanOfficer"])
def withdraw(la_id: str):
    la = get_application_or_404(la_id)
    with db.lock:
        if la["status"] not in ("DRAFT", "PREQUALIFIED", "UNDER_REVIEW"):
            raise ApiError(ERR_INVALID_STATE, "Application not in a withdrawable state.")
        la["status"] = "WITHDRAWN"
        bump(la)
        _cancel_active_locks(la_id)
    return response.ok(loan_to_dict(la))


# -------- clear-to-close --------
@bp.post("/loan-applications/<la_id>/clear-to-close")
@require_auth(roles=["Underwriter"])
def clear_to_close(la_id: str):
    la = get_application_or_404(la_id)
    with db.lock:
        if la["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, "Application is not in APPROVED.")

        # Has at least one ACKNOWLEDGED CLOSING_DISCLOSURE.
        ack_cds = [
            d for d in db.disclosures.values()
            if d["application_id"] == la_id
            and d["disclosure_type"] == "CLOSING_DISCLOSURE"
            and d["status"] == "ACKNOWLEDGED"
        ]
        if not ack_cds:
            raise ApiError(ERR_INVALID_STATE, "No ACKNOWLEDGED closing disclosure on file.")

        # Has an ACTIVE rate lock with live expiry.
        lk = _active_lock(la_id)
        if lk is None:
            raise ApiError(ERR_INVALID_STATE, "No ACTIVE rate lock on file.")

        # CD Redisclose gate (validation priority 15): latest CLOSING_DISCLOSURE
        # (DELIVERED or ACKNOWLEDGED) by delivered_at DESC.
        latest_cd = _latest_cd_any_status(la_id)
        if latest_cd is not None and latest_cd.get("change_requires_redisclose"):
            # Need a fresh ACKNOWLEDGED CD with change_requires_redisclose=false.
            fresh_ack = any(
                d["application_id"] == la_id
                and d["disclosure_type"] == "CLOSING_DISCLOSURE"
                and d["status"] == "ACKNOWLEDGED"
                and not d.get("change_requires_redisclose", False)
                # Must be after the flagged one.
                and d["delivered_at"] > latest_cd["delivered_at"]
                for d in db.disclosures.values()
            )
            if not fresh_ack:
                raise ApiError(
                    ERR_CD_REDISCLOSE_REQUIRED,
                    "A fresh acknowledged closing disclosure is required.",
                )

        # Side effects.
        la["clear_to_close_at"] = db.fmt_ts(db.utcnow())
        la["earliest_consummation_at"] = calculations.trid_earliest_consummation(la_id)
        la["status"] = "CLEAR_TO_CLOSE"
        bump(la)
    return response.ok(loan_to_dict(la))


def _latest_cd_any_status(application_id: str):
    """Return the latest CD with status DELIVERED or ACKNOWLEDGED."""
    cds = [
        d for d in db.disclosures.values()
        if d["application_id"] == application_id
        and d["disclosure_type"] == "CLOSING_DISCLOSURE"
        and d["status"] in ("DELIVERED", "ACKNOWLEDGED")
    ]
    if not cds:
        return None
    cds.sort(key=lambda d: (d.get("delivered_at") or "", d["created_at"], d.get("_seq", 0)))
    return cds[-1]


# -------- close --------
@bp.post("/loan-applications/<la_id>/close")
@require_auth(roles=["Closer"])
def close(la_id: str):
    la = get_application_or_404(la_id)
    with db.lock:
        if la["status"] != "CLEAR_TO_CLOSE":
            raise ApiError(ERR_INVALID_STATE, "Application is not in CLEAR_TO_CLOSE.")
        # TRID waiting period.
        ec = la.get("earliest_consummation_at")
        if ec is None:
            raise ApiError(ERR_TRID_WAITING_PERIOD, "earliest_consummation_at not yet set.")
        if db.utcnow() < db.parse_ts(ec):
            raise ApiError(ERR_TRID_WAITING_PERIOD, "TRID waiting period not yet elapsed.")

        # ACTIVE rate lock still live.
        lk = _active_lock(la_id)
        if lk is None:
            raise ApiError(ERR_INVALID_STATE, "No ACTIVE rate lock at close.")

        la["status"] = "CLOSED"
        bump(la)
        # Supersede the active rate lock.
        lk["status"] = "SUPERSEDED"
        bump(lk)
    return response.ok(loan_to_dict(la))


# --------------------------------------------------------------------------- #
# Helpers shared with cascade
# --------------------------------------------------------------------------- #
def _cancel_active_locks(application_id: str) -> None:
    for lk in db.rate_locks.values():
        if lk["application_id"] == application_id and lk["status"] == "ACTIVE":
            lk["status"] = "CANCELLED"
            bump(lk)


def cascade_appraisal_ltv(la: dict[str, Any], new_ltv: Decimal) -> None:
    """Recompute LTV after appraisal mutation; if > 0.95 and app is non-terminal,
    auto-DENY the application and cancel any ACTIVE rate lock.

    Caller is responsible for incrementing the loan application's version once
    for the recomputation itself; this function adds an additional +1 if the
    auto-DENY hop fires.
    """
    la["ltv_ratio"] = new_ltv
    if new_ltv > Decimal("0.95") and la["status"] in ("PREQUALIFIED", "UNDER_REVIEW"):
        la["status"] = "DENIED"
        bump(la)  # extra +1 for the auto-deny hop
        _cancel_active_locks(la["id"])
