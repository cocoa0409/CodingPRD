"""
The declared preconditions in isolation: anonymity, conflict severity, the
submission window, the work-sample package, the allocation ceiling, cycle posture,
review uniqueness, the acceptance body and the fully satisfied submit.
"""

from conftest import build_application, register_artist

from test_helpers import (
    BOARD_MEMBER,
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    PROGRAM_OFFICER_ID,
    ACCEPT_AGREEMENT_VERSION,
    api_client,
    assert_cents,
    assert_score,
    assert_unsubmitted_draft,
    cornermain_application_draft,
    cornermain_cycle_open,
    cornermain_round_open,
    cornermain_slot_approved,
    cycle_payload,
    discipline_payload,
    make_artist_headers,
    read_application,
    read_award,
    read_cycle,
    read_panel,
    review_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    twoslot_slate_submitted,
)


class TestAnonymityGateOnReviewSubmission:
    """The breach blocks the submit and the redaction lifts it."""

    def test_a_flagged_sample_stops_an_otherwise_perfect_submission(self):
        """
        Flagging one sample breaches the file and freezes the cycle, so the chair's drafted
        review cannot be submitted even though the panel, the round and the author are all
        correct; redacting the sample releases both the freeze and the submission.

        PRD: "The application's `anonymity_status` must not be `BREACHED`, otherwise
        `ERR_ANONYMITY_BREACH_UNRESOLVED`."

        PRD: "When and only when no `FLAGGED` sample remains anywhere on the application, the
        redaction bubbles up: the application's `anonymity_status` moves from `BREACHED` to
        `REDACTED`, the cycle's `unresolved_breach_count` is decremented, and the cycle's
        `posture` is recomputed — releasing the freeze if nothing else holds it."

        Design: Corner/validations/flagged_sample_breach_blocks_review_submission_until_redaction
        """
        ctx = cornermain_round_open()
        review_id = validate_success(
            api_client.create_review(
                review_payload(ctx.app, ctx.pl1), ctx.pl1_headers
            ),
            expected_status=201,
        )["id"]

        flagged = validate_success(
            api_client.screen_work_sample(ctx.ws1, "FLAGGED_IDENTIFYING", PROGRAM_OFFICER)
        )
        assert flagged["status"] == "FLAGGED", (
            f"the sample should be flagged, got {flagged['status']}"
        )
        assert flagged["screened_by"] == PROGRAM_OFFICER_ID, (
            f"the screening officer is stamped, got {flagged['screened_by']}"
        )
        assert read_application(ctx.app)["anonymity_status"] == "BREACHED", (
            "the flag breaches the file, got "
            f"{read_application(ctx.app)['anonymity_status']}"
        )
        breached_cycle = read_cycle(ctx.cyc)
        assert breached_cycle["unresolved_breach_count"] == 1, (
            f"one unresolved breach, got {breached_cycle['unresolved_breach_count']}"
        )
        assert breached_cycle["posture"] == "FROZEN", (
            f"an unresolved breach freezes the cycle, got {breached_cycle['posture']}"
        )

        validate_error(
            api_client.submit_review(review_id, ctx.pl1_headers),
            "ERR_ANONYMITY_BREACH_UNRESOLVED",
        )
        refused = validate_success(api_client.get_review(review_id, PROGRAM_OFFICER))
        assert refused["status"] == "DRAFT", (
            f"the refused review stays a draft, got {refused['status']}"
        )
        assert refused["submitted_at"] is None, "no submission instant may be stamped"

        redacted = validate_success(
            api_client.redact_work_sample(ctx.ws1, PROGRAM_OFFICER)
        )
        assert redacted["status"] == "REDACTED", (
            f"the sample should be redacted, got {redacted['status']}"
        )
        assert redacted["contains_identifying_metadata"] is False, (
            "redaction clears the identifying-metadata flag"
        )
        assert read_application(ctx.app)["anonymity_status"] == "REDACTED", (
            "the repair bubbles up to the application, got "
            f"{read_application(ctx.app)['anonymity_status']}"
        )
        repaired_cycle = read_cycle(ctx.cyc)
        assert repaired_cycle["unresolved_breach_count"] == 0, (
            f"the breach is resolved, got {repaired_cycle['unresolved_breach_count']}"
        )
        assert repaired_cycle["posture"] == "OPEN", (
            f"the freeze is released, got {repaired_cycle['posture']}"
        )

        submitted = validate_success(
            api_client.submit_review(review_id, ctx.pl1_headers)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the identical submission now succeeds, got {submitted['status']}"
        )
        assert_score(submitted["weighted_score"], 8.00, "review.weighted_score")
        application = read_application(ctx.app)
        assert application["valid_review_count"] == 1, (
            f"the restored submission counts, got {application['valid_review_count']}"
        )
        assert_score(
            application["provisional_composite_score"],
            8.00,
            "application.provisional_composite_score",
        )


class TestMandatoryConflictIsNeverWaivable:
    """Severity is derived, and it holds at both waiver gates."""

    def test_an_immediate_family_conflict_refuses_the_waiver_twice(self):
        """
        An immediate-family relationship derives a mandatory severity, so neither the waived
        disposition at screening nor the later override is honoured; a second declaration for
        the same pair is a duplicate, and the blocking screening in between recuses the
        panelist.

        PRD: "The declaration names the `panelist_id` and `application_id` — the pair must be
        unique, and a repeat is rejected with `ERR_DUPLICATE_CONFLICT` — a `relationship_type`
        from `TEACHER_STUDENT`, `IMMEDIATE_FAMILY`, `CO_AUTHOR`, `SAME_INSTITUTION`,
        `FINANCIAL_INTEREST` and `PRIOR_MENTOR`, and a written `disclosure_note`."

        PRD: "A waive-override moves the declaration `BLOCKING → WAIVED` and requires
        `severity` to be `DISCRETIONARY` — a mandatory block is again rejected with
        `ERR_MANDATORY_CONFLICT_NOT_WAIVABLE` — an `override_justification` of at least 20
        characters, and the panel to be in `CHARTERED`, `SCORING`, `DELIBERATING` or
        `SLATE_SUBMITTED`."

        Design: Corner/validations/mandatory_block_conflict_resists_waiver_at_both_gates
        """
        ctx = cornermain_round_open()
        conflict = validate_success(
            api_client.create_conflict(
                {
                    "panelist_id": ctx.pl2,
                    "application_id": ctx.app,
                    "relationship_type": "IMMEDIATE_FAMILY",
                    "disclosure_note": "The applicant is my sibling.",
                },
                ctx.pl2_headers,
            ),
            expected_status=201,
        )
        assert conflict["severity"] == "MANDATORY_BLOCK", (
            f"immediate family is a mandatory block, got {conflict['severity']}"
        )
        assert conflict["status"] == "DECLARED", (
            f"a declaration begins DECLARED, got {conflict['status']}"
        )

        validate_error(
            api_client.create_conflict(
                {
                    "panelist_id": ctx.pl2,
                    "application_id": ctx.app,
                    "relationship_type": "CO_AUTHOR",
                    "disclosure_note": "Second disclosure for the same pair.",
                },
                ctx.pl2_headers,
            ),
            "ERR_DUPLICATE_CONFLICT",
        )

        validate_error(
            api_client.screen_conflict(
                conflict["id"],
                {
                    "disposition": "WAIVED",
                    "override_justification": (
                        "The relationship is remote enough to disregard."
                    ),
                },
                PROGRAM_OFFICER,
            ),
            "ERR_MANDATORY_CONFLICT_NOT_WAIVABLE",
        )
        unscreened = validate_success(
            api_client.get_conflict(conflict["id"], PROGRAM_OFFICER)
        )
        assert unscreened["status"] == "DECLARED", (
            f"the refused waiver leaves it DECLARED, got {unscreened['status']}"
        )
        assert unscreened["screened_by"] is None, (
            f"no officer may be stamped by a refusal, got {unscreened['screened_by']}"
        )

        blocked = validate_success(
            api_client.screen_conflict(
                conflict["id"], {"disposition": "BLOCKING"}, PROGRAM_OFFICER
            )
        )
        assert blocked["status"] == "BLOCKING", (
            f"a mandatory block may only be blocked, got {blocked['status']}"
        )

        validate_error(
            api_client.waive_override_conflict(
                conflict["id"],
                {
                    "override_justification": (
                        "On reflection the relationship is immaterial to scoring."
                    )
                },
                PROGRAM_OFFICER,
            ),
            "ERR_MANDATORY_CONFLICT_NOT_WAIVABLE",
        )
        still_blocking = validate_success(
            api_client.get_conflict(conflict["id"], PROGRAM_OFFICER)
        )
        assert still_blocking["status"] == "BLOCKING", (
            f"the override changes nothing, got {still_blocking['status']}"
        )
        assert still_blocking["override_justification"] is None, (
            "a refused override records no justification, got "
            f"{still_blocking['override_justification']}"
        )

        panelist = validate_success(api_client.get_panelist(ctx.pl2, PROGRAM_OFFICER))
        assert panelist["status"] == "RECUSED", (
            f"the blocking screening recuses the panelist, got {panelist['status']}"
        )
        assert read_panel(ctx.pan)["blocking_conflict_count"] == 1, (
            "the panel carries one blocking conflict, got "
            f"{read_panel(ctx.pan)['blocking_conflict_count']}"
        )


class TestSubmissionWindowBoundaries:
    """Both window boundaries are inclusive; only the clock moves."""

    def _window_fixture(self):
        set_clock("2026-08-01T00:00:00Z")
        cycle_id = validate_success(
            api_client.create_cycle(
                cycle_payload(name="FY2027 Fellowships (window fixture)"), PROGRAM_OFFICER
            ),
            expected_status=201,
        )["id"]
        discipline_id = validate_success(
            api_client.create_discipline(
                discipline_payload(cycle_id, allocation_cents=3_000_000), PROGRAM_OFFICER
            ),
            expected_status=201,
        )["id"]
        validate_success(api_client.set_cycle_status(cycle_id, "OPEN", PROGRAM_OFFICER))
        artist_id = register_artist(
            "Cleo Amari", "cleo.amari@example.org", "2023-01-10", "NORTH"
        )
        headers = make_artist_headers(artist_id)
        application_id = build_application(
            cycle_id,
            discipline_id,
            artist_id,
            headers,
            statement="A sequence on tidal flats.",
            narrative="Twelve years of publication.",
            page_counts=(10, 12),
            submit=False,
        )
        return cycle_id, discipline_id, application_id, headers

    def test_the_open_instant_is_admitted_while_a_minute_before_it_is_not(self):
        """
        On a cycle that is OPEN throughout, a submission a fortnight early is refused for the
        window, the very instant the window opens is accepted, and the frozen residency figure
        is measured at the deadline rather than at that submission instant.

        PRD: "The logical clock must be at or after `application_open_at`, otherwise
        `ERR_APPLICATION_WINDOW_NOT_OPEN`, and at or before `application_deadline_at`,
        otherwise `ERR_APPLICATION_DEADLINE_PASSED` — both boundaries inclusive."

        Design: Corner/validations/submission_before_the_open_instant_is_refused_on_an_open_cycle
        """
        cycle_id, _, application_id, headers = self._window_fixture()
        assert read_cycle(cycle_id)["status"] == "OPEN", (
            "the cycle is open for the whole test"
        )

        validate_error(
            api_client.submit_application(application_id, headers),
            "ERR_APPLICATION_WINDOW_NOT_OPEN",
        )
        assert_unsubmitted_draft(read_application(application_id))

        set_clock("2026-08-15T00:00:00Z")
        submitted = validate_success(
            api_client.submit_application(application_id, headers)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the open instant itself is admitted, got {submitted['status']}"
        )
        assert str(submitted["submitted_at"]).startswith("2026-08-15"), (
            f"submitted_at comes from the clock, got {submitted['submitted_at']}"
        )
        assert submitted["sealed_alias"] == "LIT-2027-0001", (
            f"the first submission takes the first alias, got {submitted['sealed_alias']}"
        )
        assert submitted["residency_months_at_deadline"] == 45, (
            "residency is measured at the deadline, not at the submission instant, got "
            f"{submitted['residency_months_at_deadline']}"
        )

    def test_the_day_after_the_deadline_is_refused_on_the_same_open_cycle(self):
        """
        Once the clock passes the deadline a second artist's complete package is refused on the
        deadline alone, while the cycle is still OPEN and nothing else about the request is
        wrong.

        PRD: "The logical clock must be at or after `application_open_at`, otherwise
        `ERR_APPLICATION_WINDOW_NOT_OPEN`, and at or before `application_deadline_at`,
        otherwise `ERR_APPLICATION_DEADLINE_PASSED` — both boundaries inclusive."

        Design: Corner/validations/submission_before_the_open_instant_is_refused_on_an_open_cycle
        """
        cycle_id, discipline_id, application_id, headers = self._window_fixture()
        set_clock("2026-08-15T00:00:00Z")
        validate_success(api_client.submit_application(application_id, headers))

        set_clock("2026-10-16T00:00:00Z")
        other_artist = register_artist(
            "Sol Marek",
            "sol.marek@example.org",
            "2020-04-04",
            "SOUTH",
            residency_county="Ridge",
        )
        other_headers = make_artist_headers(other_artist)
        late_application = build_application(
            cycle_id,
            discipline_id,
            other_artist,
            other_headers,
            statement="Essays on ferry towns.",
            narrative="Nine years of criticism.",
            page_counts=(8, 9),
            submit=False,
        )

        validate_error(
            api_client.submit_application(late_application, other_headers),
            "ERR_APPLICATION_DEADLINE_PASSED",
        )
        assert_unsubmitted_draft(read_application(late_application))
        assert read_cycle(cycle_id)["status"] == "OPEN", (
            "only the clock, not the cycle status, refused the submission"
        )


class TestWorkSamplePackageIsJudgedAtSubmit:
    """Uploads pass individually; the collection is judged as a whole."""

    def test_satisfying_the_count_does_not_clear_the_duration_ceiling(self):
        """
        A single manuscript sample is too few; the seven-hundred-second audio sample that fixes
        the count breaks the six-hundred-second ceiling; and a third manuscript sample raises
        the count again without clearing that ceiling — all three refusals coming from the
        submit, never from the upload.

        PRD: "And the work-sample package must satisfy the discipline: `work_sample_count` at
        least `required_work_sample_count`, every sample's `medium` inside `allowed_media`, and
        the summed `duration_seconds` of the `AUDIO` and `VIDEO` samples at or below
        `max_total_duration_seconds`, otherwise `ERR_WORK_SAMPLE_REQUIREMENTS_NOT_MET`."

        Design: Corner/validations/work_sample_requirements_are_evaluated_at_submit
        """
        ctx = cornermain_cycle_open()
        artist_id = register_artist(
            "Cleo Amari", "cleo.amari@example.org", "2023-01-10", "NORTH"
        )
        headers = make_artist_headers(artist_id)
        application_id = build_application(
            ctx.cyc,
            ctx.disc,
            artist_id,
            headers,
            statement="A sequence on tidal flats.",
            narrative="Twelve years of publication.",
            page_counts=(10,),
            submit=False,
        )
        assert read_application(application_id)["work_sample_count"] == 1, (
            "one sample is on file, got "
            f"{read_application(application_id)['work_sample_count']}"
        )

        validate_error(
            api_client.submit_application(application_id, headers),
            "ERR_WORK_SAMPLE_REQUIREMENTS_NOT_MET",
        )

        audio = validate_success(
            api_client.create_work_sample(
                {
                    "application_id": application_id,
                    "medium": "AUDIO",
                    "ordinal": 2,
                    "duration_seconds": 700,
                    "contains_identifying_metadata": False,
                },
                headers,
            ),
            expected_status=201,
        )
        assert audio["duration_seconds"] == 700, (
            f"the upload itself is accepted, got {audio['duration_seconds']}"
        )
        assert read_application(application_id)["work_sample_count"] == 2, (
            "the count now satisfies the discipline, got "
            f"{read_application(application_id)['work_sample_count']}"
        )

        validate_error(
            api_client.submit_application(application_id, headers),
            "ERR_WORK_SAMPLE_REQUIREMENTS_NOT_MET",
        )

        validate_success(
            api_client.create_work_sample(
                {
                    "application_id": application_id,
                    "medium": "MANUSCRIPT_PAGES",
                    "ordinal": 3,
                    "page_count": 14,
                    "contains_identifying_metadata": False,
                },
                headers,
            ),
            expected_status=201,
        )
        assert read_application(application_id)["work_sample_count"] == 3, (
            "three samples are now counted, got "
            f"{read_application(application_id)['work_sample_count']}"
        )
        validate_error(
            api_client.submit_application(application_id, headers),
            "ERR_WORK_SAMPLE_REQUIREMENTS_NOT_MET",
        )

        assert_unsubmitted_draft(read_application(application_id))


class TestAllocationCeiling:
    """The ceiling is the appropriation less the reserve, inclusive."""

    def test_five_million_plus_eight_hundred_thousand_is_over_and_seven_hundred_is_exact(
        self,
    ):
        """
        Against a 6,000,000-cent appropriation whose reserve is 300,000, a second category of
        800,000 pushes the sum past the 5,700,000 ceiling and is refused, while 700,000 lands
        exactly on it and is accepted — and the cycle then opens against the same sum.

        PRD: "`allocation_cents`, at least 1, is the sub-budget reserved to the discipline;
        whenever a category is added, the sum of `allocation_cents` across the cycle's
        categories must not exceed `total_budget_cents` less `reserve_cents`, and a violation is
        rejected with `ERR_ALLOCATION_EXCEEDS_BUDGET`."

        Design: Corner/validations/discipline_allocations_are_capped_by_the_budget_minus_reserve
        """
        set_clock("2026-09-01T00:00:00Z")
        cycle_id = validate_success(
            api_client.create_cycle(
                cycle_payload(name="FY2027 Fellowships (allocation fixture)"),
                PROGRAM_OFFICER,
            ),
            expected_status=201,
        )["id"]
        validate_success(
            api_client.create_discipline(
                discipline_payload(cycle_id, allocation_cents=5_000_000), PROGRAM_OFFICER
            ),
            expected_status=201,
        )

        visual = dict(
            code="VISUAL_ARTS",
            alias_prefix="VIS",
            allowed_media=["IMAGE_SET"],
            required_panel_seats=3,
        )
        validate_error(
            api_client.create_discipline(
                discipline_payload(cycle_id, allocation_cents=800_000, **visual),
                PROGRAM_OFFICER,
            ),
            "ERR_ALLOCATION_EXCEEDS_BUDGET",
        )
        accepted = validate_success(
            api_client.create_discipline(
                discipline_payload(cycle_id, allocation_cents=700_000, **visual),
                PROGRAM_OFFICER,
            ),
            expected_status=201,
        )
        assert_cents(accepted["allocation_cents"], 700_000, "discipline.allocation_cents")

        opened = validate_success(
            api_client.set_cycle_status(cycle_id, "OPEN", PROGRAM_OFFICER)
        )
        assert opened["status"] == "OPEN", (
            f"the same sum passes the open-time check, got {opened['status']}"
        )
        assert_cents(opened["reserve_cents"], 300_000, "cycle.reserve_cents")
        assert_cents(opened["committed_cents"], 0, "cycle.committed_cents")
        assert_cents(opened["available_cents"], 5_700_000, "cycle.available_cents")


class TestPostureGateOnBoardApproval:
    """A conflict on another application still restricts the whole cycle."""

    def test_a_blocking_conflict_elsewhere_refuses_the_rank_one_approval(self):
        """
        The rank-1 slot is faultless — its application is scored and the allocation is ample —
        yet the approval is refused because a blocking conflict on the rank-2 application has
        restricted the cycle; waiving that conflict lets the identical approval through.

        PRD: "The cycle's `posture` must be `OPEN`: a `FROZEN` posture is rejected with
        `ERR_CYCLE_POSTURE_FROZEN` and a `RESTRICTED` one with `ERR_CYCLE_POSTURE_RESTRICTED`."

        Design: Corner/validations/unmanaged_blocking_conflict_restricts_board_approval
        """
        ctx = twoslot_slate_submitted()
        conflict = validate_success(
            api_client.create_conflict(
                {
                    "panelist_id": ctx.tpl2,
                    "application_id": ctx.appB,
                    "relationship_type": "SAME_INSTITUTION",
                    "disclosure_note": "We teach in the same department.",
                },
                ctx.tpl2_headers,
            ),
            expected_status=201,
        )
        assert conflict["severity"] == "DISCRETIONARY", (
            f"a shared institution is discretionary, got {conflict['severity']}"
        )
        validate_success(
            api_client.screen_conflict(
                conflict["id"], {"disposition": "BLOCKING"}, PROGRAM_OFFICER
            )
        )
        assert (
            validate_success(api_client.get_slot(ctx.slotB, PROGRAM_OFFICER))["status"]
            == "VOIDED"
        ), "the conflicted application's own slot is voided"

        restricted = read_cycle(ctx.tcyc)
        assert restricted["blocking_conflict_count"] == 1, (
            f"the cycle carries one blocking conflict, got "
            f"{restricted['blocking_conflict_count']}"
        )
        assert restricted["posture"] == "RESTRICTED", (
            f"the posture is restricted, got {restricted['posture']}"
        )

        validate_error(
            api_client.board_action(
                ctx.slotA,
                {"action": "APPROVE", "expected_cycle_version": restricted["version"]},
                BOARD_MEMBER,
            ),
            "ERR_CYCLE_POSTURE_RESTRICTED",
        )
        untouched = validate_success(api_client.get_slot(ctx.slotA, PROGRAM_OFFICER))
        assert untouched["status"] == "PROPOSED", (
            f"the rank-1 slot is unmoved, got {untouched['status']}"
        )
        assert untouched["awarded_amount_cents"] is None, (
            f"no amount may be recorded, got {untouched['awarded_amount_cents']}"
        )

        waived = validate_success(
            api_client.waive_override_conflict(
                conflict["id"],
                {
                    "override_justification": (
                        "Shared department only; no supervisory relationship exists."
                    )
                },
                PROGRAM_OFFICER,
            )
        )
        assert waived["status"] == "WAIVED", (
            f"a discretionary conflict may be overridden, got {waived['status']}"
        )
        assert (
            validate_success(api_client.get_panelist(ctx.tpl2, PROGRAM_OFFICER))["status"]
            == "SEATED"
        ), "the panelist returns to their seat"

        released = read_cycle(ctx.tcyc)
        assert released["blocking_conflict_count"] == 0, (
            f"the blocking count is cleared, got {released['blocking_conflict_count']}"
        )
        assert released["posture"] == "OPEN", (
            f"the restriction is lifted, got {released['posture']}"
        )

        approved = validate_success(
            api_client.board_action(
                ctx.slotA,
                {"action": "APPROVE", "expected_cycle_version": released["version"]},
                BOARD_MEMBER,
            )
        )
        assert approved["status"] == "BOARD_APPROVED", (
            f"the identical approval now succeeds, got {approved['status']}"
        )
        assert_cents(
            approved["awarded_amount_cents"], 1_500_000, "slot.awarded_amount_cents"
        )


class TestReviewUniquenessPerRound:
    """The triple of application, panelist and round is the key."""

    def test_the_same_reader_may_not_file_twice_in_one_round(self):
        """
        A second draft from the reader who already holds one in round 1 is refused as a
        duplicate, a different reader's first draft in the same round is accepted, and the
        refusal leaves no row behind.

        PRD: "Creation is refused in three ways: a panelist carrying a `BLOCKING` conflict on
        that application is rejected with `ERR_CONFLICT_BLOCKS_REVIEW`; a panelist who is not
        `SEATED` on the panel to which the application is assigned is rejected with
        `ERR_PANELIST_NOT_ON_PANEL`; and a second review by the same panelist on the same
        application in the same round is rejected with `ERR_DUPLICATE_REVIEW`, the uniqueness
        being on the combination of application, panelist and round across reviews that are not
        `SUPERSEDED`."

        Design: Corner/validations/second_review_for_the_same_round_is_refused_as_duplicate
        """
        ctx = cornermain_round_open()
        validate_success(
            api_client.create_review(review_payload(ctx.app, ctx.pl1), ctx.pl1_headers),
            expected_status=201,
        )

        validate_error(
            api_client.create_review(
                review_payload(
                    ctx.app,
                    ctx.pl1,
                    artistic_excellence=5,
                    work_sample_quality=5,
                    career_impact=5,
                    public_value=5,
                    comments="A second sheet from the same reader.",
                ),
                ctx.pl1_headers,
            ),
            "ERR_DUPLICATE_REVIEW",
        )

        other = validate_success(
            api_client.create_review(
                review_payload(
                    ctx.app,
                    ctx.pl2,
                    artistic_excellence=7,
                    work_sample_quality=7,
                    career_impact=6,
                    public_value=5,
                    comments="Conventional but competent.",
                ),
                ctx.pl2_headers,
            ),
            expected_status=201,
        )
        assert other["round_number"] == 1, (
            f"the second reader files in the same round, got {other['round_number']}"
        )
        assert other["status"] == "DRAFT", (
            f"a new review begins as a draft, got {other['status']}"
        )

        rows, meta = validate_paginated(
            api_client.list_reviews(
                PROGRAM_OFFICER, {"application_id": ctx.app, "limit": 100}
            )
        )
        assert meta["total_count"] == 2, (
            f"the refused request created no row, got {meta['total_count']}"
        )
        assert len(rows) == 2, f"two reviews are on file, got {len(rows)}"


class TestAcceptanceBodyOutranksTheBusinessGate:
    """A malformed body is reported before the certification rule."""

    def test_a_wrong_agreement_version_wins_over_the_unsigned_certification(self):
        """
        One acceptance carries both a wrong agreement version and an unsigned tax
        certification and reports the request-shape error; correcting only the version surfaces
        the certification error; neither refusal generates a payment schedule.

        PRD: "Acceptance carries `accept_agreement_version`, which must equal exactly the
        string `FELLOWSHIP-AGREEMENT-2027.1` — any other value is rejected with
        `ERR_INVALID_REQUEST` — and `tax_certification_signed`, which must be true, a false
        value being rejected with `ERR_TAX_CERTIFICATION_REQUIRED` so that no schedule is
        generated for an incomplete agreement."

        PRD: "**Request shape** — required fields present, correct JSON types, enum members
        inside their declared sets, integers inside their declared ranges, strings meeting
        their declared minimum lengths, datetimes in ISO 8601 UTC (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/malformed_acceptance_body_outranks_the_tax_certification_gate
        """
        ctx = cornermain_slot_approved()

        validate_error(
            api_client.accept_award(
                ctx.aw,
                {
                    "accept_agreement_version": "FELLOWSHIP-AGREEMENT-2026.9",
                    "tax_certification_signed": False,
                },
                ctx.art_headers,
            ),
            "ERR_INVALID_REQUEST",
        )
        validate_error(
            api_client.accept_award(
                ctx.aw,
                {
                    "accept_agreement_version": ACCEPT_AGREEMENT_VERSION,
                    "tax_certification_signed": False,
                },
                ctx.art_headers,
            ),
            "ERR_TAX_CERTIFICATION_REQUIRED",
        )

        _, meta = validate_paginated(
            api_client.list_installments(FISCAL_OFFICER, {"award_id": ctx.aw, "limit": 100})
        )
        assert meta["total_count"] == 0, (
            f"no schedule may be generated by a refusal, got {meta['total_count']}"
        )
        assert read_award(ctx.aw)["status"] == "OFFERED", (
            f"the award is still merely offered, got {read_award(ctx.aw)['status']}"
        )

        accepted = validate_success(
            api_client.accept_award(
                ctx.aw,
                {
                    "accept_agreement_version": ACCEPT_AGREEMENT_VERSION,
                    "tax_certification_signed": True,
                },
                ctx.art_headers,
            )
        )
        assert accepted["status"] == "ACCEPTED", (
            f"the well-formed acceptance succeeds, got {accepted['status']}"
        )
        assert accepted["accept_agreement_version"] == ACCEPT_AGREEMENT_VERSION, (
            f"the version is recorded, got {accepted['accept_agreement_version']}"
        )
        assert_cents(
            accepted["undisbursed_gross_cents"],
            1_500_000,
            "award.undisbursed_gross_cents",
        )
        assert str(accepted["final_report_due_at"]).startswith("2028-02-29"), (
            f"the report due date is set on acceptance, got "
            f"{accepted['final_report_due_at']}"
        )


class TestFullySatisfiedSubmission:
    """Nothing is violated, and five derived fields land at once."""

    def test_the_clean_submit_stamps_the_whole_snapshot_in_one_response(self):
        """
        With the window open, the artist in good standing, two allowed samples on file and no
        prior fellowship, the submit response itself already carries the alias, the instant,
        the denormalized name and region and the frozen residency figure.

        PRD: "And `applicant_legal_name` and `applicant_region` are denormalized from the
        artist row as of that instant; the latter is the basis of the geographic-distribution
        evaluation of §3.11."

        PRD: "`blackout_gap_years` is frozen as the cycle's `fiscal_year` less the artist's
        `last_award_fiscal_year`, or as `null` when the artist has no recorded prior award."

        Design: Corner/validations/submit_with_every_gate_satisfied_stamps_the_full_snapshot
        """
        ctx = cornermain_application_draft()

        submitted = validate_success(
            api_client.submit_application(ctx.app, ctx.art_headers)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the clean package is accepted, got {submitted['status']}"
        )
        assert submitted["anonymity_status"] == "SEALED", (
            f"the file is still sealed, got {submitted['anonymity_status']}"
        )
        assert submitted["sealed_alias"] == "LIT-2027-0001", (
            f"the alias is minted in the same response, got {submitted['sealed_alias']}"
        )
        assert str(submitted["submitted_at"]).startswith("2026-09-01"), (
            f"submitted_at comes from the clock, got {submitted['submitted_at']}"
        )
        assert submitted["applicant_legal_name"] == "Cleo Amari", (
            f"the name is denormalized, got {submitted['applicant_legal_name']}"
        )
        assert submitted["applicant_region"] == "NORTH", (
            f"the region is denormalized, got {submitted['applicant_region']}"
        )
        assert submitted["residency_months_at_deadline"] == 45, (
            "the residency figure is frozen at the deadline, got "
            f"{submitted['residency_months_at_deadline']}"
        )
        assert submitted["blackout_gap_years"] is None, (
            "an artist with no prior fellowship carries a null gap, got "
            f"{submitted['blackout_gap_years']}"
        )
        assert submitted["work_sample_count"] == 2, (
            f"two samples are counted, got {submitted['work_sample_count']}"
        )
        assert submitted["valid_review_count"] == 0, (
            f"no review exists yet, got {submitted['valid_review_count']}"
        )
