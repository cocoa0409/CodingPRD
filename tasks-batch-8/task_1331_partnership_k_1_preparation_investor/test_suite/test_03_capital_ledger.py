"""Capital event ledger: dual book/basis readings, reversal compensation,
distribution guard, withdrawal boundary, and cross-fund referential checks."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_fund, create_partner, create_tax_year, post_capital_event,
    get_partner, create_capital_event_payload,
    assert_capital_event,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]


def _fund_partner_year(api, gross=0):
    fund = create_fund()
    partner = create_partner(fund["id"], legal_name="P")
    ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=gross)
    return fund, partner, ty


class TestBookCapitalVsTaxBasis:
    def _scenario(self, api):
        """CONTRIBUTION 1000000, ADJUSTMENT +500000, then DISTRIBUTION 1200000."""
        fund, partner, ty = _fund_partner_year(api, gross=100000)
        post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 1000000, "2025-01-15")
        post_capital_event(partner["id"], ty["id"], "ADJUSTMENT", 500000, "2025-02-01")
        resp = api.create_capital_event(
            create_capital_event_payload(
                partner["id"], ty["id"],
                event_type="DISTRIBUTION", amount_cents=1200000, effective_date="2025-03-01",
            ),
            PREPARER,
        )
        validate_success(resp, 201)
        return partner

    def test_book_capital_includes_book_only_adjustment(self, api):
        """PRD §3.2: "The book-capital reading is a plain signed sum over the
        ordered stream with no floor; it can go negative only transiently,
        because distributions beyond the current balance are rejected."
        PRD §3.2: "A `DISTRIBUTION` may not exceed the partner’s current
        `capital_account_balance_cents` — a distribution exactly equal to the
        balance is allowed and leaves exactly zero — and an excessive
        distribution is rejected with `ERR_DISTRIBUTION_EXCEEDS_CAPITAL`."

        Design: Difficulty/dual_variant_calc/book_capital_vs_tax_basis_divergence
        """
        partner = self._scenario(api)
        data = get_partner(partner["id"])
        # 1000000 + 500000 (book-only ADJUSTMENT counts) - 1200000 == 300000;
        # the 1200000 distribution is validated against the 1500000 book balance.
        assert data["capital_account_balance_cents"] == 300000, (
            f"book capital must include the ADJUSTMENT: {data['capital_account_balance_cents']}"
        )

    def test_tax_basis_floors_and_spills_excess_distribution_gain(self, api):
        """PRD §3.2: "The tax-basis reading replays the same ordered stream but
        skips `ADJUSTMENT` events entirely — they are book-only Section 704(b)
        revaluations — running a basis that starts at zero: a positive-class
        event adds its amount; a negative-class event whose amount fits within
        the running basis subtracts it; and a negative-class event whose amount
        exceeds the running basis spills the excess into
        `excess_distribution_gain_cents` and floors the basis at zero."

        Design: Difficulty/dual_variant_calc/book_capital_vs_tax_basis_divergence
        """
        partner = self._scenario(api)
        data = get_partner(partner["id"])
        # basis replay skips the 500000 ADJUSTMENT: 1000000 in, 1200000 out
        # exceeds basis -> basis floors at 0 and 200000 spills to gain.
        assert data["tax_basis_cents"] == 0, f"basis must floor at zero: {data['tax_basis_cents']}"
        assert data["excess_distribution_gain_cents"] == 200000
        assert data["capital_account_balance_cents"] == 300000
        assert data["capital_account_balance_cents"] != data["tax_basis_cents"], (
            "identical event stream must diverge between the two readings"
        )


class TestReversalCompensation:
    def test_reverse_creates_negated_mirror_and_marks_original(self, api):
        """PRD §3.2: "Reversal creates a mirror event sharing the original’s
        `partner_id`, `tax_year_id`, and `event_type`, carrying the negation of
        the original’s `amount_cents`, the original’s `effective_date`, an
        optional `memo`, a `reverses_event_id` pointing at the original, and
        `POSTED` status; the original then becomes `REVERSED`."

        Design: Difficulty/compensating_invariant/capital_post_and_reverse_conserves_balance
        """
        fund, partner, ty = _fund_partner_year(api)
        ev = post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 1000000, "2025-01-15")
        assert get_partner(partner["id"])["capital_account_balance_cents"] == 1000000
        resp = api.reverse_capital_event(ev["id"], PREPARER)
        mirror = validate_success(resp, 201)
        assert_capital_event(mirror)
        assert mirror["amount_cents"] == -1000000, "mirror carries the negated amount"
        assert mirror["event_type"] == "CONTRIBUTION"
        assert mirror["status"] == "POSTED"
        assert mirror["reverses_event_id"] == ev["id"]
        original = validate_success(api.get_capital_event(ev["id"], PREPARER), 200)
        assert original["status"] == "REVERSED"

    def test_post_then_reverse_restores_balances_exactly(self, api):
        """PRD §2.9: "Corrections do not edit history — reversing an event
        appends a mirror event carrying the negated amount, and both the
        original and the mirror remain in the stream forever."
        PRD §3.2: "Both remain in the replay stream, so the partner’s balances
        are recomputed by full chronological replay, and both the original
        event’s `version` and the partner’s `version` increment."

        Design: Difficulty/compensating_invariant/capital_post_and_reverse_conserves_balance
        """
        fund, partner, ty = _fund_partner_year(api)
        ev = post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 1000000, "2025-01-15")
        validate_success(api.reverse_capital_event(ev["id"], PREPARER), 201)
        data = get_partner(partner["id"])
        assert data["capital_account_balance_cents"] == 0, (
            f"post+reverse must conserve the pre-post balance 0: {data['capital_account_balance_cents']}"
        )
        assert data["tax_basis_cents"] == 0
        # nothing is removed from the stream: original + mirror both listed
        events, meta = validate_paginated(
            api.list_capital_events(PREPARER, params={"partner_id": partner["id"]})
        )
        assert meta["total_count"] == 2, "original and mirror both remain in the stream"


class TestLedgerGuards:
    def test_distribution_exceeding_capital_rejected(self, api):
        """PRD §3.2: "A `DISTRIBUTION` may not exceed the partner’s current
        `capital_account_balance_cents` — a distribution exactly equal to the
        balance is allowed and leaves exactly zero — and an excessive
        distribution is rejected with `ERR_DISTRIBUTION_EXCEEDS_CAPITAL`."

        Design: Corner/validations/distribution_exceeding_capital_rejected
        """
        fund, partner, ty = _fund_partner_year(api)
        post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 100000, "2025-01-15")
        resp = api.create_capital_event(
            create_capital_event_payload(
                partner["id"], ty["id"],
                event_type="DISTRIBUTION", amount_cents=100001, effective_date="2025-02-01",
            ),
            PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_EXCEEDS_CAPITAL)
        assert get_partner(partner["id"])["capital_account_balance_cents"] == 100000

    def test_reverse_already_reversed_event_returns_invalid_state(self, api):
        """PRD §3.2: "Reversing a mirror — an event whose `reverses_event_id`
        is set — is rejected with `ERR_REVERSAL_OF_REVERSAL`, and reversing an
        already-`REVERSED` event is rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/reverse_already_reversed_event_returns_invalid_state
        """
        fund, partner, ty = _fund_partner_year(api)
        ev = post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 100000, "2025-01-15")
        validate_success(api.reverse_capital_event(ev["id"], PREPARER), 201)
        resp = api.reverse_capital_event(ev["id"], PREPARER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_reversal_of_mirror_rejected(self, api):
        """PRD §3.2: "Reversing a mirror — an event whose `reverses_event_id`
        is set — is rejected with `ERR_REVERSAL_OF_REVERSAL`, and reversing an
        already-`REVERSED` event is rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/reversal_of_mirror_rejected
        """
        fund, partner, ty = _fund_partner_year(api)
        ev = post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 100000, "2025-01-15")
        mirror = validate_success(api.reverse_capital_event(ev["id"], PREPARER), 201)
        resp = api.reverse_capital_event(mirror["id"], PREPARER)
        validate_error(resp, ApiErrorId.ERR_REVERSAL_OF_REVERSAL)

    def test_cross_fund_capital_event_rejected(self, api):
        """PRD §3.2: "The referenced partner and tax year must belong to the
        same fund, else `ERR_CROSS_FUND_REFERENCE`; the `effective_date` must
        fall inside the referenced tax year’s calendar year, else the request
        is rejected as `ERR_INVALID_REQUEST`; and an `effective_date` landing
        in a `COMPLETED` tax year is rejected with
        `ERR_TAX_YEAR_WINDOW_CLOSED`."

        Design: Corner/validations/cross_fund_capital_event_rejected
        """
        fund_x = create_fund()
        fund_y = create_fund()
        partner = create_partner(fund_x["id"], legal_name="P")
        ty_y = create_tax_year(fund_y["id"], year=2025, gross_ordinary_income_cents=0)
        resp = api.create_capital_event(
            create_capital_event_payload(
                partner["id"], ty_y["id"],
                event_type="CONTRIBUTION", amount_cents=100, effective_date="2025-01-15",
            ),
            PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_FUND_REFERENCE)


class TestWithdrawZeroBoundary:
    def _scenario(self, api):
        fund, partner, ty = _fund_partner_year(api)
        post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 500000, "2025-01-15")
        return fund, partner, ty

    def test_distribution_equal_to_balance_leaves_exactly_zero(self, api):
        """PRD §3.2: "A `DISTRIBUTION` may not exceed the partner’s current
        `capital_account_balance_cents` — a distribution exactly equal to the
        balance is allowed and leaves exactly zero — and an excessive
        distribution is rejected with `ERR_DISTRIBUTION_EXCEEDS_CAPITAL`."

        Design: Difficulty/boundary_precision_check/withdraw_zero_capital_boundary
        """
        fund, partner, ty = self._scenario(api)
        resp = api.create_capital_event(
            create_capital_event_payload(
                partner["id"], ty["id"],
                event_type="DISTRIBUTION", amount_cents=500000, effective_date="2025-02-01",
            ),
            PREPARER,
        )
        validate_success(resp, 201)
        data = get_partner(partner["id"])
        assert data["capital_account_balance_cents"] == 0, (
            f"equal distribution must leave exactly zero: {data['capital_account_balance_cents']}"
        )

    def test_withdraw_at_exactly_zero_succeeds(self, api):
        """PRD §3.2: "Withdrawal requires the partner’s
        `capital_account_balance_cents` to be exactly zero cents, else
        `ERR_PARTNER_CAPITAL_NOT_ZERO`, and requires that no K-1 package of the
        partner is in `GENERATED`, `REVIEWED`, or `APPROVED` preparation, else
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.2: "A successful withdrawal moves the partner from `ACTIVE` to
        `WITHDRAWN` — the terminal state — and increments the partner’s
        `version`."

        Design: Difficulty/boundary_precision_check/withdraw_zero_capital_boundary
        """
        fund, partner, ty = self._scenario(api)
        post_capital_event(partner["id"], ty["id"], "DISTRIBUTION", 500000, "2025-02-01")
        resp = api.withdraw_partner(partner["id"], ADMIN)
        data = validate_success(resp, 200)
        assert data["status"] == "WITHDRAWN"
        assert data["capital_account_balance_cents"] == 0

    def test_withdraw_with_one_cent_balance_rejected(self, api):
        """PRD §3.2: "Withdrawal requires the partner’s
        `capital_account_balance_cents` to be exactly zero cents, else
        `ERR_PARTNER_CAPITAL_NOT_ZERO`, and requires that no K-1 package of the
        partner is in `GENERATED`, `REVIEWED`, or `APPROVED` preparation, else
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/withdraw_with_one_cent_balance_rejected
        """
        fund, partner, ty = _fund_partner_year(api)
        post_capital_event(partner["id"], ty["id"], "CONTRIBUTION", 100000, "2025-01-15")
        post_capital_event(partner["id"], ty["id"], "DISTRIBUTION", 99999, "2025-02-01")
        resp = api.withdraw_partner(partner["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PARTNER_CAPITAL_NOT_ZERO)
        assert get_partner(partner["id"])["status"] == "ACTIVE"
