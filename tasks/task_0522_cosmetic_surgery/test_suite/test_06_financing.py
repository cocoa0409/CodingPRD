"""Financing approval: lender-specific merchant fee / practice net, balance-fit gate,
quote-accepted precondition, and the approve->financed_cents->balance cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_quote_balance_identity,
    ApiErrorId, TEST_USERS, PROC_A, PROC_B,
    create_procedure, create_accepted_quote, create_presented_quote,
    create_financing_payload,
)

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_cherry_financing_net_and_fee(api):
    """PRD §3.8: "for a CHERRY application the merchant_fee_cents is 5 percent of
    approved_amount_cents ... in each case rounded half up to whole cents. The
    practice_net_cents ... is approved_amount_cents minus merchant_fee_cents."

    Design: Difficulty/dual_variant_calc/dual_variant_financing_lender_net
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    quote, _c, _p, _l = create_accepted_quote([procA["id"], procB["id"]], deposit_cents=266000)
    fin = get_success_data(api.submit_financing(
        create_financing_payload(quote["id"], lender="CHERRY",
                                 requested_amount_cents=500000), BILLING))
    resp = api.approve_financing(fin["id"], BILLING)
    data = validate_success(resp, 200)
    assert data["merchant_fee_cents"] == 25000    # 5% of 500000
    assert data["practice_net_cents"] == 475000   # 500000 - 25000


def test_carecredit_financing_net_and_fee(api):
    """PRD §3.8: "for a CARECREDIT application it is 3 percent of approved_amount_cents,
    in each case rounded half up to whole cents. The practice_net_cents — what the
    practice actually collects after the lender's cut — is approved_amount_cents minus
    merchant_fee_cents."

    Design: Difficulty/dual_variant_calc/dual_variant_financing_lender_net
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    quote, _c, _p, _l = create_accepted_quote([procA["id"], procB["id"]], deposit_cents=266000)
    fin = get_success_data(api.submit_financing(
        create_financing_payload(quote["id"], lender="CARECREDIT",
                                 requested_amount_cents=500000), BILLING))
    resp = api.approve_financing(fin["id"], BILLING)
    data = validate_success(resp, 200)
    assert data["merchant_fee_cents"] == 15000    # 3% of 500000
    assert data["practice_net_cents"] == 485000   # 500000 - 15000


def test_financing_exceeds_balance_rejected(api):
    """PRD §3.8: "the approved_amount_cents must not exceed the quote's balance_due_cents
    at approval time, otherwise ERR_FINANCING_EXCEEDS_BALANCE."

    Design: Corner/validations/error_financing_exceeds_balance
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_accepted_quote([procA["id"]], deposit_cents=170000)
    # balance is 850000 - 170000 = 680000; request 2000000 exceeds it
    fin = get_success_data(api.submit_financing(
        create_financing_payload(quote["id"], lender="CHERRY",
                                 requested_amount_cents=2000000), BILLING))
    resp = api.approve_financing(fin["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_FINANCING_EXCEEDS_BALANCE, 402)


def test_financing_approve_requires_quote_accepted(api):
    """PRD §3.8: "It requires the application to currently be SUBMITTED (otherwise
    ERR_INVALID_STATE), the parent quote to be ACCEPTED (otherwise
    ERR_QUOTE_NOT_ACCEPTED)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_financing_approve_requires_quote_accepted
    """
    procA = create_procedure(**PROC_A)
    # quote only PRESENTED (never accepted)
    quote, _c, _p, _l = create_presented_quote([procA["id"]], sign_consent=False)
    fin = get_success_data(api.submit_financing(
        create_financing_payload(quote["id"], lender="CARECREDIT",
                                 requested_amount_cents=100000), BILLING))
    resp = api.approve_financing(fin["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED, 409)


def test_financing_approve_from_draft_quote_rejected(api):
    """PRD §3.8: "the parent quote to be ACCEPTED (otherwise ERR_QUOTE_NOT_ACCEPTED)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_financing_approve_requires_quote_accepted
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_presented_quote([procA["id"]], sign_consent=False)
    fin = get_success_data(api.submit_financing(
        create_financing_payload(quote["id"], lender="CHERRY",
                                 requested_amount_cents=50000), BILLING))
    resp = api.approve_financing(fin["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED, 409)


def test_financing_approve_reconciles_balance(api):
    """PRD §3.8: "Approval then cascades onto the quote: financed_cents is increased by
    approved_amount_cents, and balance_due_cents is recomputed accordingly."

    Design: Difficulty/transitive_cascade/cascade_financing_approve_reconciles_balance
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    quote, _c, _p, _l = create_accepted_quote([procA["id"], procB["id"]], deposit_cents=266000)
    fin = get_success_data(api.submit_financing(
        create_financing_payload(quote["id"], lender="CARECREDIT",
                                 requested_amount_cents=500000), BILLING))
    get_success_data(api.approve_financing(fin["id"], BILLING))
    quote_after = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert quote_after["financed_cents"] == 500000
    # 1330000 - 266000 - 500000 = 564000
    assert quote_after["balance_due_cents"] == 564000


def test_financing_approve_preserves_balance_identity(api):
    """PRD §2.6: "Its balance_due_cents is always the quote's total_cents minus its
    deposit_paid_cents minus its financed_cents, and this derived field must be
    recomputed and kept consistent every time any of its three inputs changes."

    Design: Difficulty/transitive_cascade/cascade_financing_approve_reconciles_balance
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    quote, _c, _p, _l = create_accepted_quote([procA["id"], procB["id"]], deposit_cents=266000)
    fin = get_success_data(api.submit_financing(
        create_financing_payload(quote["id"], lender="CARECREDIT",
                                 requested_amount_cents=500000), BILLING))
    get_success_data(api.approve_financing(fin["id"], BILLING))
    quote_after = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert_quote_balance_identity(quote_after)
    assert quote_after["financed_cents"] == 500000
