"""The named constants, rounding directions and input-set filters.

Each of these fixes one number the PRD states explicitly — the 0.60 important-soil
weight, the 25,000,000-cent fee tier boundary, the 1,200,000-cent per-acre
ceiling, the 2,000-square-foot severity threshold — or one rounding direction that
a plausible alternative would get wrong.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLOCK_2026_08_10,
    CLOCK_2026_08_20,
    CLOCK_2026_10_01,
    CLOCK_2026_10_05,
    TEST_USERS,
    ApiErrorId,
    api_client,
    application_version,
    commitments_of,
    create_landowner,
    create_parcel,
    create_program,
    create_program_required_only_payload,
    create_small_parcel,
    engage_appraisal,
    file_counter,
    funding_plan_payload,
    issue_offer,
    open_violation,
    rank_round,
    read_application,
    read_easement,
    read_source,
    review_appraisal_payload,
    run_sweep,
    set_clock,
    setup_filed_application,
    setup_funded_application,
    setup_offered_application,
    setup_priced_application,
    setup_ranked_application,
    setup_recorded_easement,
    submit_appraisal,
    suspend_source_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["appraisal_reviewer_headers"]

TEN_ACRE_PARCEL = {
    "county": "Chester",
    "acres": 10.00,
    "prime_soil_acres": 8.00,
    "statewide_important_soil_acres": 1.00,
    "contiguous_preserved_acres": 5.00,
    "road_frontage_feet": 200,
    "sewer_available": False,
    "zoning_min_lot_acres": 3.0,
    "baseline_dwelling_rights": 1,
    "unrestricted_value_cents": 20_000_000,
    "restricted_value_cents": 8_000_000,
}

HALF_UNIT_PARCEL = {
    "county": "Berks",
    "acres": 80.00,
    "prime_soil_acres": 60.00,
    "statewide_important_soil_acres": 8.00,
    "contiguous_preserved_acres": 40.00,
    "road_frontage_feet": 300,
    "sewer_available": False,
    "zoning_min_lot_acres": 2.0,
    "baseline_dwelling_rights": 2,
    "unrestricted_value_cents": 120_000_000,
    "restricted_value_cents": 45_485_000,
}


class TestInstallmentSchedule:
    """The residue of an integer division has exactly one place to land."""

    def test_six_annual_payments_floor_and_the_final_year_absorbs_the_residue(self):
        """Early years floor, the last year reconstitutes the total exactly.

        PRD §3.5: "Divide `total_program_cost_cents` by `installment_years` and
        floor to whole cents; that floored figure is `first_installment_cents`
        and is also what each of the early years pays. `final_installment_cents`
        is `total_program_cost_cents` less the floored annual figure multiplied by
        one fewer than `installment_years`, so that the early payments plus the
        final payment reconstitute the total exactly and every rounding residue
        lands on the last year."

        Design: Corner/calculations/installment_schedule_floors_annual_payments_and_lands_the_residue_on_the_final_year
        """
        scenario = setup_ranked_application()
        set_clock(CLOCK_2026_10_05)
        offered = issue_offer(
            scenario["application"]["id"],
            175_550_000,
            "INSTALLMENT",
            installment_years=6,
        )
        assert offered["status"] == "OFFER_ISSUED"
        assert offered["structure"] == "INSTALLMENT"
        assert offered["installment_years"] == 6
        assert offered["donation_pct"] == pytest.approx(0.0, abs=0.0001)
        assert offered["donation_cents"] == 0
        assert offered["bargain_sale_price_cents"] == 175_550_000
        # 175,550,000 is at or above 75,000,000, so the 1.5 percent rate applies.
        assert offered["admin_fee_cents"] == 2_633_250
        assert offered["total_program_cost_cents"] == 178_183_250

        # floor(178,183,250 / 6) is 29,697,208 with a two-cent residue.
        assert offered["first_installment_cents"] == 29_697_208
        assert offered["final_installment_cents"] == 29_697_210
        assert (
            offered["first_installment_cents"] * 5 + offered["final_installment_cents"]
            == offered["total_program_cost_cents"]
        )
        # round_half_up(178,183,250 x 0.0275 x 5 / 2)
        assert offered["installment_interest_total_cents"] == 12_250_098


class TestWaterfallInputSet:
    """A source outside the window or outside `ACTIVE` is simply not there."""

    def test_the_sweep_skips_sources_by_obligation_window_and_by_status(self):
        """Both eligibility filters, against the same 160,364,925 target.

        PRD §3.6: "A source participates only when it belongs to the same program
        as the application's round, its `status` is exactly `ACTIVE`, and its
        obligation window contains the supplied `target_closing_date`
        inclusively — that is, `obligation_window_start` is at or before the
        target date and `obligation_window_end` is at or after it."

        Design: Corner/calculations/waterfall_skips_sources_by_status_and_by_obligation_window
        """
        scenario = setup_offered_application()
        application_id = scenario["application"]["id"]
        sources = scenario["sources"]
        version = application_version(application_id)
        assert scenario["application"]["total_program_cost_cents"] == 160_364_925

        # Every window ends 2027-12-31, so a 2028 target leaves nothing eligible
        # and no source takes anything for the remainder rule to fall back on.
        validate_error(
            api_client.assemble_funding_plan(
                application_id,
                funding_plan_payload(
                    version, target_closing_date="2028-01-15T00:00:00Z"
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_FUNDING_SHORTFALL.value,
        )

        suspended = validate_success(
            api_client.suspend_funding_source(
                sources["state"]["id"],
                suspend_source_payload("state appropriation lapsed"),
                ADMIN,
            )
        )
        assert suspended["status"] == "SUSPENDED"
        # Its authority is untouched — it is merely invisible to the sweep.
        assert suspended["available_cents"] == 120_000_000
        assert suspended["reserved_cents"] == 0

        # With the STATE appropriation skipped, the two floored caps raise only
        # 56,127,723 + 40,091,231, and the FEDERAL source — the last non-zero
        # take — absorbs the whole 64,145,971 remainder out of its own headroom,
        # driving the federal total to 104,237,202 against a ceiling of
        # floor(160,364,925 x 0.50) == 80,182,462.
        validate_error(
            api_client.assemble_funding_plan(
                application_id,
                funding_plan_payload(
                    version, target_closing_date="2027-01-15T00:00:00Z"
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_FEDERAL_SHARE_EXCEEDED.value,
        )

        _rows, meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id}
            )
        )
        assert meta["total_count"] == 0

        after = read_application(application_id)
        assert after["funding_plan_status"] == "UNFUNDED"
        assert after["funded_cost_cents"] is None
        assert after["version"] == version
        assert read_source(sources["local"]["id"])["reserved_cents"] == 0
        assert read_source(sources["federal"]["id"])["reserved_cents"] == 0


class TestSoilQualityScore:
    """The important-soil weight is 0.60, not 0.50 and not 1.00."""

    def test_statewide_important_acres_are_credited_at_exactly_sixty_percent(self):
        """Two parcels differing only in 24 important acres differ by 9.00.

        PRD §3.2: "Divide `prime_soil_acres` by `acres` to obtain the prime share
        and `statewide_important_soil_acres` by `acres` to obtain the important
        share; add the prime share to the important share multiplied by the
        important-soil weight of 0.60; clamp the result to a maximum of 1;
        multiply by 100; and round half up to 2 decimals."

        Design: Corner/calculations/soil_score_credits_statewide_important_acres_at_exactly_sixty_percent
        """
        create_program()
        landowner = create_landowner()
        set_clock(CLOCK_2026_08_10)

        with_important = create_parcel(landowner["id"])
        without_important = create_parcel(
            landowner["id"], statewide_important_soil_acres=0.00
        )

        # 120/160 plus 24/160 x 0.60, times 100.
        assert with_important["soil_quality_score"] == pytest.approx(84.00, abs=0.01)
        # 120/160 alone, times 100.
        assert without_important["soil_quality_score"] == pytest.approx(75.00, abs=0.01)
        assert (
            with_important["soil_quality_score"]
            - without_important["soil_quality_score"]
        ) == pytest.approx(9.00, abs=0.01)

        # The two scores are independent: nothing else about the land moved.
        assert with_important["development_pressure_score"] == pytest.approx(
            78.00, abs=0.01
        )
        assert without_important["development_pressure_score"] == pytest.approx(
            78.00, abs=0.01
        )
        assert without_important["status"] == "ELIGIBLE"


class TestAdminFeeTier:
    """The tier boundary is an exclusive upper bound on the pre-fee cash."""

    def test_one_cent_more_on_the_price_costs_the_program_249999_cents_less(self):
        """24,999,999 sits in the 3 percent tier; 25,000,000 in the 2 percent one.

        PRD §3.5: "Third, select the administrative fee rate on that pre-fee cash
        portion: a rate of 0.030 — three percent — when `bargain_sale_price_cents`
        is strictly below 25,000,000 cents, otherwise a rate of 0.020 when it is
        strictly below 75,000,000 cents, otherwise a rate of 0.015."

        Design: Corner/calculations/admin_fee_tier_flips_at_exactly_twenty_five_million_cents_so_a_one_cent_higher_price_costs_less
        """
        scenario = setup_priced_application(
            parcel_factory=create_small_parcel, requested_price_cents=24_000_000
        )
        application_id = scenario["application"]["id"]
        ranked = scenario["application"]
        # 0.35x100.00 + 0.15x20.00 + 0.25x100.00 + 0.25x8.00
        assert ranked["composite_score"] == pytest.approx(65.00, abs=0.01)
        assert ranked["status"] == "RANKED"
        assert ranked["certified_easement_value_cents"] == 25_000_000

        set_clock(CLOCK_2026_10_05)
        offered = issue_offer(application_id, 24_999_999, "FULL_PURCHASE")
        assert offered["bargain_sale_price_cents"] == 24_999_999
        # round_half_up(24,999,999 x 0.030)
        assert offered["admin_fee_cents"] == 750_000
        assert offered["total_program_cost_cents"] == 25_749_999
        assert offered["donation_cents"] == 0

        countered = file_counter(
            application_id,
            scenario["landowner"]["id"],
            25_000_000,
            rationale="one cent more",
        )
        assert countered["status"] == "COUNTERED"
        assert countered["bargain_sale_price_cents"] == 25_000_000
        # 25,000,000 is no longer strictly below the boundary, so 0.020 applies.
        assert countered["admin_fee_cents"] == 500_000
        assert countered["total_program_cost_cents"] == 25_500_000
        assert countered["last_counter_cents"] == 25_000_000
        assert countered["proposed_price_cents"] == 25_000_000
        assert countered["donation_cents"] == 0
        # One cent more on the price, 249,999 cents less on the program's bill.
        assert (
            offered["total_program_cost_cents"]
            - countered["total_program_cost_cents"]
        ) == 249_999


class TestCertifiedValueClamp:
    """The per-acre ceiling clamps the gross spread before the rounding step."""

    def test_the_per_acre_ceiling_clamps_below_at_and_above_the_threshold(self):
        """A 10-acre parcel has a ceiling of exactly 12,000,000 cents.

        PRD §3.4: "Subtract `restricted_value_cents` from
        `unrestricted_value_cents` to obtain the gross spread. Independently
        compute a ceiling of 1,200,000 cents — twelve thousand dollars — per acre,
        multiplied by the parcel's `acres`. Take the lesser of the gross spread
        and that ceiling. Divide by 10,000 cents, round half up to a whole
        number, and multiply back by 10,000: in other words, round half up to the
        nearest hundred dollars."

        Design: Corner/calculations/certified_appraisal_value_is_clamped_by_the_per_acre_ceiling_before_rounding
        """
        scenario = setup_filed_application(
            parcel_overrides=TEN_ACRE_PARCEL,
            application_overrides={"requested_price_cents": 11_000_000},
        )
        application_id = scenario["application"]["id"]
        assert scenario["application"]["preliminary_easement_value_cents"] == 10_800_000

        appraisal = engage_appraisal(application_id)
        set_clock(CLOCK_2026_08_20)

        below = submit_appraisal(
            appraisal["id"],
            unrestricted_value_cents=20_000_000,
            restricted_value_cents=8_010_000,
        )
        # A gross of 11,990,000 is under the ceiling and passes through.
        assert below["easement_value_cents"] == 11_990_000

        rejected = validate_success(
            api_client.review_appraisal(
                appraisal["id"],
                review_appraisal_payload(
                    "REJECT", review_note="revise the comparable set"
                ),
                REVIEWER,
            )
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["easement_value_cents"] is None

        at_ceiling = submit_appraisal(
            appraisal["id"],
            unrestricted_value_cents=20_000_000,
            restricted_value_cents=8_000_000,
        )
        assert at_ceiling["easement_value_cents"] == 12_000_000

        validate_success(
            api_client.review_appraisal(
                appraisal["id"],
                review_appraisal_payload("REJECT", review_note="one more revision"),
                REVIEWER,
            )
        )
        above = submit_appraisal(
            appraisal["id"],
            unrestricted_value_cents=20_000_000,
            restricted_value_cents=7_000_000,
        )
        # A gross of 13,000,000 is clamped down to the 10-acre ceiling.
        assert above["easement_value_cents"] == 12_000_000
        assert above["status"] == "SUBMITTED"
        assert above["submission_count"] == 3

        # Nothing was ever certified, so the application still has no value.
        assert read_application(application_id)["certified_easement_value_cents"] is None


class TestRoundingDirections:
    """One parcel exercises a floor rule and a half-up rule in the same spread."""

    def test_the_preliminary_floors_while_the_certified_rounds_half_up(self):
        """A gross of 74,515,000 lands on 67,000,000 and 74,520,000.

        PRD §3.3: "Subtract the parcel's `restricted_value_cents` from its
        `unrestricted_value_cents` to get the gross spread; take 90 percent of
        that spread; then floor the result down to a whole multiple of 100,000
        cents, that is, down to the nearest thousand dollars."

        PRD §3.4: "Divide by 10,000 cents, round half up to a whole number, and
        multiply back by 10,000: in other words, round half up to the nearest
        hundred dollars."

        Design: Corner/calculations/preliminary_floors_to_the_thousand_dollar_unit_while_certified_rounds_half_up_at_exactly_half_a_unit
        """
        scenario = setup_filed_application(
            parcel_overrides=HALF_UNIT_PARCEL,
            application_overrides={"requested_price_cents": 70_000_000},
        )
        application = scenario["application"]
        # 90 percent of 74,515,000 is 67,063,500, floored to the 100,000 unit.
        assert application["preliminary_easement_value_cents"] == 67_000_000
        assert application["preliminary_easement_value_cents"] < 67_063_500
        # The request was admitted because its ceiling is 73,700,000.
        assert application["requested_price_cents"] == 70_000_000
        assert application["status"] == "RECEIVED"

        appraisal = engage_appraisal(application["id"])
        set_clock(CLOCK_2026_08_20)
        submitted = submit_appraisal(
            appraisal["id"],
            unrestricted_value_cents=120_000_000,
            restricted_value_cents=45_485_000,
        )
        # 74,515,000 / 10,000 is exactly 7451.5, which rounds half up to 7452.
        assert submitted["easement_value_cents"] == 74_520_000
        assert submitted["easement_value_cents"] > 74_515_000
        assert submitted["status"] == "SUBMITTED"
        assert submitted["basis"] == "CERTIFIED_APPRAISAL_BASIS"


class TestStewardshipGraceWindow:
    """Both monitoring boundaries are half-open, so both instants belong right."""

    def test_the_due_instant_is_already_due_and_the_grace_boundary_already_late(self):
        """Four sweeps pin 2027-12-14, 2027-12-15, 2028-01-13 and 2028-01-14.

        PRD §3.8: "The posture is then read off the logical clock with both
        boundaries half-open: the easement is `MONITORING_CURRENT` while the clock
        is strictly before `next_monitoring_due_on`; it is `MONITORING_DUE` from
        the due instant itself up to but not including the due instant advanced
        by `monitoring_grace_days`; and it is `MONITORING_DELINQUENT` from that
        grace boundary onward."

        Design: Corner/calculations/stewardship_grace_window_is_half_open_at_the_delinquency_boundary
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        # 2026-12-15 advanced by the 365-day interval.
        assert scenario["easement"]["next_monitoring_due_on"].startswith("2027-12-15")

        set_clock("2027-12-14T00:00:00Z")
        counters = run_sweep()
        assert counters["due_count"] == 0
        assert counters["delinquent_count"] == 0
        day_before = read_easement(easement_id)
        assert day_before["stewardship_status"] == "MONITORING_CURRENT"

        set_clock("2027-12-15T00:00:00Z")
        counters = run_sweep()
        assert counters["due_count"] == 1
        assert counters["delinquent_count"] == 0
        assert read_easement(easement_id)["stewardship_status"] == "MONITORING_DUE"

        # Day 29 of a 30-day grace is still merely due.
        set_clock("2028-01-13T00:00:00Z")
        run_sweep()
        assert read_easement(easement_id)["stewardship_status"] == "MONITORING_DUE"

        set_clock("2028-01-14T00:00:00Z")
        counters = run_sweep()
        assert counters["delinquent_count"] == 1
        late = read_easement(easement_id)
        assert late["stewardship_status"] == "MONITORING_DELINQUENT"
        # No visit ever completed, so the anchor never left `recorded_on`.
        assert late["last_monitored_on"] is None
        assert late["next_monitoring_due_on"].startswith("2027-12-15")
        # The compliance dimension moved independently, which is to say not at all.
        assert late["compliance_status"] == "COMPLIANT"


class TestCompositeScoreWeights:
    """The weights must sum to 1.00, and only the weighted sum is rounded."""

    def test_unnormalized_weights_are_refused_and_the_normalized_sum_decomposes(self):
        """0.99 is refused; 73.40 decomposes into four exact products.

        PRD §3.1: "The weights — `soil_weight`, `size_weight`,
        `contiguity_weight` and `pressure_weight` — each lie between 0 and 1
        inclusive, carry exactly 2 decimals, and must together sum to exactly
        1.00; any other sum is rejected with `ERR_WEIGHTS_NOT_NORMALIZED` (422)."

        PRD §3.3: "Multiply each component by its matching program weight, add
        the four products, and round that single sum half up to 2 decimals."

        Design: Corner/calculations/composite_score_weights_must_normalize_and_the_weighted_sum_decomposes_without_drift
        """
        scenario = setup_filed_application()
        program_id = scenario["program"]["id"]

        validate_error(
            api_client.create_program(
                create_program_required_only_payload(
                    name="Unnormalized Weights Program", pressure_weight=0.24
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED.value,
        )
        intact = validate_success(api_client.get_program(program_id, ADMIN))
        assert intact["soil_weight"] == pytest.approx(0.35, abs=0.01)
        assert intact["pressure_weight"] == pytest.approx(0.25, abs=0.01)

        result = rank_round(scenario["round"]["id"], clock=CLOCK_2026_10_01)
        assert result["ranked_count"] == 1
        assert result["selected_count"] == 1

        ranked = read_application(scenario["application"]["id"])
        # 0.35x84.00 + 0.15x80.00 + 0.25x50.00 + 0.25x78.00
        expected = 0.35 * 84.00 + 0.15 * 80.00 + 0.25 * 50.00 + 0.25 * 78.00
        assert expected == pytest.approx(73.40, abs=0.01)
        assert ranked["composite_score"] == pytest.approx(73.40, abs=0.01)
        assert ranked["contiguity_acres_at_receipt"] == pytest.approx(80.00, abs=0.01)
        assert ranked["rank_position"] == 1
        assert ranked["status"] == "RANKED"
        assert scenario["parcel"]["acres"] == pytest.approx(160.00, abs=0.01)

        funding_round = validate_success(
            api_client.get_funding_round(scenario["round"]["id"], ADMIN)
        )
        assert funding_round["score_basis"] == "RECEIPT_BASIS"


class TestCounterReconcilesThePlan:
    """A counter moves the cost while the plan's snapshot stays put."""

    def test_the_counter_underfunds_the_plan_without_releasing_a_commitment(self):
        """`total_program_cost_cents` moves; `funded_cost_cents` does not.

        PRD §3.5: "Because the program cost has moved while the snapshot in
        `funded_cost_cents` has not, any assembled plan is now stale and
        `funding_plan_status` flips `FUNDED → UNDERFUNDED`; an application whose
        `funding_plan_status` is still `UNFUNDED` is left alone."

        Design: Corner/calculations/counter_rewrites_the_total_and_reconciles_the_funding_plan_down_to_underfunded
        """
        scenario = setup_funded_application(offer_cents=170_000_000)
        application_id = scenario["application"]["id"]
        before = scenario["application"]
        # 170,000,000 less a 10 percent donation, plus a 1.5 percent fee.
        assert before["total_program_cost_cents"] == 155_295_000
        assert before["funded_cost_cents"] == 155_295_000
        assert before["funding_plan_status"] == "FUNDED"

        reserved = commitments_of(application_id)
        assert {row["status"] for row in reserved} == {"RESERVED"}
        # All three floored caps are exact here, so nothing is absorbed.
        assert sorted(row["amount_cents"] for row in reserved) == [
            38_823_750,
            54_353_250,
            62_118_000,
        ]
        assert {row["absorbed_remainder_cents"] for row in reserved} == {0}

        countered = file_counter(
            application_id,
            scenario["landowner"]["id"],
            175_550_000,
            rationale="the certified value is higher than the offer",
        )
        assert countered["status"] == "COUNTERED"
        assert countered["donation_cents"] == 17_555_000
        assert countered["bargain_sale_price_cents"] == 157_995_000
        assert countered["admin_fee_cents"] == 2_369_925
        assert countered["total_program_cost_cents"] == 160_364_925
        assert countered["funded_cost_cents"] == 155_295_000
        assert countered["funding_plan_status"] == "UNDERFUNDED"

        # The reconciliation is a status flip only — no commitment is touched.
        _rows, meta = validate_paginated(
            api_client.list_funding_commitments(
                ADMIN, {"application_id": application_id, "status": "RESERVED"}
            )
        )
        assert meta["total_count"] == 3
        assert read_source(scenario["sources"]["local"]["id"])["reserved_cents"] == (
            54_353_250
        )


class TestViolationSeverity:
    """2,000 square feet of excess is the last MINOR value."""

    def test_severity_and_the_cure_clock_flip_strictly_above_two_thousand(self):
        """2,000 gets 180 days; 2,001 gets 90, both from the same opening date.

        PRD §3.8: "The violation's `severity` — the enumeration is `MINOR` and
        `MAJOR` — is `MAJOR` when its `excess_sqft` is strictly greater than 2,000
        square feet and `MINOR` otherwise, so an excess of exactly 2,000 is
        `MINOR` while 2,001 is `MAJOR`. `opened_on` is the logical clock at
        creation. A `MINOR` violation is given 180 days to cure and a `MAJOR` one
        only 90, and `cure_deadline_on` is `opened_on` advanced by that whole
        number of days."

        Design: Corner/calculations/violation_severity_flips_strictly_above_two_thousand_excess_square_feet
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        assert scenario["easement"]["impervious_allowance_sqft"] == 139_392

        set_clock("2027-06-03T00:00:00Z")
        minor = open_violation(
            easement_id,
            violation_type="IMPERVIOUS_EXCEEDANCE",
            excess_sqft=2_000,
            notes="exactly at the major threshold",
        )
        assert minor["severity"] == "MINOR"
        assert minor["status"] == "OPEN"
        assert minor["opened_on"].startswith("2027-06-03")
        # 2027-06-03 advanced by 180 days.
        assert minor["cure_deadline_on"].startswith("2027-11-30")

        major = open_violation(
            easement_id,
            violation_type="IMPERVIOUS_EXCEEDANCE",
            excess_sqft=2_001,
            notes="one square foot over the major threshold",
        )
        assert major["severity"] == "MAJOR"
        assert major["status"] == "OPEN"
        assert major["opened_on"].startswith("2027-06-03")
        # The same anchor, advanced by 90 days instead.
        assert major["cure_deadline_on"].startswith("2027-09-01")

        easement = read_easement(easement_id)
        assert easement["open_violation_count"] == 2
        assert easement["compliance_status"] == "VIOLATION_OPEN"
        assert easement["stewardship_hold"] is True
