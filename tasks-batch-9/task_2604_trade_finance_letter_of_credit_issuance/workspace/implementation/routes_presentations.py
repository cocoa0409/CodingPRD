"""Presentation, examination, waiver, refusal and screening (PRD 3.6-3.8)."""

from flask import Blueprint

import calc
import ledger
import validate as v
from db import (
    clock_date,
    clock_date_str,
    clock_instant,
    db,
    new_bare_row,
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
)
from response import created, ok, paginated
from routes_credits import DOC_TYPES, ISSUED_STATUSES, guard_credit_state

bp = Blueprint("presentations", __name__)

DISCREPANCY_CODES = (
    "LATE_SHIPMENT",
    "LATE_PRESENTATION",
    "CREDIT_EXPIRED",
    "MISSING_DOCUMENT",
    "INSUFFICIENT_ORIGINALS",
    "INVOICE_OVERDRAWN",
    "GOODS_DESCRIPTION_MISMATCH",
    "INCOTERM_MISMATCH",
    "INSURANCE_UNDERVALUED",
    "TRANSHIPMENT_NOT_ALLOWED",
)
SEVERITIES = ("MATERIAL", "MINOR")
DISPOSAL_INSTRUCTIONS = ("HOLD_AT_DISPOSAL", "RETURN_TO_PRESENTER")
WAIVER_DECISIONS = ("GRANT", "DENY")
REVIEW_DECISIONS = ("RELEASE", "BLOCK", "ESCALATE")
SCREENING_SCOPES = ("CREDIT_PARTIES", "PRESENTED_DOCUMENTS")
CONCLUDED_EXAMINATION_STATUSES = ("COMPLYING", "DISCREPANT", "REFUSED", "PRECLUDED")


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def presentation_scope(principal, presentation):
    """Read-side ownership for the entity-backed party roles."""
    if presentation is None:
        return
    credit = db.credits.get(presentation["credit_id"]) or {}
    if principal.is_applicant and credit.get("applicant_id") != principal.user_id:
        bail("ERR_PRINCIPAL_NOT_PARTY")
    if principal.is_beneficiary and credit.get("beneficiary_id") != principal.user_id:
        bail("ERR_PRINCIPAL_NOT_PARTY")


def presenting_bank_guard(principal, presentation):
    if presentation is not None and presentation["presenting_bank_id"] != principal.user_id:
        bail("ERR_PRINCIPAL_NOT_PARTY")


def examination_open(presentation):
    """Band 6: the clock instant must still be inside the examination period."""
    deadline = presentation.get("examination_deadline")
    if deadline is not None and clock_instant() > deadline:
        bail("ERR_EXAMINATION_PERIOD_EXPIRED")


def screening_review_gate(presentation):
    """Band 5: a HIT_PENDING_REVIEW document screening freezes the examination."""
    check = ledger.newest_document_screening(presentation["id"])
    if check is not None and check["result"] == "HIT_PENDING_REVIEW":
        bail("ERR_SCREENING_REVIEW_PENDING")


def score_documents(presentation):
    documents = ledger.documents_of_presentation(presentation["id"])
    return calc.sanctions_dual_use_score("PRESENTED_DOCUMENTS", documents=documents)


def block_beneficiary(credit):
    beneficiary = db.beneficiaries.get((credit or {}).get("beneficiary_id"))
    if beneficiary is not None and beneficiary["status"] == "ACTIVE":
        beneficiary["status"] = "BLOCKED"
        touch(beneficiary)


def persist_screening(credit_id, presentation_id, scope, scored, screened_by):
    row = new_row(
        credit_id=credit_id,
        presentation_id=presentation_id,
        scope=scope,
        country_hits=scored["country_hits"],
        dual_use_hits=scored["dual_use_hits"],
        keyword_hits=scored["keyword_hits"],
        transit_hits=scored["transit_hits"],
        risk_score=scored["risk_score"],
        result=scored["result"],
        screened_by_user_id=screened_by,
        reviewed_by_user_id=None,
        review_note=None,
        reviewed_at=None,
    )
    db.screenings[row["id"]] = row
    return row


def refresh_presentation_examination(presentation):
    """Recompute discrepancy_count and settle the WAIVER_REQUESTED fork."""
    count = ledger.recompute_discrepancy_count(presentation)
    if presentation["examination_status"] == "WAIVER_REQUESTED":
        presentation["examination_status"] = "COMPLYING" if count == 0 else "DISCREPANT"
    return count


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/presentations/<presentation_id>")
def get_presentation(presentation_id):
    principal = require(DOCUMENT_EXAMINER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER,
                        CREDIT_OFFICER, CORRESPONDENT_BANK, BENEFICIARY_USER, APPLICANT_USER)
    presentation, deferred = pending("presentations", presentation_id)
    presentation_scope(principal, presentation)
    raise_pending(deferred)
    return ok(public(presentation))


@bp.get("/presentations")
def list_presentations():
    require(DOCUMENT_EXAMINER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER, CREDIT_OFFICER)
    rows = sorted(db.presentations.values(), key=lambda p: p["_seq"])
    rows = v.filtered(
        rows,
        credit_id=v.arg("credit_id"),
        presenting_bank_id=v.arg("presenting_bank_id"),
        examination_status=v.arg("examination_status"),
        settlement_status=v.arg("settlement_status"),
    )
    return paginated(rows, public)


@bp.get("/presentations/<presentation_id>/documents")
def list_documents(presentation_id):
    require(DOCUMENT_EXAMINER, COMPLIANCE_OFFICER, TRADE_FINANCE_OFFICER, CORRESPONDENT_BANK)
    must_find("presentations", presentation_id)
    rows = ledger.documents_of_presentation(presentation_id)
    rows = v.filtered(rows, doc_type=v.arg("doc_type"))
    return paginated(rows, public)


@bp.get("/presentations/<presentation_id>/discrepancies")
def list_discrepancies(presentation_id):
    principal = require(DOCUMENT_EXAMINER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER,
                        APPLICANT_USER, CORRESPONDENT_BANK)
    presentation, deferred = pending("presentations", presentation_id)
    presentation_scope(principal, presentation)
    raise_pending(deferred)
    rows = ledger.discrepancies_of_presentation(presentation_id)
    rows = v.filtered(rows, status=v.arg("status"), severity=v.arg("severity"))
    return paginated(rows, public)


@bp.get("/presentations/<presentation_id>/waiver-requests")
def list_waivers(presentation_id):
    principal = require(DOCUMENT_EXAMINER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER, APPLICANT_USER)
    presentation, deferred = pending("presentations", presentation_id)
    presentation_scope(principal, presentation)
    raise_pending(deferred)
    rows = ledger.waivers_of_presentation(presentation_id)
    rows = v.filtered(rows, status=v.arg("status"))
    return paginated(rows, public)


@bp.get("/presentations/<presentation_id>/settlement-claims")
def list_claims(presentation_id):
    require(TRADE_FINANCE_OFFICER, DOCUMENT_EXAMINER, COMPLIANCE_OFFICER, CORRESPONDENT_BANK)
    must_find("presentations", presentation_id)
    rows = ledger.claims_of_presentation(presentation_id)
    rows = v.filtered(rows, status=v.arg("status"), claim_type=v.arg("claim_type"))
    return paginated(rows, public)


@bp.get("/presentations/<presentation_id>/screenings")
def list_presentation_screenings(presentation_id):
    require(COMPLIANCE_OFFICER, DOCUMENT_EXAMINER, TRADE_FINANCE_OFFICER, CREDIT_OFFICER)
    must_find("presentations", presentation_id)
    rows = [s for s in db.screenings.values() if s.get("presentation_id") == presentation_id]
    rows.sort(key=lambda s: s["_seq"])
    rows = v.filtered(rows, result=v.arg("result"))
    return paginated(rows, public)


# --------------------------------------------------------------------------
# opening a presentation file
# --------------------------------------------------------------------------

@bp.post("/presentations")
def create_presentation():
    principal = require(CORRESPONDENT_BANK)
    data = v.body()
    credit_id = v.req_id(data, "credit_id")
    presenting_bank_id = v.req_id(data, "presenting_bank_id")
    cover_letter_reference = v.opt_str(data, "cover_letter_reference", 0, 60)

    # band 2 -- the acting bank must be the presenting bank
    if presenting_bank_id != principal.user_id:
        bail("ERR_PRINCIPAL_NOT_PARTY")

    credit = must_find("credits", credit_id)
    must_find("banks", presenting_bank_id)

    guard_credit_state(credit, ISSUED_STATUSES, "ERR_CREDIT_NOT_ISSUED")

    beneficiary = db.beneficiaries.get(credit["beneficiary_id"]) or {}
    nominated = {
        beneficiary.get("nominated_bank_id"),
        credit.get("advising_bank_id"),
        credit.get("confirming_bank_id"),
    }
    if presenting_bank_id not in nominated:
        bail("ERR_BANK_NOT_NOMINATED")

    row = new_row(
        credit_id=credit_id,
        presenting_bank_id=presenting_bank_id,
        cover_letter_reference=cover_letter_reference,
        received_at=clock_instant(),
        received_date=clock_date_str(),
        submitted_at=None,
        document_count=0,
        drawn_amount_cents=0,
        examination_status="RECEIVED",
        settlement_status="UNSETTLED",
        examination_deadline=None,
        discrepancy_count=0,
        refusal_notice_sent_at=None,
        disposal_instruction=None,
        maturity_date=None,
        examined_by_user_id=None,
    )
    db.presentations[row["id"]] = row
    return created(public(row))


@bp.post("/presentations/<presentation_id>/documents")
def add_document(presentation_id):
    principal = require(CORRESPONDENT_BANK)
    presentation, deferred = pending("presentations", presentation_id)
    presenting_bank_guard(principal, presentation)

    data = v.body()
    doc_type = v.req_enum(data, "doc_type", DOC_TYPES)
    originals_presented = v.req_int(data, "originals_presented", minimum=0, maximum=5)
    copies_presented = v.req_int(data, "copies_presented", minimum=0, maximum=5)
    issue_date = v.req_date(data, "issue_date")
    shipment_date = v.opt_date(data, "shipment_date")
    invoice_amount_cents = v.opt_int(data, "invoice_amount_cents", minimum=0, default=0)
    goods_description = v.opt_str(data, "goods_description", 0, 500, default="")
    hs_code = v.opt_hs_code(data, "hs_code", default="")
    consignee_country = v.opt_country(data, "consignee_country", default="")
    transit_country_codes = v.opt_code_array(data, "transit_country_codes")
    issuer_name = v.opt_str(data, "issuer_name", 0, 200, default="")

    if doc_type == "COMMERCIAL_INVOICE" and invoice_amount_cents <= 0:
        v.bad("invoice_amount_cents must be greater than zero for a COMMERCIAL_INVOICE")
    raise_pending(deferred)

    if presentation["examination_status"] != "RECEIVED":
        bail("ERR_PRESENTATION_NOT_EXAMINABLE")

    row = new_bare_row(
        presentation_id=presentation_id,
        doc_type=doc_type,
        originals_presented=originals_presented,
        copies_presented=copies_presented,
        issue_date=issue_date,
        shipment_date=shipment_date,
        invoice_amount_cents=invoice_amount_cents,
        goods_description=goods_description,
        hs_code=hs_code,
        consignee_country=consignee_country,
        transit_country_codes=list(transit_country_codes),
        issuer_name=issuer_name,
    )
    db.documents[row["id"]] = row

    presentation["document_count"] = len(ledger.documents_of_presentation(presentation_id))
    touch(presentation)
    return created(public(row))


@bp.post("/presentations/<presentation_id>/submit")
def submit_presentation(presentation_id):
    principal = require(CORRESPONDENT_BANK)
    presentation, deferred = pending("presentations", presentation_id)
    presenting_bank_guard(principal, presentation)

    data = v.body()
    v.opt_str(data, "submission_note", 0, 500)
    raise_pending(deferred)

    if presentation["examination_status"] != "RECEIVED":
        bail("ERR_PRESENTATION_NOT_EXAMINABLE")

    credit = db.credits.get(presentation["credit_id"])
    documents = ledger.documents_of_presentation(presentation_id)

    # band 5 -- a BLOCKED document screening is persisted and cascades even
    # though the submission itself is refused (PRD 3.8: only the CREDIT_PARTIES
    # scope leaves no screening history behind).
    scored = calc.sanctions_dual_use_score("PRESENTED_DOCUMENTS", documents=documents)
    if scored["result"] == "BLOCKED":
        persist_screening(presentation["credit_id"], presentation_id,
                          "PRESENTED_DOCUMENTS", scored, "system")
        block_beneficiary(credit)
        bail("ERR_SANCTIONS_BLOCK")

    # band 6 -- the presentation window is inclusive of its last date
    deadline_date = calc.parse_date((credit or {}).get("presentation_deadline_date"))
    if deadline_date is None or clock_date() > deadline_date:
        bail("ERR_PRESENTATION_WINDOW_CLOSED")

    # band 7 -- completeness against the credit's mandatory requirements
    if not documents:
        bail("ERR_PRESENTATION_INCOMPLETE")
    for requirement in ledger.requirements_of_credit(presentation["credit_id"]):
        if not requirement["is_mandatory"]:
            continue
        answered = any(
            doc["doc_type"] == requirement["doc_type"]
            and int(doc["originals_presented"]) >= int(requirement["originals_required"])
            for doc in documents
        )
        if not answered:
            bail("ERR_PRESENTATION_INCOMPLETE")

    drawn = sum(int(doc["invoice_amount_cents"] or 0)
                for doc in documents if doc["doc_type"] == "COMMERCIAL_INVOICE")

    # band 9 -- fiscal, equality admitted
    if drawn > int((credit or {}).get("available_cents") or 0):
        bail("ERR_CREDIT_DRAWABLE_EXCEEDED")

    presentation["received_date"] = clock_date_str()
    presentation["submitted_at"] = clock_instant()
    presentation["document_count"] = len(documents)
    presentation["drawn_amount_cents"] = drawn
    presentation["maturity_date"] = ledger.maturity_date_for(credit, presentation["received_date"])
    presentation["examination_deadline"] = calc.examination_period_deadline(
        presentation["received_date"])
    presentation["examination_status"] = "UNDER_EXAMINATION"
    touch(presentation)

    persist_screening(presentation["credit_id"], presentation_id,
                      "PRESENTED_DOCUMENTS", scored, "system")
    if credit is not None:
        ledger.recompute_credit_drawable(credit)
    return ok(public(presentation))


# --------------------------------------------------------------------------
# screening
# --------------------------------------------------------------------------

@bp.post("/presentations/<presentation_id>/screenings")
def rescreen_presentation(presentation_id):
    principal = require(COMPLIANCE_OFFICER)
    data = v.body()
    scope = v.req_enum(data, "scope", SCREENING_SCOPES)
    v.opt_str(data, "screening_note", 0, 500)
    presentation = must_find("presentations", presentation_id)
    credit = db.credits.get(presentation["credit_id"])

    if scope == "PRESENTED_DOCUMENTS":
        scored = score_documents(presentation)
        row = persist_screening(presentation["credit_id"], presentation_id, scope,
                                scored, principal.user_id)
        if scored["result"] == "BLOCKED":
            block_beneficiary(credit)
    else:
        parties = [
            db.applicants.get((credit or {}).get("applicant_id")),
            db.beneficiaries.get((credit or {}).get("beneficiary_id")),
            db.banks.get((credit or {}).get("advising_bank_id")),
        ]
        scored = calc.sanctions_dual_use_score("CREDIT_PARTIES", parties=parties)
        row = persist_screening(presentation["credit_id"], None, scope,
                                scored, principal.user_id)
    return created(public(row))


@bp.post("/screening-checks/<check_id>/review")
def review_screening(check_id):
    principal = require(COMPLIANCE_OFFICER)
    check, deferred = pending("screenings", check_id)
    if check is not None and check.get("screened_by_user_id") == principal.user_id:
        bail("ERR_SEGREGATION_OF_DUTIES")

    data = v.body()
    decision = v.req_enum(data, "decision", REVIEW_DECISIONS)
    review_note = v.opt_str(data, "review_note", 0, 500)
    raise_pending(deferred)

    if check["result"] != "HIT_PENDING_REVIEW":
        bail("ERR_SCREENING_NOT_REVIEWABLE")

    check["reviewed_by_user_id"] = principal.user_id
    check["reviewed_at"] = clock_instant()
    check["review_note"] = review_note
    if decision == "RELEASE":
        check["result"] = "RELEASED"
    elif decision == "ESCALATE":
        check["result"] = "ESCALATED"
    else:
        check["result"] = "BLOCKED"
        if check["scope"] == "PRESENTED_DOCUMENTS":
            block_beneficiary(db.credits.get(check["credit_id"]))
    touch(check)
    return ok(public(check))


# --------------------------------------------------------------------------
# examination
# --------------------------------------------------------------------------

@bp.post("/presentations/<presentation_id>/discrepancies")
def raise_discrepancy(presentation_id):
    principal = require(DOCUMENT_EXAMINER)
    data = v.body()
    code = v.req_str(data, "code", 1, 60)
    severity = v.req_enum(data, "severity", SEVERITIES)
    description = v.req_str(data, "description", 1, 500)
    presentation = must_find("presentations", presentation_id)

    # band 4
    if presentation["examination_status"] != "UNDER_EXAMINATION":
        bail("ERR_PRESENTATION_NOT_EXAMINABLE")

    # band 6
    examination_open(presentation)

    # band 7 -- one citation per code per presentation
    for existing in ledger.discrepancies_of_presentation(presentation_id):
        if existing["code"] == code:
            bail("ERR_DUPLICATE_KEY")

    # band 8 -- the fixed UCP list
    if code not in DISCREPANCY_CODES:
        bail("ERR_DISCREPANCY_CODE_UNKNOWN")

    row = new_row(
        presentation_id=presentation_id,
        code=code,
        severity=severity,
        description=description,
        status="IDENTIFIED",
        raised_by_user_id=principal.user_id,
    )
    db.discrepancies[row["id"]] = row

    ledger.recompute_discrepancy_count(presentation)
    presentation["examined_by_user_id"] = principal.user_id
    touch(presentation)
    return created(public(row))


@bp.post("/presentations/<presentation_id>/conclude-examination")
def conclude_examination(presentation_id):
    principal = require(DOCUMENT_EXAMINER)
    data = v.body()
    v.opt_str(data, "conclusion_note", 0, 500)
    presentation = must_find("presentations", presentation_id)

    status = presentation["examination_status"]
    if status != "UNDER_EXAMINATION":
        if status == "RECEIVED":
            bail("ERR_PRESENTATION_NOT_EXAMINABLE")
        bail("ERR_PRESENTATION_ALREADY_CONCLUDED")

    screening_review_gate(presentation)
    examination_open(presentation)

    count = ledger.recompute_discrepancy_count(presentation)
    presentation["examination_status"] = "COMPLYING" if count == 0 else "DISCREPANT"
    presentation["examined_by_user_id"] = principal.user_id
    touch(presentation)
    return ok(public(presentation))


# --------------------------------------------------------------------------
# waiver requests
# --------------------------------------------------------------------------

@bp.post("/presentations/<presentation_id>/waiver-requests")
def request_waiver(presentation_id):
    principal = require(DOCUMENT_EXAMINER)
    data = v.body()
    codes = v.req_str_array(data, "discrepancy_codes", min_items=1, max_items=10,
                            no_duplicates=True)
    v.opt_str(data, "request_note", 0, 500)
    presentation = must_find("presentations", presentation_id)

    # one live request at a time -- checked before the state guard, otherwise a
    # presentation parked in WAIVER_REQUESTED could never report this error
    for existing in ledger.waivers_of_presentation(presentation_id):
        if existing["status"] == "PENDING":
            bail("ERR_LIVE_REQUEST_EXISTS")

    status = presentation["examination_status"]
    if status != "DISCREPANT":
        if status in ("RECEIVED", "UNDER_EXAMINATION"):
            bail("ERR_PRESENTATION_NOT_EXAMINABLE")
        bail("ERR_PRESENTATION_ALREADY_CONCLUDED")

    screening_review_gate(presentation)

    identified = {}
    for row in ledger.discrepancies_of_presentation(presentation_id):
        if row["status"] == "IDENTIFIED":
            identified[row["code"]] = row
    for code in codes:
        row = identified.get(code)
        if row is None or row["severity"] != "MINOR":
            bail("ERR_DISCREPANCY_CODE_UNKNOWN")

    requested_at = clock_instant()
    row = new_row(
        presentation_id=presentation_id,
        discrepancy_codes=list(codes),
        requested_at=requested_at,
        deadline_at=calc.waiver_deadline(clock_date(), presentation.get("examination_deadline")),
        status="PENDING",
        responded_at=None,
        applicant_note=None,
        requested_by_user_id=principal.user_id,
    )
    db.waivers[row["id"]] = row

    presentation["examination_status"] = "WAIVER_REQUESTED"
    touch(presentation)
    return created(public(row))


@bp.post("/waiver-requests/<waiver_id>/respond")
def respond_waiver(waiver_id):
    principal = require(APPLICANT_USER)
    waiver, deferred = pending("waivers", waiver_id)
    if waiver is not None:
        presentation = db.presentations.get(waiver["presentation_id"]) or {}
        credit = db.credits.get(presentation.get("credit_id")) or {}
        if credit.get("applicant_id") != principal.user_id:
            bail("ERR_PRINCIPAL_NOT_PARTY")

    data = v.body()
    decision = v.req_enum(data, "decision", WAIVER_DECISIONS)
    applicant_note = v.opt_str(data, "applicant_note", 0, 500)
    raise_pending(deferred)

    if waiver["status"] != "PENDING":
        bail("ERR_WAIVER_NOT_PENDING")
    if clock_instant() > waiver["deadline_at"]:
        bail("ERR_WAIVER_WINDOW_CLOSED")

    presentation = db.presentations.get(waiver["presentation_id"])
    cited = set(waiver["discrepancy_codes"])
    target = "WAIVED" if decision == "GRANT" else "UPHELD"
    for row in ledger.discrepancies_of_presentation(waiver["presentation_id"]):
        if row["status"] == "IDENTIFIED" and row["code"] in cited:
            row["status"] = target
            touch(row)

    waiver["status"] = "GRANTED" if decision == "GRANT" else "DENIED"
    waiver["responded_at"] = clock_instant()
    waiver["applicant_note"] = applicant_note
    touch(waiver)

    if presentation is not None:
        refresh_presentation_examination(presentation)
        touch(presentation)
    return ok(public(waiver))


# --------------------------------------------------------------------------
# refusal
# --------------------------------------------------------------------------

@bp.post("/presentations/<presentation_id>/refuse")
def refuse_presentation(presentation_id):
    require(DOCUMENT_EXAMINER)
    data = v.body()
    disposal_instruction = v.req_enum(data, "disposal_instruction", DISPOSAL_INSTRUCTIONS)
    v.opt_str(data, "refusal_note", 0, 500)
    presentation = must_find("presentations", presentation_id)

    status = presentation["examination_status"]
    if status != "DISCREPANT":
        if status == "WAIVER_REQUESTED":
            bail("ERR_WAIVER_RESPONSE_PENDING")
        if status in ("RECEIVED", "UNDER_EXAMINATION"):
            bail("ERR_PRESENTATION_NOT_EXAMINABLE")
        bail("ERR_PRESENTATION_ALREADY_CONCLUDED")

    for existing in ledger.waivers_of_presentation(presentation_id):
        if existing["status"] == "PENDING":
            bail("ERR_LIVE_REQUEST_EXISTS")

    examination_open(presentation)

    for row in ledger.discrepancies_of_presentation(presentation_id):
        if row["status"] == "IDENTIFIED":
            row["status"] = "UPHELD"
            touch(row)

    presentation["examination_status"] = "REFUSED"
    presentation["refusal_notice_sent_at"] = clock_instant()
    presentation["disposal_instruction"] = disposal_instruction
    if presentation["settlement_status"] == "UNSETTLED":
        presentation["settlement_status"] = "VOID"
    ledger.recompute_discrepancy_count(presentation)
    touch(presentation)

    credit = db.credits.get(presentation["credit_id"])
    if credit is not None:
        ledger.recompute_credit_drawable(credit)
    return ok(public(presentation))
