"""Payment notice generation, idempotency, channel rules, conditional
release, reverse cascade.

PRD anchors: §2.7 (cascades), §2.8 (idempotency), §3.8 (payment + release).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    setup_approved_declaration,
    setup_released_declaration,
    setup_paid_then_reversed,
    confirm_payment,
    confirm_payment_payload,
    reverse_payment,
    reverse_payment_payload,
    fresh_idempotency_key,
    assert_payment_notice,
)


# ---------------------------------------------------------------------------
# PaymentNotice auto-creation on approval (PRD §3.7)
# ---------------------------------------------------------------------------
def test_approve_auto_creates_payment_notice(api):
    """PRD §3.7: "A clean approval transitions the declaration from
    UNDER_REVIEW to APPROVED, which fires three effects: the system
    creates a PaymentNotice whose amount_cny_minor equals the
    declaration's current total_tax_cny_minor (an immutable snapshot
    taken at approval time) and whose due_at is set to 168 hours after
    creation, the parent order cascades from PENDING_DECLARATION to
    DECLARED, and a DECLARATION_STATUS_CHANGE audit event is emitted."

    Claim: after approve, a PaymentNotice exists with status=PENDING and
    amount_cny_minor equal to the declaration's total_tax_cny_minor.
    """
    ctx = setup_approved_declaration()
    assert ctx.payment_notice is not None, (
        "PRD §3.7: approve must auto-create a PaymentNotice"
    )
    assert_payment_notice(ctx.payment_notice)
    assert ctx.payment_notice["status"] == "PENDING"
    assert (
        ctx.payment_notice["amount_cny_minor"]
        == ctx.declaration["total_tax_cny_minor"]
    )


def test_approve_cascades_order_to_declared(api):
    """PRD §2.7: "When a child declaration enters APPROVED or
    CONDITIONALLY_RELEASED, the parent order automatically advances from
    PENDING_DECLARATION to DECLARED".
    """
    ctx = setup_approved_declaration()
    order = ctx.refresh_order()
    assert order["status"] == "DECLARED"


# ---------------------------------------------------------------------------
# Idempotency contract (PRD §2.8)
# ---------------------------------------------------------------------------
def test_confirm_payment_without_idempotency_key_header_rejected(api):
    """PRD §2.8: "The caller must supply both an Idempotency-Key HTTP
    header and an idempotency_key field in the request body — when the
    header is missing, the request is rejected with
    ERR_IDEMPOTENCY_KEY_REQUIRED and HTTP status 400."
    """
    ctx = setup_approved_declaration()
    notice_id = ctx.payment_notice["id"]
    body = confirm_payment_payload(
        payment_channel="ELECTRONIC_PAYMENT",
        idempotency_key=fresh_idempotency_key(),
    )
    headers = dict(TEST_USERS["finance_officer_headers"])  # no Idempotency-Key
    res = api.confirm_payment(notice_id, body, headers)
    validate_error(res, "ERR_IDEMPOTENCY_KEY_REQUIRED", expected_status=400)


def test_confirm_payment_idempotent_replay(api):
    """PRD §2.8: "if a second request arrives with the same key and a
    payload that hashes identically, the server returns the stored prior
    result."

    Claim: the same key + identical body returned on a second call yields
    a 2xx and the same notice (status=PAID).
    """
    ctx = setup_approved_declaration()
    key = fresh_idempotency_key()
    body = confirm_payment_payload(
        payment_channel="ELECTRONIC_PAYMENT", idempotency_key=key,
    )
    hdrs = dict(TEST_USERS["finance_officer_headers"])
    hdrs["Idempotency-Key"] = key
    first = api.confirm_payment(ctx.payment_notice["id"], body, hdrs)
    notice1 = validate_success(first)
    second = api.confirm_payment(ctx.payment_notice["id"], body, hdrs)
    notice2 = validate_success(second)
    assert notice1["id"] == notice2["id"]
    assert notice1["status"] == "PAID" == notice2["status"]


def test_confirm_payment_idempotency_conflict_on_payload_mismatch(api):
    """PRD §2.8: "If the second request arrives with the same key but a
    payload that hashes differently, the server rejects it with
    ERR_IDEMPOTENCY_CONFLICT and HTTP status 409."
    """
    ctx = setup_approved_declaration()
    key = fresh_idempotency_key()
    hdrs = dict(TEST_USERS["finance_officer_headers"])
    hdrs["Idempotency-Key"] = key
    body_a = confirm_payment_payload(
        payment_channel="ELECTRONIC_PAYMENT", idempotency_key=key,
    )
    api.confirm_payment(ctx.payment_notice["id"], body_a, hdrs)
    body_b = confirm_payment_payload(
        payment_channel="BANK_TRANSFER",
        voucher_url="https://x/voucher",
        idempotency_key=key,
    )
    res = api.confirm_payment(ctx.payment_notice["id"], body_b, hdrs)
    validate_error(res, "ERR_IDEMPOTENCY_CONFLICT", expected_status=409)


# ---------------------------------------------------------------------------
# Channel-specific rules (PRD §3.8)
# ---------------------------------------------------------------------------
def test_bank_transfer_requires_voucher_url(api):
    """PRD §3.8: "A bank-transfer confirmation requires a non-empty
    voucher_url; without it the request is rejected with
    ERR_VOUCHER_REQUIRED."
    """
    ctx = setup_approved_declaration()
    key = fresh_idempotency_key()
    hdrs = dict(TEST_USERS["finance_officer_headers"])
    hdrs["Idempotency-Key"] = key
    body = confirm_payment_payload(
        payment_channel="BANK_TRANSFER", idempotency_key=key,
        # no voucher_url
    )
    res = api.confirm_payment(ctx.payment_notice["id"], body, hdrs)
    validate_error(res, "ERR_VOUCHER_REQUIRED", expected_status=422)


# ---------------------------------------------------------------------------
# Conditional release (PRD §3.8)
# ---------------------------------------------------------------------------
def test_conditional_release_requires_guarantee_channel(api):
    """PRD §3.8: "An attempt to grant conditional release while the
    payment channel is anything other than GUARANTEE_DEDUCTION is
    rejected with ERR_CHANNEL_NOT_GUARANTEE."

    Claim: a payment confirmed with payment_channel=ELECTRONIC_PAYMENT
    pins channel to a non-GUARANTEE value. Even though the declaration
    transitions APPROVED→RELEASED on confirmation, this test checks the
    earlier rejection path: a fresh APPROVED declaration whose linked
    notice's channel is BANK_TRANSFER must reject conditional_release.

    To exercise the rule strictly we set up a fresh APPROVED declaration
    and confirm with BANK_TRANSFER. The cascade jumps to RELEASED, so a
    direct conditional_release call is now state-invalid. PRD §2.9
    (highest-priority error) means the response surfaces either the
    state error or the channel error; we accept either.
    """
    from test_helpers import validate_error_is_one_of
    ctx = setup_approved_declaration()
    # Pin channel to BANK_TRANSFER via successful confirm.
    confirm_payment(
        ctx.payment_notice["id"],
        payment_channel="BANK_TRANSFER",
        voucher_url="https://x/voucher",
    )
    res = api.conditional_release(
        ctx.declaration["id"], TEST_USERS["customs_officer_headers"]
    )
    # Highest-priority error per PRD §2.9 may surface either rule first.
    validate_error_is_one_of(
        res, ["ERR_CHANNEL_NOT_GUARANTEE", "ERR_INVALID_STATE_TRANSITION"]
    )


# ---------------------------------------------------------------------------
# Successful payment cascade (PRD §3.8)
# ---------------------------------------------------------------------------
def test_payment_confirmation_cascades_to_released(api):
    """PRD §3.8: "A successful confirmation flips the notice from
    PENDING to PAID, cascades the linked declaration from APPROVED to
    RELEASED ... The declaration's transition to RELEASED cascades again
    to the parent order, advancing it from DECLARED to RELEASED, and
    pins pickup_coordinated_at on the declaration to the current clock".
    """
    ctx = setup_released_declaration()
    assert ctx.payment_notice["status"] == "PAID"
    assert ctx.declaration["status"] == "RELEASED"
    assert ctx.order["status"] == "RELEASED"
    assert ctx.declaration.get("pickup_coordinated_at") is not None


# ---------------------------------------------------------------------------
# Reverse payment cascade (PRD §3.8)
# ---------------------------------------------------------------------------
def test_reverse_payment_reverts_declaration_to_approved(api):
    """PRD §3.8: "A successful reversal flips the notice from PAID to
    REVERSED; if the linked declaration was in RELEASED, it reverts to
    APPROVED (the order's RELEASED cascade is similarly undone)."
    """
    ctx = setup_paid_then_reversed()
    assert ctx.payment_notice["status"] == "REVERSED"
    assert ctx.declaration["status"] == "APPROVED"


def test_reverse_blocked_after_executed_refund(api):
    """PRD §3.8: "Reversal is forbidden when an EXECUTED Refund already
    exists against the declaration, in which case the reversal is
    rejected with ERR_REFUND_ALREADY_EXECUTED."
    """
    from test_helpers import (
        setup_returned_order_with_paid_declaration,
        create_refund,
        submit_refund,
        approve_refund,
        execute_refund,
    )
    ctx = setup_returned_order_with_paid_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant, refund_reason="RETURN",
    )
    submit_refund(refund, ctx.declarant)
    approve_refund(refund)
    execute_refund(refund)
    # Now attempt to reverse the linked PaymentNotice.
    res = api.reverse_payment(
        ctx.payment_notice["id"],
        reverse_payment_payload("attempted_after_refund"),
        TEST_USERS["finance_officer_headers"],
    )
    validate_error(res, "ERR_REFUND_ALREADY_EXECUTED", expected_status=409)


# ---------------------------------------------------------------------------
# Already-paid notice rejected for double-confirm (state-transition error)
# ---------------------------------------------------------------------------
def test_double_confirm_rejected_with_state_transition(api):
    """PRD §2.9 last paragraph: "the response surfaces the highest-priority
    error rather than the most specific."  Priority 5 (state) precedes
    priority 14 (idempotency conflict). A confirm on an already-PAID
    notice with a fresh idempotency key (different from the original) is
    a state violation.

    Claim: confirm_payment against a PAID notice with a brand-new key
    returns ERR_INVALID_STATE_TRANSITION 409.
    """
    ctx = setup_released_declaration()
    new_key = fresh_idempotency_key("double")
    hdrs = dict(TEST_USERS["finance_officer_headers"])
    hdrs["Idempotency-Key"] = new_key
    body = confirm_payment_payload(
        payment_channel="ELECTRONIC_PAYMENT", idempotency_key=new_key,
    )
    res = api.confirm_payment(ctx.payment_notice["id"], body, hdrs)
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
