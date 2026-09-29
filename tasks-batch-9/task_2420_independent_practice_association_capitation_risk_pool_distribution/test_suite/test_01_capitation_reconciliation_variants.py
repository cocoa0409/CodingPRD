"""Reconciliation of a coverage month under the two capitation conventions."""

from test_helpers import (
    assert_allocations_resum,
    assert_fields,
    build_prorated_july_roster,
    build_reconciled_file,
    assign_enrollee,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    set_clock,
)


def _build_coverage_month_remittance(api, reconciliation_method):
    """A July coverage month holding one full-month member and one mid-month add.

    The ``ADULT`` member on ``HMO`` with a risk factor of 1.25 is on the panel
    from the first instant of the month; the ``SENIOR`` member on ``HMO_PLUS``
    joins on 16 July. Only the first member appears on the payer's file.
    """
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        base_pmpm_cents=30000,
        reconciliation_method=reconciliation_method,
        quality_withhold_bps=700,
        professional_pool_share_bps=6000,
        institutional_pool_share_bps=4000,
        max_panel_size=5,
    )
    physician = create_active_physician(api, agreement["id"])

    adult = create_enrollee(
        api,
        agreement["id"],
        external_member_id="M-0001",
        age_band="ADULT",
        benefit_tier="HMO",
        risk_score_bps=12500,
    )
    assign_enrollee(api, adult["id"], physician["id"])

    senior = create_enrollee(
        api,
        agreement["id"],
        external_member_id="M-0002",
        age_band="SENIOR",
        benefit_tier="HMO_PLUS",
        risk_score_bps=20000,
    )
    assign_enrollee(
        api, senior["id"], physician["id"], effective_date="2026-07-16T00:00:00Z"
    )

    set_clock(api, "2026-08-01T00:00:00Z")
    built = build_reconciled_file(
        api,
        agreement["id"],
        [
            {
                "external_member_id": "M-0001",
                "physician_npi": physician["npi"],
                "claimed_capitation_cents": 37500,
                "effective_date": "2026-07-01T00:00:00Z",
            }
        ],
    )
    return {"agreement": agreement, "physician": physician, **built}


class TestReconciliationVariantDivergence:
    def test_snapshot_convention_pays_the_full_month_and_ignores_the_mid_month_add(
        self, api
    ):
        """PRD §3.5: "Under `ROSTER_SNAPSHOT`, a member's amount is the member's
        full `gross_pmpm_cents` when a qualifying assignment covers the first
        instant of the month itself, and zero otherwise."

        Design: Difficulty/dual_variant_calc/capitation_reconciliation_variant_divergence_on_remittance
        """
        built = _build_coverage_month_remittance(api, "ROSTER_SNAPSHOT")
        remittance = built["remittance"]

        assert_fields(
            remittance,
            {
                "reconciliation_method_used": "ROSTER_SNAPSHOT",
                "expected_capitation_cents": 37500,
                "member_month_count_bps": 10000,
                "withhold_cents": 2625,
                "net_payable_cents": 34875,
                "institutional_allocation_cents": 13950,
                "professional_allocation_cents": 20925,
                "variance_cents": 0,
            },
        )

    def test_prorated_convention_pays_the_mid_month_add_by_covered_days(self, api):
        """PRD §3.5: "Under `MEMBER_MONTHS_PRORATED`, a member's amount is that
        member's `gross_pmpm_cents` multiplied by their covered days and divided
        by the month's calendar day count, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/capitation_reconciliation_variant_divergence_on_remittance
        """
        built = _build_coverage_month_remittance(api, "MEMBER_MONTHS_PRORATED")
        remittance = built["remittance"]

        assert_fields(
            remittance,
            {
                "reconciliation_method_used": "MEMBER_MONTHS_PRORATED",
                "expected_capitation_cents": 83694,
                "member_month_count_bps": 15161,
                "withhold_cents": 5859,
                "net_payable_cents": 77835,
                "institutional_allocation_cents": 31134,
                "professional_allocation_cents": 46701,
                "variance_cents": -46194,
            },
        )

    def test_the_two_conventions_diverge_on_an_identical_roster(self, api):
        """PRD §3.5: "Mid-month additions therefore contribute nothing at all,
        while mid-month terminations contribute the entire month; the
        covered-day count is ignored for the money amount."

        Design: Difficulty/dual_variant_calc/capitation_reconciliation_variant_divergence_on_remittance
        """
        snapshot = _build_coverage_month_remittance(api, "ROSTER_SNAPSHOT")
        prorated = _build_coverage_month_remittance(api, "MEMBER_MONTHS_PRORATED")

        snapshot_expected = snapshot["remittance"]["expected_capitation_cents"]
        prorated_expected = prorated["remittance"]["expected_capitation_cents"]

        assert snapshot_expected == 37500
        assert prorated_expected == 83694
        assert prorated_expected - snapshot_expected == 46194, (
            "the mid-month senior add is worth 46194 cents prorated and nothing "
            "at all snapshotted"
        )
        assert (
            prorated["remittance"]["member_month_count_bps"]
            - snapshot["remittance"]["member_month_count_bps"]
            == 5161
        )

    def test_negative_variance_reports_that_the_payer_asserted_less_than_computed(
        self, api
    ):
        """PRD §3.5: "Third, `variance_cents` is `claimed_capitation_cents` plus
        `retro_adjustment_cents`, less `expected_capitation_cents`; it may be
        negative, and a negative variance means the payer asserted less than the
        IPA computed."

        Design: Difficulty/dual_variant_calc/capitation_reconciliation_variant_divergence_on_remittance
        """
        built = _build_coverage_month_remittance(api, "MEMBER_MONTHS_PRORATED")
        remittance = built["remittance"]

        assert remittance["claimed_capitation_cents"] == 37500
        assert remittance["retro_adjustment_cents"] == 0
        assert remittance["variance_cents"] == 37500 - 83694


class TestProratedRoundPerMemberThenSum:
    def test_three_member_roster_rounds_each_member_then_sums(self, api):
        """PRD §3.5: "Accumulating unrounded prorated amounts and rounding the
        total once is incorrect and diverges by cents on realistic rosters."

        Design: Difficulty/combinatorial_formula/prorated_capitation_round_per_member_then_sum
        """
        built = build_prorated_july_roster(api)
        remittance = built["remittance"]

        assert remittance["expected_capitation_cents"] == 86275, (
            "37500 plus 46194 plus 2581 is 86275; summing unrounded and rounding "
            "once would have produced 86274"
        )
        assert remittance["expected_capitation_cents"] != 86274
        assert remittance["member_month_count_bps"] == 18387

    def test_withhold_is_rounded_once_on_the_expected_total(self, api):
        """PRD §3.5: "Those two quantities differ by cents on a realistic
        roster, and only the remittance-level figure is authoritative."

        Design: Difficulty/combinatorial_formula/prorated_capitation_round_per_member_then_sum
        """
        built = build_prorated_july_roster(api)
        remittance = built["remittance"]

        per_enrollee_withhold_sum = sum(
            enrollee["withhold_cents"] for enrollee in built["enrollees"]
        )
        assert remittance["withhold_cents"] != per_enrollee_withhold_sum, (
            "the remittance-level withhold and the per-enrollee withhold sum are "
            "different quantities; only the remittance-level figure is authoritative"
        )
        assert remittance["withhold_cents"] == 6039, (
            "the remittance-level withhold is 6039; the per-enrollee sum of 6040 "
            "is the divergent and wrong answer"
        )
        assert remittance["net_payable_cents"] == 80236

    def test_two_rounding_steps_leave_the_residual_in_the_professional_bucket(
        self, api
    ):
        """PRD §3.5: "And exactly two rounding steps occur across the whole
        waterfall — the withhold and the institutional allocation — with the
        residual absorbing everything else."

        Design: Difficulty/combinatorial_formula/prorated_capitation_round_per_member_then_sum
        """
        remittance = build_prorated_july_roster(api)["remittance"]

        assert_fields(
            remittance,
            {
                "variance_cents": -6194,
                "institutional_allocation_cents": 32094,
                "professional_allocation_cents": 48142,
            },
        )
        assert_allocations_resum(remittance)

    def test_file_counters_reflect_only_matched_rows(self, api):
        """PRD §3.5: "And `claimed_capitation_cents` is the sum of
        `claimed_capitation_cents` over the file's rows whose `match_status` is
        `MATCHED` and whose `row_action` is `ADD`, `CHANGE` or `TERM`."

        Design: Difficulty/combinatorial_formula/prorated_capitation_round_per_member_then_sum
        """
        enrollment_file = build_prorated_july_roster(api)["file"]

        assert_fields(
            enrollment_file,
            {
                "row_count": 3,
                "matched_row_count": 3,
                "exception_row_count": 0,
                "claimed_capitation_cents": 80081,
            },
        )
