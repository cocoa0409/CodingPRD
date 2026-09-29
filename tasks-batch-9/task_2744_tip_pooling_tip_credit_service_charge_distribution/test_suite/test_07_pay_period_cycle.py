"""Queue A — the cyclic pay-period machine and the compensating void that puts a
week's credited minutes back exactly where they started."""
from test_helpers import (
    COMPLIANCE,
    PREPARER,
    approve_period,
    close_shift,
    compute_period,
    declare_shift_tips,
    list_pay_lines_of,
    new_shift,
    read_pay_line,
    read_pay_period,
    read_shift,
    reopen_period,
    setup_texas_two_shift_world,
    setup_texas_wage_world,
    void_shift,
)


# ---------------------------------------------------------------------------
# non_linear_state_machine / pay_period_cycle_open_computed_approved_reopen_open
# ---------------------------------------------------------------------------
def test_reopening_an_approved_period_returns_it_to_open_and_supersedes_its_line(api):
    """The third lap starts clean: every stamp is null again but the minutes survive.

    PRD §3.8: "Reopening marks every pay line of the period whose `status` is
    `DRAFT` or `FINAL` as `SUPERSEDED`; sets `compute_variant`,
    `computed_by_user_id` and `approved_by_user_id` all back to null and
    `allocation_shortfall_cents` back to 0; zeroes `total_tip_credit_cents`,
    `total_topup_cents` and `reported_tips_cents`; and releases every service charge
    whose `allocated_pay_period_id` names this period from `ALLOCATED` back to
    `RECORDED`, clearing `allocated_pay_period_id` to null so the charge is
    available to be absorbed again by the next compute."
    PRD §3.8: "From either `DRAFT` or `FINAL` a line goes to the terminal
    `SUPERSEDED` when the owning period re-enters `OPEN` or when a fresh compute
    replaces the pay-line set; in both cases the line's `version` is incremented by
    1, which invalidates any `expected_pay_line_version` a client was holding."
    PRD §3.4: "`total_credited_minutes` is the sum of `scheduled_minutes` over the
    period's shifts whose `time_status` is `CLOSED`."

    Design: Difficulty/non_linear_state_machine/pay_period_cycle_open_computed_approved_reopen_open
    """
    world = setup_texas_two_shift_world(approve=True)
    first_line_id = world["pay_line"]["id"]
    assert read_pay_line(first_line_id)["version"] == 2, (
        "version 1 at compute and version 2 at approval"
    )

    reopen_period(world["pay_period"]["id"], headers=COMPLIANCE)

    period = read_pay_period(world["pay_period"]["id"])
    assert period["status"] == "OPEN"
    assert period["compute_variant"] is None
    assert period["computed_by_user_id"] is None
    assert period["approved_by_user_id"] is None
    assert period["total_tip_credit_cents"] == 0
    assert period["total_topup_cents"] == 0
    assert period["reported_tips_cents"] == 0
    assert period["allocation_shortfall_cents"] == 0
    assert period["total_credited_minutes"] == 960, (
        "reopening tears down the payroll figures, not the timekeeping ones"
    )

    superseded = read_pay_line(first_line_id)
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["version"] == 3


def test_second_compute_after_the_reopen_builds_a_fresh_line_beside_the_dead_one(api):
    """The same week is re-entered at OPEN and priced again from version 1.

    PRD §3.8: "Reopening is what makes the period machine cyclic — `OPEN →
    COMPUTED → APPROVED → OPEN` — and the second compute may legitimately produce
    different numbers, because the shift inputs changed in between."
    PRD §3.8: "It then creates exactly one pay line per employee holding at least
    one `CLOSED` shift in the period, each with `variant` `WEEKLY_AGGREGATE` and
    `status` `DRAFT`, populating it by running the service-charge wages allocation
    of §3.6 first and the wage computation below second — that order matters,
    because the wage computation reads the service-charge figure the allocation
    writes."
    PRD §3.8: "It marks every pre-existing pay line of the period whose `status` is
    `DRAFT` or `FINAL` as `SUPERSEDED` **before** inserting the new set, so that a
    recompute never leaves two live lines for one employee."

    Design: Difficulty/non_linear_state_machine/pay_period_cycle_open_computed_approved_reopen_open
    """
    world = setup_texas_two_shift_world(approve=True)
    first_line_id = world["pay_line"]["id"]
    reopen_period(world["pay_period"]["id"], headers=COMPLIANCE)

    recomputed = compute_period(world["pay_period"]["id"], headers=PREPARER)

    assert recomputed["status"] == "COMPUTED"
    assert recomputed["compute_variant"] == "WEEKLY_AGGREGATE"
    assert recomputed["computed_by_user_id"] == PREPARER["X-User-ID"]

    rows = list_pay_lines_of(world["pay_period"]["id"])
    assert len(rows) == 2, (
        f"the dead first-lap line plus exactly one fresh line, got {len(rows)}"
    )
    live = [row for row in rows if row["status"] != "SUPERSEDED"]
    assert len(live) == 1
    fresh = live[0]
    assert fresh["id"] != first_line_id
    assert fresh["version"] == 1, "a brand new row starts its own version count"
    assert fresh["variant"] == "WEEKLY_AGGREGATE"
    assert fresh["status"] == "DRAFT"
    assert fresh["tip_credit_cents"] == 5500, (
        "the second lap reverts to the aggregate reading of the same two shifts"
    )
    assert fresh["topup_cents"] == 2692
    assert fresh["total_gross_cents"] == 6100

    assert recomputed["total_tip_credit_cents"] == 5500
    assert recomputed["total_topup_cents"] == 2692


def test_approving_the_second_lap_is_legal_and_reprices_per_shift_again(api):
    """The cycle really is a cycle: OPEN to COMPUTED to APPROVED a second time.

    PRD §3.8: "A `ComplianceOfficer` approves a period, moving it `COMPUTED →
    APPROVED`."
    PRD §3.8: "Approval recomputes every non-`SUPERSEDED` pay line of the period
    under the `PER_SHIFT` variant, overwriting `tip_credit_cents`, `topup_cents`
    and `total_gross_cents`; runs the reporting test below, writing each line's
    `allocated_tips_cents` and the period's `allocation_shortfall_cents`; moves
    every non-`SUPERSEDED` pay line from `DRAFT` to `FINAL`; sets the period's
    `compute_variant` to `PER_SHIFT` and its `approved_by_user_id` to the acting
    `X-User-ID`; and recomputes the period's `total_tip_credit_cents` and
    `total_topup_cents` from the new `PER_SHIFT` figures."

    Design: Difficulty/non_linear_state_machine/pay_period_cycle_open_computed_approved_reopen_open
    """
    world = setup_texas_two_shift_world(approve=True)
    reopen_period(world["pay_period"]["id"], headers=COMPLIANCE)
    compute_period(world["pay_period"]["id"], headers=PREPARER)

    approved = approve_period(world["pay_period"]["id"], headers=COMPLIANCE)

    assert approved["status"] == "APPROVED"
    assert approved["compute_variant"] == "PER_SHIFT"
    assert approved["approved_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert approved["total_tip_credit_cents"] == 4596
    assert approved["total_topup_cents"] == 3596

    live = [
        row
        for row in list_pay_lines_of(world["pay_period"]["id"])
        if row["status"] != "SUPERSEDED"
    ]
    assert len(live) == 1
    assert live[0]["status"] == "FINAL"
    assert live[0]["variant"] == "PER_SHIFT"
    assert live[0]["version"] == 2
    assert live[0]["total_gross_cents"] == 7004


# ---------------------------------------------------------------------------
# compensating_invariant / shift_create_close_then_void_conserves_credited_minutes
# ---------------------------------------------------------------------------
def _new_open_shift(world: dict) -> dict:
    return new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        gross_sales_cents=120000,
        charged_sales_cents=0,
    )


def test_closing_a_shift_moves_the_period_rollups_and_voiding_moves_them_back(api):
    """480 minutes and 120000 of receipts appear at the close and vanish at the void.

    PRD §3.5: "Closing recomputes the period's `total_credited_minutes` and
    `gross_receipts_cents`, since the shift has only now become one of the period's
    `CLOSED` shifts."
    PRD §3.4: "Voiding zeroes the shift's `non_tip_credit_minutes`,
    `tip_credit_eligible_minutes` and `retained_tips_cents`, then recomputes the
    owning period's `total_credited_minutes` and `gross_receipts_cents` from
    whichever shifts survive as `CLOSED`."
    PRD §3.4: "Voiding a closed shift is in this sense the exact compensating
    action for creating and closing it — after the void, the period's
    `total_credited_minutes` returns to the value it held before the shift was ever
    recorded."

    Design: Difficulty/compensating_invariant/shift_create_close_then_void_conserves_credited_minutes
    """
    world = setup_texas_wage_world()
    period_id = world["pay_period"]["id"]

    shift = _new_open_shift(world)
    before = read_pay_period(period_id)
    assert before["total_credited_minutes"] == 0, (
        "an OPEN shift is not yet one of the period's CLOSED shifts"
    )
    assert before["gross_receipts_cents"] == 0

    close_shift(shift["id"])
    after_close = read_pay_period(period_id)
    assert after_close["total_credited_minutes"] == 480
    assert after_close["gross_receipts_cents"] == 120000

    declare_shift_tips(shift["id"], world["employee"]["id"], 1000, 0)
    after_declare = read_pay_period(period_id)
    assert after_declare["total_credited_minutes"] == 480, (
        "declaring tips touches money, not minutes"
    )
    assert read_shift(shift["id"])["retained_tips_cents"] == 1000

    void_shift(shift["id"], reason="shift belonged to another employee")
    after_void = read_pay_period(period_id)
    assert after_void["total_credited_minutes"] == 0
    assert after_void["gross_receipts_cents"] == 0
    assert after_void["status"] == "OPEN"
    assert list_pay_lines_of(period_id) == []


def test_voided_shift_keeps_its_recorded_inputs_while_its_derived_money_zeroes(api):
    """The audit trail of what was recorded survives; only the derived figures fall.

    PRD §3.4: "Voiding zeroes the shift's `non_tip_credit_minutes`,
    `tip_credit_eligible_minutes` and `retained_tips_cents`, then recomputes the
    owning period's `total_credited_minutes` and `gross_receipts_cents` from
    whichever shifts survive as `CLOSED`."
    PRD §3.4: "Voiding is available from either timekeeping state — a shift whose
    `time_status` is `OPEN` and a shift whose `time_status` is `CLOSED` are both
    legal targets, and both land in `VOIDED`, which is terminal — and unlike almost
    every other write on a shift it does not require the owning period to be
    `OPEN`, precisely because its job is to correct periods that have already moved
    on."
    PRD §3.5: "Each of the three transitions writes the two declared amounts,
    overwriting whatever was there before, increments `declaration_count` by 1 — so
    a `declaration_count` of 1 marks an original declaration and 2 or more marks
    amendments — and recomputes `retained_tips_cents`."

    Design: Difficulty/compensating_invariant/shift_create_close_then_void_conserves_credited_minutes
    """
    world = setup_texas_wage_world()
    shift = _new_open_shift(world)
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], world["employee"]["id"], 1000, 0)

    voided = void_shift(shift["id"], reason="shift belonged to another employee")

    assert voided["time_status"] == "VOIDED"
    assert voided["tip_credit_eligible_minutes"] == 0
    assert voided["non_tip_credit_minutes"] == 0
    assert voided["retained_tips_cents"] == 0

    assert voided["scheduled_minutes"] == 480, (
        "the recorded interval is history and is never rewritten"
    )
    assert voided["gross_sales_cents"] == 120000
    assert voided["declared_cash_tips_cents"] == 1000
    assert voided["declaration_status"] == "DECLARED"
    assert voided["declaration_count"] == 1
