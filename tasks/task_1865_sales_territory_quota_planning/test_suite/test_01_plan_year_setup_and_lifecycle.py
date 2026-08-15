"""Plan year setup, shape rules, lifecycle spine, locking, and pagination."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    activate_territory,
    add_territory,
    assert_plan_year,
    communicate_plan,
    create_plan,
    create_plan_year_payload,
    file_dispute,
    get_plan,
    lock_plan,
    make_sales_rep_headers,
    open_plan,
    set_clock,
    setup_reconciled_leaf,
    setup_two_territory_communicated,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_plan_year_create_defaults_and_initial_state(api):
    """PRD: "Two optional policy knobs ride along: `reconciliation_policy`, one of
    `TOP_DOWN_WINS` or `BLENDED` and defaulting to `TOP_DOWN_WINS` when omitted,
    and `credit_transition_policy`, one of `PRORATE_BY_DAY` or `MONTH_SNAPSHOT`
    and defaulting to `PRORATE_BY_DAY` when omitted."
    PRD: "A new plan year is born in `DRAFT` status with `version` 1, and both
    `communicated_at` and `locked_at` are null until their respective
    transitions write them."

    Design: Corner/entities/plan_year_create_defaults_and_initial_state
    """
    resp = api.create_plan_year(create_plan_year_payload(), ADMIN)
    plan = validate_success(resp, 201)
    assert_plan_year(plan)
    assert plan["reconciliation_policy"] == "TOP_DOWN_WINS"
    assert plan["credit_transition_policy"] == "PRORATE_BY_DAY"
    assert plan["status"] == "DRAFT"
    assert plan["version"] == 1
    assert plan["communicated_at"] is None
    assert plan["locked_at"] is None


def test_plan_year_date_shape_validation_rejected(api):
    """PRD: "the start date must fall on the first day of a month; the end date
    must be the last day of the month exactly eleven months after the start
    month, so every plan year runs twelve calendar months; and the lock date
    must not precede the start date. A violation of any of the three is
    `ERR_INVALID_PLAN_DATES`."

    Design: Corner/entities/plan_year_date_shape_validation_rejected
    """
    bad_start = create_plan_year_payload(
        label="B1", start_date="2027-01-02", end_date="2027-12-31")
    validate_error(api.create_plan_year(bad_start, ADMIN),
                   ApiErrorId.ERR_INVALID_PLAN_DATES, 422)

    bad_end = create_plan_year_payload(
        label="B2", start_date="2027-01-01", end_date="2027-11-30")
    validate_error(api.create_plan_year(bad_end, ADMIN),
                   ApiErrorId.ERR_INVALID_PLAN_DATES, 422)

    bad_lock = create_plan_year_payload(
        label="B3", start_date="2027-01-01", end_date="2027-12-31",
        lock_date="2026-12-31")
    validate_error(api.create_plan_year(bad_lock, ADMIN),
                   ApiErrorId.ERR_INVALID_PLAN_DATES, 422)

    data, meta = validate_paginated(api.list_plan_years(ADMIN))
    assert meta["total_count"] == 0 and data == [], \
        "no plan may be persisted after shape violations"


def test_plan_year_closed_interval_overlap_rejected(api):
    """PRD: "Once shape passes, the plan's closed date interval is compared
    against every existing plan year, and any overlap — even touching at a
    single shared day — is rejected with `ERR_PLAN_DATE_OVERLAP`."

    A plan starting 2027-12-01 collides with [2027-01-01, 2027-12-31] because
    December 2027 days belong to both closed intervals.

    Design: Difficulty/resource_temporal_overlap/plan_year_closed_interval_overlap
    """
    create_plan(label="FY27")
    overlap = create_plan_year_payload(
        label="FY27-LATE", start_date="2027-12-01", end_date="2028-11-30",
        lock_date="2027-12-15")
    validate_error(api.create_plan_year(overlap, ADMIN),
                   ApiErrorId.ERR_PLAN_DATE_OVERLAP, 409)


def test_plan_year_touching_boundary_accepted(api):
    """PRD: "Once shape passes, the plan's closed date interval is compared
    against every existing plan year, and any overlap — even touching at a
    single shared day — is rejected with `ERR_PLAN_DATE_OVERLAP`."

    A plan starting 2028-01-01 is one day past the inclusive end 2027-12-31,
    so it shares no day with the existing plan and must be accepted.

    Design: Difficulty/resource_temporal_overlap/plan_year_closed_interval_overlap
    """
    create_plan(label="FY27")
    resp = api.create_plan_year(
        create_plan_year_payload(label="FY28", start_date="2028-01-01",
                                 end_date="2028-12-31",
                                 lock_date="2028-01-15"), ADMIN)
    plan = validate_success(resp, 201)
    assert plan["status"] == "DRAFT"


def test_plan_years_list_pagination(api):
    """PRD: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and it is bounded below by 1 and above by 100.
    The `offset` parameter states how many items to skip and defaults to 0."
    PRD: "The `meta` object of a list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/plan_years_list_pagination
    """
    create_plan(label="FY27")
    create_plan(label="FY28", start_date="2028-01-01", end_date="2028-12-31",
                lock_date="2028-01-15")

    page1, meta1 = validate_paginated(
        api.list_plan_years(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_plan_years(ADMIN, params={"limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]


def test_plan_open_without_active_territory_rejected(api):
    """PRD: "From `DRAFT`, opening the plan moves it to `OPEN` and is permitted
    only once at least one territory in the plan is `ACTIVE`; otherwise the
    open is refused with `ERR_NO_ACTIVE_TERRITORY`."

    Design: Corner/state_machines/plan_open_without_active_territory_rejected
    """
    plan = create_plan(label="FY27")
    add_territory(plan["id"], name="T")  # left in DRAFT
    validate_error(api.open_plan(plan["id"], ADMIN),
                   ApiErrorId.ERR_NO_ACTIVE_TERRITORY, 409)
    assert get_plan(plan["id"])["status"] == "DRAFT"


def test_plan_communicate_before_reconcile_invalid(api):
    """PRD: "Communication moves the plan from `RECONCILED` to `COMMUNICATED`
    and stamps `communicated_at` with the current logical timestamp"
    PRD: "Then the entity's own from-state is checked against the requested
    transition (`ERR_INVALID_STATE_TRANSITION`)"

    Communicating an OPEN plan skips two lifecycle states, so the from-state
    check rejects it.

    Design: Corner/state_machines/plan_communicate_before_reconcile_invalid
    """
    plan = create_plan(label="FY27")
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    open_plan(plan["id"])
    validate_error(api.communicate_plan(plan["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
    assert get_plan(plan["id"])["status"] == "OPEN"


def test_plan_version_increments_on_mutation(api):
    """PRD: "The `version` is an integer that starts at 1 and increments by one
    on every mutation of the resource"
    PRD: "`LOCKED` is terminal. Every one of these transitions increments the
    plan's `version` by one."

    Create yields version 1; the open transition increments it to exactly 2.

    Design: Corner/cross_cutting_complexity_layers/plan_version_increments_on_mutation
    """
    resp = api.create_plan_year(create_plan_year_payload(label="FY27"), ADMIN)
    plan = validate_success(resp, 201)
    assert plan["version"] == 1
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    opened = validate_success(api.open_plan(plan["id"], ADMIN), 200)
    assert opened["version"] == 2, \
        "open must increment the plan version exactly once"
    assert get_plan(plan["id"])["version"] == 2


def test_plan_lock_before_lock_date_rejected(api):
    """PRD: "Locking moves the plan from `COMMUNICATED` to `LOCKED` and stamps
    `locked_at`, but only when two preconditions hold: the current logical date
    has reached the plan's `lock_date` — earlier attempts fail with
    `ERR_LOCK_DATE_NOT_REACHED`"

    At 2027-01-14 the lock is rejected; at 2027-01-15 (the lock_date itself,
    reached) it succeeds and `locked_at` is stamped from the logical clock.

    Design: Corner/state_machines/plan_lock_before_lock_date_rejected
    """
    base = setup_reconciled_leaf(label="FY27")
    plan_id = base["plan"]["id"]
    communicate_plan(plan_id)
    set_clock("2027-01-14T00:00:00Z")
    validate_error(api.lock_plan(plan_id, ADMIN),
                   ApiErrorId.ERR_LOCK_DATE_NOT_REACHED, 409)
    assert get_plan(plan_id)["status"] == "COMMUNICATED"
    set_clock("2027-01-15T00:00:00Z")
    locked = validate_success(api.lock_plan(plan_id, ADMIN), 200)
    assert locked["status"] == "LOCKED"
    assert locked["locked_at"] is not None
    assert locked["locked_at"].startswith("2027-01-15T00:00:00"), \
        f"locked_at must be stamped with the current logical timestamp, " \
        f"got {locked['locked_at']!r}"


def test_plan_lock_blocked_by_open_dispute_rejected(api):
    """PRD: "no dispute in the plan still sits in `FILED`, `UNDER_REVIEW`, or
    `ESCALATED`, because unresolved disputes block the lock with
    `ERR_PLAN_HAS_UNRESOLVED_DISPUTES`."

    A FILED dispute blocks the lock even once the lock date has passed;
    withdrawing it releases the gate.

    Design: Corner/state_machines/plan_lock_blocked_by_open_dispute_rejected
    """
    ns = setup_two_territory_communicated(label="FY27")
    plan_id = ns["plan"]["id"]
    dispute = file_dispute(plan_id, ns["acc"]["id"], ns["ty"]["id"],
                           ns["rep"]["id"], reason="mine")
    set_clock("2027-01-15T00:00:00Z")
    validate_error(api.lock_plan(plan_id, ADMIN),
                   ApiErrorId.ERR_PLAN_HAS_UNRESOLVED_DISPUTES, 409)
    assert get_plan(plan_id)["status"] == "COMMUNICATED"

    withdrawn = validate_success(
        api.withdraw_dispute(dispute["id"],
                             make_sales_rep_headers(ns["rep"]["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    locked = validate_success(api.lock_plan(plan_id, ADMIN), 200)
    assert locked["status"] == "LOCKED"


def test_plan_locked_blocks_configuration_mutation(api):
    """PRD: "Once `LOCKED`, the plan refuses every configuration mutation with
    `ERR_PLAN_LOCKED`; the only writes still permitted are change requests,
    disputes, credit events, the dispute-SLA checkpoint, the coverage report,
    the clock, and reads."
    PRD: "Territories may be created at any point before the plan is locked and
    are born in `DRAFT`."

    Design: Corner/state_machines/plan_locked_blocks_configuration_mutation
    """
    base = setup_reconciled_leaf(label="FY27")
    plan_id = base["plan"]["id"]
    communicate_plan(plan_id)
    set_clock("2027-01-15T00:00:00Z")
    lock_plan(plan_id)
    assert get_plan(plan_id)["status"] == "LOCKED"

    resp = api.create_territory(
        {"plan_year_id": plan_id, "name": "LATE", "potential_cents": 50,
         "headcount_capacity": 1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_LOCKED, 409)
