"""Dispute negotiation cycle, the accept cascade, invoice revert branch, ledger
conservation, validation priority, and the fiscal / state gates on dispute open."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_invoice_with_line, setup_submitted_dispute, setup_vendor_responded_dispute,
    setup_posted_allocation,
    new_dispute, vendor_respond, analyst_resubmit,
    create_dispute_payload, respond_dispute_payload, resubmit_dispute_payload,
    make_vendor_headers, TEST_USERS,
)

_ANALYST = TEST_USERS["analyst_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / dispute_negotiation_cycle
# ---------------------------------------------------------------------------

def test_resubmit_moves_dispute_to_resubmitted_and_increments_round(api):
    """PRD §3.5: "A resubmission overwrites claimed_credit_cents, increments round_count by one,
    and moves the dispute to RESUBMITTED — from which the vendor may respond again, forming the
    VENDOR_RESPONDED -> RESUBMITTED -> VENDOR_RESPONDED negotiation loop."

    Design: Difficulty/non_linear_state_machine/dispute_negotiation_cycle
    """
    scen = setup_vendor_responded_dispute(
        api, line_billed_amount_cents=100000, disputed_amount_cents=9500,
        claimed_credit_cents=9500, offered_credit_cents=6000, response_type="PARTIAL")
    d = validate_success(api.resubmit_dispute(
        scen["dispute"]["id"], resubmit_dispute_payload(9500), _ANALYST))
    assert d["status"] == "RESUBMITTED", f"status should be RESUBMITTED, got {d['status']}"
    assert d["round_count"] == 1, f"round_count should be 1, got {d['round_count']}"


def test_vendor_can_respond_again_after_resubmit(api):
    """PRD §3.5: "A response records the classification and offer and moves the dispute to
    VENDOR_RESPONDED."
    PRD §3.5: "the offered credit may not exceed the current claimed_credit_cents"

    After resubmit (round 1) the vendor responds again with a higher offer 8000
    (<= claimed 9500) -> VENDOR_RESPONDED, offered_credit_cents 8000.

    Design: Difficulty/non_linear_state_machine/dispute_negotiation_cycle
    """
    scen = setup_vendor_responded_dispute(
        api, line_billed_amount_cents=100000, disputed_amount_cents=9500,
        claimed_credit_cents=9500, offered_credit_cents=6000, response_type="PARTIAL")
    analyst_resubmit(api, scen["dispute"]["id"], 9500)
    d = validate_success(api.respond_dispute(
        scen["dispute"]["id"], respond_dispute_payload("PARTIAL", 8000),
        make_vendor_headers(scen["vendor"]["id"])))
    assert d["status"] == "VENDOR_RESPONDED", f"status should be VENDOR_RESPONDED, got {d['status']}"
    assert d["offered_credit_cents"] == 8000, f"offered should be 8000, got {d['offered_credit_cents']}"


# ---------------------------------------------------------------------------
# non_linear_state_machine / invoice_dispute_revert_branch
# ---------------------------------------------------------------------------

def test_withdraw_reverts_invoice_to_under_review(api):
    """PRD §3.5: "if no open disputes remain on the invoice, the invoice reverts from DISPUTED to
    UNDER_REVIEW."
    PRD §3.5: "it bubbles up: an invoice sitting in UNDER_REVIEW is moved to DISPUTED when one of
    its lines enters dispute."

    Opening the dispute drove the invoice UNDER_REVIEW -> DISPUTED; withdrawing the only dispute
    reverts it DISPUTED -> UNDER_REVIEW.

    Design: Difficulty/non_linear_state_machine/invoice_dispute_revert_branch
    """
    scen = setup_submitted_dispute(api, line_billed_amount_cents=100000,
                                   disputed_amount_cents=9500, claimed_credit_cents=9500)
    disputed = validate_success(api.get_invoice(scen["invoice"]["id"], _ANALYST))
    assert disputed["status"] == "DISPUTED", f"invoice should be DISPUTED first, got {disputed['status']}"
    validate_success(api.withdraw_dispute(scen["dispute"]["id"], _ANALYST))
    invoice = validate_success(api.get_invoice(scen["invoice"]["id"], _ANALYST))
    assert invoice["status"] == "UNDER_REVIEW", f"invoice should revert to UNDER_REVIEW, got {invoice['status']}"


def test_withdraw_returns_line_to_billed(api):
    """PRD §3.5: "It returns the line from DISPUTED back to BILLED with no change to its
    credited_amount_cents or net_amount_cents"

    Design: Difficulty/non_linear_state_machine/invoice_dispute_revert_branch
    """
    scen = setup_submitted_dispute(api, line_billed_amount_cents=100000,
                                   disputed_amount_cents=9500, claimed_credit_cents=9500)
    d = validate_success(api.withdraw_dispute(scen["dispute"]["id"], _ANALYST))
    assert d["status"] == "WITHDRAWN", f"dispute should be WITHDRAWN, got {d['status']}"
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["status"] == "BILLED", f"line should return to BILLED, got {line['status']}"


# ---------------------------------------------------------------------------
# transitive_cascade / accept_dispute_cascade_depth3
# ---------------------------------------------------------------------------

def _accept_setup(api):
    scen = setup_posted_allocation(api, line_billed_amount_cents=100000, owner_user_id="own_ops")
    dispute = new_dispute(api, scen["line"]["id"], 8000, 8000)
    dispute = vendor_respond(api, dispute["id"], scen["vendor"]["id"], "PARTIAL", 8000)
    scen["dispute"] = dispute
    return scen


def test_accept_credits_line_and_raises_contract_recovered(api):
    """PRD §3.5: "The credited line moves from DISPUTED to CREDITED: the credit amount is added
    to the line's credited_amount_cents, and the line's net_amount_cents is recomputed as
    billed_amount_cents minus credited_amount_cents. The parent contract's total_recovered_cents
    has the credit amount added to it"

    credit 8000: credited_amount_cents 8000, net 100000-8000=92000, contract total_recovered 8000.

    Design: Difficulty/transitive_cascade/accept_dispute_cascade_depth3
    """
    scen = _accept_setup(api)
    validate_success(api.accept_dispute(scen["dispute"]["id"], _ANALYST))
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["credited_amount_cents"] == 8000, f"credited should be 8000, got {line['credited_amount_cents']}"
    assert line["net_amount_cents"] == 92000, f"net should be 92000, got {line['net_amount_cents']}"
    contract = validate_success(api.get_contract(scen["contract"]["id"], _ANALYST))
    assert contract["total_recovered_cents"] == 8000, \
        f"contract total_recovered should be 8000, got {contract['total_recovered_cents']}"


def test_accept_reverses_allocation_and_reverts_invoice(api):
    """PRD §3.5: "Any allocations already created on that line — whether still DRAFT or already
    POSTED — are moved to REVERSED, because the amount they charged back is no longer the correct
    net. Finally, if that was the last open dispute on the invoice, the invoice reverts from
    DISPUTED back to UNDER_REVIEW."

    Design: Difficulty/transitive_cascade/accept_dispute_cascade_depth3
    """
    scen = _accept_setup(api)
    d = validate_success(api.accept_dispute(scen["dispute"]["id"], _ANALYST))
    assert d["status"] == "ACCEPTED", f"dispute should be ACCEPTED, got {d['status']}"
    allocs, _meta = validate_paginated(api.list_line_item_allocations(scen["line"]["id"], _ANALYST))
    posted = next(a for a in allocs if a["id"] == scen["allocation"]["id"])
    assert posted["status"] == "REVERSED", f"allocation should be REVERSED, got {posted['status']}"
    invoice = validate_success(api.get_invoice(scen["invoice"]["id"], _ANALYST))
    assert invoice["status"] == "UNDER_REVIEW", f"invoice should revert to UNDER_REVIEW, got {invoice['status']}"


# ---------------------------------------------------------------------------
# compensating_invariant / recovered_ledger_conserved_on_dispute_withdraw
# ---------------------------------------------------------------------------

def test_open_then_withdraw_leaves_recovered_ledger_at_zero(api):
    """PRD §2.7: "a dispute that is opened and later withdrawn — creating no credit — leaves
    total_recovered_cents unchanged across the whole open-then-withdraw cycle."
    PRD §3.5: "withdrawal creates no credit, so the contract's total_recovered_cents is left
    untouched: an open-then-withdraw cycle is a no-op on the recovery ledger."

    Design: Difficulty/compensating_invariant/recovered_ledger_conserved_on_dispute_withdraw
    """
    scen = setup_submitted_dispute(api, line_billed_amount_cents=100000,
                                   disputed_amount_cents=8000, claimed_credit_cents=8000)
    d = validate_success(api.withdraw_dispute(scen["dispute"]["id"], _ANALYST))
    assert d["status"] == "WITHDRAWN"
    contract = validate_success(api.get_contract(scen["contract"]["id"], _ANALYST))
    assert contract["total_recovered_cents"] == 0, \
        f"total_recovered should stay 0 after withdraw, got {contract['total_recovered_cents']}"
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["status"] == "BILLED", f"line should be BILLED after withdraw, got {line['status']}"


def test_withdraw_keeps_savings_summary_recovered_at_zero(api):
    """PRD §2.7: "the recovery-ledger invariant: a contract's total_recovered_cents reflects only
    credits that were actually issued, so a dispute that is opened and later withdrawn — creating
    no credit — leaves total_recovered_cents unchanged across the whole open-then-withdraw cycle."

    The per-contract savings rollup echoes the same conserved ledger value (0).

    Design: Difficulty/compensating_invariant/recovered_ledger_conserved_on_dispute_withdraw
    """
    scen = setup_submitted_dispute(api, line_billed_amount_cents=100000,
                                   disputed_amount_cents=8000, claimed_credit_cents=8000)
    validate_success(api.withdraw_dispute(scen["dispute"]["id"], _ANALYST))
    summary = validate_success(api.get_savings_summary(scen["contract"]["id"], _ANALYST))
    assert summary["total_recovered_cents"] == 0, \
        f"savings-summary total_recovered should be 0, got {summary['total_recovered_cents']}"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / dispute_state_beats_fiscal_line_not_disputable
# ---------------------------------------------------------------------------

def test_dispute_open_state_check_preempts_fiscal_ceiling(api):
    """PRD §2.9: "State — the target resource is in a state that permits the requested
    transition, else the applicable state error such as ERR_INVALID_STATE, ERR_LINE_NOT_DISPUTABLE
    ... (409)."
    PRD §3.5: "A dispute may only be opened on a line in BILLED status whose parent invoice is
    currently UNDER_REVIEW or DISPUTED; if the line is not BILLED, or the invoice is in neither of
    those states, the request is rejected with ERR_LINE_NOT_DISPUTABLE."

    Invoice still RECEIVED and an over-claim (999999 > billed 100000): the state check (priority 5)
    outranks the fiscal check (priority 9), so ERR_LINE_NOT_DISPUTABLE is returned.

    Design: Difficulty/priority_pair_validation_conflict/dispute_state_beats_fiscal_line_not_disputable
    """
    scen = setup_invoice_with_line(
        api, line_overrides={"billed_amount_cents": 100000, "billed_quantity": 60}, do_review=False)
    resp = api.create_dispute(scen["line"]["id"], create_dispute_payload(999999, 999999), _ANALYST)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_DISPUTABLE.value)


def test_dispute_open_state_failure_leaves_line_and_invoice_unchanged(api):
    """PRD §3.5: "A dispute may only be opened on a line in BILLED status whose parent invoice is
    currently UNDER_REVIEW or DISPUTED; if the line is not BILLED, or the invoice is in neither of
    those states, the request is rejected with ERR_LINE_NOT_DISPUTABLE."

    Because the state check pre-empts the fiscal ceiling, the rejected over-claim leaves the line
    BILLED and the invoice RECEIVED (no dispute created, no fiscal side effect).

    Design: Difficulty/priority_pair_validation_conflict/dispute_state_beats_fiscal_line_not_disputable
    """
    scen = setup_invoice_with_line(
        api, line_overrides={"billed_amount_cents": 100000, "billed_quantity": 60}, do_review=False)
    api.create_dispute(scen["line"]["id"], create_dispute_payload(999999, 999999), _ANALYST)
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["status"] == "BILLED", f"line should remain BILLED, got {line['status']}"
    invoice = validate_success(api.get_invoice(scen["invoice"]["id"], _ANALYST))
    assert invoice["status"] == "RECEIVED", f"invoice should remain RECEIVED, got {invoice['status']}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / dispute_open_requires_invoice_reviewed
# ---------------------------------------------------------------------------

def test_dispute_open_rejected_while_invoice_received(api):
    """PRD §3.5: "A dispute may only be opened on a line in BILLED status whose parent invoice is
    currently UNDER_REVIEW or DISPUTED; if the line is not BILLED, or the invoice is in neither of
    those states, the request is rejected with ERR_LINE_NOT_DISPUTABLE."

    Fiscally valid claim (5000 <= billed 100000): only the cross-entity invoice-state gate fails.

    Design: Difficulty/cross_entity_state_dependency/dispute_open_requires_invoice_reviewed
    """
    scen = setup_invoice_with_line(
        api, line_overrides={"billed_amount_cents": 100000, "billed_quantity": 60}, do_review=False)
    resp = api.create_dispute(scen["line"]["id"], create_dispute_payload(5000, 5000), _ANALYST)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_DISPUTABLE.value)
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["status"] == "BILLED", f"line should remain BILLED, got {line['status']}"


def test_dispute_open_succeeds_once_invoice_reviewed(api):
    """PRD §3.5: "Opening a dispute puts it in SUBMITTED status ... It also drives the line's
    status to DISPUTED, and it bubbles up: an invoice sitting in UNDER_REVIEW is moved to
    DISPUTED when one of its lines enters dispute."

    The identical dispute-open succeeds once the invoice is UNDER_REVIEW.

    Design: Difficulty/cross_entity_state_dependency/dispute_open_requires_invoice_reviewed
    """
    scen = setup_invoice_with_line(
        api, line_overrides={"billed_amount_cents": 100000, "billed_quantity": 60}, do_review=True)
    d = validate_success(api.create_dispute(scen["line"]["id"], create_dispute_payload(5000, 5000), _ANALYST), 201)
    assert d["status"] == "SUBMITTED", f"dispute should be SUBMITTED, got {d['status']}"
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["status"] == "DISPUTED", f"line should be DISPUTED, got {line['status']}"


# ---------------------------------------------------------------------------
# Corner: state_machines / resubmit_beyond_max_rounds_returns_error
# ---------------------------------------------------------------------------

def test_resubmit_beyond_max_rounds_returns_error(api):
    """PRD §3.5: "only while round_count is below the cap of 2 rounds (ERR_MAX_ROUNDS_EXCEEDED
    once the cap is reached)"

    Two completed rounds bring round_count to 2; a third resubmit is rejected.

    Design: Corner/state_machines/resubmit_beyond_max_rounds_returns_error
    """
    scen = setup_vendor_responded_dispute(
        api, line_billed_amount_cents=100000, disputed_amount_cents=9500,
        claimed_credit_cents=9500, offered_credit_cents=5000, response_type="PARTIAL")
    d_id, v_id = scen["dispute"]["id"], scen["vendor"]["id"]
    analyst_resubmit(api, d_id, 9500)              # round_count -> 1, RESUBMITTED
    vendor_respond(api, d_id, v_id, "PARTIAL", 6000)
    analyst_resubmit(api, d_id, 9500)              # round_count -> 2, RESUBMITTED
    vendor_respond(api, d_id, v_id, "PARTIAL", 7000)
    resp = api.resubmit_dispute(d_id, resubmit_dispute_payload(9500), _ANALYST)
    validate_error(resp, ApiErrorId.ERR_MAX_ROUNDS_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Corner: validations / vendor_offer_exceeds_claim_returns_error
# ---------------------------------------------------------------------------

def test_vendor_offer_exceeds_claim_returns_error(api):
    """PRD §3.5: "the offered credit may not exceed the current claimed_credit_cents, else
    ERR_OFFER_EXCEEDS_CLAIM."

    offered 20000 > claimed 9500.

    Design: Corner/validations/vendor_offer_exceeds_claim_returns_error
    """
    scen = setup_submitted_dispute(api, line_billed_amount_cents=100000,
                                   disputed_amount_cents=9500, claimed_credit_cents=9500)
    resp = api.respond_dispute(
        scen["dispute"]["id"], respond_dispute_payload("PARTIAL", 20000),
        make_vendor_headers(scen["vendor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXCEEDS_CLAIM.value)


# ---------------------------------------------------------------------------
# Corner: validations / dispute_claim_exceeds_billed_returns_fiscal_error
# ---------------------------------------------------------------------------

def test_dispute_claim_exceeds_billed_returns_fiscal_error(api):
    """PRD §3.5: "The claimed credit may not exceed the line's billed_amount_cents; a claim above
    it is rejected with ERR_CREDIT_EXCEEDS_BILLED."

    On a reviewed invoice (state OK), claimed 200000 > billed 100000.

    Design: Corner/validations/dispute_claim_exceeds_billed_returns_fiscal_error
    """
    scen = setup_invoice_with_line(
        api, line_overrides={"billed_amount_cents": 100000, "billed_quantity": 60}, do_review=True)
    resp = api.create_dispute(scen["line"]["id"], create_dispute_payload(200000, 200000), _ANALYST)
    validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_BILLED.value)
