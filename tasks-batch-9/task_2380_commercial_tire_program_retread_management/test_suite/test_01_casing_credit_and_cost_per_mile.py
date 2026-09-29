"""Casing credit variants and the two cost-per-mile variants."""

from test_helpers import (
    assert_group_reports_cost_per_mile,
    entries_of_type,
    fixtures,
    validate_success,
)


class TestCasingCreditVariants:
    """The grade-provisional and production-verified variants of one formula."""

    def test_inspection_accrues_the_grade_provisional_figure(self, api):
        """PRD §3.4: "The **grade-provisional** variant runs at inspection time,
        uses the casing's `retread_count` as read at that moment, and applies no
        uplift; its figure is posted as the `ACCRUAL`."
        PRD §3.4: "The product is then multiplied by a retread fatigue decay
        factor, which is the larger of two quantities: a floor of 0.25, and one
        minus fifteen hundredths multiplied by the retread count in play."

        Design: Difficulty/dual_variant_calc/casing_credit_provisional_vs_production_verified
        """
        program = fixtures.setup_fleet_program(
            with_agreement=True,
            agreement_overrides={"casing_credit_rate_cents": 15000},
        )
        collected = fixtures.create_collected_casing(
            program["fleet"]["id"], program["location"]["id"], retread_count=1
        )

        graded = validate_success(
            api.inspect_casing(
                collected["id"],
                {"grade": "B", "expected_casing_version": collected["version"]},
                fixtures.inspector_headers(),
            )
        )

        assert graded["status"] == "INSPECTED"
        assert graded["inspection_grade"] == "B"
        assert graded["provisional_credit_cents"] == 8925, (
            "15000 * 0.70 * 0.85 rounded half up once is 8925 cents"
        )

        entries = fixtures.list_ledger(program["fleet"]["id"])
        accruals = entries_of_type(entries, "ACCRUAL")
        assert len(accruals) == 1, "one inspection posts exactly one ACCRUAL"
        assert accruals[0]["amount_cents"] == 8925
        assert accruals[0]["source_entity_type"] == "CASING"
        assert fixtures.read_fleet(program["fleet"]["id"])[
            "casing_credit_balance_cents"
        ] == 8925

    def test_completion_posts_the_production_verified_delta_not_the_gross(self, api):
        """PRD §3.4: "And the entry posted at completion is the **delta**, never
        the gross: the `ADJUSTMENT` amount is the production-verified figure
        minus the grade-provisional figure."
        PRD §3.4: "It then multiplies the raw product by one plus a ten-percent
        uplift before the single half-up rounding to whole cents."
        PRD §3.5: "From that base, six months are deducted for each retread the
        carcass already carried at scheduling time, as recorded in
        `retread_count_at_scheduling`."

        Design: Difficulty/dual_variant_calc/casing_credit_provisional_vs_production_verified
        """
        program = fixtures.setup_plant_program(
            with_agreement=True,
            agreement_overrides={"casing_credit_rate_cents": 15000},
        )
        casing = fixtures.create_inspected_casing(
            program["fleet"]["id"],
            program["location"]["id"],
            grade="B",
            retread_count=1,
        )
        job = fixtures.schedule_retread_job(casing["id"], program["line"]["id"])
        fixtures.start_job(job["id"])

        completed = validate_success(
            api.complete_retread_job(
                job["id"],
                {"completed_at": "2026-08-20T11:00:00Z", "cost_basis_cents": 28000},
                fixtures.SCHEDULER,
            )
        )

        assert completed["status"] == "COMPLETED"
        assert completed["warranty_months"] == 18, (
            "grade B gives 24 months, less 6 for the one prior retread"
        )
        assert completed["warranty_expires_on"] == "2028-02-20"

        entries = fixtures.list_ledger(program["fleet"]["id"])
        adjustments = entries_of_type(entries, "ADJUSTMENT")
        assert len(adjustments) == 1
        assert adjustments[0]["amount_cents"] == 893, (
            "9818 production-verified less 8925 grade-provisional is 893, "
            "not the 9818 gross"
        )
        assert adjustments[0]["source_entity_type"] == "RETREAD_JOB"

        after = fixtures.read_casing(casing["id"])
        assert after["status"] == "RETREADED"
        assert after["retread_count"] == 2
        assert after.get("inspection_grade") is None
        assert after["provisional_credit_cents"] == 9818
        assert fixtures.read_fleet(program["fleet"]["id"])[
            "casing_credit_balance_cents"
        ] == 9818


class TestCostPerMileVariants:
    """One asset set, two questions: money already earned back versus projected."""

    def test_historical_actual_divides_cost_by_miles_already_run(self, api):
        """PRD §3.9: "Under the `HISTORICAL_ACTUAL` variant, a group's cost per
        mile is the sum of its assets' `cost_basis_cents` divided by the sum of
        their miles run, rounded half up to four decimal places."
        PRD §3.9: "The division is performed exactly once per group, on the
        summed numerator and the summed denominator."

        Design: Difficulty/dual_variant_calc/cost_per_mile_historical_actual_vs_forward_projected
        """
        program = fixtures.setup_cost_per_mile_asset()

        data = validate_success(
            api.get_cost_per_mile(
                program["fleet"]["id"],
                fixtures.ADMIN,
                params={"variant": "HISTORICAL_ACTUAL"},
            )
        )

        assert data["variant"] == "HISTORICAL_ACTUAL"
        assert data["group_count"] == 1
        assert data["excluded_asset_count"] == 0
        assert len(data["groups"]) == 1
        assert_group_reports_cost_per_mile(data["groups"][0], 0.8333)

    def test_forward_projected_divides_cost_by_the_implied_whole_life(self, api):
        """PRD §3.9: "Under the `FORWARD_PROJECTED` variant, each asset first
        gets a wear rate per mile, which is its consumed tread divided by its
        miles run, kept as an exact rational and never rounded; its projected
        life in miles is its usable tread divided by that wear rate, truncated
        down to a whole number of miles; and the group's cost per mile is the sum
        of its assets' `cost_basis_cents` divided by the sum of those projected
        lives, rounded half up to four decimal places."
        PRD §3.9: "The governing policy is the one for the fleet and the asset's
        `position`, and the asset's usable tread is its `tread_depth_at_mount_32nds`
        less that policy's `pull_point_32nds` — the depth the fleet is actually
        willing to wear away."

        Design: Difficulty/dual_variant_calc/cost_per_mile_historical_actual_vs_forward_projected
        """
        program = fixtures.setup_cost_per_mile_asset()

        data = validate_success(
            api.get_cost_per_mile(
                program["fleet"]["id"],
                fixtures.ADMIN,
                params={"variant": "FORWARD_PROJECTED"},
            )
        )

        assert data["variant"] == "FORWARD_PROJECTED"
        assert data["group_count"] == 1
        assert data["excluded_asset_count"] == 0
        assert_group_reports_cost_per_mile(data["groups"][0], 0.4167)

        historical = validate_success(
            api.get_cost_per_mile(
                program["fleet"]["id"],
                fixtures.ADMIN,
                params={"variant": "HISTORICAL_ACTUAL"},
            )
        )
        assert historical["group_count"] == data["group_count"], (
            "the two variants answer different questions on the same asset set"
        )
        assert historical["excluded_asset_count"] == data["excluded_asset_count"]
