"""Queue A — reversing a pool: the five-hop cascade, the money identity it
restores, and the compute it blocks while it is still pending."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    COMPLIANCE,
    PREPARER,
    assert_instant_equals,
    close_shift,
    declare_shift_tips,
    distribute_pool,
    list_allocations_of,
    list_pay_lines_of,
    new_active_policy,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_pool,
    new_role_assignment,
    new_shift,
    read_location,
    read_pay_period,
    read_pool,
    read_shift,
    reverse_pool,
    set_logical_clock,
    setup_texas_pool_world,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


# ---------------------------------------------------------------------------
# transitive_cascade / pool_reverse_cascade_depth_five
# ---------------------------------------------------------------------------
def test_pool_reversal_unwinds_the_ledger_and_the_three_shifts(api):
    """Hops 1 to 3: the pool zeroes, offsetting rows appear, the shifts are restored.

    PRD §3.7: "First, `contribution_status` moves `CONTRIBUTED → REVERSED` and
    `reversed_at` is stamped with the current logical instant;
    `total_contributed_cents`, `service_charge_tips_cents`, `cc_fee_deducted_cents`
    and `net_pool_cents` all become 0 as a consequence."
    PRD §3.7: "A pool whose `distribution_status` was `DISTRIBUTED` moves
    `DISTRIBUTED → REVERSED`, and for each `DISTRIBUTION` row of the pool the server
    appends one further ledger row whose `entry_type` is `REVERSAL` and whose
    `allocated_cents` is the exact negation of that `DISTRIBUTION` row's amount; the
    original `DISTRIBUTION` rows themselves are never mutated, so every recipient's
    net sum of `allocated_cents` for this pool returns to 0 and `distributed_cents`
    returns to 0 with it."
    PRD §3.7: "Third, every shift whose `shift_tip_pool_id` names this pool has that
    link cleared back to null, its `pool_contribution_cents` zeroed, and its
    `retained_tips_cents` restored to `declared_cash_tips_cents` plus
    `declared_charged_tips_cents` — the shift is whole again and free to be declared,
    pooled or voided."

    Design: Difficulty/transitive_cascade/pool_reverse_cascade_depth_five
    """
    world = setup_texas_pool_world(compute=True)

    pool = validate_success(
        api.reverse_shift_tip_pool(
            world["pool"]["id"],
            COMPLIANCE,
            {"reason": "policy audit found the busser ineligible"},
        )
    )

    assert pool["contribution_status"] == "REVERSED"
    assert pool["distribution_status"] == "REVERSED"
    assert_instant_equals(pool["reversed_at"], CLOCK, "reversed_at")
    assert pool["total_contributed_cents"] == 0
    assert pool["cc_fee_deducted_cents"] == 0
    assert pool["net_pool_cents"] == 0
    assert pool["distributed_cents"] == 0

    rows = list_allocations_of(world["pool"]["id"])
    assert len(rows) == 6, f"three DISTRIBUTION plus three REVERSAL rows, got {len(rows)}"
    distributions = sorted(
        row["allocated_cents"] for row in rows if row["entry_type"] == "DISTRIBUTION"
    )
    reversals = sorted(
        row["allocated_cents"] for row in rows if row["entry_type"] == "REVERSAL"
    )
    assert distributions == [940, 2005, 2508], (
        "the original rows are never mutated by the compensating pass"
    )
    assert reversals == [-2508, -2005, -940]
    assert sum(row["allocated_cents"] for row in rows) == 0

    expected_retained = {
        world["shift_server"]["id"]: 34020,
        world["shift_bartender"]["id"]: 14020,
        world["shift_busser"]["id"]: 0,
    }
    for shift_id, retained in expected_retained.items():
        shift = read_shift(shift_id)
        assert shift["shift_tip_pool_id"] is None
        assert shift["pool_contribution_cents"] == 0
        assert shift["retained_tips_cents"] == retained
        assert shift["time_status"] == "CLOSED", (
            "a pool reversal unwinds money, not timekeeping"
        )
        assert shift["declaration_status"] == "DECLARED"


def test_pool_reversal_drags_the_computed_period_back_to_open_and_rebuilds_rollups(api):
    """Hops 4 and 5: a period two references away is reopened and both rollups recomputed.

    PRD §3.7: "Fourth, for every pay period containing one of those shifts, if that
    period's `status` is `COMPUTED` or `APPROVED` it is driven back to `OPEN` by the
    server, which marks every pay line of that period `SUPERSEDED`."
    PRD §3.7: "Fifth, the unit's `pending_pool_cents` is recomputed over that unit's
    surviving `CONTRIBUTED` and `PENDING` pools, and each affected period's
    `total_credited_minutes` and `gross_receipts_cents` are recomputed from its
    surviving `CLOSED` shifts."
    PRD §3.8: "The two server-initiated transitions carry an identical side-effect set
    to each other: every pay line of the period whose `status` is `DRAFT` or `FINAL` is
    marked `SUPERSEDED`; `compute_variant`, `computed_by_user_id` and
    `approved_by_user_id` are set to null; `total_tip_credit_cents`,
    `total_topup_cents`, `allocation_shortfall_cents` and `reported_tips_cents` are
    zeroed; and `total_credited_minutes` and `gross_receipts_cents` are then recomputed
    from whichever shifts survive as `CLOSED`."

    Design: Difficulty/transitive_cascade/pool_reverse_cascade_depth_five
    """
    world = setup_texas_pool_world(compute=True)
    assert read_pay_period(world["pay_period"]["id"])["status"] == "COMPUTED"

    reverse_pool(world["pool"]["id"], reason="policy audit found the busser ineligible")

    period = read_pay_period(world["pay_period"]["id"])
    assert period["status"] == "OPEN"
    assert period["compute_variant"] is None
    assert period["computed_by_user_id"] is None
    assert period["total_tip_credit_cents"] == 0
    assert period["total_topup_cents"] == 0
    assert period["total_credited_minutes"] == 1320
    assert period["gross_receipts_cents"] == 180000

    lines = list_pay_lines_of(world["pay_period"]["id"])
    assert lines, "the compute produced pay lines that the reversal must supersede"
    assert all(line["status"] == "SUPERSEDED" for line in lines)

    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0


# ---------------------------------------------------------------------------
# compensating_invariant / pool_distribute_then_reverse_conserves_declared_tips
# ---------------------------------------------------------------------------
def test_declared_tips_are_conserved_across_the_distribution(api):
    """Retained tips plus the card fee plus the net pool equals the 48040 declared.

    PRD §3.7: "The invariant that reversal preserves is worth stating plainly, because
    it is the test of a correct implementation: at every quiescent moment, the sum of
    all tips declared on a unit's shifts equals the sum of those shifts'
    `retained_tips_cents` plus the pool's `cc_fee_deducted_cents` plus its
    `net_pool_cents`."
    PRD §3.1: "`pending_pool_cents` is a live measure of money in transit — the sum,
    across every tip pool of that unit whose `contribution_status` is `CONTRIBUTED` and
    whose `distribution_status` is `PENDING`, of that pool's `total_contributed_cents`
    plus its `service_charge_tips_cents`."

    Design: Difficulty/compensating_invariant/pool_distribute_then_reverse_conserves_declared_tips
    """
    world = setup_texas_pool_world()
    declared_total = 34020 + 14020 + 0

    assert read_location(world["location"]["id"])["pending_pool_cents"] == 6505

    distribute_pool(world["pool"]["id"])

    retained = [
        read_shift(world["shift_server"]["id"])["retained_tips_cents"],
        read_shift(world["shift_bartender"]["id"])["retained_tips_cents"],
        read_shift(world["shift_busser"]["id"])["retained_tips_cents"],
    ]
    assert retained == [28917, 12618, 0]
    assert sum(retained) == 41535

    pool = read_pool(world["pool"]["id"])
    assert sum(retained) + pool["cc_fee_deducted_cents"] + pool["net_pool_cents"] == (
        declared_total
    ), "41535 retained plus 1052 of card fee plus 5453 of net pool is 48040"

    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0


def test_reversal_restores_the_same_total_without_rewriting_a_single_ledger_row(api):
    """The identity closes again on 48040 with a signed ledger that nets to zero.

    PRD §3.7: "That identity holds before a pool is created and holds again after it
    is reversed."
    PRD §1: "money is never silently rewritten"
    PRD §2.6: "A pool-allocation ledger row is immutable once written: it carries only
    `id` and `created_at`."

    Design: Difficulty/compensating_invariant/pool_distribute_then_reverse_conserves_declared_tips
    """
    world = setup_texas_pool_world()
    declared_total = 34020 + 14020 + 0

    distribute_pool(world["pool"]["id"])
    reverse_pool(world["pool"]["id"], reason="card fee wrongly passed through")

    retained = [
        read_shift(world["shift_server"]["id"])["retained_tips_cents"],
        read_shift(world["shift_bartender"]["id"])["retained_tips_cents"],
        read_shift(world["shift_busser"]["id"])["retained_tips_cents"],
    ]
    assert retained == [34020, 14020, 0]

    pool = read_pool(world["pool"]["id"])
    assert pool["cc_fee_deducted_cents"] == 0
    assert pool["net_pool_cents"] == 0
    assert sum(retained) + pool["cc_fee_deducted_cents"] + pool["net_pool_cents"] == (
        declared_total
    )

    all_rows = list_allocations_of(world["pool"]["id"])
    assert sum(row["allocated_cents"] for row in all_rows) == 0

    surviving, _meta = validate_paginated(
        api.list_pool_allocations(
            PREPARER,
            params={
                "shift_tip_pool_id": world["pool"]["id"],
                "entry_type": "DISTRIBUTION",
            },
        )
    )
    assert sorted(row["allocated_cents"] for row in surviving) == [940, 2005, 2508], (
        "compensation never rewrites history"
    )

    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0

    period = read_pay_period(world["pay_period"]["id"])
    assert period["status"] == "OPEN", "this instance never computed the week"
    assert list_pay_lines_of(world["pay_period"]["id"]) == []


# ---------------------------------------------------------------------------
# cross_entity_state_dependency /
# compute_pay_period_with_pending_pool_returns_pool_not_distributed
# ---------------------------------------------------------------------------
def _setup_pending_pool_two_shift_world() -> dict:
    """One Texas unit with an ACTIVE pool policy, a SERVER and a BARTENDER shift
    on 2026-08-04 both CLOSED and DECLARED, and a pool that was never distributed."""
    set_logical_clock()
    location = new_location(name="Plano Unit", service_charge_treatment="TIPS")
    role_server = new_job_role()
    role_bartender = new_job_role(
        code="BARTENDER",
        title="Bartender",
        pool_contribution_pct_bps=1000,
        pool_share_points=8,
    )
    employee_server = new_employee(
        location["id"], full_name="Sam Server", external_payroll_ref="D1"
    )
    employee_bartender = new_employee(
        location["id"], full_name="Bea Bartender", external_payroll_ref="D2"
    )
    new_role_assignment(employee_server["id"], role_server["id"])
    new_role_assignment(employee_bartender["id"], role_bartender["id"])
    policy = new_active_policy(location["id"], location["version"])
    pay_period = new_pay_period(location["id"])

    shift_server = new_shift(
        employee_server["id"],
        location["id"],
        role_server["id"],
        pay_period["id"],
        gross_sales_cents=120000,
        charged_sales_cents=90000,
        cc_processing_fee_bps=250,
    )
    shift_bartender = new_shift(
        employee_bartender["id"],
        location["id"],
        role_bartender["id"],
        pay_period["id"],
        gross_sales_cents=60000,
        charged_sales_cents=40000,
        cc_processing_fee_bps=250,
    )
    close_shift(shift_server["id"])
    close_shift(shift_bartender["id"])
    declare_shift_tips(shift_server["id"], employee_server["id"], 4000, 30020)
    declare_shift_tips(shift_bartender["id"], employee_bartender["id"], 2000, 12020)
    pool = new_pool(location["id"])

    return {
        "location": location,
        "policy": policy,
        "pay_period": pay_period,
        "shift_server": shift_server,
        "shift_bartender": shift_bartender,
        "pool": pool,
    }


def test_compute_is_refused_while_a_pool_for_the_week_is_still_pending(api):
    """Both shifts are DECLARED, so the objection is the undistributed pool alone.

    PRD §3.8: "Then, for every pairing of unit and operating date that has at least
    one `CLOSED` shift of this period, if that unit holds a policy whose `status` is
    `ACTIVE` then a pool for that pairing must exist whose `contribution_status` is
    `CONTRIBUTED` and whose `distribution_status` is `DISTRIBUTED`; a night that
    should have been pooled but was not yields `ERR_POOL_NOT_DISTRIBUTED`."
    PRD §2.10 rung 35: "Every `CLOSED` shift of the period has `declaration_status`
    either `DECLARED` or `AMENDED` — `ERR_UNDECLARED_SHIFT_IN_PERIOD`, 422, on
    `POST /pay-periods/{pay_period_id}/compute`."

    Design: Difficulty/cross_entity_state_dependency/compute_pay_period_with_pending_pool_returns_pool_not_distributed
    """
    world = _setup_pending_pool_two_shift_world()

    validate_error(
        api.compute_pay_period(world["pay_period"]["id"], PREPARER),
        ApiErrorId.ERR_POOL_NOT_DISTRIBUTED.value,
    )

    period = read_pay_period(world["pay_period"]["id"])
    assert period["status"] == "OPEN"
    assert period["compute_variant"] is None
    assert period["computed_by_user_id"] is None
    assert list_pay_lines_of(world["pay_period"]["id"]) == []

    pool = read_pool(world["pool"]["id"])
    assert pool["contribution_status"] == "CONTRIBUTED"
    assert pool["distribution_status"] == "PENDING"
    assert pool["total_contributed_cents"] == 6505


def test_distributing_the_pool_releases_the_money_and_lets_the_compute_through(api):
    """The unit's money in transit drops to zero and the identical compute succeeds.

    PRD §3.1: "A pool leaves the sum the instant its `distribution_status` becomes
    `DISTRIBUTED` and equally the instant either of its dimensions becomes
    `REVERSED`."
    PRD §3.8: "It sets the period's `compute_variant` to `WEEKLY_AGGREGATE` and its
    `computed_by_user_id` to the acting `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/compute_pay_period_with_pending_pool_returns_pool_not_distributed
    """
    world = _setup_pending_pool_two_shift_world()

    assert read_location(world["location"]["id"], ADMIN)["pending_pool_cents"] == 6505
    validate_error(
        api.compute_pay_period(world["pay_period"]["id"], PREPARER),
        ApiErrorId.ERR_POOL_NOT_DISTRIBUTED.value,
    )

    distribute_pool(world["pool"]["id"])
    assert read_location(world["location"]["id"], ADMIN)["pending_pool_cents"] == 0

    computed = validate_success(
        api.compute_pay_period(world["pay_period"]["id"], PREPARER)
    )
    assert computed["status"] == "COMPUTED"
    assert computed["compute_variant"] == "WEEKLY_AGGREGATE"
    assert len(list_pay_lines_of(world["pay_period"]["id"])) == 2
