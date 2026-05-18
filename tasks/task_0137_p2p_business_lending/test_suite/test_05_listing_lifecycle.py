"""Listings: create, tiered pricing, withdraw, expiry.

PRD §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    BASE_RATE_BPS_BY_GRADE,
    FUNDING_DEADLINE_OFFSET_DAYS,
    TERM_PREMIUM_BPS_PER_MONTH_OVER_24,
    advance_clock,
    assert_loan_listing,
    attach_plaid_snapshot,
    create_borrower,
    create_listing,
    create_listing_payload,
    create_compliance_officer,
    get_listing,
    get_platform,
    make_compliance_officer_headers,
    setup_approved_borrower,
    setup_open_listing,
    setup_platform_with_officer,
    suspend_borrower,
    validate_error,
)


# ===========================================================================
# Listing create — PRD §3.3
# ===========================================================================
class TestListingCreate:

    def test_create_listing_snapshots_grade_and_locks_rate(self, api):
        """PRD §3.3: "On open, the server snapshots grade_at_listing
        from the borrower's final_grade, computes the locked
        interest_rate_bps from the tiered pricing formula".

        Claim: a fresh listing's grade_at_listing equals the borrower's
        current final_grade, and interest_rate_bps is locked at that
        moment.
        """
        platform, officer, b = setup_approved_borrower()
        listing = create_listing(
            platform["id"], b["id"],
            principal_cents=100_000, term_months=12,
        )
        assert_loan_listing(listing)
        assert listing["grade_at_listing"] == b["final_grade"]
        assert listing["status"] == "OPEN"
        assert listing["pledged_cents"] == 0

    def test_funding_deadline_is_clock_plus_14(self, api):
        """PRD §3.3: "sets funding_deadline_day_index to the platform's
        current clock_day_index plus 14".

        Claim: funding_deadline_day_index == clock_day_index_at_open +
        14.
        """
        platform, officer = setup_platform_with_officer()
        # Advance the clock to a non-zero day index to verify the
        # addition rather than an off-by-zero.
        platform = advance_clock(platform["id"], 7)
        # Approve a borrower against this advanced clock.
        b = create_borrower(platform["id"])
        attach_plaid_snapshot(platform["id"], b["id"])
        from test_helpers import approve_borrower
        approve_borrower(platform["id"], b["id"], officer["id"])
        listing = create_listing(
            platform["id"], b["id"],
            principal_cents=100_000, term_months=12,
        )
        assert listing["funding_deadline_day_index"] == 7 + 14

    def test_second_open_listing_blocked(
        self, api, platform_operator_headers,
    ):
        """PRD §3.3: "A second listing cannot be opened for a borrower
        who already owns an OPEN or FUNDED listing; that case yields
        ERR_BORROWER_NOT_LISTABLE".

        Claim: while listing #1 is OPEN, creating listing #2 on the
        same borrower -> ERR_BORROWER_NOT_LISTABLE.
        """
        platform, officer, b, listing1 = setup_open_listing()
        resp = api.create_listing(
            platform["id"], b["id"],
            create_listing_payload(
                principal_cents=50_000, term_months=12,
            ),
            platform_operator_headers,
        )
        validate_error(resp, "ERR_BORROWER_NOT_LISTABLE")

    def test_listing_create_blocked_if_borrower_not_approved(
        self, api, platform_operator_headers,
    ):
        """PRD §3.3: "as does any attempt by a borrower whose status is
        not APPROVED. ... ERR_BORROWER_NOT_LISTABLE".

        Claim: borrower in PENDING_KYC creating a listing ->
        ERR_BORROWER_NOT_LISTABLE.
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(platform["id"])
        # Borrower is PENDING_KYC.
        resp = api.create_listing(
            platform["id"], b["id"],
            create_listing_payload(
                principal_cents=100_000, term_months=12,
            ),
            platform_operator_headers,
        )
        validate_error(resp, "ERR_BORROWER_NOT_LISTABLE")


# ===========================================================================
# Tiered interest rate — PRD §3.3
# ===========================================================================
class TestTieredInterestRate:

    @pytest.mark.parametrize(
        "grade,term,expected_bps",
        [
            # base + max(0, term-24)*10
            ("A", 12, 600),   # base 600 + 0 premium
            ("A", 24, 600),   # base 600 + max(0,0)*10 = 0
            ("A", 36, 720),   # base 600 + (36-24)*10 = 120
            ("A", 60, 960),   # base 600 + (60-24)*10 = 360
            ("B", 24, 900),
            ("B", 36, 1020),
            ("C", 12, 1300),
            ("C", 24, 1300),
            ("C", 36, 1420),
            ("D", 60, 2160),
            ("E", 36, 2520),  # base 2400 + 120
        ],
    )
    def test_tiered_rate_with_term_premium(
        self, api, grade, term, expected_bps,
    ):
        """PRD §3.3: "The base table is exactly { A: 600, B: 900, C:
        1300, D: 1800, E: 2400 }. The term premium is computed as the
        maximum of zero and the term in months minus 24, then
        multiplied by ten basis points per month — so the first 24
        months carry no premium, and beyond that each additional month
        adds 10 bps. The final interest_rate_bps is the sum of the
        base and the term premium".

        Claim: for each (grade, term) pair, listing.interest_rate_bps
        matches base + max(0, term-24)*10.
        """
        # Build a borrower whose final_grade is exactly `grade`. Use
        # the helper that drives final_grade via Plaid inputs.
        platform, officer = setup_platform_with_officer()
        # Calibrate Plaid inputs per target grade. For 'A' we use the
        # strongest inputs; for 'E' the weakest; intermediate grades
        # are tested via specific inputs.
        plaid_inputs_by_grade = {
            "A": dict(
                deposits=90 * 10_000_000, balance=25_000_000,
                nsf=0, debt=0,
            ),
            "B": dict(
                deposits=90 * 5_000_000, balance=12_000_000,
                nsf=0, debt=0,
            ),
            "C": dict(
                deposits=90 * 3_000_000, balance=6_000_000,
                nsf=0, debt=10_000,
            ),
            "D": dict(
                deposits=90 * 1_000_000, balance=2_000_000,
                nsf=2, debt=50_000,
            ),
            "E": dict(
                deposits=15_000_00, balance=2_000_00,
                nsf=5, debt=2_000_00,
            ),
        }
        p = plaid_inputs_by_grade[grade]
        # Calibration loop: attach snapshots until we hit target grade.
        # Provisional grade depends on revenue + requested amount; we
        # set those to land final grade right.
        from test_helpers import (
            approve_borrower, create_borrower, get_borrower,
        )
        b = create_borrower(
            platform["id"],
            annual_revenue_cents=500_000_000,
            requested_amount_cents=1_000_000,
        )
        attach_plaid_snapshot(
            platform["id"], b["id"],
            deposits_last_90d_cents=p["deposits"],
            avg_daily_balance_cents=p["balance"],
            nsf_count_last_90d=p["nsf"],
            existing_debt_service_cents=p["debt"],
        )
        b_after = get_borrower(platform["id"], b["id"])
        assert b_after["final_grade"] == grade, (
            f"PRD §3.2 grade formula: inputs deposits={p['deposits']}, "
            f"balance={p['balance']}, nsf={p['nsf']}, debt={p['debt']} "
            f"with annual_revenue=500M cents must land final_grade="
            f"{grade!r} per the documented score+band formula; got "
            f"{b_after['final_grade']!r}"
        )
        approve_borrower(platform["id"], b["id"], officer["id"])
        listing = create_listing(
            platform["id"], b["id"],
            principal_cents=100_000, term_months=term,
        )
        assert listing["grade_at_listing"] == grade
        assert listing["interest_rate_bps"] == expected_bps, (
            f"grade={grade} term={term}: expected {expected_bps} bps, "
            f"got {listing['interest_rate_bps']}"
        )


# ===========================================================================
# Listing withdraw — PRD §3.3
# ===========================================================================
class TestListingWithdraw:

    def test_withdraw_open_listing(self, api, platform_operator_headers):
        """PRD §3.3: "A Borrower may withdraw their own OPEN listing (a
        PlatformOperator may also do so on their behalf). The
        transition OPEN -> WITHDRAWN cascades".

        Claim: withdraw on OPEN listing -> status == WITHDRAWN.
        """
        platform, officer, b, listing = setup_open_listing()
        resp = api.withdraw_listing(
            platform["id"], listing["id"],
            platform_operator_headers,
        )
        body = resp.json()
        assert resp.status_code in (200, 204)
        # Read back to confirm.
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "WITHDRAWN"

    def test_withdraw_already_withdrawn_listing_rejected(
        self, api, platform_operator_headers,
    ):
        """PRD §3.3: "WITHDRAWN, EXPIRED, and ORIGINATED are all
        terminal listing states." PRD §2.9: state-transition legality
        (ERR_INVALID_STATE_TRANSITION) is checked before business rules.

        Claim: withdraw on an already-WITHDRAWN listing ->
        ERR_INVALID_STATE_TRANSITION.
        """
        platform, officer, b, listing = setup_open_listing()
        api.withdraw_listing(
            platform["id"], listing["id"], platform_operator_headers,
        )
        # Second withdraw must be rejected.
        resp = api.withdraw_listing(
            platform["id"], listing["id"], platform_operator_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE_TRANSITION")


# ===========================================================================
# Listing expiry — PRD §3.3
# ===========================================================================
class TestListingExpiry:

    def test_listing_at_deadline_not_yet_expired(
        self, api, platform_operator_headers,
    ):
        """PRD §3.3: "A listing that remains underfunded past its
        funding_deadline_day_index (that is, the current clock_day_index
        is strictly greater than the deadline and pledged_cents is
        strictly less than principal_cents) is expired by the
        advance-clock sweep".

        Claim: at clock_day_index == funding_deadline_day_index (NOT
        strictly greater), listing is still OPEN.
        """
        platform, officer, b, listing = setup_open_listing()
        # listing.funding_deadline_day_index = 0 + 14 = 14.
        advance_clock(platform["id"], 14)
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "OPEN", (
            f"listing should still be OPEN at clock=deadline (strict >); "
            f"got {refreshed['status']}"
        )

    def test_listing_past_deadline_transitions_to_expired(
        self, api, platform_operator_headers,
    ):
        """PRD §3.3: "A listing that remains underfunded past its
        funding_deadline_day_index ... is expired by the advance-clock
        sweep ... OPEN -> EXPIRED is a system-driven transition."

        Claim: at clock_day_index strictly greater than deadline with
        pledged_cents=0, listing transitions OPEN -> EXPIRED.
        """
        platform, officer, b, listing = setup_open_listing()
        # Advance 15 days; clock_day_index = 15 > 14 = deadline.
        advance_clock(platform["id"], 15)
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["status"] == "EXPIRED"
