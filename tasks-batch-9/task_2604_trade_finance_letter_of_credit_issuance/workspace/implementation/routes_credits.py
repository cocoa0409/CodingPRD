"""Credit drafting, approval, issuance, confirmation and cancellation.

PRD 3.2, 3.3 and 3.4.
"""

from flask import Blueprint

import calc
import ledger
import validate as v
from db import (
    clock_date,
    clock_date_str,
    clock_instant,
    db,
    new_row,
    public,
    touch,
)
from errors import bail
from middleware import (
    APPLICANT_USER,
    BENEFICIARY_USER,
    COMPLIANCE_OFFICER,
    CORRESPONDENT_BANK,
    CREDIT_OFFICER,
    DOCUMENT_EXAMINER,
    TRADE_FINANCE_OFFICER,
    must_find,
    pending,
    raise_pending,
    require,
    require_same_id,
    segregation,
)
from response import created, ok, paginated

bp = Blueprint("credits", __name__)

AVAILABLE_BY = ("SIGHT_PAYMENT", "ACCEPTANCE", "NEGOTIATION", "DEFERRED_PAYMENT")
INCOTERMS = ("EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")
DOC_TYPES = (
    "COMMERCIAL_INVOICE",
    "BILL_OF_LADING",
    "AIR_WAYBILL",
    "INSURANCE_CERTIFICATE",
    "PACKING_LIST",
    "CERTIFICATE_OF_ORIGIN",
    "INSPECTION_CERTIFICATE",
    "DRAFT_BILL_OF_EXCHANGE",
)
TRANSPORT_DOC_TYPES = ("BILL_OF_LADING", "AIR_WAYBILL")
INSURANCE_REQUIRED_INCOTERMS = ("CIF", "CIP")
INSURANCE_FORBIDDEN_INCOTERMS = ("FOB", "FCA", "EXW")
APPROVE_DECISIONS = ("APPROVE", "RETURN_TO_DRAFT")
CONFIRMATION_DECISIONS = ("CONFIRM", "DECLINE")
CANCELLABLE_STATUSES = ("DRAFT", "PENDING_CREDIT_APPROVAL", "APPROVED", "ON_HOLD", "ISSUED")
ISSUED_STATUSES = ("ISSUED", "AMENDMENT_PENDING")


# --------------------------------------------------------------------------
# shared guards
# --------------------------------------------------------------------------

def credit_scope(principal, credit):
    """Read-side ownership for the two entity-backed party roles."""
    if credit is None:
        return
    if principal.is_applicant:
        require_same_id(principal, credit["applicant_id"])
    elif principal.is_beneficiary:
        require_same_id(principal, credit["beneficiary_id"])


def guard_credit_state(credit, allowed, error_id):
    """Band 4. A terminal credit always reports ERR_CREDIT_TERMINAL."""
    status = credit["status"]
    if status in allowed:
        return
    if status in ledger.CREDIT_TERMINAL_STATUSES:
        bail("ERR_CREDIT_TERMINAL")
    bail(error_id)


def screen_credit_parties(credit, screened_by="system"):
    """Score the CREDIT_PARTIES scope without persisting anything yet."""
    applicant = db.applicants.get(credit["applicant_id"])
    beneficiary = db.beneficiaries.get(credit["beneficiary_id"])
    advising_bank = db.banks.get(credit["advising_bank_id"])
    scored = calc.sanctions_dual_use_score(
        "CREDIT_PARTIES", parties=[applicant, beneficiary, advising_bank])
    row = {
        "credit_id": credit["id"],
        "presentation_id": None,
        "scope": "CREDIT_PARTIES",
        "country_hits": scored["country_hits"],
        "dual_use_hits": scored["dual_use_hits"],
        "keyword_hits": scored["keyword_hits"],
        "transit_hits": scored["transit_hits"],
        "risk_score": scored["risk_score"],
        "result": scored["result"],
        "screened_by_user_id": screened_by,
        "reviewed_by_user_id": None,
        "review_note": None,
        "reviewed_at": None,
    }
    return scored, row


def incoterm_document_check(credit):
    """Submission-time paperwork coherence (ERR_INCOTERM_DOCUMENT_MISMATCH)."""
    requirements = ledger.requirements_of_credit(credit["id"])
    has_invoice = any(r["doc_type"] == "COMMERCIAL_INVOICE" and r["is_mandatory"] for r in requirements)
    has_transport = any(r["doc_type"] in TRANSPORT_DOC_TYPES for r in requirements)
    has_insurance = any(r["doc_type"] == "INSURANCE_CERTIFICATE" for r in requirements)
    has_mandatory_insurance = any(
        r["doc_type"] == "INSURANCE_CERTIFICATE" and r["is_mandatory"] for r in requirements)
    incoterm = credit.get("incoterm")
    if not has_invoice or not has_transport:
        bail("ERR_INCOTERM_DOCUMENT_MISMATCH")
    if incoterm in INSURANCE_REQUIRED_INCOTERMS and not has_mandatory_insurance:
        bail("ERR_INCOTERM_DOCUMENT_MISMATCH")
    if incoterm in INSURANCE_FORBIDDEN_INCOTERMS and has_insurance:
        bail("ERR_INCOTERM_DOCUMENT_MISMATCH")


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/credits/<credit_id>")
def get_credit(credit_id):
    principal = require(TRADE_FINANCE_OFFICER, CREDIT_OFFICER, COMPLIANCE_OFFICER,
                        DOCUMENT_EXAMINER, APPLICANT_USER, BENEFICIARY_USER, CORRESPONDENT_BANK)
    credit, deferred = pending("credits", credit_id)
    credit_scope(principal, credit)
    raise_pending(deferred)
    return ok(public(credit))


@bp.get("/credits")
def list_credits():
    require(TRADE_FINANCE_OFFICER, CREDIT_OFFICER, COMPLIANCE_OFFICER, DOCUMENT_EXAMINER)
    rows = sorted(db.credits.values(), key=lambda c: c["_seq"])
    rows = v.filtered(
        rows,
        applicant_id=v.arg("applicant_id"),
        beneficiary_id=v.arg("beneficiary_id"),
        facility_id=v.arg("facility_id"),
        advising_bank_id=v.arg("advising_bank_id"),
        confirming_bank_id=v.arg("confirming_bank_id"),
        status=v.arg("status"),
        confirmation_status=v.arg("confirmation_status"),
    )
    return paginated(rows, public)


@bp.get("/credits/<credit_id>/documentary-requirements")
def list_requirements(credit_id):
    principal = require(TRADE_FINANCE_OFFICER, CREDIT_OFFICER, DOCUMENT_EXAMINER,
                        COMPLIANCE_OFFICER, BENEFICIARY_USER, CORRESPONDENT_BANK)
    credit, deferred = pending("credits", credit_id)
    credit_scope(principal, credit)
    raise_pending(deferred)
    rows = ledger.requirements_of_credit(credit_id)
    rows = v.filtered(rows, doc_type=v.arg("doc_type"), is_mandatory=v.arg_bool("is_mandatory"))
    return paginated(rows, public)


@bp.get("/credits/<credit_id>/amendments")
def list_amendments(credit_id):
    principal = require(TRADE_FINANCE_OFFICER, CREDIT_OFFICER, COMPLIANCE_OFFICER,
                        APPLICANT_USER, BENEFICIARY_USER)
    credit, deferred = pending("credits", credit_id)
    credit_scope(principal, credit)
    raise_pending(deferred)
    rows = sorted(ledger.amendments_of_credit(credit_id), key=lambda a: int(a["seq"]))
    rows = v.filtered(
        rows,
        status=v.arg("status"),
        requires_beneficiary_consent=v.arg_bool("requires_beneficiary_consent"),
    )
    return paginated(rows, public)


@bp.get("/credits/<credit_id>/allocations")
def list_credit_allocations(credit_id):
    require(TRADE_FINANCE_OFFICER, CREDIT_OFFICER, COMPLIANCE_OFFICER)
    must_find("credits", credit_id)
    rows = ledger.credit_allocations(credit_id)
    rows = v.filtered(rows, status=v.arg("status"))
    return paginated(rows, public)


@bp.get("/credits/<credit_id>/screening-checks")
def list_credit_screenings(credit_id):
    require(COMPLIANCE_OFFICER, TRADE_FINANCE_OFFICER, CREDIT_OFFICER, DOCUMENT_EXAMINER)
    must_find("credits", credit_id)
    rows = ledger.screenings_of_credit(credit_id)
    rows = v.filtered(rows, scope=v.arg("scope"), result=v.arg("result"),
                      presentation_id=v.arg("presentation_id"))
    return paginated(rows, public)


# --------------------------------------------------------------------------
# drafting
# --------------------------------------------------------------------------

@bp.post("/credits")
def create_credit():
    principal = require(TRADE_FINANCE_OFFICER)
    data = v.body()
    applicant_id = v.req_id(data, "applicant_id")
    beneficiary_id = v.req_id(data, "beneficiary_id")
    facility_id = v.req_id(data, "facility_id")
    advising_bank_id = v.req_id(data, "advising_bank_id")
    currency = v.req_currency(data, "currency")
    amount_cents = v.req_int(data, "amount_cents", minimum=100000)
    available_by = v.req_enum(data, "available_by", AVAILABLE_BY)
    incoterm = v.req_enum(data, "incoterm", INCOTERMS)
    incoterm_place = v.req_str(data, "incoterm_place", 1, 120)
    latest_shipment_date = v.req_date(data, "latest_shipment_date")
    expiry_date = v.req_date(data, "expiry_date")
    expiry_place = v.req_str(data, "expiry_place", 1, 120)
    presentation_period_days = v.req_int(data, "presentation_period_days", minimum=1, maximum=30)
    tolerance_pct = v.opt_int(data, "tolerance_pct", minimum=0, maximum=10, default=0)
    tenor_days = v.opt_int(data, "tenor_days", minimum=0, maximum=360, default=0)
    partial_shipment_allowed = v.opt_bool(data, "partial_shipment_allowed", False)
    transhipment_allowed = v.opt_bool(data, "transhipment_allowed", False)

    # availability / tenor pairing
    if available_by == "SIGHT_PAYMENT":
        if tenor_days != 0:
            v.bad("tenor_days must be 0 when available_by is SIGHT_PAYMENT")
    elif tenor_days < 1:
        v.bad("tenor_days must be at least 1 for a usance credit")

    applicant = must_find("applicants", applicant_id)
    beneficiary = must_find("beneficiaries", beneficiary_id)
    facility = must_find("facilities", facility_id)
    advising_bank = must_find("banks", advising_bank_id)

    # band 5 -- compliance safety
    if (applicant.get("sanctions_flag") or beneficiary.get("sanctions_flag")
            or advising_bank.get("sanctions_flag") or beneficiary.get("status") == "BLOCKED"):
        bail("ERR_SANCTIONS_BLOCK")
    if applicant.get("kyc_status") != "CLEARED":
        bail("ERR_APPLICANT_KYC_NOT_CLEARED")
    if advising_bank.get("status") != "ACTIVE":
        bail("ERR_ADVISING_BANK_INELIGIBLE")

    # band 6 -- temporal
    if calc.parse_date(latest_shipment_date) > calc.parse_date(expiry_date):
        bail("ERR_SHIPMENT_AFTER_EXPIRY")

    # band 8 -- referential
    if facility["applicant_id"] != applicant_id or facility["currency"] != currency:
        bail("ERR_FACILITY_APPLICANT_MISMATCH")
    if calc.parse_date(facility["facility_expiry_date"]) < calc.parse_date(expiry_date):
        bail("ERR_FACILITY_EXPIRED")

    row = new_row(
        applicant_id=applicant_id,
        beneficiary_id=beneficiary_id,
        facility_id=facility_id,
        advising_bank_id=advising_bank_id,
        confirming_bank_id=None,
        currency=currency,
        amount_cents=amount_cents,
        tolerance_pct=tolerance_pct,
        available_by=available_by,
        tenor_days=tenor_days,
        incoterm=incoterm,
        incoterm_place=incoterm_place,
        partial_shipment_allowed=partial_shipment_allowed,
        transhipment_allowed=transhipment_allowed,
        latest_shipment_date=latest_shipment_date,
        expiry_date=expiry_date,
        expiry_place=expiry_place,
        presentation_period_days=presentation_period_days,
        presentation_deadline_date=None,
        issue_date=None,
        status="DRAFT",
        confirmation_status="UNCONFIRMED",
        provisional_allocation_cents=0,
        max_drawable_cents=0,
        gross_exposure_cents=0,
        committed_allocation_cents=0,
        commission_bps_applied=0,
        base_commission_cents=0,
        confirmation_charge_cents=0,
        total_charge_cents=0,
        chargeable_utilisation_cents=0,
        reserved_cents=0,
        drawn_settled_cents=0,
        available_cents=0,
        amendment_seq=0,
        confirmation_window_start=None,
        confirmation_window_end=None,
        drafted_by_user_id=principal.user_id,
        issued_by_user_id=None,
        cancelled_reason=None,
    )
    row["max_drawable_cents"] = calc.nominal_max_drawable(row)
    window = calc.presentation_window(row)
    row["presentation_deadline_date"] = window["presentation_deadline_date"]
    provisional = calc.credit_allocation_exposure(row, facility, "provisional_draft")
    row["provisional_allocation_cents"] = provisional["committed_allocation_cents"]
    row["_declined_bank_ids"] = []
    db.credits[row["id"]] = row
    return created(public(row))


@bp.post("/credits/<credit_id>/documentary-requirements")
def create_requirement(credit_id):
    require(TRADE_FINANCE_OFFICER)
    data = v.body()
    doc_type = v.req_enum(data, "doc_type", DOC_TYPES)
    originals_required = v.req_int(data, "originals_required", minimum=0, maximum=5)
    copies_required = v.req_int(data, "copies_required", minimum=0, maximum=5)
    issuer_constraint = v.req_str(data, "issuer_constraint", 0, 120, non_blank=False)
    is_mandatory = v.opt_bool(data, "is_mandatory", True)
    credit = must_find("credits", credit_id)

    guard_credit_state(credit, ("DRAFT",), "ERR_CREDIT_NOT_DRAFT")

    for existing in ledger.requirements_of_credit(credit_id):
        if existing["doc_type"] == doc_type:
            bail("ERR_DUPLICATE_KEY")

    row = new_row(
        credit_id=credit_id,
        doc_type=doc_type,
        originals_required=originals_required,
        copies_required=copies_required,
        issuer_constraint=issuer_constraint,
        is_mandatory=is_mandatory,
        amended_in_seq=int(credit.get("amendment_seq") or 0),
    )
    db.requirements[row["id"]] = row
    return created(public(row))


@bp.post("/credits/<credit_id>/submit-for-approval")
def submit_for_approval(credit_id):
    require(TRADE_FINANCE_OFFICER)
    data = v.body()
    v.opt_str(data, "submission_note", 0, 500)
    credit = must_find("credits", credit_id)

    guard_credit_state(credit, ("DRAFT",), "ERR_CREDIT_NOT_DRAFT")
    incoterm_document_check(credit)

    facility = db.facilities.get(credit["facility_id"])
    provisional = calc.credit_allocation_exposure(credit, facility, "provisional_draft")
    credit["provisional_allocation_cents"] = provisional["committed_allocation_cents"]
    credit["status"] = "PENDING_CREDIT_APPROVAL"
    touch(credit)
    return ok(public(credit))


@bp.post("/credits/<credit_id>/approve")
def approve_credit(credit_id):
    principal = require(CREDIT_OFFICER)
    credit, deferred = pending("credits", credit_id)
    if credit is not None:
        segregation(principal, credit.get("drafted_by_user_id"))

    data = v.body()
    decision = v.req_enum(data, "decision", APPROVE_DECISIONS)
    v.opt_str(data, "approval_note", 0, 500)
    raise_pending(deferred)

    guard_credit_state(credit, ("PENDING_CREDIT_APPROVAL",), "ERR_CREDIT_NOT_DRAFT")

    if decision == "RETURN_TO_DRAFT":
        credit["status"] = "DRAFT"
        touch(credit)
        return ok(public(credit))

    facility = db.facilities.get(credit["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        bail("ERR_FACILITY_NOT_ACTIVE")
    applicant = db.applicants.get(credit["applicant_id"])
    if applicant is None or applicant.get("kyc_status") != "CLEARED":
        bail("ERR_APPLICANT_KYC_NOT_CLEARED")

    credit["status"] = "APPROVED"
    touch(credit)
    return ok(public(credit))


@bp.post("/credits/<credit_id>/issue")
def issue_credit(credit_id):
    principal = require(TRADE_FINANCE_OFFICER)
    data = v.body()
    v.opt_str(data, "issue_note", 0, 500)
    credit = must_find("credits", credit_id)

    # band 4 -- own state, then the cross-entity facility gate
    guard_credit_state(credit, ("APPROVED",), "ERR_CREDIT_NOT_APPROVED")
    facility = db.facilities.get(credit["facility_id"])
    if facility is None or facility["status"] != "ACTIVE" or facility["utilisation_posture"] == "FROZEN":
        bail("ERR_FACILITY_NOT_ACTIVE")

    # band 5 -- compliance safety. A BLOCKED score persists nothing at all.
    scored, screening_fields = screen_credit_parties(credit, screened_by="system")
    if scored["result"] == "BLOCKED":
        bail("ERR_SANCTIONS_BLOCK")

    # band 7 / 8
    advising_bank = db.banks.get(credit["advising_bank_id"])
    if (advising_bank is None or advising_bank["status"] != "ACTIVE"
            or advising_bank.get("sanctions_flag")):
        bail("ERR_ADVISING_BANK_INELIGIBLE")
    if calc.parse_date(facility["facility_expiry_date"]) < clock_date():
        bail("ERR_FACILITY_EXPIRED")

    # pricing -- computed on the row itself before the fiscal gate
    issue_date = clock_date_str()
    exposure = calc.credit_allocation_exposure(
        credit, facility, "committed_issuance", overrides={"issue_date": issue_date})
    probe = dict(credit)
    probe["issue_date"] = issue_date
    probe["gross_exposure_cents"] = exposure["gross_exposure_cents"]
    probe["committed_allocation_cents"] = exposure["committed_allocation_cents"]
    charges = calc.issuance_charges(probe, None)

    # band 9 -- fiscal, checked last. Equality is admitted.
    if charges["chargeable_utilisation_cents"] > int(facility["available_cents"]):
        bail("ERR_FACILITY_LIMIT_EXCEEDED")

    credit["issue_date"] = issue_date
    credit["issued_by_user_id"] = principal.user_id
    credit["status"] = "ISSUED"
    credit["max_drawable_cents"] = calc.nominal_max_drawable(credit)
    credit["gross_exposure_cents"] = exposure["gross_exposure_cents"]
    credit["committed_allocation_cents"] = exposure["committed_allocation_cents"]
    credit["commission_bps_applied"] = charges["commission_bps_applied"]
    credit["base_commission_cents"] = charges["base_commission_cents"]
    credit["confirmation_charge_cents"] = charges["confirmation_charge_cents"]
    credit["total_charge_cents"] = charges["total_charge_cents"]
    credit["chargeable_utilisation_cents"] = charges["chargeable_utilisation_cents"]
    window = calc.presentation_window(credit)
    credit["presentation_deadline_date"] = window["presentation_deadline_date"]
    credit["confirmation_window_start"] = window["confirmation_window_start"]
    credit["confirmation_window_end"] = window["confirmation_window_end"]
    touch(credit)

    screening = new_row(**screening_fields)
    db.screenings[screening["id"]] = screening

    # cascade hop 1 -- the committed allocation row
    allocation = new_row(
        facility_id=facility["id"],
        credit_id=credit["id"],
        allocated_cents=exposure["committed_allocation_cents"],
        charge_cents=charges["total_charge_cents"],
        released_cents=0,
        basis="COMMITTED_ISSUANCE",
        status="OPEN",
        released_at=None,
    )
    db.allocations[allocation["id"]] = allocation

    # hops 2, 3 and 4 fall out of the recompute
    ledger.recompute_facility(facility, exclude_credit_id=credit["id"])
    ledger.recompute_credit_drawable(credit)
    return ok(public(credit))


# --------------------------------------------------------------------------
# confirmation
# --------------------------------------------------------------------------

@bp.post("/credits/<credit_id>/confirmation-requests")
def request_confirmation(credit_id):
    require(TRADE_FINANCE_OFFICER)
    data = v.body()
    named_bank_id = data.get("confirming_bank_id")
    if named_bank_id is not None:
        named_bank_id = v.req_id(data, "confirming_bank_id")
    v.opt_str(data, "request_note", 0, 500)
    credit = must_find("credits", credit_id)
    named_bank = must_find("banks", named_bank_id) if named_bank_id is not None else None

    # band 4 -- both dimensions
    guard_credit_state(credit, ISSUED_STATUSES, "ERR_CREDIT_NOT_ISSUED")
    if credit["confirmation_status"] not in ("UNCONFIRMED", "CONFIRMATION_DECLINED"):
        bail("ERR_CREDIT_NOT_ISSUED")

    # band 5 -- a sanctioned party never gets a confirmation request out
    scored, _fields = screen_credit_parties(credit)
    if scored["result"] == "BLOCKED":
        bail("ERR_SANCTIONS_BLOCK")

    # band 6 -- half-open [start, end)
    today = clock_date()
    start = calc.parse_date(credit.get("confirmation_window_start"))
    end = calc.parse_date(credit.get("confirmation_window_end"))
    if start is None or end is None or today < start or today >= end:
        bail("ERR_CONFIRMATION_WINDOW_CLOSED")

    beneficiary = db.beneficiaries.get(credit["beneficiary_id"])
    beneficiary_country = (beneficiary or {}).get("country_code")
    all_credits = list(db.credits.values())

    if named_bank is not None:
        if not calc.bank_confirmation_eligible(named_bank, beneficiary_country):
            bail("ERR_CONFIRMING_BANK_INELIGIBLE")
        selected = named_bank
    else:
        selected = calc.select_confirming_bank(
            list(db.banks.values()), all_credits, credit, beneficiary_country,
            ledger.declined_bank_ids(credit_id))
        if selected is None:
            bail("ERR_NO_ELIGIBLE_CONFIRMING_BANK")

    probe = dict(credit)
    probe["confirming_bank_id"] = selected["id"]
    probe["confirmation_status"] = "CONFIRMATION_REQUESTED"
    peak = calc.confirming_line_peak_occupancy(all_credits, selected["id"], candidate=probe)
    if peak > int(selected["confirmation_appetite_cents"] or 0):
        bail("ERR_CONFIRMING_LINE_WINDOW_FULL")

    credit["confirming_bank_id"] = selected["id"]
    credit["confirmation_status"] = "CONFIRMATION_REQUESTED"
    touch(credit)
    ledger.recompute_bank_line(selected)
    return ok(public(credit))


@bp.post("/credits/<credit_id>/confirmation-responses")
def respond_confirmation(credit_id):
    principal = require(CORRESPONDENT_BANK)
    credit, deferred = pending("credits", credit_id)
    if credit is not None and credit.get("confirming_bank_id") != principal.user_id:
        bail("ERR_PRINCIPAL_NOT_PARTY")

    data = v.body()
    decision = v.req_enum(data, "decision", CONFIRMATION_DECISIONS)
    declined_reason = v.opt_str(data, "declined_reason", 0, 500)
    if decision == "DECLINE" and not (declined_reason or "").strip():
        v.bad("declined_reason is required when declining a confirmation request")
    raise_pending(deferred)

    guard_credit_state(credit, ISSUED_STATUSES, "ERR_CREDIT_NOT_ISSUED")
    if credit["confirmation_status"] != "CONFIRMATION_REQUESTED":
        bail("ERR_CREDIT_NOT_ISSUED")

    bank = db.banks.get(credit["confirming_bank_id"])
    facility = db.facilities.get(credit["facility_id"])

    if decision == "DECLINE":
        declined = credit.setdefault("_declined_bank_ids", [])
        if bank is not None and bank["id"] not in declined:
            declined.append(bank["id"])
        credit["confirming_bank_id"] = None
        credit["confirmation_status"] = "CONFIRMATION_DECLINED"
        touch(credit)
        ledger.recompute_bank_line(bank)
        return ok(public(credit))

    # CONFIRM -- price the confirmation on a probe copy before mutating anything
    probe = dict(credit)
    probe["confirmation_status"] = "CONFIRMED"
    charges = calc.issuance_charges(probe, bank)
    delta = charges["confirmation_charge_cents"] - int(credit.get("confirmation_charge_cents") or 0)
    if facility is not None and delta > int(facility["available_cents"]):
        bail("ERR_FACILITY_LIMIT_EXCEEDED")

    credit["confirmation_status"] = "CONFIRMED"
    credit["confirmation_charge_cents"] = charges["confirmation_charge_cents"]
    credit["total_charge_cents"] = charges["total_charge_cents"]
    credit["chargeable_utilisation_cents"] = charges["chargeable_utilisation_cents"]
    touch(credit)

    allocation = ledger.open_allocation_of_credit(credit["id"])
    if allocation is not None:
        allocation["charge_cents"] = charges["total_charge_cents"]
        touch(allocation)
    if facility is not None:
        ledger.recompute_facility(facility, exclude_credit_id=credit["id"])
    ledger.recompute_bank_line(bank)
    return ok(public(credit))


# --------------------------------------------------------------------------
# cancellation
# --------------------------------------------------------------------------

def _live_presentation(presentation):
    return (presentation["examination_status"] != "REFUSED"
            and presentation["settlement_status"] not in ("VOID", "PAID", "NEGOTIATED", "REIMBURSED"))


@bp.post("/credits/<credit_id>/cancel")
def cancel_credit(credit_id):
    require(TRADE_FINANCE_OFFICER)
    data = v.body()
    reason = v.req_str(data, "reason", 1, 500)
    consent_reference = v.opt_str(data, "beneficiary_consent_reference", 0, 120)
    credit = must_find("credits", credit_id)

    guard_credit_state(credit, CANCELLABLE_STATUSES, "ERR_CREDIT_NOT_ISSUED")

    for presentation in ledger.presentations_of_credit(credit_id):
        if _live_presentation(presentation):
            bail("ERR_CREDIT_HAS_LIVE_PRESENTATION")

    if credit["status"] == "ISSUED" and not (consent_reference or "").strip():
        bail("ERR_BENEFICIARY_CONSENT_REQUIRED")

    bank = db.banks.get(credit.get("confirming_bank_id"))
    credit["status"] = "CANCELLED"
    credit["cancelled_reason"] = reason
    touch(credit)

    facility = db.facilities.get(credit["facility_id"])
    released = False
    for row in ledger.credit_allocations(credit_id):
        if row["status"] != "OPEN":
            continue
        row["status"] = "RELEASED"
        row["released_cents"] = int(row["allocated_cents"]) + int(row["charge_cents"])
        row["released_at"] = clock_instant()
        touch(row)
        released = True
    if facility is not None and released:
        ledger.recompute_facility(facility, exclude_credit_id=credit_id)

    if bank is not None:
        ledger.recompute_bank_line(bank)
    ledger.recompute_credit_drawable(credit)
    return ok(public(credit))
