"""The two adjacent rungs of the validation ladder an implementation gets backwards.

Compliance standing is weighed before the balance sheet on a certification
submit, and bench occupancy is weighed before the laboratory's capacity ceiling
on a booking. Each pair is driven twice: once with both rules broken, so the
higher rung must decide the response, and once with only the lower rule broken,
so the masked rung proves it was armed all along.
"""

from test_helpers import (
    ERR_BENCH_WINDOW_CONFLICT,
    ERR_INSUFFICIENT_CREDIT,
    ERR_LAB_CAPACITY_EXCEEDED,
    ERR_MEMBER_NOT_IN_GOOD_STANDING,
    SESSION_SCHEDULED,
    SUB_DRAFT,
    SUB_SUBMITTED,
    assert_cents,
    assert_credit_ledger_invariant,
    assert_reserved_bench_minutes,
    assert_states,
    build_program,
    capacity_ceiling,
    grant_tool_access,
    new_session,
    purchase_credits,
    read_laboratory,
    read_member,
    read_session,
    read_submission,
    revoke_tool_access,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import test_session_payload
from test_helpers.test_users import ADMIN_HEADERS, make_member_headers

#: The pinned fee of the baseline lighting submission: 120000 cents of LIGHTING
#: base fee plus 15000 for each of the two declared codes, no SB1 surcharge, no
#: ADOPTER discount and the STANDARD track multiplier of one.
PINNED_FEE_CENTS = 150000

#: What the member holds when the scenario opens — short of the pinned fee.
UNDERFUNDED_CENTS = 100000


def _submit_gate_program():
    """A DRAFT submission whose member breaches both submit gates at once.

    The member executed its IP commitment and was granted testing-tool access,
    funded only 100000 of the 150000-cent pinned fee, and then had that tool
    access revoked — so ``good_standing`` is false *and* the balance is short.
    """
    ctx = build_program(stage="draft", credit_cents=UNDERFUNDED_CENTS)
    assert ctx.certification_fee_cents == PINNED_FEE_CENTS, (
        "the baseline lighting submission pins a fee of {} cents, got {}".format(
            PINNED_FEE_CENTS, ctx.certification_fee_cents
        )
    )
    revoke_tool_access(ctx.member_id)
    member = read_member(ctx.member_id)
    assert member["good_standing"] is False, (
        "revoking tool access must leave good_standing false, got {!r}".format(
            member["good_standing"]
        )
    )
    assert_cents(
        member["credit_balance_cents"], UNDERFUNDED_CENTS, "credit_balance_cents"
    )
    return ctx


def _submit(ctx):
    """Attempt the submit as the owning member and return the raw response."""
    return api_client.submit_submission(
        ctx.submission_id, headers=make_member_headers(ctx.member_id)
    )


class TestGoodStandingOutranksInsufficientCreditOnSubmit:
    """Compliance standing against money on `POST /submissions/{id}/submit`."""

    def test_01_a_submit_breaching_both_gates_reports_the_standing_not_the_money(self):
        """A member who has lost tool access and cannot cover the pinned fee is
        turned away on its standing, with the credit error nowhere in sight.

        PRD (§2.8): "A submit request from a member who has both lost good
        standing *and* lacks the credit to cover the pinned fee is rejected with
        `ERR_MEMBER_NOT_IN_GOOD_STANDING` and HTTP 409 — never with
        `ERR_INSUFFICIENT_CREDIT`."

        Design: Difficulty/priority_pair_validation_conflict/good_standing_outranks_insufficient_credit_on_submit
        """
        ctx = _submit_gate_program()

        response = _submit(ctx)

        error = validate_error(response, ERR_MEMBER_NOT_IN_GOOD_STANDING)
        assert response.status_code == 409, (
            "the good-standing rung answers with HTTP 409, got {}".format(
                response.status_code
            )
        )
        assert error["error_id"] != ERR_INSUFFICIENT_CREDIT, (
            "the money rung sits below the standing rung and must not decide this "
            "response, expected {} and not {}, got {}".format(
                ERR_MEMBER_NOT_IN_GOOD_STANDING,
                ERR_INSUFFICIENT_CREDIT,
                error["error_id"],
            )
        )

    def test_02_restoring_standing_exposes_the_credit_rung_underneath(self):
        """Granting tool access back leaves the balance untouched, and the very
        same submit now reports the money — the lower rung was masked, not absent.

        PRD (§3.4): "A submit attempted from any state other than `DRAFT` or
        `RETURNED_FOR_INFO` is rejected with `ERR_INVALID_SUBMISSION_STATE`, a
        non-`RATIFIED` specification with `ERR_INVALID_SPECIFICATION_STATE`, a
        failed baseline declaration with `ERR_SECURITY_BASELINE_NOT_MET`, and an
        underfunded first submit with `ERR_INSUFFICIENT_CREDIT` and HTTP 402."

        Design: Difficulty/priority_pair_validation_conflict/good_standing_outranks_insufficient_credit_on_submit
        """
        ctx = _submit_gate_program()
        validate_error(_submit(ctx), ERR_MEMBER_NOT_IN_GOOD_STANDING)

        grant_tool_access(ctx.member_id)
        restored = read_member(ctx.member_id)
        assert restored["good_standing"] is True, (
            "a further grant restores good standing, got {!r}".format(
                restored["good_standing"]
            )
        )
        assert_cents(
            restored["credit_balance_cents"], UNDERFUNDED_CENTS, "credit_balance_cents"
        )

        response = _submit(ctx)

        error = validate_error(response, ERR_INSUFFICIENT_CREDIT)
        assert response.status_code == 402, (
            "the certification-credit rung answers with HTTP 402, got {}".format(
                response.status_code
            )
        )
        assert error["error_id"] != ERR_MEMBER_NOT_IN_GOOD_STANDING, (
            "with standing restored the standing rung is satisfied and cannot "
            "decide the response, expected {}, got {}".format(
                ERR_INSUFFICIENT_CREDIT, error["error_id"]
            )
        )

    def test_03_neither_refusal_moved_the_submission_or_the_ledger(self):
        """Two refused submits later the submission is still a DRAFT that has
        never escrowed, and every cent the member bought is still spendable.

        PRD (§3.2): "A submission's `fee_escrowed_cents` is non-zero exactly while
        its `state` is `SUBMITTED`, `IN_REVIEW` or `RETURNED_FOR_INFO`."

        Design: Difficulty/priority_pair_validation_conflict/good_standing_outranks_insufficient_credit_on_submit
        """
        ctx = _submit_gate_program()
        validate_error(_submit(ctx), ERR_MEMBER_NOT_IN_GOOD_STANDING)
        grant_tool_access(ctx.member_id)
        validate_error(_submit(ctx), ERR_INSUFFICIENT_CREDIT)

        submission = read_submission(ctx.submission_id)
        member = read_member(ctx.member_id)

        assert_states(submission, state=SUB_DRAFT)
        assert_cents(submission["fee_escrowed_cents"], 0, "fee_escrowed_cents")
        assert submission["submitted_at"] is None, (
            "a refused submit never stamps submitted_at, got {!r}".format(
                submission["submitted_at"]
            )
        )
        assert_cents(
            member["credit_balance_cents"], UNDERFUNDED_CENTS, "credit_balance_cents"
        )
        assert_cents(member["escrowed_credit_cents"], 0, "escrowed_credit_cents")
        assert_cents(
            member["credits_purchased_cents"],
            UNDERFUNDED_CENTS,
            "credits_purchased_cents",
        )
        assert_cents(member["credits_consumed_cents"], 0, "credits_consumed_cents")
        assert_credit_ledger_invariant(member)

    def test_04_a_balance_of_exactly_the_pinned_fee_is_accepted_and_escrowed(self):
        """Topping the account up to exactly 150000 clears the last rung: the
        submit succeeds and moves the whole fee out of the spendable balance.

        PRD (§3.8): "The member's `credit_balance_cents` must be at least the
        submission's pinned `certification_fee_cents`, or the request is refused
        with `ERR_INSUFFICIENT_CREDIT`."

        Design: Difficulty/priority_pair_validation_conflict/good_standing_outranks_insufficient_credit_on_submit
        """
        ctx = _submit_gate_program()
        validate_error(_submit(ctx), ERR_MEMBER_NOT_IN_GOOD_STANDING)
        grant_tool_access(ctx.member_id)
        validate_error(_submit(ctx), ERR_INSUFFICIENT_CREDIT)
        purchase_credits(ctx.member_id, PINNED_FEE_CENTS - UNDERFUNDED_CENTS)

        response = _submit(ctx)

        submission = validate_success(response)
        assert_states(submission, state=SUB_SUBMITTED)
        assert_cents(
            submission["fee_escrowed_cents"], PINNED_FEE_CENTS, "fee_escrowed_cents"
        )
        assert same_instant(submission["submitted_at"], "2026-09-01T00:00:00Z"), (
            "submitted_at is stamped from the logical clock, expected "
            "2026-09-01T00:00:00Z, got {!r}".format(submission["submitted_at"])
        )
        member = read_member(ctx.member_id)
        assert_cents(member["credit_balance_cents"], 0, "credit_balance_cents")
        assert_cents(
            member["escrowed_credit_cents"], PINNED_FEE_CENTS, "escrowed_credit_cents"
        )
        assert_cents(
            member["credits_purchased_cents"],
            PINNED_FEE_CENTS,
            "credits_purchased_cents",
        )
        assert_credit_ledger_invariant(member)


#: A single-bench laboratory is budgeted ten hours per cycle.
SINGLE_BENCH_CEILING_MINUTES = capacity_ceiling(1)

#: The bench window already booked when the scenario opens, worth 480 minutes.
HELD_MINUTES = 480


def _single_bench_program():
    """An ISSUED plan and a one-bench laboratory already holding 480 minutes.

    With a `bench_capacity` of 1 the ceiling is 600 minutes, so the standing
    booking of 2026-09-02T09:00:00Z..2026-09-02T17:00:00Z leaves only 120
    minutes of headroom on a bench that is occupied all day.
    """
    ctx = build_program(stage="issued", lab_overrides={"bench_capacity": 1})
    ctx.session_x = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T17:00:00Z",
        session_type="INTEROP",
    )
    assert ctx.session_x["reserved_minutes"] == HELD_MINUTES, (
        "the standing booking spans eight hours, expected reserved_minutes {}, "
        "got {}".format(HELD_MINUTES, ctx.session_x["reserved_minutes"])
    )
    assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), HELD_MINUTES)
    return ctx


def _book(ctx, window_start, window_end):
    """Attempt a bench booking on bench 1 and return the raw response."""
    return api_client.create_test_session(
        test_session_payload(
            ctx.plan_id,
            ctx.laboratory_id,
            window_start=window_start,
            window_end=window_end,
            bench_index=1,
            session_type="SECURITY",
        ),
        ADMIN_HEADERS,
    )


class TestBenchWindowConflictOutranksLabCapacityOnSessionCreate:
    """Bench occupancy against the capacity ceiling on `POST /test-sessions`."""

    def test_05_a_booking_breaching_both_rules_reports_the_window_conflict(self):
        """A 240-minute booking that overlaps the standing window would also push
        the laboratory to 720 of its 600 minutes, yet the window conflict decides.

        PRD (§2.8): "A session booking that both collides with an existing booking
        on the same bench *and* would push the laboratory past its capacity ceiling
        is rejected with `ERR_BENCH_WINDOW_CONFLICT` — never with
        `ERR_LAB_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/bench_window_conflict_outranks_lab_capacity_on_session_create
        """
        ctx = _single_bench_program()

        response = _book(ctx, "2026-09-02T13:00:00Z", "2026-09-02T17:00:00Z")

        error = validate_error(response, ERR_BENCH_WINDOW_CONFLICT)
        assert response.status_code == 409, (
            "the bench-occupancy rung answers with HTTP 409, got {}".format(
                response.status_code
            )
        )
        assert error["error_id"] != ERR_LAB_CAPACITY_EXCEEDED, (
            "the capacity rung sits below the occupancy rung and must not decide "
            "this response, expected {} and not {}, got {}".format(
                ERR_BENCH_WINDOW_CONFLICT,
                ERR_LAB_CAPACITY_EXCEEDED,
                error["error_id"],
            )
        )
        assert HELD_MINUTES + 240 > SINGLE_BENCH_CEILING_MINUTES, (
            "the refused booking really does breach the ceiling too, expected "
            "{} + 240 above {}".format(HELD_MINUTES, SINGLE_BENCH_CEILING_MINUTES)
        )

    def test_06_the_same_minutes_on_a_clear_window_expose_the_capacity_rung(self):
        """Moving the identical 240 minutes to the following day clears the bench
        buffer, and the booking is then refused on the ceiling instead.

        PRD (§3.6): "Only if the window is clear does the **capacity ceiling**
        apply."

        Design: Difficulty/priority_pair_validation_conflict/bench_window_conflict_outranks_lab_capacity_on_session_create
        """
        ctx = _single_bench_program()
        validate_error(
            _book(ctx, "2026-09-02T13:00:00Z", "2026-09-02T17:00:00Z"),
            ERR_BENCH_WINDOW_CONFLICT,
        )

        response = _book(ctx, "2026-09-03T09:00:00Z", "2026-09-03T13:00:00Z")

        error = validate_error(response, ERR_LAB_CAPACITY_EXCEEDED)
        assert response.status_code == 409, (
            "the bench-capacity rung answers with HTTP 409, got {}".format(
                response.status_code
            )
        )
        assert error["error_id"] != ERR_BENCH_WINDOW_CONFLICT, (
            "a window sixteen hours clear of the standing booking cannot conflict, "
            "expected {}, got {}".format(ERR_LAB_CAPACITY_EXCEEDED, error["error_id"])
        )

    def test_07_neither_refused_booking_stored_a_session_or_held_a_minute(self):
        """After both refusals the laboratory still holds exactly the 480 minutes of
        its one stored session, which is untouched.

        PRD (§3.3): "`reserved_bench_minutes` is defined as the sum of
        `reserved_minutes` over the laboratory's sessions whose `state` is
        `SCHEDULED` or `IN_PROGRESS`, and that definition is normative: after any
        number of book, start, complete, cancel and cascade-cancel cycles, the
        stored aggregate must equal that sum exactly, with no accumulated drift."

        Design: Difficulty/priority_pair_validation_conflict/bench_window_conflict_outranks_lab_capacity_on_session_create
        """
        ctx = _single_bench_program()
        validate_error(
            _book(ctx, "2026-09-02T13:00:00Z", "2026-09-02T17:00:00Z"),
            ERR_BENCH_WINDOW_CONFLICT,
        )
        validate_error(
            _book(ctx, "2026-09-03T09:00:00Z", "2026-09-03T13:00:00Z"),
            ERR_LAB_CAPACITY_EXCEEDED,
        )

        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), HELD_MINUTES)
        sessions, meta = validate_paginated(
            api_client.list_test_sessions(ADMIN_HEADERS, laboratory_id=ctx.laboratory_id)
        )
        assert len(sessions) == 1, (
            "only the standing booking was ever stored, expected 1 session, "
            "got {}".format(len(sessions))
        )
        assert meta["total_count"] == 1, (
            "the refused bookings must not appear in the collection, expected "
            "total_count 1, got {}".format(meta["total_count"])
        )
        standing = read_session(ctx.session_x["id"])
        assert_states(standing, state=SESSION_SCHEDULED)
        assert standing["reserved_minutes"] == HELD_MINUTES, (
            "the standing session is untouched by the two refusals, expected "
            "reserved_minutes {}, got {}".format(
                HELD_MINUTES, standing["reserved_minutes"]
            )
        )

    def test_08_a_booking_landing_exactly_on_the_ceiling_is_accepted(self):
        """The remaining 120 minutes fit: the booking is stored SCHEDULED and takes
        the laboratory to exactly its 600-minute ceiling.

        PRD (§3.6): "The requested session's `reserved_minutes`, being the whole
        minutes between `window_start` and `window_end`, are added to the
        laboratory's current `reserved_bench_minutes`, and if that total *exceeds*
        the ceiling the booking is rejected with `ERR_LAB_CAPACITY_EXCEEDED`;
        landing exactly on the ceiling is allowed and one minute over is not."

        Design: Difficulty/priority_pair_validation_conflict/bench_window_conflict_outranks_lab_capacity_on_session_create
        """
        ctx = _single_bench_program()
        validate_error(
            _book(ctx, "2026-09-02T13:00:00Z", "2026-09-02T17:00:00Z"),
            ERR_BENCH_WINDOW_CONFLICT,
        )
        validate_error(
            _book(ctx, "2026-09-03T09:00:00Z", "2026-09-03T13:00:00Z"),
            ERR_LAB_CAPACITY_EXCEEDED,
        )

        response = _book(ctx, "2026-09-03T09:00:00Z", "2026-09-03T11:00:00Z")

        session = validate_success(response, 201)
        assert_states(session, state=SESSION_SCHEDULED)
        assert session["reserved_minutes"] == 120, (
            "a two-hour window reserves 120 whole minutes, got {}".format(
                session["reserved_minutes"]
            )
        )
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_reserved_bench_minutes(laboratory, SINGLE_BENCH_CEILING_MINUTES)
        assert SINGLE_BENCH_CEILING_MINUTES == HELD_MINUTES + 120, (
            "the accepted booking lands on the ceiling exactly, expected {} = {} + "
            "120".format(SINGLE_BENCH_CEILING_MINUTES, HELD_MINUTES)
        )
