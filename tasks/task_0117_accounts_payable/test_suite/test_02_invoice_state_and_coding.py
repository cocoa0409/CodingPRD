"""Invoice state machine, coding, and the match (PRD §3.3, §3.4).

Each test translates exactly one corner-design instance.
"""
from test_helpers import (
    validate_success, validate_error,
    create_invoice_line_payload,
    setup_master_data, create_vendor, capture_invoice, add_line, create_lined_invoice,
    create_gl_account, create_purchase_order, code_invoice,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_invoice_initial_state_is_captured(api):
    """PRD §3.3: "Capture normally lands the invoice in `CAPTURED`."

    Design: Corner/state_machines/invoice_initial_state_is_captured
    """
    vendor = create_vendor(legal_name="Init", payment_method="ACH")
    resp = api.create_invoice(
        {"vendor_id": vendor["id"], "invoice_number": "INIT-1", "invoice_date": "2026-05-01"},
        CLERK)
    data = validate_success(resp, 201)
    assert data["status"] == "CAPTURED"


def test_invoice_low_ocr_confidence_starts_coding_review(api):
    """PRD §3.3: "if `ocr_confidence` is below the confidence floor of 0.80, the
    captured invoice is instead placed directly into `CODING_REVIEW`".

    Design: Corner/state_machines/invoice_low_ocr_confidence_starts_coding_review
    """
    vendor = create_vendor(legal_name="Blur", payment_method="ACH")
    resp = api.create_invoice(
        {"vendor_id": vendor["id"], "invoice_number": "OCR-LOW",
         "invoice_date": "2026-05-01", "ocr_confidence": 0.5}, CLERK)
    data = validate_success(resp, 201)
    assert data["status"] == "CODING_REVIEW"


def test_submit_approval_from_captured_invalid_state(api):
    """PRD §3.5: "Submission is permitted only from `MATCHED`".
    PRD §2.4: "for any endpoint that drives a state machine, whether the target
    resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/submit_approval_from_captured_invalid_state
    """
    setup_master_data()
    vendor = create_vendor(legal_name="Cap", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="CAP-1")
    add_line(inv["id"], 1000)
    resp = api.submit_invoice_for_approval(inv["id"], CLERK)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_code_invoice_with_no_lines_invalid_state(api):
    """PRD §3.4: "Running the match requires the invoice to have at least one line and a
    `total_amount_cents` greater than 0".

    Design: Corner/state_machines/code_invoice_with_no_lines_invalid_state
    """
    vendor = create_vendor(legal_name="Empty", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="EMPTY-1")
    resp = api.code_invoice(inv["id"], CLERK)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_reject_invoice_in_coding_review_reaches_terminal(api):
    """PRD §3.4: "a clerk may reject it outright, moving it to `REJECTED` and appending
    a `REJECTED` audit event."

    Design: Corner/state_machines/reject_invoice_in_coding_review_reaches_terminal
    """
    vendor = create_vendor(legal_name="Rej", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="REJ-1", ocr_confidence=0.4)
    resp = api.reject_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"


def test_terminal_rejected_cannot_be_coded_again(api):
    """PRD §3.3: "The full status vocabulary an invoice may occupy is `CAPTURED`,
    `CODING_REVIEW`, `MATCHED`, `PENDING_APPROVAL`, `APPROVED`, `SCHEDULED`, `PAID`,
    and `REJECTED`, the last of which is terminal."

    Design: Corner/state_machines/terminal_rejected_cannot_be_coded_again
    """
    vendor = create_vendor(legal_name="Term", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="TERM-1", ocr_confidence=0.4)
    validate_success(api.reject_invoice(inv["id"], CLERK), 200)
    resp = api.code_invoice(inv["id"], CLERK)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_duplicate_invoice_number_per_vendor_rejected(api):
    """PRD §3.4: "requires that no other invoice already exists with the same
    combination of `vendor_id` and `invoice_number` — the duplicate-detection check,
    which on collision rejects the match with `ERR_DUPLICATE_INVOICE`."

    Design: Corner/validations/duplicate_invoice_number_per_vendor_rejected
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Dup", payment_method="ACH")
    inv1 = create_lined_invoice(vendor["id"], 1000, invoice_number="DUP", invoice_date="2026-05-01")
    code_invoice(inv1["id"])
    inv2 = create_lined_invoice(vendor["id"], 2000, invoice_number="DUP", invoice_date="2026-05-02")
    resp = api.code_invoice(inv2["id"], CLERK)
    validate_error(resp, "ERR_DUPLICATE_INVOICE", 409)


def test_line_to_non_postable_gl_rejected(api):
    """PRD §3.3: "Adding a line that codes to a missing or non-postable GL account is
    rejected with `ERR_GL_ACCOUNT_NOT_POSTABLE`."

    Design: Corner/validations/line_to_non_postable_gl_rejected
    """
    create_gl_account(code="9000", name="RollUp", is_postable=False)
    vendor = create_vendor(legal_name="GL", payment_method="ACH")
    inv = capture_invoice(vendor["id"], invoice_number="GL-1")
    resp = api.add_invoice_line(inv["id"],
                                create_invoice_line_payload(gl_account_code="9000", amount_cents=1000),
                                CLERK)
    validate_error(resp, "ERR_GL_ACCOUNT_NOT_POSTABLE", 422)


def test_non_po_invoice_zero_variance_matches(api):
    """PRD §3.4: "For a `NON_PO` invoice there is nothing to match against, so the
    variance is 0."
    PRD §3.3: "it is `NON_PO` when no PO is referenced".

    Design: Corner/calculations/non_po_invoice_zero_variance_matches
    """
    create_gl_account()
    vendor = create_vendor(legal_name="NP", payment_method="ACH")
    inv = create_lined_invoice(vendor["id"], 77777, invoice_number="NPV-1")
    resp = api.code_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["match_type"] == "NON_PO"
    assert data["variance_cents"] == 0
    assert data["status"] == "MATCHED"


def test_code_response_reflects_match_immediately(api):
    """PRD §3.4: "On a successful match the system computes the match type and the
    variance, records the acting operator into `coded_by`".
    PRD §3.4: "For a `THREE_WAY` invoice the variance is the invoice's
    `total_amount_cents` minus the purchase order's `received_amount_cents`".

    Design: Corner/consistency_model/code_response_reflects_match_immediately
    """
    create_gl_account()
    vendor = create_vendor(legal_name="Imm", payment_method="ACH")
    po = create_purchase_order(vendor["id"], ordered_amount_cents=100000)
    from test_helpers import create_posted_receipt
    create_posted_receipt(po["id"], 100000)
    inv = create_lined_invoice(vendor["id"], 100500, po_id=po["id"], invoice_number="IMM-1",
                               invoice_date="2026-05-10")
    resp = api.code_invoice(inv["id"], CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "MATCHED"
    assert data["variance_cents"] == 500, f"expected 500, got {data['variance_cents']}"
