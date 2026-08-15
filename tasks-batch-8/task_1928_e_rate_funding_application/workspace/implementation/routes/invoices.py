"""InvoiceSubmission endpoints: BEAR/SPI claims, review, approval, disbursement,
rejection/resubmission review loop (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_APPLICANT_ACCESS_DENIED, ERR_PROVIDER_ACCESS_DENIED,
    ERR_LINE_NOT_COMMITTED, ERR_SERVICES_NOT_STARTED,
    ERR_INVOICE_DEADLINE_PASSED, ERR_AUDIT_HOLD_ACTIVE,
    ERR_REIMBURSEMENT_EXCEEDS_REMAINING,
)
from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.calcs import tentative_reimbursement
from services.core import new_record, touch, retain_document, request_of_line
from util import CLOCK, parse_date
from validate import (
    get_body, check_allowed, req_str, req_int, req_enum, require_ref,
    require_path_resource,
)

bp = Blueprint("invoice_submissions", __name__, url_prefix="/erate")

CREATE_FIELDS = {"frn_line_id", "method", "gross_invoiced_cents",
                 "applicant_paid_cents"}
METHODS = ("BEAR", "SPI")


def _contract_provider_of_line(line):
    contract = db["contracts"].get(line["contract_id"])
    return contract["service_provider_id"] if contract else None


def _create_scope_check(caller, line, method):
    """Tier 3 ownership at creation: BEAR is filed by the applicant's own
    coordinator; SPI by the representative of the provider on the line's
    contract (submitted_by_provider_id comes from the caller identity)."""
    if method == "BEAR":
        freq = request_of_line(line)
        target_applicant = freq["applicant_id"] if freq else None
        if caller.role != "ApplicantCoordinator" \
                or caller.applicant_id is None \
                or caller.applicant_id != target_applicant:
            raise_error(ERR_APPLICANT_ACCESS_DENIED,
                        "a BEAR invoice may only be filed by the applicant's coordinator")
    else:  # SPI
        if caller.role != "VendorRepresentative" \
                or caller.provider_id is None \
                or caller.provider_id != _contract_provider_of_line(line):
            raise_error(ERR_PROVIDER_ACCESS_DENIED,
                        "an SPI invoice may only be filed by the contract's provider representative")


def _resubmit_scope_check(caller, invoice, line):
    """Resubmission ownership (PRD 2.1): SPI — the recorded submitting provider;
    BEAR — a user belonging to the line's applicant."""
    if invoice["method"] == "SPI":
        if caller.role != "VendorRepresentative" \
                or caller.user_id != invoice["submitted_by_provider_id"]:
            raise_error(ERR_PROVIDER_ACCESS_DENIED,
                        "an SPI invoice may only be resubmitted by its submitting provider")
    else:
        freq = request_of_line(line)
        target_applicant = freq["applicant_id"] if freq else None
        if caller.role != "ApplicantCoordinator" \
                or caller.applicant_id is None \
                or caller.applicant_id != target_applicant:
            raise_error(ERR_APPLICANT_ACCESS_DENIED,
                        "a BEAR invoice may only be resubmitted by the applicant's coordinator")


@bp.post("/invoice-submissions")
def create_invoice():
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator", "VendorRepresentative"])
    body = get_body()
    # Tier 3 ownership, resolved from the raw body peek (line + method).
    raw_line_id = body.get("frn_line_id")
    raw_method = body.get("method")
    line_peek = db["funding_request_lines"].get(raw_line_id) \
        if isinstance(raw_line_id, str) else None
    if line_peek is not None and raw_method in METHODS:
        _create_scope_check(caller, line_peek, raw_method)
    check_allowed(body, CREATE_FIELDS)
    frn_line_id = req_str(body, "frn_line_id")
    method = req_enum(body, "method", METHODS)
    gross_invoiced_cents = req_int(body, "gross_invoiced_cents", positive=True)
    paid_present = "applicant_paid_cents" in body and body.get("applicant_paid_cents") is not None
    if method == "BEAR":
        if not paid_present:
            raise_error(ERR_INVALID_REQUEST,
                        "applicant_paid_cents is required for a BEAR invoice")
        applicant_paid_cents = req_int(body, "applicant_paid_cents", positive=True)
        if applicant_paid_cents > gross_invoiced_cents:
            raise_error(ERR_INVALID_REQUEST,
                        "applicant_paid_cents exceeds gross_invoiced_cents")
    else:
        if paid_present:
            raise_error(ERR_INVALID_REQUEST,
                        "applicant_paid_cents is forbidden on an SPI invoice")
        applicant_paid_cents = None
    line = require_ref("funding_request_lines", frn_line_id, "frn_line_id")
    # Tier 3 (deferred when the peek could not resolve the line).
    _create_scope_check(caller, line, method)
    # State gates.
    if line["status"] != "COMMITTED":
        raise_error(ERR_LINE_NOT_COMMITTED, "the funding request line is not COMMITTED")
    freq = request_of_line(line)
    if not freq["services_started"]:
        raise_error(ERR_SERVICES_NOT_STARTED,
                    "services have not started on the line's funding request")
    # Temporal gate: closed invoice deadline (submission on the date is allowed).
    if CLOCK.today() > parse_date(line["invoice_deadline_date"]):
        raise_error(ERR_INVOICE_DEADLINE_PASSED,
                    "the line's invoice deadline has passed")
    rec = new_record("invoice_submissions", {
        "frn_line_id": frn_line_id,
        "method": method,
        "submitted_by_provider_id": caller.user_id if method == "SPI" else None,
        "gross_invoiced_cents": gross_invoiced_cents,
        "applicant_paid_cents": applicant_paid_cents,
        "approved_reimbursement_cents": None,
        "rejection_reason": None,
        "status": "SUBMITTED",
    })
    return success_object(public(rec), 201)


@bp.get("/invoice-submissions")
def list_invoices():
    return list_collection("invoice_submissions", {
        "frn_line_id": request.args.get("frn_line_id"),
        "submitted_by_provider_id": request.args.get("submitted_by_provider_id"),
        "status": request.args.get("status"),
        "method": request.args.get("method"),
    })


@bp.get("/invoice-submissions/<rid>")
def get_invoice(rid):
    return get_one("invoice_submissions", rid)


@bp.post("/invoice-submissions/<rid>/begin-review")
def begin_review(rid):
    caller = get_caller()
    check_role(caller, ["InvoiceProcessor"])
    body = get_body()
    check_allowed(body, set())
    invoice = require_path_resource("invoice_submissions", rid)
    if invoice["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "invoice is not SUBMITTED")
    invoice["status"] = "UNDER_REVIEW"
    touch(invoice)
    return success_object(public(invoice))


@bp.post("/invoice-submissions/<rid>/approve")
def approve(rid):
    caller = get_caller()
    check_role(caller, ["InvoiceProcessor"])
    body = get_body()
    check_allowed(body, set())
    invoice = require_path_resource("invoice_submissions", rid)
    if invoice["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION, "invoice is not UNDER_REVIEW")
    line = db["funding_request_lines"][invoice["frn_line_id"]]
    freq = request_of_line(line)
    applicant = db["applicants"][freq["applicant_id"]]
    # Compliance before fiscal (PRD 2.10): an active applicant audit hold blocks
    # approval before any reimbursement arithmetic is examined.
    if applicant["audit_hold_active"]:
        raise_error(ERR_AUDIT_HOLD_ACTIVE,
                    "an applicant-level audit hold blocks invoice approval")
    tentative = tentative_reimbursement(invoice, line, freq)
    if tentative > line["remaining_reimbursable_cents"]:
        # Equality is allowed and drains the remaining balance to exactly 0.
        raise_error(ERR_REIMBURSEMENT_EXCEEDS_REMAINING,
                    "tentative reimbursement exceeds the line's remaining reimbursable amount")
    invoice["approved_reimbursement_cents"] = tentative
    invoice["status"] = "APPROVED"
    touch(invoice)
    return success_object(public(invoice))


@bp.post("/invoice-submissions/<rid>/pay")
def pay(rid):
    caller = get_caller()
    check_role(caller, ["InvoiceProcessor"])
    body = get_body()
    check_allowed(body, set())
    invoice = require_path_resource("invoice_submissions", rid)
    if invoice["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "invoice is not APPROVED")
    line = db["funding_request_lines"][invoice["frn_line_id"]]
    approved = invoice["approved_reimbursement_cents"]
    line["reimbursed_cents"] += approved
    line["remaining_reimbursable_cents"] -= approved
    touch(line)
    invoice["status"] = "PAID"
    freq = request_of_line(line)
    retain_document("INVOICE_SUBMISSION", rid, freq["funding_cycle_id"],
                    "DISBURSEMENT_RECORD")
    touch(invoice)
    return success_object(public(invoice))


@bp.post("/invoice-submissions/<rid>/reject")
def reject(rid):
    caller = get_caller()
    check_role(caller, ["InvoiceProcessor"])
    body = get_body()
    check_allowed(body, {"rejection_reason"})
    rejection_reason = req_str(body, "rejection_reason")
    invoice = require_path_resource("invoice_submissions", rid)
    if invoice["status"] == "UNDER_REVIEW":
        # No money fields ever changed; nothing to unwind.
        pass
    elif invoice["status"] == "APPROVED":
        # Compensating action: approval revoked before any disbursement; the
        # line's ledger is untouched.
        invoice["approved_reimbursement_cents"] = None
    else:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "only UNDER_REVIEW or APPROVED invoices may be rejected")
    invoice["rejection_reason"] = rejection_reason
    invoice["status"] = "REJECTED"
    touch(invoice)
    return success_object(public(invoice))


@bp.post("/invoice-submissions/<rid>/resubmit")
def resubmit(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator", "VendorRepresentative"])
    existing = db["invoice_submissions"].get(rid)
    if existing is not None:
        line = db["funding_request_lines"].get(existing["frn_line_id"])
        if line is not None:
            _resubmit_scope_check(caller, existing, line)
    body = get_body()
    check_allowed(body, set())
    invoice = require_path_resource("invoice_submissions", rid)
    if invoice["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "invoice is not REJECTED")
    invoice["rejection_reason"] = None
    invoice["status"] = "UNDER_REVIEW"
    touch(invoice)
    return success_object(public(invoice))
