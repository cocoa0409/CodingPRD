"""Master lease: lifecycle loop, committed-capacity conservation, capacity cap,
active-required booking, and optimistic-concurrency renegotiation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_corporate_account, create_active_master_lease, create_employee,
    create_rate_plan, create_unit, setup_corporate_stay,
    create_master_lease_payload, create_stay_payload, renegotiate_payload,
    make_corporate_admin_headers, assert_master_lease_capacity_invariant,
    TEST_USERS,
)

PM = TEST_USERS["property_manager_headers"]


# --- Suspend/resume cycle (ACTIVE -> SUSPENDED -> ACTIVE) ---

def test_master_lease_resume_returns_to_active(api):
    """PRD §3.2: "Activating a `DRAFT` lease moves it to `ACTIVE`; suspending an
    `ACTIVE` lease moves it to `SUSPENDED`; resuming a `SUSPENDED` lease returns it
    to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/master_lease_suspend_resume_cycle
    """
    lease = create_active_master_lease(api)
    validate_success(api.suspend_master_lease(lease["id"], PM))
    resumed = validate_success(api.resume_master_lease(lease["id"], PM))
    assert resumed["status"] == "ACTIVE"


def test_master_lease_cycle_increments_version_each_transition(api):
    """PRD §2.4: "The `version` field is an integer that begins at 1 and increments
    by exactly 1 on every mutation of the resource."
    PRD §3.2: "Each of these three transitions increments the lease's `version` by 1."

    Design: Difficulty/non_linear_state_machine/master_lease_suspend_resume_cycle
    """
    account = create_corporate_account(api)
    created = validate_success(
        api.create_master_lease(create_master_lease_payload(account["id"]), PM),
        expected_status=201,
    )
    assert created["version"] == 1
    validate_success(api.activate_master_lease(created["id"], PM))   # -> v2
    validate_success(api.suspend_master_lease(created["id"], PM))    # -> v3
    resumed = validate_success(api.resume_master_lease(created["id"], PM))  # -> v4
    assert resumed["status"] == "ACTIVE"
    assert resumed["version"] == 4


def test_activate_already_active_lease_rejected(api):
    """PRD §3.2: "A transition attempted from the wrong starting status —
    activating a lease that is not `DRAFT`, suspending one that is not `ACTIVE`, or
    resuming one that is not `SUSPENDED` — is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_lease_returns_invalid_state
    """
    lease = create_active_master_lease(api)
    resp = api.activate_master_lease(lease["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_lease_reports_units_free_immediately(api):
    """PRD §3.2: "A newly created lease begins in `DRAFT` status with `version` at
    1, `units_consumed` at 0, and `units_free` equal to `committed_units`."

    Design: Corner/consistency_model/immediate_consistency_units_free_visible_on_create
    """
    account = create_corporate_account(api)
    created = validate_success(
        api.create_master_lease(create_master_lease_payload(account["id"], committed_units=4), PM),
        expected_status=201,
    )
    assert created["units_consumed"] == 0
    assert created["units_free"] == 4


# --- Committed-capacity conservation across book then cancel ---

def test_cancel_releases_committed_unit(api):
    """PRD §3.3: "On cancellation, any provisional invoice already attached to the
    stay is left in `DRAFT` and is no longer billable, and — because the stay leaves
    the `RESERVED`/`ACTIVE` set — the master lease's `units_consumed` is re-derived
    downward, releasing the committed unit back to `units_free`."

    Design: Difficulty/compensating_invariant/master_lease_units_conservation_book_then_cancel
    """
    ctx = setup_corporate_stay(api, committed_units=3)
    validate_success(api.cancel_stay(ctx["stay"]["id"], ctx["admin_headers"]))
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay["status"] == "CANCELLED"
    lease = validate_success(api.get_master_lease(ctx["lease"]["id"], PM))
    assert lease["units_consumed"] == 0
    assert lease["units_free"] == 3


def test_capacity_conservation_holds_through_book_and_cancel(api):
    """PRD §3.2: "At any moment, `units_consumed` equals the number of stays on the
    lease whose `status` is either `RESERVED` or `ACTIVE`, and `units_free` equals
    `committed_units` minus `units_consumed`, floored at zero so it is never
    negative. The conservation identity `committed_units = units_consumed +
    units_free` therefore always holds."

    Design: Difficulty/compensating_invariant/master_lease_units_conservation_book_then_cancel
    """
    ctx = setup_corporate_stay(api, committed_units=3)
    after_book = validate_success(api.get_master_lease(ctx["lease"]["id"], PM))
    assert after_book["units_consumed"] == 1
    assert after_book["units_free"] == 2
    assert_master_lease_capacity_invariant(after_book)

    validate_success(api.cancel_stay(ctx["stay"]["id"], ctx["admin_headers"]))
    after_cancel = validate_success(api.get_master_lease(ctx["lease"]["id"], PM))
    assert after_cancel["committed_units"] == 3
    assert_master_lease_capacity_invariant(after_cancel)


def test_master_lease_cap_exceeded_on_third_booking(api):
    """PRD §3.3: "For a corporate stay, accepting the booking must not push the
    master lease's `units_consumed` above its `committed_units`. A booking that
    would exceed the committed block is rejected with
    `ERR_MASTER_LEASE_CAP_EXCEEDED`."

    Design: Corner/calculations/master_lease_cap_exceeded_on_third_booking
    """
    account = create_corporate_account(api)
    rate_plan = create_rate_plan(api)
    u1 = create_unit(api, name="U1")
    u2 = create_unit(api, name="U2", property_name="Oak Ridge")
    u3 = create_unit(api, name="U3", property_name="Pine Row")
    lease = create_active_master_lease(api, account["id"], committed_units=2)
    employee = create_employee(api, account["id"])
    admin = make_corporate_admin_headers(account["id"])

    validate_success(api.create_stay(create_stay_payload(
        u1["id"], rate_plan["id"], move_in="2026-05-01T00:00:00Z",
        planned_move_out="2026-06-30T00:00:00Z", deposit_held_cents=0,
        master_lease_id=lease["id"], employee_id=employee["id"]), admin), expected_status=201)
    validate_success(api.create_stay(create_stay_payload(
        u2["id"], rate_plan["id"], move_in="2026-07-05T00:00:00Z",
        planned_move_out="2026-09-05T00:00:00Z", deposit_held_cents=0,
        master_lease_id=lease["id"], employee_id=employee["id"]), admin), expected_status=201)

    resp = api.create_stay(create_stay_payload(
        u3["id"], rate_plan["id"], move_in="2026-10-01T00:00:00Z",
        planned_move_out="2026-12-01T00:00:00Z", deposit_held_cents=0,
        master_lease_id=lease["id"], employee_id=employee["id"]), admin)
    validate_error(resp, ApiErrorId.ERR_MASTER_LEASE_CAP_EXCEEDED.value)

    lease_after = validate_success(api.get_master_lease(lease["id"], PM))
    assert lease_after["units_consumed"] == 2
    assert lease_after["units_free"] == 0


def test_corporate_booking_against_draft_lease_rejected(api):
    """PRD §3.3: "When a `master_lease_id` is supplied, the referenced master lease
    must be `ACTIVE`; otherwise the booking is rejected with
    `ERR_MASTER_LEASE_NOT_ACTIVE`."

    Design: Corner/validations/error_master_lease_not_active_on_corporate_booking
    """
    account = create_corporate_account(api)
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    # Master lease left in DRAFT (never activated).
    lease = validate_success(
        api.create_master_lease(create_master_lease_payload(account["id"]), PM),
        expected_status=201,
    )
    employee = create_employee(api, account["id"])
    admin = make_corporate_admin_headers(account["id"])

    resp = api.create_stay(create_stay_payload(
        unit["id"], rate_plan["id"], move_in="2026-05-01T00:00:00Z",
        planned_move_out="2026-06-30T00:00:00Z", deposit_held_cents=0,
        master_lease_id=lease["id"], employee_id=employee["id"]), admin)
    validate_error(resp, ApiErrorId.ERR_MASTER_LEASE_NOT_ACTIVE.value)


# --- Optimistic concurrency on renegotiation ---

def test_renegotiate_with_stale_version_rejected(api):
    """PRD §2.6: "Before applying the new rate, the server compares
    `expected_master_lease_version` against the lease's current `version`. If they
    differ — because an intervening activate, suspend, resume, or earlier
    renegotiate has advanced the lease's `version` since the client read it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is made."

    Design: Corner/cross_cutting_complexity_layers/occ_renegotiate_stale_version_conflict
    """
    lease = create_active_master_lease(api)
    v0 = validate_success(api.get_master_lease(lease["id"], PM))["version"]
    validate_success(api.renegotiate_master_lease(
        lease["id"], renegotiate_payload(v0, 250000), PM))  # advances version

    resp = api.renegotiate_master_lease(lease["id"], renegotiate_payload(v0, 240000), PM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    after = validate_success(api.get_master_lease(lease["id"], PM))
    assert after["negotiated_monthly_rate_cents"] == 250000


def test_renegotiate_with_current_version_supersedes_rate(api):
    """PRD §3.2: "Renegotiation supersedes the lease's monthly rate: it replaces
    `negotiated_monthly_rate_cents` with a new value and increments `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_renegotiate_success_bumps_version
    """
    lease = create_active_master_lease(api)
    v0 = validate_success(api.get_master_lease(lease["id"], PM))["version"]
    updated = validate_success(api.renegotiate_master_lease(
        lease["id"], renegotiate_payload(v0, 250000), PM))
    assert updated["negotiated_monthly_rate_cents"] == 250000
    assert updated["version"] == v0 + 1
