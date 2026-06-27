"""Returns, clawbacks, and their cascades, plus the compensating-balance
invariants.

Translates difficulty `transitive_cascade` (return on reserved claim) and
`compensating_invariant` (full-return zeroing, failed-cashout reversal), and
corner `calculations` / `validations` / `errors` return instances.
"""
from test_helpers import (
    validate_success, validate_error, api_client, TEST_USERS, make_member_headers,
    ApiErrorId,
    create_merchant, create_offer, create_member, create_verified_member,
    create_online_click_and_claim, create_in_store_approved_claim,
    create_cashout_reserving, set_clock, get_member,
    setup_member_with_two_available_claims, setup_member_with_available_online_claim,
    setup_processing_cashout,
)

_PA = TEST_USERS["platform_admin_headers"]
_RA = TEST_USERS["review_agent_headers"]
_FA = TEST_USERS["finance_admin_headers"]


def test_return_on_reserved_claim_fails_cashout_and_reverts_siblings(api):
    """PRD §3.9: "A return against a `RESERVED` claim ... the claim moves `RESERVED`
    to `CLAWED_BACK`, and then three cross-entity cascade steps follow. Step one
    transitions the owning cash-out to `FAILED`. Step two reverts every other claim
    that cash-out had reserved from `RESERVED` back to `AVAILABLE`. Step three
    recomputes the member's reserved and available balances accordingly."

    Design: Difficulty/transitive_cascade/return_on_reserved_claim_fails_cashout_and_reverts_siblings
    """
    member_id, _, c1, c2 = setup_member_with_two_available_claims(
        per_claim_purchase=10000, online_rate_bps=1000, email="mg@x.com")
    cashout = create_cashout_reserving(member_id, 2000, method="PAYPAL")  # reserves both
    resp = api.create_return_event(
        {"reward_claim_id": c1, "returned_amount_cents": 10000}, _FA)
    validate_success(resp, expected_status=201)
    claim1 = validate_success(api.get_reward_claim(c1, _FA))
    assert claim1["status"] == "CLAWED_BACK"
    co = validate_success(api.get_cashout(cashout["id"], _FA))
    assert co["status"] == "FAILED"
    claim2 = validate_success(api.get_reward_claim(c2, _FA))
    assert claim2["status"] == "AVAILABLE", \
        f"sibling reserved claim must revert to AVAILABLE, got {claim2['status']}"


def test_return_on_reserved_claim_recomputes_member_balances(api):
    """PRD §3.9: "Step three recomputes the member's reserved and available balances
    accordingly."
    PRD §3.9: "the claim moves `RESERVED` to `CLAWED_BACK`, and then three
    cross-entity cascade steps follow. Step one transitions the owning cash-out to
    `FAILED`. Step two reverts every other claim that cash-out had reserved from
    `RESERVED` back to `AVAILABLE`."

    After the cascade, the surviving sibling claim (1000) is back in the available
    balance and nothing remains reserved.

    Design: Difficulty/transitive_cascade/return_on_reserved_claim_fails_cashout_and_reverts_siblings
    """
    member_id, _, c1, c2 = setup_member_with_two_available_claims(
        per_claim_purchase=10000, online_rate_bps=1000, email="mg2@x.com")
    create_cashout_reserving(member_id, 2000, method="PAYPAL")
    validate_success(api.create_return_event(
        {"reward_claim_id": c1, "returned_amount_cents": 10000}, _FA), 201)
    member_now = get_member(member_id)
    assert member_now["reserved_balance_cents"] == 0, \
        f"reserved must drop to 0 after cascade, got {member_now['reserved_balance_cents']}"
    assert member_now["available_balance_cents"] == 1000, \
        f"surviving sibling must return to available, got {member_now['available_balance_cents']}"


def test_full_return_clawback_zeroes_reward_credit(api):
    """PRD §3.9: "A full return - where `returned_amount_cents` is at least the
    claim's `purchase_amount_cents` - claws back the entire `amount_cents`, so that
    the original reward credit and the clawback debit cancel exactly to zero."
    PRD §3.9: "A return against an `AVAILABLE` claim (matured but not yet reserved)
    moves it `AVAILABLE` to `CLAWED_BACK` and reduces the member's available
    balance by `clawback_cents`."

    Design: Difficulty/compensating_invariant/full_return_clawback_zeroes_reward_credit
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("mq@x.com")
    _, claim = create_in_store_approved_claim(member["id"], merchant["id"], offer["id"], 8000)
    set_clock("2026-02-15T00:00:00Z")  # mature claim to AVAILABLE
    resp = api.create_return_event(
        {"reward_claim_id": claim["id"], "returned_amount_cents": 8000}, _FA)
    event = validate_success(resp, expected_status=201)
    assert event["clawback_cents"] == 460, \
        f"full-return clawback must equal the 460 reward, got {event['clawback_cents']}"
    clawed = validate_success(api.get_reward_claim(claim["id"], _FA))
    assert clawed["status"] == "CLAWED_BACK"
    member_now = get_member(member["id"])
    assert member_now["available_balance_cents"] == 0
    assert member_now["pending_balance_cents"] == 0


def test_full_return_emits_clawback_ledger_entry(api):
    """PRD §3.9: "Reporting a return moves the claim to `CLAWED_BACK` (terminal) and
    emits a `CLAIM_CLAWBACK` ledger entry for the negative `clawback_cents`".
    PRD §2.6: "`CLAIM_CLAWBACK`, `CLAIM_EXPIRED`, and `CASHOUT_DEBIT` are negative".

    The audit-mirror side of the conservation: the clawback debit (-460) is logged
    alongside the forward maturation credit.

    Design: Difficulty/compensating_invariant/full_return_clawback_zeroes_reward_credit
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("mq2@x.com")
    hdr = make_member_headers(member["id"])
    _, claim = create_in_store_approved_claim(member["id"], merchant["id"], offer["id"], 8000)
    set_clock("2026-02-15T00:00:00Z")
    validate_success(api.create_return_event(
        {"reward_claim_id": claim["id"], "returned_amount_cents": 8000}, _FA), 201)
    entries = validate_success(
        api.list_member_ledger_entries(member["id"], hdr, params={"entry_type": "CLAIM_CLAWBACK"}))
    if isinstance(entries, dict):
        entries = [entries]
    clawbacks = [e for e in entries if e["entry_type"] == "CLAIM_CLAWBACK"]
    assert clawbacks, "a CLAIM_CLAWBACK ledger entry must be emitted"
    assert clawbacks[0]["amount_cents"] == -460, \
        f"clawback ledger entry must be -460, got {clawbacks[0]['amount_cents']}"


def test_failed_cashout_reversal_conserves_available_balance(api):
    """PRD §3.6: "When `outcome` is `FAILED`, the cash-out becomes `FAILED`, every
    claim it reserved reverts `RESERVED` to `AVAILABLE` with its `cashout_id`
    cleared, and the member's reserved balance falls while `net_cashoutable_cents`
    rises."

    Design: Difficulty/compensating_invariant/failed_cashout_reversal_conserves_available_balance
    """
    member_id, claim_id, cashout_id = setup_processing_cashout(
        purchase_amount_cents=10000, online_rate_bps=1000,
        requested_amount_cents=1000, email="mr@x.com")
    settled = validate_success(api.settle_cashout(cashout_id, {"outcome": "FAILED"}, _FA))
    assert settled["status"] == "FAILED"
    claim = validate_success(api.get_reward_claim(claim_id, _FA))
    assert claim["status"] == "AVAILABLE"
    member_now = get_member(member_id)
    assert member_now["available_balance_cents"] == 1000
    assert member_now["reserved_balance_cents"] == 0


def test_failed_cashout_clears_claim_cashout_id_and_restores_net(api):
    """PRD §3.5: "if the cash-out fails the claim reverts `RESERVED` to `AVAILABLE`,
    its `cashout_id` is cleared, reserved balance falls and `net_cashoutable_cents`
    rises again."

    Distinct observables from the available-balance assertion: the claim's
    cashout_id is null again and net_cashoutable is restored.

    Design: Difficulty/compensating_invariant/failed_cashout_reversal_conserves_available_balance
    """
    member_id, claim_id, cashout_id = setup_processing_cashout(
        purchase_amount_cents=10000, online_rate_bps=1000,
        requested_amount_cents=1000, email="mr2@x.com")
    validate_success(api.settle_cashout(cashout_id, {"outcome": "FAILED"}, _FA))
    claim = validate_success(api.get_reward_claim(claim_id, _FA))
    assert claim["status"] == "AVAILABLE"
    assert claim.get("cashout_id") in (None, ""), \
        f"cashout_id must be cleared after failure, got {claim.get('cashout_id')}"
    member_now = get_member(member_id)
    assert member_now["net_cashoutable_cents"] == 1000, \
        f"net cashoutable must be restored to 1000, got {member_now['net_cashoutable_cents']}"


def test_partial_return_proportional_clawback_ceil(api):
    """PRD §3.9: "The proportion is `returned_amount_cents` divided by the claim's
    `purchase_amount_cents`, clamped to the range 0 through 1, and `clawback_cents`
    is the claim's `amount_cents` multiplied by that proportion, rounded up
    (ceiling) so the platform never under-claws."

    Design: Corner/calculations/partial_return_proportional_clawback_ceil
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("pr@x.com")
    _, claim = create_in_store_approved_claim(member["id"], merchant["id"], offer["id"], 8000)
    set_clock("2026-02-15T00:00:00Z")
    resp = api.create_return_event(
        {"reward_claim_id": claim["id"], "returned_amount_cents": 4000}, _FA)
    event = validate_success(resp, expected_status=201)
    # proportion 4000/8000 = 0.5, ceil(460*0.5) = 230.
    assert event["clawback_cents"] == 230, \
        f"partial-return clawback must be 230, got {event['clawback_cents']}"
    clawed = validate_success(api.get_reward_claim(claim["id"], _FA))
    assert clawed["status"] == "CLAWED_BACK"


def test_return_exceeds_purchase_rejected(api):
    """PRD §3.9: "the `returned_amount_cents` may not exceed the claim's
    `purchase_amount_cents`, else `ERR_RETURN_EXCEEDS_PURCHASE` (HTTP 422)."

    Design: Corner/validations/return_exceeds_purchase_returns_422
    """
    member_id, _, claim_id = setup_member_with_available_online_claim(
        10000, online_rate_bps=1000, verified=False, email="rx@x.com")
    resp = api.create_return_event(
        {"reward_claim_id": claim_id, "returned_amount_cents": 99999}, _FA)
    validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_PURCHASE)


def test_return_on_paid_claim_rejected_already_terminal(api):
    """PRD §3.9: "A return may not be filed against a claim already in a terminal
    state - a claim in `PAID`, `CLAWED_BACK`, or `EXPIRED` rejects the return with
    `ERR_CLAIM_ALREADY_TERMINAL` (HTTP 409)".

    Design: Corner/errors/return_on_already_terminal_paid_claim_rejected
    """
    member_id, claim_id, cashout_id = setup_processing_cashout(
        purchase_amount_cents=10000, online_rate_bps=1000,
        requested_amount_cents=1000, email="tp@x.com")
    validate_success(api.settle_cashout(cashout_id, {"outcome": "PAID"}, _FA))
    paid_claim = validate_success(api.get_reward_claim(claim_id, _FA))
    assert paid_claim["status"] == "PAID"
    resp = api.create_return_event(
        {"reward_claim_id": claim_id, "returned_amount_cents": 10000}, _FA)
    validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL)
