"""Escrow trust accounting: deposit floor/ceiling discipline, release and void
preconditions, and balance conservation across the clear/refund pair."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_escrow_entry_payload,
    get_success_data,
    listing_headers,
    record_cleared_deposit,
    required_deposit_cents,
    set_clock,
    setup_accepted_offer,
    setup_draft_statement,
    waive_all_contingencies,
    list_offer_contingencies,
    selling_headers,
    validate_error,
    validate_success,
)

ESCROW = TEST_USERS["escrow_officer_headers"]
CLOSING = TEST_USERS["closing_officer_headers"]


class TestDepositSafetyVsFiscalPair:
    def test_deposit_above_twice_required_rejected_excessive(self, api):
        """PRD §3.6: "As an anti-structuring guard, no single DEPOSIT entry may
        exceed twice the required amount; a larger one is rejected with
        `ERR_DEPOSIT_EXCESSIVE` (HTTP 422), and per the pipeline order the
        excessive ceiling is evaluated before the sufficiency floor."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_deposit_entry
        """
        deal = setup_accepted_offer(offer_price_cents=100000000)
        required = required_deposit_cents(100000000, 1000)
        assert required == 10000000
        res = api.create_escrow_entry(
            deal["offer"]["id"],
            create_escrow_entry_payload(amount_cents=2 * required + 1000000),
            ESCROW,
        )
        validate_error(res, ApiErrorId.ERR_DEPOSIT_EXCESSIVE)

    def test_deposit_below_required_rejected_insufficient(self, api):
        """PRD §3.6: "A DEPOSIT entry must be at least that required amount — an
        exactly-equal amount is acceptable — and anything short is rejected with
        `ERR_DEPOSIT_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_deposit_entry
        """
        deal = setup_accepted_offer(offer_price_cents=100000000)
        required = required_deposit_cents(100000000, 1000)
        res = api.create_escrow_entry(
            deal["offer"]["id"],
            create_escrow_entry_payload(amount_cents=required - 1000000),
            ESCROW,
        )
        validate_error(res, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)


class TestDepositFloorBoundary:
    def test_deposit_exactly_at_required_floor_accepted(self, api):
        """PRD §3.6: "The required deposit is the offer's `offer_price_cents`
        multiplied by its `deposit_pct_basis` and divided by ten thousand,
        rounded half-up to whole cents. A DEPOSIT entry must be at least that
        required amount — an exactly-equal amount is acceptable"

        Offer 123456789 at 1000 basis points: required is
        round_half_up(12345678.9) = 12345679; that exact amount must pass.

        Design: Difficulty/boundary_precision_check/deposit_exactly_at_required_floor_accepted
        """
        deal = setup_accepted_offer(offer_price_cents=123456789)
        entry = validate_success(
            api.create_escrow_entry(
                deal["offer"]["id"],
                create_escrow_entry_payload(amount_cents=12345679),
                ESCROW,
            ),
            201,
        )
        assert entry["amount_cents"] == 12345679
        assert entry["status"] == "PENDING"

    def test_deposit_one_cent_below_required_floor_rejected(self, api):
        """PRD §3.6: "anything short is rejected with `ERR_DEPOSIT_INSUFFICIENT`
        (HTTP 422)" — the floor is an inclusive >=, so required - 1 must fail.

        Design: Difficulty/boundary_precision_check/deposit_exactly_at_required_floor_accepted
        """
        deal = setup_accepted_offer(offer_price_cents=123456789)
        res = api.create_escrow_entry(
            deal["offer"]["id"],
            create_escrow_entry_payload(amount_cents=12345678),
            ESCROW,
        )
        validate_error(res, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)


class TestEscrowReleaseStateGating:
    def test_release_pending_entry_with_draft_statement_rejected(self, api):
        """PRD §3.6: "Release into the closing is the ClosingOfficer's action and
        moves a CLEARED entry to DISBURSED, but only while the parent offer stands
        ACCEPTED and its closing statement stands APPROVED."
        PRD §3.6: "Release, refund, and forfeiture all demand a CLEARED entry;
        attempting any of them against an entry in any other state is rejected
        with `ERR_ESCROW_NOT_CLEARED` (HTTP 409)." — with the entry still
        PENDING, the entry-state rule fires first and names its own error.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_escrow_release
        """
        deal = setup_accepted_offer(offer_price_cents=170000000)
        entry = validate_success(
            api.create_escrow_entry(
                deal["offer"]["id"],
                create_escrow_entry_payload(
                    amount_cents=17000000, value_date="2026-08-03T00:00:00Z"
                ),
                ESCROW,
            ),
            201,
        )
        assert entry["status"] == "PENDING"
        statement = setup_draft_statement(deal)
        assert statement["status"] == "DRAFT"

        res = api.release_escrow_entry(entry["id"], CLOSING)
        validate_error(res, ApiErrorId.ERR_ESCROW_NOT_CLEARED)
        entries = get_success_data(
            api.list_escrow_entries(deal["offer"]["id"], ESCROW)
        )
        current = [e for e in entries if e["id"] == entry["id"]][0]
        assert current["status"] == "PENDING"

    def test_release_cleared_entry_with_unapproved_statement_rejected(self, api):
        """PRD §3.6: "Release into the closing is the ClosingOfficer's action and
        moves a CLEARED entry to DISBURSED, but only while the parent offer stands
        ACCEPTED and its closing statement stands APPROVED."

        With the entry CLEARED and the offer ACCEPTED, the single failing
        precondition is the statement not standing APPROVED.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_escrow_release
        """
        deal = setup_accepted_offer(offer_price_cents=170000000)
        entry = record_cleared_deposit(deal, amount_cents=17000000)
        assert entry["status"] == "CLEARED"
        statement = setup_draft_statement(deal)
        assert statement["status"] == "DRAFT"

        res = api.release_escrow_entry(entry["id"], CLOSING)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        entries = get_success_data(
            api.list_escrow_entries(deal["offer"]["id"], ESCROW)
        )
        current = [e for e in entries if e["id"] == entry["id"]][0]
        assert current["status"] == "CLEARED"


def test_void_after_value_date_rejected(api):
    """PRD §3.6: "while the clock still precedes the `value_date`, the same desk
    may instead void the entry to VOIDED" — once the clock has reached the
    value date the entry is no longer voidable, so the state check rejects with
    `ERR_INVALID_STATE` per "does the server ask whether the target resource's
    current state permits the requested transition, rejecting with
    `ERR_INVALID_STATE` (HTTP 409)" (§2.8).

    Design: Corner/state_machines/escrow_void_only_before_value_date
    """
    deal = setup_accepted_offer(offer_price_cents=100000000)
    entry = validate_success(
        api.create_escrow_entry(
            deal["offer"]["id"],
            create_escrow_entry_payload(
                amount_cents=10000000, value_date="2026-08-03T00:00:00Z"
            ),
            ESCROW,
        ),
        201,
    )
    set_clock("2026-08-04T00:00:00Z")
    res = api.void_escrow_entry(entry["id"], ESCROW)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    entries = get_success_data(api.list_escrow_entries(deal["offer"]["id"], ESCROW))
    current = [e for e in entries if e["id"] == entry["id"]][0]
    assert current["status"] == "PENDING"


def _fail_offer_after_unresolved_objection(api, deal):
    """Object one contingency, waive the rest, let the five-day cure window
    lapse, then collapse the offer."""
    contingencies = list_offer_contingencies(deal)
    objected = contingencies[0]
    validate_success(
        api.object_contingency(
            objected["id"],
            {"objection_note": "Survey found hull blistering"},
            selling_headers(deal),
        )
    )
    for c in contingencies[1:]:
        validate_success(api.waive_contingency(c["id"], selling_headers(deal)))
    # Objection was lodged at the fixture clock 2026-08-02; six days later the
    # five-day cure window has elapsed and the sweep moves it to EXPIRED.
    set_clock("2026-08-08T00:00:00Z")
    failed = validate_success(api.fail_offer(deal["offer"]["id"], selling_headers(deal)))
    assert failed["status"] == "FAILED"
    return failed


class TestEscrowBalanceConservation:
    def test_clear_then_refund_returns_balance_to_zero(self, api):
        """PRD §3.6: "once the clock reaches such an entry's `value_date`, the
        EscrowOfficer marks it CLEARED" and "Refund is the EscrowOfficer's action,
        moving a CLEARED entry to REFUNDED whenever the parent offer stands
        FAILED, WITHDRAWN, EXPIRED, or REJECTED"
        PRD §3.5: "the selling side may collapse the deal, moving the offer from
        ACCEPTED to FAILED."

        Design: Difficulty/compensating_invariant/escrow_balance_conserved_across_clear_and_refund
        """
        deal = setup_accepted_offer(offer_price_cents=150000000)
        entry = record_cleared_deposit(deal, amount_cents=15000000)
        assert entry["status"] == "CLEARED"

        _fail_offer_after_unresolved_objection(api, deal)

        refunded = validate_success(api.refund_escrow_entry(entry["id"], ESCROW))
        assert refunded["status"] == "REFUNDED"

        entries = get_success_data(
            api.list_escrow_entries(deal["offer"]["id"], ESCROW)
        )
        cleared_total = sum(
            e["amount_cents"]
            for e in entries
            if e["entry_type"] == "DEPOSIT" and e["status"] == "CLEARED"
        )
        refunded_total = sum(
            e["amount_cents"] for e in entries if e["status"] == "REFUNDED"
        )
        assert cleared_total == 0, "no deposit may remain CLEARED after the refund"
        assert refunded_total == 15000000, (
            "refunded outflow must equal the original deposit: trust balance "
            "returns to its pre-clear value with zero drift"
        )

    def test_two_cleared_deposits_refund_in_full(self, api):
        """PRD §3.6: "Refund is the EscrowOfficer's action, moving a CLEARED
        entry to REFUNDED whenever the parent offer stands FAILED, WITHDRAWN,
        EXPIRED, or REJECTED"

        Both cleared deposits refund; the per-offer trust balance conserved
        across the clear/refund pair for every entry, not just one.

        Design: Difficulty/compensating_invariant/escrow_balance_conserved_across_clear_and_refund
        """
        deal = setup_accepted_offer(offer_price_cents=150000000)
        entry_a = record_cleared_deposit(deal, amount_cents=15000000)
        entry_b = record_cleared_deposit(deal, amount_cents=15000000)

        _fail_offer_after_unresolved_objection(api, deal)

        for entry in (entry_a, entry_b):
            refunded = validate_success(api.refund_escrow_entry(entry["id"], ESCROW))
            assert refunded["status"] == "REFUNDED"

        entries = get_success_data(
            api.list_escrow_entries(deal["offer"]["id"], ESCROW)
        )
        assert len(entries) == 2
        cleared_total = sum(
            e["amount_cents"]
            for e in entries
            if e["entry_type"] == "DEPOSIT" and e["status"] == "CLEARED"
        )
        refunded_total = sum(
            e["amount_cents"] for e in entries if e["status"] == "REFUNDED"
        )
        assert cleared_total == 0
        assert refunded_total == 30000000
