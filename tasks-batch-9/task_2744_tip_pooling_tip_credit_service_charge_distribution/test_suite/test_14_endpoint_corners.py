"""Queue B — §1.5 endpoint corners: the role-assignment write/read triad, the
append-only allocation ledger, the void that only a reversal unlocks, and the logical
clock that stamps every timestamp the service writes."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    PREPARER,
    ApiErrorId,
    activate_policy,
    assert_instant_equals,
    assert_timestamp_format,
    close_shift,
    declare_shift_tips,
    distribute_pool,
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
    read_pool,
    read_shift,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"
LATER_CLOCK = "2026-08-11T09:30:00Z"
DATE_1 = "2026-08-04T00:00:00Z"


def _pooled_world(distribute: bool = False) -> dict:
    """A Texas unit under an ACTIVE TIPPED_ONLY / TIPS_RECEIVED_PCT / POINTS_ONLY
    policy with card fees off, one CLOSED and DECLARED 480-minute shift on 2026-08-04
    declaring 4000 cash tips, and the 2026-08-04 pool built from it."""
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
        "employee": employee,
        "pay_period": pay_period,
        "shift": shift,
        "pool": pool,
    }


def _allocations(api, **params) -> tuple:
    return validate_paginated(api.list_pool_allocations(PREPARER, params=params))


# ---------------------------------------------------------------------------
# endpoints / role_assignment_crud_links_an_employee_to_two_jobs_and_derives_dual_job
# ---------------------------------------------------------------------------
def test_two_jobs_for_one_employee_neither_collide_nor_imply_a_dual_job(api):
    """The overlap guard is scoped to a role, and the dual-jobs flag to a tip status.

    PRD §3.2: "First, the new assignment's date interval — treating a null
    `effective_to` as extending indefinitely — may not intersect the interval of any
    existing assignment for the same `employee_id` and the same `job_role_id`; an
    intersection is refused with `ERR_ASSIGNMENT_OVERLAP`."
    PRD §3.2: "`dual_job` is true on an assignment when the same employee holds another
    assignment whose date interval intersects this one and whose job role carries a
    different `tip_status` — a bartender who also works mornings as a prep cook, for
    instance."
    PRD §3.2: "Recording a new assignment therefore inspects the employee's other
    overlapping assignments and, where the tipped classifications differ, flips
    `dual_job` to true on both the new row and the pre-existing row it overlaps."
    PRD §3.2: "`dual_job` is false by default and on an employee holding a single job it
    stays false."
    PRD §3.2: "`effective_to` is the last such date and may be omitted, in which case
    the assignment is open-ended."
    PRD §3.2: "`is_primary`, false unless supplied, marks which job is the employee's
    principal one when they hold more than one."

    Design: Corner/endpoints/role_assignment_crud_links_an_employee_to_two_jobs_and_derives_dual_job
    """
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    role_bar = new_job_role(
        code="BARTENDER",
        title="Bartender",
        pool_contribution_pct_bps=1000,
        pool_share_points=8,
    )
    employee = new_employee(location["id"])
    pay_period = new_pay_period(location["id"])

    asg_server = new_role_assignment(employee["id"], role_server["id"])
    assert asg_server["effective_to"] is None, "an omitted effective_to is open-ended"
    assert asg_server["is_primary"] is True
    assert asg_server["dual_job"] is False, "one job only, so far"
    assert asg_server["version"] == 1
    assert_instant_equals(asg_server["created_at"], CLOCK, "created_at")

    asg_bar = new_role_assignment(
        employee["id"], role_bar["id"], is_primary=False
    )
    assert asg_bar["is_primary"] is False
    assert asg_bar["dual_job"] is False, (
        "SERVER and BARTENDER are both TIPPED, so the classifications do not differ"
    )
    assert (
        validate_success(api.get_role_assignment(asg_server["id"], PREPARER))["dual_job"]
        is False
    ), "the pre-existing row is re-evaluated too, and it also stays false"

    round_trip = validate_success(api.get_role_assignment(asg_server["id"], PREPARER))
    for field in (
        "id",
        "employee_id",
        "job_role_id",
        "effective_from",
        "tip_credit_notice_acknowledged_at",
        "is_primary",
        "dual_job",
        "version",
        "created_at",
    ):
        assert round_trip[field] == asg_server[field], f"{field} did not round-trip"

    rows, meta = validate_paginated(
        api.list_role_assignments(PREPARER, params={"employee_id": employee["id"]})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["id"] for row in rows} == {asg_server["id"], asg_bar["id"]}

    rows, meta = validate_paginated(
        api.list_role_assignments(
            PREPARER,
            params={"employee_id": employee["id"], "job_role_id": role_bar["id"]},
        )
    )
    assert meta["total_count"] == 1, "the two filters combine conjunctively"
    assert rows[0]["id"] == asg_bar["id"]

    page, meta = validate_paginated(
        api.list_role_assignments(
            PREPARER, params={"employee_id": employee["id"], "limit": 1, "offset": 1}
        )
    )
    assert len(page) == 1
    assert meta["total_count"] == 2, "the count is of matches, not of the page"
    assert meta["has_more"] is False, "offset 1 plus one row exhausts the two matches"

    role_prep = new_job_role(
        code="PREP_COOK",
        title="Prep Cook",
        tip_status="NON_TIPPED",
        pool_contribution_pct_bps=0,
        pool_share_points=0,
        side_work_eligible=False,
    )
    asg_prep = new_role_assignment(employee["id"], role_prep["id"], is_primary=False)
    assert asg_prep["dual_job"] is True, "a NON_TIPPED job beside two TIPPED ones"
    for assignment_id in (asg_server["id"], asg_bar["id"]):
        refreshed = validate_success(api.get_role_assignment(assignment_id, PREPARER))
        assert refreshed["dual_job"] is True, (
            "the flag is flipped on the pre-existing rows the new one overlaps"
        )

    shift_bar = new_shift(
        employee["id"],
        location["id"],
        role_bar["id"],
        pay_period["id"],
        start_at="2026-08-04T08:00:00Z",
        end_at="2026-08-04T16:00:00Z",
    )
    shift_server = new_shift(
        employee["id"], location["id"], role_server["id"], pay_period["id"]
    )
    assert read_shift(shift_bar["id"])["job_role_id"] == role_bar["id"]
    assert read_shift(shift_server["id"])["job_role_id"] == role_server["id"]
    assert shift_server["start_at"].startswith("2026-08-04T16:00:00"), (
        "the second shift begins exactly where the first ended"
    )


# ---------------------------------------------------------------------------
# endpoints / pool_allocation_ledger_is_append_only_and_nets_to_zero_after_a_reversal
# ---------------------------------------------------------------------------
def test_the_reversal_appends_the_exact_negation_and_edits_nothing(api):
    """Two rows where there was one, +600 beside -600, and the first row untouched.

    PRD §3.7: "A pool whose `distribution_status` was `DISTRIBUTED` moves `DISTRIBUTED →
    REVERSED`, and for each `DISTRIBUTION` row of the pool the server appends one
    further ledger row whose `entry_type` is `REVERSAL` and whose `allocated_cents` is
    the exact negation of that `DISTRIBUTION` row's amount; the original `DISTRIBUTION`
    rows themselves are never mutated, so every recipient's net sum of `allocated_cents`
    for this pool returns to 0 and `distributed_cents` returns to 0 with it."
    PRD §3.7: "Distribution appends exactly one pool-allocation ledger row per
    participant, each carrying its `shift_tip_pool_id`, the receiving `employee_id`, the
    earning `shift_id`, an `entry_type` of `DISTRIBUTION`, the participant's
    `share_weight`, its `allocated_cents` — the base share plus the leftover cent where
    won — its `remainder_cent_awarded` flag, and a copy of the pool's `business_date`,
    carried on the row so that allocations can be read and filtered without joining back
    to the pool."
    PRD §2.6: "A pool-allocation ledger row is immutable once written: it carries only
    `id` and `created_at`. It has no `updated_at` field and no `version` field at all,
    and neither field appears in its response payload."

    Design: Corner/endpoints/pool_allocation_ledger_is_append_only_and_nets_to_zero_after_a_reversal
    """
    world = _pooled_world(distribute=True)
    pool_id = world["pool"]["id"]

    before, meta = _allocations(api, shift_tip_pool_id=pool_id)
    assert meta["total_count"] == 1
    original = before[0]
    assert original["allocated_cents"] == 600, "1500 bps of the 4000 declared"
    assert original["entry_type"] == "DISTRIBUTION"
    assert original["share_weight"] == 10, "POINTS_ONLY weights by the role's points"
    assert original["remainder_cent_awarded"] is False
    assert original["shift_id"] == world["shift"]["id"]
    assert original["employee_id"] == world["employee"]["id"]
    assert original["shift_tip_pool_id"] == pool_id
    assert_instant_equals(original["business_date"], DATE_1, "business_date")
    assert "version" not in original, "a ledger row carries no version"
    assert "updated_at" not in original, "and no updated_at either"
    assert_timestamp_format(original["created_at"])

    validate_success(
        api.reverse_shift_tip_pool(
            pool_id, COMPLIANCE, {"reason": "policy applied to the wrong trading day"}
        )
    )

    _rows, meta = _allocations(api, shift_tip_pool_id=pool_id)
    assert meta["total_count"] == 2, "the ledger grew rather than shrank"

    reversals, meta = _allocations(api, shift_tip_pool_id=pool_id, entry_type="REVERSAL")
    assert meta["total_count"] == 1
    assert reversals[0]["allocated_cents"] == -600, "the exact negation"
    assert reversals[0]["shift_id"] == world["shift"]["id"]
    assert_instant_equals(reversals[0]["business_date"], DATE_1, "business_date")

    unmutated = validate_success(api.get_pool_allocation(original["id"], PREPARER))
    assert unmutated["allocated_cents"] == 600, "history is not rewritten"
    assert unmutated["entry_type"] == "DISTRIBUTION"

    by_day, meta = _allocations(
        api, employee_id=world["employee"]["id"], business_date=DATE_1
    )
    assert meta["total_count"] == 2, "the ledger is queryable by employee and trading day"
    assert sum(row["allocated_cents"] for row in by_day) == 0, "the pair nets to nothing"


def test_every_derived_figure_reads_the_net_rather_than_a_deletion(api):
    """Pool, employee, unit and shift all settle back where they started.

    PRD §3.7: "First, `contribution_status` moves `CONTRIBUTED → REVERSED` and
    `reversed_at` is stamped with the current logical instant;
    `total_contributed_cents`, `service_charge_tips_cents`, `cc_fee_deducted_cents` and
    `net_pool_cents` all become 0 as a consequence."
    PRD §3.2: "Hiring also sets `trailing_pool_receipts_cents` to 0; thereafter it is
    the running sum of `allocated_cents` over every pool-allocation ledger row naming
    this employee, counting both `DISTRIBUTION` rows and `REVERSAL` rows, so that a
    reversed pool leaves it back where it started."
    PRD §3.7: "Third, every shift whose `shift_tip_pool_id` names this pool has that
    link cleared back to null, its `pool_contribution_cents` zeroed, and its
    `retained_tips_cents` restored to `declared_cash_tips_cents` plus
    `declared_charged_tips_cents` — the shift is whole again and free to be declared,
    pooled or voided."
    PRD §3.7: "Fifth, the unit's `pending_pool_cents` is recomputed over that unit's
    surviving `CONTRIBUTED` and `PENDING` pools, and each affected period's
    `total_credited_minutes` and `gross_receipts_cents` are recomputed from its
    surviving `CLOSED` shifts."

    Design: Corner/endpoints/pool_allocation_ledger_is_append_only_and_nets_to_zero_after_a_reversal
    """
    world = _pooled_world(distribute=True)
    assert read_employee(world["employee"]["id"])["trailing_pool_receipts_cents"] == 600

    validate_success(
        api.reverse_shift_tip_pool(
            world["pool"]["id"], COMPLIANCE, {"reason": "wrong trading day"}
        )
    )

    pool = read_pool(world["pool"]["id"])
    assert pool["distribution_status"] == "REVERSED"
    assert pool["contribution_status"] == "REVERSED"
    assert pool["distributed_cents"] == 0
    assert pool["total_contributed_cents"] == 0
    assert pool["net_pool_cents"] == 0
    assert_instant_equals(pool["reversed_at"], CLOCK, "reversed_at")

    assert read_employee(world["employee"]["id"])["trailing_pool_receipts_cents"] == 0, (
        "the signed sum over both rows"
    )
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0

    shift = read_shift(world["shift"]["id"])
    assert shift["shift_tip_pool_id"] is None
    assert shift["pool_contribution_cents"] == 0
    assert shift["retained_tips_cents"] == 4000
    assert read_pay_period(world["pay_period"]["id"])["total_credited_minutes"] == 480, (
        "the shift survives as CLOSED, so the period's minutes stand"
    )


# ---------------------------------------------------------------------------
# endpoints / voiding_a_pooled_shift_is_allowed_only_after_the_pool_is_reversed
# ---------------------------------------------------------------------------
def test_the_same_void_payload_is_a_conflict_then_a_success(api):
    """What blocks the void is the live pool, so reversing it makes the identical call land.

    PRD §3.5: "What it does require is that the shift not still be attached to live
    pooled money: `shift_tip_pool_id` must be null, or the pool it names must already
    have `contribution_status` `REVERSED`."
    PRD §3.5: "A shift folded into a pool that has not been reversed is refused with
    `ERR_SHIFT_ALREADY_POOLED`, and the pool must be reversed first, which as §3.7
    explains clears the link anyway."
    PRD §3.7: "A pool whose `distribution_status` was still `PENDING` moves `PENDING →
    REVERSED` and appends no ledger rows at all, because there are no `DISTRIBUTION`
    rows to negate; only the contribution side needs unwinding."
    PRD §3.5: "Voiding zeroes the shift's `non_tip_credit_minutes`,
    `tip_credit_eligible_minutes` and `retained_tips_cents`, then recomputes the owning
    period's `total_credited_minutes` and `gross_receipts_cents` from whichever shifts
    survive as `CLOSED`."
    PRD §3.5: "Voiding is available from either timekeeping state — a shift whose
    `time_status` is `OPEN` and a shift whose `time_status` is `CLOSED` are both legal
    targets, and both land in `VOIDED`, which is terminal — and unlike almost every
    other write on a shift it does not require the owning period to be `OPEN`, precisely
    because its job is to correct periods that have already moved on."

    Design: Corner/endpoints/voiding_a_pooled_shift_is_allowed_only_after_the_pool_is_reversed
    """
    world = _pooled_world()
    shift_id = world["shift"]["id"]
    payload = {"reason": "duplicate punch"}

    validate_error(
        api.void_shift(shift_id, PREPARER, payload),
        ApiErrorId.ERR_SHIFT_ALREADY_POOLED.value,
    )
    frozen = read_shift(shift_id)
    assert frozen["time_status"] == "CLOSED", "the refusal moved nothing"
    assert frozen["retained_tips_cents"] == 3400, "4000 declared less the 600 pooled"

    reversed_pool = validate_success(
        api.reverse_shift_tip_pool(
            world["pool"]["id"],
            COMPLIANCE,
            {"reason": "unwinding the day to correct a duplicate punch"},
        )
    )
    assert reversed_pool["contribution_status"] == "REVERSED"
    assert reversed_pool["distribution_status"] == "REVERSED", (
        "a pool reversed out of PENDING still lands in the terminal REVERSED"
    )
    assert reversed_pool["total_contributed_cents"] == 0
    _rows, meta = _allocations(api, shift_tip_pool_id=world["pool"]["id"])
    assert meta["total_count"] == 0, "a pool that never distributed has nothing to negate"

    released = read_shift(shift_id)
    assert released["shift_tip_pool_id"] is None
    assert released["pool_contribution_cents"] == 0
    assert released["retained_tips_cents"] == 4000

    voided = validate_success(api.void_shift(shift_id, PREPARER, payload))
    assert voided["time_status"] == "VOIDED", (
        "the identical payload that failed now succeeds"
    )
    assert voided["non_tip_credit_minutes"] == 0
    assert voided["tip_credit_eligible_minutes"] == 0
    assert voided["retained_tips_cents"] == 0

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_credited_minutes"] == 0, (
        "recomputed from the shifts that survive as CLOSED, and none do"
    )
    assert period["status"] == "OPEN"
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0


# ---------------------------------------------------------------------------
# endpoints / clock_endpoint_stamps_every_subsequent_system_timestamp
# ---------------------------------------------------------------------------
def test_no_time_passes_between_calls_and_creation_instants_are_never_rewritten(api):
    """Two rows written at one instant share it byte for byte; a clock move shows up only ahead.

    PRD §2.6: "The server keeps a **logical clock** rather than reading wall-clock time.
    Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`;
    that startup default is mandatory and the server never falls back to real time. A
    `PayrollAdmin` may move the clock to an arbitrary UTC instant by supplying
    `current_utc`. From that moment on, every `created_at`, `updated_at`,
    `activated_at`, `distributed_at`, `reversed_at`, `closed_at` and `applied_at` stamp
    the server writes reads from the new logical instant, and every temporal validation —
    future-dating of shifts and service charges in particular — compares against it."
    PRD §2.6: "**`created_at`** (string): an ISO 8601 UTC timestamp with three fractional
    digits, for example `2026-08-01T00:00:00.000Z`, recording when the row was first
    written."
    PRD §2.6: "**`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional
    digits, refreshed on every mutation of the row — including mutations of purely
    derived fields performed by a cascade rather than by a direct client request on that
    row."
    PRD §3.3: "First, the newly active policy's `activated_at` is stamped with the
    current logical instant."
    PRD §3.3: "Fifth, the unit's `version` is incremented by exactly 1, so any second
    activation replayed with the same `expected_location_version` fails."

    Design: Corner/endpoints/clock_endpoint_stamps_every_subsequent_system_timestamp
    """
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    assert_instant_equals(location["created_at"], CLOCK, "location.created_at")
    assert_instant_equals(role_server["created_at"], CLOCK, "job_role.created_at")
    assert location["created_at"] == role_server["created_at"], (
        "no time passes between calls unless the clock is moved"
    )
    assert_instant_equals(location["updated_at"], CLOCK, "location.updated_at")
    assert location["version"] == 1

    moved = validate_success(api.set_clock({"current_utc": LATER_CLOCK}, ADMIN))
    assert moved == {}, "the clock endpoint returns no resource payload"

    employee = new_employee(location["id"])
    policy = new_draft_policy(location["id"], share_basis="POINTS_ONLY")
    assert_instant_equals(employee["created_at"], LATER_CLOCK, "employee.created_at")
    assert_instant_equals(policy["created_at"], LATER_CLOCK, "policy.created_at")
    assert policy["activated_at"] is None

    activated = activate_policy(policy["id"], location["version"])
    assert activated["status"] == "ACTIVE"
    assert_instant_equals(activated["activated_at"], LATER_CLOCK, "activated_at")
    assert_instant_equals(activated["updated_at"], LATER_CLOCK, "policy.updated_at")

    refreshed = read_location(location["id"])
    assert_instant_equals(refreshed["created_at"], CLOCK, "location.created_at")
    assert refreshed["created_at"] == location["created_at"], (
        "the creation instant is never rewritten"
    )
    assert_instant_equals(refreshed["updated_at"], LATER_CLOCK, "location.updated_at")
    assert refreshed["version"] == 2, "the activation bumped the unit, at the new instant"

    for _label, value in (
        ("location.created_at", refreshed["created_at"]),
        ("location.updated_at", refreshed["updated_at"]),
        ("policy.activated_at", activated["activated_at"]),
    ):
        assert_timestamp_format(value)
