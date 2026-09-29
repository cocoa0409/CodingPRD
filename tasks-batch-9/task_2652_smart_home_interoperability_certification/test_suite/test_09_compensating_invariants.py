"""The programme's two conserved quantities, walked around full round trips.

Money is conserved by escrow: every cent a submission escrows at submit comes
back to the member on a withdrawal or a rejection, or moves into consumption at
credential issuance, and the three-way ledger identity holds at every checkpoint
in between. Bench minutes are conserved by the laboratory's live set: a booking
adds them and a cancellation or a completion removes exactly the same figure, so
a laboratory that has finished its work sits back at zero and can book its whole
ceiling again.
"""

from test_helpers import (
    DAC_ISSUED,
    SESSION_CANCELLED,
    SESSION_COMPLETE,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SUB_CERTIFIED,
    SUB_REJECTED,
    SUB_SUBMITTED,
    SUB_WITHDRAWN,
    append_results,
    build_program,
    cancel_session,
    complete_session,
    conformance_decision,
    feature,
    issue_credential,
    issue_test_plan,
    new_session,
    new_submission,
    new_test_plan,
    plan_result_lines,
    purchase_credits,
    read_laboratory,
    read_ledger,
    read_member,
    read_session,
    read_submission,
    result_line,
    security_decision,
    set_clock,
    start_review,
    start_session,
    submit_submission,
    validate_paginated,
    withdraw_submission,
)
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_cents,
    assert_credit_ledger_invariant,
    assert_reserved_bench_minutes,
    assert_score,
    assert_states,
    capacity_ceiling,
)
from test_helpers.fixtures import read_test_plan
from test_helpers.test_users import ADMIN_HEADERS

#: Two mandatory and two optional lighting feature sets, so a submission's
#: declared-code count — and therefore its pinned fee — can be varied at will.
FOUR_LIGHTING_FEATURES = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_DIM", "MANDATORY", 10),
    feature("OPT_SCENE", "OPTIONAL", 8),
    feature("OPT_COLOR", "OPTIONAL", 6),
]

#: LIGHTING base 120000 plus 15000 per declared code, at SB1 and ADOPTER on the
#: STANDARD track, so the four submissions pin 150000, 165000, 180000 and 150000.
FEE_TWO_CODES_CENTS = 150000
FEE_THREE_CODES_CENTS = 165000
FEE_FOUR_CODES_CENTS = 180000
TOTAL_PURCHASED_CENTS = 1000000

_ESCROW_CHECKPOINTS = ["setup", "withdraw", "reject", "consumption", "respend"]
_BENCH_CHECKPOINTS = [
    "baseline",
    "booked",
    "cancelled",
    "rebooked",
    "started",
    "completed",
    "origin",
    "ceiling",
]


def _lines_for_plan(plan_id, outcome="PASS"):
    """One result line per feature set of a plan's closure, all one outcome."""
    plan = read_test_plan(plan_id)
    return [
        result_line(feature_set_id, outcome)
        for feature_set_id in plan["included_feature_set_ids"]
    ]


def _record_ledger(ctx, checkpoint):
    """Store the member row as it stands at one checkpoint of the round trip."""
    ctx.ledgers[checkpoint] = read_member(ctx.member_id)
    return ctx.ledgers[checkpoint]


def _record_minutes(ctx, checkpoint):
    """Store the laboratory's live occupancy figure at one checkpoint."""
    laboratory = read_laboratory(ctx.laboratory_id)
    ctx.laboratories[checkpoint] = laboratory
    ctx.minutes[checkpoint] = laboratory["reserved_bench_minutes"]
    return laboratory


def _escrow_round_trip(stop_after="respend"):
    """Escrow three fees, then release two of them and consume the third.

    One member funded by two purchases opens four lighting submissions against
    one ratified specification: SUB1 declaring two codes, SUB2 three, SUB3 four
    and SUB4 two. The first three are submitted, so three fees sit in escrow.
    The chain then leaves escrow three different ways — SUB1 is withdrawn, SUB2
    is rejected by its conformance reviewer, SUB3 is certified — and finally
    SUB4 is submitted out of the money the first two exits gave back. The member
    row is snapshotted into ``ctx.ledgers`` at every checkpoint.
    """
    limit = _ESCROW_CHECKPOINTS.index(stop_after)
    ctx = build_program(
        stage="laboratory",
        features=FOUR_LIGHTING_FEATURES,
        credit_cents=600000,
    )
    purchase_credits(ctx.member_id, 400000)
    ctx.ledgers = {}

    two_codes = ["CORE_ONOFF", "CORE_DIM"]
    three_codes = ["CORE_ONOFF", "CORE_DIM", "OPT_SCENE"]
    four_codes = ["CORE_ONOFF", "CORE_DIM", "OPT_SCENE", "OPT_COLOR"]
    ctx.submission1 = new_submission(ctx.member_id, ctx.specification_id, two_codes)
    ctx.submission2 = new_submission(ctx.member_id, ctx.specification_id, three_codes)
    ctx.submission3 = new_submission(ctx.member_id, ctx.specification_id, four_codes)
    ctx.submission4 = new_submission(ctx.member_id, ctx.specification_id, two_codes)
    ctx.sub1_id = ctx.submission1["id"]
    ctx.sub2_id = ctx.submission2["id"]
    ctx.sub3_id = ctx.submission3["id"]
    ctx.sub4_id = ctx.submission4["id"]

    ctx.submission1 = submit_submission(ctx.sub1_id, ctx.member_id)
    ctx.submission2 = submit_submission(ctx.sub2_id, ctx.member_id)
    ctx.submission3 = submit_submission(ctx.sub3_id, ctx.member_id)
    _record_ledger(ctx, "setup")
    if limit == _ESCROW_CHECKPOINTS.index("setup"):
        return ctx

    # EXIT 1 — the member withdraws SUB1, which releases its escrow.
    ctx.submission1 = withdraw_submission(ctx.sub1_id, ctx.member_id)
    _record_ledger(ctx, "withdraw")
    if limit == _ESCROW_CHECKPOINTS.index("withdraw"):
        return ctx

    # EXIT 2 — SUB2 is tested, every line fails, and the conformance reviewer
    # rejects it, which releases its escrow too.
    start_review(ctx.sub2_id)
    plan2 = new_test_plan(ctx.sub2_id)
    ctx.plan2_id = plan2["id"]
    issue_test_plan(ctx.plan2_id)
    session2 = new_session(
        ctx.plan2_id,
        ctx.laboratory_id,
        bench_index=2,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T11:00:00Z",
    )
    set_clock("2026-09-02T09:30:00Z")
    start_session(session2["id"], ctx.laboratory_id)
    append_results(
        session2["id"], ctx.laboratory_id, _lines_for_plan(ctx.plan2_id, "FAIL")
    )
    set_clock("2026-09-02T10:30:00Z")
    complete_session(session2["id"], ctx.laboratory_id)
    ctx.session2_id = session2["id"]
    ctx.submission2 = conformance_decision(ctx.sub2_id, "REJECT")
    _record_ledger(ctx, "reject")
    if limit == _ESCROW_CHECKPOINTS.index("reject"):
        return ctx

    # EXIT 3 — SUB3 passes everything and its credential is issued, which
    # consumes its escrow instead of releasing it.
    start_review(ctx.sub3_id)
    plan3 = new_test_plan(ctx.sub3_id)
    ctx.plan3_id = plan3["id"]
    issue_test_plan(ctx.plan3_id)
    session3 = new_session(
        ctx.plan3_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T13:00:00Z",
    )
    set_clock("2026-09-02T11:00:00Z")
    start_session(session3["id"], ctx.laboratory_id)
    append_results(
        session3["id"], ctx.laboratory_id, _lines_for_plan(ctx.plan3_id, "PASS")
    )
    set_clock("2026-09-02T12:00:00Z")
    complete_session(session3["id"], ctx.laboratory_id)
    ctx.session3_id = session3["id"]
    conformance_decision(ctx.sub3_id, "APPROVE")
    security_decision(ctx.sub3_id, "APPROVE")
    ctx.submission3 = issue_credential(ctx.sub3_id, "DAC-0000301")
    _record_ledger(ctx, "consumption")
    if limit == _ESCROW_CHECKPOINTS.index("consumption"):
        return ctx

    # The released money is real: SUB4's first submit escrows its whole fee.
    ctx.submission4 = submit_submission(ctx.sub4_id, ctx.member_id)
    _record_ledger(ctx, "respend")
    return ctx


class TestCreditEscrowRoundTrip:
    """One member's money, followed through three different escrow exits."""

    def test_01_three_submits_escrow_their_pinned_fees_to_the_cent(self):
        """Submitting three submissions moves exactly their three pinned fees out
        of the spendable balance and into escrow, and the ledger identity closes
        on 505000 + 0 + 495000 == 1000000.

        PRD (§3.4): "On success `state` becomes `SUBMITTED`, `submitted_at` is
        stamped, and the fee is escrowed: the member's `credit_balance_cents` falls
        by `certification_fee_cents`, the member's `escrowed_credit_cents` rises by
        the same amount, and the submission's `fee_escrowed_cents` is set to
        `certification_fee_cents`."

        Design: Difficulty/compensating_invariant/credit_escrow_round_trips_through_withdraw_reject_and_consumption
        """
        ctx = _escrow_round_trip(stop_after="setup")

        member = ctx.ledgers["setup"]
        assert_cents(
            member["credits_purchased_cents"],
            TOTAL_PURCHASED_CENTS,
            "credits_purchased_cents after the two purchases",
        )
        assert_cents(
            member["escrowed_credit_cents"],
            FEE_TWO_CODES_CENTS + FEE_THREE_CODES_CENTS + FEE_FOUR_CODES_CENTS,
            "escrowed_credit_cents with three submissions in flight",
        )
        assert_cents(member["credit_balance_cents"], 505000, "credit_balance_cents")
        assert_cents(member["credits_consumed_cents"], 0, "credits_consumed_cents")
        assert_credit_ledger_invariant(member)

        for label, submission_id, fee in (
            ("SUB1", ctx.sub1_id, FEE_TWO_CODES_CENTS),
            ("SUB2", ctx.sub2_id, FEE_THREE_CODES_CENTS),
            ("SUB3", ctx.sub3_id, FEE_FOUR_CODES_CENTS),
        ):
            submission = read_submission(submission_id)
            assert submission["state"] == SUB_SUBMITTED, (
                "{} must be SUBMITTED after its submit, got {}".format(
                    label, submission["state"]
                )
            )
            assert_cents(
                submission["certification_fee_cents"], fee,
                "{} certification_fee_cents".format(label),
            )
            assert_cents(
                submission["fee_escrowed_cents"], fee,
                "{} fee_escrowed_cents".format(label),
            )
        draft = read_submission(ctx.sub4_id)
        assert_cents(
            draft["fee_escrowed_cents"], 0, "the DRAFT SUB4 fee_escrowed_cents"
        )

    def test_02_a_withdrawal_releases_exactly_the_escrowed_fee(self):
        """Withdrawing SUB1 moves its 150000 back into the spendable balance and
        nothing else: escrow falls from 495000 to 345000, the balance rises from
        505000 to 655000 and the submission's own escrow is zeroed.

        PRD (§3.4): "It sets `state` to `WITHDRAWN`, which is terminal, and
        releases any escrow: the member's `escrowed_credit_cents` falls by
        `fee_escrowed_cents`, the member's `credit_balance_cents` rises by the same
        amount, and `fee_escrowed_cents` is then set to 0."

        Design: Difficulty/compensating_invariant/credit_escrow_round_trips_through_withdraw_reject_and_consumption
        """
        ctx = _escrow_round_trip(stop_after="withdraw")

        before = ctx.ledgers["setup"]
        after = ctx.ledgers["withdraw"]
        submission = read_submission(ctx.sub1_id)
        assert_states(submission, state=SUB_WITHDRAWN)
        assert_cents(
            submission["fee_escrowed_cents"], 0,
            "a WITHDRAWN submission's fee_escrowed_cents",
        )
        assert_cents(after["escrowed_credit_cents"], 345000, "escrowed_credit_cents")
        assert_cents(after["credit_balance_cents"], 655000, "credit_balance_cents")
        released = after["credit_balance_cents"] - before["credit_balance_cents"]
        assert released == FEE_TWO_CODES_CENTS, (
            "the withdrawal must return exactly SUB1's {} cents, got {}".format(
                FEE_TWO_CODES_CENTS, released
            )
        )
        assert_cents(
            after["credits_purchased_cents"], TOTAL_PURCHASED_CENTS,
            "credits_purchased_cents after a release",
        )
        assert_cents(after["credits_consumed_cents"], 0, "credits_consumed_cents")
        assert_credit_ledger_invariant(after)

    def test_03_a_conformance_rejection_releases_exactly_the_escrowed_fee(self):
        """A REJECT verdict on SUB2 drives it to REJECTED, pins the final readiness
        score its all-failing evidence earns and returns its 165000 in full, taking
        escrow to 180000 and the balance to 820000.

        PRD (§3.8): "Symmetrically, when the submission is `IN_REVIEW` and
        *either* axis is `REJECTED`, the submission moves `IN_REVIEW → REJECTED` and
        the escrow is compensated: the member's `escrowed_credit_cents` falls by the
        submission's `fee_escrowed_cents`, its `credit_balance_cents` rises by the
        same figure, and `fee_escrowed_cents` is then set to 0."

        Design: Difficulty/compensating_invariant/credit_escrow_round_trips_through_withdraw_reject_and_consumption
        """
        ctx = _escrow_round_trip(stop_after="reject")

        before = ctx.ledgers["withdraw"]
        after = ctx.ledgers["reject"]
        submission = read_submission(ctx.sub2_id)
        assert_states(submission, state=SUB_REJECTED)
        assert_score(
            submission["final_readiness_score"], "15.00", "final_readiness_score"
        )
        assert_cents(
            submission["fee_escrowed_cents"], 0,
            "a REJECTED submission's fee_escrowed_cents",
        )
        assert_cents(after["escrowed_credit_cents"], 180000, "escrowed_credit_cents")
        assert_cents(after["credit_balance_cents"], 820000, "credit_balance_cents")
        released = after["credit_balance_cents"] - before["credit_balance_cents"]
        assert released == FEE_THREE_CODES_CENTS, (
            "the rejection must return exactly SUB2's {} cents, got {}".format(
                FEE_THREE_CODES_CENTS, released
            )
        )
        assert_cents(after["credits_consumed_cents"], 0, "credits_consumed_cents")
        assert_credit_ledger_invariant(after)

    def test_04_the_two_ledger_variants_differ_by_the_money_still_in_escrow(self):
        """With one submission still escrowed, AVAILABLE reports 820000 while
        COMMITTED reports the whole 1000000 the member still owns, and both agree on
        the 180000 in escrow and the 0 consumed.

        PRD (§3.2): "The `COMMITTED` variant, requested explicitly, is the finance
        view of everything the member still owns including money held in escrow: it
        does *not* subtract `escrowed_credit_cents`, so its `balance_cents` is simply
        `credits_purchased_cents` reduced by `credits_consumed_cents`."

        Design: Difficulty/compensating_invariant/credit_escrow_round_trips_through_withdraw_reject_and_consumption
        """
        ctx = _escrow_round_trip(stop_after="reject")

        available = read_ledger(ctx.member_id, variant="AVAILABLE")
        committed = read_ledger(ctx.member_id, variant="COMMITTED")

        assert_cents(
            available["balance_cents"], 820000, "AVAILABLE balance_cents"
        )
        assert_cents(
            committed["balance_cents"], TOTAL_PURCHASED_CENTS, "COMMITTED balance_cents"
        )
        difference = committed["balance_cents"] - available["balance_cents"]
        assert difference == 180000, (
            "the two variants must differ by exactly the 180000 cents still in "
            "escrow, got {}".format(difference)
        )
        for label, ledger in (("AVAILABLE", available), ("COMMITTED", committed)):
            assert_cents(
                ledger["escrowed_credit_cents"], 180000,
                "{} escrowed_credit_cents".format(label),
            )
            assert_cents(
                ledger["credits_consumed_cents"], 0,
                "{} credits_consumed_cents".format(label),
            )
            assert_cents(
                ledger["credits_purchased_cents"], TOTAL_PURCHASED_CENTS,
                "{} credits_purchased_cents".format(label),
            )
        assert_credit_ledger_invariant(available)

    def test_05_credential_issuance_consumes_the_escrow_instead_of_releasing_it(self):
        """Issuing SUB3's credential moves its 180000 out of escrow and into
        `credits_consumed_cents` rather than back into the balance, closing the
        identity on 820000 + 180000 + 0 == 1000000.

        PRD (§3.8): "Issuance moves `REVIEW_COMPLETE → CERTIFIED`, stamps
        `certified_at`, moves `dac_state` `NOT_ISSUED → ISSUED` with the supplied
        `dac_serial` stored, and *consumes* rather than releases the escrow: the
        member's `escrowed_credit_cents` falls by `fee_escrowed_cents`, its
        `credits_consumed_cents` rises by the same figure, and `fee_escrowed_cents`
        becomes 0."

        Design: Difficulty/compensating_invariant/credit_escrow_round_trips_through_withdraw_reject_and_consumption
        """
        ctx = _escrow_round_trip(stop_after="consumption")

        after = ctx.ledgers["consumption"]
        submission = read_submission(ctx.sub3_id)
        assert_states(submission, state=SUB_CERTIFIED, dac_state=DAC_ISSUED)
        assert_score(
            submission["final_readiness_score"], "85.00", "final_readiness_score"
        )
        assert_cents(
            submission["fee_escrowed_cents"], 0,
            "a CERTIFIED submission's fee_escrowed_cents",
        )
        assert_cents(
            after["credits_consumed_cents"], FEE_FOUR_CODES_CENTS,
            "credits_consumed_cents after issuance",
        )
        assert_cents(after["escrowed_credit_cents"], 0, "escrowed_credit_cents")
        assert_cents(after["credit_balance_cents"], 820000, "credit_balance_cents")
        assert_credit_ledger_invariant(after)
        # A consumption is not a release: the balance did not move at all.
        assert (
            after["credit_balance_cents"] == ctx.ledgers["reject"]["credit_balance_cents"]
        ), (
            "consuming the escrow must leave credit_balance_cents at {}, got {}".format(
                ctx.ledgers["reject"]["credit_balance_cents"],
                after["credit_balance_cents"],
            )
        )

    def test_06_the_released_money_is_spendable_again_and_purchases_never_move(self):
        """SUB4's first submit escrows its full 150000 out of money that only exists
        because the withdrawal and the rejection were exact, and
        `credits_purchased_cents` reads 1000000 at every one of the five checkpoints.

        PRD (§2.11): "Escrow is compensating: the cents a submission escrows at
        submit are returned to `credit_balance_cents` in full on rejection or
        withdrawal, or moved in full into `credits_consumed_cents` at credential
        issuance, and in every one of those three outcomes `fee_escrowed_cents`
        returns to 0."

        Design: Difficulty/compensating_invariant/credit_escrow_round_trips_through_withdraw_reject_and_consumption
        """
        ctx = _escrow_round_trip(stop_after="respend")

        after = ctx.ledgers["respend"]
        submission = read_submission(ctx.sub4_id)
        assert_states(submission, state=SUB_SUBMITTED)
        assert_cents(
            submission["certification_fee_cents"], FEE_TWO_CODES_CENTS,
            "SUB4 certification_fee_cents",
        )
        assert_cents(
            submission["fee_escrowed_cents"], FEE_TWO_CODES_CENTS,
            "SUB4 fee_escrowed_cents",
        )
        assert_cents(
            after["escrowed_credit_cents"], FEE_TWO_CODES_CENTS,
            "escrowed_credit_cents with only SUB4 in flight",
        )
        assert_cents(after["credit_balance_cents"], 670000, "credit_balance_cents")
        assert_cents(
            after["credits_consumed_cents"], FEE_FOUR_CODES_CENTS,
            "credits_consumed_cents",
        )
        assert_credit_ledger_invariant(after)

        for checkpoint in _ESCROW_CHECKPOINTS:
            ledger = ctx.ledgers[checkpoint]
            assert_cents(
                ledger["credits_purchased_cents"], TOTAL_PURCHASED_CENTS,
                "credits_purchased_cents at the {} checkpoint".format(checkpoint),
            )
            assert_credit_ledger_invariant(ledger)


def _bench_round_trip(stop_after="ceiling"):
    """Book, cancel, re-book, start, complete and cancel one laboratory's benches.

    A two-bench laboratory with a ceiling of 1200 minutes takes a 120-minute
    booking on bench 1 and a 300-minute booking on bench 2, loses the first to a
    cancellation, re-books the identical bench-1 window, runs that session
    through to completion and finally loses the 300-minute booking too. The
    laboratory's occupancy figure is snapshotted into ``ctx.minutes`` at every
    checkpoint, and one 1200-minute booking closes the walk.
    """
    limit = _BENCH_CHECKPOINTS.index(stop_after)
    ctx = build_program(stage="issued")
    ctx.minutes = {}
    ctx.laboratories = {}
    _record_minutes(ctx, "baseline")
    if limit == _BENCH_CHECKPOINTS.index("baseline"):
        return ctx

    ctx.session1 = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T11:00:00Z",
    )
    ctx.session2 = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=2,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T14:00:00Z",
        session_type="SECURITY",
    )
    _record_minutes(ctx, "booked")
    if limit == _BENCH_CHECKPOINTS.index("booked"):
        return ctx

    ctx.session1 = cancel_session(ctx.session1["id"])
    _record_minutes(ctx, "cancelled")
    if limit == _BENCH_CHECKPOINTS.index("cancelled"):
        return ctx

    # The cancelled window is free again, so the identical bench-1 interval books.
    ctx.session3 = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T11:00:00Z",
    )
    _record_minutes(ctx, "rebooked")
    if limit == _BENCH_CHECKPOINTS.index("rebooked"):
        return ctx

    set_clock("2026-09-02T09:30:00Z")
    ctx.session3 = start_session(ctx.session3["id"], ctx.laboratory_id)
    _record_minutes(ctx, "started")
    if limit == _BENCH_CHECKPOINTS.index("started"):
        return ctx

    append_results(ctx.session3["id"], ctx.laboratory_id, plan_result_lines(ctx))
    ctx.session3 = complete_session(ctx.session3["id"], ctx.laboratory_id)
    _record_minutes(ctx, "completed")
    if limit == _BENCH_CHECKPOINTS.index("completed"):
        return ctx

    ctx.session2 = cancel_session(ctx.session2["id"])
    _record_minutes(ctx, "origin")
    if limit == _BENCH_CHECKPOINTS.index("origin"):
        return ctx

    ctx.session4 = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-04T03:00:00Z",
        window_end="2026-09-04T23:00:00Z",
    )
    _record_minutes(ctx, "ceiling")
    return ctx


class TestBenchMinutesReturnToZero:
    """One laboratory's reserved minutes, followed through cancel and completion."""

    def test_07_two_bookings_reserve_exactly_the_sum_of_their_windows(self):
        """A laboratory that has booked nothing holds 0 minutes; a 120-minute and a
        300-minute booking take it to exactly 420, with no changeover buffer added
        to the reservation.

        PRD (§3.6): "An accepted booking stores the session in `state` `SCHEDULED`
        with `started_at` and `completed_at` null, `completed_late` false,
        `result_lines` an empty array, `disputed_line_count` 0, and `reserved_minutes`
        computed from the window; the laboratory's `reserved_bench_minutes` rises by
        that figure immediately."

        Design: Difficulty/compensating_invariant/bench_minutes_return_to_zero_after_every_cancel_and_completion
        """
        ctx = _bench_round_trip(stop_after="booked")

        assert_reserved_bench_minutes(ctx.laboratories["baseline"], 0)
        assert ctx.session1["reserved_minutes"] == 120, (
            "the 09:00..11:00 window reserves 120 minutes, got {}".format(
                ctx.session1["reserved_minutes"]
            )
        )
        assert ctx.session2["reserved_minutes"] == 300, (
            "the 09:00..14:00 window reserves 300 minutes, got {}".format(
                ctx.session2["reserved_minutes"]
            )
        )
        assert_states(ctx.session1, state=SESSION_SCHEDULED)
        assert_states(ctx.session2, state=SESSION_SCHEDULED)
        assert_reserved_bench_minutes(ctx.laboratories["booked"], 420)
        assert ctx.minutes["booked"] == (
            ctx.session1["reserved_minutes"] + ctx.session2["reserved_minutes"]
        ), (
            "reserved_bench_minutes must be the plain sum 420 with no changeover "
            "buffer added, got {}".format(ctx.minutes["booked"])
        )

    def test_08_a_cancellation_restores_the_pre_booking_total_and_frees_the_window(self):
        """Cancelling the 120-minute session takes the laboratory back to precisely
        the 300 minutes it held before that session existed, and the identical
        bench-1 window then books again for the same 120 minutes.

        PRD (§3.6): "Cancellation sets `state` to `CANCELLED`, compensates the
        laboratory by decrementing `reserved_bench_minutes` by exactly this session's
        `reserved_minutes` — restoring the figure the laboratory held before this
        session was ever created — and frees the bench window, so a later booking may
        occupy the same laboratory-and-bench interval."

        Design: Difficulty/compensating_invariant/bench_minutes_return_to_zero_after_every_cancel_and_completion
        """
        ctx = _bench_round_trip(stop_after="rebooked")

        assert_states(read_session(ctx.session1["id"]), state=SESSION_CANCELLED)
        assert_reserved_bench_minutes(ctx.laboratories["cancelled"], 300)
        assert ctx.minutes["cancelled"] == ctx.session2["reserved_minutes"], (
            "after the cancellation only S2's {} minutes remain, got {}".format(
                ctx.session2["reserved_minutes"], ctx.minutes["cancelled"]
            )
        )
        assert ctx.session3["window_start"] == ctx.session1["window_start"], (
            "the re-booking must occupy the same window_start {}, got {}".format(
                ctx.session1["window_start"], ctx.session3["window_start"]
            )
        )
        assert ctx.session3["reserved_minutes"] == 120, (
            "the re-booked 09:00..11:00 window reserves 120 minutes, got {}".format(
                ctx.session3["reserved_minutes"]
            )
        )
        assert_reserved_bench_minutes(ctx.laboratories["rebooked"], 420)

    def test_09_starting_a_session_moves_state_but_never_moves_minutes(self):
        """An IN_PROGRESS session is inside the live set exactly like a SCHEDULED
        one, so starting the re-booked session leaves the laboratory on the same 420
        minutes it held while that session was merely scheduled.

        PRD (§3.3): "`reserved_bench_minutes` is defined as the sum of
        `reserved_minutes` over the laboratory's sessions whose `state` is `SCHEDULED`
        or `IN_PROGRESS`, and that definition is normative: after any number of book,
        start, complete, cancel and cascade-cancel cycles, the stored aggregate must
        equal that sum exactly, with no accumulated drift."

        Design: Difficulty/compensating_invariant/bench_minutes_return_to_zero_after_every_cancel_and_completion
        """
        ctx = _bench_round_trip(stop_after="started")

        assert_states(ctx.session3, state=SESSION_IN_PROGRESS)
        assert_reserved_bench_minutes(ctx.laboratories["started"], 420)
        assert ctx.minutes["started"] == ctx.minutes["rebooked"], (
            "the start must move no minutes, expected {} unchanged, got {}".format(
                ctx.minutes["rebooked"], ctx.minutes["started"]
            )
        )
        live = read_session(ctx.session2["id"])["reserved_minutes"] + (
            ctx.session3["reserved_minutes"]
        )
        assert ctx.minutes["started"] == live, (
            "the aggregate must equal the SCHEDULED plus IN_PROGRESS sum {}, "
            "got {}".format(live, ctx.minutes["started"])
        )

    def test_10_completing_a_session_releases_exactly_its_own_minutes(self):
        """The session that finishes inside its window is not late, leaves the live
        set, and takes exactly its own 120 minutes with it, putting the laboratory
        back on S2's 300.

        PRD (§3.6): "Completion moves `IN_PROGRESS → COMPLETE`, stamps
        `completed_at`, and recomputes `completed_late`, which is true exactly when
        `completed_at` is not null and is strictly after `window_end`; a session that
        finishes precisely at its `window_end` is not late. It also decrements the
        laboratory's `reserved_bench_minutes` by exactly this session's
        `reserved_minutes`, and it may bubble the parent plan from `IN_EXECUTION` to
        `COMPLETE` under the coverage conditions of §3.5."

        Design: Difficulty/compensating_invariant/bench_minutes_return_to_zero_after_every_cancel_and_completion
        """
        ctx = _bench_round_trip(stop_after="completed")

        assert_states(ctx.session3, state=SESSION_COMPLETE)
        assert ctx.session3["completed_late"] is False, (
            "the session completed at 09:30 against an 11:00 window_end, so "
            "completed_late must be false, got {!r}".format(
                ctx.session3["completed_late"]
            )
        )
        assert_reserved_bench_minutes(ctx.laboratories["completed"], 300)
        released = ctx.minutes["started"] - ctx.minutes["completed"]
        assert released == ctx.session3["reserved_minutes"], (
            "the completion must release exactly this session's {} minutes, "
            "got {}".format(ctx.session3["reserved_minutes"], released)
        )
        assert ctx.minutes["completed"] == ctx.minutes["cancelled"], (
            "the laboratory is back on S2's contribution of {} minutes, got "
            "{}".format(ctx.minutes["cancelled"], ctx.minutes["completed"])
        )

    def test_11_the_whole_ceiling_books_again_once_the_live_set_is_empty(self):
        """With every session cancelled or completed the laboratory reads 0 minutes
        again, and a single booking for the full 1200-minute ceiling is accepted —
        impossible had any exit leaked a minute — while all four session rows survive.

        PRD (§3.6): "The requested session's `reserved_minutes`, being the whole
        minutes between `window_start` and `window_end`, are added to the laboratory's
        current `reserved_bench_minutes`, and if that total *exceeds* the ceiling the
        booking is rejected with `ERR_LAB_CAPACITY_EXCEEDED`; landing exactly on the
        ceiling is allowed and one minute over is not."

        Design: Difficulty/compensating_invariant/bench_minutes_return_to_zero_after_every_cancel_and_completion
        """
        ctx = _bench_round_trip(stop_after="ceiling")

        assert_states(read_session(ctx.session2["id"]), state=SESSION_CANCELLED)
        assert_reserved_bench_minutes(ctx.laboratories["origin"], 0)
        assert ctx.session4["reserved_minutes"] == 1200, (
            "the 2026-09-04T03:00..23:00 window reserves 1200 minutes, got "
            "{}".format(ctx.session4["reserved_minutes"])
        )
        assert_reserved_bench_minutes(
            ctx.laboratories["ceiling"], capacity_ceiling(2)
        )
        assert ctx.minutes["ceiling"] == 1200, (
            "a two-bench laboratory may land exactly on its 1200-minute ceiling, "
            "got {}".format(ctx.minutes["ceiling"])
        )

        rows, meta = validate_paginated(
            api_client.list_test_sessions(
                ADMIN_HEADERS, laboratory_id=ctx.laboratory_id
            )
        )
        assert meta["total_count"] == 4, (
            "compensation removes minutes, never rows, expected 4 sessions, "
            "got {}".format(meta["total_count"])
        )
        states = {row["id"]: row["state"] for row in rows}
        expected = {
            ctx.session1["id"]: SESSION_CANCELLED,
            ctx.session2["id"]: SESSION_CANCELLED,
            ctx.session3["id"]: SESSION_COMPLETE,
            ctx.session4["id"]: SESSION_SCHEDULED,
        }
        for session_id, state in expected.items():
            assert states.get(session_id) == state, (
                "session {} must still be listed as {}, got {!r}".format(
                    session_id, state, states.get(session_id)
                )
            )
