"""Queue B — §1.6 error corners on the six pool-creation gates and the four distribution
gates: each refusal opened by exactly the action the PRD names, plus the two ways a pool
can hold money with no lawful home for it."""
from test_helpers import (
    COMPLIANCE,
    PREPARER,
    ApiErrorId,
    activate_policy,
    close_shift,
    create_shift_tip_pool_payload,
    declare_shift_tips,
    make_shift_manager_headers,
    new_draft_policy,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_role_assignment,
    new_shift,
    read_location,
    read_pool,
    read_shift,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DATE_1 = "2026-08-04T00:00:00Z"
DATE_2 = "2026-08-05T00:00:00Z"


def _gated_world() -> dict:
    """A Texas unit whose only policy is still DRAFT, with one CLOSED but UNDECLARED
    SERVER shift on 2026-08-04."""
    set_logical_clock()
    location = new_location()
    role = new_job_role()
    ana = new_employee(location["id"])
    new_role_assignment(ana["id"], role["id"])
    policy = new_draft_policy(location["id"], share_basis="POINTS_ONLY",
                             cc_fee_pass_through=False)
    period = new_pay_period(location["id"])
    manager = make_shift_manager_headers(ana["id"])
    shift = new_shift(
        ana["id"],
        location["id"],
        role["id"],
        period["id"],
        headers=manager,
        gross_sales_cents=50000,
        charged_sales_cents=40000,
    )
    close_shift(shift["id"], manager)
    return {
        "location": location,
        "role": role,
        "ana": ana,
        "policy": policy,
        "period": period,
        "shift": shift,
    }


def _pool_attempt(api, location_id: str, business_date: str = DATE_1):
    return api.create_shift_tip_pool(
        create_shift_tip_pool_payload(location_id, business_date=business_date), PREPARER
    )


# ---------------------------------------------------------------------------
# errors / pool_creation_policy_declaration_and_duplicate_guards_rejected
# ---------------------------------------------------------------------------
def test_each_pool_gate_is_opened_only_by_the_act_that_satisfies_it(api):
    """No policy, then no declaration, then no money: three refusals in the pinned order.

    PRD §3.7: "Six checks guard pool creation, in this order. The period covering
    `business_date` at that unit must be `OPEN`, failing which `ERR_PAY_PERIOD_NOT_OPEN`.
    Then no shift whose job role is a management role may contribute to or receive from the
    pool, so a pool that would be built solely from management shifts on either side is
    refused with `ERR_MANAGER_POOL_PARTICIPATION`. Then the unit must have exactly one
    policy whose `status` is `ACTIVE` to pin, failing which `ERR_NO_ACTIVE_POOL_POLICY`.
    Then every `CLOSED` shift at that unit on that `business_date` must have
    `declaration_status` of either `DECLARED` or `AMENDED` — an undeclared closed shift
    would make the pool wrong — failing which `ERR_UNDECLARED_SHIFT_IN_POOL`."
    PRD §3.7: "Finally the pool must hold money: `total_contributed_cents` plus
    `service_charge_tips_cents` must be strictly greater than 0, failing which
    `ERR_EMPTY_POOL_NO_CONTRIBUTIONS`."
    PRD §3.5: "The declaration dimension moves `UNDECLARED → DECLARED` on the first
    declaration, `DECLARED → AMENDED` on the second, and thereafter cycles
    `AMENDED → AMENDED` without bound for as long as the period stays `OPEN` and the shift
    stays unpooled."

    Design: Corner/errors/pool_creation_policy_declaration_and_duplicate_guards_rejected
    """
    world = _gated_world()

    validate_error(
        _pool_attempt(api, world["location"]["id"]),
        ApiErrorId.ERR_NO_ACTIVE_POOL_POLICY.value,
    )

    activate_policy(world["policy"]["id"], world["location"]["version"])
    validate_error(
        _pool_attempt(api, world["location"]["id"]),
        ApiErrorId.ERR_UNDECLARED_SHIFT_IN_POOL.value,
    )

    declare_shift_tips(world["shift"]["id"], world["ana"]["id"], 0, 0)
    validate_error(
        _pool_attempt(api, world["location"]["id"]),
        ApiErrorId.ERR_EMPTY_POOL_NO_CONTRIBUTIONS.value,
    )

    amended = declare_shift_tips(
        world["shift"]["id"], world["ana"]["id"], 4000, 0
    )
    assert amended["declaration_status"] == "AMENDED"
    assert amended["declaration_count"] == 2, "the amendment is the way past the gate"


def test_the_pool_that_finally_lands_pins_the_policy_and_debits_the_shift(api):
    """Fifteen percent of 4000 leaves the shift with 3400 and the unit pending 600.

    PRD §3.7: "The pool immediately pins the unit's governing policy:
    `tip_pool_policy_id` records which policy was `ACTIVE` at creation time and
    `policy_version_pinned` records the `version` that policy carried at that moment."
    PRD §3.7: "Each contributing shift then has its `pool_contribution_cents` set to that
    contribution, its `shift_tip_pool_id` stamped with the new pool, and its
    `retained_tips_cents` reset to the tips it received less the contribution."
    PRD §3.7: "On the pool itself, `total_contributed_cents` becomes the sum of the
    contributions across the contributing shifts and `contributing_shift_count` becomes the
    number of those shifts whose contribution came out greater than 0 — a stamped-in busser
    with a contribution of 0 is therefore not counted there."
    PRD §3.7: "Creation also absorbs the date's `TIPS`-treated service charges into
    `service_charge_tips_cents` as described in §3.6, leaves `cc_fee_deducted_cents`,
    `distributed_cents`, `participant_count` and `total_share_weight` at 0 with
    `distributed_at` and `reversed_at` null, and recomputes the unit's
    `pending_pool_cents` — which the new pool now joins, since it is `CONTRIBUTED` and
    `PENDING`."

    Design: Corner/errors/pool_creation_policy_declaration_and_duplicate_guards_rejected
    """
    world = _gated_world()
    activate_policy(world["policy"]["id"], world["location"]["version"])
    declare_shift_tips(world["shift"]["id"], world["ana"]["id"], 4000, 0)

    pool = validate_success(
        _pool_attempt(api, world["location"]["id"]), expected_status=201
    )
    assert pool["contribution_status"] == "CONTRIBUTED"
    assert pool["distribution_status"] == "PENDING"
    assert pool["total_contributed_cents"] == 600, "1500 bps of the 4000 received"
    assert pool["contributing_shift_count"] == 1
    assert pool["tip_pool_policy_id"] == world["policy"]["id"]
    assert pool["policy_version_pinned"] == 2, (
        "activation mutated the policy, so the pinned version is the post-activation one"
    )
    assert pool["distributed_at"] is None
    assert pool["reversed_at"] is None
    assert pool["participant_count"] == 0
    assert pool["total_share_weight"] == 0

    debited = read_shift(world["shift"]["id"])
    assert debited["shift_tip_pool_id"] == pool["id"]
    assert debited["pool_contribution_cents"] == 600
    assert debited["retained_tips_cents"] == 3400
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 600


def test_one_contributed_pool_per_unit_and_operating_date(api):
    """The same location and business_date twice is a conflict, not a second pool.

    PRD §3.7: "Then no pool whose `contribution_status` is `CONTRIBUTED` may already exist
    for the same unit and `business_date`, failing which `ERR_POOL_DATE_DUPLICATE`; note
    that a pool whose contribution side has been reversed does not block a fresh one, which
    is what makes reversal followed by rebuild a usable correction path."
    PRD §3.7: "A tip pool is computed once per operating date per unit."

    Design: Corner/errors/pool_creation_policy_declaration_and_duplicate_guards_rejected
    """
    world = _gated_world()
    activate_policy(world["policy"]["id"], world["location"]["version"])
    declare_shift_tips(world["shift"]["id"], world["ana"]["id"], 4000, 0)
    first = validate_success(
        _pool_attempt(api, world["location"]["id"]), expected_status=201
    )

    validate_error(
        _pool_attempt(api, world["location"]["id"]),
        ApiErrorId.ERR_POOL_DATE_DUPLICATE.value,
    )

    rows, meta = validate_paginated(
        api.list_shift_tip_pools(
            PREPARER, params={"location_id": world["location"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


# ---------------------------------------------------------------------------
# errors / manager_only_and_participantless_pools_rejected
# ---------------------------------------------------------------------------
def _two_date_world() -> dict:
    """A Texas unit under an ACTIVE TIPPED_ONLY / POINTS_ONLY policy where a tipped
    working manager declares 4000 on 2026-08-04 and a pointless prep cook declares 4000 on
    2026-08-05."""
    set_logical_clock()
    location = new_location()
    role_mgr = new_job_role(
        code="MGR",
        title="Working Manager",
        is_management=True,
        pool_contribution_pct_bps=0,
        pool_share_points=0,
        side_work_eligible=False,
    )
    role_prep = new_job_role(
        code="PREP",
        title="Prep Cook",
        pool_share_points=0,
        side_work_eligible=False,
    )
    mia = new_employee(location["id"], full_name="Mia Duarte")
    pia = new_employee(location["id"], full_name="Pia Nunes", external_payroll_ref="E2")
    new_role_assignment(mia["id"], role_mgr["id"])
    new_role_assignment(pia["id"], role_prep["id"])
    policy = new_draft_policy(
        location["id"], share_basis="POINTS_ONLY", cc_fee_pass_through=False
    )
    activate_policy(policy["id"], location["version"])
    period = new_pay_period(location["id"])
    manager = make_shift_manager_headers(mia["id"])

    world = {
        "location": location,
        "role_mgr": role_mgr,
        "role_prep": role_prep,
        "mia": mia,
        "pia": pia,
        "policy": policy,
        "period": period,
    }
    for key, employee, role, date, start, end in (
        ("mia_shift", mia, role_mgr, DATE_1, "2026-08-04T16:00:00Z", "2026-08-05T00:00:00Z"),
        ("pia_shift", pia, role_prep, DATE_2, "2026-08-05T16:00:00Z", "2026-08-06T00:00:00Z"),
    ):
        shift = new_shift(
            employee["id"],
            location["id"],
            role["id"],
            period["id"],
            headers=manager,
            business_date=date,
            start_at=start,
            end_at=end,
            gross_sales_cents=50000,
            charged_sales_cents=40000,
        )
        close_shift(shift["id"], manager)
        declare_shift_tips(shift["id"], employee["id"], 4000, 0)
        world[key] = shift
    return world


def test_a_tipped_working_manager_is_still_no_pool(api):
    """Management is an unconditional exclusion, so her date has no pool to build at all.

    PRD §3.7: "Then no shift whose job role is a management role may contribute to or
    receive from the pool, so a pool that would be built solely from management shifts on
    either side is refused with `ERR_MANAGER_POOL_PARTICIPATION`."
    PRD §3.7: "Management shifts are excluded from the input set unconditionally."
    PRD §3.7: "Finally the pool must hold money: `total_contributed_cents` plus
    `service_charge_tips_cents` must be strictly greater than 0, failing which
    `ERR_EMPTY_POOL_NO_CONTRIBUTIONS`."
    PRD §3.5: "While the shift is unpooled its `pool_contribution_cents` is 0, so its
    retained tips are simply everything it declared."

    Design: Corner/errors/manager_only_and_participantless_pools_rejected
    """
    world = _two_date_world()

    validate_error(
        _pool_attempt(api, world["location"]["id"], DATE_1),
        ApiErrorId.ERR_MANAGER_POOL_PARTICIPATION.value,
    )

    untouched = read_shift(world["mia_shift"]["id"])
    assert untouched["shift_tip_pool_id"] is None
    assert untouched["pool_contribution_cents"] == 0
    assert untouched["retained_tips_cents"] == 4000, (
        "her tips are hers; the manager guard precedes the empty-pool guard"
    )
    _rows, meta = validate_paginated(
        api.list_shift_tip_pools(
            PREPARER, params={"location_id": world["location"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_contributor_with_no_share_points_strands_the_money_until_reversal(api):
    """The prep cook funds a pool she cannot receive from, and only reversal returns it.

    PRD §3.7: "The shifts that feed the pool are those at the requested unit and
    `business_date` whose `time_status` is `CLOSED`, whose `declaration_status` is
    `DECLARED` or `AMENDED`, and whose `shift_tip_pool_id` is still null, and whose job role
    is not a management role and carries either a `pool_contribution_pct_bps` greater than 0
    or a `pool_share_points` greater than 0; and additionally, where the pinned policy's
    `pool_type` is `TIPPED_ONLY`, whose job role's `tip_status` is `TIPPED`."
    PRD §3.7: "The participants — the shifts eligible to receive — are those whose
    `shift_tip_pool_id` names this pool, whose `time_status` is `CLOSED`, whose job role is
    not a management role and carries a `pool_share_points` greater than 0, and, where the
    pinned policy's `pool_type` is `TIPPED_ONLY`, whose job role's `tip_status` is
    `TIPPED`."
    PRD §3.7: "Four checks guard a distribution, in this order: the pool's
    `distribution_status` must be `PENDING`, so distributing a pool already `DISTRIBUTED`
    or already `REVERSED` yields `ERR_POOL_ALREADY_DISTRIBUTED`; the pool's
    `contribution_status` must be `CONTRIBUTED`, failing which `ERR_POOL_REVERSED`;
    `total_contributed_cents` plus `service_charge_tips_cents` must be strictly greater than
    0, failing which `ERR_EMPTY_POOL_NO_CONTRIBUTIONS`; and `participant_count` must be
    strictly greater than 0, failing which `ERR_NO_ELIGIBLE_PARTICIPANTS`."
    PRD §3.7: "That last check is what stops money being stranded in a pool that has
    contributors but nobody eligible to receive."

    Design: Corner/errors/manager_only_and_participantless_pools_rejected
    """
    world = _two_date_world()

    pool = validate_success(
        _pool_attempt(api, world["location"]["id"], DATE_2), expected_status=201
    )
    assert pool["total_contributed_cents"] == 600, "1500 bps still applies to her tips"
    assert pool["contributing_shift_count"] == 1
    assert pool["participant_count"] == 0

    validate_error(
        api.distribute_shift_tip_pool(pool["id"], PREPARER),
        ApiErrorId.ERR_NO_ELIGIBLE_PARTICIPANTS.value,
    )
    stranded = read_pool(pool["id"])
    assert stranded["distribution_status"] == "PENDING"
    assert stranded["distributed_cents"] == 0
    assert stranded["distributed_at"] is None
    assert stranded["cc_fee_deducted_cents"] == 0
    _rows, meta = validate_paginated(
        api.list_pool_allocations(PREPARER, params={"shift_tip_pool_id": pool["id"]})
    )
    assert meta["total_count"] == 0


def test_reversal_is_the_only_exit_for_a_pool_nobody_may_receive_from(api):
    """Both dimensions go to REVERSED, the shift is whole again and no ledger row appears.

    PRD §3.7: "A pool whose `distribution_status` was still `PENDING` moves
    `PENDING → REVERSED` and appends no ledger rows at all, because there are no
    `DISTRIBUTION` rows to negate; only the contribution side needs unwinding."
    PRD §3.7: "Third, every shift whose `shift_tip_pool_id` names this pool has that link
    cleared back to null, its `pool_contribution_cents` zeroed, and its
    `retained_tips_cents` restored to `declared_cash_tips_cents` plus
    `declared_charged_tips_cents` — the shift is whole again and free to be declared,
    pooled or voided."
    PRD §3.7: "Fifth, the unit's `pending_pool_cents` is recomputed over that unit's
    surviving `CONTRIBUTED` and `PENDING` pools, and each affected period's
    `total_credited_minutes` and `gross_receipts_cents` are recomputed from its surviving
    `CLOSED` shifts."
    PRD §3.7: "Both starting points land in the terminal `REVERSED`."

    Design: Corner/errors/manager_only_and_participantless_pools_rejected
    """
    world = _two_date_world()
    pool = validate_success(
        _pool_attempt(api, world["location"]["id"], DATE_2), expected_status=201
    )
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 600

    reversed_pool = validate_success(
        api.reverse_shift_tip_pool(
            pool["id"], COMPLIANCE, {"reason": "no eligible recipients"}
        )
    )
    assert reversed_pool["contribution_status"] == "REVERSED"
    assert reversed_pool["distribution_status"] == "REVERSED"
    assert reversed_pool["total_contributed_cents"] == 0
    assert reversed_pool["net_pool_cents"] == 0

    restored = read_shift(world["pia_shift"]["id"])
    assert restored["shift_tip_pool_id"] is None
    assert restored["pool_contribution_cents"] == 0
    assert restored["retained_tips_cents"] == 4000

    _rows, meta = validate_paginated(
        api.list_pool_allocations(PREPARER, params={"shift_tip_pool_id": pool["id"]})
    )
    assert meta["total_count"] == 0, "a never-distributed pool has nothing to negate"
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0
