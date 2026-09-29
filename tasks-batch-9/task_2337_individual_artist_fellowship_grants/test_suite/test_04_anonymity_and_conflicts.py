"""
The anonymity dimension, the blocking-conflict cascade and the compensations that
undo it.
"""

from test_helpers import (
    BOARD_MEMBER,
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    PROGRAM_OFFICER_ID,
    api_client,
    assert_cents,
    assert_score,
    conflict_payload,
    cycle_version,
    cyclemain_award_accepted,
    cyclemain_reviews_submitted,
    cyclemain_round_closed,
    cyclemain_round_open,
    cyclemain_slate_submitted,
    list_reviews_of,
    make_panelist_headers,
    read_application,
    read_award,
    read_cycle,
    read_panel,
    set_clock,
    validate_error,
    validate_success,
)
from conftest import create_panel, nominate, seat

BLOCKING_NOTE = "The applicant and I both hold appointments at the lakeshore arts centre."
OVERRIDE_NOTE = (
    "Shared institutional affiliation only; no supervisory or financial relationship, "
    "documented by the programme officer."
)


def _declare_and_block(panelist_id: str, application_id: str) -> str:
    conflict_id = validate_success(
        api_client.create_conflict(
            conflict_payload(
                panelist_id,
                application_id,
                "SAME_INSTITUTION",
                disclosure_note=BLOCKING_NOTE,
            ),
            PROGRAM_OFFICER,
        ),
        expected_status=201,
    )["id"]
    validate_success(
        api_client.screen_conflict(
            conflict_id, {"disposition": "BLOCKING"}, PROGRAM_OFFICER
        )
    )
    return conflict_id


class TestAnonymityIsItsOwnDimension:
    """The review lifecycle and the anonymity lifecycle advance on separate triggers."""

    def test_flagging_a_sample_breaches_anonymity_without_moving_the_review_status(self):
        """
        Flagging one of two work samples drives the anonymity dimension from SEALED to
        BREACHED, invalidates every submitted review and freezes the cycle, while the
        application's own review status stays UNDER_REVIEW and the second sample stays
        unscreened.

        PRD: "`FLAGGED_IDENTIFYING` moves the sample to `FLAGGED` and is the trigger for
        the breach cascade: the application's `anonymity_status` moves from `SEALED` to
        `BREACHED` (or from `REDACTED` back to `BREACHED`, when a later sample on an
        already-repaired application is flagged), every review of that application in
        `SUBMITTED` becomes `INVALIDATED` with `invalidation_reason` set to
        `ANONYMITY_BREACH`, the application's `valid_review_count`,
        `provisional_composite_score` and `score_spread` are recomputed from what remains,
        and the cycle's `unresolved_breach_count` is incremented and its `posture`
        recomputed — which, by the cascade of §2.7, means `FROZEN` for as long as the
        breach stands."

        Design: Difficulty/non_linear_state_machine/application_review_and_anonymity_dimensions_move_independently
        """
        ctx = cyclemain_reviews_submitted()

        flagged = validate_success(
            api_client.screen_work_sample(ctx.ws1a, "FLAGGED_IDENTIFYING", PROGRAM_OFFICER)
        )
        assert flagged["status"] == "FLAGGED", (
            f"the screened sample should move to FLAGGED, got {flagged['status']}"
        )
        untouched = validate_success(api_client.get_work_sample(ctx.ws1b, PROGRAM_OFFICER))
        assert untouched["status"] == "PENDING_SCREEN", (
            "the second sample is not screened by the first screening, got "
            f"{untouched['status']}"
        )

        application = read_application(ctx.app1)
        assert application["anonymity_status"] == "BREACHED", (
            f"anonymity should move SEALED -> BREACHED, got {application['anonymity_status']}"
        )
        assert application["status"] == "UNDER_REVIEW", (
            "the review dimension must not move with the anonymity dimension, got "
            f"{application['status']}"
        )
        assert application["valid_review_count"] == 0, (
            f"every counted review is invalidated, got {application['valid_review_count']}"
        )
        for field in (
            "provisional_composite_score",
            "final_composite_score",
            "score_spread",
        ):
            assert application[field] is None, (
                f"{field} should read null with no counted review left, got {application[field]}"
            )

        reviews = list_reviews_of(ctx.app1)
        assert [row["status"] for row in reviews] == ["INVALIDATED"] * 5, (
            f"all five reviews should be INVALIDATED, got {[r['status'] for r in reviews]}"
        )
        assert {row["invalidation_reason"] for row in reviews} == {"ANONYMITY_BREACH"}, (
            "each invalidation should name the anonymity breach, got "
            f"{[r['invalidation_reason'] for r in reviews]}"
        )

        cycle = read_cycle(ctx.cyc)
        assert cycle["unresolved_breach_count"] == 1, (
            f"the breach should be counted on the cycle, got {cycle['unresolved_breach_count']}"
        )
        assert cycle["posture"] == "FROZEN", (
            f"an unresolved breach freezes the cycle, got {cycle['posture']}"
        )

    def test_redaction_repairs_anonymity_but_never_resurrects_the_reviews(self):
        """
        Redacting the flagged sample returns the anonymity dimension to REDACTED and
        releases the cycle freeze, yet the invalidated reviews stay invalidated, so the
        round can no longer be closed for want of counted reviews.

        PRD: "Reviews invalidated for `ANONYMITY_BREACH` are **not** restored by
        redaction; only a waived conflict restores reviews, as §3.6 describes."

        Design: Difficulty/non_linear_state_machine/application_review_and_anonymity_dimensions_move_independently
        """
        ctx = cyclemain_reviews_submitted()
        validate_success(
            api_client.screen_work_sample(ctx.ws1a, "FLAGGED_IDENTIFYING", PROGRAM_OFFICER)
        )

        redacted = validate_success(
            api_client.redact_work_sample(ctx.ws1a, PROGRAM_OFFICER)
        )
        assert redacted["status"] == "REDACTED", (
            f"the sample should move FLAGGED -> REDACTED, got {redacted['status']}"
        )
        assert redacted["contains_identifying_metadata"] is False, (
            "redaction clears contains_identifying_metadata"
        )

        application = read_application(ctx.app1)
        assert application["anonymity_status"] == "REDACTED", (
            f"anonymity should move BREACHED -> REDACTED, got {application['anonymity_status']}"
        )
        assert application["status"] == "UNDER_REVIEW", (
            f"the review dimension still has not moved, got {application['status']}"
        )

        cycle = read_cycle(ctx.cyc)
        assert cycle["unresolved_breach_count"] == 0, (
            f"the repaired breach is no longer counted, got {cycle['unresolved_breach_count']}"
        )
        assert cycle["posture"] == "OPEN", (
            f"the freeze should be released, got {cycle['posture']}"
        )

        statuses = [row["status"] for row in list_reviews_of(ctx.app1)]
        assert statuses == ["INVALIDATED"] * 5, (
            f"redaction is not a compensation for the reviews, got {statuses}"
        )
        validate_error(
            api_client.close_round(ctx.pan, PROGRAM_OFFICER), "ERR_INSUFFICIENT_REVIEWS"
        )
        panel = read_panel(ctx.pan)
        assert panel["quorum_min_reviews"] == 3, (
            f"the five-seat panel requires three counted reviews, got {panel['quorum_min_reviews']}"
        )


class TestBlockingConflictCascade:
    """One screening propagates through conflict, panelist, review, application, panel,
    slot and cycle."""

    def test_the_screening_recuses_its_author_and_rescores_the_application(self):
        """
        Screening a discretionary conflict as BLOCKING recuses its panelist without
        releasing the seat, invalidates only that panelist's review, and recomputes the
        provisional mean over the four survivors to 7.10 while the final variant written
        at round close stays 7.30.

        PRD: "A `BLOCKING` screening is the widest cascade in the review phase, and every
        one of its six effects is required."

        Design: Difficulty/transitive_cascade/blocking_conflict_cascades_six_levels_to_slot_and_cycle_posture
        """
        ctx = cyclemain_slate_submitted()
        conflict_id = _declare_and_block(ctx.pl1, ctx.app1)

        conflict = validate_success(api_client.get_conflict(conflict_id, PROGRAM_OFFICER))
        assert conflict["status"] == "BLOCKING", (
            f"the declaration should be BLOCKING, got {conflict['status']}"
        )
        assert conflict["severity"] == "DISCRETIONARY", (
            f"SAME_INSTITUTION derives DISCRETIONARY, got {conflict['severity']}"
        )
        assert conflict["screened_by"] == PROGRAM_OFFICER_ID, (
            f"screened_by should name the acting officer, got {conflict['screened_by']}"
        )

        panelist = validate_success(api_client.get_panelist(ctx.pl1, PROGRAM_OFFICER))
        assert panelist["status"] == "RECUSED", (
            f"the panelist should move SEATED -> RECUSED, got {panelist['status']}"
        )
        assert ctx.app1 in panelist["recused_application_ids"], (
            "the conflicted application should be listed on the panelist"
        )
        assert read_panel(ctx.pan)["seated_count"] == 5, (
            "recusal deliberately keeps the seat, so seated_count must stay 5"
        )

        rv1 = validate_success(api_client.get_review(ctx.rv1, PROGRAM_OFFICER))
        assert rv1["status"] == "INVALIDATED", (
            f"the recused author's review should be INVALIDATED, got {rv1['status']}"
        )
        assert rv1["invalidation_reason"] == "BLOCKING_CONFLICT", (
            f"the reason should name the conflict, got {rv1['invalidation_reason']}"
        )
        others = [
            row["status"] for row in list_reviews_of(ctx.app1) if row["id"] != ctx.rv1
        ]
        assert others == ["SUBMITTED"] * 4, (
            f"the other four reviews should be untouched, got {others}"
        )

        application = read_application(ctx.app1)
        assert application["valid_review_count"] == 4, (
            f"four reviews should remain counted, got {application['valid_review_count']}"
        )
        assert_score(
            application["provisional_composite_score"],
            7.10,
            "application.provisional_composite_score",
        )
        assert_score(application["score_spread"], 2.50, "application.score_spread")
        assert_score(
            application["final_composite_score"],
            7.30,
            "application.final_composite_score",
        )
        assert application["status"] == "SCORED", (
            f"the application's own status is untouched, got {application['status']}"
        )

    def test_the_screening_voids_the_slot_and_restricts_the_cycle(self):
        """
        The same screening penalises the panel's readiness to 92.00 with another round
        flagged, voids the proposed recommendation slot, and restricts the cycle's posture
        even though the appropriation is untouched — so the board's approval of that slot
        is refused on slot state rather than on posture.

        PRD: "And every recommendation slot for that application still in `PROPOSED`
        becomes `VOIDED`, with the owning panel's `reopen_required` set to true when that
        panel may still run another round."

        Design: Difficulty/transitive_cascade/blocking_conflict_cascades_six_levels_to_slot_and_cycle_posture
        """
        ctx = cyclemain_slate_submitted()
        _declare_and_block(ctx.pl1, ctx.app1)

        panel = read_panel(ctx.pan)
        assert panel["blocking_conflict_count"] == 1, (
            f"the panel should carry one blocking conflict, got {panel['blocking_conflict_count']}"
        )
        assert_score(panel["readiness_score"], 92.00, "panel.readiness_score")
        assert panel["quorum_met"] is True, (
            "five seats still meet the three-review quorum"
        )
        assert panel["reopen_required"] is True, (
            "voiding a proposed slot flags the owning panel for another round"
        )
        assert panel["status"] == "SLATE_SUBMITTED", (
            f"the panel's own status is untouched, got {panel['status']}"
        )

        slot = validate_success(api_client.get_slot(ctx.slot1, BOARD_MEMBER))
        assert slot["status"] == "VOIDED", (
            f"the proposed slot should be VOIDED, got {slot['status']}"
        )

        cycle = read_cycle(ctx.cyc)
        assert cycle["blocking_conflict_count"] == 1, (
            f"the cycle should count the blocking conflict, got {cycle['blocking_conflict_count']}"
        )
        assert cycle["posture"] == "RESTRICTED", (
            f"a positive blocking count restricts the cycle, got {cycle['posture']}"
        )
        assert_cents(cycle["available_cents"], 5_700_000, "cycle.available_cents")

        validate_error(
            api_client.board_action(
                ctx.slot1,
                {
                    "action": "APPROVE",
                    "expected_cycle_version": cycle_version(ctx.cyc, BOARD_MEMBER),
                },
                BOARD_MEMBER,
            ),
            "ERR_SLOT_STATE_INVALID",
        )


class TestBreachBlocksDisbursement:
    """A frozen posture stops money moving, and redaction lets the same call through."""

    def test_a_breach_after_acceptance_freezes_the_cycle_and_refuses_the_release(self):
        """
        Flagging a work sample after the award has been accepted freezes the cycle,
        invalidates the reviews and leaves the award itself untouched; the cycle still
        reaches AWARDED but the breached application is passed over by the unsealing
        cascade, and the due first installment cannot be released.

        PRD: "Every application of the cycle whose `anonymity_status` is `SEALED` or
        `REDACTED` becomes `UNSEALED`, processed in application `created_at` ascending
        order, which makes `applicant_legal_name` and `applicant_region` visible to the
        `Panelist` role for the first time."

        Design: Difficulty/transitive_cascade/anonymity_breach_freezes_cycle_and_blocks_disbursement_until_redaction
        """
        ctx = cyclemain_award_accepted()
        validate_success(
            api_client.screen_work_sample(ctx.ws1a, "FLAGGED_IDENTIFYING", PROGRAM_OFFICER)
        )

        cycle = read_cycle(ctx.cyc)
        assert cycle["unresolved_breach_count"] == 1, (
            f"the breach should be counted, got {cycle['unresolved_breach_count']}"
        )
        assert cycle["posture"] == "FROZEN", (
            f"the cycle should freeze, got {cycle['posture']}"
        )
        assert cycle["status"] == "BOARD_REVIEW", (
            f"the posture change does not move the status, got {cycle['status']}"
        )

        reviews = list_reviews_of(ctx.app1)
        assert [row["status"] for row in reviews] == ["INVALIDATED"] * 5, (
            f"the reviews should be invalidated, got {[r['status'] for r in reviews]}"
        )
        assert {row["invalidation_reason"] for row in reviews} == {"ANONYMITY_BREACH"}
        assert read_application(ctx.app1)["valid_review_count"] == 0, (
            "no counted review should remain"
        )
        assert_cents(
            read_award(ctx.aw1)["gross_amount_cents"], 1_500_000, "award.gross_amount_cents"
        )

        validate_success(
            api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER)
        )
        assert read_application(ctx.app1)["anonymity_status"] == "BREACHED", (
            "only SEALED and REDACTED applications are unsealed at AWARDED"
        )

        set_clock("2027-01-01T00:00:00Z")
        validate_error(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER),
            "ERR_CYCLE_POSTURE_FROZEN",
        )
        installment = validate_success(
            api_client.get_installment(ctx.inst1, FISCAL_OFFICER)
        )
        assert installment["status"] == "SCHEDULED", (
            f"the refused installment stays SCHEDULED, got {installment['status']}"
        )
        assert installment["released_by"] is None, "released_by must stay null"

    def test_redacting_the_sample_lets_the_identical_release_through(self):
        """
        Redacting the flagged sample clears the freeze and restores availability, after
        which the very same release call succeeds and stamps the acting fiscal officer —
        without paying anything.

        PRD: "**Release** moves an installment `SCHEDULED → RELEASED` and stamps
        `released_by` and `released_at`."

        Design: Difficulty/transitive_cascade/anonymity_breach_freezes_cycle_and_blocks_disbursement_until_redaction
        """
        ctx = cyclemain_award_accepted()
        validate_success(
            api_client.screen_work_sample(ctx.ws1a, "FLAGGED_IDENTIFYING", PROGRAM_OFFICER)
        )
        validate_success(
            api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER)
        )
        set_clock("2027-01-01T00:00:00Z")
        validate_error(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER),
            "ERR_CYCLE_POSTURE_FROZEN",
        )

        validate_success(api_client.redact_work_sample(ctx.ws1a, PROGRAM_OFFICER))
        assert read_application(ctx.app1)["anonymity_status"] == "REDACTED", (
            "the repaired application should read REDACTED"
        )
        cycle = read_cycle(ctx.cyc)
        assert cycle["unresolved_breach_count"] == 0, (
            f"the breach should be resolved, got {cycle['unresolved_breach_count']}"
        )
        assert cycle["posture"] == "OPEN", (
            f"the freeze should lift, got {cycle['posture']}"
        )
        assert_cents(cycle["available_cents"], 4_372_500, "cycle.available_cents")

        released = validate_success(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER)
        )
        assert released["status"] == "RELEASED", (
            f"the identical call should now succeed, got {released['status']}"
        )
        assert released["released_by"] == "fiscal-1", (
            f"released_by should name the acting fiscal officer, got {released['released_by']}"
        )
        assert read_award(ctx.aw1)["payment_status"] == "UNPAID", (
            "releasing is not paying, so payment_status stays UNPAID"
        )


class TestWaiveOverrideCompensation:
    """The override must land on the exact pre-block numbers."""

    def test_blocking_then_overriding_returns_the_review_count_and_score_exactly(self):
        """
        A blocking screening drops the provisional mean to the four-review 7.10; the
        waive-override restores the fifth review and lands back on 7.28 exactly rather
        than on any recomputation of the surviving four.

        PRD: "The override is a true compensation: every review by that panelist on that
        application in `INVALIDATED` whose `invalidation_reason` is `BLOCKING_CONFLICT`
        returns to `SUBMITTED` with that reason cleared, the application's
        `valid_review_count`, `provisional_composite_score` and `score_spread` return to
        their exact pre-block values, the panel's `blocking_conflict_count` is decremented,
        the panelist moves `RECUSED → SEATED` provided no other `BLOCKING` conflict of
        theirs remains, and the panel's `readiness_score` and the cycle's
        `blocking_conflict_count` and `posture` are recomputed."

        Design: Difficulty/compensating_invariant/waived_conflict_restores_review_count_score_and_readiness
        """
        ctx = cyclemain_round_closed()
        conflict_id = _declare_and_block(ctx.pl1, ctx.app1)

        blocked = read_application(ctx.app1)
        assert blocked["valid_review_count"] == 4, (
            f"the block should drop the count to 4, got {blocked['valid_review_count']}"
        )
        assert_score(
            blocked["provisional_composite_score"],
            7.10,
            "application.provisional_composite_score under the block",
        )

        waived = validate_success(
            api_client.waive_override_conflict(
                conflict_id, {"override_justification": OVERRIDE_NOTE}, PROGRAM_OFFICER
            )
        )
        assert waived["status"] == "WAIVED", (
            f"the declaration should move BLOCKING -> WAIVED, got {waived['status']}"
        )
        assert waived["override_justification"] == OVERRIDE_NOTE, (
            "the justification should be persisted on the waived row"
        )

        rv1 = validate_success(api_client.get_review(ctx.rv1, PROGRAM_OFFICER))
        assert rv1["status"] == "SUBMITTED", (
            f"the invalidated review should return to SUBMITTED, got {rv1['status']}"
        )
        assert rv1["invalidation_reason"] is None, (
            f"the invalidation reason should be cleared, got {rv1['invalidation_reason']}"
        )

        restored = read_application(ctx.app1)
        assert restored["valid_review_count"] == 5, (
            f"all five reviews should count again, got {restored['valid_review_count']}"
        )
        assert_score(
            restored["provisional_composite_score"],
            7.28,
            "application.provisional_composite_score after the override",
        )
        assert_score(restored["final_composite_score"], 7.30, "application.final_composite_score")
        assert_score(restored["score_spread"], 2.50, "application.score_spread")

    def test_the_override_restores_the_seat_the_readiness_and_the_posture(self):
        """
        The override returns the panelist to SEATED with an empty recusal list, lifts the
        panel's readiness from 92.00 back to 100.00 and returns the cycle's posture to
        OPEN, all while the panel stays in deliberation.

        PRD: "Reversal is possible, but only for a discretionary conflict."

        Design: Difficulty/compensating_invariant/waived_conflict_restores_review_count_score_and_readiness
        """
        ctx = cyclemain_round_closed()
        conflict_id = _declare_and_block(ctx.pl1, ctx.app1)

        blocked_panel = read_panel(ctx.pan)
        assert_score(blocked_panel["readiness_score"], 92.00, "panel.readiness_score under the block")
        assert blocked_panel["seated_count"] == 5, "recusal keeps the seat"
        assert read_cycle(ctx.cyc)["posture"] == "RESTRICTED", (
            "a blocking conflict restricts the cycle"
        )

        validate_success(
            api_client.waive_override_conflict(
                conflict_id, {"override_justification": OVERRIDE_NOTE}, PROGRAM_OFFICER
            )
        )

        panelist = validate_success(api_client.get_panelist(ctx.pl1, PROGRAM_OFFICER))
        assert panelist["status"] == "SEATED", (
            f"the panelist should move RECUSED -> SEATED, got {panelist['status']}"
        )
        assert panelist["recused_application_ids"] == [], (
            f"the recusal list should be empty, got {panelist['recused_application_ids']}"
        )

        panel = read_panel(ctx.pan)
        assert panel["blocking_conflict_count"] == 0, (
            f"the panel's blocking count should return to 0, got {panel['blocking_conflict_count']}"
        )
        assert_score(panel["readiness_score"], 100.00, "panel.readiness_score after the override")
        assert panel["status"] == "DELIBERATING", (
            f"the panel is in deliberation throughout, got {panel['status']}"
        )
        assert panel["reopen_required"] is False, (
            "no slot existed to void, so no further round is required"
        )

        cycle = read_cycle(ctx.cyc)
        assert cycle["blocking_conflict_count"] == 0, (
            f"the cycle's blocking count should return to 0, got {cycle['blocking_conflict_count']}"
        )
        assert cycle["posture"] == "OPEN", (
            f"the posture should return to OPEN, got {cycle['posture']}"
        )


class TestConflictOutranksMembership:
    """Two readers on the wrong panel, two different codes."""

    def _second_panel(self, ctx):
        panel_id = create_panel(
            ctx.cyc,
            ctx.disc,
            required_seats=3,
            required_regions=["NORTH", "CENTRAL", "SOUTH"],
            window_start="2026-12-01T00:00:00Z",
            window_end="2027-01-01T00:00:00Z",
        )
        conflicted = nominate(
            panel_id, "plx.tribal@example.org", "Xan Perez", "TRIBAL", is_chair=True
        )
        clean = nominate(panel_id, "ply.coastal@example.org", "Yu Lindqvist", "COASTAL")
        seat(conflicted)
        seat(clean)
        _declare_and_block(conflicted, ctx.app1)
        return panel_id, conflicted, clean

    def test_the_conflicted_reader_hears_about_the_conflict_not_the_membership(self):
        """
        Two readers seated on a different panel attempt the same review of the same
        application: the one carrying a blocking conflict is told about the conflict, and
        the one carrying none is told about the membership.

        PRD: "Third, conflict safety outranks panel-membership referential integrity, so a
        recused panelist who tries to review an application belonging to some other panel
        reports `ERR_CONFLICT_BLOCKS_REVIEW`, not `ERR_PANELIST_NOT_ON_PANEL`."

        Design: Difficulty/priority_pair_validation_conflict/conflict_safety_p75_outranks_panel_membership_p90
        """
        ctx = cyclemain_round_open()
        _, conflicted, clean = self._second_panel(ctx)

        validate_error(
            api_client.create_review(
                {
                    "application_id": ctx.app1,
                    "panelist_id": conflicted,
                    "artistic_excellence": 9,
                    "work_sample_quality": 9,
                    "career_impact": 9,
                    "public_value": 9,
                    "comments": "Should never be recorded.",
                },
                make_panelist_headers(conflicted),
            ),
            "ERR_CONFLICT_BLOCKS_REVIEW",
        )
        validate_error(
            api_client.create_review(
                {
                    "application_id": ctx.app1,
                    "panelist_id": clean,
                    "artistic_excellence": 5,
                    "work_sample_quality": 5,
                    "career_impact": 5,
                    "public_value": 5,
                    "comments": "Also should never be recorded.",
                },
                make_panelist_headers(clean),
            ),
            "ERR_PANELIST_NOT_ON_PANEL",
        )

    def test_neither_refused_draft_leaves_a_review_behind(self):
        """
        Both refusals happen at creation, so no review row exists for either reader and
        the application's counted set and the second panel's assignment count are unmoved.

        PRD: "Creation is refused in three ways: a panelist carrying a `BLOCKING` conflict
        on that application is rejected with `ERR_CONFLICT_BLOCKS_REVIEW`; a panelist who
        is not `SEATED` on the panel to which the application is assigned is rejected with
        `ERR_PANELIST_NOT_ON_PANEL`; and a second review by the same panelist on the same
        application in the same round is rejected with `ERR_DUPLICATE_REVIEW`, the
        uniqueness being on the combination of application, panelist and round across
        reviews that are not `SUPERSEDED`."

        Design: Difficulty/priority_pair_validation_conflict/conflict_safety_p75_outranks_panel_membership_p90
        """
        ctx = cyclemain_round_open()
        second_panel, conflicted, clean = self._second_panel(ctx)

        for panelist_id, headers in (
            (conflicted, make_panelist_headers(conflicted)),
            (clean, make_panelist_headers(clean)),
        ):
            response = api_client.create_review(
                {
                    "application_id": ctx.app1,
                    "panelist_id": panelist_id,
                    "artistic_excellence": 7,
                    "work_sample_quality": 7,
                    "career_impact": 7,
                    "public_value": 7,
                    "comments": "Should never be recorded.",
                },
                headers,
            )
            assert response.status_code == 409, (
                f"creation should be refused, got {response.status_code}"
            )

        authors = {row["panelist_id"] for row in list_reviews_of(ctx.app1)}
        assert authors.isdisjoint({conflicted, clean}), (
            f"no review row should exist for either reader, got authors {authors}"
        )
        assert read_application(ctx.app1)["valid_review_count"] == 0, (
            "the counted set should stay empty"
        )
        assert read_panel(second_panel)["assigned_application_count"] == 0, (
            "the second panel was never chartered, so it holds no application"
        )
