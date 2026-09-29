"""Queue B — §1.4 validation corners: the card-fee flag pinned per pool, the ceiling
on applied corrections, and the compute preconditions surfacing one at a time."""
from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_ALT,
    PREPARER,
    PREPARER_ALT,
    ApiErrorId,
    activate_policy,
    apply_correction,
    approve_period,
    close_shift,
    compute_period,
    declare_shift_tips,
    distribute_pool,
    list_allocations_of,
    list_pay_lines_of,
    new_correction,
    new_draft_policy,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_pool,
    new_role_assignment,
    new_service_charge,
    new_shift,
    read_correction,
    read_location,
    read_pay_line,
    read_pay_period,
    read_policy,
    read_pool,
    read_shift,
    set_logical_clock,
    sole_pay_line_of,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"
DATE_1 = "2026-08-04T00:00:00Z"
DATE_2 = "2026-08-05T00:00:00Z"
DATE_CHARGE = "2026-08-06T00:00:00Z"


def _line_of(pay_period_id: str, employee_id: str) -> dict:
    """The one live pay line the period holds for this employee."""
    live = [
        row
        for row in list_pay_lines_of(pay_period_id)
        if row["employee_id"] == employee_id and row["status"] != "SUPERSEDED"
    ]
    assert len(live) == 1, f"expected one live pay line, got {len(live)}"
    return live[0]


def _fee_flag_world() -> dict:
    """One ACTUAL_ONLY Texas unit trading two identical nights. The 2026-08-04 pool
    is built and paid out under policy A (cc_fee_pass_through true); policy B
    (cc_fee_pass_through false) is then activated and the 2026-08-05 pool is built
    and paid out under it."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    role_bartender = new_job_role(
        code="BARTENDER",
        title="Bartender",
        tip_status="TIPPED",
        is_management=False,
        pool_contribution_pct_bps=1000,
        pool_share_points=8,
        side_work_eligible=True,
    )
    ana = new_employee(location["id"])
    bea = new_employee(location["id"], full_name="Bea Olsen", external_payroll_ref="E2")
    new_role_assignment(ana["id"], role_server["id"])
    new_role_assignment(bea["id"], role_bartender["id"])

    policy_a = new_draft_policy(
        location["id"], share_basis="POINTS_ONLY", cc_fee_pass_through=True
    )
    activate_policy(policy_a["id"], location["version"])
    pay_period = new_pay_period(location["id"])

    shifts = {}
    for date, start, end in (
        (DATE_1, "2026-08-04T16:00:00Z", "2026-08-05T00:00:00Z"),
        (DATE_2, "2026-08-05T16:00:00Z", "2026-08-06T00:00:00Z"),
    ):
        server_shift = new_shift(
            ana["id"], location["id"], role_server["id"], pay_period["id"],
            business_date=date, start_at=start, end_at=end,
            gross_sales_cents=100000, charged_sales_cents=50000,
            cc_processing_fee_bps=300,
        )
        close_shift(server_shift["id"])
        declare_shift_tips(server_shift["id"], ana["id"], 2000, 8000)
        bar_shift = new_shift(
            bea["id"], location["id"], role_bartender["id"], pay_period["id"],
            business_date=date, start_at=start, end_at=end,
            gross_sales_cents=60000, charged_sales_cents=30000,
            cc_processing_fee_bps=250,
        )
        close_shift(bar_shift["id"])
        declare_shift_tips(bar_shift["id"], bea["id"], 1000, 5000)
        shifts[date] = {"server": server_shift, "bartender": bar_shift}

    pool_with_fee = new_pool(location["id"], DATE_1)
    distribute_pool(pool_with_fee["id"])

    policy_b = new_draft_policy(
        location["id"], share_basis="POINTS_ONLY", cc_fee_pass_through=False
    )
    activate_policy(policy_b["id"], read_location(location["id"])["version"])

    pool_no_fee = new_pool(location["id"], DATE_2)
    distribute_pool(pool_no_fee["id"])

    return {
        "location": location,
        "ana": ana,
        "bea": bea,
        "shifts": shifts,
        "policy_a": policy_a,
        "policy_b": policy_b,
        "pool_with_fee": read_pool(pool_with_fee["id"]),
        "pool_no_fee": read_pool(pool_no_fee["id"]),
        "pay_period": pay_period,
    }


# ---------------------------------------------------------------------------
# validations / pool_card_fee_pass_through_flag_toggles_the_deduction
# ---------------------------------------------------------------------------
def test_the_pass_through_flag_withholds_365_cents_from_the_first_night(api):
    """Two shifts, two rates, two roundings: 240 + 125 leaves the pool before the split.

    PRD §3.7: "Under `ACTUAL_ONLY`, a shift's fee is that shift's
    `cc_processing_fee_bps` applied as a basis-point rate to that shift's
    `declared_charged_tips_cents`, rounded half up."
    PRD §3.7: "Each shift's fee is rounded half up on its own, and
    `cc_fee_deducted_cents` is the sum of those already-rounded per-shift figures."
    PRD §3.7: "With the fee settled, `net_pool_cents` is `total_contributed_cents` plus
    `service_charge_tips_cents` less `cc_fee_deducted_cents`."
    PRD §3.7: "Under `POINTS_ONLY` it is simply the job role's `pool_share_points`."
    PRD §3.7: "A participant that wins a leftover cent has `remainder_cent_awarded` set
    true on its ledger row; every other row carries false."

    Design: Corner/validations/pool_card_fee_pass_through_flag_toggles_the_deduction
    """
    world = _fee_flag_world()
    pool = world["pool_with_fee"]

    assert pool["tip_pool_policy_id"] == world["policy_a"]["id"]
    assert pool["contributing_shift_count"] == 2
    assert pool["total_contributed_cents"] == 2100, (
        "1500 from the server's 10000 in tips and 600 from the bartender's 6000"
    )
    assert pool["cc_fee_deducted_cents"] == 365, (
        "240 from 300 bps of 8000 plus 125 from 250 bps of 5000, each shift rounded "
        "on its own charged tips"
    )
    assert pool["net_pool_cents"] == 1735
    assert pool["total_share_weight"] == 18
    assert pool["distributed_cents"] == 1735

    rows = {row["employee_id"]: row for row in list_allocations_of(pool["id"])}
    server_row = rows[world["ana"]["id"]]
    bar_row = rows[world["bea"]["id"]]
    assert server_row["share_weight"] == 10
    assert server_row["allocated_cents"] == 964
    assert server_row["remainder_cent_awarded"] is True
    assert bar_row["share_weight"] == 8
    assert bar_row["allocated_cents"] == 771
    assert bar_row["remainder_cent_awarded"] is False
    assert server_row["allocated_cents"] + bar_row["allocated_cents"] == 1735


def test_the_superseded_policy_still_governs_the_pool_that_pinned_it(api):
    """The second night keeps every cent, and the 365 reappears as 203 plus 162.

    PRD §3.7: "The pool immediately pins the unit's governing policy:
    `tip_pool_policy_id` records which policy was `ACTIVE` at creation time and
    `policy_version_pinned` records the `version` that policy carried at that moment."
    PRD §3.7: "If the pinned policy's `cc_fee_pass_through` is false, or the unit's
    `cc_fee_policy` is `PROHIBITED`, then `cc_fee_deducted_cents` is 0 and the fee
    calculation stops there."
    PRD §3.3: "Second, if another policy at the same `location_id` currently holds
    `status` `ACTIVE`, that incumbent is driven from `ACTIVE` to `SUPERSEDED` — a
    system-driven transition with no client request of its own."
    PRD §3.3: "Pools of the retired policy that were already `DISTRIBUTED` are
    deliberately left untouched: they keep their `policy_version_pinned` and stand as
    the audit record of what was actually paid."
    PRD §3.7: "Each contributing shift then has its `pool_contribution_cents` set to
    that contribution, its `shift_tip_pool_id` stamped with the new pool, and its
    `retained_tips_cents` reset to the tips it received less the contribution."

    Design: Corner/validations/pool_card_fee_pass_through_flag_toggles_the_deduction
    """
    world = _fee_flag_world()

    assert read_policy(world["policy_a"]["id"])["status"] == "SUPERSEDED"
    assert world["pool_with_fee"]["tip_pool_policy_id"] == world["policy_a"]["id"], (
        "the already-distributed pool still names the retired policy"
    )

    pool = world["pool_no_fee"]
    assert pool["tip_pool_policy_id"] == world["policy_b"]["id"]
    assert pool["total_contributed_cents"] == 2100, "the same two nights of tips"
    assert pool["cc_fee_deducted_cents"] == 0
    assert pool["net_pool_cents"] == 2100
    assert pool["total_share_weight"] == 18

    rows = {row["employee_id"]: row for row in list_allocations_of(pool["id"])}
    server_now = rows[world["ana"]["id"]]["allocated_cents"]
    bar_now = rows[world["bea"]["id"]]["allocated_cents"]
    assert server_now == 1167
    assert rows[world["ana"]["id"]]["remainder_cent_awarded"] is True
    assert bar_now == 933
    assert server_now + bar_now == 2100

    before = {
        row["employee_id"]: row["allocated_cents"]
        for row in list_allocations_of(world["pool_with_fee"]["id"])
    }
    server_delta = server_now - before[world["ana"]["id"]]
    bar_delta = bar_now - before[world["bea"]["id"]]
    assert server_delta == 203
    assert bar_delta == 162
    assert server_delta + bar_delta == world["pool_with_fee"]["cc_fee_deducted_cents"], (
        "the deltas account for the whole suppressed fee: no cent is lost to rounding "
        "in either direction"
    )

    for date in (DATE_1, DATE_2):
        server_shift = read_shift(world["shifts"][date]["server"]["id"])
        assert server_shift["pool_contribution_cents"] == 1500
        assert server_shift["retained_tips_cents"] == 8500, (
            "the flag changes what leaves the pool, never what enters it"
        )


def _applied_correction_world() -> dict:
    """The single-shift Texas week approved into one FINAL pay line whose
    minimum_wage_obligation_cents is 5800, carrying one already-APPLIED 3000-cent
    POOL_SHARE_SHORTFALL correction issued by op_comp_2 and applied by op_prep_2."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    employee = new_employee(location["id"])
    new_role_assignment(employee["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])
    shift = new_shift(
        employee["id"], location["id"], role_server["id"], pay_period["id"]
    )
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], employee["id"], 5000, 0)
    compute_period(pay_period["id"])
    approve_period(pay_period["id"])
    line = sole_pay_line_of(pay_period["id"])

    first = new_correction(
        line["id"], line["version"], headers=COMPLIANCE_ALT,
        amount_cents=3000, reason_code="POOL_SHARE_SHORTFALL",
    )
    apply_correction(first["id"], headers=PREPARER_ALT)
    return {
        "location": location,
        "employee": employee,
        "pay_period": pay_period,
        "pay_line": read_pay_line(line["id"]),
        "first_correction": first,
    }


# ---------------------------------------------------------------------------
# validations / applied_corrections_may_not_exceed_the_lines_wage_obligation
# ---------------------------------------------------------------------------
def test_the_ceiling_is_on_the_applied_sum_not_on_any_one_correction(api):
    """2900 issues cleanly and is then refused at apply time, because 3000 + 2900 is 5900.

    PRD §3.9: "`amount_cents` is the back wages owed and must be strictly greater than
    0."
    PRD §3.9: "Four checks apply, in this order: the acting `X-User-ID` must differ
    from the correction's `issued_by_user_id`, failing which
    `ERR_SEGREGATION_OF_DUTIES`; the correction's `status` must be `PENDING`, so
    applying one already `APPLIED` or already `VOIDED` yields
    `ERR_CORRECTION_NOT_PENDING`; the target line's `status` must be `FINAL`, failing
    which `ERR_PAY_LINE_NOT_FINAL`; and the sum of `amount_cents` over the line's
    already-`APPLIED` corrections plus this one may not exceed the line's
    `minimum_wage_obligation_cents`, failing which
    `ERR_CORRECTION_EXCEEDS_OBLIGATION`."
    PRD §3.9: "A newly issued correction has `status` `PENDING`, its
    `issued_by_user_id` set to the acting `X-User-ID`, and `applied_by_user_id`,
    `applied_at` and `voided_at` all null."
    PRD §3.8: "`pending_correction_cents` and `correction_applied_cents` are the sums
    of `amount_cents` over the line's corrections whose `status` is `PENDING` and whose
    `status` is `APPLIED` respectively."

    Design: Corner/validations/applied_corrections_may_not_exceed_the_lines_wage_obligation
    """
    world = _applied_correction_world()
    line = world["pay_line"]
    assert line["minimum_wage_obligation_cents"] == 5800
    assert line["correction_applied_cents"] == 3000
    assert line["total_gross_cents"] == 4704, "1704 of wages plus the 3000 posted"
    assert line["version"] == 4, "compute 1, approval 2, the issue 3, the apply 4"

    second = new_correction(
        line["id"], line["version"], headers=COMPLIANCE_ALT,
        amount_cents=2900, reason_code="POOL_SHARE_SHORTFALL",
    )
    assert second["status"] == "PENDING", (
        "2900 on its own is well under the 5800 obligation, so nothing is rejected at "
        "issue time"
    )

    validate_error(
        api.apply_back_wage_correction(second["id"], PREPARER_ALT),
        ApiErrorId.ERR_CORRECTION_EXCEEDS_OBLIGATION.value,
    )

    assert read_correction(second["id"])["status"] == "PENDING"
    after = read_pay_line(line["id"])
    assert after["correction_applied_cents"] == 3000
    assert after["pending_correction_cents"] == 2900
    assert after["total_gross_cents"] == 4704, "the refused apply moved no money"
    assert after["version"] == 5, "the issue bumped it, the rejected apply did not"


def test_a_replacement_correction_lands_exactly_on_the_obligation(api):
    """2800 supersedes the 2900 and 5800 is accepted: the ceiling is inclusive.

    PRD §3.9: "`supersedes_correction_id`, when supplied, must name a correction whose
    `status` is `PENDING` on the very same `pay_line_id`, and it is **required**
    whenever such a correction already exists on that line, so both a wrong target and
    a missing one yield `ERR_SUPERSEDE_TARGET_MISMATCH`."
    PRD §3.9: "Issuing it voids the superseded `PENDING` correction it displaced —
    that transition stamps the displaced row's `voided_at` with the current logical
    instant and removes its amount from the line's `pending_correction_cents` — raises
    the line's `pending_correction_cents` by the new amount, increments the line's
    `version` by exactly 1, and recomputes the owning period's
    `total_correction_cents`."
    PRD §3.9: "The correction's `amount_cents` is subtracted from the line's
    `pending_correction_cents`; the same amount is added to the line's
    `correction_applied_cents`; the same amount is added to the line's
    `total_gross_cents`; the line's `version` is incremented by 1; and `applied_at` is
    stamped with the current logical instant while `applied_by_user_id` records the
    acting `X-User-ID`."
    PRD §3.4: "`total_correction_cents` is the sum of `amount_cents` over back-wage
    corrections whose `status` is either `PENDING` or `APPLIED` and whose `pay_line_id`
    names a pay line of this period; a correction that has been `VOIDED` drops out of
    the sum entirely."

    Design: Corner/validations/applied_corrections_may_not_exceed_the_lines_wage_obligation
    """
    world = _applied_correction_world()
    line_id = world["pay_line"]["id"]

    second = new_correction(
        line_id, world["pay_line"]["version"], headers=COMPLIANCE_ALT,
        amount_cents=2900, reason_code="POOL_SHARE_SHORTFALL",
    )
    validate_error(
        api.apply_back_wage_correction(second["id"], PREPARER_ALT),
        ApiErrorId.ERR_CORRECTION_EXCEEDS_OBLIGATION.value,
    )

    third = new_correction(
        line_id, read_pay_line(line_id)["version"], headers=COMPLIANCE_ALT,
        amount_cents=2800, reason_code="POOL_SHARE_SHORTFALL",
        supersedes_correction_id=second["id"],
    )
    assert read_correction(second["id"])["status"] == "VOIDED"
    assert third["supersedes_correction_id"] == second["id"]

    displaced_line = read_pay_line(line_id)
    assert displaced_line["pending_correction_cents"] == 2800
    assert displaced_line["version"] == 6

    applied = apply_correction(third["id"], headers=PREPARER_ALT)
    assert applied["status"] == "APPLIED"

    final = read_pay_line(line_id)
    assert final["correction_applied_cents"] == 5800, (
        "3000 plus 2800 lands exactly on the obligation, and the ceiling is inclusive"
    )
    assert final["pending_correction_cents"] == 0
    assert final["total_gross_cents"] == 7504
    assert final["version"] == 7

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_correction_cents"] == 5800, (
        "3000 plus 2800, with the VOIDED 2900 excluded from the rollup"
    )


def _cascade_world() -> dict:
    """A Texas unit with no ACTIVE policy: Ana's CLOSED shift declaring 5000, Bea's
    CLOSED but still UNDECLARED shift beside it, and a 6000-cent WAGES charge parked
    on 2026-08-06, a date inside the period that carries no shift at all."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    ana = new_employee(location["id"])
    bea = new_employee(location["id"], full_name="Bea Olsen", external_payroll_ref="E2")
    new_role_assignment(ana["id"], role_server["id"])
    new_role_assignment(bea["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])

    shift_ana = new_shift(ana["id"], location["id"], role_server["id"], pay_period["id"])
    close_shift(shift_ana["id"])
    declare_shift_tips(shift_ana["id"], ana["id"], 5000, 0)

    shift_bea = new_shift(bea["id"], location["id"], role_server["id"], pay_period["id"])
    close_shift(shift_bea["id"])

    charge = new_service_charge(
        location["id"],
        business_date=DATE_CHARGE,
        amount_cents=6000,
        description="Thursday banquet",
    )
    return {
        "location": location,
        "ana": ana,
        "bea": bea,
        "shift_ana": shift_ana,
        "shift_bea": shift_bea,
        "charge": charge,
        "pay_period": pay_period,
    }


def _no_pay_lines_yet(api, pay_period_id: str) -> None:
    _rows, meta = validate_paginated(
        api.list_pay_lines(PREPARER, params={"pay_period_id": pay_period_id})
    )
    assert meta["total_count"] == 0, "a failed compute writes no lines"


# ---------------------------------------------------------------------------
# validations / compute_rejects_undeclared_shift_then_unallocatable_charge_then_succeeds
# ---------------------------------------------------------------------------
def test_the_charge_check_is_reached_only_once_the_declaration_check_clears(api):
    """One compute call, two different refusals, and no pay lines written by either.

    PRD §3.8: "Then every `CLOSED` shift of the period must carry
    `declaration_status` of `DECLARED` or `AMENDED`, failing which
    `ERR_UNDECLARED_SHIFT_IN_PERIOD`."
    PRD §3.8: "Then every service charge of this unit whose `status` is `RECORDED`,
    whose resolved `treatment` is `WAGES` and whose `business_date` falls inside the
    period must have at least one `CLOSED` shift on that `business_date` to allocate
    against, failing which `ERR_SERVICE_CHARGE_UNALLOCATABLE`."
    PRD §3.8: "It then creates exactly one pay line per employee holding at least one
    `CLOSED` shift in the period, each with `variant` `WEEKLY_AGGREGATE` and `status`
    `DRAFT`, populating it by running the service-charge wages allocation of §3.6 first
    and the wage computation below second — that order matters, because the wage
    computation reads the service-charge figure the allocation writes."
    PRD §3.4: "A newly opened period has `status` `OPEN`, `compute_variant` null,
    `computed_by_user_id` null, `approved_by_user_id` null, and every rollup at 0."

    Design: Corner/validations/compute_rejects_undeclared_shift_then_unallocatable_charge_then_succeeds
    """
    world = _cascade_world()
    period_id = world["pay_period"]["id"]

    validate_error(
        api.compute_pay_period(period_id, PREPARER),
        ApiErrorId.ERR_UNDECLARED_SHIFT_IN_PERIOD.value,
    )
    still_open = read_pay_period(period_id)
    assert still_open["status"] == "OPEN"
    assert still_open["compute_variant"] is None
    _no_pay_lines_yet(api, period_id)

    declare_shift_tips(world["shift_bea"]["id"], world["bea"]["id"], 0, 0)

    validate_error(
        api.compute_pay_period(period_id, PREPARER),
        ApiErrorId.ERR_SERVICE_CHARGE_UNALLOCATABLE.value,
    )
    assert read_pay_period(period_id)["status"] == "OPEN"
    _no_pay_lines_yet(api, period_id)


def test_the_thirty_dollar_test_reprices_the_whole_week_of_the_silent_employee(api):
    """Once both blockers are cleared, Bea's 480 eligible minutes buy her nothing.

    PRD §3.6: "Every void clears both `allocated_pool_id` and
    `allocated_pay_period_id`."
    PRD §3.8: "It sets the period's `compute_variant` to `WEEKLY_AGGREGATE` and its
    `computed_by_user_id` to the acting `X-User-ID`."
    PRD §3.8: "`tip_credit_eligible_minutes` is the sum of the shifts' own
    `tip_credit_eligible_minutes`, except that it is forced to 0 when
    `tipped_employee_qualified` is false."
    PRD §3.8: "`non_tip_credit_minutes` is `total_minutes` less
    `tip_credit_eligible_minutes`."
    PRD §3.8: "If `tipped_employee_qualified` comes out false, `tip_credit_cents` is 0
    for the whole line."

    Design: Corner/validations/compute_rejects_undeclared_shift_then_unallocatable_charge_then_succeeds
    """
    world = _cascade_world()
    period_id = world["pay_period"]["id"]
    declare_shift_tips(world["shift_bea"]["id"], world["bea"]["id"], 0, 0)
    validate_success(
        api.void_service_charge(
            world["charge"]["id"], PREPARER, {"reason": "no service occurred that day"}
        )
    )

    computed = compute_period(period_id)
    assert computed["status"] == "COMPUTED"
    assert computed["compute_variant"] == "WEEKLY_AGGREGATE"

    ana_line = _line_of(period_id, world["ana"]["id"])
    assert ana_line["tip_credit_eligible_minutes"] == 480
    assert ana_line["straight_cash_cents"] == 1704
    assert ana_line["service_charge_wages_cents"] == 0, "the charge was voided away"
    assert ana_line["tipped_employee_qualified"] is True
    assert ana_line["tip_credit_cents"] == 4096
    assert ana_line["topup_cents"] == 0
    assert ana_line["total_gross_cents"] == 1704

    bea_line = _line_of(period_id, world["bea"]["id"])
    assert bea_line["tipped_employee_qualified"] is False, (
        "0 declared is below the 3000-cent monthly threshold"
    )
    assert bea_line["tip_credit_eligible_minutes"] == 0
    assert bea_line["non_tip_credit_minutes"] == 480
    assert bea_line["straight_cash_cents"] == 5800, "her whole week reprices at 725"
    assert bea_line["tip_credit_cents"] == 0
    assert bea_line["topup_cents"] == 0
    assert bea_line["total_gross_cents"] == 5800

    assert read_shift(world["shift_bea"]["id"])["tip_credit_eligible_minutes"] == 480, (
        "the shift-level classification passed; only the line-level tipped-employee "
        "test failed"
    )

    period = read_pay_period(period_id)
    assert period["total_credited_minutes"] == 960
    assert period["total_tip_credit_cents"] == 4096
    assert period["total_topup_cents"] == 0
    assert period["reported_tips_cents"] == 5000
