"""
Whole error families walked on one fixture at a time: the two cycle close guards,
the board waterfall's refusals, the disbursement guard, the reporting ladder and
the two appeal remedies.
"""

from test_helpers import (
    ACCEPT_AGREEMENT_VERSION,
    APPEALS_OFFICER,
    APPEALS_OFFICER_ID,
    BOARD_MEMBER,
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    api_client,
    assert_cents,
    assert_cycle_ledger,
    assert_score,
    award_id_for_application,
    cornermain_cycle_awarded,
    cornermain_installment_one_paid,
    cornermain_slate_submitted,
    cycle_version,
    list_reviews_of,
    read_application,
    read_artist,
    read_award,
    read_cycle,
    read_discipline,
    read_panel,
    set_clock,
    twoslot_slate_submitted,
    validate_error,
    validate_paginated,
    validate_success,
)

REPORT_BODY = {
    "narrative": "The manuscript was completed in eleven months.",
    "public_value_statement": "Four free readings in county libraries.",
    "audience_reached_count": 320,
    "expenditure_summary": "Materials, travel and childcare.",
}


def _read_slot(slot_id):
    return validate_success(api_client.get_slot(slot_id, PROGRAM_OFFICER))


def _pay_remaining_installments(ctx):
    """Carry a CornerMain award from one paid installment to FULLY_PAID."""
    set_clock("2027-05-01T00:00:00Z")
    validate_success(api_client.release_installment(ctx.i2, FISCAL_OFFICER))
    validate_success(api_client.pay_installment(ctx.i2, FISCAL_OFFICER))
    set_clock("2027-08-29T00:00:00Z")
    validate_success(api_client.release_installment(ctx.i3, FISCAL_OFFICER))
    validate_success(api_client.pay_installment(ctx.i3, FISCAL_OFFICER))


def _strike_the_only_slot(ctx):
    """Strike the CornerMain slot at the 2026-10-16 clock, opening the appeal window."""
    validate_success(
        api_client.board_action(
            ctx.slot,
            {
                "action": "STRIKE",
                "expected_cycle_version": cycle_version(ctx.cyc),
                "struck_reason_code": "BUDGET",
            },
            BOARD_MEMBER,
        )
    )


class TestCycleCloseGuards:
    """Two different children block two different steps of the same ladder."""

    def test_a_pending_slot_blocks_awarding_and_an_open_award_blocks_closing_out(self):
        """
        A still-proposed slot refuses the move into awarded; once the slot is approved the move
        succeeds and releases the reserve, so availability rises on an unchanged committed
        total; the offered award then refuses the close-out until it is declined.

        PRD: "It requires that no recommendation slot of the cycle still be `PROPOSED`, so that
        the board has disposed of the whole slate; a pending slot is rejected with
        `ERR_SLOTS_PENDING_BOARD_ACTION`."

        PRD: "`AWARDED → CLOSED_OUT` requires that every award of the cycle have reached
        `COMPLETED`, `DECLINED`, `RESCINDED` or `FORFEITED`, failing which it is rejected with
        `ERR_CYCLE_HAS_OPEN_AWARDS`, and that every appeal on the cycle's applications be
        `UPHELD` or `DENIED`, failing which it is rejected with `ERR_APPEAL_STATE_INVALID`; on
        success every panel of the cycle not already `DISSOLVED` becomes `DISSOLVED`, its seated
        panelists remaining `SEATED` but no further review being creatable."

        Design: Corner/errors/cycle_advance_and_close_out_each_guard_their_open_children
        """
        ctx = cornermain_slate_submitted()

        validate_error(
            api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER),
            "ERR_SLOTS_PENDING_BOARD_ACTION",
        )
        assert read_cycle(ctx.cyc)["status"] == "BOARD_REVIEW", (
            "the refused advance leaves the cycle in board review"
        )

        approved = validate_success(
            api_client.board_action(
                ctx.slot,
                {"action": "APPROVE", "expected_cycle_version": cycle_version(ctx.cyc)},
                BOARD_MEMBER,
            )
        )
        assert_cents(
            approved["awarded_amount_cents"], 1_500_000, "slot.awarded_amount_cents"
        )
        assert_cycle_ledger(
            read_cycle(ctx.cyc), 1_500_000, 0.085, 127_500, 300_000, 1_627_500, 4_072_500, "OPEN"
        )

        awarded = validate_success(
            api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER)
        )
        assert awarded["status"] == "AWARDED", (
            f"the disposed slate admits the advance, got {awarded['status']}"
        )
        assert_cycle_ledger(
            awarded, 1_500_000, 0.085, 127_500, 0, 1_627_500, 4_372_500, "OPEN"
        )

        award_id = award_id_for_application(ctx.app)
        validate_error(
            api_client.set_cycle_status(ctx.cyc, "CLOSED_OUT", PROGRAM_OFFICER),
            "ERR_CYCLE_HAS_OPEN_AWARDS",
        )
        assert read_award(award_id)["status"] == "OFFERED", (
            "the award is still an open offer"
        )

        declined = validate_success(api_client.decline_award(award_id, ctx.art_headers))
        assert declined["status"] == "DECLINED", (
            f"the recipient declines the offer, got {declined['status']}"
        )
        assert_cycle_ledger(read_cycle(ctx.cyc), 0, 0.0, 0, 0, 0, 6_000_000, "OPEN")

        closed = validate_success(
            api_client.set_cycle_status(ctx.cyc, "CLOSED_OUT", PROGRAM_OFFICER)
        )
        assert closed["status"] == "CLOSED_OUT", (
            f"no open award remains, got {closed['status']}"
        )
        assert read_panel(ctx.pan)["status"] == "DISSOLVED", (
            "closing out dissolves the cycle's panels"
        )


class TestBoardWaterfallRefusals:
    """Rank order first, then the allocation, then the slot's own state."""

    def test_rank_two_cannot_go_first_and_cannot_be_prorated_below_the_floor(self):
        """
        On an allocation that funds only one full award the rank-two slot is refused for acting
        out of order, and after rank one takes the whole base award the remainder is under the
        prorated floor, so rank two is refused outright rather than funded at the remainder;
        re-approving rank one is refused for its state, and neither refusal spends the version
        the eventual strike uses.

        PRD: "Every recommendation slot of the same panel with a lower `rank` must already be
        `BOARD_APPROVED` or `BOARD_STRUCK`, so that the funding waterfall is deterministic;
        acting out of order is rejected with `ERR_SLOT_RANK_ORDER_VIOLATION`."

        PRD: "In every other case — a remainder below the prorated floor, or a policy of
        `SKIP_TO_ALTERNATE` — the approval is refused with `ERR_DISCIPLINE_ALLOCATION_EXHAUSTED`."

        PRD: "A board action on a slot that is not `PROPOSED` is rejected with
        `ERR_SLOT_STATE_INVALID`."

        Design: Corner/errors/board_actions_respect_rank_order_then_exhaust_the_allocation
        """
        ctx = twoslot_slate_submitted()

        validate_error(
            api_client.board_action(
                ctx.slotB,
                {"action": "APPROVE", "expected_cycle_version": ctx.tcyc_v},
                BOARD_MEMBER,
            ),
            "ERR_SLOT_RANK_ORDER_VIOLATION",
        )
        assert _read_slot(ctx.slotB)["status"] == "PROPOSED", (
            "the out-of-order slot is untouched"
        )

        first = validate_success(
            api_client.board_action(
                ctx.slotA,
                {"action": "APPROVE", "expected_cycle_version": ctx.tcyc_v},
                BOARD_MEMBER,
            )
        )
        assert_cents(first["awarded_amount_cents"], 1_500_000, "slot.awarded_amount_cents")
        award = read_award(award_id_for_application(ctx.appA))
        assert award["is_prorated"] is False, (
            "the full base award is not a prorated one"
        )
        assert_cents(award["gross_amount_cents"], 1_500_000, "award.gross_amount_cents")

        current = cycle_version(ctx.tcyc)
        validate_error(
            api_client.board_action(
                ctx.slotB,
                {"action": "APPROVE", "expected_cycle_version": current},
                BOARD_MEMBER,
            ),
            "ERR_DISCIPLINE_ALLOCATION_EXHAUSTED",
        )
        validate_error(
            api_client.board_action(
                ctx.slotA,
                {"action": "APPROVE", "expected_cycle_version": current},
                BOARD_MEMBER,
            ),
            "ERR_SLOT_STATE_INVALID",
        )

        struck = validate_success(
            api_client.board_action(
                ctx.slotB,
                {
                    "action": "STRIKE",
                    "expected_cycle_version": current,
                    "struck_reason_code": "BUDGET",
                },
                BOARD_MEMBER,
            )
        )
        assert struck["status"] == "BOARD_STRUCK", (
            f"the version the refusals left alone still works, got {struck['status']}"
        )

        discipline = read_discipline(ctx.tdisc)
        assert_cents(discipline["committed_cents"], 1_500_000, "discipline.committed_cents")
        assert discipline["funded_application_count"] == 1, (
            "one of the two applications is funded, got "
            f"{discipline['funded_application_count']}"
        )


class TestMoneyMovedGuards:
    """A released row is already too far along for a rescission."""

    def test_a_released_installment_blocks_rescission_and_two_other_codes_follow(self):
        """
        Accepting the accepted award again while the window is still open is refused for the
        award's state; with installment one released but not yet paid the rescission is refused
        because money is already committed to leave, and paying an installment that is still
        scheduled is refused for its state; paying the released row then works and turns the
        award active.

        PRD: "**Rescission** is a `ProgramOfficer` act available from `OFFERED` and from
        `ACCEPTED`, requiring a `rescind_reason_code` of `APPEAL_REMEDY`,
        `INELIGIBILITY_DISCOVERED` or `APPLICANT_REQUEST` — its absence is rejected with
        `ERR_INVALID_REQUEST` — and, from `ACCEPTED`, requiring that no installment of the award
        be `RELEASED` or `PAID`, a violation being rejected with `ERR_AWARD_HAS_DISBURSEMENTS`:
        once money has left the council the award must be wound down through reversal and
        reporting, not rescission."

        PRD: "Accepting the same award twice while still inside the window is a different
        matter and reports the state error."

        PRD: "The first payment also moves the award `ACCEPTED → ACTIVE`."

        Design: Corner/errors/rescission_and_installment_actions_are_blocked_once_money_moves
        """
        ctx = cornermain_cycle_awarded()

        # Still inside the acceptance window, so the second acceptance is judged on the
        # award's state rather than on the deadline.
        validate_error(
            api_client.accept_award(
                ctx.aw,
                {
                    "accept_agreement_version": ACCEPT_AGREEMENT_VERSION,
                    "tax_certification_signed": True,
                },
                ctx.art_headers,
            ),
            "ERR_AWARD_STATE_INVALID",
        )
        _, meta = validate_paginated(
            api_client.list_installments(FISCAL_OFFICER, {"award_id": ctx.aw, "limit": 100})
        )
        assert meta["total_count"] == 3, (
            f"the refused acceptance schedules nothing, got {meta['total_count']}"
        )

        set_clock("2027-01-01T00:00:00Z")
        released = validate_success(api_client.release_installment(ctx.i1, FISCAL_OFFICER))
        assert released["status"] == "RELEASED", (
            f"installment one is released, got {released['status']}"
        )

        validate_error(
            api_client.rescind_award(ctx.aw, "APPLICANT_REQUEST", PROGRAM_OFFICER),
            "ERR_AWARD_HAS_DISBURSEMENTS",
        )
        assert read_award(ctx.aw)["status"] == "ACCEPTED", (
            "the refused rescission leaves the award accepted"
        )
        assert (
            validate_success(api_client.get_installment(ctx.i1, FISCAL_OFFICER))["status"]
            == "RELEASED"
        ), "the released row is untouched by the refusal"

        validate_error(
            api_client.pay_installment(ctx.i2, FISCAL_OFFICER),
            "ERR_INSTALLMENT_STATE_INVALID",
        )

        paid = validate_success(api_client.pay_installment(ctx.i1, FISCAL_OFFICER))
        assert paid["status"] == "PAID", f"the released row pays, got {paid['status']}"
        assert str(paid["paid_at"]).startswith("2027-01-01"), (
            f"payment is stamped from the clock, got {paid['paid_at']}"
        )

        award = read_award(ctx.aw)
        assert award["status"] == "ACTIVE", (
            f"the first payment activates the award, got {award['status']}"
        )
        assert award["payment_status"] == "PARTIALLY_PAID", (
            f"one of three rows is paid, got {award['payment_status']}"
        )
        assert_cents(award["disbursed_gross_cents"], 600_000, "award.disbursed_gross_cents")


class TestFinalReportFamily:
    """Not due, duplicated, mis-stated and finally capped."""

    def test_the_reporting_ladder_runs_from_not_due_to_the_revision_cap(self):
        """
        Filing before the grant period ends is refused as not due; once the clock passes the
        period end the filing is accepted and a second one is refused as a duplicate; a resubmit
        of an already-submitted report is refused for its state; and a third revision request is
        refused at the cap, after which acceptance completes the fully paid award and writes the
        artist's award history.

        PRD: "Filing a report while the status is still `NOT_DUE` is rejected with
        `ERR_FINAL_REPORT_NOT_DUE` — a report cannot precede the end of the grant period."

        PRD: "At most one report may exist per award, and a second attempt is rejected with
        `ERR_DUPLICATE_FINAL_REPORT`; corrections travel through the revision loop, never
        through a second row."

        PRD: "`REQUEST_REVISION` requires `revision_count` to be below 2 — a third revision
        request is refused with `ERR_MAX_REVISIONS_REACHED`, after which the report must be
        accepted or the award pursued as delinquent — and requires a `revision_note` of at least
        20 characters, a shorter or absent one being rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/final_report_family_from_not_due_through_the_revision_cap
        """
        ctx = cornermain_installment_one_paid()
        _pay_remaining_installments(ctx)
        assert read_award(ctx.aw)["payment_status"] == "FULLY_PAID", (
            "all three installments are paid"
        )

        validate_error(
            api_client.create_final_report(
                {"award_id": ctx.aw, **REPORT_BODY}, ctx.art_headers
            ),
            "ERR_FINAL_REPORT_NOT_DUE",
        )
        assert read_award(ctx.aw)["reporting_status"] == "NOT_DUE", (
            "the grant period has not ended yet"
        )

        set_clock("2028-01-01T00:00:00Z")
        assert read_award(ctx.aw)["reporting_status"] == "DUE", (
            "the checkpoint moves the report to due once the period ends"
        )

        report = validate_success(
            api_client.create_final_report(
                {"award_id": ctx.aw, **REPORT_BODY}, ctx.art_headers
            ),
            expected_status=201,
        )
        assert report["status"] == "SUBMITTED", (
            f"a new report begins submitted, got {report['status']}"
        )
        assert report["revision_count"] == 0, (
            f"no revision has been requested, got {report['revision_count']}"
        )
        assert read_award(ctx.aw)["reporting_status"] == "RECEIVED", (
            "filing moves the award's reporting status to received"
        )

        validate_error(
            api_client.create_final_report(
                {
                    "award_id": ctx.aw,
                    "narrative": "A duplicate filing.",
                    "public_value_statement": "Duplicate.",
                    "audience_reached_count": 1,
                    "expenditure_summary": "Duplicate.",
                },
                ctx.art_headers,
            ),
            "ERR_DUPLICATE_FINAL_REPORT",
        )

        first_revision = validate_success(
            api_client.review_final_report(
                report["id"],
                {
                    "decision": "REQUEST_REVISION",
                    "revision_note": "Please itemise the expenditure summary by quarter.",
                },
                PROGRAM_OFFICER,
            )
        )
        assert first_revision["status"] == "REVISION_REQUESTED", (
            f"the report goes back for revision, got {first_revision['status']}"
        )
        assert first_revision["revision_count"] == 1, (
            f"the first revision is counted, got {first_revision['revision_count']}"
        )

        resubmitted = validate_success(
            api_client.resubmit_final_report(
                report["id"],
                {
                    "narrative": "Revised narrative with quarterly detail.",
                    "public_value_statement": "Four free readings in county libraries.",
                    "audience_reached_count": 320,
                    "expenditure_summary": "Q1 materials, Q2 travel, Q3 childcare, Q4 printing.",
                },
                ctx.art_headers,
            )
        )
        assert resubmitted["status"] == "SUBMITTED", (
            f"the resubmission returns to submitted, got {resubmitted['status']}"
        )

        validate_error(
            api_client.resubmit_final_report(
                report["id"],
                {
                    "narrative": "A second resubmission with nothing requested.",
                    "public_value_statement": "Four free readings in county libraries.",
                    "audience_reached_count": 320,
                    "expenditure_summary": "Unchanged.",
                },
                ctx.art_headers,
            ),
            "ERR_FINAL_REPORT_STATE_INVALID",
        )

        second_revision = validate_success(
            api_client.review_final_report(
                report["id"],
                {
                    "decision": "REQUEST_REVISION",
                    "revision_note": "Please add the audience methodology in an appendix.",
                },
                PROGRAM_OFFICER,
            )
        )
        assert second_revision["revision_count"] == 2, (
            f"the second revision is counted, got {second_revision['revision_count']}"
        )
        validate_success(
            api_client.resubmit_final_report(
                report["id"],
                {
                    "narrative": "Revised narrative with the methodology appendix.",
                    "public_value_statement": "Four free readings in county libraries.",
                    "audience_reached_count": 320,
                    "expenditure_summary": "Q1 materials, Q2 travel, Q3 childcare, Q4 printing.",
                },
                ctx.art_headers,
            )
        )
        validate_error(
            api_client.review_final_report(
                report["id"],
                {
                    "decision": "REQUEST_REVISION",
                    "revision_note": "One further revision beyond the declared maximum.",
                },
                PROGRAM_OFFICER,
            ),
            "ERR_MAX_REVISIONS_REACHED",
        )

        accepted = validate_success(
            api_client.review_final_report(
                report["id"], {"decision": "ACCEPT"}, PROGRAM_OFFICER
            )
        )
        assert accepted["status"] == "ACCEPTED", (
            f"acceptance is terminal for a report, got {accepted['status']}"
        )
        award = read_award(ctx.aw)
        assert award["reporting_status"] == "ACCEPTED", (
            f"the award's reporting dimension follows, got {award['reporting_status']}"
        )
        assert award["status"] == "COMPLETED", (
            "a fully paid award completes on acceptance, got "
            f"{award['status']}"
        )

        artist = read_artist(ctx.art)
        assert artist["active_award_count"] == 0, (
            f"the completed award is no longer active, got {artist['active_award_count']}"
        )
        assert artist["prior_award_count"] == 1, (
            f"completion writes the award history, got {artist['prior_award_count']}"
        )
        assert artist["last_award_fiscal_year"] == 2027, (
            f"the cycle's fiscal year is recorded, got {artist['last_award_fiscal_year']}"
        )
        assert str(artist["last_award_period_end"]).startswith("2027-12-31"), (
            f"the grant period end is recorded, got {artist['last_award_period_end']}"
        )


class TestAppealFamily:
    """One struck application, five appeal codes and two opposite paths."""

    def test_the_window_the_grounds_and_the_remedy_map_each_refuse_in_turn(self):
        """
        A filing one day past the thirty-day window is refused while the thirtieth day itself is
        admitted; a substantive appeal cannot be screened but can be denied straight from filed,
        and a denied appeal no longer blocks a new filing while a live one does; the procedural
        appeal cannot be decided before screening nor upheld with the wrong remedy, and the
        permitted remedy unwinds the scoring.

        PRD: "The filing window is temporal: the application's `notified_at` must be set — the
        applicant must actually have been notified — and the logical clock must fall within the
        cycle's `appeal_window_days` of that instant, the window boundary itself being
        inclusive; a filing that is too early or too late is rejected with
        `ERR_APPEAL_WINDOW_CLOSED`."

        PRD: "An `AppealsOfficer` screens a filed appeal for procedural jurisdiction, moving it
        `FILED → SCREENED` and stamping `screened_by`; an attempt to screen an appeal citing
        `SUBSTANTIVE_SCORE_DISAGREEMENT` is rejected with `ERR_NON_PROCEDURAL_APPEAL_GROUNDS`,
        and screening an appeal that is not `FILED` is rejected with `ERR_APPEAL_STATE_INVALID`."

        PRD: "Only one live appeal may exist per application: a second filing while an existing
        appeal is anything other than `DENIED` is rejected with `ERR_DUPLICATE_APPEAL`."

        PRD: "A remedy outside the permitted set, or a missing one, is rejected with
        `ERR_REMEDY_NOT_PERMITTED_FOR_GROUNDS`."

        Design: Corner/errors/appeal_family_from_the_window_through_the_remedy_map
        """
        ctx = cornermain_slate_submitted()
        _strike_the_only_slot(ctx)
        assert str(read_application(ctx.app)["notified_at"]).startswith("2026-10-16"), (
            "the strike notifies the applicant and opens the window"
        )

        set_clock("2026-11-16T00:00:00Z")
        validate_error(
            api_client.create_appeal(
                {
                    "application_id": ctx.app,
                    "grounds_code": "SCORING_PROCEDURE_DEFECT",
                    "statement": "The panel did not record a second-round score.",
                },
                ctx.art_headers,
            ),
            "ERR_APPEAL_WINDOW_CLOSED",
        )

        set_clock("2026-11-15T00:00:00Z")
        substantive = validate_success(
            api_client.create_appeal(
                {
                    "application_id": ctx.app,
                    "grounds_code": "SUBSTANTIVE_SCORE_DISAGREEMENT",
                    "statement": "The panel undervalued the manuscript.",
                },
                ctx.art_headers,
            ),
            expected_status=201,
        )
        assert substantive["status"] == "FILED", (
            f"the thirtieth day is inside the window, got {substantive['status']}"
        )
        assert substantive["filed_by_artist_id"] == ctx.art, (
            "the appellant is copied from the application, got "
            f"{substantive['filed_by_artist_id']}"
        )

        validate_error(
            api_client.screen_appeal(substantive["id"], APPEALS_OFFICER),
            "ERR_NON_PROCEDURAL_APPEAL_GROUNDS",
        )
        assert (
            validate_success(api_client.get_appeal(substantive["id"], APPEALS_OFFICER))[
                "status"
            ]
            == "FILED"
        ), "the refused screening leaves the appeal filed"

        denied = validate_success(
            api_client.decide_appeal(
                substantive["id"], {"decision": "DENY"}, APPEALS_OFFICER
            )
        )
        assert denied["status"] == "DENIED", (
            f"a substantive appeal is denied straight from filed, got {denied['status']}"
        )
        assert denied["screened_by"] is None, (
            f"the denial skipped screening, got {denied['screened_by']}"
        )

        procedural = validate_success(
            api_client.create_appeal(
                {
                    "application_id": ctx.app,
                    "grounds_code": "SCORING_PROCEDURE_DEFECT",
                    "statement": "The panel did not record a second-round score.",
                },
                ctx.art_headers,
            ),
            expected_status=201,
        )
        validate_error(
            api_client.create_appeal(
                {
                    "application_id": ctx.app,
                    "grounds_code": "CONFLICT_NOT_MANAGED",
                    "statement": "A third filing while the second is open.",
                },
                ctx.art_headers,
            ),
            "ERR_DUPLICATE_APPEAL",
        )

        validate_error(
            api_client.decide_appeal(
                procedural["id"],
                {"decision": "UPHOLD", "remedy_code": "RESCORE_BY_NEW_PANEL"},
                APPEALS_OFFICER,
            ),
            "ERR_APPEAL_STATE_INVALID",
        )
        screened = validate_success(
            api_client.screen_appeal(procedural["id"], APPEALS_OFFICER)
        )
        assert screened["status"] == "SCREENED", (
            f"a procedural appeal is screened first, got {screened['status']}"
        )

        validate_error(
            api_client.decide_appeal(
                procedural["id"],
                {"decision": "UPHOLD", "remedy_code": "REISSUE_SLATE"},
                APPEALS_OFFICER,
            ),
            "ERR_REMEDY_NOT_PERMITTED_FOR_GROUNDS",
        )
        upheld = validate_success(
            api_client.decide_appeal(
                procedural["id"],
                {"decision": "UPHOLD", "remedy_code": "RESCORE_BY_NEW_PANEL"},
                APPEALS_OFFICER,
            )
        )
        assert upheld["status"] == "UPHELD", (
            f"the permitted remedy is accepted, got {upheld['status']}"
        )
        assert upheld["decided_by"] == APPEALS_OFFICER_ID, (
            f"the deciding officer is stamped, got {upheld['decided_by']}"
        )

        panel = read_panel(ctx.pan)
        assert panel["status"] == "SCORING", (
            f"the panel returns to scoring, got {panel['status']}"
        )
        assert panel["round_number"] == 2, (
            f"the round number is incremented, got {panel['round_number']}"
        )
        assert panel["assigned_application_count"] == 0, (
            "the appellant application is detached, got "
            f"{panel['assigned_application_count']}"
        )

        application = read_application(ctx.app)
        assert application["status"] == "ELIGIBLE", (
            f"the application is returned to the pool, got {application['status']}"
        )
        assert application["assigned_panel_id"] is None, (
            f"its panel assignment is cleared, got {application['assigned_panel_id']}"
        )
        assert application["valid_review_count"] == 0, (
            f"no counted review remains, got {application['valid_review_count']}"
        )
        assert application["final_composite_score"] is None, (
            f"the composite reads null, got {application['final_composite_score']}"
        )
        for review in list_reviews_of(ctx.app):
            assert review["status"] == "INVALIDATED", (
                f"every submitted review is invalidated, got {review['status']}"
            )
            assert review["invalidation_reason"] == "APPEAL_REMEDY", (
                f"the reason names the remedy, got {review['invalidation_reason']}"
            )


class TestCompositionAppealReissuesTheSlate:
    """A struck slot is not irreversibly terminal."""

    def test_the_reissued_slot_returns_to_proposed_and_can_then_be_approved(self):
        """
        Upholding a composition appeal with the reissue remedy restores the struck slot to
        proposed with its board fields cleared and the application back to scored without
        touching a single review, and the board can then approve the very same slot.

        PRD: "`REISSUE_SLATE` reopens the board's decision."

        PRD: "The application's recommendation slot, whether it sits in `VOIDED` or in
        `BOARD_STRUCK`, returns to `PROPOSED` with its `board_action_by` and
        `struck_reason_code` cleared, and the application returns `NOT_RECOMMENDED → SCORED`."

        Design: Corner/errors/upheld_composition_appeal_reissues_the_struck_slate
        """
        ctx = cornermain_slate_submitted()
        _strike_the_only_slot(ctx)
        appeal = validate_success(
            api_client.create_appeal(
                {
                    "application_id": ctx.app,
                    "grounds_code": "PANEL_COMPOSITION_DEFECT",
                    "statement": "The panel seated no reader from my region.",
                },
                ctx.art_headers,
            ),
            expected_status=201,
        )
        validate_success(api_client.screen_appeal(appeal["id"], APPEALS_OFFICER))

        decided = validate_success(
            api_client.decide_appeal(
                appeal["id"],
                {"decision": "UPHOLD", "remedy_code": "REISSUE_SLATE"},
                APPEALS_OFFICER,
            )
        )
        assert decided["status"] == "UPHELD", (
            f"composition defects permit either remedy, got {decided['status']}"
        )
        assert decided["remedy_code"] == "REISSUE_SLATE", (
            f"the remedy is recorded, got {decided['remedy_code']}"
        )

        slot = _read_slot(ctx.slot)
        assert slot["status"] == "PROPOSED", (
            f"the struck slot is reissued, got {slot['status']}"
        )
        assert slot["board_action_by"] is None, (
            f"the acting board member is cleared, got {slot['board_action_by']}"
        )
        assert slot["struck_reason_code"] is None, (
            f"the strike reason is cleared, got {slot['struck_reason_code']}"
        )
        assert slot["awarded_amount_cents"] is None, (
            f"a proposed slot carries no amount, got {slot['awarded_amount_cents']}"
        )

        application = read_application(ctx.app)
        assert application["status"] == "SCORED", (
            f"the application returns to scored, got {application['status']}"
        )
        assert_score(
            application["final_composite_score"], 7.30, "application.final_composite_score"
        )
        for review in list_reviews_of(ctx.app):
            assert review["status"] == "SUBMITTED", (
                f"this remedy invalidates no review, got {review['status']}"
            )

        approved = validate_success(
            api_client.board_action(
                ctx.slot,
                {"action": "APPROVE", "expected_cycle_version": cycle_version(ctx.cyc)},
                BOARD_MEMBER,
            )
        )
        assert_cents(
            approved["awarded_amount_cents"], 1_500_000, "slot.awarded_amount_cents"
        )
        award = read_award(award_id_for_application(ctx.app))
        assert award["status"] == "OFFERED", (
            f"a new award begins offered, got {award['status']}"
        )
        assert award["payment_status"] == "UNPAID", (
            f"nothing is paid yet, got {award['payment_status']}"
        )
        assert award["reporting_status"] == "NOT_DUE", (
            f"no report is due yet, got {award['reporting_status']}"
        )
