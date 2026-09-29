"""State machines that are neither linear nor single-axis.

The submission's primary axis is cyclic on the review loop and bounded by a
revision ceiling rather than by reachability, and the loop deliberately leaves the
credit ledger alone after the first escrow. The certification listing instead
carries two parallel axes on one row: they move on disjoint triggers, the
visibility axis cycles back through SUPPRESSED, and WITHDRAWN locks the row.
"""

from test_helpers import (
    CASE_OPEN,
    CASE_REMEDIATED,
    CASE_REMEDIATION_ORDERED,
    CASE_WITHDRAWAL_ORDERED,
    COMPLIANCE_NONCOMPLIANT,
    COMPLIANCE_REMEDIATED,
    COMPLIANCE_UNDER_INVESTIGATION,
    DAC_ISSUED,
    DAC_REVOKED,
    PUB_PUBLISHED,
    PUB_SUPPRESSED,
    PUB_WITHDRAWN,
    REVIEW_PENDING,
    REVIEW_RETURNED,
    SUB_IN_REVIEW,
    SUB_RETURNED_FOR_INFO,
    SUB_SUBMITTED,
    advance_case,
    assert_cents,
    assert_penalty,
    assert_states,
    build_program,
    get_success_data,
    new_case,
    plus_days,
    publish_listing,
    read_case,
    read_ledger,
    read_listing,
    read_member,
    read_submission,
    same_instant,
    set_clock,
    start_review,
    submit_submission,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INVALID_LISTING_STATE,
    ERR_INVALID_SUBMISSION_STATE,
    ERR_REVISION_LIMIT_EXCEEDED,
)
from test_helpers.factories import return_for_info_payload
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CONFORMANCE_REVIEWER_1,
    make_conformance_headers,
)

#: The instant every enforcement trigger of the listing scenario runs at.
TRIGGER_CLOCK = "2026-09-03T00:00:00Z"

#: LIGHTING base 120000 plus 15000 for each of the two declared codes plus an SB1
#: surcharge of nothing, undiscounted for an ADOPTER on the STANDARD track.
PINNED_FEE_CENTS = 150000
PURCHASED_CENTS = 1000000


def _return_for_info(submission_id, reason, reviewer_user_id=CONFORMANCE_REVIEWER_1):
    """The raw return-for-info response, so a refusal can be inspected."""
    return api_client.return_for_info(
        submission_id,
        return_for_info_payload(reason),
        make_conformance_headers(reviewer_user_id),
    )


def _returned_for_info(submission_id, reason, reviewer_user_id=CONFORMANCE_REVIEWER_1):
    """Return the submission for more information and expect it to be accepted."""
    return get_success_data(_return_for_info(submission_id, reason, reviewer_user_id))


def _in_review_program():
    """A funded submission picked up by the conformance reviewer, fee escrowed once."""
    ctx = build_program(stage="submitted")
    ctx.submission = start_review(ctx.submission_id)
    return ctx


def _close_one_cycle(ctx, reason):
    """One whole turn of IN_REVIEW -> RETURNED_FOR_INFO -> SUBMITTED -> IN_REVIEW."""
    _returned_for_info(ctx.submission_id, reason)
    submit_submission(ctx.submission_id, ctx.member_id)
    ctx.submission = start_review(ctx.submission_id)
    return ctx.submission


class TestSubmissionReviewLoopAndRevisionCeiling:
    """The cyclic review loop, its ceiling, and the escrow it never re-takes."""

    def test_01_a_return_from_submitted_is_refused_and_leaves_the_round_at_zero(self):
        """Return-for-info is an IN_REVIEW action, so firing it while the submission
        is still merely SUBMITTED is refused and burns no revision round.

        PRD (§2.8): "**Submission state.** `ERR_INVALID_SUBMISSION_STATE` (409) when
        the linked submission's `state` or credential posture does not permit the
        operation: test-plan creation requires `IN_REVIEW`; listing creation requires
        `REVIEW_COMPLETE` or `CERTIFIED`; listing publication requires the linked
        submission's `dac_state` to be `ISSUED`; and each of the submission's own
        lifecycle actions requires the originating state named in §3.8."

        Design: Difficulty/non_linear_state_machine/submission_review_cycle_loops_twice_then_hits_the_revision_ceiling
        """
        ctx = build_program(stage="submitted")

        response = _return_for_info(
            ctx.submission_id, "Premature - the submission is not under review yet"
        )

        validate_error(response, ERR_INVALID_SUBMISSION_STATE)
        submission = read_submission(ctx.submission_id)
        assert_states(
            submission,
            state=SUB_SUBMITTED,
            conformance_review_state=REVIEW_PENDING,
        )
        assert submission["revision_round"] == 0, (
            "a refused return-for-info consumes no revision round, expected 0, "
            "got {}".format(submission["revision_round"])
        )
        assert submission["conformance_reviewer_user_id"] is None, (
            "a refused return records no reviewer, got {!r}".format(
                submission["conformance_reviewer_user_id"]
            )
        )

    def test_02_the_first_return_moves_both_axes_and_records_the_reviewer(self):
        """The first accepted return drives the primary axis to RETURNED_FOR_INFO,
        the conformance axis to RETURNED, raises revision_round to 1 and stamps the
        acting reviewer's identifier.

        PRD (§3.8): "The return moves `IN_REVIEW → RETURNED_FOR_INFO` on the primary
        axis and `PENDING → RETURNED` on the conformance axis, increments
        `revision_round` by one, and records `conformance_reviewer_user_id` as the
        acting `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/submission_review_cycle_loops_twice_then_hits_the_revision_ceiling
        """
        ctx = _in_review_program()

        returned = _returned_for_info(ctx.submission_id, "Missing EMC test report")

        assert_states(
            returned,
            state=SUB_RETURNED_FOR_INFO,
            conformance_review_state=REVIEW_RETURNED,
            conformance_reviewer_user_id=CONFORMANCE_REVIEWER_1,
        )
        assert returned["revision_round"] == 1, (
            "the first return raises revision_round to 1, got {}".format(
                returned["revision_round"]
            )
        )
        stored = read_submission(ctx.submission_id)
        assert_states(
            stored,
            state=SUB_RETURNED_FOR_INFO,
            conformance_review_state=REVIEW_RETURNED,
        )

    def test_03_the_loop_closes_twice_and_the_round_counter_only_moves_on_returns(self):
        """Re-submitting closes the cycle back to SUBMITTED with the conformance axis
        reset to PENDING and revision_round still 1; the second return then takes the
        counter to 2.

        PRD (§3.4): "On success `state` becomes `SUBMITTED`, `submitted_at` is
        re-stamped, and `conformance_review_state` returns from `RETURNED` to
        `PENDING`, closing the review cycle `IN_REVIEW → RETURNED_FOR_INFO →
        SUBMITTED → IN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/submission_review_cycle_loops_twice_then_hits_the_revision_ceiling
        """
        ctx = _in_review_program()
        _returned_for_info(ctx.submission_id, "Missing EMC test report")

        resubmitted = submit_submission(ctx.submission_id, ctx.member_id)

        assert_states(
            resubmitted,
            state=SUB_SUBMITTED,
            conformance_review_state=REVIEW_PENDING,
        )
        assert resubmitted["revision_round"] == 1, (
            "a re-submit closes the cycle without consuming a round, expected "
            "revision_round 1, got {}".format(resubmitted["revision_round"])
        )

        picked_up_again = start_review(ctx.submission_id)
        assert_states(
            picked_up_again,
            state=SUB_IN_REVIEW,
            conformance_review_state=REVIEW_PENDING,
        )

        second_return = _returned_for_info(ctx.submission_id, "EMC report unsigned")
        assert_states(
            second_return,
            state=SUB_RETURNED_FOR_INFO,
            conformance_review_state=REVIEW_RETURNED,
        )
        assert second_return["revision_round"] == 2, (
            "the second return raises revision_round to 2, got {}".format(
                second_return["revision_round"]
            )
        )

    def test_04_a_third_return_hits_the_ceiling_and_leaves_the_submission_in_review(self):
        """After two completed cycles the loop is closed by the round limit: a third
        return is refused with ERR_REVISION_LIMIT_EXCEEDED and the submission stays
        IN_REVIEW with its counter at 2.

        PRD (§3.8): "A return requires `conformance_review_state` to be `PENDING` and
        `revision_round` to be strictly below 2; a submission that has already been
        returned twice is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/submission_review_cycle_loops_twice_then_hits_the_revision_ceiling
        """
        ctx = _in_review_program()
        _close_one_cycle(ctx, "Missing EMC test report")
        _close_one_cycle(ctx, "EMC report unsigned")

        before = read_submission(ctx.submission_id)
        assert_states(
            before, state=SUB_IN_REVIEW, conformance_review_state=REVIEW_PENDING
        )
        assert before["revision_round"] == 2, (
            "two closed cycles leave revision_round at 2, got {}".format(
                before["revision_round"]
            )
        )

        response = _return_for_info(ctx.submission_id, "Third bite at the apple")

        validate_error(response, ERR_REVISION_LIMIT_EXCEEDED)
        after = read_submission(ctx.submission_id)
        assert_states(
            after, state=SUB_IN_REVIEW, conformance_review_state=REVIEW_PENDING
        )
        assert after["revision_round"] == 2, (
            "the refused return leaves revision_round at 2, got {}".format(
                after["revision_round"]
            )
        )

    def test_05_the_loop_never_escrows_the_fee_a_second_time(self):
        """Two whole cycles later the ledger reads exactly as it did after the first
        submit: 850000 spendable, 150000 escrowed, nothing consumed, and the
        submission still holding one escrow of its pinned 150000-cent fee.

        PRD (§3.4): "Crucially the ledger is untouched: `fee_escrowed_cents` already
        equals `certification_fee_cents`, and no second escrow is taken."

        Design: Difficulty/non_linear_state_machine/submission_review_cycle_loops_twice_then_hits_the_revision_ceiling
        """
        ctx = _in_review_program()
        _close_one_cycle(ctx, "Missing EMC test report")
        _close_one_cycle(ctx, "EMC report unsigned")

        member = read_member(ctx.member_id)
        submission = read_submission(ctx.submission_id)

        assert_cents(submission["certification_fee_cents"], PINNED_FEE_CENTS,
                     "certification_fee_cents")
        assert_cents(submission["fee_escrowed_cents"], PINNED_FEE_CENTS,
                     "fee_escrowed_cents after two review cycles")
        assert_cents(member["credits_purchased_cents"], PURCHASED_CENTS,
                     "credits_purchased_cents")
        assert_cents(member["credit_balance_cents"], PURCHASED_CENTS - PINNED_FEE_CENTS,
                     "credit_balance_cents after two review cycles")
        assert_cents(member["escrowed_credit_cents"], PINNED_FEE_CENTS,
                     "escrowed_credit_cents after two review cycles")
        assert_cents(member["credits_consumed_cents"], 0, "credits_consumed_cents")

        available = read_ledger(ctx.member_id, variant="AVAILABLE")
        committed = read_ledger(ctx.member_id, variant="COMMITTED")
        assert_cents(available["balance_cents"], PURCHASED_CENTS - PINNED_FEE_CENTS,
                     "AVAILABLE balance_cents")
        assert_cents(committed["balance_cents"], PURCHASED_CENTS,
                     "COMMITTED balance_cents")


def _published_program():
    """The certified chain carried to a PUBLISHED, COMPLIANT listing, with the
    logical clock then moved to the instant every enforcement step runs at."""
    ctx = build_program(stage="published")
    ctx.published_at_before = ctx.listing["published_at"]
    set_clock(TRIGGER_CLOCK)
    return ctx


def _open_interop_case(ctx):
    """One operator-filed interoperability case worth 100 impacted units."""
    case = new_case(
        ctx.listing_id,
        category="INTEROP_DEFECT",
        evidence_summary="Group messaging drops on hub B",
        claimed_impact_units=100,
    )
    ctx.case1_id = case["id"]
    return case


def _order_remediation(ctx, remediation_days=20):
    """Escalate the interoperability case and order remediation against it."""
    _open_interop_case(ctx)
    advance_case(ctx.case1_id, "ESCALATE")
    return advance_case(
        ctx.case1_id, "ORDER_REMEDIATION", remediation_days=remediation_days
    )


def _confirm_remediation(ctx):
    """Carry the interoperability case all the way to REMEDIATED."""
    _order_remediation(ctx)
    return advance_case(ctx.case1_id, "CONFIRM_REMEDIATION")


class TestListingAxesWalkIndependentlyThenLock:
    """One listing row, two parallel axes, disjoint triggers and a terminal lock."""

    def test_06_opening_a_case_moves_only_the_enforcement_axis(self):
        """Filing an investigation against a published listing puts the enforcement
        axis under investigation and leaves the consumer-visibility axis, including
        its published_at stamp, exactly where it was.

        PRD (§3.9): "Acceptance opens the case in `state` `OPEN`, records
        `opened_by_user_id` as the acting `X-User-ID`, leaves `auto_opened` false,
        `closed_by_user_id` and `remediation_deadline_at` null, prices the assessment,
        moves the listing's `compliance_status` to `UNDER_INVESTIGATION` while leaving
        `publication_status` untouched, and recomputes the member's `open_case_count`."

        Design: Difficulty/non_linear_state_machine/listing_publication_and_compliance_axes_walk_independently_then_lock
        """
        ctx = _published_program()

        case = _open_interop_case(ctx)

        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            publication_status=PUB_PUBLISHED,
            compliance_status=COMPLIANCE_UNDER_INVESTIGATION,
        )
        assert listing["published_at"] == ctx.published_at_before, (
            "opening a case must not restamp published_at, expected {!r}, got "
            "{!r}".format(ctx.published_at_before, listing["published_at"])
        )
        assert case["state"] == CASE_OPEN, (
            "an accepted case opens in OPEN, got {}".format(case["state"])
        )
        assert case["remediation_deadline_at"] is None, (
            "a freshly opened case carries no remediation deadline, got {!r}".format(
                case["remediation_deadline_at"]
            )
        )
        assert_penalty(read_case(ctx.case1_id), 100, "INTEROP_DEFECT")

    def test_07_ordering_remediation_moves_only_the_visibility_axis(self):
        """Ordering remediation suppresses the listing and dates the deadline twenty
        days out from the logical clock, while the enforcement axis stays exactly
        where the case opening put it.

        PRD (§3.9): "`ORDER_REMEDIATION` moves it `EVIDENCE_REVIEW →
        REMEDIATION_ORDERED`, requires `remediation_days` to be present and between 1
        and 365 — an absent or out-of-range value being refused with
        `ERR_INVALID_DATE_RANGE` — sets `remediation_deadline_at` to the logical
        clock's current instant advanced by that many days, and, where the listing's
        `publication_status` is `PUBLISHED`, suppresses it."

        Design: Difficulty/non_linear_state_machine/listing_publication_and_compliance_axes_walk_independently_then_lock
        """
        ctx = _published_program()

        ordered = _order_remediation(ctx, remediation_days=20)

        assert ordered["state"] == CASE_REMEDIATION_ORDERED, (
            "ORDER_REMEDIATION leaves the case in REMEDIATION_ORDERED, got "
            "{}".format(ordered["state"])
        )
        expected_deadline = plus_days(TRIGGER_CLOCK, 20)
        assert same_instant(ordered["remediation_deadline_at"], expected_deadline), (
            "remediation_deadline_at must be {} (2026-09-03 plus 20 days), got "
            "{!r}".format(expected_deadline, ordered["remediation_deadline_at"])
        )
        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            publication_status=PUB_SUPPRESSED,
            compliance_status=COMPLIANCE_UNDER_INVESTIGATION,
        )

    def test_08_confirming_remediation_leaves_the_listing_suppressed(self):
        """Confirming remediation restores the enforcement axis to REMEDIATED but
        deliberately leaves the device out of the directory; a separate publication
        act then walks SUPPRESSED back to PUBLISHED and restamps published_at.

        PRD (§3.9): "Opening an investigation moves the enforcement axis and leaves
        visibility alone; ordering remediation moves both; confirming remediation
        restores the enforcement axis to `REMEDIATED` but deliberately leaves
        visibility at `SUPPRESSED`, so a separate publication act is needed to put the
        device back in front of consumers."

        Design: Difficulty/non_linear_state_machine/listing_publication_and_compliance_axes_walk_independently_then_lock
        """
        ctx = _published_program()

        confirmed = _confirm_remediation(ctx)

        assert confirmed["state"] == CASE_REMEDIATED, (
            "CONFIRM_REMEDIATION leaves the case in REMEDIATED, got {}".format(
                confirmed["state"]
            )
        )
        after_confirmation = read_listing(ctx.listing_id)
        assert_states(
            after_confirmation,
            publication_status=PUB_SUPPRESSED,
            compliance_status=COMPLIANCE_REMEDIATED,
        )

        republished = publish_listing(ctx.listing_id)

        assert_states(
            republished,
            publication_status=PUB_PUBLISHED,
            compliance_status=COMPLIANCE_REMEDIATED,
        )
        assert same_instant(republished["published_at"], TRIGGER_CLOCK), (
            "the re-publication restamps published_at from the logical clock, "
            "expected {}, got {!r}".format(TRIGGER_CLOCK, republished["published_at"])
        )

    def test_09_ordering_withdrawal_moves_both_axes_and_locks_the_row(self):
        """A second investigation ordering withdrawal drives visibility to WITHDRAWN,
        enforcement to NONCOMPLIANT and the credential to REVOKED in one act, and
        WITHDRAWN is terminal, so no later publication can reopen the row.

        PRD (§3.9): "`WITHDRAWN` is terminal on the visibility axis; the enforcement
        axis has no terminal state at all, because a remediated listing can be
        investigated again without bound."

        Design: Difficulty/non_linear_state_machine/listing_publication_and_compliance_axes_walk_independently_then_lock
        """
        ctx = _published_program()
        _confirm_remediation(ctx)
        publish_listing(ctx.listing_id)
        assert read_submission(ctx.submission_id)["dac_state"] == DAC_ISSUED, (
            "the credential is still ISSUED before the withdrawal is ordered, got "
            "{}".format(read_submission(ctx.submission_id)["dac_state"])
        )

        case_two = new_case(
            ctx.listing_id,
            category="SECURITY_DEFECT",
            evidence_summary="Secure boot chain broken in 1.4.0",
            claimed_impact_units=1200,
        )
        advance_case(case_two["id"], "ESCALATE")
        withdrawn_case = advance_case(case_two["id"], "ORDER_WITHDRAWAL")

        assert withdrawn_case["state"] == CASE_WITHDRAWAL_ORDERED, (
            "ORDER_WITHDRAWAL leaves the case in WITHDRAWAL_ORDERED, got "
            "{}".format(withdrawn_case["state"])
        )
        assert_penalty(read_case(case_two["id"]), 1200, "SECURITY_DEFECT")
        listing = read_listing(ctx.listing_id)
        assert_states(
            listing,
            publication_status=PUB_WITHDRAWN,
            compliance_status=COMPLIANCE_NONCOMPLIANT,
        )
        assert read_submission(ctx.submission_id)["dac_state"] == DAC_REVOKED, (
            "the withdrawal revokes the linked submission's credential, expected "
            "REVOKED, got {}".format(read_submission(ctx.submission_id)["dac_state"])
        )

        response = api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS)

        # The withdrawal revoked the credential as well as locking the visibility
        # axis, so BOTH rung 16 (submission state: publication requires dac_state
        # ISSUED) and rung 22 (listing state: WITHDRAWN cannot publish) are
        # violated. Per §2.8 the earlier rung wins, so the ladder-correct answer
        # is ERR_INVALID_SUBMISSION_STATE, never ERR_INVALID_LISTING_STATE.
        validate_error(response, ERR_INVALID_SUBMISSION_STATE)
        locked = read_listing(ctx.listing_id)
        assert_states(
            locked,
            publication_status=PUB_WITHDRAWN,
            compliance_status=COMPLIANCE_NONCOMPLIANT,
        )
