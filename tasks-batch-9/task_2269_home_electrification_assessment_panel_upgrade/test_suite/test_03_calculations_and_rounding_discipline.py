"""Tier arithmetic, per-line flooring, quality candidacy, sweep order and reconciliation."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    DEFAULT_LOW_TIER_CAP_CENTS,
    DEFAULT_MODERATE_TIER_CAP_CENTS,
    DEFAULT_STANDARD_TIER_CAP_CENTS,
    IncomeTier,
    InspectionStatus,
    InspectionType,
    MEASURE_HP_HVAC,
    ProjectStatus,
    QuoteVariant,
    REVIEWER_HEADERS,
    ReservationStatus,
    add_catalog,
    assert_household_cap,
    assert_program_buckets,
    assert_quote_line,
    assert_quote_totals_match_lines,
    build_assessment_measure,
    build_hvac_heat_pump_payload,
    build_measure_result,
    build_pass_result_payload,
    build_project_measure,
    build_world,
    cancel_inspection,
    create_approved_assessment,
    create_enrolled_contractor,
    create_household,
    create_inspector,
    create_open_program,
    create_project,
    create_verified_household,
    file_income_verification,
    find_measure_line,
    pay_project,
    read_assessment,
    read_contractor,
    read_household,
    read_program,
    read_project,
    read_project_measures,
    read_quality_review,
    read_quote,
    read_reservation,
    record_result,
    report_installation,
    reserve_project,
    review_project,
    schedule_inspection,
    set_clock,
    submit_project,
    sweep,
    validate_paginated,
    verify_income_verification,
)

#  A four-person benchmark median, so the size adjustment factor is exactly 1.00
#  and the AMI percentage is the plain income-to-median ratio.
BENCHMARK_MEDIAN_CENTS = 10000000

TIER_BOUNDARY_CASES = [
    (8000000, 80.0, IncomeTier.LOW, DEFAULT_LOW_TIER_CAP_CENTS),
    (8010000, 80.1, IncomeTier.MODERATE, DEFAULT_MODERATE_TIER_CAP_CENTS),
    (15000000, 150.0, IncomeTier.MODERATE, DEFAULT_MODERATE_TIER_CAP_CENTS),
    (15010000, 150.1, IncomeTier.STANDARD, DEFAULT_STANDARD_TIER_CAP_CENTS),
]

SIZE_ADJUSTMENT_CASES = [
    (1, 114.3, IncomeTier.MODERATE, DEFAULT_MODERATE_TIER_CAP_CENTS),
    (5, 74.1, IncomeTier.LOW, DEFAULT_LOW_TIER_CAP_CENTS),
    (7, 64.5, IncomeTier.LOW, DEFAULT_LOW_TIER_CAP_CENTS),
    (9, 64.5, IncomeTier.LOW, DEFAULT_LOW_TIER_CAP_CENTS),
]


class TestIncomeTierAssignment:
    @pytest.mark.parametrize(
        "income_cents,expected_ami,expected_tier,expected_cap", TIER_BOUNDARY_CASES
    )
    def test_tier_thresholds_are_inclusive_at_eighty_and_one_hundred_fifty(
        self, api, income_cents, expected_ami, expected_tier, expected_cap
    ):
        """Both tier boundaries admit the household sitting exactly on them.

        PRD §3.2: "If the rounded percentage is less than or equal to the
        program's `ami_low_threshold_pct`, the tier is `LOW`. Otherwise, if it is
        less than or equal to `ami_moderate_threshold_pct`, the tier is
        `MODERATE`. Otherwise the tier is `STANDARD`."

        PRD §3.2: "The lifetime cap is the program's cap for that tier:
        `low_tier_cap_cents` for `LOW`, `moderate_tier_cap_cents` for `MODERATE`,
        `standard_tier_cap_cents` for `STANDARD`."

        Design: Corner/calculations/income_tier_thresholds_are_inclusive_at_eighty_and_one_fifty
        """
        program = create_open_program(api)
        household = create_household(api, program["id"])

        packet = file_income_verification(
            api,
            household["id"],
            annual_household_income_cents=income_cents,
            county_median_income_cents=BENCHMARK_MEDIAN_CENTS,
            household_size_attested=4,
        )
        decided = verify_income_verification(api, packet["id"])

        assert decided["computed_ami_percent"] == pytest.approx(expected_ami, abs=0.01)
        assert decided["assigned_income_tier"] == expected_tier
        assert decided["assigned_cap_cents"] == expected_cap

        stored = read_household(api, household["id"])
        assert stored["ami_percent"] == pytest.approx(expected_ami, abs=0.01)
        assert stored["income_tier"] == expected_tier
        assert stored["rebate_cap_cents"] == expected_cap
        assert stored["encumbered_cents"] == 0
        assert stored["lifetime_cap_remaining_cents"] == expected_cap

    @pytest.mark.parametrize(
        "attested_size,expected_ami,expected_tier,expected_cap", SIZE_ADJUSTMENT_CASES
    )
    def test_the_size_adjustment_factor_clamps_at_seven_occupants(
        self, api, attested_size, expected_ami, expected_tier, expected_cap
    ):
        """The factor scales the benchmark median and stops growing past seven.

        PRD §3.2: "Take the attested occupant count, and if it exceeds 7 treat it
        as 7. Look up the size adjustment factor for that count: 0.70 for one
        occupant, 0.80 for two, 0.90 for three, 1.00 for four, 1.08 for five, 1.16
        for six, and 1.24 for seven or more."

        PRD §3.2: "Multiply `county_median_income_cents` by that factor to obtain
        the size-adjusted median income."

        PRD §3.2: "the household's own `household_size` field is never used, only
        `household_size_attested`"

        Design: Corner/calculations/size_adjustment_constant_clamps_at_household_size_seven
        """
        program = create_open_program(api)
        #  The intake record keeps its own occupant count of four throughout, so
        #  only the attested count can be driving the arithmetic below.
        household = create_household(api, program["id"], household_size=4)

        packet = file_income_verification(
            api,
            household["id"],
            annual_household_income_cents=8000000,
            county_median_income_cents=BENCHMARK_MEDIAN_CENTS,
            household_size_attested=attested_size,
        )
        decided = verify_income_verification(api, packet["id"])

        assert decided["household_size_attested"] == attested_size
        assert decided["computed_ami_percent"] == pytest.approx(expected_ami, abs=0.01)
        assert decided["assigned_income_tier"] == expected_tier
        assert decided["assigned_cap_cents"] == expected_cap

        stored = read_household(api, household["id"])
        assert stored["household_size"] == 4
        assert stored["ami_percent"] == pytest.approx(expected_ami, abs=0.01)
        assert stored["income_tier"] == expected_tier
        assert stored["rebate_cap_cents"] == expected_cap


class TestPerLineIncentiveArithmetic:
    def test_the_cost_share_ceiling_floors_while_the_ami_percent_rounds_half_up(self, api):
        """Two different rounding rules meet on one project and neither borrows the other's.

        PRD §2.6: "**Percent-of-income arithmetic** rounds half up to one decimal
        place, and it rounds **before** any threshold comparison is made. The tier
        test therefore reads the rounded percentage, never the unrounded quotient."

        PRD §3.5: "It computes a cost-share ceiling as the line's cost multiplied
        by the household's tier cost-share fraction, floored to whole cents. The
        line amount is then the smallest of three values: the raw amount, the
        `pinned_measure_cap_cents`, and the cost-share ceiling."

        Design: Corner/calculations/cost_share_floors_the_half_cent_while_ami_rounds_half_up
        """
        program = create_open_program(api)
        add_catalog(api, program["id"], [build_hvac_heat_pump_payload()])
        household = create_household(api, program["id"])

        #  149.95 percent rounds half up to exactly the moderate boundary, so the
        #  cost-share fraction in force is 0.50.
        packet = file_income_verification(
            api,
            household["id"],
            annual_household_income_cents=14995000,
            county_median_income_cents=BENCHMARK_MEDIAN_CENTS,
            household_size_attested=4,
        )
        decided = verify_income_verification(api, packet["id"])
        assert decided["computed_ami_percent"] == pytest.approx(150.0, abs=0.01)
        assert decided["assigned_income_tier"] == IncomeTier.MODERATE
        assert decided["assigned_cap_cents"] == DEFAULT_MODERATE_TIER_CAP_CENTS

        contractor = create_enrolled_contractor(api, program["id"])
        assessment = create_approved_assessment(
            api,
            household["id"],
            contractor["id"],
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000001)],
        )
        #  An odd cost makes the half-cent visible: 1000001 * 0.50 is 500000.5.
        assert read_assessment(api, assessment["id"])["estimated_total_incentive_cents"] == 500000

        project = create_project(
            api,
            household["id"],
            assessment["id"],
            contractor["id"],
            packet["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000001)],
            estimated_project_cost_cents=1000001,
        )
        assert project["provisional_total_incentive_cents"] == 500000
        assert isinstance(project["provisional_total_incentive_cents"], int)

        line = find_measure_line(read_project_measures(api, project["id"]), MEASURE_HP_HVAC)
        assert line["provisional_incentive_cents"] == 500000
        assert isinstance(line["provisional_incentive_cents"], int)

        quote = read_quote(api, project["id"], QuoteVariant.PROVISIONAL)
        assert_quote_line(
            quote,
            MEASURE_HP_HVAC,
            raw_incentive_cents=800000,
            cost_share_cap_cents=500000,
            capped_line_cents=500000,
            allocated_cents=500000,
        )
        assert quote["total_incentive_cents"] == 500000
        assert quote["group_capped_total_cents"] == 500000
        assert quote["household_cap_limit_cents"] == DEFAULT_MODERATE_TIER_CAP_CENTS
        assert quote["group_cap_applied"] is False
        assert quote["household_cap_applied"] is False
        assert quote["residual_cents_assigned_to_measure_code"] is None
        assert_quote_totals_match_lines(quote)


class TestQualityScoreCandidateSet:
    def test_cancelled_and_still_scheduled_inspections_never_reach_the_quality_score(self, api):
        """Only recorded outcomes are candidates, and a cancelled window frees its slot.

        PRD §3.3: "The candidate set is every inspection whose project belongs to
        this contractor and whose status is `PASSED`, `CONDITIONAL_PASS`, or
        `FAILED`, regardless of what state the project itself is in; inspections
        still `SCHEDULED` and inspections `CANCELLED` are excluded entirely."

        PRD §3.3: "An empty window yields a score of 100 under either measure."

        PRD §3.8: "moving it `SCHEDULED → CANCELLED` and incrementing its version;
        the cancelled window stops participating in the conflict rule."

        Design: Corner/calculations/quality_score_candidates_exclude_cancelled_and_scheduled_inspections
        """
        world = build_world(
            api,
            stage="installed",
            catalog=[build_hvac_heat_pump_payload()],
            measure_results=[build_measure_result(MEASURE_HP_HVAC, 1, 700000)],
        )
        contractor_id = world["contractor_id"]
        project_id = world["project_id"]

        inspector_one = create_inspector(
            api, world["program_id"], inspector_name="Tova Lind", certification_id="INS-61"
        )
        inspector_two = create_inspector(
            api, world["program_id"], inspector_name="Uri Peled", certification_id="INS-62"
        )

        abandoned = schedule_inspection(
            api,
            project_id,
            inspector_one["id"],
            scheduled_start="2026-08-21T09:00:00Z",
            scheduled_end="2026-08-21T11:00:00Z",
        )
        cancelled = cancel_inspection(
            api,
            abandoned["id"],
            cancellation_reason="Inspector reassigned to a storm response",
        )
        assert cancelled["status"] == InspectionStatus.CANCELLED

        empty_window = read_quality_review(api, contractor_id)
        assert empty_window["rolling_window_score"] == 100
        assert empty_window["severity_weighted_score"] == 100
        assert empty_window["rolling_window_inspection_count"] == 0
        assert empty_window["weighted_inspection_count"] == 0

        #  11:30 sits inside the 45-minute buffer behind the cancelled 11:00 end,
        #  so this request would conflict if the cancelled row still counted.
        post_install = schedule_inspection(
            api,
            project_id,
            inspector_one["id"],
            scheduled_start="2026-08-21T11:30:00Z",
            scheduled_end="2026-08-21T13:30:00Z",
        )
        assert post_install["status"] == InspectionStatus.SCHEDULED

        pending = read_quality_review(api, contractor_id)
        assert pending["rolling_window_inspection_count"] == 0
        assert read_contractor(api, contractor_id)["completed_inspection_count"] == 0

        record_result(api, post_install["id"], inspector_one["id"], build_pass_result_payload())
        after_first = read_quality_review(api, contractor_id)
        assert after_first["rolling_window_score"] == 100
        assert after_first["rolling_window_inspection_count"] == 1
        assert read_contractor(api, contractor_id)["completed_inspection_count"] == 1

        spot = schedule_inspection(
            api,
            project_id,
            inspector_two["id"],
            InspectionType.SPOT,
            scheduled_start="2026-08-25T09:00:00Z",
            scheduled_end="2026-08-25T10:00:00Z",
        )
        still_one = read_quality_review(api, contractor_id)
        assert still_one["rolling_window_inspection_count"] == 1
        assert read_contractor(api, contractor_id)["completed_inspection_count"] == 1

        record_result(api, spot["id"], inspector_two["id"], build_pass_result_payload())
        after_second = read_quality_review(api, contractor_id)
        assert after_second["rolling_window_score"] == 100
        assert after_second["rolling_window_inspection_count"] == 2
        assert read_contractor(api, contractor_id)["completed_inspection_count"] == 2

        rows, meta = validate_paginated(
            api.list_inspections(REVIEWER_HEADERS, {"project_id": project_id})
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3


class TestExpirySweepOrdering:
    def test_the_sweep_processes_due_reservations_in_expiry_order_not_creation_order(self, api):
        """Creation order and expiry order disagree, and the sweep follows expiry.

        PRD §3.6: "A `ProgramAdmin` runs the expiry sweep for a program, which
        collects that program's reservations in status `RESERVED` whose
        `expires_at` is less than or equal to the logical clock — the comparison is
        inclusive, so a reservation expiring exactly now does expire — and
        processes them in `expires_at` ascending order and then `created_at`
        ascending order. Ordering never falls back to identifiers."

        PRD §3.6: "The sweep reports a `program_id`, a `swept_reservation_count`, a
        `released_cents` total summing the released reserved amounts, an
        `expired_project_ids` array in processing order, and the resulting
        `program_budget_available_cents`."

        Design: Corner/calculations/sweep_expires_due_reservations_in_expires_at_order_not_creation_order
        """
        world = build_world(
            api,
            stage="approved",
            catalog=[build_hvac_heat_pump_payload()],
            household_overrides={
                "applicant_name": "Early Expiry",
                "email": "early@example.com",
                "service_address_line1": "70 Early Ln",
            },
        )
        program_id = world["program_id"]
        contractor_id = world["contractor_id"]
        project_early = world["project"]

        late = create_verified_household(
            api,
            program_id,
            applicant_name="Late Expiry",
            email="late@example.com",
            service_address_line1="80 Late Ln",
        )
        late_household = late["household"]
        late_assessment = create_approved_assessment(
            api,
            late_household["id"],
            contractor_id,
            [build_assessment_measure(MEASURE_HP_HVAC, 1, 1000000)],
        )
        project_late = create_project(
            api,
            late_household["id"],
            late_assessment["id"],
            contractor_id,
            late["income_verification"]["id"],
            [build_project_measure(MEASURE_HP_HVAC, 1, 1000000)],
            estimated_project_cost_cents=1000000,
        )
        submit_project(api, project_late["id"], contractor_id)
        review_project(api, project_late["id"])

        #  The later-expiring reservation is created FIRST, then the clock is moved
        #  backwards so the second reservation expires four days earlier.
        set_clock(api, "2026-08-05T00:00:00Z")
        reservation_late = reserve_project(api, project_late["id"], program_id)
        set_clock(api, "2026-08-01T00:00:00Z")
        reservation_early = reserve_project(api, project_early["id"], program_id)

        assert reservation_late["expires_at"].startswith("2026-12-03")
        assert reservation_early["expires_at"].startswith("2026-11-29")
        assert reservation_early["expires_at"] < reservation_late["expires_at"]
        assert reservation_late["reserved_amount_cents"] == 800000
        assert reservation_early["reserved_amount_cents"] == 800000

        set_clock(api, "2026-12-05T00:00:00Z")
        result = sweep(api, program_id)

        assert result["program_id"] == program_id
        assert result["swept_reservation_count"] == 2
        assert result["released_cents"] == 1600000
        assert result["expired_project_ids"] == [project_early["id"], project_late["id"]]
        assert result["program_budget_available_cents"] == 50000000

        assert_program_buckets(
            read_program(api, program_id), available=50000000, reserved=0, committed=0
        )
        assert read_reservation(api, reservation_early["id"])["status"] == ReservationStatus.EXPIRED
        assert read_reservation(api, reservation_late["id"])["status"] == ReservationStatus.EXPIRED
        assert read_project(api, project_early["id"])["status"] == ProjectStatus.EXPIRED
        assert read_project(api, project_late["id"])["status"] == ProjectStatus.EXPIRED
        assert_household_cap(
            read_household(api, world["household_id"]),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )
        assert_household_cap(
            read_household(api, late_household["id"]),
            remaining=DEFAULT_LOW_TIER_CAP_CENTS,
            encumbered=0,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )


class TestDisbursementReconciliation:
    def test_an_upward_final_total_is_still_capped_by_the_initial_reservation(self, api):
        """A job that cost more than estimated is paid the reservation, not the entitlement.

        PRD §3.9: "The disbursed amount is the smaller of that basis and the
        reservation's `initial_reserved_amount_cents`, and the release difference
        is the initial reserved amount less the disbursed amount — never negative,
        because the disbursement is capped by the initial reservation."

        PRD §3.5: "the final computation uses `verified_quantity` and
        `actual_cost_cents`."

        Design: Corner/calculations/upward_final_variant_is_capped_by_the_initial_reservation_on_payment
        """
        world = build_world(
            api,
            stage="reserved",
            catalog=[build_hvac_heat_pump_payload()],
            assessment_measures=[build_assessment_measure(MEASURE_HP_HVAC, 1, 500000)],
        )
        project_id = world["project_id"]
        reservation = world["reservation"]

        #  The estimate of 500000 is what the cost-share ceiling bound, so the
        #  reservation encumbers less than the measure's own 800000 ceiling.
        assert world["project"]["provisional_total_incentive_cents"] == 500000
        assert reservation["initial_reserved_amount_cents"] == 500000
        assert reservation["reserved_amount_cents"] == 500000
        assert_program_buckets(
            world["program"], available=49500000, reserved=500000, committed=0
        )
        assert_household_cap(
            world["household"],
            remaining=900000,
            encumbered=500000,
            cap=DEFAULT_LOW_TIER_CAP_CENTS,
        )

        report_installation(
            api,
            project_id,
            world["contractor_id"],
            [build_measure_result(MEASURE_HP_HVAC, 1, 900000)],
            actual_project_cost_cents=900000,
        )
        inspector = create_inspector(api, world["program_id"])
        inspection = schedule_inspection(api, project_id, inspector["id"])
        record_result(api, inspection["id"], inspector["id"], build_pass_result_payload())

        verified = read_project(api, project_id)
        assert verified["status"] == ProjectStatus.VERIFIED
        #  min(raw 800000, pinned cap 800000, floor(900000 * 1.00)) == 800000.
        assert verified["final_total_incentive_cents"] == 800000

        paid = pay_project(api, project_id, ADMIN_HEADERS, payment_reference="ACH-9301")
        assert paid["status"] == ProjectStatus.PAID
        assert paid["disbursed_amount_cents"] == 500000

        #  The release difference is zero, so nothing returns to the appropriation.
        assert_program_buckets(
            read_program(api, world["program_id"]),
            available=49500000,
            reserved=0,
            committed=500000,
        )
        household = read_household(api, world["household_id"])
        assert_household_cap(
            household, remaining=900000, encumbered=500000, cap=DEFAULT_LOW_TIER_CAP_CENTS
        )
        assert household["rebate_cap_cents"] == (
            household["lifetime_cap_remaining_cents"] + household["encumbered_cents"]
        )

        committed = read_reservation(api, reservation["id"])
        assert committed["status"] == ReservationStatus.COMMITTED
        assert committed["initial_reserved_amount_cents"] == 500000
        assert committed["reserved_amount_cents"] == 500000
        assert committed["committed_at"] is not None
