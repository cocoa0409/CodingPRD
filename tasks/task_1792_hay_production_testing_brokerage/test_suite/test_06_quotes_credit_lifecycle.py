"""Quote lifecycle, credit reserve, and contract birth: expiry sweeps, the
credit-limit fiscal gate, accept/cancel conservation, and terminal lockdown.

Covers PRD §3.5 (buyers and quotes) and §3.6 (contracts).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_buyer,
    create_draft_quote,
    get_buyer,
    issue_quote,
    make_buyer_headers,
    set_clock,
    setup_accepted_contract,
    setup_pricing_bed,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_contract_tonnage_identity
from test_helpers.fixtures import accept_quote, find_contract_by_quote

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


def _issued_quote(credit_limit_cents, tons=12.0, quality_tier="PREMIUM"):
    """Pricing bed + buyer + ISSUED quote. Returns (buyer, issued_quote)."""
    setup_pricing_bed()
    buyer = create_buyer(credit_limit_cents=credit_limit_cents)
    quote = create_draft_quote(buyer["id"], quality_tier=quality_tier, tons=tons)
    issued = issue_quote(quote["id"], buyer["id"])
    return buyer, issued


# ===========================================================================
# priority_pair_validation_conflict / expired_quote_beats_credit_limit
# ===========================================================================

class TestExpiredQuoteBeatsCreditLimit:
    def test_expired_state_error_beats_credit_limit(self, api):
        """PRD §3.5: "First, if the current clock has passed `expires_at`, the
        quote auto-transitions to `EXPIRED` *before any other accept-time
        check*, and the acceptance fails with `ERR_QUOTE_EXPIRED`".

        The buyer's 1000-cent credit limit guarantees the fiscal check would
        also fail, but the earlier expiry guard wins the response.

        Design: Difficulty/priority_pair_validation_conflict/expired_quote_beats_credit_limit
        """
        buyer, issued = _issued_quote(1000)
        set_clock("2026-08-05T00:00:00Z")
        quote = validate_success(
            api_client.get_quote(issued["id"], make_buyer_headers(buyer["id"]))
        )
        resp = api_client.accept_quote(
            issued["id"],
            {"expected_quote_version": quote["version"]},
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)

    def test_clock_advance_sweeps_quote_to_expired(self, api):
        """PRD §2.4: "any quote still in `ISSUED` whose validity deadline has
        been passed by the new clock value is swept to `EXPIRED`."

        A quote issued at the default clock (2026-08-01T00:00Z, expiring 72h
        later) reads EXPIRED once the clock advances to 2026-08-05.

        Design: Difficulty/priority_pair_validation_conflict/expired_quote_beats_credit_limit
        """
        buyer, issued = _issued_quote(1000)
        set_clock("2026-08-05T00:00:00Z")
        quote = validate_success(
            api_client.get_quote(issued["id"], make_buyer_headers(buyer["id"]))
        )
        assert quote["status"] == "EXPIRED"


# ===========================================================================
# boundary_precision_check / credit_limit_exact_equality_accepted
# ===========================================================================

class TestCreditLimitExactEqualityAccepted:
    def test_accept_at_exact_credit_limit_succeeds(self, api):
        """PRD §3.5: the fiscal check "requires that the buyer's
        `credit_used_cents` plus the quote's `total_cents` not exceed the
        buyer's `credit_limit_cents` — exact equality with the limit is
        allowed".

        The PREMIUM 12.0t quote totals exactly 439170 cents; a buyer whose
        limit is exactly 439170 accepts it.

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_accepted
        """
        buyer, issued = _issued_quote(439170)
        accepted = accept_quote(issued["id"], buyer["id"], issued["version"])
        assert accepted["status"] == "ACCEPTED"

    def test_credit_used_lands_at_full_limit(self, api):
        """PRD §3.5: "then the buyer's `credit_used_cents` increases by the
        quote's `total_cents`, establishing the reserve."

        After accepting the 439170-cent quote at a 439170 limit, the buyer's
        credit_used_cents sits at exactly 100% utilization.

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_accepted
        """
        buyer, issued = _issued_quote(439170)
        accept_quote(issued["id"], buyer["id"], issued["version"])
        read = get_buyer(buyer["id"])
        assert read["credit_used_cents"] == 439170


# ===========================================================================
# compensating_invariant / accept_cancel_credit_invariant
# ===========================================================================

class TestAcceptCancelCreditInvariant:
    def test_accept_reserves_exact_quote_total(self, api):
        """PRD §3.5: "then the buyer's `credit_used_cents` increases by the
        quote's `total_cents`, establishing the reserve."

        The 439170-cent quote moves the buyer's reserve from 0 to exactly
        439170.

        Design: Difficulty/compensating_invariant/accept_cancel_credit_invariant
        """
        buyer, issued = _issued_quote(500000)
        accept_quote(issued["id"], buyer["id"], issued["version"])
        read = get_buyer(buyer["id"])
        assert read["credit_used_cents"] == 439170

    def test_cancel_releases_reserve_to_zero(self, api):
        """PRD §3.6: "Both exits share the same two side effects: every open
        load allocation referencing the contract is released, and the buyer's
        `credit_used_cents` is reduced by `total_reserved_cents`, freeing the
        reserve."

        Accept followed by cancel returns credit_used_cents to exactly 0 and
        leaves the contract CANCELLED — the credit headroom is conserved with
        no drift.

        Design: Difficulty/compensating_invariant/accept_cancel_credit_invariant
        """
        buyer, issued = _issued_quote(500000)
        accept_quote(issued["id"], buyer["id"], issued["version"])
        contract = find_contract_by_quote(issued["id"])
        cancelled = validate_success(api_client.cancel_contract(contract["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED"
        read = get_buyer(buyer["id"])
        assert read["credit_used_cents"] == 0


# ===========================================================================
# Corner/validations / credit_limit_exceeded_at_accept
# ===========================================================================

def test_credit_limit_exceeded_at_accept(api):
    """PRD §3.5: "requires that the buyer's `credit_used_cents` plus the
    quote's `total_cents` not exceed the buyer's `credit_limit_cents` —
    exact equality with the limit is allowed — otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    A 439170-cent quote against a 100000-cent limit is rejected; the quote
    stays ISSUED and no reserve is held.

    Design: Corner/validations/credit_limit_exceeded_at_accept
    """
    buyer, issued = _issued_quote(100000)
    resp = api_client.accept_quote(
        issued["id"], {"expected_quote_version": issued["version"]},
        make_buyer_headers(buyer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    quote = validate_success(
        api_client.get_quote(issued["id"], make_buyer_headers(buyer["id"]))
    )
    assert quote["status"] == "ISSUED"
    assert get_buyer(buyer["id"])["credit_used_cents"] == 0


# ===========================================================================
# Corner/validations / suspended_buyer_cannot_issue
# ===========================================================================

def test_suspended_buyer_cannot_issue(api):
    """PRD §3.5: "A buyer issues their own `DRAFT` quote — wrong state draws
    `ERR_QUOTE_NOT_ISSUABLE`, another user's quote draws
    `ERR_FORBIDDEN_OWNERSHIP`, and a suspended buyer draws
    `ERR_BUYER_SUSPENDED`."

    A quote drafted while the buyer was ACTIVE cannot be issued once the
    buyer is SUSPENDED.

    Design: Corner/validations/suspended_buyer_cannot_issue
    """
    setup_pricing_bed()
    buyer = create_buyer()
    quote = create_draft_quote(buyer["id"])
    validate_success(api_client.suspend_buyer(buyer["id"], ADMIN))
    resp = api_client.issue_quote(quote["id"], make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_BUYER_SUSPENDED)


# ===========================================================================
# Corner/state_machines / declined_quote_terminal_lockdown
# ===========================================================================

def test_declined_quote_terminal_lockdown(api):
    """PRD §3.5: "The buyer may decline, moving the quote to terminal
    `DECLINED` with no side effects." PRD §3.5: "the from-state guard
    requires `ISSUED`, otherwise `ERR_QUOTE_NOT_ISSUABLE`". PRD §3.6: "A
    contract is never created directly; it is born from quote acceptance."

    Accept after decline fails, the quote stays DECLINED, and no contract
    exists for the quote.

    Design: Corner/state_machines/declined_quote_terminal_lockdown
    """
    buyer, issued = _issued_quote(1000000, tons=5.0, quality_tier="GOOD")
    declined = validate_success(
        api_client.decline_quote(issued["id"], make_buyer_headers(buyer["id"]))
    )
    assert declined["status"] == "DECLINED"
    quote = validate_success(
        api_client.get_quote(issued["id"], make_buyer_headers(buyer["id"]))
    )
    resp = api_client.accept_quote(
        issued["id"], {"expected_quote_version": quote["version"]},
        make_buyer_headers(buyer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ISSUABLE)
    contracts, meta = validate_paginated(
        api_client.list_contracts(OPS, params={"quote_id": issued["id"]})
    )
    assert contracts == []
    assert meta["total_count"] == 0


# ===========================================================================
# Corner/validations / deadline_not_passed_default_rejected
# ===========================================================================

def test_deadline_not_passed_default_rejected(api):
    """PRD §3.6: default may be declared "only once the current clock date
    has passed the contract's `delivery_deadline`; declaring too early is
    rejected with `ERR_DEADLINE_NOT_PASSED`."

    The contract's deadline is 2026-08-20 and the clock reads 2026-08-01, so
    declare-default is rejected and the contract stays ACTIVE.

    Design: Corner/validations/deadline_not_passed_default_rejected
    """
    ctx = setup_accepted_contract(tons=5.0, quality_tier="GOOD")
    resp = api_client.declare_default(ctx["contract"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_NOT_PASSED)
    assert get_buyer(ctx["buyer"]["id"])["credit_used_cents"] > 0
    assert api_client.get_contract(ctx["contract"]["id"], OPS).json()[
        "data"
    ]["status"] == "ACTIVE"


# ===========================================================================
# Corner/consistency_model / immediate_contract_visibility_after_accept
# ===========================================================================

def test_immediate_contract_visibility_after_accept(api):
    """PRD §3.5: "A successful acceptance moves the quote itself to
    `ACCEPTED` — a terminal state — and cascades in two hops: first a
    contract is created in `ACTIVE` status with its fields copied from the
    quote". PRD §3.6: "`committed_tons` copies the quote's `tons`;
    `unit_price_cents` copies the quote's locked per-ton price and is never
    re-priced thereafter".

    The read immediately following accept already returns the contract:
    ACTIVE, committed_tons 12.0, locked unit_price_cents 23000.

    Design: Corner/consistency_model/immediate_contract_visibility_after_accept
    """
    buyer, issued = _issued_quote(1000000)
    accepted = accept_quote(issued["id"], buyer["id"], issued["version"])
    assert accepted["status"] == "ACCEPTED"
    contract = find_contract_by_quote(issued["id"])
    assert contract["status"] == "ACTIVE"
    assert contract["committed_tons"] == 12.0
    assert contract["unit_price_cents"] == 23000
    assert_contract_tonnage_identity(contract)
