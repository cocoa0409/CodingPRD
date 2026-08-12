"""Royalty engine tests: tiered pricing, QUOTED vs SETTLED variants, and
classification (PRD §2.8, §3.3, §3.4, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_application,
    begin_review,
    create_application,
    create_org,
    create_title,
    current_application_version,
    fund_agreement_for_activation,
    get_success_data,
    make_applicant_headers,
    report_performance_payload,
    reset_clock,
    setup_active_agreement,
    setup_pending_agreement,
    submit_application,
    validate_error,
    validate_success,
)

ADMIN_ROLE = None  # headers pulled from fixtures below via test_helpers


def _admin():
    from test_helpers import TEST_USERS

    return TEST_USERS["rights_admin_headers"]


def _officer():
    from test_helpers import TEST_USERS

    return TEST_USERS["licensing_officer_headers"]


def _finance():
    from test_helpers import TEST_USERS

    return TEST_USERS["finance_officer_headers"]


class TestQuotedVsSettledDivergence:
    """Difficulty: QUOTED over projected gross vs SETTLED over reported gross."""

    def _build_two_performance_agreement(self, api):
        reset_clock("2026-05-01T00:00:00Z")
        title = create_title(
            name="Hybrid Play",
            royalty_basis="HYBRID",
            base_flat_fee_cents=100000,
            gross_percent_bp=800,
        )
        org = create_org(legal_name="Community Troupe")
        applicant = make_applicant_headers(org["id"])
        app = create_application(
            title["id"],
            org["id"],
            applicant,
            venue_seating_capacity=250,
            ticket_top_price_cents=2000,
            projected_gross_cents=800000,
            performance_count=2,
            first_performance_date="2026-06-01T19:00:00Z",
            last_performance_date="2026-06-02T19:00:00Z",
        )
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        agreement = approve_application(app["id"])
        # PRD §3.4: activation requires funding (partial-payment rule)
        fund_agreement_for_activation(agreement["id"])
        get_success_data(api.activate_agreement(agreement["id"], _admin()))
        perf1 = get_success_data(
            api.create_performance(
                agreement["id"],
                {"performance_at": "2026-06-01T19:00:00Z"},
                applicant,
            )
        )
        perf2 = get_success_data(
            api.create_performance(
                agreement["id"],
                {"performance_at": "2026-06-02T19:00:00Z"},
                applicant,
            )
        )
        reset_clock("2026-06-03T00:00:00Z")
        return title, org, applicant, agreement, perf1, perf2

    def test_quoted_total_uses_projected_gross(self, api):
        """PRD §3.4: "The quoted royalty `quoted_royalty_total_cents` is computed
        by the performance-royalty rule in its `QUOTED` variant over the
        application's projected figures, and the opening `royalty_balance_cents`
        is that quoted total."
        PRD §2.8: "between 200 and 399 seats yields 1.25" and "an `AMATEUR`
        production multiplies by 1.00".

        Design: Difficulty/dual_variant_calc/royalty_quoted_vs_settled_diverge_on_actual_gross
        """
        _t, _o, _ap, agreement, _p1, _p2 = self._build_two_performance_agreement(api)
        # QUOTED: flat/perf = 100000*1.25*1.00 = 125000;
        # pct/perf = round(800000*800/10000/2) = 32000; per-perf 157000; x2.
        assert agreement["quoted_royalty_total_cents"] == 314000
        assert agreement["royalty_balance_cents"] == 314000
        assert agreement["royalty_mode"] == "QUOTED"

    def test_settled_per_performance_uses_reported_gross(self, api):
        """PRD §3.5: "`royalty_cents` is computed for that single performance via
        the performance-royalty rule in its `SETTLED` variant — using this
        performance's `reported_gross_cents`, the agreement's
        `house_seating_capacity`, and a divisor of 1 for the per-performance
        computation."

        Design: Difficulty/dual_variant_calc/royalty_quoted_vs_settled_diverge_on_actual_gross
        """
        _t, _o, applicant, agreement, perf1, perf2 = (
            self._build_two_performance_agreement(api)
        )
        r1 = get_success_data(
            api.report_performance(
                perf1["id"],
                {"reported_attendance": 220, "reported_gross_cents": 500000},
                applicant,
            )
        )
        r2 = get_success_data(
            api.report_performance(
                perf2["id"],
                {"reported_attendance": 240, "reported_gross_cents": 700000},
                applicant,
            )
        )
        # SETTLED perf1: flat 125000 + round(500000*800/10000/1)=40000 -> 165000
        assert r1["royalty_cents"] == 165000
        # SETTLED perf2: flat 125000 + round(700000*800/10000/1)=56000 -> 181000
        assert r2["royalty_cents"] == 181000
        # Divergence: reported gross 1,200,000 != projected 800,000
        quoted_per_perf = 314000 // 2  # 157000
        assert r1["royalty_cents"] != quoted_per_perf
        assert (r1["royalty_cents"] + r2["royalty_cents"]) != 314000


class TestTieredMultimodeRoyalty:
    """Difficulty: >=3 inputs (capacity, classification, basis) with non-linear
    tier interaction at the 199/200 boundary."""

    def _approve_with_capacity(self, api, title_id, org, applicant, capacity):
        app = create_application(
            title_id,
            org["id"],
            applicant,
            venue_seating_capacity=capacity,
            ticket_top_price_cents=2000,
            projected_gross_cents=800000,
            performance_count=2,
            first_performance_date="2026-06-01T19:00:00Z",
            last_performance_date="2026-06-02T19:00:00Z",
        )
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        return approve_application(app["id"])

    def test_tier_boundary_flips_flat_component(self, api):
        """PRD §2.8: "at most 199 seats yields a multiplier of 1.00, between 200
        and 399 seats yields 1.25".

        Design: Difficulty/combinatorial_formula/royalty_tiered_multimode_three_inputs_nonlinear
        """
        reset_clock("2026-05-01T00:00:00Z")
        title = create_title(
            royalty_basis="HYBRID", base_flat_fee_cents=100000, gross_percent_bp=800
        )
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        agr1 = self._approve_with_capacity(api, title["id"], org, applicant, 199)
        agr2 = self._approve_with_capacity(api, title["id"], org, applicant, 200)
        # cap 199: (100000*1.00 + 32000)/perf * 2 = 264000
        assert agr1["quoted_royalty_total_cents"] == 264000
        # cap 200: (100000*1.25 + 32000)/perf * 2 = 314000
        assert agr2["quoted_royalty_total_cents"] == 314000

    def test_one_seat_difference_changes_total(self, api):
        """PRD §2.8: "The house-size ladder has four tiers: at most 199 seats
        yields a multiplier of 1.00, between 200 and 399 seats yields 1.25".

        Design: Difficulty/combinatorial_formula/royalty_tiered_multimode_three_inputs_nonlinear
        """
        reset_clock("2026-05-01T00:00:00Z")
        title = create_title(
            royalty_basis="HYBRID", base_flat_fee_cents=100000, gross_percent_bp=800
        )
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        agr1 = self._approve_with_capacity(api, title["id"], org, applicant, 199)
        agr2 = self._approve_with_capacity(api, title["id"], org, applicant, 200)
        assert agr1["quoted_royalty_total_cents"] != agr2["quoted_royalty_total_cents"]
        assert (
            agr2["quoted_royalty_total_cents"] - agr1["quoted_royalty_total_cents"]
            == 50000
        )


class TestTierBoundary199vs200:
    """Difficulty boundary instance on a PER_PERFORMANCE title."""

    def _approve_capacity(self, api, title_id, org, applicant, capacity):
        app = create_application(
            title_id,
            org["id"],
            applicant,
            venue_seating_capacity=capacity,
            ticket_top_price_cents=1000,
            projected_gross_cents=100000,
            performance_count=1,
        )
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        return approve_application(app["id"])

    def test_199_seats_uses_tier1_multiplier(self, api):
        """PRD §2.8: "at most 199 seats yields a multiplier of 1.00".

        Design: Difficulty/boundary_precision_check/tier_boundary_199_vs_200_seats
        """
        reset_clock("2026-05-01T00:00:00Z")
        title = create_title(royalty_basis="PER_PERFORMANCE", base_flat_fee_cents=100000)
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        agr = self._approve_capacity(api, title["id"], org, applicant, 199)
        # 100000 * 1.00 * 1.00 * 1 perf
        assert agr["quoted_royalty_total_cents"] == 100000

    def test_200_seats_uses_tier2_multiplier(self, api):
        """PRD §2.8: "between 200 and 399 seats yields 1.25".

        Design: Difficulty/boundary_precision_check/tier_boundary_199_vs_200_seats
        """
        reset_clock("2026-05-01T00:00:00Z")
        title = create_title(royalty_basis="PER_PERFORMANCE", base_flat_fee_cents=100000)
        org = create_org()
        applicant = make_applicant_headers(org["id"])
        agr = self._approve_capacity(api, title["id"], org, applicant, 200)
        # 100000 * 1.25 * 1.00 * 1 perf = 125000; exactly one tier jump
        assert agr["quoted_royalty_total_cents"] == 125000


class TestComputedQuotedRoyalty:
    def test_computed_field_quoted_royalty_total_set_by_system(self, api):
        """PRD §3.4: "The quoted royalty `quoted_royalty_total_cents` is computed
        by the performance-royalty rule in its `QUOTED` variant over the
        application's projected figures, and the opening `royalty_balance_cents`
        is that quoted total."

        Design: Corner/entities/computed_field_quoted_royalty_total_set_by_system
        """
        ctx = setup_pending_agreement()
        agreement = ctx["agreement"]
        # PER_PERFORMANCE base 50000, cap 100 (tier 1.00), AMATEUR, 1 perf
        assert agreement["quoted_royalty_total_cents"] == 50000
        assert agreement["royalty_balance_cents"] == 50000


class TestClassificationRule:
    def test_classification_rule_paid_performers_makes_professional(self, api):
        """PRD §3.3: "If `performers_compensated` is true, the determination is
        `PROFESSIONAL`."

        Design: Corner/calculations/classification_rule_paid_performers_makes_professional
        """
        reset_clock()
        title = create_title()
        org = create_org(org_kind="COMMUNITY")
        applicant = make_applicant_headers(org["id"])
        app = create_application(
            title["id"],
            org["id"],
            applicant,
            performers_compensated=True,
            requested_classification="AMATEUR",
        )
        submit_application(app["id"], applicant)
        under_review = begin_review(app["id"])
        assert under_review["determined_classification"] == "PROFESSIONAL"
