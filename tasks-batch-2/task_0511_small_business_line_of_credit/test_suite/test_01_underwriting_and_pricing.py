"""Underwriting risk scoring, tiered pricing, and renewal fee/APR economics.

Covers difficulty instances (dual_variant_calc, combinatorial_formula) and corner calculation
instances. Every test reaches its state through test_helpers fixtures and asserts PRD-exact
field names and pre-computed literal values.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    create_merchant,
    create_bank_feed,
    create_draft_application,
    create_submitted_application,
    create_active_credit_line,
    create_application_payload,
    submit_application_payload,
    create_renewal_offer_payload,
    UW1,
    UW2,
    CO1,
)


class TestRiskScoreVariants:
    def test_risk_score_recomputes_on_revision_resubmit_with_newer_feed(self, api):
        """Resubmission attaches a newer feed and rescores, discarding the prior score.

        PRD §3.2: "A resubmission may attach a different feed: the submit request accepts an
        optional bank_feed_id, and when present the application is rescored against that newer
        feed, discarding the prior risk_score."

        Design: Difficulty/dual_variant_calc/risk_score_initial_vs_revision_submit
        """
        merchant = create_merchant(monthly_revenue_cents=2_000_000)
        feed_lo = create_bank_feed(
            merchant["id"], plaid_item_id="plaid_lo", pulled_at="2026-04-20T00:00:00Z",
            avg_daily_balance_cents=700_000, nsf_count_90d=0, deposit_volume_cents=3_000_000,
        )
        feed_hi = create_bank_feed(
            merchant["id"], plaid_item_id="plaid_hi", pulled_at="2026-04-25T00:00:00Z",
            avg_daily_balance_cents=900_000, nsf_count_90d=0, deposit_volume_cents=4_800_000,
        )
        app = validate_success(
            api.create_application(
                create_application_payload(merchant["id"], feed_lo["id"], requested_limit_cents=1_000_000),
                UW1,
            ),
            201,
        )
        # Initial submit against feed_lo -> score 52.
        submitted = validate_success(api.submit_application(app["id"], UW1), 200)
        assert submitted["risk_score"] == 52, "initial-submit variant scores against feed_lo"
        # A different underwriter sends it back for revision.
        validate_success(api.request_revision_application(app["id"], UW2), 200)
        # Resubmit against the fresher feed_hi -> recomputed to 73.
        resubmitted = validate_success(
            api.submit_application(app["id"], UW1, submit_application_payload(bank_feed_id=feed_hi["id"])),
            200,
        )
        assert resubmitted["risk_score"] == 73, "revision-resubmit variant rescores against feed_hi"
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["bank_feed_id"] == feed_hi["id"]

    def test_risk_score_revision_loop_returns_to_submitted(self, api):
        """The revision loop re-enters SUBMITTED with a recomputed risk_score.

        PRD §3.2: "from NEEDS_REVISION the application can be resubmitted, forming the cyclic
        revision loop SUBMITTED → NEEDS_REVISION → SUBMITTED."

        Design: Difficulty/non_linear_state_machine/application_revision_resubmit_cycle
        """
        merchant, feed, app = create_submitted_application(
            feed_overrides={"pulled_at": "2026-04-28T00:00:00Z"}
        )
        assert app["risk_score"] == 85
        validate_success(api.request_revision_application(app["id"], UW2), 200)
        resubmitted = validate_success(api.submit_application(app["id"], UW1), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["risk_score"] == 85

    def test_risk_score_weighted_blend_clamps_to_85(self, api):
        """The weighted blend with both ratios clamped to 1.0 and zero NSF yields exactly 85.

        PRD §3.2: "The raw blend is then the balance ratio weighted at 0.50, plus the revenue
        ratio weighted at 0.35, minus the NSF penalty weighted at 0.40."
        PRD §3.2: "That raw value is clamped to the range from 0.0 to 1.0, and only then
        multiplied by 100 and rounded — a single final round, half up, to zero decimal places —
        producing an integer score from 0 to 100."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_nonlinear_mode_a
        """
        merchant = create_merchant(monthly_revenue_cents=2_000_000)
        feed = create_bank_feed(
            merchant["id"], avg_daily_balance_cents=2_000_000, nsf_count_90d=0,
            deposit_volume_cents=9_000_000,
        )
        app = validate_success(
            api.create_application(
                create_application_payload(merchant["id"], feed["id"], requested_limit_cents=1_000_000),
                UW1,
            ),
            201,
        )
        submitted = validate_success(api.submit_application(app["id"], UW1), 200)
        assert submitted["risk_score"] == 85


class TestRenewalEconomics:
    def test_equivalent_apr_annualizes_after_rate(self, api):
        """equivalent_apr_bps annualizes the flat rate after computing it (rate-then-annualize).

        PRD §3.7: "the flat periodic rate is the new fee factor divided by 10000, that rate is
        then multiplied by 365 days divided by the term length in days to extrapolate it to a
        year, and the annualized rate is multiplied back by 10000 and rounded once, half up, to
        whole basis points."

        Design: Difficulty/combinatorial_formula/equivalent_apr_annualize_after_rate_mode_c
        """
        _, _, _, line = create_active_credit_line(cadence="WEEKLY")
        offer = validate_success(
            api.create_renewal_offer(
                line["id"], create_renewal_offer_payload(new_fee_factor_bps=1200, term_days=180), CO1
            ),
            201,
        )
        assert offer["total_fee_cents"] == 120000
        assert offer["equivalent_apr_bps"] == 2433

    def test_renewal_total_fee_correct_result(self, api):
        """total_fee_cents is the flat fee on a representative full draw of the limit.

        PRD §3.7: "The total_fee_cents is the flat fee on a representative full draw of the
        limit: the line's credit_limit_cents multiplied by the offer's new fee factor, divided
        by 10000, rounded half up to a whole cent."

        Design: Corner/calculations/renewal_total_fee_correct_result
        """
        _, _, _, line = create_active_credit_line(cadence="WEEKLY")
        offer = validate_success(
            api.create_renewal_offer(
                line["id"], create_renewal_offer_payload(new_fee_factor_bps=1800, term_days=90), CO1
            ),
            201,
        )
        assert offer["total_fee_cents"] == 180000
        assert offer["equivalent_apr_bps"] == 7300


class TestApprovedLimitPricing:
    def test_approved_limit_capped_by_advance_multiple_tier_b(self, api):
        """A TIER_B applicant's approved limit is capped by floor(avg_daily_balance * 1.00).

        PRD §3.2: "a score from 65 up to but not including 80 selects TIER_B, with an advance
        multiple of 1.00"
        PRD §3.2: "At origination, the approved limit is the lesser of the requested limit and
        that raw cap; there is no current-limit floor on a brand-new application."

        Design: Corner/calculations/approved_limit_capped_by_advance_multiple
        """
        merchant = create_merchant(monthly_revenue_cents=2_000_000)
        feed = create_bank_feed(
            merchant["id"], avg_daily_balance_cents=900_000, nsf_count_90d=0,
            deposit_volume_cents=4_800_000,
        )
        app = validate_success(
            api.create_application(
                create_application_payload(merchant["id"], feed["id"], requested_limit_cents=1_000_000),
                UW1,
            ),
            201,
        )
        submitted = validate_success(api.submit_application(app["id"], UW1), 200)
        assert submitted["risk_score"] == 73
        approved = validate_success(api.approve_application(app["id"], UW2), 200)
        assert approved["pricing_tier"] == "TIER_B"
        assert approved["approved_limit_cents"] == 900_000
