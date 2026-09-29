"""Queue B — §1.2 state machines on the shift, the pool and the policy: declared
initial states, replayed triggers, terminal lockdown and the self-looping declaration."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    PREPARER,
    ApiErrorId,
    activate_policy,
    assert_instant_equals,
    close_shift,
    declare_shift_tips,
    declare_tips_payload,
    distribute_pool,
    make_employee_headers,
    make_shift_manager_headers,
    new_active_policy,
    new_draft_policy,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_pool,
    new_role_assignment,
    new_shift,
    read_employee,
    read_location,
    read_pay_period,
    read_policy,
    read_pool,
    read_shift,
    set_logical_clock,
    setup_texas_wage_world,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"


def _pooled_world(distribute: bool = False) -> dict:
    """A Texas unit under an ACTIVE TIPPED_ONLY / TIPS_RECEIVED_PCT / POINTS_ONLY
    policy with card fees switched off, one CLOSED shift declaring 4000 cash tips,
    and the 2026-08-04 pool built from it."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    employee = new_employee(location["id"])
    new_role_assignment(employee["id"], role_server["id"])
    new_active_policy(
        location["id"],
        location["version"],
        share_basis="POINTS_ONLY",
        cc_fee_pass_through=False,
    )
    pay_period = new_pay_period(location["id"])
    shift = new_shift(
        employee["id"], location["id"], role_server["id"], pay_period["id"]
    )
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], employee["id"], 4000, 0)
    pool = new_pool(location["id"])
    if distribute:
        distribute_pool(pool["id"])
    return {
        "location": location,
        "role_server": role_server,
        "employee": employee,
        "pay_period": pay_period,
        "shift": shift,
        "pool": pool,
    }


# ---------------------------------------------------------------------------
# initial_state
# ---------------------------------------------------------------------------
def test_three_machines_are_born_in_their_declared_initial_states(api):
    """A shift is born on two dimensions at once and nothing derived is populated yet.

    PRD §3.4: "A newly recorded shift starts with `time_status` `OPEN` and
    `declaration_status` `UNDECLARED`, with `shift_tip_pool_id` null and with
    `declared_cash_tips_cents`, `declared_charged_tips_cents`, `declaration_count`,
    `non_tip_credit_minutes`, `tip_credit_eligible_minutes`,
    `pool_contribution_cents`, `retained_tips_cents` and `shift_tip_credit_cents` all
    at 0."
    PRD §3.3: "A drafted policy has `status` `DRAFT` and `activated_at` null."
    PRD §3.4: "A newly opened period has `status` `OPEN`, `compute_variant` null,
    `computed_by_user_id` null, `approved_by_user_id` null, and every rollup at 0."
    PRD §3.4: "`total_credited_minutes` is the sum of `scheduled_minutes` over the
    period's shifts whose `time_status` is `CLOSED`."

    Design: Corner/state_machines/shift_period_and_policy_all_start_in_their_declared_initial_states
    """
    world = setup_texas_wage_world()

    period = world["pay_period"]
    assert period["status"] == "OPEN"
    assert period["compute_variant"] is None

    policy = new_draft_policy(world["location"]["id"])
    assert policy["status"] == "DRAFT"
    assert policy["activated_at"] is None

    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        period["id"],
        side_work_minutes=0,
        max_continuous_side_work_minutes=0,
    )
    assert shift["time_status"] == "OPEN"
    assert shift["declaration_status"] == "UNDECLARED"
    assert shift["scheduled_minutes"] == 480
    assert shift["non_tip_credit_minutes"] == 0
    assert shift["tip_credit_eligible_minutes"] == 0, (
        "classification happens at close, not at recording"
    )
    assert shift["declaration_count"] == 0
    assert shift["declared_cash_tips_cents"] == 0
    assert shift["declared_charged_tips_cents"] == 0
    assert shift["shift_tip_pool_id"] is None
    assert shift["pool_contribution_cents"] == 0
    assert shift["retained_tips_cents"] == 0
    assert shift["shift_tip_credit_cents"] == 0
    assert shift["version"] == 1

    assert read_pay_period(period["id"])["total_credited_minutes"] == 0, (
        "an OPEN shift credits no minutes"
    )


# ---------------------------------------------------------------------------
# invalid_transition — close
# ---------------------------------------------------------------------------
def test_closing_an_already_closed_shift_neither_errors_late_nor_double_counts(api):
    """CLOSED is not a from-state of close, and the rejected replay reclassifies nothing.

    PRD §3.5: "Two preconditions apply, in this order: the shift's `time_status` must
    be `OPEN`, so that a shift already `CLOSED` or already `VOIDED` yields
    `ERR_SHIFT_NOT_OPEN`; and the shift's pay period must still be `OPEN`, failing
    which `ERR_PAY_PERIOD_NOT_OPEN`."
    PRD §3.5: "Closing recomputes the period's `total_credited_minutes` and
    `gross_receipts_cents`, since the shift has only now become one of the period's
    `CLOSED` shifts."
    PRD §3.5: "`tip_credit_eligible_minutes` is then `scheduled_minutes` minus
    `non_tip_credit_minutes`, and it is the only quantity a tip credit may ever be
    claimed against."

    Design: Corner/state_machines/close_an_already_closed_shift_returns_shift_not_open
    """
    world = setup_texas_wage_world()
    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        side_work_minutes=0,
        max_continuous_side_work_minutes=0,
    )
    close_shift(shift["id"])

    validate_error(
        api.close_shift(shift["id"], PREPARER), ApiErrorId.ERR_SHIFT_NOT_OPEN.value
    )

    after = read_shift(shift["id"])
    assert after["time_status"] == "CLOSED"
    assert after["tip_credit_eligible_minutes"] == 480
    assert after["non_tip_credit_minutes"] == 0
    assert after["version"] == 2, "create then close, and the refused replay adds none"

    assert read_pay_period(world["pay_period"]["id"])["total_credited_minutes"] == 480, (
        "not 960: the rollup is recomputed from the CLOSED set, never incremented"
    )


# ---------------------------------------------------------------------------
# idempotency — distribute
# ---------------------------------------------------------------------------
def test_distributing_a_distributed_pool_is_a_conflict_not_a_second_payout(api):
    """The replay is a 409 and the ledger still holds exactly one 600-cent row.

    PRD §3.7: "Four checks guard a distribution, in this order: the pool's
    `distribution_status` must be `PENDING`, so distributing a pool already
    `DISTRIBUTED` or already `REVERSED` yields `ERR_POOL_ALREADY_DISTRIBUTED`; the
    pool's `contribution_status` must be `CONTRIBUTED`, failing which
    `ERR_POOL_REVERSED`; `total_contributed_cents` plus `service_charge_tips_cents`
    must be strictly greater than 0, failing which
    `ERR_EMPTY_POOL_NO_CONTRIBUTIONS`; and `participant_count` must be strictly
    greater than 0, failing which `ERR_NO_ELIGIBLE_PARTICIPANTS`."
    PRD §3.7: "Distribution appends exactly one pool-allocation ledger row per
    participant, each carrying its `shift_tip_pool_id`, the receiving `employee_id`,
    the earning `shift_id`, an `entry_type` of `DISTRIBUTION`, the participant's
    `share_weight`, its `allocated_cents` — the base share plus the leftover cent
    where won — its `remainder_cent_awarded` flag, and a copy of the pool's
    `business_date`, carried on the row so that allocations can be read and filtered
    without joining back to the pool."
    PRD §3.2: "Hiring also sets `trailing_pool_receipts_cents` to 0; thereafter it is
    the running sum of `allocated_cents` over every pool-allocation ledger row naming
    this employee, counting both `DISTRIBUTION` rows and `REVERSAL` rows, so that a
    reversed pool leaves it back where it started."

    Design: Corner/state_machines/distribute_an_already_distributed_pool_returns_pool_already_distributed
    """
    world = _pooled_world(distribute=True)

    validate_error(
        api.distribute_shift_tip_pool(world["pool"]["id"], PREPARER),
        ApiErrorId.ERR_POOL_ALREADY_DISTRIBUTED.value,
    )

    pool = read_pool(world["pool"]["id"])
    assert pool["distribution_status"] == "DISTRIBUTED"
    assert pool["net_pool_cents"] == 600
    assert pool["distributed_cents"] == 600
    assert pool["participant_count"] == 1

    _rows, meta = validate_paginated(
        api.list_pool_allocations(
            PREPARER, params={"shift_tip_pool_id": world["pool"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "no second ledger row was appended"

    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0
    assert read_employee(world["employee"]["id"])["trailing_pool_receipts_cents"] == 600, (
        "the recipient was credited once, not twice"
    )


# ---------------------------------------------------------------------------
# terminal_state_lockdown — reverse
# ---------------------------------------------------------------------------
def test_reversed_is_terminal_on_both_pool_dimensions_under_one_error_id(api):
    """A second reverse and a first distribute are each refused by their own rung.

    PRD §3.7: "Reversal also requires that `contribution_status` still be
    `CONTRIBUTED`, failing which `ERR_POOL_REVERSED`."
    PRD §3.7: "the pool's `distribution_status` must be `PENDING`, so distributing a
    pool already `DISTRIBUTED` or already `REVERSED` yields
    `ERR_POOL_ALREADY_DISTRIBUTED`"
    PRD §3.7: "First, `contribution_status` moves `CONTRIBUTED → REVERSED` and
    `reversed_at` is stamped with the current logical instant;
    `total_contributed_cents`, `service_charge_tips_cents`, `cc_fee_deducted_cents`
    and `net_pool_cents` all become 0 as a consequence."
    PRD §3.7: "A pool whose `distribution_status` was still `PENDING` moves `PENDING
    → REVERSED` and appends no ledger rows at all, because there are no
    `DISTRIBUTION` rows to negate; only the contribution side needs unwinding."
    PRD §3.7: "Third, every shift whose `shift_tip_pool_id` names this pool has that
    link cleared back to null, its `pool_contribution_cents` zeroed, and its
    `retained_tips_cents` restored to `declared_cash_tips_cents` plus
    `declared_charged_tips_cents` — the shift is whole again and free to be declared,
    pooled or voided."

    Design: Corner/state_machines/reverse_and_distribute_a_reversed_pool_both_return_pool_reversed
    """
    world = _pooled_world()
    pool_id = world["pool"]["id"]
    validate_success(
        api.reverse_shift_tip_pool(
            pool_id, COMPLIANCE, {"reason": "policy misconfiguration found before payout"}
        )
    )

    validate_error(
        api.reverse_shift_tip_pool(pool_id, COMPLIANCE, {"reason": "second attempt"}),
        ApiErrorId.ERR_POOL_REVERSED.value,
    )
    validate_error(
        api.distribute_shift_tip_pool(pool_id, PREPARER),
        ApiErrorId.ERR_POOL_ALREADY_DISTRIBUTED.value,
    )

    pool = read_pool(pool_id)
    assert pool["contribution_status"] == "REVERSED"
    assert pool["distribution_status"] == "REVERSED"
    assert pool["total_contributed_cents"] == 0
    assert pool["net_pool_cents"] == 0
    assert pool["distributed_cents"] == 0
    assert_instant_equals(pool["reversed_at"], CLOCK, "reversed_at")

    shift = read_shift(world["shift"]["id"])
    assert shift["pool_contribution_cents"] == 0
    assert shift["retained_tips_cents"] == 4000, "the full declared amount restored"
    assert shift["shift_tip_pool_id"] is None

    _rows, meta = validate_paginated(
        api.list_pool_allocations(PREPARER, params={"shift_tip_pool_id": pool_id})
    )
    assert meta["total_count"] == 0, (
        "a pool reversed while PENDING wrote no DISTRIBUTION row, so it needs no "
        "REVERSAL row either"
    )
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0


# ---------------------------------------------------------------------------
# invalid_transition — activate
# ---------------------------------------------------------------------------
def test_replayed_activation_is_a_state_conflict_even_with_a_fresh_version(api):
    """The DRAFT check is reached before the version check, so the 409 is not a 412.

    PRD §3.3: "Activation drives the policy from `DRAFT` to `ACTIVE` and is guarded
    by four checks, evaluated in this order. The policy's `status` must be `DRAFT` —
    activating one already `ACTIVE` or already `SUPERSEDED` yields
    `ERR_POLICY_NOT_DRAFT`. Then the supplied `expected_location_version` must equal
    the unit's stored `version`, failing which the activation is refused with
    `ERR_STALE_LOCATION_VERSION`."
    PRD §3.3: "First, the newly active policy's `activated_at` is stamped with the
    current logical instant."
    PRD §3.3: "Fifth, the unit's `version` is incremented by exactly 1, so any second
    activation replayed with the same `expected_location_version` fails."

    Design: Corner/state_machines/activate_an_already_active_policy_returns_policy_not_draft
    """
    set_logical_clock()
    location = new_location()
    policy = new_draft_policy(location["id"])
    activate_policy(policy["id"], location["version"])

    refreshed = read_location(location["id"])
    assert refreshed["version"] == 2, "activation is the sole writer of a unit's version"

    validate_error(
        api.activate_tip_pool_policy(
            policy["id"], {"expected_location_version": refreshed["version"]}, COMPLIANCE
        ),
        ApiErrorId.ERR_POLICY_NOT_DRAFT.value,
    )

    stored = read_policy(policy["id"])
    assert stored["status"] == "ACTIVE"
    assert_instant_equals(stored["activated_at"], CLOCK, "activated_at")
    assert read_location(location["id"])["version"] == 2, (
        "the rejected call moved nothing"
    )

    _rows, meta = validate_paginated(
        api.list_tip_pool_policies(
            ADMIN, params={"location_id": location["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# valid_transition — the declaration self-loop
# ---------------------------------------------------------------------------
def test_a_third_declaration_re_enters_amended_and_keeps_counting(api):
    """AMENDED loops onto itself while the timekeeping dimension never moves.

    PRD §3.5: "The declaration dimension moves `UNDECLARED → DECLARED` on the first
    declaration, `DECLARED → AMENDED` on the second, and thereafter cycles `AMENDED →
    AMENDED` without bound for as long as the period stays `OPEN` and the shift stays
    unpooled."
    PRD §3.5: "Each of the three transitions writes the two declared amounts,
    overwriting whatever was there before, increments `declaration_count` by 1 — so a
    `declaration_count` of 1 marks an original declaration and 2 or more marks
    amendments — and recomputes `retained_tips_cents`."
    PRD §3.4: "The two status dimensions are genuinely independent: timekeeping
    advances without regard to whether tips have been declared, and declaration
    advances without regard to anything but the timekeeping state it requires as a
    precondition."
    PRD §2.6: "**`version`** (integer): a monotonically increasing counter that
    starts at 1 when the row is created and increases by exactly 1 on each subsequent
    mutation of the row."

    Design: Corner/state_machines/amend_a_declaration_twice_keeps_amended_and_counts_every_declaration
    """
    world = setup_texas_wage_world()
    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
        gross_sales_cents=0,
        charged_sales_cents=0,
    )
    close_shift(shift["id"])
    first = declare_shift_tips(shift["id"], world["employee"]["id"], 1000, 0)
    assert first["declaration_status"] == "DECLARED"
    assert first["declaration_count"] == 1

    second = declare_shift_tips(shift["id"], world["employee"]["id"], 2000, 0)
    assert second["declaration_status"] == "AMENDED"
    assert second["declaration_count"] == 2
    assert second["declared_cash_tips_cents"] == 2000
    assert second["retained_tips_cents"] == 2000

    third = validate_success(
        api.declare_tips(
            shift["id"],
            declare_tips_payload(3000, 0),
            make_shift_manager_headers(world["employee"]["id"]),
        )
    )
    assert third["declaration_status"] == "AMENDED", "the loop re-enters, it does not error"
    assert third["declaration_count"] == 3
    assert third["declared_cash_tips_cents"] == 3000
    assert third["retained_tips_cents"] == 3000

    assert third["time_status"] == "CLOSED"
    assert third["tip_credit_eligible_minutes"] == 480
    assert third["version"] == 5, (
        "create 1, close 2, declare 3, amend 4, amend 5 — one bump per mutation"
    )
    assert read_pay_period(world["pay_period"]["id"])["total_credited_minutes"] == 480


# ---------------------------------------------------------------------------
# precondition_enforcement — the pooled freeze
# ---------------------------------------------------------------------------
def test_a_pooled_shift_may_not_restate_the_tips_the_pool_was_built_from(api):
    """The freeze is checked ahead of every amount rule and leaves the split intact.

    PRD §3.5: "Amendment additionally requires that the shift not have been folded
    into a pool: once `shift_tip_pool_id` is set, the declaration is frozen and any
    further declaration is refused with `ERR_SHIFT_ALREADY_POOLED`, because the pool
    has already been computed from the numbers as they stood."
    PRD §3.7: "Each contributing shift then has its `pool_contribution_cents` set to
    that contribution, its `shift_tip_pool_id` stamped with the new pool, and its
    `retained_tips_cents` reset to the tips it received less the contribution."
    PRD §3.7: "On the pool itself, `total_contributed_cents` becomes the sum of the
    contributions across the contributing shifts and `contributing_shift_count`
    becomes the number of those shifts whose contribution came out greater than 0 — a
    stamped-in busser with a contribution of 0 is therefore not counted there."

    Design: Corner/state_machines/amend_a_declaration_on_a_pooled_shift_returns_shift_already_pooled
    """
    world = _pooled_world()

    validate_error(
        api.declare_tips(
            world["shift"]["id"],
            declare_tips_payload(9000, 0),
            make_employee_headers(world["employee"]["id"]),
        ),
        ApiErrorId.ERR_SHIFT_ALREADY_POOLED.value,
    )

    shift = read_shift(world["shift"]["id"])
    assert shift["declared_cash_tips_cents"] == 4000
    assert shift["declaration_count"] == 1
    assert shift["declaration_status"] == "DECLARED"
    assert shift["pool_contribution_cents"] == 600, "1500 bps of the 4000 declared"
    assert shift["retained_tips_cents"] == 3400
    assert shift["shift_tip_pool_id"] == world["pool"]["id"]

    pool = read_pool(world["pool"]["id"])
    assert pool["total_contributed_cents"] == 600
    assert pool["contributing_shift_count"] == 1
    assert pool["contribution_status"] == "CONTRIBUTED"
    assert pool["distribution_status"] == "PENDING"

    assert read_location(world["location"]["id"])["pending_pool_cents"] == 600
