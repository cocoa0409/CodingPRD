"""
Residency arithmetic at the month boundary, the submission rejection ladder and the
applicant-standing gate that sits on a different row from the application.
"""

from conftest import build_application, register_artist

from test_helpers import (
    PROGRAM_OFFICER,
    PROGRAM_OFFICER_ID,
    api_client,
    assert_unsubmitted_draft,
    add_second_application,
    cyclemain_application_draft,
    cyclemain_application_submitted,
    cyclemain_cycle_open,
    make_artist_headers,
    read_application,
    read_artist,
    read_discipline,
    set_clock,
    validate_error,
    validate_success,
)


class TestResidencyAnniversaryBoundary:
    """Whole calendar months with an anniversary rule, not a division by thirty."""

    def _two_neighbours(self):
        ctx = cyclemain_cycle_open()
        artist_b = register_artist(
            "Bea Ostrom",
            "bea.ostrom@example.org",
            "2024-10-15",
            "NORTH",
            residency_county="Lakeshore",
        )
        application_b = build_application(
            ctx.cyc,
            ctx.disc,
            artist_b,
            make_artist_headers(artist_b),
            statement="Linked stories set along one dredged channel.",
            narrative="Two years of residency, one chapbook, steady journal placement.",
            page_counts=(10, 10),
        )
        artist_c = register_artist(
            "Cyril Adeyemi",
            "cyril.adeyemi@example.org",
            "2024-10-16",
            "SOUTH",
            residency_county="Rivermouth",
        )
        application_c = build_application(
            ctx.cyc,
            ctx.disc,
            artist_c,
            make_artist_headers(artist_c),
            statement="A verse sequence about ferry timetables.",
            narrative="Recent arrival to the state, previously published abroad.",
            page_counts=(9, 9),
        )
        set_clock("2026-10-16T00:00:00Z")
        validate_success(api_client.set_cycle_status(ctx.cyc, "CLOSED", PROGRAM_OFFICER))
        return ctx, application_b, application_c

    def test_one_day_of_difference_decides_the_twenty_fourth_month(self):
        """
        Against a 15 October 2026 deadline, a residency beginning on 15 October 2024 freezes
        at 24 months and clears the cycle's minimum, while one beginning a single day later
        freezes at 23 and is refused an eligible determination.

        PRD: "With a deadline of 15 October 2026 and a residency minimum of 24 months, a
        residency beginning on 15 October 2024 measures exactly 24 months and passes, while
        one beginning a single day later measures 23 and fails."

        Design: Difficulty/boundary_precision_check/residency_duration_at_the_exact_month_anniversary_boundary
        """
        _, application_b, application_c = self._two_neighbours()

        assert read_application(application_b)["residency_months_at_deadline"] == 24, (
            "the anniversary date should count its month, got "
            f"{read_application(application_b)['residency_months_at_deadline']}"
        )
        assert read_application(application_c)["residency_months_at_deadline"] == 23, (
            "one day short of the anniversary should lose the month, got "
            f"{read_application(application_c)['residency_months_at_deadline']}"
        )

        eligible = validate_success(
            api_client.determine_eligibility(
                application_b, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            )
        )
        assert eligible["status"] == "ELIGIBLE", (
            f"the 24-month applicant should be found eligible, got {eligible['status']}"
        )
        assert eligible["eligibility_determined_by"] == PROGRAM_OFFICER_ID, (
            "the determining officer should be recorded, got "
            f"{eligible['eligibility_determined_by']}"
        )

        validate_error(
            api_client.determine_eligibility(
                application_c, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            ),
            "ERR_ELIGIBILITY_CRITERIA_NOT_MET",
        )
        assert read_application(application_c)["status"] == "SUBMITTED", (
            "a refused determination leaves the application awaiting one"
        )

    def test_the_negative_determination_must_name_a_criterion_that_actually_fails(self):
        """
        The 23-month applicant is not an enrolled student, so citing that ground is refused;
        citing the residency duration succeeds, and only the eligible neighbour is counted
        on the discipline.

        PRD: "An officer who cites a criterion the applicant in fact satisfies is rejected
        with `ERR_INELIGIBILITY_REASON_UNSUPPORTED`."

        Design: Difficulty/boundary_precision_check/residency_duration_at_the_exact_month_anniversary_boundary
        """
        ctx, application_b, application_c = self._two_neighbours()
        validate_success(
            api_client.determine_eligibility(
                application_b, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            )
        )

        validate_error(
            api_client.determine_eligibility(
                application_c,
                {
                    "determination": "INELIGIBLE",
                    "ineligibility_reason_code": "ENROLLED_STUDENT",
                },
                PROGRAM_OFFICER,
            ),
            "ERR_INELIGIBILITY_REASON_UNSUPPORTED",
        )

        ineligible = validate_success(
            api_client.determine_eligibility(
                application_c,
                {
                    "determination": "INELIGIBLE",
                    "ineligibility_reason_code": "RESIDENCY_DURATION",
                },
                PROGRAM_OFFICER,
            )
        )
        assert ineligible["status"] == "INELIGIBLE", (
            f"the supported ground should be accepted, got {ineligible['status']}"
        )
        assert ineligible["ineligibility_reason_code"] == "RESIDENCY_DURATION", (
            f"the ground should be recorded, got {ineligible['ineligibility_reason_code']}"
        )

        assert read_discipline(ctx.disc)["eligible_application_count"] == 1, (
            "only the eligible determination should be counted, got "
            f"{read_discipline(ctx.disc)['eligible_application_count']}"
        )


class TestSubmissionRejectionLadder:
    """One unchanged request walks three priority bands as the calendar moves."""

    def _second_draft(self, ctx):
        return build_application(
            ctx.cyc,
            ctx.disc,
            ctx.art1,
            ctx.art1_headers,
            statement="A second, revised statement filed in the same cycle.",
            narrative="Same career narrative, resubmitted with a different sample set.",
            page_counts=(14, 8),
            submit=False,
        )

    def test_the_duplicate_gives_way_to_the_deadline_once_the_window_shuts(self):
        """
        A second live application from the same artist is refused as a duplicate while the
        window is open, and the identical request is refused on the deadline once the clock
        passes it.

        PRD: "Note the ordering that follows from §2.10: a second submission attempted
        after the deadline reports the deadline error, not the duplicate error."

        Design: Difficulty/priority_pair_validation_conflict/cycle_state_p70_outranks_deadline_p80_which_outranks_duplicate_p85
        """
        ctx = cyclemain_application_submitted()
        second = self._second_draft(ctx)

        validate_error(
            api_client.submit_application(second, ctx.art1_headers),
            "ERR_DUPLICATE_APPLICATION",
        )

        set_clock("2026-10-16T00:00:00Z")
        validate_error(
            api_client.submit_application(second, ctx.art1_headers),
            "ERR_APPLICATION_DEADLINE_PASSED",
        )

    def test_a_closed_cycle_outranks_both_and_no_rejection_consumes_an_alias(self):
        """
        Closing the cycle makes the same request report the cycle's own state, and after all
        three rejections the draft is untouched and the discipline's alias counter still
        stands at the single successful submission.

        PRD: "The discipline's `submitted_sequence_counter` is incremented by one and the
        `sealed_alias` is then minted from that new value as the discipline's
        `alias_prefix`, a hyphen, the cycle's `fiscal_year`, a hyphen, and the counter
        written as four digits with leading zeros — the first literary-arts submission of
        fiscal year 2027 in a discipline whose prefix is LIT therefore receives the alias
        LIT-2027-0001."

        Design: Difficulty/priority_pair_validation_conflict/cycle_state_p70_outranks_deadline_p80_which_outranks_duplicate_p85
        """
        ctx = cyclemain_application_submitted()
        second = self._second_draft(ctx)
        validate_error(
            api_client.submit_application(second, ctx.art1_headers),
            "ERR_DUPLICATE_APPLICATION",
        )
        set_clock("2026-10-16T00:00:00Z")
        validate_error(
            api_client.submit_application(second, ctx.art1_headers),
            "ERR_APPLICATION_DEADLINE_PASSED",
        )

        validate_success(api_client.set_cycle_status(ctx.cyc, "CLOSED", PROGRAM_OFFICER))
        validate_error(
            api_client.submit_application(second, ctx.art1_headers),
            "ERR_CYCLE_STATE_INVALID",
        )

        assert_unsubmitted_draft(read_application(second))
        assert read_discipline(ctx.disc)["submitted_sequence_counter"] == 1, (
            "no rejected submission may consume an alias number, got "
            f"{read_discipline(ctx.disc)['submitted_sequence_counter']}"
        )
        assert read_application(ctx.app1)["sealed_alias"] == "LIT-2027-0001", (
            "the one successful submission holds the first alias, got "
            f"{read_application(ctx.app1)['sealed_alias']}"
        )


class TestStandingGateLivesOnTheArtist:
    """The blocking state sits on the applicant, not on the application."""

    def test_debarring_the_applicant_blocks_a_perfectly_complete_draft(self):
        """
        Two complete drafts differ only in their applicant's standing: debarring the first
        artist refuses their submission outright while the second artist's equivalent
        submission is accepted.

        PRD: "The artist's `standing` must be `GOOD_STANDING`, otherwise
        `ERR_ARTIST_NOT_IN_GOOD_STANDING`."

        Design: Difficulty/cross_entity_state_dependency/application_submit_gated_on_artist_standing_not_application_state
        """
        ctx = cyclemain_application_draft()
        add_second_application(ctx, submit=False)

        debarred = validate_success(
            api_client.debar_artist(ctx.art1, "FUNDS_MISUSE", PROGRAM_OFFICER)
        )
        assert debarred["standing"] == "DEBARRED", (
            f"the artist should be debarred, got {debarred['standing']}"
        )
        assert debarred["debar_reason_code"] == "FUNDS_MISUSE", (
            f"the reason should be recorded, got {debarred['debar_reason_code']}"
        )

        validate_error(
            api_client.submit_application(ctx.app1, ctx.art1_headers),
            "ERR_ARTIST_NOT_IN_GOOD_STANDING",
        )
        assert_unsubmitted_draft(read_application(ctx.app1))

        submitted = validate_success(
            api_client.submit_application(ctx.app2, ctx.art2_headers)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the untouched applicant should submit normally, got {submitted['status']}"
        )

    def test_the_rejected_submission_leaves_the_first_alias_to_the_second_artist(self):
        """
        Because the alias counter advances only on a successful submission, the second
        artist's application takes LIT-2027-0001 despite having been created second, and the
        discipline's counter records exactly one submission.

        PRD: "A successful submission does five things."

        Design: Difficulty/cross_entity_state_dependency/application_submit_gated_on_artist_standing_not_application_state
        """
        ctx = cyclemain_application_draft()
        add_second_application(ctx, submit=False)
        validate_success(api_client.debar_artist(ctx.art1, "FUNDS_MISUSE", PROGRAM_OFFICER))
        validate_error(
            api_client.submit_application(ctx.app1, ctx.art1_headers),
            "ERR_ARTIST_NOT_IN_GOOD_STANDING",
        )
        validate_success(api_client.submit_application(ctx.app2, ctx.art2_headers))

        assert read_application(ctx.app2)["sealed_alias"] == "LIT-2027-0001", (
            "the first successful submission takes the first alias, got "
            f"{read_application(ctx.app2)['sealed_alias']}"
        )
        assert read_application(ctx.app1)["sealed_alias"] is None, (
            "the refused draft holds no alias"
        )
        assert read_discipline(ctx.disc)["submitted_sequence_counter"] == 1, (
            "the counter should record exactly one submission, got "
            f"{read_discipline(ctx.disc)['submitted_sequence_counter']}"
        )
        assert read_artist(ctx.art1)["standing"] == "DEBARRED", (
            "the debarred artist's standing is unchanged by the refusal"
        )
