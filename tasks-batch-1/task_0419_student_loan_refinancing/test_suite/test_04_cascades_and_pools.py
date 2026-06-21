"""Transitive cascades from funding and delinquency, and resource interval
overlaps (offer expiry window, pool capacity band).

Difficulty queue A: transitive_cascade and resource_temporal_overlap.
"""
import pytest

from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    make_borrower_headers,
    make_disbursement_officer_headers,
    setup_funded_loan,
    setup_loan_with_eligible_cosigner,
    setup_approved_application,
    setup_prequalified_application,
    set_clock,
    mark_delinquent,
    get_loan,
    get_cosigner,
    get_abs_pool,
    api_client,
)


class TestFundCascade:
    def test_fund_cascade_pool_tag_committed_and_member_tier(self, api):
        """PRD 3.7: "It links to its application_id and to the locked offer_id, and
        is tagged with the chosen pool in abs_pool_id."
        PRD 3.7: "the chosen pool's committed_principal_cents is increased by that
        same original principal."
        PRD 3.7: "Funding also delivers a member benefit: if the borrower's
        member_tier is currently NONE, it is upgraded to SILVER (a higher tier is
        left untouched)."

        Pool with capacity 6,000,000, principal 5,000,000:
        loan.abs_pool_id == pool.id; pool.committed_principal_cents == 5,000,000;
        borrower.member_tier NONE -> SILVER.

        Design: Difficulty/transitive_cascade/fund_cascade_pool_loan_member_tier_depth3
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-C4", "max_principal_cents": 6_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        pool = bundle["pool"]
        assert loan["abs_pool_id"] == pool["id"], (
            f"loan should be tagged to pool {pool['id']}, got {loan['abs_pool_id']}"
        )
        pool_after = get_abs_pool(pool["id"])
        assert pool_after["committed_principal_cents"] == 5_000_000, (
            f"pool committed should be 5,000,000, got {pool_after['committed_principal_cents']}"
        )
        borrower_after = get_success_data(api.get_borrower(
            bundle["borrower"]["id"], make_borrower_headers(bundle["borrower"]["id"])))
        assert borrower_after["member_tier"] == "SILVER", (
            f"member_tier should be SILVER after funding, got {borrower_after['member_tier']}"
        )

    def test_fund_creates_loan_with_copied_principal(self, api):
        """PRD 3.7: "Its original_principal_cents is copied from the application's
        requested principal, and the chosen pool's committed_principal_cents is
        increased by that same original principal."

        Design: Difficulty/transitive_cascade/fund_cascade_pool_loan_member_tier_depth3
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-C4B", "max_principal_cents": 6_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        loan = bundle["loan"]
        assert loan["original_principal_cents"] == 5_000_000
        pool_after = get_abs_pool(bundle["pool"]["id"])
        assert pool_after["committed_principal_cents"] == loan["original_principal_cents"]


class TestMarkDelinquentCascade:
    def test_mark_delinquent_resets_streak_and_reverts_eligibility(self, api):
        """PRD 3.11: "As a side effect it resets the cosigner's on_time_streak to 0
        if a CONSENTED cosigner exists, and if cosigner_release_status was ELIGIBLE
        it reverts to PENDING"

        After 3 on-time payments the cosigner is ELIGIBLE; mark-delinquent resets
        on_time_streak to 0 and reverts release status to PENDING.

        Design: Difficulty/transitive_cascade/mark_delinquent_cascade_streak_release_depth2
        """
        bundle = setup_loan_with_eligible_cosigner(
            base_clock="2026-06-01T00:00:00Z",
            payment_amount_cents=50_000,
            pool_overrides={"pool_code": "POOL-C4D", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        )
        loan = bundle["loan"]
        cosigner = bundle["cosigner"]
        assert loan["cosigner_release_status"] == "ELIGIBLE", (
            f"precondition: loan must be ELIGIBLE, got {loan['cosigner_release_status']}"
        )
        assert cosigner["on_time_streak"] == 3

        mark_delinquent(loan, servicing_agent_id=bundle["servicing_agent_id"])
        loan_after = get_loan(loan["id"])
        cosigner_after = get_cosigner(cosigner["id"])
        assert cosigner_after["on_time_streak"] == 0, (
            f"on_time_streak should reset to 0, got {cosigner_after['on_time_streak']}"
        )
        assert loan_after["cosigner_release_status"] == "PENDING", (
            f"release status should revert to PENDING, got {loan_after['cosigner_release_status']}"
        )

    def test_mark_delinquent_sets_repayment_delinquent(self, api):
        """PRD 3.11: "Marking a current loan delinquent is defined only from
        repayment_status CURRENT and moves it to DELINQUENT."

        Design: Difficulty/transitive_cascade/mark_delinquent_cascade_streak_release_depth2
        """
        bundle = setup_loan_with_eligible_cosigner(
            base_clock="2026-06-01T00:00:00Z",
            payment_amount_cents=50_000,
            pool_overrides={"pool_code": "POOL-C4E", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        )
        loan = bundle["loan"]
        mark_delinquent(loan, servicing_agent_id=bundle["servicing_agent_id"])
        loan_after = get_loan(loan["id"])
        assert loan_after["repayment_status"] == "DELINQUENT", (
            f"repayment_status should be DELINQUENT, got {loan_after['repayment_status']}"
        )


class TestOfferExpiryWindow:
    def test_lock_rejected_at_or_after_expiry(self, api):
        """PRD 3.4: "it must not be expired — its expires_at must be strictly
        greater than the current clock; a lock attempted at or after expiry is
        rejected with ERR_OFFER_EXPIRED (HTTP 409)."

        Prequalify at 2026-06-01 (offer TTL 48h), advance clock to 2026-09-01
        (well past expiry), lock -> ERR_OFFER_EXPIRED.

        Design: Difficulty/resource_temporal_overlap/offer_expiry_half_open_window_on_lock
        """
        set_clock("2026-06-01T00:00:00Z")
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        borrower = bundle["borrower"]
        app = bundle["application"]
        offer = bundle["offers"][0]
        set_clock("2026-09-01T00:00:00Z")
        resp = api.lock_offer(
            offer["id"], {"expected_application_version": app["version"], "autopay_elected": True},
            make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)

    def test_expired_offer_lock_leaves_offer_presented(self, api):
        """PRD 3.4: "a lock attempted at or after expiry is rejected with
        ERR_OFFER_EXPIRED (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/offer_expiry_half_open_window_on_lock
        """
        set_clock("2026-06-01T00:00:00Z")
        bundle = setup_prequalified_application(
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 12_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        borrower = bundle["borrower"]
        app = bundle["application"]
        offer = bundle["offers"][0]
        set_clock("2026-09-01T00:00:00Z")
        api.lock_offer(
            offer["id"], {"expected_application_version": app["version"], "autopay_elected": True},
            make_borrower_headers(borrower["id"]))
        offer_after = get_success_data(api.get_offer(
            offer["id"], make_borrower_headers(borrower["id"])))
        assert offer_after["status"] == "PRESENTED", (
            f"offer must remain PRESENTED after a rejected expired lock, got {offer_after['status']}"
        )


class TestPoolCapacityBand:
    def test_funding_rejected_when_principal_exceeds_remaining_capacity(self, api):
        """PRD 3.7: "whose committed_principal_cents plus the application's
        requested_principal_cents is at most the pool's max_principal_cents. If
        that candidate set is empty, funding is rejected with ERR_NO_ELIGIBLE_POOL
        (HTTP 422) and no loan is created."

        Pool max 20,000,000 already committed 18,000,000 (remaining 2,000,000);
        application requesting 5,000,000 cannot fit -> ERR_NO_ELIGIBLE_POOL.

        Design: Difficulty/resource_temporal_overlap/pool_capacity_aggregate_interval_at_funding
        """
        # Fill the pool to 18,000,000 via a prior funded loan.
        filler = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-FULL", "max_principal_cents": 20_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 100_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 18_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        pool = filler["pool"]
        pool_after_fill = get_abs_pool(pool["id"])
        assert pool_after_fill["committed_principal_cents"] == 18_000_000

        # Approved application requesting 5,000,000 against the now-tight pool.
        bundle = setup_approved_application(
            autopay_elected=True,
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        do_headers = make_disbursement_officer_headers("do-pool-full")
        resp = api.fund_application(bundle["application"]["id"], do_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_POOL.value)
        pool_unchanged = get_abs_pool(pool["id"])
        assert pool_unchanged["committed_principal_cents"] == 18_000_000, (
            f"pool committed must be unchanged at 18,000,000, got {pool_unchanged['committed_principal_cents']}"
        )

    def test_funding_succeeds_when_principal_fits_exactly(self, api):
        """PRD 3.7: "whose committed_principal_cents plus the application's
        requested_principal_cents is at most the pool's max_principal_cents."

        Pool max 5,000,000, committed 0, principal 5,000,000 fits exactly.

        Design: Difficulty/resource_temporal_overlap/pool_capacity_aggregate_interval_at_funding
        """
        bundle = setup_funded_loan(
            autopay_elected=True,
            pool_overrides={"pool_code": "POOL-EXACT", "max_principal_cents": 5_000_000,
                            "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
            grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                            "base_apr_bps": 650, "index_apr_bps": 0},
            borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
            application_overrides={"requested_principal_cents": 5_000_000,
                                   "requested_term_months": 120, "requested_rate_type": "FIXED"},
        )
        pool_after = get_abs_pool(bundle["pool"]["id"])
        assert pool_after["committed_principal_cents"] == 5_000_000, (
            f"committed should fill the pool exactly to 5,000,000, got {pool_after['committed_principal_cents']}"
        )
