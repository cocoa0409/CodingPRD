"""
The payment schedule, the award's three independent dimensions, disbursement gates
and the compensations that unwind or replace money already committed.
"""

from test_helpers import (
    BOARD_MEMBER,
    FISCAL_OFFICER,
    FISCAL_OFFICER_ID,
    PROGRAM_OFFICER,
    api_client,
    assert_cents,
    assert_gross_conservation,
    assert_installment,
    assert_net_identity,
    assert_rate,
    award_id_for_application,
    cycle_version,
    cyclemain_award_accepted,
    cyclemain_cycle_awarded,
    cyclemain_installment_one_paid,
    cyclemain_two_applications_slated,
    final_report_payload,
    list_installments_of,
    read_application,
    read_artist,
    read_award,
    read_cycle,
    read_discipline,
    set_clock,
    validate_error,
    validate_success,
)


class TestPerInstallmentWithholding:
    """The rate is applied to each installment separately, never to the total."""

    def test_the_three_installments_carry_their_own_rounded_withholding(self):
        """
        A 1,500,000-cent award to an artist with no taxpayer identification splits into
        600,000, 525,000 and 375,000 and withholds 162,420, 142,118 and 101,513 at 0.2707,
        each netting down independently and each dated from the grant period start.

        PRD: "That per-installment rounding order is not incidental. On a gross of
        1,500,000 cents with no taxpayer identification on file, the three gross figures
        are 600,000, 525,000 and 375,000; the three withholding figures are 162,420,
        142,118 and 101,513, summing to 406,051; and the three nets are 437,580, 382,882
        and 273,487, summing to 1,093,949."

        Design: Difficulty/combinatorial_formula/award_withholding_rounded_per_installment_not_on_the_total
        """
        ctx = cyclemain_award_accepted()
        installments = ctx.installments

        assert [row["installment_number"] for row in installments] == [1, 2, 3], (
            "exactly three installments should exist in number order, got "
            f"{[row['installment_number'] for row in installments]}"
        )
        expected = (
            (1, 600_000, 162_420, 437_580, "2027-01-01"),
            (2, 525_000, 142_118, 382_882, "2027-05-01"),
            (3, 375_000, 101_513, 273_487, "2027-08-29"),
        )
        for row, (number, gross, withholding, net, scheduled) in zip(installments, expected):
            assert_installment(
                row,
                installment_number=number,
                gross_cents=gross,
                withholding_rate=0.2707,
                withholding_cents=withholding,
                net_cents=net,
                scheduled_date=scheduled,
            )
            assert_net_identity(row)
            assert row["status"] == "SCHEDULED", (
                f"a fresh installment should be SCHEDULED, got {row['status']}"
            )
        assert sum(row["gross_cents"] for row in installments) == 1_500_000, (
            "the three gross figures must sum to the award gross exactly"
        )

    def test_the_award_totals_the_rounded_parts_rather_than_rounding_the_total(self):
        """
        The award's scheduled withholding is the sum of the three rounded parts, 406,051 —
        one cent above the 406,050 that rounding the whole gross against the rate once
        would give — and the whole gross is still undisbursed against a report due after a
        leap February.

        PRD: "Rounding the whole gross against the rate just once would yield 406,050 — a
        one-cent divergence that the per-installment order is required to produce."

        Design: Difficulty/combinatorial_formula/award_withholding_rounded_per_installment_not_on_the_total
        """
        ctx = cyclemain_award_accepted()
        award = read_award(ctx.aw1)

        assert_cents(
            award["scheduled_withholding_cents"], 406_051, "award.scheduled_withholding_cents"
        )
        assert award["scheduled_withholding_cents"] != 406_050, (
            "406,050 is the forbidden single-rounding reading"
        )
        assert_cents(
            award["undisbursed_gross_cents"], 1_500_000, "award.undisbursed_gross_cents"
        )
        assert str(award["final_report_due_at"]).startswith("2028-02-29"), (
            "the report falls due 60 days after a 2027-12-31 grant period end, got "
            f"{award['final_report_due_at']}"
        )


class TestAwardDimensionsDiverge:
    """Agreement status, payment status and reporting status move independently."""

    def test_one_payment_puts_the_three_dimensions_on_three_different_values(self):
        """
        Paying the first installment activates the award, marks it partially paid and
        leaves the reporting obligation not yet due, with the ledger showing only the
        first installment's gross and net disbursed.

        PRD: "The award's `payment_status` is re-derived on every installment write as its
        own independent dimension, and it moves in both directions."

        Design: Difficulty/non_linear_state_machine/award_agreement_payment_and_reporting_dimensions_diverge
        """
        ctx = cyclemain_installment_one_paid()
        award = read_award(ctx.aw1)

        assert award["status"] == "ACTIVE", (
            f"the first payment moves ACCEPTED -> ACTIVE, got {award['status']}"
        )
        assert award["payment_status"] == "PARTIALLY_PAID", (
            f"one of three installments is paid, got {award['payment_status']}"
        )
        assert award["reporting_status"] == "NOT_DUE", (
            "the grant period has not ended, so nothing is owed yet, got "
            f"{award['reporting_status']}"
        )
        assert_cents(award["disbursed_gross_cents"], 600_000, "award.disbursed_gross_cents")
        assert_cents(award["disbursed_net_cents"], 437_580, "award.disbursed_net_cents")
        assert_cents(
            award["undisbursed_gross_cents"], 900_000, "award.undisbursed_gross_cents"
        )

    def test_the_reporting_dimension_falls_due_on_its_own(self):
        """
        Advancing the clock past the grant period end moves the reporting dimension from
        NOT_DUE to DUE without touching either of the other two, and reports no delinquency
        yet.

        PRD: "Second, an award in `ACCEPTED` or `ACTIVE` whose `grant_period_end` now lies
        in the past moves its `reporting_status` from `NOT_DUE` to `DUE`."

        Design: Difficulty/non_linear_state_machine/award_agreement_payment_and_reporting_dimensions_diverge
        """
        ctx = cyclemain_installment_one_paid()

        checkpoint = set_clock("2028-01-01T00:00:00Z")
        assert ctx.aw1 not in checkpoint["delinquent_award_ids"], (
            "the report is due but not yet late, so no delinquency should be reported"
        )

        award = read_award(ctx.aw1)
        assert award["reporting_status"] == "DUE", (
            f"reporting_status should move NOT_DUE -> DUE, got {award['reporting_status']}"
        )
        assert award["status"] == "ACTIVE", (
            f"the agreement dimension is unmoved, got {award['status']}"
        )
        assert award["payment_status"] == "PARTIALLY_PAID", (
            f"the payment dimension is unmoved, got {award['payment_status']}"
        )

    def test_delinquency_holds_the_remaining_installments_until_the_report_lands(self):
        """
        Letting the report deadline pass makes the award delinquent, puts its artist out of
        good standing and holds only the still-scheduled installments; filing the report
        returns all three to their prior condition while the agreement and payment
        dimensions never move.

        PRD: "Filing moves the award's `reporting_status` from `DUE` or from `DELINQUENT`
        to `RECEIVED`; where the award had been `DELINQUENT`, filing also decrements the
        artist's `delinquent_award_count`, returns the artist's `standing` to
        `GOOD_STANDING` once that count reaches 0 and the artist is not `DEBARRED`, and
        returns every `HELD` installment of that award whose `hold_reason_code` is
        `REPORT_DELINQUENT` to `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/award_agreement_payment_and_reporting_dimensions_diverge
        """
        ctx = cyclemain_installment_one_paid()
        set_clock("2028-01-01T00:00:00Z")

        checkpoint = set_clock("2028-03-01T00:00:00Z")
        assert ctx.aw1 in checkpoint["delinquent_award_ids"], (
            "the overdue award should be named in delinquent_award_ids"
        )
        held = list_installments_of(ctx.aw1)
        for row in held:
            if row["installment_number"] in (2, 3):
                assert row["id"] in checkpoint["held_installment_ids"], (
                    f"installment {row['installment_number']} should be named in "
                    "held_installment_ids"
                )
                assert row["status"] == "HELD", (
                    f"installment {row['installment_number']} should be HELD, got {row['status']}"
                )
                assert row["hold_reason_code"] == "REPORT_DELINQUENT", (
                    f"the hold should name the delinquency, got {row['hold_reason_code']}"
                )
            else:
                assert row["status"] == "PAID", (
                    f"the paid installment is untouched, got {row['status']}"
                )

        award = read_award(ctx.aw1)
        assert award["reporting_status"] == "DELINQUENT", (
            f"reporting_status should move DUE -> DELINQUENT, got {award['reporting_status']}"
        )
        assert award["status"] == "ACTIVE", "the agreement dimension is still ACTIVE"
        assert award["payment_status"] == "PARTIALLY_PAID", (
            "the payment dimension is still PARTIALLY_PAID"
        )
        artist = read_artist(ctx.art1)
        assert artist["standing"] == "REPORT_DELINQUENT", (
            f"the artist should lose good standing, got {artist['standing']}"
        )
        assert artist["delinquent_award_count"] == 1, (
            f"the delinquent award should be counted, got {artist['delinquent_award_count']}"
        )

        validate_success(
            api_client.create_final_report(
                final_report_payload(ctx.aw1), ctx.art1_headers
            ),
            expected_status=201,
        )

        award = read_award(ctx.aw1)
        assert award["reporting_status"] == "RECEIVED", (
            f"filing should move the reporting dimension to RECEIVED, got {award['reporting_status']}"
        )
        assert award["status"] == "ACTIVE", (
            "the agreement dimension never moved across the reporting walk"
        )
        assert award["payment_status"] == "PARTIALLY_PAID", (
            "the payment dimension never moved across the reporting walk"
        )
        for row in list_installments_of(ctx.aw1):
            if row["installment_number"] in (2, 3):
                assert row["status"] == "SCHEDULED", (
                    f"the held installment should be released back to SCHEDULED, got {row['status']}"
                )
                assert row["hold_reason_code"] is None, (
                    f"the hold reason should be cleared, got {row['hold_reason_code']}"
                )
        artist = read_artist(ctx.art1)
        assert artist["standing"] == "GOOD_STANDING", (
            f"the artist should return to good standing, got {artist['standing']}"
        )
        assert artist["delinquent_award_count"] == 0, (
            f"the delinquency count should return to 0, got {artist['delinquent_award_count']}"
        )


class TestRescissionUnwinding:
    """Rescinding an undisbursed award must leave no trace in the ledger."""

    def test_rescission_voids_every_installment_and_zeroes_the_award_ledger(self):
        """
        Rescinding an accepted award before any money has moved voids all three scheduled
        installments and empties the award's own withholding and undisbursed figures.

        PRD: "Rescission from `ACCEPTED` additionally voids every installment in
        `SCHEDULED` or `HELD` and resets `scheduled_withholding_cents` and
        `undisbursed_gross_cents` to 0."

        Design: Difficulty/transitive_cascade/award_rescission_unwinds_installments_slot_ledger_and_artist_counters
        """
        ctx = cyclemain_cycle_awarded()

        rescinded = validate_success(
            api_client.rescind_award(ctx.aw1, "INELIGIBILITY_DISCOVERED", PROGRAM_OFFICER)
        )
        assert rescinded["status"] == "RESCINDED", (
            f"the award should move ACCEPTED -> RESCINDED, got {rescinded['status']}"
        )
        assert rescinded["rescind_reason_code"] == "INELIGIBILITY_DISCOVERED", (
            f"the reason should be recorded, got {rescinded['rescind_reason_code']}"
        )
        assert_cents(
            rescinded["scheduled_withholding_cents"],
            0,
            "award.scheduled_withholding_cents",
        )
        assert_cents(
            rescinded["undisbursed_gross_cents"], 0, "award.undisbursed_gross_cents"
        )

        statuses = [row["status"] for row in list_installments_of(ctx.aw1)]
        assert statuses == ["VOIDED"] * 3, (
            f"all three installments should be VOIDED, got {statuses}"
        )

    def test_rescission_returns_the_slot_application_counters_and_appropriation(self):
        """
        The same rescission voids the board-approved slot, returns the application to
        NOT_AWARDED with a fresh notification, clears the artist's and the discipline's
        award counters without crediting any history, and drives the cycle's whole fiscal
        block back to zero against an already-released reserve.

        PRD: "In every rescission the application becomes `NOT_AWARDED` with `notified_at`
        re-stamped, the slot becomes `VOIDED`, the artist's `active_award_count` is
        decremented, and the discipline and cycle fiscal fields and posture are recomputed
        exactly as for a decline."

        Design: Difficulty/transitive_cascade/award_rescission_unwinds_installments_slot_ledger_and_artist_counters
        """
        ctx = cyclemain_cycle_awarded()
        validate_success(
            api_client.rescind_award(ctx.aw1, "INELIGIBILITY_DISCOVERED", PROGRAM_OFFICER)
        )

        slot = validate_success(api_client.get_slot(ctx.slot1, BOARD_MEMBER))
        assert slot["status"] == "VOIDED", (
            f"the board-approved slot should be VOIDED, got {slot['status']}"
        )

        application = read_application(ctx.app1)
        assert application["status"] == "NOT_AWARDED", (
            f"the application should move AWARDED -> NOT_AWARDED, got {application['status']}"
        )
        assert str(application["notified_at"]).startswith("2026-10-16"), (
            f"notified_at should be re-stamped from the logical clock, got {application['notified_at']}"
        )

        artist = read_artist(ctx.art1)
        assert artist["active_award_count"] == 0, (
            f"active_award_count should return to 0, got {artist['active_award_count']}"
        )
        assert artist["prior_award_count"] == 0, (
            f"a rescinded award never becomes history, got {artist['prior_award_count']}"
        )

        discipline = read_discipline(ctx.disc)
        assert_cents(discipline["committed_cents"], 0, "discipline.committed_cents")
        assert discipline["funded_application_count"] == 0, (
            f"funded_application_count should return to 0, got {discipline['funded_application_count']}"
        )
        assert discipline["eligible_application_count"] == 1, (
            "the application remains one of the discipline's eligible files, got "
            f"{discipline['eligible_application_count']}"
        )

        cycle = read_cycle(ctx.cyc)
        assert_cents(cycle["funded_total_cents"], 0, "cycle.funded_total_cents")
        assert_rate(cycle["admin_assessment_rate"], 0.0, "cycle.admin_assessment_rate")
        assert_cents(cycle["admin_assessment_cents"], 0, "cycle.admin_assessment_cents")
        assert_cents(cycle["committed_cents"], 0, "cycle.committed_cents")
        assert_cents(cycle["reserve_cents"], 0, "cycle.reserve_cents")
        assert_cents(cycle["available_cents"], 6_000_000, "cycle.available_cents")
        assert cycle["posture"] == "OPEN", (
            f"nothing holds the cycle back, so the posture is OPEN, got {cycle['posture']}"
        )


class TestReleaseRejectionOrder:
    """A frozen cycle is reported before an installment that is merely early."""

    def test_the_frozen_posture_is_reported_ahead_of_the_due_date(self):
        """
        With both the posture rule and the due-date rule violated, the release names the
        freeze; redacting the breach leaves only the temporal violation and the identical
        call then names the due date, with the installment untouched throughout.

        PRD: "When a request violates more than one rule, exactly one error is reported,
        and which one is normative. Checks are evaluated in this fixed order, and the first
        violation wins:"

        PRD: "**Cross-entity state and cycle posture** — the owning cycle, panel, award or
        artist is in the state the operation requires, and the cycle's posture permits it."

        PRD: "**Business temporal** — deadlines, windows and overlaps."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_p70_outranks_installment_not_due_p80
        """
        ctx = cyclemain_award_accepted()
        validate_success(
            api_client.screen_work_sample(ctx.ws1a, "FLAGGED_IDENTIFYING", PROGRAM_OFFICER)
        )
        validate_success(api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER))

        cycle = read_cycle(ctx.cyc)
        assert cycle["posture"] == "FROZEN", (
            f"the breach should have frozen the cycle, got {cycle['posture']}"
        )
        validate_error(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER),
            "ERR_CYCLE_POSTURE_FROZEN",
        )

        validate_success(api_client.redact_work_sample(ctx.ws1a, PROGRAM_OFFICER))
        validate_error(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER),
            "ERR_INSTALLMENT_NOT_DUE",
        )

        installment = validate_success(
            api_client.get_installment(ctx.inst1, FISCAL_OFFICER)
        )
        assert installment["status"] == "SCHEDULED", (
            f"the installment should still be SCHEDULED, got {installment['status']}"
        )
        assert installment["released_by"] is None, (
            "released_by must stay null through both rejections"
        )
        assert installment["released_at"] is None, (
            "released_at must stay null through both rejections"
        )

    def test_the_identical_release_succeeds_once_the_scheduled_date_arrives(self):
        """
        Once the breach is repaired and the clock reaches the installment's scheduled date,
        the unchanged release call succeeds.

        PRD: "Either of the last two failures is reported as `ERR_INSTALLMENT_NOT_DUE`:
        installments are released in order and never early."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_p70_outranks_installment_not_due_p80
        """
        ctx = cyclemain_award_accepted()
        validate_success(
            api_client.screen_work_sample(ctx.ws1a, "FLAGGED_IDENTIFYING", PROGRAM_OFFICER)
        )
        validate_success(api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER))
        validate_success(api_client.redact_work_sample(ctx.ws1a, PROGRAM_OFFICER))
        validate_error(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER),
            "ERR_INSTALLMENT_NOT_DUE",
        )

        set_clock("2027-01-01T00:00:00Z")
        released = validate_success(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER)
        )
        assert released["status"] == "RELEASED", (
            f"the installment should move SCHEDULED -> RELEASED, got {released['status']}"
        )


class TestReleaseNeedsTheCycleAwarded:
    """The gate lives two levels up the chain, on the cycle."""

    def test_a_due_installment_on_an_accepted_award_still_waits_for_the_cycle(self):
        """
        Every local precondition holds — the award is accepted, the installment scheduled,
        the acting officer is not the approver and the scheduled date has arrived — yet the
        cycle is still in board review, so the money does not move.

        PRD: "It requires the cycle to be in `AWARDED`, otherwise
        `ERR_CYCLE_STATE_INVALID`; the cycle's `posture` not to be `FROZEN`, otherwise
        `ERR_CYCLE_POSTURE_FROZEN`; the award's `status` to be `ACCEPTED` or `ACTIVE`,
        otherwise `ERR_AWARD_STATE_INVALID`; the acting officer's `X-User-ID` to differ
        from the award's `approved_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; the
        logical clock to be at or after the installment's `scheduled_date`; and every
        installment of the award with a lower `installment_number` to have already left
        `SCHEDULED` and `HELD` — that is, to be `PAID`, `RELEASED`, `VOIDED` or
        `REVERSED`."

        Design: Difficulty/cross_entity_state_dependency/installment_release_gated_on_the_cycle_reaching_awarded
        """
        ctx = cyclemain_award_accepted()
        set_clock("2027-01-01T00:00:00Z")

        assert read_award(ctx.aw1)["status"] == "ACCEPTED", (
            "the award itself is in a releasable state"
        )
        assert read_cycle(ctx.cyc)["status"] == "BOARD_REVIEW", (
            "the grandparent cycle has not yet been awarded"
        )

        validate_error(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER),
            "ERR_CYCLE_STATE_INVALID",
        )
        installment = validate_success(
            api_client.get_installment(ctx.inst1, FISCAL_OFFICER)
        )
        assert installment["status"] == "SCHEDULED", (
            f"the installment should stay SCHEDULED, got {installment['status']}"
        )
        assert installment["released_by"] is None, "released_by must stay null"
        assert installment["released_at"] is None, "released_at must stay null"

    def test_moving_the_cycle_to_awarded_lets_the_same_release_through_unpaid(self):
        """
        Advancing the cycle to AWARDED lets the identical release succeed and stamps the
        acting fiscal officer, but nothing has been disbursed: the award is still unpaid
        with its whole gross undisbursed.

        PRD: "**Release** moves an installment `SCHEDULED → RELEASED` and stamps
        `released_by` and `released_at`."

        Design: Difficulty/cross_entity_state_dependency/installment_release_gated_on_the_cycle_reaching_awarded
        """
        ctx = cyclemain_award_accepted()
        set_clock("2027-01-01T00:00:00Z")
        validate_error(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER),
            "ERR_CYCLE_STATE_INVALID",
        )

        validate_success(api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER))
        released = validate_success(
            api_client.release_installment(ctx.inst1, FISCAL_OFFICER)
        )
        assert released["status"] == "RELEASED", (
            f"the identical call should now succeed, got {released['status']}"
        )
        assert released["released_by"] == FISCAL_OFFICER_ID, (
            f"released_by should name the acting officer, got {released['released_by']}"
        )

        award = read_award(ctx.aw1)
        assert award["payment_status"] == "UNPAID", (
            f"releasing is not paying, got {award['payment_status']}"
        )
        assert_cents(award["disbursed_gross_cents"], 0, "award.disbursed_gross_cents")
        assert_cents(
            award["undisbursed_gross_cents"], 1_500_000, "award.undisbursed_gross_cents"
        )


class TestReversalConservesGross:
    """A reversal replaces the row rather than shrinking the award."""

    def test_the_replacement_row_copies_the_money_and_takes_the_clock_date(self):
        """
        Reversing the paid first installment leaves it REVERSED with its payment instant
        intact and creates exactly one replacement carrying the same number, gross,
        withholding rate, withholding and net, scheduled from the logical clock, so the
        award's gross is still conserved across its live rows.

        PRD: "A replacement installment is then created in `SCHEDULED` with the same
        `installment_number`, `gross_cents`, `withholding_rate`, `withholding_cents` and
        `net_cents` as the reversed row, with `replaces_installment_id` pointing at the
        reversed row, and with `scheduled_date` set to the logical-clock date."

        Design: Difficulty/compensating_invariant/reversed_payment_conserves_award_gross_through_a_replacement_row
        """
        ctx = cyclemain_installment_one_paid()

        validate_success(
            api_client.reverse_installment(ctx.inst1, "BANK_RETURN", FISCAL_OFFICER)
        )

        reversed_row = validate_success(
            api_client.get_installment(ctx.inst1, FISCAL_OFFICER)
        )
        assert reversed_row["status"] == "REVERSED", (
            f"the paid installment should move to REVERSED, got {reversed_row['status']}"
        )
        assert reversed_row["reversal_reason_code"] == "BANK_RETURN", (
            f"the reason should be recorded, got {reversed_row['reversal_reason_code']}"
        )
        assert str(reversed_row["paid_at"]).startswith("2027-01-01"), (
            f"the reversed row keeps its paid_at, got {reversed_row['paid_at']}"
        )

        rows = list_installments_of(ctx.aw1)
        assert len(rows) == 4, (
            f"the award should now list four installment rows, got {len(rows)}"
        )
        replacements = [row for row in rows if row["replaces_installment_id"] == ctx.inst1]
        assert len(replacements) == 1, (
            f"exactly one replacement should exist, got {len(replacements)}"
        )
        replacement = replacements[0]
        assert replacement["status"] == "SCHEDULED", (
            f"the replacement begins SCHEDULED, got {replacement['status']}"
        )
        assert_installment(
            replacement,
            installment_number=1,
            gross_cents=600_000,
            withholding_rate=0.2707,
            withholding_cents=162_420,
            net_cents=437_580,
            scheduled_date="2027-01-01",
        )
        assert_gross_conservation(read_award(ctx.aw1), rows)

    def test_the_reversal_empties_the_disbursed_ledger_without_deactivating_the_award(self):
        """
        With no installment left paid, the payment dimension falls back to UNPAID and the
        disbursed figures return to zero with the whole gross undisbursed again, while the
        award itself stays ACTIVE.

        PRD: "And it goes back from `PARTIALLY_PAID` to `UNPAID` when no installment of the
        award remains `PAID`, at which point `disbursed_gross_cents`, `disbursed_net_cents`
        and `total_withholding_cents` all return to 0."

        Design: Difficulty/compensating_invariant/reversed_payment_conserves_award_gross_through_a_replacement_row
        """
        ctx = cyclemain_installment_one_paid()
        before = read_award(ctx.aw1)
        assert before["payment_status"] == "PARTIALLY_PAID", (
            f"one payment makes the award partially paid, got {before['payment_status']}"
        )
        assert_cents(before["disbursed_gross_cents"], 600_000, "award.disbursed_gross_cents")

        validate_success(
            api_client.reverse_installment(ctx.inst1, "BANK_RETURN", FISCAL_OFFICER)
        )

        award = read_award(ctx.aw1)
        assert award["payment_status"] == "UNPAID", (
            f"no installment remains paid, got {award['payment_status']}"
        )
        assert_cents(award["disbursed_gross_cents"], 0, "award.disbursed_gross_cents")
        assert_cents(award["disbursed_net_cents"], 0, "award.disbursed_net_cents")
        assert_cents(
            award["undisbursed_gross_cents"], 1_500_000, "award.undisbursed_gross_cents"
        )
        assert award["status"] == "ACTIVE", (
            f"a reversal does not walk the award back to ACCEPTED, got {award['status']}"
        )


class TestCoolingBuffer:
    """Exactly 365 days of daylight between grant periods is enough."""

    def test_a_gap_of_364_days_refuses_the_approval_and_leaves_the_slot_proposed(self):
        """
        An artist whose previous grant period ended on 2 January 2026 is 364 days short of
        the new period's 1 January 2027 start, so the board's approval of their rank-1 slot
        is refused and nothing at all is committed.

        PRD: "And the artist must clear the grant-period cooling buffer: either the
        artist's `last_award_period_end` is `null`, or the cycle's `grant_period_start`
        falls at least 365 days after it, the boundary being inclusive so that a gap of
        exactly 365 days is permitted; a shorter gap is rejected with
        `ERR_AWARD_PERIOD_COOLING_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/award_period_cooling_buffer_at_exactly_365_days
        """
        ctx = cyclemain_two_applications_slated()
        validate_success(
            api_client.add_award_history(
                ctx.art1,
                {"fiscal_year": 2024, "grant_period_end": "2026-01-02T00:00:00Z"},
                PROGRAM_OFFICER,
            )
        )

        artist = read_artist(ctx.art1)
        assert str(artist["last_award_period_end"]).startswith("2026-01-02"), (
            f"the recorded history should set last_award_period_end, got {artist['last_award_period_end']}"
        )
        assert artist["prior_award_count"] == 1, (
            f"the recorded fellowship should be counted, got {artist['prior_award_count']}"
        )

        validate_error(
            api_client.board_action(
                ctx.slot1,
                {
                    "action": "APPROVE",
                    "expected_cycle_version": cycle_version(ctx.cyc, BOARD_MEMBER),
                },
                BOARD_MEMBER,
            ),
            "ERR_AWARD_PERIOD_COOLING_VIOLATION",
        )

        slot = validate_success(api_client.get_slot(ctx.slot1, BOARD_MEMBER))
        assert slot["status"] == "PROPOSED", (
            f"the refused slot stays PROPOSED, got {slot['status']}"
        )
        assert slot["awarded_amount_cents"] is None, (
            f"no amount should be recorded, got {slot['awarded_amount_cents']}"
        )
        assert read_application(ctx.app1)["status"] == "SCORED", (
            "the application should stay SCORED"
        )
        assert read_artist(ctx.art1)["active_award_count"] == 0, (
            "no award should have been created"
        )

    def test_a_gap_of_exactly_365_days_is_inside_the_closed_interval(self):
        """
        The rejected approval left the cycle's version untouched, so the board may strike
        rank 1 with the same version and go on to approve rank 2, whose artist cleared the
        buffer by exactly 365 days, funding the full base award out of the untouched
        allocation.

        PRD: "Both actions require the cycle to be in `BOARD_REVIEW`, otherwise
        `ERR_CYCLE_STATE_INVALID`, and require `expected_cycle_version` to equal the
        cycle's current `version`, otherwise `ERR_STALE_CYCLE_VERSION`."

        Design: Difficulty/resource_temporal_overlap/award_period_cooling_buffer_at_exactly_365_days
        """
        ctx = cyclemain_two_applications_slated()
        validate_success(
            api_client.add_award_history(
                ctx.art1,
                {"fiscal_year": 2024, "grant_period_end": "2026-01-02T00:00:00Z"},
                PROGRAM_OFFICER,
            )
        )
        validate_success(
            api_client.add_award_history(
                ctx.art2,
                {"fiscal_year": 2024, "grant_period_end": "2026-01-01T00:00:00Z"},
                PROGRAM_OFFICER,
            )
        )
        stale_version = cycle_version(ctx.cyc, BOARD_MEMBER)
        validate_error(
            api_client.board_action(
                ctx.slot1,
                {"action": "APPROVE", "expected_cycle_version": stale_version},
                BOARD_MEMBER,
            ),
            "ERR_AWARD_PERIOD_COOLING_VIOLATION",
        )

        struck = validate_success(
            api_client.board_action(
                ctx.slot1,
                {
                    "action": "STRIKE",
                    "struck_reason_code": "APPLICANT_INELIGIBLE",
                    "expected_cycle_version": stale_version,
                },
                BOARD_MEMBER,
            )
        )
        assert struck["status"] == "BOARD_STRUCK", (
            "the refused approval must not have bumped the cycle version, got "
            f"{struck['status']}"
        )
        struck_application = read_application(ctx.app1)
        assert struck_application["status"] == "NOT_RECOMMENDED", (
            f"the struck application should be NOT_RECOMMENDED, got {struck_application['status']}"
        )
        assert struck_application["notified_at"] is not None, (
            "the struck applicant should be notified"
        )

        validate_success(
            api_client.board_action(
                ctx.slot2,
                {
                    "action": "APPROVE",
                    "expected_cycle_version": cycle_version(ctx.cyc, BOARD_MEMBER),
                },
                BOARD_MEMBER,
            )
        )
        award = read_award(award_id_for_application(ctx.app2))
        assert_cents(award["gross_amount_cents"], 1_500_000, "award.gross_amount_cents")
        assert award["is_prorated"] is False, (
            "the whole allocation was still uncommitted, so nothing is prorated"
        )

        cycle = read_cycle(ctx.cyc)
        assert_cents(cycle["funded_total_cents"], 1_500_000, "cycle.funded_total_cents")
        assert_rate(cycle["admin_assessment_rate"], 0.085, "cycle.admin_assessment_rate")
        assert_cents(cycle["admin_assessment_cents"], 127_500, "cycle.admin_assessment_cents")
        assert_cents(cycle["available_cents"], 4_072_500, "cycle.available_cents")
        assert cycle["posture"] == "OPEN", (
            f"the cycle should remain OPEN, got {cycle['posture']}"
        )
