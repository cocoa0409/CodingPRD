"""External event sync endpoints (SystemIntegrator only)."""

import db
import errors
import helpers
import response
import serializers
from flask import Blueprint
from middleware import auth_required
from services import audit


bp = Blueprint("events", __name__)


VALID_SIGNATURE_KINDS = {"DRAFT_LOCKED", "BILL_ISSUED"}


@bp.route("/_events/payment-received", methods=["POST"])
@auth_required("SystemIntegrator")
def payment_received():
    body = helpers.get_json_body()
    bill_id = body.get("bill_id")
    amount_cents = body.get("amount_cents")
    external_payment_id = body.get("external_payment_id")

    if not isinstance(bill_id, str) or not bill_id:
        errors.raise_error(errors.ERR_EVENT_PAYLOAD_INVALID, "bill_id required.")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        errors.raise_error(errors.ERR_EVENT_PAYLOAD_INVALID, "amount_cents must be an integer.")
    if not isinstance(external_payment_id, str) or not external_payment_id:
        errors.raise_error(errors.ERR_EVENT_PAYLOAD_INVALID, "external_payment_id required.")

    bill = db.bills.get(bill_id)
    if bill is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Bill {bill_id} not found.")

    # If the bill is no longer in ISSUED, distinguish "already paid/settled" (duplicate)
    # from "was never issued" (mismatch).
    if bill["status"] != "ISSUED":
        if bill["status"] in {"PAID", "SETTLED"}:
            errors.raise_error(
                errors.ERR_PAYMENT_DUPLICATE,
                "Bill already finalized; duplicate payment event.",
            )
        errors.raise_error(
            errors.ERR_PAYMENT_AMOUNT_MISMATCH,
            "Bill is not in ISSUED status.",
        )

    if amount_cents != bill["total_due_cents"]:
        errors.raise_error(
            errors.ERR_PAYMENT_AMOUNT_MISMATCH,
            "amount_cents does not match Bill.total_due_cents.",
        )

    bill["status"] = "PAID"
    helpers.bump(bill)
    return response.ok(serializers.bill_dict(bill))


@bp.route("/_events/document-signed", methods=["POST"])
@auth_required("SystemIntegrator")
def document_signed():
    body = helpers.get_json_body()
    draft_id = body.get("draft_id")
    signature_kind = body.get("signature_kind")
    external_signature_id = body.get("external_signature_id")

    if not isinstance(draft_id, str) or not draft_id:
        errors.raise_error(errors.ERR_EVENT_PAYLOAD_INVALID, "draft_id required.")
    if signature_kind not in VALID_SIGNATURE_KINDS:
        errors.raise_error(
            errors.ERR_EVENT_PAYLOAD_INVALID,
            "signature_kind must be one of {DRAFT_LOCKED, BILL_ISSUED}.",
        )
    if not isinstance(external_signature_id, str) or not external_signature_id:
        errors.raise_error(errors.ERR_EVENT_PAYLOAD_INVALID, "external_signature_id required.")

    draft = db.document_drafts.get(draft_id)
    if draft is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Draft {draft_id} not found.")

    if draft["status"] not in {"SIGNED_OFF", "LOCKED"}:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Draft must be SIGNED_OFF or LOCKED for an external signature event.",
        )

    audit.append(
        subject_type="DOCUMENT_DRAFT", subject_id=draft_id,
        action="EXTERNAL_SIGNATURE_RECORDED",
        payload_snapshot={
            "signature_kind": signature_kind,
            "external_signature_id": external_signature_id,
        },
    )
    return response.ok({
        "draft_id": draft_id,
        "signature_kind": signature_kind,
        "external_signature_id": external_signature_id,
        "recorded": True,
    })


@bp.route("/_events/court-filed", methods=["POST"])
@auth_required("SystemIntegrator")
def court_filed():
    body = helpers.get_json_body()
    evidence_id = body.get("evidence_id")
    court_filing_id = body.get("court_filing_id")

    if not isinstance(evidence_id, str) or not evidence_id:
        errors.raise_error(errors.ERR_EVENT_PAYLOAD_INVALID, "evidence_id required.")
    if not isinstance(court_filing_id, str) or not court_filing_id:
        errors.raise_error(errors.ERR_EVENT_PAYLOAD_INVALID, "court_filing_id required.")

    evidence = db.evidence_rows.get(evidence_id)
    if evidence is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Evidence {evidence_id} not found.")

    audit.append(
        subject_type="EVIDENCE", subject_id=evidence_id,
        action="COURT_FILED",
        payload_snapshot={"court_filing_id": court_filing_id},
    )
    return response.ok({
        "evidence_id": evidence_id,
        "court_filing_id": court_filing_id,
        "recorded": True,
    })
