"""Install day, the crew-day bucket and the lease term it starts."""

from test_helpers import (
    CLERK,
    COORD,
    WAREHOUSE,
    ApiErrorId,
    assert_install,
    assert_lease,
    assert_money,
    assert_same_instant,
    assert_warehouse_conservation,
    lease_of,
    set_clock,
    setup_two_projects_one_install_day,
    setup_vacant_project_staged,
    setup_vacant_pull_committed,
    setup_vendor_rate_rounding_install_started,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_starting_a_completed_install_is_an_invalid_install_state(api):
    """PRD §2.7: "Rung 24: the install's `state` is a legal origin for the requested
    transition; otherwise `ERR_INSTALL_INVALID_STATE`, HTTP 409."
    PRD §3.4: "Starting the install requires the logical clock to have reached its
    `scheduled_at` and the pull to be `COMMITTED`, and moves it `SCHEDULED → IN_PROGRESS`."

    Design: Corner/state_machines/install_start_after_completion_rejected_as_install_invalid_state
    """
    ctx = setup_vacant_project_staged()

    resp = api.start_install(ctx["install_id"], COORD)

    validate_error(resp, ApiErrorId.ERR_INSTALL_INVALID_STATE.value, 409)
    install = validate_success(api.get_install(ctx["install_id"], COORD))
    assert_install(install)
    assert install["state"] == "COMPLETE"
    assert_same_instant(install["completed_at"], "2026-06-10T09:00:00Z",
                        "install.completed_at")
    assert install["attempt_count"] == 0


def test_rescheduling_a_no_access_install_counts_the_attempt(api):
    """PRD §3.4: "When the crew cannot get in, the install moves `SCHEDULED → NO_ACCESS`,
    which requires the clock to have reached the scheduled instant."
    PRD §3.4: "A no-access install may be rescheduled to a new `scheduled_at`, moving
    `NO_ACCESS → SCHEDULED` and incrementing `attempt_count`, provided `attempt_count` is
    strictly below 2 and the new day still satisfies both crew capacity and vendor lead
    time."

    Design: Corner/state_machines/install_no_access_then_reschedule_increments_attempt_count
    """
    ctx = setup_vacant_pull_committed()
    install = validate_success(api.schedule_install(
        ctx["proj_id"],
        {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3, "initial_cycles": 6},
        COORD), 201)
    set_clock("2026-06-10T09:00:00Z")
    validate_success(api.install_no_access(install["id"], COORD))

    resp = api.reschedule_install(install["id"], "2026-06-12T09:00:00Z", COORD)

    validate_success(resp)
    stored = validate_success(api.get_install(install["id"], COORD))
    assert stored["state"] == "SCHEDULED"
    assert stored["attempt_count"] == 1
    assert_same_instant(stored["scheduled_at"], "2026-06-12T09:00:00Z",
                        "install.scheduled_at")
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["state"] == "COMMITTED"


def test_the_third_install_reschedule_hits_the_attempt_limit(api):
    """PRD §2.7: "Rung 56: the install's `attempt_count` is strictly less than 2 before a
    `NO_ACCESS` install may be rescheduled; otherwise `ERR_INSTALL_ATTEMPT_LIMIT`, HTTP 409."
    PRD §3.4: "A no-access install may be rescheduled to a new `scheduled_at`, moving
    `NO_ACCESS → SCHEDULED` and incrementing `attempt_count`, provided `attempt_count` is
    strictly below 2 and the new day still satisfies both crew capacity and vendor lead
    time."

    Design: Corner/errors/third_install_reschedule_hits_the_attempt_limit
    """
    ctx = setup_vacant_pull_committed()
    install = validate_success(api.schedule_install(
        ctx["proj_id"],
        {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3, "initial_cycles": 6},
        COORD), 201)
    for now, nxt in (("2026-06-10T09:00:00Z", "2026-06-12T09:00:00Z"),
                     ("2026-06-12T09:00:00Z", "2026-06-14T09:00:00Z")):
        set_clock(now)
        validate_success(api.install_no_access(install["id"], COORD))
        validate_success(api.reschedule_install(install["id"], nxt, COORD))
    set_clock("2026-06-14T09:00:00Z")
    validate_success(api.install_no_access(install["id"], COORD))

    resp = api.reschedule_install(install["id"], "2026-06-16T09:00:00Z", COORD)

    validate_error(resp, ApiErrorId.ERR_INSTALL_ATTEMPT_LIMIT.value, 409)
    stored = validate_success(api.get_install(install["id"], COORD))
    assert stored["attempt_count"] == 2
    assert stored["state"] == "NO_ACCESS"


def test_install_completion_deploys_every_line_unit_and_vendor_order(api):
    """PRD §3.4: "Hop three moves every `ALLOCATED` pull line to `DEPLOYED` and every linked
    owned item `RESERVED → DEPLOYED` with `times_deployed` incremented, while every
    `CONFIRMED` rental order moves to `DELIVERED`."
    PRD §3.4: "Hop one moves the lease `PENDING → ACTIVE` with its `start_date` set to that
    very `completed_at` — the lease clock starts at install-complete, not at contract
    signature and not at authorization."

    Design: Corner/cross_cutting_complexity_layers/install_complete_cascade_is_verified_end_to_end
    """
    ctx = setup_vacant_project_staged()

    summary = validate_success(api.get_inventory_summary(WAREHOUSE))

    assert summary["on_hand_total"] == 3
    assert summary["deployed"] == 3
    assert summary["available"] == 0
    assert summary["reserved"] == 0
    assert_warehouse_conservation(summary)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["state"] == "ACTIVE"
    assert_same_instant(lease["start_date"], "2026-06-10T09:00:00Z", "lease.start_date")
    assert_same_instant(lease["end_date"], "2026-10-08T09:00:00Z", "lease.end_date")
    assert validate_success(
        api.get_pull_line(ctx["line_a"], WAREHOUSE))["state"] == "DEPLOYED"
    item = validate_success(api.get_inventory_item(ctx["item_a"], WAREHOUSE))
    assert item["status"] == "DEPLOYED"
    assert item["times_deployed"] == 1
    assert validate_success(
        api.get_rental_order(ctx["ro_id"], WAREHOUSE))["state"] == "DELIVERED"


def test_lease_dates_are_anchored_on_install_completion(api):
    """PRD §3.5: "Install completion moves it `PENDING → ACTIVE` and derives everything at
    once: `start_date` becomes the install's `completed_at`; `billed_cycles` becomes
    `initial_cycles`; `end_date` becomes `start_date` plus `billed_cycles` multiplied by 30
    days; the pickup window is derived; and `monthly_rent` is computed."
    PRD §3.2: "`authorized_at` is stamped with the logical clock."

    Design: Corner/calculations/lease_dates_derive_from_install_complete_not_from_authorization
    """
    ctx = setup_vacant_project_staged()

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))

    assert_lease(lease)
    assert_same_instant(lease["start_date"], "2026-06-10T09:00:00Z", "lease.start_date")
    assert_same_instant(lease["end_date"], "2026-10-08T09:00:00Z", "lease.end_date")
    assert lease["billed_cycles"] == 4
    assert lease["state"] == "ACTIVE"
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_same_instant(project["authorized_at"], "2026-06-01T00:00:00Z",
                        "project.authorized_at")


def test_the_lease_is_discoverable_only_through_the_project_filter(api):
    """PRD §3.4: "**Scheduling the install is what creates the lease**, in state `PENDING`,
    with the supplied `initial_cycles`."
    PRD §3.5: "**`monthly_rent` is the sum of the pull lines that are actually standing in
    the house.**"

    Design: Corner/endpoints/lease_is_discoverable_only_through_the_project_filter
    """
    ctx = setup_vacant_project_staged()

    rows, meta = validate_paginated(api.list_leases(
        COORD, params={"project_id": ctx["proj_id"]}))

    assert api.list_leases(COORD, params={"project_id": ctx["proj_id"]}).json()[
        "response_type"] == "array"
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["lease_id"]
    assert rows[0]["initial_cycles"] == 4
    assert_money(rows[0]["monthly_rent"], 1867.50, "lease.monthly_rent")


def test_accruing_holdover_on_an_active_lease_is_an_invalid_lease_state(api):
    """PRD §2.7: "Rung 26: the lease's `state` is a legal origin for the requested
    transition; otherwise `ERR_LEASE_INVALID_STATE`, HTTP 409."
    PRD §3.5: "The first accrual moves the lease `ENDING → HOLDOVER` and requires the
    logical clock to be strictly past `pickup_window_end` plus 2 grace days; it sets
    `holdover_cap_period_start` to `pickup_window_end` and derives both holdover figures."

    Design: Corner/state_machines/lease_accrue_holdover_while_active_rejected_as_lease_invalid_state
    """
    ctx = setup_vacant_project_staged()

    resp = api.accrue_holdover(ctx["lease_id"], CLERK)

    validate_error(resp, ApiErrorId.ERR_LEASE_INVALID_STATE.value, 409)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["state"] == "ACTIVE"
    assert lease["holdover_days"] == 0
    assert_money(lease["holdover_charge"], 0.00, "lease.holdover_charge")


def test_a_second_install_on_the_same_utc_date_double_books_the_crew(api):
    """PRD §2.7: "Rung 61: the proposed install's UTC calendar day carries fewer than 1
    install already in state `SCHEDULED` or `IN_PROGRESS`; otherwise
    `ERR_CREW_DOUBLE_BOOKED`, HTTP 409."
    PRD §3.4: "Crew capacity is bucketed by **UTC calendar day** with a capacity of 1
    install per day and no buffer of any kind: two installs at 09:00 and at 21:00 on the
    same UTC date collide even though their working hours do not overlap, while an install
    at 23:59 and another at 00:01 the next day never collide."

    Design: Difficulty/resource_temporal_overlap/crew_day_bucket_rejects_a_second_install_on_the_same_utc_date
    """
    ctx = setup_two_projects_one_install_day()

    resp = api.schedule_install(
        ctx["proj_b"],
        {"scheduled_at": "2026-06-10T21:00:00Z", "crew_size": 2, "initial_cycles": 4}, COORD)

    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value, 409)
    install_a = validate_success(api.get_install(ctx["install_a"], COORD))
    assert install_a["state"] == "SCHEDULED"


def test_the_double_booked_project_stays_at_pull_open_with_no_install(api):
    """PRD §2.7: "Rung 61: the proposed install's UTC calendar day carries fewer than 1
    install already in state `SCHEDULED` or `IN_PROGRESS`; otherwise
    `ERR_CREW_DOUBLE_BOOKED`, HTTP 409."
    PRD §3.4: "The install is created in state `SCHEDULED` with `attempt_count` 0 and a null
    `completed_at`, and the project moves `PULL_OPEN → INSTALL_SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/crew_day_bucket_rejects_a_second_install_on_the_same_utc_date
    """
    ctx = setup_two_projects_one_install_day()

    resp = api.schedule_install(
        ctx["proj_b"],
        {"scheduled_at": "2026-06-10T21:00:00Z", "crew_size": 2, "initial_cycles": 4}, COORD)

    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value, 409)
    project_b = validate_success(api.get_project(ctx["proj_b"], COORD))
    assert project_b["workflow_state"] == "PULL_OPEN"
    _, meta = validate_paginated(api.list_installs(COORD, params={"project_id": ctx["proj_b"]}))
    assert meta["total_count"] == 0, "the refused install must not have been stored"


def test_each_pull_line_is_rounded_before_it_enters_the_monthly_rent(api):
    """PRD §3.5: "The lines are summed in ascending order of their creation timestamp, and
    **each line's `monthly_rate` is rounded half-up to two decimal places before it enters
    the sum**, with the accumulated total likewise carried at two decimal places."
    PRD §3.4: "Every allocated line's `monthly_rate` is derived at that moment: an owned
    line takes the allocated unit's own `monthly_rate` and ignores `quantity` entirely,
    while a vendor line takes 85.00 multiplied by the vendor's `rate_multiplier` multiplied
    by the line's `quantity`; either way the result is rounded half-up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/lease_monthly_rent_rounds_per_line_before_summing
    """
    ctx = setup_vendor_rate_rounding_install_started()

    validate_success(api.complete_install(ctx["install_id"], COORD))

    line_1 = validate_success(api.get_pull_line(ctx["line_1"], WAREHOUSE))
    line_2 = validate_success(api.get_pull_line(ctx["line_2"], WAREHOUSE))
    assert_money(line_1["monthly_rate"], 339.92, "pull line 1.monthly_rate")
    assert_money(line_2["monthly_rate"], 339.92, "pull line 2.monthly_rate")
    lease = lease_of(ctx["proj_id"])
    assert_money(lease["monthly_rent"], 679.84, "lease.monthly_rent")


def test_the_order_total_rounds_once_and_differs_from_the_per_line_sum(api):
    """PRD §3.4: "`monthly_rate_total` is the order's `unit_count` multiplied by a vendor
    unit base rate of 85.00 multiplied by the vendor's `rate_multiplier`, rounded half-up to
    two decimal places **once per order and not per unit**."
    PRD §2.8: "Where a formula in §3 says "rounded", that is what is meant, and where it
    says a value is rounded *before* entering a sum, the order is binding: rounding each
    component and then adding is not interchangeable with adding raw components and
    rounding once, and the two can differ by a cent on the same inputs."

    Design: Difficulty/combinatorial_formula/lease_monthly_rent_rounds_per_line_before_summing
    """
    ctx = setup_vendor_rate_rounding_install_started()

    validate_success(api.complete_install(ctx["install_id"], COORD))

    order = validate_success(api.get_rental_order(ctx["ro_id"], WAREHOUSE))
    assert_money(order["monthly_rate_total"], 679.83, "order.monthly_rate_total")
    lease = lease_of(ctx["proj_id"])
    assert float(lease["monthly_rent"]) != float(order["monthly_rate_total"]), (
        "rounding per line then summing must not equal summing then rounding once"
    )


def test_the_workflow_axis_reaches_staged_while_the_payment_axis_is_only_deposit_held(api):
    """PRD §3.9: "A project carries **two independent state machines on the same row**:
    `workflow_state` advances on execution events, `payment_state` advances on billing
    events, and neither reads the other's current value as a precondition — with exactly one
    join point."
    PRD §3.3: "Collecting the deposit moves it `REQUIRED → HELD`, sets `held_remaining` to
    the full `amount`, and drives the project's `payment_state` `UNBILLED → DEPOSIT_HELD`."

    Design: Difficulty/non_linear_state_machine/project_workflow_and_payment_axes_advance_independently
    """
    ctx = setup_vacant_project_staged()

    project = validate_success(api.get_project(ctx["proj_id"], COORD))

    assert project["workflow_state"] == "STAGED"
    assert project["payment_state"] == "DEPOSIT_HELD"


def test_neither_project_axis_has_flipped_the_destage_or_fiscal_flags(api):
    """PRD §3.9: "A project's `destage_eligible` becomes true once the listing has reached
    `UNDER_CONTRACT` or the lease has reached its `end_date`, whichever happens first."
    PRD §3.9: "A project's `fiscal_hold` is true exactly while its `payment_state` is
    `ESCALATED`, and while it is true no new commitment may be made — no pull, no install,
    no visit, no photo shoot, no reshoot request, no lease extension and no package upgrade
    — each refused with `ERR_FISCAL_HOLD` (HTTP 402)."

    Design: Difficulty/non_linear_state_machine/project_workflow_and_payment_axes_advance_independently
    """
    ctx = setup_vacant_project_staged()

    project = validate_success(api.get_project(ctx["proj_id"], COORD))

    assert project["destage_eligible"] is False
    assert project["fiscal_hold"] is False
