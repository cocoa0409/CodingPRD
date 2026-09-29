"""
Declared transitions, their preconditions, their cascades and the state errors that
guard everything absent from the tables.
"""

from conftest import build_application, create_panel, nominate, register_artist, seat

from test_helpers import (
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    PROGRAM_OFFICER_ID,
    ACCEPT_AGREEMENT_VERSION,
    api_client,
    assert_cents,
    assert_cycle_ledger,
    assert_score,
    cornermain_application_draft,
    cornermain_application_submitted,
    cornermain_cycle_closed,
    cornermain_cycle_draft,
    cornermain_cycle_panel_review,
    cornermain_installment_one_paid,
    cornermain_panel_chartered,
    cornermain_round_open,
    cornermain_slot_approved,
    cycle_payload,
    discipline_payload,
    make_artist_headers,
    read_application,
    read_award,
    read_artist,
    read_cycle,
    read_discipline,
    read_panel,
    review_payload,
    set_clock,
    validate_error,
    validate_success,
    REVIEW_SCORES_660,
    REVIEW_SCORES_730,
    REVIEW_SCORES_800,
)
from test_helpers.fixtures import _draft_and_submit_review


class TestCycleStatusLadder:
    """Each rung recomputes the ledger and refuses a half-applied transition."""

    def test_opening_a_cycle_recomputes_the_reserve_and_bumps_only_the_cycle(self):
        """
        Opening a 6,000,000-cent cycle that carries one 2,000,000-cent discipline leaves the
        contingency reserve in place at 300,000, availability at 5,700,000 and the posture
        OPEN, and the status change is the only mutation the cycle row has seen since
        creation.

        PRD: "`DRAFT → OPEN` requires at least one discipline category to exist, failing which
        the request is rejected with `ERR_CYCLE_HAS_NO_DISCIPLINES`, and requires that the sum
        of the categories' `allocation_cents` be at most `total_budget_cents` less
        `reserve_cents`, failing which it is rejected with `ERR_ALLOCATION_EXCEEDS_BUDGET`; on
        success the reserve, availability and posture are recomputed."

        Design: Corner/state_machines/cycle_open_transition_recomputes_the_reserve_band
        """
        ctx = cornermain_cycle_draft()
        opened = validate_success(
            api_client.set_cycle_status(ctx.cyc, "OPEN", PROGRAM_OFFICER)
        )

        assert opened["status"] == "OPEN", f"the cycle should open, got {opened['status']}"
        assert_cycle_ledger(
            opened,
            funded_total_cents=0,
            admin_assessment_rate=0.0,
            admin_assessment_cents=0,
            reserve_cents=300_000,
            committed_cents=0,
            available_cents=5_700_000,
            posture="OPEN",
        )
        assert opened["version"] == 2, (
            "only the status change has mutated the cycle, got version "
            f"{opened['version']}"
        )
        assert opened["updated_at"] > opened["created_at"], (
            "the transition refreshes updated_at"
        )

    def test_opening_without_a_discipline_is_refused_then_accepted_unchanged(self):
        """
        The identical open request fails while the cycle has no discipline category and
        succeeds once one exists, and the failed attempt leaves the cycle in DRAFT at its
        original version.

        PRD: "Any `to_status` that is not declared from the cycle's current status is rejected
        with `ERR_CYCLE_STATE_INVALID`, and the same code is what a child operation receives
        when it requires a cycle status the cycle is not in."

        Design: Corner/state_machines/opening_a_cycle_with_no_discipline_returns_cycle_has_no_disciplines
        """
        set_clock("2026-09-01T00:00:00Z")
        cycle_id = validate_success(
            api_client.create_cycle(cycle_payload(), PROGRAM_OFFICER), expected_status=201
        )["id"]

        validate_error(
            api_client.set_cycle_status(cycle_id, "OPEN", PROGRAM_OFFICER),
            "ERR_CYCLE_HAS_NO_DISCIPLINES",
        )
        refused = read_cycle(cycle_id)
        assert refused["status"] == "DRAFT", (
            f"a refused transition leaves the cycle DRAFT, got {refused['status']}"
        )
        assert refused["version"] == 1, (
            f"nothing was written, so the version stands at 1, got {refused['version']}"
        )

        validate_success(
            api_client.create_discipline(discipline_payload(cycle_id), PROGRAM_OFFICER),
            expected_status=201,
        )
        opened = validate_success(
            api_client.set_cycle_status(cycle_id, "OPEN", PROGRAM_OFFICER)
        )
        assert opened["status"] == "OPEN", (
            f"the same request now succeeds, got {opened['status']}"
        )

    def test_closing_before_the_deadline_is_refused_and_the_clock_decides(self):
        """
        With the clock at 1 September the close is refused because the submission deadline has
        not arrived; moving the clock past 15 October is the only change needed for the same
        call to succeed, and the submitted application is untouched either way.

        PRD: "`OPEN → CLOSED` requires the logical clock to have reached
        `application_deadline_at`, and closing early is rejected with
        `ERR_DEADLINE_NOT_REACHED`; applications still sitting in `DRAFT` are left untouched
        but can no longer be submitted, because the submit window has closed with the cycle."

        Design: Corner/state_machines/closing_a_cycle_before_the_deadline_returns_deadline_not_reached
        """
        ctx = cornermain_application_submitted()

        validate_error(
            api_client.set_cycle_status(ctx.cyc, "CLOSED", PROGRAM_OFFICER),
            "ERR_DEADLINE_NOT_REACHED",
        )
        assert read_cycle(ctx.cyc)["status"] == "OPEN", (
            "a refused close leaves the cycle OPEN"
        )

        set_clock("2026-10-16T00:00:00Z")
        closed = validate_success(
            api_client.set_cycle_status(ctx.cyc, "CLOSED", PROGRAM_OFFICER)
        )
        assert closed["status"] == "CLOSED", (
            f"past the deadline the close succeeds, got {closed['status']}"
        )

        application = read_application(ctx.app)
        assert application["status"] == "SUBMITTED", (
            f"closing does not move a submitted application, got {application['status']}"
        )
        assert application["sealed_alias"] == "LIT-2027-0001", (
            f"the alias is untouched by the close, got {application['sealed_alias']}"
        )

    def test_panel_review_waits_for_every_submission_to_be_determined(self):
        """
        A closed cycle still holding an undetermined submission refuses to advance to panel
        review; the determination itself is what finally counts the application on the
        discipline, after which the same call succeeds.

        PRD: "`CLOSED → PANEL_REVIEW` requires that no application of the cycle remain in
        `SUBMITTED` — every submitted application must carry an eligibility determination —
        and a violation is rejected with `ERR_APPLICATION_STATE_INVALID`; the posture is
        recomputed."

        Design: Corner/state_machines/panel_review_requires_every_submission_to_carry_a_determination
        """
        ctx = cornermain_cycle_closed()

        validate_error(
            api_client.set_cycle_status(ctx.cyc, "PANEL_REVIEW", PROGRAM_OFFICER),
            "ERR_APPLICATION_STATE_INVALID",
        )
        assert read_cycle(ctx.cyc)["status"] == "CLOSED", (
            "the refused advance leaves the cycle CLOSED"
        )

        determined = validate_success(
            api_client.determine_eligibility(
                ctx.app, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            )
        )
        assert determined["status"] == "ELIGIBLE", (
            f"the determination should land, got {determined['status']}"
        )
        assert determined["eligibility_determined_by"] == PROGRAM_OFFICER_ID, (
            f"the officer is stamped, got {determined['eligibility_determined_by']}"
        )
        assert determined["notified_at"] is None, (
            "an eligible determination notifies nobody, got "
            f"{determined['notified_at']}"
        )
        assert read_discipline(ctx.disc)["eligible_application_count"] == 1, (
            "the determination is what counts the application, got "
            f"{read_discipline(ctx.disc)['eligible_application_count']}"
        )

        advanced = validate_success(
            api_client.set_cycle_status(ctx.cyc, "PANEL_REVIEW", PROGRAM_OFFICER)
        )
        assert advanced["status"] == "PANEL_REVIEW", (
            f"the same request now succeeds, got {advanced['status']}"
        )

    def test_cancelling_an_open_cycle_sweeps_drafts_and_submissions_alike(self):
        """
        Cancelling an open cycle withdraws both the submitted and the still-draft application,
        rejects the pending work samples of the submitted one, freezes the posture and releases
        the contingency reserve while nothing was ever committed or funded.

        PRD: "From `OPEN`, `OPEN → CANCELLED` first sweeps every application of the cycle in
        `DRAFT` or `SUBMITTED` to `WITHDRAWN`, in application `created_at` ascending order, and
        then forces the posture to `FROZEN`."

        PRD: "`reserve_cents` ... equals five percent of `total_budget_cents`, rounded half up
        to a whole cent, while the cycle's `status` is `DRAFT`, `OPEN`, `CLOSED`,
        `PANEL_REVIEW` or `BOARD_REVIEW`, and it becomes 0 once the status reaches `AWARDED`,
        `CLOSED_OUT` or `CANCELLED`."

        Design: Corner/state_machines/cancelling_an_open_cycle_withdraws_draft_and_submitted_applications
        """
        ctx = cornermain_application_submitted()
        other_artist = register_artist(
            "Jun Park",
            "jun.park@example.org",
            "2020-02-02",
            "CENTRAL",
            residency_county="Harbor",
        )
        other_application = build_application(
            ctx.cyc,
            ctx.disc,
            other_artist,
            make_artist_headers(other_artist),
            statement="An unfinished novel in letters.",
            narrative="Nine years of literary translation and one anthology.",
            page_counts=(9, 7),
            submit=False,
        )

        cancelled = validate_success(
            api_client.set_cycle_status(ctx.cyc, "CANCELLED", PROGRAM_OFFICER)
        )
        assert cancelled["status"] == "CANCELLED", (
            f"the cycle should cancel, got {cancelled['status']}"
        )
        assert cancelled["posture"] == "FROZEN", (
            f"cancellation freezes the posture, got {cancelled['posture']}"
        )
        assert_cents(cancelled["reserve_cents"], 0, "cycle.reserve_cents")
        assert_cents(cancelled["committed_cents"], 0, "cycle.committed_cents")
        assert_cents(cancelled["funded_total_cents"], 0, "cycle.funded_total_cents")

        for application_id in (ctx.app, other_application):
            assert read_application(application_id)["status"] == "WITHDRAWN", (
                f"application {application_id} should be swept to WITHDRAWN"
            )
        sample = validate_success(api_client.get_work_sample(ctx.ws2, PROGRAM_OFFICER))
        assert sample["status"] == "REJECTED", (
            f"a pending sample is rejected by the withdrawal, got {sample['status']}"
        )


class TestPanelLifecycle:
    """Panels arrive fully derived and charter exactly once."""

    def test_a_new_panel_is_forming_with_its_quorum_already_known(self):
        """
        A brand-new three-seat panel reports no seats, no coverage, no readiness and no
        quorum, yet its quorum floor already reads three because that figure depends only on
        the required seats.

        PRD: "It is the larger of 3 and sixty percent of `required_seats` rounded up to a
        whole number — a five-seat panel therefore needs 3, a six-seat panel needs 4, and an
        eight-seat panel needs 5."

        Design: Corner/state_machines/newly_created_panel_starts_forming_with_zero_derived_counters
        """
        ctx = cornermain_cycle_panel_review()
        panel = validate_success(
            api_client.create_panel(
                {
                    "cycle_id": ctx.cyc,
                    "discipline_category_id": ctx.disc,
                    "required_seats": 3,
                    "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
                    "deliberation_window_start": "2026-11-01T00:00:00Z",
                    "deliberation_window_end": "2026-12-01T00:00:00Z",
                },
                PROGRAM_OFFICER,
            ),
            expected_status=201,
        )

        assert panel["status"] == "FORMING", (
            f"a panel is born FORMING, got {panel['status']}"
        )
        assert panel["round_number"] == 0, f"no round yet, got {panel['round_number']}"
        assert panel["seated_count"] == 0, f"no seats yet, got {panel['seated_count']}"
        assert panel["region_coverage_count"] == 0, (
            f"no coverage yet, got {panel['region_coverage_count']}"
        )
        assert_score(panel["readiness_score"], 0.00, "panel.readiness_score")
        assert panel["quorum_met"] is False, "an empty panel has met no quorum"
        assert panel["quorum_min_reviews"] == 3, (
            "the quorum floor does not wait for a seat, got "
            f"{panel['quorum_min_reviews']}"
        )
        assert panel["blocking_conflict_count"] == 0, "no conflict yet"
        assert panel["reopen_required"] is False, "no round has closed"
        assert panel["assigned_application_count"] == 0, "nothing is assigned yet"
        assert panel["chartered_by"] is None, "nobody has chartered it"
        assert panel["slate_submitted_at"] is None, "no slate has been transmitted"

    def test_chartering_sweeps_only_the_eligible_unassigned_applications(self):
        """
        A fully seated panel charters at perfect readiness and claims the one eligible
        application of its discipline, while a never-submitted draft application in the same
        discipline is left where it is.

        PRD: "A successful charter moves the panel `FORMING → CHARTERED`, stamps
        `chartered_by` with the acting officer's `X-User-ID`, and then sweeps the cycle in
        application `created_at` ascending order: every application of the cycle whose
        `discipline_category_id` matches the panel's, whose `status` is `ELIGIBLE`, whose
        `assigned_panel_id` is `null` and whose `anonymity_status` is `SEALED` or `REDACTED`
        moves `ELIGIBLE → UNDER_REVIEW` with `assigned_panel_id` set to this panel."

        Design: Corner/state_machines/charter_assigns_only_eligible_unassigned_applications_of_the_discipline
        """
        ctx = cornermain_application_submitted()
        other_artist = register_artist(
            "Jun Park",
            "jun.park@example.org",
            "2020-02-02",
            "CENTRAL",
            residency_county="Harbor",
        )
        draft_application = build_application(
            ctx.cyc,
            ctx.disc,
            other_artist,
            make_artist_headers(other_artist),
            statement="An unfinished novel in letters.",
            narrative="Nine years of literary translation and one anthology.",
            page_counts=(9, 7),
            submit=False,
        )
        set_clock("2026-10-16T00:00:00Z")
        validate_success(api_client.set_cycle_status(ctx.cyc, "CLOSED", PROGRAM_OFFICER))
        validate_success(
            api_client.determine_eligibility(
                ctx.app, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            )
        )
        validate_success(
            api_client.set_cycle_status(ctx.cyc, "PANEL_REVIEW", PROGRAM_OFFICER)
        )
        panel_id = create_panel(ctx.cyc, ctx.disc, required_seats=3)
        seat(nominate(panel_id, "chair.north@example.org", "Kira Vale", "NORTH", is_chair=True))
        seat(nominate(panel_id, "reader.central@example.org", "Lev Ostrom", "CENTRAL"))
        seat(nominate(panel_id, "reader.south@example.org", "Mira Sol", "SOUTH"))

        chartered = validate_success(api_client.charter_panel(panel_id, PROGRAM_OFFICER))
        assert chartered["status"] == "CHARTERED", (
            f"a ready panel charters, got {chartered['status']}"
        )
        assert chartered["seated_count"] == 3, f"three seats, got {chartered['seated_count']}"
        assert chartered["region_coverage_count"] == 3, (
            f"all three regions covered, got {chartered['region_coverage_count']}"
        )
        assert_score(chartered["readiness_score"], 100.00, "panel.readiness_score")
        assert chartered["quorum_met"] is True, "three seats meet the quorum floor of three"
        assert chartered["chartered_by"] == PROGRAM_OFFICER_ID, (
            f"the chartering officer is stamped, got {chartered['chartered_by']}"
        )
        assert chartered["assigned_application_count"] == 1, (
            "only the eligible application is claimed, got "
            f"{chartered['assigned_application_count']}"
        )

        claimed = read_application(ctx.app)
        assert claimed["status"] == "UNDER_REVIEW", (
            f"the eligible application moves to UNDER_REVIEW, got {claimed['status']}"
        )
        assert claimed["assigned_panel_id"] == panel_id, (
            f"it is attached to this panel, got {claimed['assigned_panel_id']}"
        )
        untouched = read_application(draft_application)
        assert untouched["status"] == "DRAFT", (
            f"the draft is not swept, got {untouched['status']}"
        )
        assert untouched["assigned_panel_id"] is None, (
            "no panel may claim a draft application"
        )


class TestReviewRoundMechanics:
    """One submit writes three rows; the close waits for quorum."""

    def test_submitting_one_review_stamps_the_author_and_the_application(self):
        """
        A drafted review carries no score until it is submitted; the submit stamps the
        instant, writes the weighted score, counts the author's submission and gives the
        application a provisional composite from that single counted review.

        PRD: "Submission stamps `submitted_at` from the logical clock, computes
        `weighted_score`, increments the author's `review_submitted_count` by one, and
        recomputes the application's `valid_review_count` and `provisional_composite_score`."

        Design: Corner/state_machines/review_submission_side_effects_land_on_three_rows_at_once
        """
        ctx = cornermain_round_open()

        drafted = validate_success(
            api_client.create_review(
                review_payload(
                    ctx.app,
                    ctx.pl1,
                    artistic_excellence=9,
                    work_sample_quality=8,
                    career_impact=7,
                    public_value=6,
                    comments="Assured voice, uneven middle section.",
                ),
                ctx.pl1_headers,
            ),
            expected_status=201,
        )
        assert drafted["status"] == "DRAFT", (
            f"a new review is a draft, got {drafted['status']}"
        )
        assert drafted["round_number"] == 1, (
            f"the draft takes the panel's round, got {drafted['round_number']}"
        )
        assert drafted["weighted_score"] is None, "no score before submission"
        assert drafted["submitted_at"] is None, "no timestamp before submission"

        submitted = validate_success(
            api_client.submit_review(drafted["id"], ctx.pl1_headers)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the review should be submitted, got {submitted['status']}"
        )
        assert_score(submitted["weighted_score"], 8.00, "review.weighted_score")
        assert str(submitted["submitted_at"]).startswith("2026-10-16"), (
            f"submitted_at comes from the logical clock, got {submitted['submitted_at']}"
        )

        assert read_panel(ctx.pan)["round_number"] == 1, "the panel is in its first round"
        application = read_application(ctx.app)
        assert application["valid_review_count"] == 1, (
            f"one counted review, got {application['valid_review_count']}"
        )
        assert_score(
            application["provisional_composite_score"],
            8.00,
            "application.provisional_composite_score",
        )
        assert application["final_composite_score"] is None, (
            "the final composite waits for close-round"
        )
        assert application["score_spread"] is None, "the spread waits for close-round"

        author = validate_success(api_client.get_panelist(ctx.pl1, PROGRAM_OFFICER))
        assert author["review_submitted_count"] == 1, (
            f"the author's counter advances, got {author['review_submitted_count']}"
        )
        assert author["status"] == "SEATED", (
            f"submitting does not change the seat, got {author['status']}"
        )

    def test_the_round_cannot_close_two_reviews_short_of_quorum(self):
        """
        With two of the three required reviews the close is refused and the application keeps
        only a provisional score; the third review makes the identical call succeed and writes
        the final composite and the spread.

        PRD: "It requires the cycle to be in `PANEL_REVIEW`, otherwise
        `ERR_CYCLE_STATE_INVALID`, and requires every application assigned to the panel and
        still `UNDER_REVIEW` to have a `valid_review_count` of at least the panel's
        `quorum_min_reviews`; a shortfall on any one of them is rejected with
        `ERR_INSUFFICIENT_REVIEWS`, and reviews that are `DRAFT`, `INVALIDATED` or
        `SUPERSEDED` do not count towards it."

        Design: Corner/state_machines/close_round_without_quorum_returns_insufficient_reviews
        """
        ctx = cornermain_round_open()
        _draft_and_submit_review(
            ctx.app, ctx.pl1, REVIEW_SCORES_800, "Assured voice, uneven middle section."
        )
        _draft_and_submit_review(
            ctx.app, ctx.pl2, REVIEW_SCORES_660, "Competent but conventional."
        )

        validate_error(
            api_client.close_round(ctx.pan, PROGRAM_OFFICER), "ERR_INSUFFICIENT_REVIEWS"
        )
        partial = read_application(ctx.app)
        assert partial["status"] == "UNDER_REVIEW", (
            f"a refused close leaves the application under review, got {partial['status']}"
        )
        assert partial["valid_review_count"] == 2, (
            f"two counted reviews, got {partial['valid_review_count']}"
        )
        assert_score(
            partial["provisional_composite_score"],
            7.30,
            "application.provisional_composite_score",
        )
        assert partial["final_composite_score"] is None, (
            "no final composite is written by a refused close"
        )

        _draft_and_submit_review(
            ctx.app, ctx.pl3, REVIEW_SCORES_730, "Strong career trajectory."
        )
        closed = validate_success(api_client.close_round(ctx.pan, PROGRAM_OFFICER))
        assert closed["status"] == "DELIBERATING", (
            f"the panel moves to deliberation, got {closed['status']}"
        )
        assert closed["reopen_required"] is False, (
            "a spread of 1.40 does not reopen the round"
        )

        scored = read_application(ctx.app)
        assert scored["status"] == "SCORED", (
            f"the application is scored, got {scored['status']}"
        )
        assert_score(scored["final_composite_score"], 7.30, "final_composite_score")
        assert_score(scored["score_spread"], 1.40, "score_spread")
        assert scored["review_round_number"] == 1, (
            f"the closing round is recorded, got {scored['review_round_number']}"
        )


class TestSettledActionsAndTerminalStates:
    """A settled row answers with its own entity's state error."""

    def test_each_repeated_action_names_its_own_entity(self):
        """
        Re-submitting the application, re-seating a panelist, re-screening a work sample,
        re-screening a conflict and re-chartering the panel each report their own entity's
        state error rather than a shared code or a silent success.

        PRD: "Each stamps `screened_by` with the acting officer's `X-User-ID`, and a sample
        may only be screened once — a second attempt, or a redaction of a sample that is not
        `FLAGGED`, is rejected with `ERR_WORK_SAMPLE_STATE_INVALID`."

        PRD: "Seating the same panelist twice, or acting on one who has already resigned, is
        rejected with `ERR_PANELIST_STATE_INVALID`."

        Design: Corner/state_machines/repeated_settled_actions_each_report_their_own_entity_state_error
        """
        ctx = cornermain_panel_chartered()

        validate_error(
            api_client.submit_application(ctx.app, ctx.art_headers),
            "ERR_APPLICATION_STATE_INVALID",
        )
        validate_error(
            api_client.seat_panelist(ctx.pl1, PROGRAM_OFFICER),
            "ERR_PANELIST_STATE_INVALID",
        )

        screened = validate_success(
            api_client.screen_work_sample(ctx.ws1, "CLEARED", PROGRAM_OFFICER)
        )
        assert screened["status"] == "CLEARED", (
            f"the first screening clears the sample, got {screened['status']}"
        )
        assert screened["screened_by"] == PROGRAM_OFFICER_ID, (
            f"the officer is stamped, got {screened['screened_by']}"
        )
        validate_error(
            api_client.screen_work_sample(ctx.ws1, "CLEARED", PROGRAM_OFFICER),
            "ERR_WORK_SAMPLE_STATE_INVALID",
        )

        conflict = validate_success(
            api_client.create_conflict(
                {
                    "panelist_id": ctx.pl2,
                    "application_id": ctx.app,
                    "relationship_type": "CO_AUTHOR",
                    "disclosure_note": "We co-edited an anthology in 2019.",
                },
                ctx.pl2_headers,
            ),
            expected_status=201,
        )
        assert conflict["severity"] == "DISCRETIONARY", (
            f"a co-authorship is discretionary, got {conflict['severity']}"
        )
        waiver = {
            "disposition": "WAIVED",
            "override_justification": (
                "Single anthology credit six years ago; no ongoing professional relationship."
            ),
        }
        waived = validate_success(
            api_client.screen_conflict(conflict["id"], waiver, PROGRAM_OFFICER)
        )
        assert waived["status"] == "WAIVED", (
            f"the first screening waives it, got {waived['status']}"
        )
        validate_error(
            api_client.screen_conflict(conflict["id"], waiver, PROGRAM_OFFICER),
            "ERR_CONFLICT_STATE_INVALID",
        )

        validate_error(
            api_client.charter_panel(ctx.pan, PROGRAM_OFFICER), "ERR_PANEL_STATE_INVALID"
        )
        assert read_panel(ctx.pan)["assigned_application_count"] == 1, (
            "no second assignment pass may run, got "
            f"{read_panel(ctx.pan)['assigned_application_count']}"
        )

    def test_a_withdrawn_application_refuses_every_later_action(self):
        """
        Withdrawing a draft rejects its pending samples and zeroes the derived count, after
        which both a submit and a second withdrawal are refused and the row keeps neither an
        alias nor a submission timestamp.

        PRD: "Withdrawing from `DRAFT` or `SUBMITTED` rejects every work sample of the
        application still in `PENDING_SCREEN` or `FLAGGED`, moving them to `REJECTED`;
        withdrawing from `SUBMITTED` additionally recomputes the cycle's
        `unresolved_breach_count` and `posture`; and withdrawing from `ELIGIBLE` decrements the
        discipline's `eligible_application_count` by one."

        Design: Corner/state_machines/withdrawn_application_is_terminal_and_rejects_every_later_action
        """
        ctx = cornermain_application_draft()

        withdrawn = validate_success(
            api_client.withdraw_application(ctx.app, ctx.art_headers)
        )
        assert withdrawn["status"] == "WITHDRAWN", (
            f"the application should withdraw, got {withdrawn['status']}"
        )
        assert withdrawn["work_sample_count"] == 0, (
            f"every sample was rejected, got {withdrawn['work_sample_count']}"
        )
        sample = validate_success(api_client.get_work_sample(ctx.ws1, PROGRAM_OFFICER))
        assert sample["status"] == "REJECTED", (
            f"the pending sample is rejected, got {sample['status']}"
        )

        validate_error(
            api_client.submit_application(ctx.app, ctx.art_headers),
            "ERR_APPLICATION_STATE_INVALID",
        )
        validate_error(
            api_client.withdraw_application(ctx.app, ctx.art_headers),
            "ERR_APPLICATION_STATE_INVALID",
        )

        final = read_application(ctx.app)
        assert final["status"] == "WITHDRAWN", (
            f"withdrawal is terminal, got {final['status']}"
        )
        assert final["sealed_alias"] is None, "no alias may be minted after withdrawal"
        assert final["submitted_at"] is None, "no submission timestamp may be written"

    def test_undeclared_triggers_are_refused_by_the_entity_in_the_path(self):
        """
        An open cycle asked to jump straight to awarded, a forming panel asked to close a
        round and a draft application asked for an eligibility determination each report the
        state of the entity named in the path — the last of them ahead of the cycle-state rule
        it also violates.

        PRD: "**Target-entity state** — the entity named in the path is in a state from which
        the requested transition is declared (the entity-specific `..._STATE_INVALID` code)."

        Design: Corner/state_machines/triggers_absent_from_the_transition_table_are_rejected_per_entity
        """
        ctx = cornermain_application_draft()
        panel_id = create_panel(ctx.cyc, ctx.disc, required_seats=3)

        validate_error(
            api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER),
            "ERR_CYCLE_STATE_INVALID",
        )
        validate_error(
            api_client.close_round(panel_id, PROGRAM_OFFICER), "ERR_PANEL_STATE_INVALID"
        )
        validate_error(
            api_client.determine_eligibility(
                ctx.app, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            ),
            "ERR_APPLICATION_STATE_INVALID",
        )

        assert read_cycle(ctx.cyc)["status"] == "OPEN", "the cycle is unmoved"
        assert read_panel(panel_id)["status"] == "FORMING", "the panel is unmoved"
        assert read_application(ctx.app)["status"] == "DRAFT", "the application is unmoved"


class TestClockAndStandingCascades:
    """The checkpoint and debarment each touch only what they should."""

    def test_the_clock_forfeits_an_unaccepted_offer_and_unwinds_four_rows(self):
        """
        One clock advance past the acceptance deadline reports the award as forfeited and
        unwinds the award, the application, the slot and the cycle ledger; the late acceptance
        then names the lapsed deadline rather than the award's state.

        PRD: "First, an award still in `OFFERED` whose `acceptance_deadline_at` now lies in
        the past becomes `FORFEITED`: its application becomes `NOT_AWARDED`, its recommendation
        slot becomes `VOIDED`, the artist's `active_award_count` is decremented, and the owning
        cycle's `funded_total_cents`, `admin_assessment_rate`, `admin_assessment_cents`,
        `committed_cents`, `available_cents` and `posture` are all recomputed — the same fiscal
        unwinding a voluntary decline performs, so forfeiture and decline are exactly
        compensating."

        Design: Corner/state_machines/clock_advance_past_the_acceptance_window_forfeits_the_unaccepted_offer
        """
        ctx = cornermain_slot_approved()

        checkpoint = set_clock("2026-11-01T00:00:00Z")
        assert ctx.aw in checkpoint["forfeited_award_ids"], (
            "the lapsed offer should be reported as forfeited, got "
            f"{checkpoint['forfeited_award_ids']}"
        )
        assert str(checkpoint["current_utc"]).startswith("2026-11-01"), (
            f"the clock should report its new instant, got {checkpoint['current_utc']}"
        )

        award = read_award(ctx.aw)
        assert award["status"] == "FORFEITED", (
            f"the award should be forfeited, got {award['status']}"
        )
        assert str(award["acceptance_deadline_at"]).startswith("2026-10-30"), (
            "the deadline was fourteen days after approval, got "
            f"{award['acceptance_deadline_at']}"
        )

        application = read_application(ctx.app)
        assert application["status"] == "NOT_AWARDED", (
            f"the application should be released, got {application['status']}"
        )
        assert str(application["notified_at"]).startswith("2026-11-01"), (
            f"notified_at is re-stamped, got {application['notified_at']}"
        )

        slot = validate_success(api_client.get_slot(ctx.slot, PROGRAM_OFFICER))
        assert slot["status"] == "VOIDED", f"the slot should void, got {slot['status']}"
        assert_cents(slot["awarded_amount_cents"], 0, "slot.awarded_amount_cents")

        assert_cycle_ledger(
            read_cycle(ctx.cyc),
            funded_total_cents=0,
            admin_assessment_rate=0.0,
            admin_assessment_cents=0,
            reserve_cents=300_000,
            committed_cents=0,
            available_cents=5_700_000,
            posture="OPEN",
        )
        artist = read_artist(ctx.art)
        assert artist["active_award_count"] == 0, (
            f"the active count is decremented, got {artist['active_award_count']}"
        )
        assert artist["prior_award_count"] == 0, (
            f"a forfeited offer is no award history, got {artist['prior_award_count']}"
        )

        validate_error(
            api_client.accept_award(
                ctx.aw,
                {
                    "accept_agreement_version": ACCEPT_AGREEMENT_VERSION,
                    "tax_certification_signed": True,
                },
                ctx.art_headers,
            ),
            "ERR_ACCEPTANCE_DEADLINE_PASSED",
        )

    def test_debarment_holds_the_scheduled_rows_and_spares_the_paid_one(self):
        """
        Debarring an artist whose first installment is already paid holds only the two rows
        still scheduled, leaves the paid row and the award's disbursement figures exactly as
        they were.

        PRD: "Debarment takes a `debar_reason_code`, sets `standing` to `DEBARRED`, and moves
        every `SCHEDULED` installment on every one of that artist's awards to `HELD` with
        `hold_reason_code` set to `ARTIST_DEBARRED`, processing awards in `created_at`
        ascending order and installments within each award in `installment_number` ascending
        order."

        Design: Corner/state_machines/debarment_holds_only_the_still_scheduled_installments
        """
        ctx = cornermain_installment_one_paid()

        debarred = validate_success(
            api_client.debar_artist(ctx.art, "FRAUD", PROGRAM_OFFICER)
        )
        assert debarred["standing"] == "DEBARRED", (
            f"the artist should be debarred, got {debarred['standing']}"
        )
        assert debarred["debar_reason_code"] == "FRAUD", (
            f"the reason should be recorded, got {debarred['debar_reason_code']}"
        )

        paid = validate_success(api_client.get_installment(ctx.i1, FISCAL_OFFICER))
        assert paid["status"] == "PAID", (
            f"a paid installment is untouched, got {paid['status']}"
        )
        assert paid["hold_reason_code"] is None, "a paid row carries no hold reason"
        assert_cents(paid["gross_cents"], 600_000, "installment 1 gross_cents")
        assert_cents(paid["withholding_cents"], 0, "installment 1 withholding_cents")
        assert_cents(paid["net_cents"], 600_000, "installment 1 net_cents")

        for installment_id, gross in ((ctx.i2, 525_000), (ctx.i3, 375_000)):
            held = validate_success(
                api_client.get_installment(installment_id, FISCAL_OFFICER)
            )
            assert held["status"] == "HELD", (
                f"a scheduled row should be held, got {held['status']}"
            )
            assert held["hold_reason_code"] == "ARTIST_DEBARRED", (
                f"the hold reason should name the debarment, got {held['hold_reason_code']}"
            )
            assert_cents(held["gross_cents"], gross, "installment gross_cents")

        award = read_award(ctx.aw)
        assert award["status"] == "ACTIVE", (
            f"the award stays active, got {award['status']}"
        )
        assert award["payment_status"] == "PARTIALLY_PAID", (
            f"one of three rows is paid, got {award['payment_status']}"
        )
        assert_cents(award["disbursed_gross_cents"], 600_000, "award.disbursed_gross_cents")
        assert_cents(
            award["undisbursed_gross_cents"], 900_000, "award.undisbursed_gross_cents"
        )
