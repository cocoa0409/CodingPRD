"""
The declared constants and formulas read off finished ledgers: criterion weights,
the diversity pool filter, the withholding switch, the three-way split and the
readiness threshold.
"""

from conftest import nominate, seat

from test_helpers import (
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    api_client,
    assert_cents,
    assert_installment,
    assert_net_identity,
    assert_rate,
    assert_score,
    cornermain_award_accepted,
    cornermain_cycle_panel_review,
    cornermain_round_closed,
    list_installments_of,
    read_application,
    read_award,
    read_panel,
    twoslot_slate_submitted,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCriterionWeights:
    """Four unequal weights, three separating literals."""

    def test_three_review_score_sets_land_on_their_weighted_not_averaged_values(self):
        """
        The same closed round holds reviews scored (9,8,7,6), (7,7,6,5) and (8,6,8,7), whose
        weighted values are 8.00, 6.60 and 7.30 rather than the 7.50, 6.25 and 7.25 a plain
        four-criterion average would give, and their mean carries through to the application.

        PRD: "`weighted_score` weights the four criteria unequally, because artistic merit
        dominates the council's rubric: forty percent on `artistic_excellence`, thirty percent
        on `work_sample_quality`, twenty percent on `career_impact` and ten percent on
        `public_value`."

        PRD: "Criterion scores of 9, 8, 7 and 6 in that order therefore give 8.00, and 7, 7, 6
        and 5 give 6.60."

        Design: Corner/calculations/review_weighted_score_uses_the_declared_criterion_weights
        """
        ctx = cornermain_round_closed()

        expected = ((ctx.rv1, 8.00), (ctx.rv2, 6.60), (ctx.rv3, 7.30))
        for review_id, weighted in expected:
            review = validate_success(api_client.get_review(review_id, PROGRAM_OFFICER))
            assert_score(review["weighted_score"], weighted, "review.weighted_score")
            assert review["status"] == "SUBMITTED", (
                f"a counted review stays SUBMITTED, got {review['status']}"
            )
            assert review["round_number"] == 1, (
                f"all three belong to round 1, got {review['round_number']}"
            )
            assert review["invalidation_reason"] is None, (
                f"nothing invalidated these reviews, got {review['invalidation_reason']}"
            )

        application = read_application(ctx.app)
        assert application["valid_review_count"] == 3, (
            f"three counted reviews, got {application['valid_review_count']}"
        )
        assert_score(
            application["provisional_composite_score"],
            7.30,
            "application.provisional_composite_score",
        )
        assert_score(
            application["final_composite_score"], 7.30, "application.final_composite_score"
        )
        assert_score(application["score_spread"], 1.40, "application.score_spread")


class TestDiversityPoolFilter:
    """Four applications on file, two of them outside the pool."""

    def test_the_draft_and_the_ineligible_row_never_reach_the_index(self):
        """
        Of four applications the draft one and the one determined ineligible are excluded, so
        the pool is two evenly split regions: an index of 0.5000 and a distribution score of
        62.50, with nothing funded yet.

        PRD: "The **eligible pool** is every application of the cycle whose `status` is
        anything other than `DRAFT`, `WITHDRAWN` or `INELIGIBLE`, and `eligible_pool_size` is
        its size."

        PRD: "`geographic_distribution_score` is then derived from the **rounded** index — the
        evaluation order is normative — as 125 multiplied by one less that rounded index,
        rounded half up to two decimal places."

        Design: Corner/calculations/diversity_pool_excludes_draft_and_ineligible_applications
        """
        ctx = twoslot_slate_submitted()

        evaluation = validate_success(
            api_client.get_cycle_evaluation(ctx.tcyc, PROGRAM_OFFICER)
        )
        assert evaluation["eligible_pool_size"] == 2, (
            "the draft and the ineligible application are filtered out, got "
            f"{evaluation['eligible_pool_size']}"
        )
        assert_rate(evaluation["region_hhi"], 0.5000, "evaluation.region_hhi")
        assert_score(
            evaluation["geographic_distribution_score"],
            62.50,
            "evaluation.geographic_distribution_score",
        )
        assert_rate(evaluation["funded_rate"], 0.0000, "evaluation.funded_rate")

        regions = evaluation["region_breakdown"]
        assert len(regions) == 2, (
            f"the pool spans two regions, got {len(regions)} rows"
        )
        assert [row["applicant_count"] for row in regions] == [1, 1], (
            "one applicant in each region, got "
            f"{[row['applicant_count'] for row in regions]}"
        )
        for row in regions:
            assert_rate(row["share"], 0.5, "region_breakdown.share")

        disciplines = evaluation["discipline_breakdown"]
        assert len(disciplines) == 1, (
            f"the cycle has one discipline, got {len(disciplines)} rows"
        )
        assert disciplines[0]["eligible_application_count"] == 2, (
            "two eligible determinations were made, got "
            f"{disciplines[0]['eligible_application_count']}"
        )
        assert disciplines[0]["funded_application_count"] == 0, (
            "no slot has been approved, got "
            f"{disciplines[0]['funded_application_count']}"
        )
        assert_cents(
            disciplines[0]["committed_cents"], 0, "discipline_breakdown.committed_cents"
        )

        first = read_application(ctx.appA)
        second = read_application(ctx.appB)
        assert_score(first["final_composite_score"], 7.30, "appA.final_composite_score")
        assert_score(second["final_composite_score"], 7.00, "appB.final_composite_score")
        assert_score(second["score_spread"], 2.00, "appB.score_spread")


class TestWithholdingSwitch:
    """The 0.2707 rate is conditional, and the offsets are not."""

    def test_a_recipient_with_a_tin_on_file_is_withheld_nothing(self):
        """
        Every installment of a 1,500,000-cent award to a recipient whose taxpayer
        identification number is on file carries a zero rate, zero withholding and a net equal
        to its gross, and the three scheduled dates sit at the declared day offsets from the
        grant period start.

        PRD: "First fix the withholding rate: it is 0.2707 when the artist's `tin_status` is
        anything other than `ON_FILE` at this moment, and 0 when the status is `ON_FILE`; the
        rate that results is stored on each installment as `withholding_rate`."

        PRD: "Each installment takes an `installment_number` of 1, 2 or 3 and a
        `scheduled_date` of the award's `grant_period_start` date plus an offset of 0, 120 and
        240 days respectively."

        Design: Corner/calculations/withholding_constants_are_bypassed_when_the_tin_is_on_file
        """
        ctx = cornermain_award_accepted()

        rows, meta = validate_paginated(
            api_client.list_installments(FISCAL_OFFICER, {"award_id": ctx.aw, "limit": 100})
        )
        assert meta["total_count"] == 3, (
            f"the schedule always has three rows, got {meta['total_count']}"
        )
        by_number = {row["installment_number"]: row for row in rows}
        assert sorted(by_number) == [1, 2, 3], (
            f"the rows are numbered 1, 2 and 3, got {sorted(by_number)}"
        )

        expected = (
            (1, 600_000, "2027-01-01"),
            (2, 525_000, "2027-05-01"),
            (3, 375_000, "2027-08-29"),
        )
        for number, gross, scheduled_date in expected:
            row = by_number[number]
            assert row["status"] == "SCHEDULED", (
                f"installment {number} starts SCHEDULED, got {row['status']}"
            )
            assert_installment(
                row,
                installment_number=number,
                gross_cents=gross,
                withholding_rate=0.0,
                withholding_cents=0,
                net_cents=gross,
                scheduled_date=scheduled_date,
            )
            assert_net_identity(row)

        award = read_award(ctx.aw)
        assert_cents(
            award["scheduled_withholding_cents"], 0, "award.scheduled_withholding_cents"
        )
        assert_cents(
            award["undisbursed_gross_cents"], 1_500_000, "award.undisbursed_gross_cents"
        )
        assert str(award["final_report_due_at"]).startswith("2028-02-29"), (
            "the report falls due sixty days after the grant period ends, got "
            f"{award['final_report_due_at']}"
        )


class TestGrossSplitConservation:
    """Two rounded percentages and one subtraction."""

    def test_the_third_installment_absorbs_whatever_the_first_two_left(self):
        """
        The three gross figures are 600,000, 525,000 and 375,000, and the third is the
        subtraction rather than a third percentage, so the three add back to the award's gross
        exactly with nothing lost or invented.

        PRD: "Next split the gross: installment one's `gross_cents` is forty percent of the
        award's `gross_amount_cents` rounded half up to a whole cent, installment two's is
        thirty-five percent rounded the same way, and installment three's is the award's
        `gross_amount_cents` less the first two — a subtraction, so the remainder absorbs any
        rounding drift and the three gross figures sum to the award gross exactly."

        Design: Corner/calculations/installment_split_puts_the_rounding_remainder_in_the_third_row
        """
        ctx = cornermain_award_accepted()
        rows = list_installments_of(ctx.aw)
        by_number = {row["installment_number"]: row for row in rows}

        assert_cents(by_number[1]["gross_cents"], 600_000, "installment 1 gross_cents")
        assert_cents(by_number[2]["gross_cents"], 525_000, "installment 2 gross_cents")
        assert_cents(by_number[3]["gross_cents"], 375_000, "installment 3 gross_cents")

        award = read_award(ctx.aw)
        assert_cents(award["gross_amount_cents"], 1_500_000, "award.gross_amount_cents")
        total = sum(by_number[number]["gross_cents"] for number in (1, 2, 3))
        assert total == award["gross_amount_cents"], (
            "the three gross figures must sum to the award gross exactly, got "
            f"{total} against {award['gross_amount_cents']}"
        )
        assert by_number[3]["gross_cents"] == (
            award["gross_amount_cents"]
            - by_number[1]["gross_cents"]
            - by_number[2]["gross_cents"]
        ), "the third row is the subtraction, not a third rounded percentage"


class TestReadinessThreshold:
    """Seventy-five exactly is admitted, and the region factor is not optional."""

    def test_thirty_three_point_three_three_fails_and_seventy_five_exactly_passes(self):
        """
        A four-seat panel needing three regions reads 33.33 with two seats covering two
        regions and is refused a charter; the third seat lifts it to exactly 75.00, which the
        threshold admits.

        PRD: "Multiply 100 by the seat ratio, the region ratio, the conflict multiplier and
        the bonus, take the smaller of that product and 100, and round half up to two
        decimals."

        PRD: "The `readiness_score` must be at least 75.00, and at least one seated panelist
        must carry the panel's own discipline code among their `expertise_codes`; either
        failure is reported as `ERR_PANEL_NOT_READY`."

        Design: Corner/calculations/charter_gate_passes_at_exactly_the_seventy_five_readiness_threshold
        """
        ctx = cornermain_cycle_panel_review()
        panel_id = validate_success(
            api_client.create_panel(
                {
                    "cycle_id": ctx.cyc,
                    "discipline_category_id": ctx.disc,
                    "required_seats": 4,
                    "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
                    "deliberation_window_start": "2026-11-01T00:00:00Z",
                    "deliberation_window_end": "2026-12-01T00:00:00Z",
                },
                PROGRAM_OFFICER,
            ),
            expected_status=201,
        )["id"]
        seat(nominate(panel_id, "chair.north@example.org", "Kira Vale", "NORTH", is_chair=True))
        seat(nominate(panel_id, "reader.central@example.org", "Lev Ostrom", "CENTRAL"))

        two_seated = read_panel(panel_id)
        assert two_seated["seated_count"] == 2, (
            f"two of four seats, got {two_seated['seated_count']}"
        )
        assert two_seated["region_coverage_count"] == 2, (
            f"two of three regions, got {two_seated['region_coverage_count']}"
        )
        assert_score(two_seated["readiness_score"], 33.33, "panel.readiness_score")

        validate_error(
            api_client.charter_panel(panel_id, PROGRAM_OFFICER), "ERR_PANEL_NOT_READY"
        )
        assert read_panel(panel_id)["status"] == "FORMING", (
            "a refused charter leaves the panel FORMING"
        )

        seat(nominate(panel_id, "reader.south@example.org", "Mira Sol", "SOUTH"))
        third = read_panel(panel_id)
        assert third["seated_count"] == 3, (
            f"three of four seats, got {third['seated_count']}"
        )
        assert third["region_coverage_count"] == 3, (
            f"all three regions, got {third['region_coverage_count']}"
        )
        assert_score(third["readiness_score"], 75.00, "panel.readiness_score")

        chartered = validate_success(api_client.charter_panel(panel_id, PROGRAM_OFFICER))
        assert chartered["status"] == "CHARTERED", (
            f"exactly 75.00 is admitted by the threshold, got {chartered['status']}"
        )
        assert chartered["assigned_application_count"] == 1, (
            "the one eligible application is claimed, got "
            f"{chartered['assigned_application_count']}"
        )
