"""Driver employment lifecycle (parallel employment/duty dimensions, cascade
on suspend/terminate) and the safety-score decay ledger (PRD §3.4, §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_driver,
    get_driver,
    get_load,
    get_tractor,
    get_trip,
    make_fleet_admin_headers,
    make_safety_officer_headers,
    post_duty_event,
    record_safety_event,
    set_clock,
    setup_planned_trip,
    validate_error,
    validate_paginated,
    validate_success,
)

FLEET_ADMIN = make_fleet_admin_headers()
SAFETY_OFFICER = make_safety_officer_headers()


def _driver_with_driving_event(cdl_number="CDL-6"):
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number=cdl_number)
    assert driver["employment_status"] == "ACTIVE"
    assert driver["duty_status"] == "OFF_DUTY"
    post_duty_event(driver["id"], event_type="DRIVING",
                    occurred_at="2026-08-01T06:00:00Z")
    return driver


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / driver_parallel_employment_x_duty_dimensions
# ---------------------------------------------------------------------------

def test_suspend_preserves_duty_status(api):
    """PRD §3.8: "A driver's `employment_status` — `ACTIVE`, `SUSPENDED`, or
    the terminal `TERMINATED` — is entirely independent of the `duty_status`
    mirror of the event stream; suspending a driver, in particular, does not
    rewrite their `duty_status`."

    Design: Difficulty/non_linear_state_machine/driver_parallel_employment_x_duty_dimensions
    """
    driver = _driver_with_driving_event()
    suspended = validate_success(
        api_client.suspend_driver(driver["id"], SAFETY_OFFICER))
    assert suspended["employment_status"] == "SUSPENDED"
    assert suspended["duty_status"] == "DRIVING", (
        "the duty axis is an independent projection of the event stream")


def test_reinstate_preserves_duty_status(api):
    """PRD §3.8: "Reinstatement by a `SafetyOfficer` returns a `SUSPENDED`
    driver to `ACTIVE` — from any other state, `ERR_DRIVER_NOT_SUSPENDED`."
    PRD §3.8: "A driver's `employment_status` — `ACTIVE`, `SUSPENDED`, or the
    terminal `TERMINATED` — is entirely independent of the `duty_status`
    mirror of the event stream; suspending a driver, in particular, does not
    rewrite their `duty_status`."

    Design: Difficulty/non_linear_state_machine/driver_parallel_employment_x_duty_dimensions
    """
    driver = _driver_with_driving_event()
    validate_success(api_client.suspend_driver(driver["id"], SAFETY_OFFICER))
    reinstated = validate_success(
        api_client.reinstate_driver(driver["id"], SAFETY_OFFICER))
    assert reinstated["employment_status"] == "ACTIVE"
    assert reinstated["duty_status"] == "DRIVING", (
        "employment transitions never touch the duty axis")


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / driver_suspension_three_hop_cascade
# ---------------------------------------------------------------------------

def test_suspend_cancels_trip_with_safety_reason(api):
    """PRD §3.8: "the suspension cascades through the dispatch book: every
    non-terminal trip of the driver, meaning each in `PLANNED`, `DISPATCHED`,
    or `AT_PICKUP`, is cancelled with `cancel_reason` `SAFETY`".

    Design: Difficulty/transitive_cascade/driver_suspension_three_hop_cascade
    """
    ctx = setup_planned_trip(cdl_number="CDL-8", unit_number="T-8")
    suspended = validate_success(
        api_client.suspend_driver(ctx["driver"]["id"], SAFETY_OFFICER))
    assert suspended["employment_status"] == "SUSPENDED"
    trip = get_trip(ctx["trip"]["id"])
    assert trip["status"] == "CANCELLED"
    assert trip["cancel_reason"] == "SAFETY"


def test_suspend_rolls_back_load_and_releases_tractor(api):
    """PRD §3.8: "each such cancellation rolls its load back to `ACCEPTED` with
    `reassignment_count` incremented by one and releases its tractor from
    `ASSIGNED` to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/driver_suspension_three_hop_cascade
    """
    ctx = setup_planned_trip(cdl_number="CDL-8", unit_number="T-8")
    validate_success(api_client.suspend_driver(ctx["driver"]["id"],
                                               SAFETY_OFFICER))
    load = get_load(ctx["load"]["id"])
    assert load["status"] == "ACCEPTED"
    assert load["reassignment_count"] == 1
    assert get_tractor(ctx["tractor"]["id"])["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / safety_event_void_restores_score
# ---------------------------------------------------------------------------

def test_void_restores_safety_score(api):
    """PRD §3.8: "A driver's `safety_score` starts at 100 and is recomputed
    immediately whenever an event is recorded or voided. Every non-voided event
    contributes its `severity_points`, weighted by age at the logical now".
    (Add severity 10 -> 90; void -> exactly 100 again.)

    Design: Difficulty/compensating_invariant/safety_event_void_restores_score
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-17")
    assert driver["safety_score"] == 100
    event = record_safety_event(driver["id"], kind="INSPECTION_VIOLATION",
                                severity_points=10,
                                occurred_at="2026-07-15T00:00:00Z")
    assert get_driver(driver["id"])["safety_score"] == 90
    validate_success(api_client.void_safety_event(event["id"], SAFETY_OFFICER))
    assert get_driver(driver["id"])["safety_score"] == 100, (
        "voided events are excluded from the score; add+void conserves it")


def test_double_void_rejected(api):
    """PRD §3.8: "a `SafetyOfficer` may later void one as a compensating
    action, setting `voided` true, and voiding an already-voided event is
    rejected with `ERR_SAFETY_EVENT_NOT_VOIDABLE`."

    Design: Difficulty/compensating_invariant/safety_event_void_restores_score
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-17")
    event = record_safety_event(driver["id"], kind="INSPECTION_VIOLATION",
                                severity_points=10,
                                occurred_at="2026-07-15T00:00:00Z")
    validate_success(api_client.void_safety_event(event["id"], SAFETY_OFFICER))
    resp = api_client.void_safety_event(event["id"], SAFETY_OFFICER)
    validate_error(resp, ApiErrorId.ERR_SAFETY_EVENT_NOT_VOIDABLE)


def test_terminate_cascades_and_locks(api):
    """PRD §3.8: "Termination by a `FleetAdmin` lands from `ACTIVE` or
    `SUSPENDED` — acting on a driver already `TERMINATED` is rejected with
    `ERR_DRIVER_ALREADY_TERMINATED` — and applies the same trip cascade as
    suspension, cancelling every non-terminal trip with `cancel_reason`
    `SAFETY` and the same per-trip rollback of load and tractor."
    PRD §3.8: "A `SafetyOfficer` suspends an `ACTIVE` driver — suspension from
    any other state is rejected with `ERR_DRIVER_NOT_ACTIVE`".

    Design: Corner/state_machines/driver_terminate_cascades_and_locks
    """
    ctx = setup_planned_trip(cdl_number="CDL-C21", unit_number="T-C21")
    terminated = validate_success(
        api_client.terminate_driver(ctx["driver"]["id"], FLEET_ADMIN))
    assert terminated["employment_status"] == "TERMINATED"
    trip = get_trip(ctx["trip"]["id"])
    assert trip["status"] == "CANCELLED"
    assert trip["cancel_reason"] == "SAFETY"
    assert get_load(ctx["load"]["id"])["status"] == "ACCEPTED"
    assert get_tractor(ctx["tractor"]["id"])["status"] == "AVAILABLE"

    validate_error(api_client.suspend_driver(ctx["driver"]["id"], SAFETY_OFFICER),
                   ApiErrorId.ERR_DRIVER_NOT_ACTIVE)
    validate_error(api_client.terminate_driver(ctx["driver"]["id"], FLEET_ADMIN),
                   ApiErrorId.ERR_DRIVER_ALREADY_TERMINATED)


def test_reinstate_active_driver_rejected(api):
    """PRD §3.8: "Reinstatement by a `SafetyOfficer` returns a `SUSPENDED`
    driver to `ACTIVE` — from any other state, `ERR_DRIVER_NOT_SUSPENDED`."

    Design: Corner/errors/driver_reinstate_active_rejected
    """
    driver = create_driver(cdl_number="CDL-R12")
    resp = api_client.reinstate_driver(driver["id"], SAFETY_OFFICER)
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_SUSPENDED)


def test_safety_decay_full_vs_half_weight(api):
    """PRD §3.8: "Every non-voided event contributes its `severity_points`,
    weighted by age at the logical now: full weight while the event is at most
    8760 hours old — 365 days, the boundary included; half weight while it is
    older than that but at most 17520 hours old — 730 days, again with the
    boundary included; and no weight at all beyond that."

    Design: Corner/calculations/safety_decay_half_vs_full_weight
    """
    set_clock("2026-08-01T06:00:00Z")
    drv_a = create_driver(cdl_number="CDL-C29A")
    record_safety_event(drv_a["id"], kind="INSPECTION_VIOLATION",
                        severity_points=20, occurred_at="2025-06-27T06:00:00Z")
    drv_b = create_driver(cdl_number="CDL-C29B")
    record_safety_event(drv_b["id"], kind="INSPECTION_VIOLATION",
                        severity_points=20, occurred_at="2025-08-01T06:00:00Z")
    assert get_driver(drv_a["id"])["safety_score"] == 90, (
        "400 days old -> half weight: 100 - round_half_up(20 * 0.5)")
    assert get_driver(drv_b["id"])["safety_score"] == 80, (
        "exactly 8760 hours old -> full weight, boundary included: 100 - 20")


def test_manual_hos_violation_kind_rejected(api):
    """PRD §3.8: "The third kind, `HOS_VIOLATION`, is reserved to the system —
    it arises only from the illegal-driving rule of §3.4 with `source`
    `AUTO_HOS` — and an attempt to record one manually is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/errors/manual_hos_violation_kind_rejected
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-R2")
    resp = api_client.create_safety_event(
        driver["id"], {"kind": "HOS_VIOLATION",
                       "occurred_at": "2026-07-15T00:00:00Z"},
        SAFETY_OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_illegal_driving_auto_creates_hos_violation(api):
    """PRD §3.4: "A `DRIVING` event appended while `break_blocked` is true, or
    while any of the three remaining-minutes clocks stands at zero, is still
    recorded — and it also auto-creates a SafetyEvent of kind `HOS_VIOLATION`
    with `severity_points` 5 and `source` `AUTO_HOS`, which immediately
    recomputes the driver's `safety_score` as described in §3.8."
    (660 driving minutes already accumulated today -> drive_11h remaining 0.)

    Design: Corner/errors/auto_hos_violation_created_on_illegal_driving
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-R3")
    post_duty_event(driver["id"], event_type="DRIVING",
                    occurred_at="2026-08-01T06:00:00Z")
    set_clock("2026-08-01T17:00:00Z")
    post_duty_event(driver["id"], event_type="OFF_DUTY",
                    occurred_at="2026-08-01T17:00:00Z")
    set_clock("2026-08-01T17:30:00Z")
    recorded = post_duty_event(driver["id"], event_type="DRIVING",
                               occurred_at="2026-08-01T17:30:00Z")
    assert recorded["event_type"] == "DRIVING", "violations are logged"

    events, _ = validate_paginated(
        api_client.list_safety_events(driver["id"], SAFETY_OFFICER))
    assert len(events) == 1
    assert events[0]["kind"] == "HOS_VIOLATION"
    assert events[0]["source"] == "AUTO_HOS"
    assert events[0]["severity_points"] == 5
    assert get_driver(driver["id"])["safety_score"] == 95


def test_driver_version_increments_on_every_mutation(api):
    """PRD §2.5: "`version` — an integer assigned the value 1 at creation and
    incremented by one on every mutation of the resource, again including
    cascaded mutations."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_mutation
    """
    driver = create_driver(cdl_number="CDL-X1")
    assert driver["version"] == 1
    patched = validate_success(api_client.patch_driver(
        driver["id"], {"home_terminal": "FTW", "expected_driver_version": 1},
        FLEET_ADMIN))
    assert patched["version"] == 2
    suspended = validate_success(
        api_client.suspend_driver(driver["id"], SAFETY_OFFICER))
    assert suspended["version"] == 3, "suspend is a mutation and must bump version"


def test_safety_event_recompute_bumps_driver_version(api):
    """PRD §2.7: "Whenever one operation ripples into another resource —
    assigning a load, releasing a tractor, cascading a suspension, flipping
    accessorials to billed — every resource the server touches has its
    `updated_at` refreshed and its `version` incremented, whether or not the
    client named that resource in the request."
    PRD §2.7: "the `safety_score` is recomputed the moment a safety event is
    recorded or voided".

    Design: Corner/cross_cutting_complexity_layers/cascade_updates_version_and_score
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-X4")
    assert driver["version"] == 1
    record_safety_event(driver["id"], kind="INSPECTION_VIOLATION",
                        severity_points=10, occurred_at="2026-07-15T00:00:00Z")
    after = get_driver(driver["id"])
    assert after["safety_score"] == 90
    assert after["version"] == 2, (
        "the cascaded score recompute mutates the driver row")
