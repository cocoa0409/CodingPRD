"""Post-release amendment and refunds (three reasons, two calc variants).

PRD anchors: §3.9 (amendment), §3.10 (refunds).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    setup_released_declaration,
    setup_amended_declaration,
    setup_returned_order_with_paid_declaration,
    setup_under_review_declaration,
    create_refund,
    create_refund_payload,
    submit_refund,
    approve_refund,
    reject_refund,
    execute_refund,
    amend_declaration_payload,
    make_declarant_headers,
    make_importer_headers,
    assert_refund,
    assert_declaration,
    DOC_TYPE_RETURN,
    DOC_TYPE_CANCELLATION,
    DOC_TYPE_AMENDMENT,
)


# ---------------------------------------------------------------------------
# Amendment
# ---------------------------------------------------------------------------
def test_amend_released_declaration(api):
    """PRD §3.9: "A declarant may file a post-release amendment as long
    as the linked PaymentNotice is in PAID and no EXECUTED Refund exists
    for the declaration. ... and transitions the declaration from
    RELEASED to AMENDED."
    """
    ctx = setup_amended_declaration()
    assert ctx.declaration["status"] == "AMENDED"


def test_finalize_amendment_returns_to_released(api):
    """PRD §3.9: "A customs officer subsequently finalizes the amendment,
    transitioning it from AMENDED back to RELEASED and emitting a
    DECLARATION_STATUS_CHANGE audit event."
    """
    ctx = setup_amended_declaration()
    res = api.finalize_amendment(
        ctx.declaration["id"], TEST_USERS["customs_officer_headers"]
    )
    finalized = validate_success(res)
    assert finalized["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Refund creation + submission preconditions
# ---------------------------------------------------------------------------
def test_create_refund_initial_state_is_draft(api):
    """PRD §3.10: "A refund draft is created against a declaration_id
    along with the refund_reason and an array of supporting_documents
    (each entry of the form {doc_type, voucher_url})."
    """
    ctx = setup_amended_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant,
        refund_reason="ERRONEOUS_DECLARATION",
    )
    assert_refund(refund)
    assert refund["status"] == "DRAFT"


def test_return_refund_requires_order_returned(api):
    """PRD §3.10: "The cross-entity guard then matches the refund reason
    to the order's status: a RETURN refund requires the parent order to
    be in RETURNED ... A mismatch on the cross-entity guard yields
    ERR_ORDER_NOT_ELIGIBLE."

    Claim: submitting a RETURN refund on an order still in RELEASED
    yields ERR_ORDER_NOT_ELIGIBLE.
    """
    ctx = setup_released_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant,
        refund_reason="RETURN",
        supporting_documents=[
            {"doc_type": DOC_TYPE_RETURN, "voucher_url": "https://x/return"},
        ],
    )
    res = api.submit_refund(
        refund["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_ORDER_NOT_ELIGIBLE", expected_status=409)


def test_return_refund_succeeds_after_order_returned(api):
    """PRD §3.10: "a RETURN refund requires the parent order to be in
    RETURNED ... For RETURN refunds, the refundable amount is the entire
    PaymentNotice.amount_cny_minor — the goods never effectively cleared,
    so the full tax is returned."
    """
    ctx = setup_returned_order_with_paid_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant, refund_reason="RETURN",
    )
    res = api.submit_refund(
        refund["id"], make_declarant_headers(ctx.declarant["id"])
    )
    submitted = validate_success(res)
    assert submitted["status"] == "SUBMITTED"
    assert (
        submitted["refundable_amount_cny_minor"]
        == ctx.payment_notice["amount_cny_minor"]
    )


def test_return_refund_missing_documents(api):
    """PRD §3.10: "a RETURN refund must include a document of type
    SHIPMENT_RETURN_RECEIPT, an ORDER_CANCELLATION refund must include
    CANCELLATION_AGREEMENT, and an ERRONEOUS_DECLARATION refund must
    include AMENDMENT_DECISION; missing the required type yields
    ERR_REFUND_DOCUMENTS_INCOMPLETE."

    Claim: a RETURN refund with non-matching documents → 422
    ERR_REFUND_DOCUMENTS_INCOMPLETE on submit.
    """
    ctx = setup_returned_order_with_paid_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant, refund_reason="RETURN",
        supporting_documents=[
            {"doc_type": "RANDOM_DOC", "voucher_url": "https://x/r"},
        ],
    )
    res = api.submit_refund(
        refund["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_REFUND_DOCUMENTS_INCOMPLETE", expected_status=422)


def test_erroneous_refund_with_higher_amended_tax_rejected(api):
    """PRD §3.10: "For ERRONEOUS_DECLARATION refunds only, an additional
    fiscal eligibility check fires: the post-amendment
    Declaration.total_tax_cny_minor must be strictly less than
    PaymentNotice.amount_cny_minor (the original snapshot); when the
    amendment raised the tax instead of lowering it — that is, when the
    post-amendment total is at or above the snapshot — the refund is
    rejected at this guard with ERR_REFUND_NOT_ELIGIBLE, before the
    amount calculation runs."

    Claim: when the declaration's total_tax equals the notice snapshot
    (no amendment lowered it), an ERRONEOUS_DECLARATION refund is
    rejected with ERR_REFUND_NOT_ELIGIBLE.
    """
    # setup_amended_declaration leaves the line set unchanged, so taxes
    # recompute identically — total_tax == notice.amount.
    ctx = setup_amended_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant,
        refund_reason="ERRONEOUS_DECLARATION",
    )
    res = api.submit_refund(
        refund["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_REFUND_NOT_ELIGIBLE", expected_status=409)


# ---------------------------------------------------------------------------
# Approve / reject / execute
# ---------------------------------------------------------------------------
def test_full_refund_lifecycle(api):
    """PRD §3.10: "A submitted refund is decided by a customs officer —
    approval transitions it from SUBMITTED to APPROVED ...
    Approved refunds are then disbursed by a finance operator,
    transitioning from APPROVED to EXECUTED; on execution,
    executed_amount_cny_minor is set equal to refundable_amount_cny_minor".
    """
    ctx = setup_returned_order_with_paid_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant, refund_reason="RETURN",
    )
    submitted = submit_refund(refund, ctx.declarant)
    approved = approve_refund(submitted)
    executed = execute_refund(approved)
    assert executed["status"] == "EXECUTED"
    assert (
        executed["executed_amount_cny_minor"]
        == executed["refundable_amount_cny_minor"]
    )


def test_refund_rejection_records_reason_and_no_disbursement(api):
    """PRD §3.10: "rejection transitions it from SUBMITTED to REJECTED,
    persists the customs officer's rejection_reason, and emits a
    REFUND_DECISION event marked rejected."
    """
    ctx = setup_returned_order_with_paid_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant, refund_reason="RETURN",
    )
    submitted = submit_refund(refund, ctx.declarant)
    res = api.reject_refund(
        submitted["id"], {"rejection_reason": "duplicate claim"},
        TEST_USERS["customs_officer_headers"],
    )
    rejected = validate_success(res)
    assert rejected["status"] == "REJECTED"
    assert rejected.get("rejection_reason") == "duplicate claim"
    # Branch asymmetry: rejected refund has NOT been executed.
    # The executed_amount_cny_minor default is 0 (PRD §1.1 default for
    # this field per scaffold; PRD §3.10 says the disbursement happens
    # only on EXECUTED). We assert it's 0, consistent with the rejection
    # path's "no executed_amount" invariant from PRD §3.10.
    assert rejected.get("executed_amount_cny_minor", 0) == 0


# ---------------------------------------------------------------------------
# Cancellation refund
# ---------------------------------------------------------------------------
def test_cancellation_refund_requires_cancelled_order(api):
    """PRD §3.10: "an ORDER_CANCELLATION refund requires the parent
    order to be in CANCELLED ... A mismatch on the cross-entity guard
    yields ERR_ORDER_NOT_ELIGIBLE."

    Claim: an ORDER_CANCELLATION refund on a still-RELEASED order yields
    ERR_ORDER_NOT_ELIGIBLE.
    """
    ctx = setup_released_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant,
        refund_reason="ORDER_CANCELLATION",
        supporting_documents=[
            {"doc_type": DOC_TYPE_CANCELLATION,
             "voucher_url": "https://x/cancel"},
        ],
    )
    res = api.submit_refund(
        refund["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_ORDER_NOT_ELIGIBLE", expected_status=409)
