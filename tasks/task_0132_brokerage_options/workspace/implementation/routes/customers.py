"""Customer + KYC routes."""
from __future__ import annotations

import re

from flask import Blueprint

import config as cfg
from db import store
from errors import (
    err_invalid_state,
    err_kyc_age_ineligible,
    err_kyc_ineligible_country,
    err_validation,
    err_w9_name_mismatch,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    enforce_customer_owns_customer,
    get_customer_or_404,
    get_json,
    require_int,
    require_str,
)
from services.serializers import customer_view, kyc_submission_view
from utils import age_years, new_uuid, parse_iso_date


bp = Blueprint("customers", __name__)


SSN_LAST4_RE = re.compile(r"^\d{4}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


# ── POST /brokerage/customers ──────────────────────────────────────────────

@bp.post("/brokerage/customers")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_ADMIN])
def create_customer():
    body = get_json()

    legal_name = require_str(body, "legal_name", max_len=120)
    if not (1 <= len(legal_name.strip()) <= 120):
        raise err_validation("legal_name length out of range")

    dob_raw = require_str(body, "date_of_birth")
    dob = parse_iso_date(dob_raw)
    if dob is None:
        raise err_validation("date_of_birth must be a YYYY-MM-DD ISO date")

    ssn = require_str(body, "ssn_last4")
    if not SSN_LAST4_RE.match(ssn):
        raise err_validation("ssn_last4 must be exactly 4 digits")

    annual_income = require_int(body, "annual_income_cents", minimum=0)
    liquid_nw = require_int(body, "liquid_net_worth_cents", minimum=0)
    total_nw = require_int(body, "total_net_worth_cents", minimum=0)
    if total_nw < liquid_nw:
        raise err_validation("total_net_worth_cents must be >= liquid_net_worth_cents")
    yrs_exp = require_int(body, "years_options_experience", minimum=0)

    now = store.now()
    cid = new_uuid()
    customer = {
        "id": cid,
        "legal_name": legal_name,
        "date_of_birth": dob_raw.strip(),
        "ssn_last4": ssn,
        "annual_income_cents": annual_income,
        "liquid_net_worth_cents": liquid_nw,
        "total_net_worth_cents": total_nw,
        "years_options_experience": yrs_exp,
        "kyc_status": cfg.KYC_NOT_STARTED,
        "w9_collected": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock:
        store.customers[cid] = customer
    return success(customer_view(customer), 201)


# ── GET /brokerage/customers/{customer_id} ─────────────────────────────────

@bp.get("/brokerage/customers/<customer_id>")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE, cfg.ROLE_ADMIN])
def get_customer(customer_id: str):
    c = get_customer_or_404(customer_id)
    enforce_customer_owns_customer(c)
    return success(customer_view(c), 200)


# ── POST /brokerage/customers/{customer_id}/kyc ────────────────────────────

@bp.post("/brokerage/customers/<customer_id>/kyc")
@require_auth([cfg.ROLE_CUSTOMER])
def submit_kyc(customer_id: str):
    c = get_customer_or_404(customer_id)
    enforce_customer_owns_customer(c)

    body = get_json()

    # State precondition: kyc_status must be NOT_STARTED, OR most recent
    # KYCSubmission for this customer has status=REJECTED. Any other
    # state means there's an in-flight submission and is ERR_INVALID_STATE.
    latest = _latest_kyc_submission(customer_id)
    if c["kyc_status"] == cfg.KYC_NOT_STARTED:
        pass
    elif c["kyc_status"] == cfg.KYC_REJECTED and (latest is None or latest["status"] == cfg.KYC_SUB_REJECTED):
        pass
    else:
        raise err_invalid_state("KYC submission already in flight or already verified")

    # Field-level validation BEFORE business-safety checks so the field
    # shapes themselves are valid; missing/invalid fields → ERR_VALIDATION.
    gov_type = require_str(body, "government_id_type")
    if gov_type not in cfg.KYC_ID_TYPES:
        raise err_validation("government_id_type must be one of PASSPORT/DRIVERS_LICENSE/STATE_ID")
    gov_num = require_str(body, "government_id_number", max_len=40)
    if not (1 <= len(gov_num) <= 40):
        raise err_validation("government_id_number length out of range")
    address_line1 = require_str(body, "address_line1")
    address_country_raw = require_str(body, "address_country")
    if not COUNTRY_RE.match(address_country_raw):
        raise err_validation("address_country must be 2 uppercase letters")
    w9_signed = require_str(body, "w9_signed_name")

    # Business-safety order per PRD §2.9 / §3.1: country → age → W9.
    if address_country_raw != "US":
        raise err_kyc_ineligible_country()

    dob = parse_iso_date(c["date_of_birth"])
    today = store.now().date()
    if dob is None or age_years(dob, today) < 18:
        raise err_kyc_age_ineligible()

    if w9_signed.strip().casefold() != c["legal_name"].strip().casefold():
        raise err_w9_name_mismatch()

    now = store.now()
    sub_id = new_uuid()
    submission = {
        "id": sub_id,
        "customer_id": customer_id,
        "government_id_type": gov_type,
        "government_id_number": gov_num,
        "address_line1": address_line1,
        "address_country": address_country_raw,
        "w9_signed_name": w9_signed,
        "status": cfg.KYC_SUB_PENDING,
        "rejection_reason": None,
        "created_at": now,
    }

    with store.lock:
        store.kyc_submissions[sub_id] = submission
        c["kyc_status"] = cfg.KYC_PENDING
        c["updated_at"] = now
        c["version"] = c["version"] + 1
        # Advance any PENDING_KYC accounts for this customer → KYC_REVIEW.
        for a in store.accounts.values():
            if a["customer_id"] == customer_id and a["status"] == cfg.ACCT_STATUS_PENDING_KYC:
                a["status"] = cfg.ACCT_STATUS_KYC_REVIEW
                a["updated_at"] = now
                a["version"] = a["version"] + 1

    return success(kyc_submission_view(submission), 201)


# ── POST /brokerage/customers/{customer_id}/kyc/decision ───────────────────

@bp.post("/brokerage/customers/<customer_id>/kyc/decision")
@require_auth([cfg.ROLE_COMPLIANCE])
def decide_kyc(customer_id: str):
    c = get_customer_or_404(customer_id)
    body = get_json()
    decision = require_str(body, "decision")
    if decision not in ("VERIFY", "REJECT"):
        raise err_validation("decision must be VERIFY or REJECT")

    latest = _latest_kyc_submission(customer_id)
    if latest is None or latest["status"] != cfg.KYC_SUB_PENDING:
        raise err_invalid_state("no PENDING KYC submission")

    if decision == "VERIFY":
        if latest["address_country"] != "US":
            raise err_invalid_state("KYCSubmission.address_country must be US")
        now = store.now()
        with store.lock:
            latest["status"] = cfg.KYC_SUB_VERIFIED
            c["kyc_status"] = cfg.KYC_VERIFIED
            c["w9_collected"] = True
            c["updated_at"] = now
            c["version"] = c["version"] + 1
            # Account transitions: KYC_REVIEW → APPROVED, posture → OPEN.
            for a in store.accounts.values():
                if a["customer_id"] == customer_id and a["status"] == cfg.ACCT_STATUS_KYC_REVIEW:
                    a["status"] = cfg.ACCT_STATUS_APPROVED
                    a["trading_posture"] = cfg.POSTURE_OPEN
                    a["updated_at"] = now
                    a["version"] = a["version"] + 1
    else:
        reason = body.get("rejection_reason") or "rejected by compliance"
        now = store.now()
        with store.lock:
            latest["status"] = cfg.KYC_SUB_REJECTED
            latest["rejection_reason"] = reason
            c["kyc_status"] = cfg.KYC_REJECTED
            c["updated_at"] = now
            c["version"] = c["version"] + 1
            # Account reverts to PENDING_KYC so customer may resubmit.
            for a in store.accounts.values():
                if a["customer_id"] == customer_id and a["status"] == cfg.ACCT_STATUS_KYC_REVIEW:
                    a["status"] = cfg.ACCT_STATUS_PENDING_KYC
                    a["updated_at"] = now
                    a["version"] = a["version"] + 1

    return success(kyc_submission_view(latest), 200)


# ── helpers ────────────────────────────────────────────────────────────────


def _latest_kyc_submission(customer_id: str) -> dict | None:
    subs = [s for s in store.kyc_submissions.values() if s["customer_id"] == customer_id]
    if not subs:
        return None
    subs.sort(key=lambda s: s["created_at"], reverse=True)
    return subs[0]
