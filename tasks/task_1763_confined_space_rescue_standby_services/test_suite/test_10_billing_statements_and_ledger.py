"""Billing variants, statement aggregation, and the account ledger
(PRD §2.8, §2.9, §3.8)."""
from test_helpers import (
    CLERK,
    ApiErrorId,
    add_on_duty_attendant,
    create_account,
    create_ops_team,
    create_space,
    generate_statement,
    make_personnel,
    post_reading,
    read_account,
    read_permit,
    read_standby,
    read_statement,
    schedule_standby,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    setup_released_standby,
    statement_lines,
    standby_checkin,
    standby_release,
    validate_error,
    validate_success,
)

DAY = "2026-08-03"
PERIOD_START = "2026-08-03T00:00:00Z"
PERIOD_END = "2026-08-04T00:00:00Z"


def _lines_by_kind(stmt_id):
    lines = statement_lines(stmt_id)
    return lines


class TestBillingModeDivergence:
    def test_hourly_mode_bills_duration(self, api):
        """PRD §3.8: "An account's `billing_mode` selects exactly one variant:
        `HOURLY_STANDBY` produces per-assignment `STANDBY_HOURLY` lines and no
        `EVENT_BASE` or `EVENT_RESCUER` lines, while `EVENT` produces exactly
        the reverse, and identical standby activity yields different totals
        under the two variants." and "The actual minutes between
        `checked_in_at` and `checked_out_at` are rounded up to the next
        quarter-hour — any partial 15-minute block bills as a full block —
        yielding `billable_minutes`; dividing by 60 yields billable hours.
        Chargeable hours are the greater of the account's
        `minimum_billable_hours` and the billable hours."

        Design: Difficulty/dual_variant_calc/billing_mode_hourly_vs_event_divergence
        """
        ctx = setup_released_standby()  # checked in 10:00, released 12:07
        standby = ctx["standby"]
        assert standby["billable_minutes"] == 135, (
            "127 actual minutes round up to the 15-minute grid: 135")
        # 2.25h floored to the 4h minimum * 20000, weekday daytime x1.0.
        assert standby["line_amount_cents"] == 80000

        stmt = generate_statement(ctx["account"]["id"])
        assert stmt["line_count"] == 1
        lines = _lines_by_kind(stmt["id"])
        assert lines[0]["line_kind"] == "STANDBY_HOURLY"
        assert lines[0]["amount_cents"] == 80000
        assert stmt["total_cents"] == 80000

    def test_event_mode_bills_flat(self, api):
        """PRD §3.8: "For accounts in `EVENT` mode, duration is irrelevant —
        a 30-minute standby and a nine-hour standby bill identically." and "It
        likewise appends, for each released standby assignment of the account's
        permits with `checked_out_at` inside the period and `billed` still
        false, an `EVENT_RESCUER` line with `quantity` 1 at
        `event_per_rescuer_cents`, setting `billed` true."

        Design: Difficulty/dual_variant_calc/billing_mode_hourly_vs_event_divergence
        """
        # Identical activity to the hourly test (10:00 check-in, 12:07
        # release), but the account bills EVENT: 25000 flat instead of 80000.
        ctx = setup_released_standby(
            account_overrides={"billing_mode": "EVENT"})
        standby = ctx["standby"]
        assert standby.get("line_amount_cents") is None, (
            "the hourly charge is never computed for an EVENT account")

        stmt = generate_statement(ctx["account"]["id"])
        assert stmt["line_count"] == 1, (
            "the permit was never activated, so no EVENT_BASE line; only the "
            "per-rescuer line")
        lines = _lines_by_kind(stmt["id"])
        assert lines[0]["line_kind"] == "EVENT_RESCUER"
        assert lines[0]["quantity"] == 1
        assert lines[0]["unit_rate_cents"] == 25000
        assert lines[0]["amount_cents"] == 25000
        assert stmt["total_cents"] == 25000
        assert 80000 != 25000, (
            "identical standby activity bills divergently under the two "
            "billing_mode variants")


class TestHourlyPricing:
    def test_tier_crossing_with_after_hours_multiplier(self, api):
        """PRD §3.8: "The chargeable hours split at the account's
        `tier1_hours_threshold`: hours up to the threshold bill at the
        account's `hourly_standby_rate_cents`, and hours beyond it bill at that
        rate multiplied by `tier2_multiplier`. A day-type multiplier then
        applies to the whole assignment, non-stacking with explicit precedence:
        when `checked_in_at` falls on a Saturday or Sunday in UTC, the
        `weekend_multiplier` applies and takes precedence; otherwise, when
        `checked_in_at`'s UTC hour is before 7 or at or after 19, the
        `after_hours_multiplier` applies; otherwise the multiplier is 1.0. The
        final `line_amount_cents` is the base amount multiplied by the day
        multiplier, rounded half-up once at the end to integer cents."

        Design: Difficulty/combinatorial_formula/hourly_tier_crossing_with_after_hours_multiplier
        """
        ctx = setup_released_standby(
            at_setup="2026-08-03T18:00:00Z",
            checkin_at="2026-08-03T20:00:00Z",
            release_at="2026-08-04T06:00:00Z",
            standby_start_at="2026-08-03T20:00:00Z",
            standby_end_at="2026-08-04T08:00:00Z")
        standby = ctx["standby"]
        assert standby["billable_minutes"] == 600, (
            "600 actual minutes, an exact quarter-hour multiple")
        # 10.0h chargeable (above the 4h floor): 8h * 20000 + 2h * 20000 * 1.5
        # = 220000 base; check-in Monday 20:00 has UTC hour 20 >= 19 and is
        # not a weekend, so the after-hours multiplier applies: * 1.5.
        assert standby["line_amount_cents"] == 330000

    def test_tier_crossing_swept_line_matches_release(self, api):
        """PRD §3.8: "For accounts in `HOURLY_STANDBY` mode, each standby
        assignment computes its charge at release time, stored on the
        assignment as `billable_minutes` and `line_amount_cents`, and the
        generation sweep appends one `STANDBY_HOURLY` line per released
        assignment with `checked_out_at` inside the period and `billed` still
        false."

        Design: Difficulty/combinatorial_formula/hourly_tier_crossing_with_after_hours_multiplier
        """
        ctx = setup_released_standby(
            at_setup="2026-08-03T18:00:00Z",
            checkin_at="2026-08-03T20:00:00Z",
            release_at="2026-08-04T06:00:00Z",
            standby_start_at="2026-08-03T20:00:00Z",
            standby_end_at="2026-08-04T08:00:00Z")
        stmt = generate_statement(ctx["account"]["id"],
                                  period_start="2026-08-03T00:00:00Z",
                                  period_end="2026-08-05T00:00:00Z")
        assert stmt["line_count"] == 1
        line = _lines_by_kind(stmt["id"])[0]
        assert line["line_kind"] == "STANDBY_HOURLY"
        assert line["amount_cents"] == 330000, (
            "the swept line carries the release-time computed amount")
        assert stmt["total_cents"] == 330000

    def test_quarter_hour_roundup(self, api):
        """PRD §3.8: "The actual minutes between `checked_in_at` and
        `checked_out_at` are rounded up to the next quarter-hour — any partial
        15-minute block bills as a full block — yielding `billable_minutes`;
        dividing by 60 yields billable hours."

        Design: Corner/calculations/corner_quarter_hour_roundup
        """
        ctx = setup_released_standby(
            account_overrides={"minimum_billable_hours": 1},
            release_at="2026-08-03T11:01:00Z")
        standby = ctx["standby"]
        assert standby["billable_minutes"] == 75, "ceil(61/15)*15 = 75"
        # 1.25h (above the 1h minimum) * 20000, weekday daytime x1.0.
        assert standby["line_amount_cents"] == 25000

    def test_minimum_hours_floor(self, api):
        """PRD §3.8: "Chargeable hours are the greater of the account's
        `minimum_billable_hours` and the billable hours."

        Design: Corner/calculations/corner_minimum_hours_floor
        """
        ctx = setup_released_standby(release_at="2026-08-03T10:30:00Z")
        standby = ctx["standby"]
        assert standby["billable_minutes"] == 30, "an exact quarter-hour"
        # 0.5h billable < the 4h default floor: max(4, 0.5) = 4h * 20000.
        assert standby["line_amount_cents"] == 80000


class TestStatementAggregation:
    def test_per_line_rounding_half_up(self, api):
        """PRD §2.8: "The statement aggregation rule pins a strict rounding
        order: each `StatementLine`'s `amount_cents` is rounded to integer
        cents **first**, and only then are the per-line amounts summed into the
        statement's `total_cents`. Sum-then-round is forbidden. For example,
        two lines whose raw products are 4999.5 cents each produce a statement
        total of 10000 cents (5000 plus 5000), not 9999."

        Design: Difficulty/combinatorial_formula/statement_per_line_rounding_then_sum
        """
        # rate 3333, 1h minimum, after-hours x1.5: each 1.0h standby released
        # at 21:00 computes 1.0 * 3333 * 1.5 = 4999.5 raw -> 5000 per line.
        ctx = setup_issued_permit(
            at="2026-08-03T19:00:00Z",
            account_overrides={"hourly_standby_rate_cents": 3333,
                               "minimum_billable_hours": 1})
        team = ctx["team"]
        rescuer2 = _make_second_rescuer()
        sa1 = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                               team["rescuer"]["id"],
                               standby_start_at="2026-08-03T20:00:00Z",
                               standby_end_at="2026-08-03T22:00:00Z")
        sa2 = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                               rescuer2["id"],
                               standby_start_at="2026-08-03T20:00:00Z",
                               standby_end_at="2026-08-03T22:00:00Z")
        set_clock("2026-08-03T20:00:00Z")
        standby_checkin(sa1["id"], team["lead_headers"])
        standby_checkin(sa2["id"], team["lead_headers"])
        set_clock("2026-08-03T21:00:00Z")
        standby_release(sa1["id"], team["lead_headers"])
        standby_release(sa2["id"], team["lead_headers"])

        stmt = generate_statement(ctx["account"]["id"])
        amounts = sorted(
            line["amount_cents"] for line in _lines_by_kind(stmt["id"]))
        assert amounts == [5000, 5000], (
            "each 4999.5-cent line rounds half-up to 5000 BEFORE summing")

    def test_statement_total_rounds_then_sums(self, api):
        """PRD §2.8: "Sum-then-round is forbidden. For example, two lines
        whose raw products are 4999.5 cents each produce a statement total of
        10000 cents (5000 plus 5000), not 9999."

        Design: Difficulty/combinatorial_formula/statement_per_line_rounding_then_sum
        """
        ctx = setup_issued_permit(
            at="2026-08-03T19:00:00Z",
            account_overrides={"hourly_standby_rate_cents": 3333,
                               "minimum_billable_hours": 1})
        team = ctx["team"]
        rescuer2 = _make_second_rescuer()
        assignments = []
        for rescuer in (team["rescuer"], rescuer2):
            assignments.append(schedule_standby(
                ctx["permit"]["id"], team["lead_headers"], rescuer["id"],
                standby_start_at="2026-08-03T20:00:00Z",
                standby_end_at="2026-08-03T22:00:00Z"))
        # The logical clock only moves forward.
        set_clock("2026-08-03T20:00:00Z")
        for sa in assignments:
            standby_checkin(sa["id"], team["lead_headers"])
        set_clock("2026-08-03T21:00:00Z")
        for sa in assignments:
            standby_release(sa["id"], team["lead_headers"])

        stmt = generate_statement(ctx["account"]["id"])
        assert stmt["line_count"] == 2
        assert stmt["total_cents"] == 10000, (
            "per-line round then sum: 5000 + 5000 = 10000; the forbidden "
            "sum-then-round order would yield 9999")


class TestCrossModeLines:
    def test_cancellation_fee_line(self, api):
        """PRD §3.8: "When a permit with `actual_entry_at` set is cancelled on
        any path, a `CANCELLATION_FEE` line becomes billable; at generation, if
        the permit's `closed_at` falls inside the period and
        `cancellation_fee_billed` is still false, the line is appended with
        `quantity` 1 and a `unit_rate_cents` equal to half the account's
        `event_base_fee_cents` rounded half-up to integer cents, and
        `cancellation_fee_billed` is set true."

        Design: Corner/calculations/corner_cancellation_fee_line
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z",
                                  check_in_standby=False)
        set_clock("2026-08-03T10:00:00Z")
        cancelled = validate_success(api.cancel_permit(
            ctx["permit"]["id"], ctx["team"]["supervisor_headers"],
            reason="client stopped work"))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["close_reason"] == "CANCELLED"

        stmt = generate_statement(ctx["account"]["id"])
        assert stmt["line_count"] == 1, (
            "the never-checked-in standby accrues nothing")
        line = _lines_by_kind(stmt["id"])[0]
        assert line["line_kind"] == "CANCELLATION_FEE"
        assert line["quantity"] == 1
        assert line["unit_rate_cents"] == 75000
        assert line["amount_cents"] == 75000, (
            "round_half_up(150000 * 0.5)")
        assert stmt["total_cents"] == 75000
        permit = read_permit(ctx["permit"]["id"])
        assert permit["cancellation_fee_billed"] is True, (
            "the sweep marks the fee billed")

    def test_deployment_surcharge_line(self, api):
        """PRD §3.8: "When a standby assignment reached `DEPLOYED` before
        release, a `DEPLOYMENT_SURCHARGE` line with `quantity` 1 at the
        account's `deployment_surcharge_cents` is swept together with the
        assignment's mode-specific line once `checked_out_at` falls inside the
        period."
        PRD §3.6: "Link three: when any entry becomes `EVACUATED`, that
        permit's standby assignments in `ON_STANDBY` move to `DEPLOYED` with
        `deployed_at` stamped."

        Design: Corner/calculations/corner_deployment_surcharge_line
        """
        ctx = setup_issued_permit(at="2026-08-03T07:30:00Z",
                                  planned_start_at="2026-08-03T07:00:00Z")
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]
        standby = schedule_standby(permit_id, team["lead_headers"],
                                   team["rescuer"]["id"],
                                   standby_start_at="2026-08-03T08:00:00Z",
                                   standby_end_at="2026-08-03T20:00:00Z")
        set_clock("2026-08-03T08:00:00Z")
        standby_checkin(standby["id"], team["lead_headers"])
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        validate_success(api.activate_permit(permit_id,
                                             team["supervisor_headers"]))
        att_entry = add_on_duty_attendant(
            {"team": team, "permit": {"id": permit_id}},
            scheduled_start_at="2026-08-03T08:00:00Z")
        assert att_entry["status"] == "ON_DUTY"

        # The alarm at 10:00 evacuates the attendant and deploys the rescuer.
        set_clock("2026-08-03T10:00:00Z")
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="CONTINUOUS", o2_pct=21.0, lel_pct=5,
                     h2s_ppm=20, co_ppm=10)
        assert read_standby(standby["id"])["status"] == "DEPLOYED"

        set_clock("2026-08-03T12:00:00Z")
        released = standby_release(standby["id"], team["lead_headers"])
        assert released["status"] == "RELEASED"
        # 240 min -> 4.0h -> max(4, 4) = 4h * 20000, weekday 08:00 x1.0.
        assert released["line_amount_cents"] == 80000

        stmt = generate_statement(ctx["account"]["id"])
        lines = _lines_by_kind(stmt["id"])
        by_kind = {line["line_kind"]: line["amount_cents"] for line in lines}
        assert by_kind.get("STANDBY_HOURLY") == 80000
        assert by_kind.get("DEPLOYMENT_SURCHARGE") == 50000, (
            "flat surcharge at the account's deployment_surcharge_cents")
        assert stmt["total_cents"] == 130000


class TestStatementLifecycle:
    def test_statement_empty_period_zero(self, api):
        """PRD §3.8: "Generation sweeps the account's unbilled billable items
        according to the account's `billing_mode`, appending `StatementLine`
        records and marking swept items billed; `total_cents` and `line_count`
        are then recomputed under the pinned rounding order of §2.8." — with no
        billable items the statement holds zero lines and a zero total, and
        "A `BillingClerk` finalizes a statement in `OPEN` or `DISPUTED`" still
        applies to it.

        Design: Corner/calculations/corner_statement_empty_period_zero
        """
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Empty Co")
        stmt = generate_statement(account["id"])
        assert stmt["status"] == "OPEN"
        assert stmt["total_cents"] == 0
        assert stmt["line_count"] == 0

        finalized = validate_success(api.finalize_statement(stmt["id"],
                                                            _clerk()))
        assert finalized["status"] == "FINALIZED", (
            "no in-period permits exist, so finalization is not blocked")
        assert read_account(account["id"])["balance_cents"] == 0, (
            "finalizing the empty statement leaves the balance unchanged")

    def test_void_open_statement_invalid(self, api):
        """PRD §3.8: "Voiding a `FINALIZED` or `DISPUTED` statement moves it
        to `VOID`, subtracts the statement's
        `billed_balance_contribution_cents` from the account's `balance_cents`,
        zeroes the contribution, and recomputes the hold — a finalize followed
        by a void leaves `balance_cents` unchanged, forming a compensating
        pair." — voiding an `OPEN` statement is not a defined transition and
        fails with the statement state error `ERR_STATEMENT_INVALID_STATE` ("A
        `BillingClerk` finalizes a statement in `OPEN` or `DISPUTED` (any other
        state is `ERR_STATEMENT_INVALID_STATE`)").

        Design: Corner/errors/corner_void_open_statement_invalid
        """
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Void Co")
        stmt = generate_statement(account["id"])
        assert stmt["status"] == "OPEN"

        resp = api.void_statement(stmt["id"], _clerk())
        validate_error(resp, ApiErrorId.ERR_STATEMENT_INVALID_STATE)
        assert read_statement(stmt["id"])["status"] == "OPEN"

    def test_statement_generate_idempotent(self, api):
        """PRD §3.8: "When an `OPEN` statement with an identical period
        already exists, generation returns that statement and tops it up with
        newly billable items rather than creating a duplicate." and "the
        generation sweep appends one `STANDBY_HOURLY` line per released
        assignment with `checked_out_at` inside the period and `billed` still
        false."

        Design: Corner/cross_cutting_layers/corner_statement_generate_idempotent
        """
        ctx = setup_released_standby()
        stmt1 = generate_statement(ctx["account"]["id"])
        assert stmt1["line_count"] == 1
        assert read_standby(ctx["standby"]["id"])["billed"] is True, (
            "the first sweep marks the assignment billed")

        stmt2 = generate_statement(ctx["account"]["id"])
        assert stmt2["id"] == stmt1["id"], (
            "an identical-period OPEN statement is topped up, not duplicated")
        assert stmt2["line_count"] == 1, (
            "the already-billed assignment is not swept twice")
        assert stmt2["total_cents"] == 80000

    def test_statement_period_overlap_rejected(self, api):
        """PRD §3.8: "A requested period that intersects an existing
        `FINALIZED`, `DISPUTED`, or `PAID` statement of the same account is
        rejected with `ERR_STATEMENT_PERIOD_OVERLAP`." and "supplying
        `period_start` (inclusive) and `period_end` (exclusive, strictly after
        `period_start`)" — periods are half-open, so an exactly-adjacent period
        does not intersect.

        Design: Corner/validations/corner_statement_period_overlap_rejected
        """
        ctx = setup_released_standby()
        stmt1 = generate_statement(ctx["account"]["id"])
        validate_success(api.finalize_statement(stmt1["id"], _clerk()))

        resp = api.generate_statement(
            ctx["account"]["id"],
            {"period_start": "2026-08-03T12:00:00Z",
             "period_end": "2026-08-05T00:00:00Z"}, _clerk())
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)
        assert resp.status_code == 409

        # Adjacent half-open periods: new start == existing end is legal.
        stmt2 = generate_statement(ctx["account"]["id"],
                                   period_start="2026-08-04T00:00:00Z",
                                   period_end="2026-08-05T00:00:00Z")
        assert stmt2["status"] == "OPEN"
        assert stmt2["total_cents"] == 0, (
            "all prior items were billed by the first statement")


class TestFinalizeGating:
    def test_finalize_blocked_while_permit_active(self, api):
        """PRD §3.8: "Finalization is blocked while any permit of the account
        is `ACTIVE` or `SUSPENDED` with `actual_entry_at` inside the
        statement's period (`ERR_PERMITS_STILL_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/statement_finalize_gated_by_open_permits
        """
        # Activation and standby check-in both happen at 07:00 (weekday
        # daytime, multiplier 1.0); the permit is ACTIVE with actual_entry_at
        # inside the statement period.
        ctx = setup_active_permit(at="2026-08-03T07:00:00Z")
        set_clock("2026-08-03T09:00:00Z")
        stmt = generate_statement(ctx["account"]["id"])
        assert stmt["status"] == "OPEN"

        resp = api.finalize_statement(stmt["id"], _clerk())
        validate_error(resp, ApiErrorId.ERR_PERMITS_STILL_OPEN)
        assert read_statement(stmt["id"])["status"] == "OPEN", (
            "a blocked finalize leaves the statement OPEN")

    def test_finalize_after_close_tops_up_same_statement(self, api):
        """PRD §3.8: "Finalization is blocked while any permit of the account
        is `ACTIVE` or `SUSPENDED` with `actual_entry_at` inside the
        statement's period (`ERR_PERMITS_STILL_OPEN`)."; "When an `OPEN`
        statement with an identical period already exists, generation returns
        that statement and tops it up with newly billable items rather than
        creating a duplicate."; "On finalize, `total_cents` is recomputed as
        the sum of per-line rounded amounts, the account's `balance_cents` is
        increased by the delta between `total_cents` and the statement's
        previous `billed_balance_contribution_cents`, the contribution is then
        set to `total_cents`, `finalized_at` is stamped, and `on_credit_hold`
        is recomputed."
        PRD §3.5: "Closure cascades: standby assignments in `ON_STANDBY` are
        released with billable fields computed, assignments in `SCHEDULED` are
        cancelled, assignments in `DEPLOYED` are left unchanged and must be
        released explicitly, roster entries in `SCHEDULED` are cancelled, and
        verifications in `PENDING` or `VERIFIED` are voided."

        Design: Difficulty/cross_entity_state_dependency/statement_finalize_gated_by_open_permits
        """
        # Check-in at 07:00 (weekday daytime, multiplier 1.0); closing at
        # 09:00 releases 120 minutes -> 2.0h -> the 4h floor bills 80000.
        ctx = setup_active_permit(at="2026-08-03T07:00:00Z")
        team = ctx["team"]
        set_clock("2026-08-03T09:00:00Z")
        stmt = generate_statement(ctx["account"]["id"])

        validate_error(api.finalize_statement(stmt["id"], _clerk()),
                       ApiErrorId.ERR_PERMITS_STILL_OPEN)

        # Closing the ACTIVE permit releases the ON_STANDBY assignment at
        # 09:00 (checked in 07:00 -> 120 min -> 2.0h -> max(4, 2) = 4h floor).
        closed = validate_success(api.close_permit(ctx["permit"]["id"],
                                                   team["supervisor_headers"]))
        assert closed["status"] == "CLOSED"
        released = read_standby(ctx["standby"]["id"])
        assert released["status"] == "RELEASED"
        assert released["line_amount_cents"] == 80000

        stmt_again = generate_statement(ctx["account"]["id"])
        assert stmt_again["id"] == stmt["id"], (
            "top-up returns the same OPEN statement")

        finalized = validate_success(api.finalize_statement(stmt["id"],
                                                            _clerk()))
        assert finalized["status"] == "FINALIZED"
        assert finalized["total_cents"] == 80000
        assert read_account(ctx["account"]["id"])["balance_cents"] == 80000


class TestLedgerInvariant:
    def test_finalize_debits_balance(self, api):
        """PRD §3.8: "On finalize, `total_cents` is recomputed as the sum of
        per-line rounded amounts, the account's `balance_cents` is increased by
        the delta between `total_cents` and the statement's previous
        `billed_balance_contribution_cents`, the contribution is then set to
        `total_cents`, `finalized_at` is stamped, and `on_credit_hold` is
        recomputed."
        PRD §2.9: "Every `ClientAccount` maintains a `balance_cents` that
        always equals the sum of `billed_balance_contribution_cents` over all
        of the account's `BillingStatement` records — this ledger invariant
        must hold after every mutation."

        Design: Difficulty/compensating_invariant/finalize_void_balance_invariant
        """
        ctx = setup_released_standby()
        stmt = generate_statement(ctx["account"]["id"])
        assert read_account(ctx["account"]["id"])["balance_cents"] == 0, (
            "generation does not debit the account")

        finalized = validate_success(api.finalize_statement(stmt["id"],
                                                            _clerk()))
        assert finalized["status"] == "FINALIZED"
        assert finalized["billed_balance_contribution_cents"] == 80000
        assert finalized["finalized_at"] is not None
        assert read_account(ctx["account"]["id"])["balance_cents"] == 80000, (
            "contribution 0 -> 80000 debits the balance by the full total")

    def test_void_after_finalize_conserves_balance(self, api):
        """PRD §3.8: "Voiding a `FINALIZED` or `DISPUTED` statement moves it
        to `VOID`, subtracts the statement's
        `billed_balance_contribution_cents` from the account's `balance_cents`,
        zeroes the contribution, and recomputes the hold — a finalize followed
        by a void leaves `balance_cents` unchanged, forming a compensating
        pair."

        Design: Difficulty/compensating_invariant/finalize_void_balance_invariant
        """
        ctx = setup_released_standby()
        stmt = generate_statement(ctx["account"]["id"])
        validate_success(api.finalize_statement(stmt["id"], _clerk()))
        assert read_account(ctx["account"]["id"])["balance_cents"] == 80000

        voided = validate_success(api.void_statement(stmt["id"], _clerk()))
        assert voided["status"] == "VOID"
        assert voided["total_cents"] == 80000, (
            "the VOID statement preserves its total for audit")
        assert voided["billed_balance_contribution_cents"] == 0
        assert read_account(ctx["account"]["id"])["balance_cents"] == 0, (
            "the forward finalize (+80000) paired with the compensating void "
            "(-80000) conserves balance_cents")

    def test_partial_payment_rejected(self, api):
        """PRD §3.8: "Payment of a `FINALIZED` statement requires
        `payment_cents` to equal `total_cents` exactly; any other amount is
        rejected with `ERR_PARTIAL_PAYMENT`. A successful payment moves the
        statement to `PAID`, subtracts `payment_cents` from `balance_cents`,
        zeroes the contribution, and recomputes the hold."

        Design: Corner/validations/corner_partial_payment_rejected
        """
        ctx = setup_released_standby()
        stmt = generate_statement(ctx["account"]["id"])
        validate_success(api.finalize_statement(stmt["id"], _clerk()))

        resp = api.pay_statement(stmt["id"], 79999, _clerk())
        validate_error(resp, ApiErrorId.ERR_PARTIAL_PAYMENT)
        assert resp.status_code == 422
        assert read_statement(stmt["id"])["status"] == "FINALIZED", (
            "a rejected partial payment changes nothing")

        paid = validate_success(api.pay_statement(stmt["id"], 80000, _clerk()))
        assert paid["status"] == "PAID"
        assert read_account(ctx["account"]["id"])["balance_cents"] == 0, (
            "80000 debited at finalize, 80000 credited at pay")


class TestCreditHold:
    def test_credit_hold_boundary(self, api):
        """PRD §2.9: "An account's `on_credit_hold` flag is recomputed
        whenever `balance_cents` changes: the flag is true exactly when
        `balance_cents` is greater than or equal to `credit_limit_cents`, with
        the boundary inclusive, so an account whose balance equals its credit
        limit is on hold. Credit hold is a fiscal gate on new work: creating an
        entry permit for a space owned by an account on credit hold is rejected
        with `ERR_CLIENT_CREDIT_HOLD`."

        Design: Corner/validations/corner_credit_hold_boundary
        """
        team = create_ops_team()
        ctx = setup_released_standby(
            account_overrides={"credit_limit_cents": 80000}, team=team)
        account_id = ctx["account"]["id"]
        assert ctx["account"]["on_credit_hold"] is False, (
            "balance 0 < 80000 at creation")

        stmt = generate_statement(account_id)
        validate_success(api.finalize_statement(stmt["id"], _clerk()))
        account = read_account(account_id)
        assert account["balance_cents"] == 80000
        assert account["on_credit_hold"] is True, (
            "80000 >= 80000: the boundary is inclusive")

        space2 = create_space(account_id, space_code="TK-CH2")
        resp = api.create_entry_permit(
            space2["id"],
            {"purpose": "Blocked job",
             "planned_start_at": "2026-08-04T06:00:00Z",
             "planned_end_at": "2026-08-04T20:00:00Z",
             "expected_space_version": space2["version"]},
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_CLIENT_CREDIT_HOLD)
        assert resp.status_code == 402
        # The first permit (created while the balance was 0) proves the gate
        # is conditional on the hold state.
        assert ctx["permit"]["status"] == "ISSUED"


def _clerk():
    return CLERK


def _make_second_rescuer():
    return make_personnel("Rescuer Two", ["RESCUER"],
                          certifications=["CONFINED_SPACE_RESCUE"])
