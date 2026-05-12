"""Letter of Credit drafting, lifecycle, amendments, ownership."""

from flask import g
from datetime import timedelta

import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_VERSION_CONFLICT,
    ERR_INVALID_STATE_TRANSITION,
    ERR_APPLICANT_SUSPENDED,
    ERR_BENEFICIARY_SUSPENDED,
    ERR_BANK_ROLE_MISMATCH,
    ERR_CONFIRMING_BANK_REQUIRED,
    ERR_EXPIRY_IN_PAST,
    ERR_SHIPMENT_AFTER_EXPIRY,
    ERR_SWIFT_NOT_DELIVERED,
    ERR_LC_HAS_DRAWINGS,
    ERR_LC_HAS_OPEN_PRESENTATIONS,
    ERR_LC_NOT_AMENDABLE,
    ERR_AMENDMENT_PENDING,
    ERR_AMENDMENT_VIOLATES_PRESENTATIONS,
    ERR_AMENDMENT_CONSENT_OUT_OF_ORDER,
    ERR_AMENDMENT_ALREADY_DECIDED,
)
from services import audit, swift


# ---------- Helpers ----------

REQUIRED_DOCS_ENUM = {
    "COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST",
    "INSURANCE_POLICY", "CERTIFICATE_OF_ORIGIN",
}
USANCE_ALLOWED = {30, 60, 90, 120, 180}
NON_TERMINAL_PRES = {"SUBMITTED", "UNDER_EXAMINATION", "EXAMINED_CLEAN",
                     "EXAMINED_DISCREPANT", "ACCEPTED_BY_APPLICANT", "REFUSED"}
OPEN_PRES_FOR_CANCEL = {"SUBMITTED", "UNDER_EXAMINATION", "EXAMINED_CLEAN",
                        "EXAMINED_DISCREPANT", "ACCEPTED_BY_APPLICANT"}


def _check_version(lc, payload):
    if payload and "version" in payload and payload["version"] is not None:
        if payload["version"] != lc.get("version"):
            raise_error(ERR_VERSION_CONFLICT, "version mismatch")


def _resolve_or_404(table, ref_id, label):
    if ref_id is None:
        return None
    row = db.get_by_id(table, ref_id)
    if row is None:
        raise_error(ERR_NOT_FOUND, f"{label} not found")
    return row


def _bank_or_404(bank_id, expected_role):
    bank = db.get_by_id("banks", bank_id)
    if bank is None:
        raise_error(ERR_NOT_FOUND, f"bank {bank_id} not found")
    if bank.get("bank_role") != expected_role:
        raise_error(ERR_BANK_ROLE_MISMATCH, f"bank_role {bank.get('bank_role')} != {expected_role}")
    return bank


def _compute_cap(amount, tolerance_pct):
    # floor((amount * (100 + tolerance_pct)) / 100), with tolerance carried as int or float
    # Convert tolerance_pct to int-or-float handling by multiplying by 100 to keep integer math
    # Spec: amount * (100 + tolerance_pct) / 100, integer floor
    # Implement using Decimal-equivalent integer math when tolerance_pct is integer; else float-safe.
    if tolerance_pct is None:
        tolerance_pct = 0
    # support fractional tolerance, but typical values are integers 0..10
    # Multiply by 100 in numerator, then divide
    num = amount * (100 + tolerance_pct)
    cap = int(num // 100)
    return cap


def _drawn_minor_units(lc_id):
    total = 0
    for s in db.find_many("payment_settlements", lc_id=lc_id):
        if s.get("status") in ("ACCEPTED", "PAID"):
            total += int(s.get("principal_minor_units", 0))
    return total


def recompute_available(lc):
    cap = _compute_cap(lc.get("amount_minor_units", 0), lc.get("tolerance_pct", 0))
    drawn = _drawn_minor_units(lc["id"])
    avail = max(0, cap - drawn)
    lc["drawn_amount_minor_units"] = drawn
    lc["available_amount_minor_units"] = avail
    return lc


# ---------- Public LC API ----------

def list_lcs(filters, limit, offset, role, user_id):
    """List LCs filtered by role-based ownership."""
    rows = db.all_rows("letters_of_credit")
    # Apply ownership filter for non-admin roles
    if role == "Applicant":
        rows = [r for r in rows if r.get("applicant_id") == user_id]
    elif role == "Beneficiary":
        rows = [r for r in rows if r.get("beneficiary_id") == user_id]
    elif role == "IssuingBank":
        rows = [r for r in rows if r.get("issuing_bank_id") == user_id]
    elif role == "AdvisingBank":
        rows = [r for r in rows if r.get("advising_bank_id") == user_id]
    elif role == "ConfirmingBank":
        rows = [r for r in rows if r.get("confirming_bank_id") == user_id]
    # Operator, Auditor see all

    if filters:
        for k, v in filters.items():
            if v is not None:
                rows = [r for r in rows if r.get(k) == v]

    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(rows)
    if offset:
        rows = rows[offset:]
    rows = rows[:limit]
    return rows, total


def get_lc(lc_id, role, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    _enforce_lc_visibility(lc, role, user_id)
    return lc


def _enforce_lc_visibility(lc, role, user_id):
    if role in ("Operator", "Auditor"):
        return
    if role == "Applicant" and lc.get("applicant_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant does not own this LC")
    if role == "Beneficiary" and lc.get("beneficiary_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Beneficiary does not own this LC")
    if role == "IssuingBank" and lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    if role == "AdvisingBank" and lc.get("advising_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "AdvisingBank does not own this LC")
    if role == "ConfirmingBank" and lc.get("confirming_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "ConfirmingBank does not own this LC")
    if role == "NegotiatingBank":
        # Negotiating bank can only see LCs where it has been involved through a settlement.
        for s in db.find_many("payment_settlements", lc_id=lc["id"]):
            if s.get("settlement_type") == "NEGOTIATION" and s.get("negotiating_bank_id") == user_id:
                return
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "NegotiatingBank not associated with this LC")


def create_draft(payload, role, user_id):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    # Required fields
    applicant_id = payload.get("applicant_id")
    beneficiary_id = payload.get("beneficiary_id")
    issuing_bank_id = payload.get("issuing_bank_id")
    advising_bank_id = payload.get("advising_bank_id")
    lc_type = payload.get("lc_type")
    currency = payload.get("currency")
    amount_minor_units = payload.get("amount_minor_units")
    latest_shipment_date = payload.get("latest_shipment_date")
    expiry_date = payload.get("expiry_date")
    required_documents = payload.get("required_documents")

    for key, val in [
        ("applicant_id", applicant_id),
        ("beneficiary_id", beneficiary_id),
        ("issuing_bank_id", issuing_bank_id),
        ("advising_bank_id", advising_bank_id),
        ("lc_type", lc_type),
        ("currency", currency),
        ("amount_minor_units", amount_minor_units),
        ("latest_shipment_date", latest_shipment_date),
        ("expiry_date", expiry_date),
        ("required_documents", required_documents),
    ]:
        if val is None:
            raise_error(ERR_INVALID_REQUEST, f"{key} required")

    if lc_type not in ("SIGHT", "USANCE"):
        raise_error(ERR_INVALID_REQUEST, "lc_type must be SIGHT or USANCE")

    if not isinstance(amount_minor_units, int) or isinstance(amount_minor_units, bool) or amount_minor_units <= 0:
        raise_error(ERR_INVALID_REQUEST, "amount_minor_units must be positive integer")

    tolerance_pct = payload.get("tolerance_pct", 0)
    if tolerance_pct is None:
        tolerance_pct = 0
    if not isinstance(tolerance_pct, (int, float)) or isinstance(tolerance_pct, bool):
        raise_error(ERR_INVALID_REQUEST, "tolerance_pct must be numeric")
    if tolerance_pct < 0 or tolerance_pct > 10:
        raise_error(ERR_INVALID_REQUEST, "tolerance_pct must be between 0 and 10")

    if not isinstance(currency, str) or len(currency) != 3:
        raise_error(ERR_INVALID_REQUEST, "currency must be ISO 4217 3-letter code")

    if not isinstance(required_documents, list) or not required_documents:
        raise_error(ERR_INVALID_REQUEST, "required_documents must be non-empty array")
    for d in required_documents:
        if d not in REQUIRED_DOCS_ENUM:
            raise_error(ERR_INVALID_REQUEST, f"invalid document_type {d}")
    # PRD: must contain COMMERCIAL_INVOICE and BILL_OF_LADING at minimum
    if "COMMERCIAL_INVOICE" not in required_documents or "BILL_OF_LADING" not in required_documents:
        raise_error(ERR_INVALID_REQUEST, "required_documents must include COMMERCIAL_INVOICE and BILL_OF_LADING")

    usance_tenor_days = payload.get("usance_tenor_days")
    if lc_type == "USANCE":
        if usance_tenor_days not in USANCE_ALLOWED:
            raise_error(ERR_INVALID_REQUEST, "usance_tenor_days must be one of 30,60,90,120,180")
    else:
        usance_tenor_days = None

    confirmation_required = bool(payload.get("confirmation_required", False))
    confirming_bank_id = payload.get("confirming_bank_id")

    presentation_period_days = payload.get("presentation_period_days", 21)
    if not isinstance(presentation_period_days, int) or presentation_period_days <= 0:
        raise_error(ERR_INVALID_REQUEST, "presentation_period_days must be positive integer")

    discrepancy_fee = payload.get("discrepancy_fee_minor_units", 7500)
    if not isinstance(discrepancy_fee, int) or discrepancy_fee < 0:
        raise_error(ERR_INVALID_REQUEST, "discrepancy_fee_minor_units must be non-negative integer")

    # Body FK existence (priority 4)
    applicant = db.get_by_id("applicants", applicant_id)
    if applicant is None:
        raise_error(ERR_NOT_FOUND, "applicant not found")
    beneficiary = db.get_by_id("beneficiaries", beneficiary_id)
    if beneficiary is None:
        raise_error(ERR_NOT_FOUND, "beneficiary not found")
    issuing_bank = db.get_by_id("banks", issuing_bank_id)
    if issuing_bank is None:
        raise_error(ERR_NOT_FOUND, "issuing bank not found")
    advising_bank = db.get_by_id("banks", advising_bank_id)
    if advising_bank is None:
        raise_error(ERR_NOT_FOUND, "advising bank not found")
    confirming_bank = None
    if confirming_bank_id:
        confirming_bank = db.get_by_id("banks", confirming_bank_id)
        if confirming_bank is None:
            raise_error(ERR_NOT_FOUND, "confirming bank not found")

    # Applicant ownership: only the acting applicant may create LC for itself.
    if role == "Applicant" and applicant_id != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant can only create LC for itself")

    # bank role-vs-slot
    if issuing_bank.get("bank_role") != "ISSUING":
        raise_error(ERR_BANK_ROLE_MISMATCH, "issuing_bank must have bank_role=ISSUING")
    if advising_bank.get("bank_role") != "ADVISING":
        raise_error(ERR_BANK_ROLE_MISMATCH, "advising_bank must have bank_role=ADVISING")
    if confirming_bank is not None and confirming_bank.get("bank_role") != "CONFIRMING":
        raise_error(ERR_BANK_ROLE_MISMATCH, "confirming_bank must have bank_role=CONFIRMING")

    # confirmation consistency at CREATION (also re-checked at submit)
    if confirmation_required and not confirming_bank_id:
        raise_error(ERR_CONFIRMING_BANK_REQUIRED, "confirmation_required=true requires confirming_bank_id")
    if confirming_bank_id and not confirmation_required:
        raise_error(ERR_CONFIRMING_BANK_REQUIRED, "confirming_bank_id requires confirmation_required=true")

    cap = _compute_cap(amount_minor_units, tolerance_pct)

    record = {
        "lc_number": None,
        "applicant_id": applicant_id,
        "beneficiary_id": beneficiary_id,
        "issuing_bank_id": issuing_bank_id,
        "advising_bank_id": advising_bank_id,
        "confirming_bank_id": confirming_bank_id,
        "lc_type": lc_type,
        "usance_tenor_days": usance_tenor_days,
        "currency": currency,
        "amount_minor_units": amount_minor_units,
        "tolerance_pct": tolerance_pct,
        "drawn_amount_minor_units": 0,
        "available_amount_minor_units": cap,
        "latest_shipment_date": latest_shipment_date,
        "presentation_period_days": presentation_period_days,
        "expiry_date": expiry_date,
        "confirmation_required": confirmation_required,
        "required_documents": list(required_documents),
        "lifecycle_status": "DRAFT",
        "amendment_consent_status": "NONE",
        "confirmation_status": "NOT_REQUIRED",
        "cancelled_reason": None,
        "discrepancy_fee_minor_units": discrepancy_fee,
    }
    lc = db.insert("letters_of_credit", record)

    audit.append("lc.create", "LC", lc["id"], lc_id=lc["id"],
                 before_state=None, after_state="DRAFT", payload=payload)
    return lc


def submit(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("applicant_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant does not own this LC")
    _check_version(lc, payload)
    if lc["lifecycle_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "LC not in DRAFT")

    # priority 7+: validate
    applicant = db.get_by_id("applicants", lc["applicant_id"])
    if applicant is None:
        raise_error(ERR_NOT_FOUND, "applicant not found")
    if applicant.get("status") != "ACTIVE":
        raise_error(ERR_APPLICANT_SUSPENDED, "applicant suspended")
    beneficiary = db.get_by_id("beneficiaries", lc["beneficiary_id"])
    if beneficiary is None:
        raise_error(ERR_NOT_FOUND, "beneficiary not found")
    if beneficiary.get("status") != "ACTIVE":
        raise_error(ERR_BENEFICIARY_SUSPENDED, "beneficiary suspended")

    # required_documents check (already enforced at create, but spec lists at submit)
    rd = lc.get("required_documents") or []
    if "COMMERCIAL_INVOICE" not in rd or "BILL_OF_LADING" not in rd:
        raise_error(ERR_INVALID_REQUEST, "required_documents must include COMMERCIAL_INVOICE and BILL_OF_LADING")

    if lc["lc_type"] == "USANCE" and lc.get("usance_tenor_days") not in USANCE_ALLOWED:
        raise_error(ERR_INVALID_REQUEST, "usance_tenor_days invalid")

    if lc.get("confirmation_required") and not lc.get("confirming_bank_id"):
        raise_error(ERR_CONFIRMING_BANK_REQUIRED, "confirmation_required without confirming_bank_id")

    # temporal checks
    expiry_dt = db.parse_dt(lc["expiry_date"])
    ship_dt = db.parse_dt(lc["latest_shipment_date"])
    if expiry_dt is None or ship_dt is None:
        raise_error(ERR_INVALID_REQUEST, "expiry_date and latest_shipment_date must be valid ISO 8601")
    if expiry_dt <= db.now():
        raise_error(ERR_EXPIRY_IN_PAST, "expiry_date in past")
    if ship_dt > expiry_dt:
        raise_error(ERR_SHIPMENT_AFTER_EXPIRY, "latest_shipment_date after expiry_date")

    db.update("letters_of_credit", lc_id, {"lifecycle_status": "UNDER_REVIEW"})
    audit.append("lc.submit", "LC", lc_id, lc_id=lc_id,
                 before_state="DRAFT", after_state="UNDER_REVIEW", payload=payload)
    return db.get_by_id("letters_of_credit", lc_id)


def return_to_applicant(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(lc, payload)
    if lc["lifecycle_status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION, "LC not in UNDER_REVIEW")
    db.update("letters_of_credit", lc_id, {"lifecycle_status": "DRAFT"})
    audit.append("lc.return_to_applicant", "LC", lc_id, lc_id=lc_id,
                 before_state="UNDER_REVIEW", after_state="DRAFT", payload=payload)
    return db.get_by_id("letters_of_credit", lc_id)


def issue(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(lc, payload)

    if lc["lifecycle_status"] == "ISSUED":
        # Idempotent re-issue: return existing row with same lc_number; do not emit duplicate MT700.
        # SwiftMessage emit() is itself idempotent on (subject_type, subject_id, message_type)
        return lc

    if lc["lifecycle_status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION, "LC not in UNDER_REVIEW")

    updates = {"lifecycle_status": "ISSUED"}
    if not lc.get("lc_number"):
        updates["lc_number"] = db.next_lc_number()
    if lc.get("confirmation_required"):
        updates["confirmation_status"] = "PENDING"
    else:
        updates["confirmation_status"] = "NOT_REQUIRED"
    db.update("letters_of_credit", lc_id, updates)
    lc = db.get_by_id("letters_of_credit", lc_id)

    # Emit MT700
    issuing = db.get_by_id("banks", lc["issuing_bank_id"]) or {}
    advising = db.get_by_id("banks", lc["advising_bank_id"]) or {}
    swift.emit(
        "MT700", "LC", lc["id"], lc["id"],
        sender_bic=issuing.get("swift_bic", ""),
        receiver_bic=advising.get("swift_bic", ""),
        payload={"lc_number": lc["lc_number"], "amount_minor_units": lc["amount_minor_units"],
                 "currency": lc["currency"], "expiry_date": lc["expiry_date"]},
    )

    audit.append("lc.issue", "LC", lc_id, lc_id=lc_id,
                 before_state="UNDER_REVIEW", after_state="ISSUED", payload=payload)
    return db.get_by_id("letters_of_credit", lc_id)


def advise(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("advising_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "AdvisingBank does not own this LC")
    _check_version(lc, payload)
    if lc["lifecycle_status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "LC not in ISSUED")
    # MT700 prerequisite
    mt700 = None
    for m in db.find_many("swift_messages", lc_id=lc["id"], message_type="MT700"):
        mt700 = m
        break
    if mt700 is None:
        raise_error(ERR_SWIFT_NOT_DELIVERED, "MT700 not yet delivered")

    downstream_bic = (payload or {}).get("downstream_advising_bank_bic")
    if downstream_bic:
        advising = db.get_by_id("banks", lc["advising_bank_id"]) or {}
        swift.emit(
            "MT710", "LC", lc["id"], lc["id"],
            sender_bic=advising.get("swift_bic", ""),
            receiver_bic=downstream_bic,
            payload={"downstream_advising_bank_bic": downstream_bic, "lc_number": lc.get("lc_number")},
        )

    new_status = "ADVISED"
    # Auto-transition to ACTIVE if no confirmation required
    if not lc.get("confirmation_required"):
        new_status = "ACTIVE"
    db.update("letters_of_credit", lc_id, {"lifecycle_status": new_status})
    audit.append("lc.advise", "LC", lc_id, lc_id=lc_id,
                 before_state="ISSUED", after_state=new_status, payload=payload)
    return db.get_by_id("letters_of_credit", lc_id)


def confirm(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("confirming_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "ConfirmingBank does not own this LC")
    _check_version(lc, payload)
    if not lc.get("confirmation_required"):
        raise_error(ERR_INVALID_STATE_TRANSITION, "LC has no confirmation requirement")
    if lc.get("confirmation_status") not in ("PENDING",):
        raise_error(ERR_INVALID_STATE_TRANSITION, f"confirmation_status={lc.get('confirmation_status')}")

    updates = {"confirmation_status": "CONFIRMED"}
    if lc["lifecycle_status"] == "ADVISED":
        updates["lifecycle_status"] = "ACTIVE"
    db.update("letters_of_credit", lc_id, updates)
    audit.append("lc.confirm", "LC", lc_id, lc_id=lc_id,
                 before_state=lc["lifecycle_status"], after_state=updates.get("lifecycle_status", lc["lifecycle_status"]),
                 payload=payload)
    return db.get_by_id("letters_of_credit", lc_id)


def cancel(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(lc, payload)

    if lc["lifecycle_status"] not in ("ISSUED", "ADVISED", "ACTIVE"):
        raise_error(ERR_INVALID_STATE_TRANSITION, "LC not cancellable from current state")

    if lc.get("drawn_amount_minor_units", 0) > 0:
        raise_error(ERR_LC_HAS_DRAWINGS, "LC has drawings")

    for p in db.find_many("presentations", lc_id=lc_id):
        if p.get("status") in OPEN_PRES_FOR_CANCEL:
            raise_error(ERR_LC_HAS_OPEN_PRESENTATIONS, "LC has open presentations")

    for a in db.find_many("lc_amendments", lc_id=lc_id):
        if a.get("status") == "PENDING":
            raise_error(ERR_AMENDMENT_PENDING, "LC has pending amendment")

    cancelled_reason = (payload or {}).get("cancelled_reason")
    if not isinstance(cancelled_reason, str) or not cancelled_reason.strip():
        raise_error(ERR_INVALID_REQUEST, "cancelled_reason required")

    db.update("letters_of_credit", lc_id, {
        "lifecycle_status": "CANCELLED",
        "cancelled_reason": cancelled_reason,
    })
    audit.append("lc.cancel", "LC", lc_id, lc_id=lc_id,
                 before_state=lc["lifecycle_status"], after_state="CANCELLED", payload=payload)
    return db.get_by_id("letters_of_credit", lc_id)


# ---------- Amendments ----------

ALLOWED_AMENDMENT_FIELDS = {"amount_minor_units", "expiry_date", "latest_shipment_date",
                            "tolerance_pct", "required_documents"}


def initiate_amendment(lc_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")

    if lc["lifecycle_status"] not in ("ISSUED", "ADVISED", "ACTIVE"):
        raise_error(ERR_LC_NOT_AMENDABLE, "LC not amendable")

    if lc.get("amendment_consent_status") != "NONE":
        raise_error(ERR_AMENDMENT_PENDING, "another amendment pending")

    # also check by row scan in case status got out of sync
    for a in db.find_many("lc_amendments", lc_id=lc_id):
        if a.get("status") == "PENDING":
            raise_error(ERR_AMENDMENT_PENDING, "another amendment pending")

    changes = (payload or {}).get("changes")
    if not isinstance(changes, dict) or not changes:
        raise_error(ERR_INVALID_REQUEST, "changes object required with at least one field")

    for k in changes.keys():
        if k not in ALLOWED_AMENDMENT_FIELDS:
            raise_error(ERR_INVALID_REQUEST, f"changes.{k} not amendable")

    # Validate field types
    if "required_documents" in changes:
        rd = changes["required_documents"]
        if not isinstance(rd, list) or not rd:
            raise_error(ERR_INVALID_REQUEST, "changes.required_documents must be non-empty array")
        for d in rd:
            if d not in REQUIRED_DOCS_ENUM:
                raise_error(ERR_INVALID_REQUEST, f"invalid document_type {d}")
        if "COMMERCIAL_INVOICE" not in rd or "BILL_OF_LADING" not in rd:
            raise_error(ERR_INVALID_REQUEST, "required_documents must include COMMERCIAL_INVOICE and BILL_OF_LADING")
    if "amount_minor_units" in changes:
        a = changes["amount_minor_units"]
        if not isinstance(a, int) or isinstance(a, bool) or a <= 0:
            raise_error(ERR_INVALID_REQUEST, "amount_minor_units must be positive integer")
    if "tolerance_pct" in changes:
        t = changes["tolerance_pct"]
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0 or t > 10:
            raise_error(ERR_INVALID_REQUEST, "tolerance_pct must be between 0 and 10")

    seq = db.next_amendment_seq(lc_id)
    confirming_present = bool(lc.get("confirming_bank_id"))
    amendment = db.insert("lc_amendments", {
        "lc_id": lc_id,
        "amendment_seq": seq,
        "changes": dict(changes),
        "applicant_consent": "PENDING",
        "beneficiary_consent": "PENDING",
        "confirming_bank_consent": "PENDING" if confirming_present else "NOT_REQUIRED",
        "status": "PENDING",
        "rejected_by_role": None,
        "applied_at": None,
    })

    db.update("letters_of_credit", lc_id, {"amendment_consent_status": "PENDING_APPLICANT"})

    issuing = db.get_by_id("banks", lc["issuing_bank_id"]) or {}
    advising = db.get_by_id("banks", lc["advising_bank_id"]) or {}
    swift.emit(
        "MT707", "AMENDMENT", amendment["id"], lc_id,
        sender_bic=issuing.get("swift_bic", ""),
        receiver_bic=advising.get("swift_bic", ""),
        payload={"amendment_seq": seq, "changes": dict(changes)},
    )

    audit.append("amendment.initiate", "AMENDMENT", amendment["id"], lc_id=lc_id,
                 before_state=None, after_state="PENDING", payload=payload)
    return amendment


def get_amendment(lc_id, amendment_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    a = db.get_by_id("lc_amendments", amendment_id)
    if a is None or a.get("lc_id") != lc_id:
        raise_error(ERR_NOT_FOUND, "amendment not found")
    return a


def list_amendments(lc_id, filters, limit, offset):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    use_filters = {"lc_id": lc_id}
    if filters and filters.get("status"):
        use_filters["status"] = filters["status"]
    rows, total = db.list_table("lc_amendments", filters=use_filters,
                                sort_keys=("created_at", "id"), limit=limit, offset=offset)
    return rows, total


def withdraw_amendment(lc_id, amendment_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    a = db.get_by_id("lc_amendments", amendment_id)
    if a is None or a.get("lc_id") != lc_id:
        raise_error(ERR_NOT_FOUND, "amendment not found")
    _check_version(a, payload)

    if a.get("status") != "PENDING":
        raise_error(ERR_AMENDMENT_ALREADY_DECIDED, "amendment already decided")
    if a.get("applicant_consent") != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION, "cannot withdraw after applicant consented")

    db.update("lc_amendments", amendment_id, {"status": "WITHDRAWN"})
    db.update("letters_of_credit", lc_id, {"amendment_consent_status": "NONE"})
    audit.append("amendment.withdraw", "AMENDMENT", amendment_id, lc_id=lc_id,
                 before_state="PENDING", after_state="WITHDRAWN", payload=payload)
    return db.get_by_id("lc_amendments", amendment_id)


def _decision_str(payload):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")
    d = payload.get("decision")
    if d not in ("CONSENTED", "REJECTED"):
        raise_error(ERR_INVALID_REQUEST, "decision must be CONSENTED or REJECTED")
    return d


def applicant_consent(lc_id, amendment_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("applicant_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Applicant does not own this LC")
    a = db.get_by_id("lc_amendments", amendment_id)
    if a is None or a.get("lc_id") != lc_id:
        raise_error(ERR_NOT_FOUND, "amendment not found")
    _check_version(a, payload)

    if a.get("status") != "PENDING":
        raise_error(ERR_AMENDMENT_ALREADY_DECIDED, "amendment already decided")

    if a.get("applicant_consent") != "PENDING":
        raise_error(ERR_AMENDMENT_ALREADY_DECIDED, "applicant already decided")

    decision = _decision_str(payload)

    if decision == "REJECTED":
        db.update("lc_amendments", amendment_id, {
            "applicant_consent": "REJECTED",
            "status": "REJECTED",
            "rejected_by_role": "APPLICANT",
        })
        db.update("letters_of_credit", lc_id, {"amendment_consent_status": "NONE"})
        audit.append("amendment.applicant_consent", "AMENDMENT", amendment_id, lc_id=lc_id,
                     before_state="PENDING_APPLICANT", after_state="REJECTED", payload=payload)
        return db.get_by_id("lc_amendments", amendment_id)

    # CONSENTED — moves cycle to PENDING_BENEFICIARY (always)
    db.update("lc_amendments", amendment_id, {"applicant_consent": "CONSENTED"})
    db.update("letters_of_credit", lc_id, {"amendment_consent_status": "PENDING_BENEFICIARY"})
    audit.append("amendment.applicant_consent", "AMENDMENT", amendment_id, lc_id=lc_id,
                 before_state="PENDING_APPLICANT", after_state="PENDING_BENEFICIARY", payload=payload)
    return db.get_by_id("lc_amendments", amendment_id)


def beneficiary_consent(lc_id, amendment_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("beneficiary_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "Beneficiary does not own this LC")
    a = db.get_by_id("lc_amendments", amendment_id)
    if a is None or a.get("lc_id") != lc_id:
        raise_error(ERR_NOT_FOUND, "amendment not found")
    _check_version(a, payload)

    if a.get("status") != "PENDING":
        raise_error(ERR_AMENDMENT_ALREADY_DECIDED, "amendment already decided")

    if a.get("applicant_consent") != "CONSENTED":
        raise_error(ERR_AMENDMENT_CONSENT_OUT_OF_ORDER, "applicant has not yet consented")

    if a.get("beneficiary_consent") != "PENDING":
        raise_error(ERR_AMENDMENT_ALREADY_DECIDED, "beneficiary already decided")

    decision = _decision_str(payload)
    if decision == "REJECTED":
        db.update("lc_amendments", amendment_id, {
            "beneficiary_consent": "REJECTED",
            "status": "REJECTED",
            "rejected_by_role": "BENEFICIARY",
        })
        db.update("letters_of_credit", lc_id, {"amendment_consent_status": "NONE"})
        audit.append("amendment.beneficiary_consent", "AMENDMENT", amendment_id, lc_id=lc_id,
                     before_state="PENDING_BENEFICIARY", after_state="REJECTED", payload=payload)
        return db.get_by_id("lc_amendments", amendment_id)

    # CONSENTED
    if lc.get("confirming_bank_id"):
        db.update("lc_amendments", amendment_id, {"beneficiary_consent": "CONSENTED"})
        db.update("letters_of_credit", lc_id, {"amendment_consent_status": "PENDING_CONFIRMING_BANK"})
        audit.append("amendment.beneficiary_consent", "AMENDMENT", amendment_id, lc_id=lc_id,
                     before_state="PENDING_BENEFICIARY", after_state="PENDING_CONFIRMING_BANK", payload=payload)
        return db.get_by_id("lc_amendments", amendment_id)

    # No confirming bank — finalize amendment now
    _validate_changes_against_presentations(lc, a.get("changes") or {})
    db.update("lc_amendments", amendment_id, {"beneficiary_consent": "CONSENTED"})
    _apply_amendment(lc, amendment_id)
    audit.append("amendment.beneficiary_consent", "AMENDMENT", amendment_id, lc_id=lc_id,
                 before_state="PENDING_BENEFICIARY", after_state="CONSENTED", payload=payload)
    return db.get_by_id("lc_amendments", amendment_id)


def confirming_bank_consent(lc_id, amendment_id, payload, user_id):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    if lc.get("confirming_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "ConfirmingBank does not own this LC")
    a = db.get_by_id("lc_amendments", amendment_id)
    if a is None or a.get("lc_id") != lc_id:
        raise_error(ERR_NOT_FOUND, "amendment not found")
    _check_version(a, payload)

    if a.get("status") != "PENDING":
        raise_error(ERR_AMENDMENT_ALREADY_DECIDED, "amendment already decided")

    if a.get("applicant_consent") != "CONSENTED" or a.get("beneficiary_consent") != "CONSENTED":
        raise_error(ERR_AMENDMENT_CONSENT_OUT_OF_ORDER, "earlier consents missing")

    if a.get("confirming_bank_consent") != "PENDING":
        raise_error(ERR_AMENDMENT_ALREADY_DECIDED, "confirming bank already decided")

    decision = _decision_str(payload)
    if decision == "REJECTED":
        db.update("lc_amendments", amendment_id, {
            "confirming_bank_consent": "REJECTED",
            "status": "REJECTED",
            "rejected_by_role": "CONFIRMING_BANK",
        })
        db.update("letters_of_credit", lc_id, {"amendment_consent_status": "NONE"})
        audit.append("amendment.confirming_bank_consent", "AMENDMENT", amendment_id, lc_id=lc_id,
                     before_state="PENDING_CONFIRMING_BANK", after_state="REJECTED", payload=payload)
        return db.get_by_id("lc_amendments", amendment_id)

    _validate_changes_against_presentations(lc, a.get("changes") or {})
    db.update("lc_amendments", amendment_id, {"confirming_bank_consent": "CONSENTED"})
    _apply_amendment(lc, amendment_id)
    audit.append("amendment.confirming_bank_consent", "AMENDMENT", amendment_id, lc_id=lc_id,
                 before_state="PENDING_CONFIRMING_BANK", after_state="CONSENTED", payload=payload)
    return db.get_by_id("lc_amendments", amendment_id)


def _validate_changes_against_presentations(lc, changes):
    new_latest_ship = changes.get("latest_shipment_date")
    if new_latest_ship is not None:
        new_dt = db.parse_dt(new_latest_ship)
        if new_dt is None:
            raise_error(ERR_INVALID_REQUEST, "latest_shipment_date invalid")
        for p in db.find_many("presentations", lc_id=lc["id"]):
            ps = db.parse_dt(p.get("shipment_date"))
            if ps is not None and ps > new_dt:
                raise_error(ERR_AMENDMENT_VIOLATES_PRESENTATIONS, "new latest_shipment_date precedes existing presentation")

    new_expiry = changes.get("expiry_date")
    if new_expiry is not None:
        new_dt = db.parse_dt(new_expiry)
        if new_dt is None:
            raise_error(ERR_INVALID_REQUEST, "expiry_date invalid")
        for p in db.find_many("presentations", lc_id=lc["id"]):
            pres_at = db.parse_dt(p.get("presented_at"))
            if pres_at is not None and pres_at > new_dt:
                raise_error(ERR_AMENDMENT_VIOLATES_PRESENTATIONS, "new expiry_date precedes existing presentation")


def _apply_amendment(lc, amendment_id):
    a = db.get_by_id("lc_amendments", amendment_id)
    changes = a.get("changes") or {}
    lc_updates = {}
    for k in ("amount_minor_units", "expiry_date", "latest_shipment_date",
              "tolerance_pct", "required_documents"):
        if k in changes:
            lc_updates[k] = changes[k]
    lc_updates["amendment_consent_status"] = "NONE"

    db.update("letters_of_credit", lc["id"], lc_updates)

    # Reconciliation if amount or tolerance changed
    if "amount_minor_units" in changes or "tolerance_pct" in changes:
        new_lc = db.get_by_id("letters_of_credit", lc["id"])
        cap = _compute_cap(new_lc.get("amount_minor_units", 0), new_lc.get("tolerance_pct", 0))
        drawn = _drawn_minor_units(lc["id"])
        avail = max(0, cap - drawn)
        db.update("letters_of_credit", lc["id"], {
            "drawn_amount_minor_units": drawn,
            "available_amount_minor_units": avail,
        })

    db.update("lc_amendments", amendment_id, {
        "status": "CONSENTED",
        "applied_at": db.now_iso(),
    })
    audit.append("amendment.apply", "AMENDMENT", amendment_id, lc_id=lc["id"],
                 before_state="PENDING", after_state="CONSENTED", payload=changes)


def list_audit_log(lc_id, filters, limit, offset):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    use_filters = {"lc_id": lc_id}
    if filters and filters.get("subject_type"):
        use_filters["subject_type"] = filters["subject_type"]
    rows, total = db.list_table("audit_log_entries", filters=use_filters,
                                sort_keys=("created_at", "id"), limit=limit, offset=offset)
    return rows, total
