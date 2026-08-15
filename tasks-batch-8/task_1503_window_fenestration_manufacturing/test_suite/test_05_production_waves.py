"""Production wave planning: capacity, lead-time gating, OCC, lifecycle (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    assert_production_wave,
    assign_order,
    confirm_order,
    create_draft_order,
    create_open_wave,
    create_wave,
    create_wave_payload,
    get_success_data,
    lock_and_release,
    setup_confirmed_order,
    setup_mn_catalog,
    setup_order_in_production,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PL = TEST_USERS["production_lead_headers"]


def test_wave_create_computed_input_ignored(api):
    """PRD §3.4: "Creating a wave takes a `wave_date`, a `capacity_units` ceiling
    on total window units, and a `capacity_glass_sqft` ceiling on total glazing
    area; the wave starts `PLANNED` with `allocated_units` and
    `allocated_glass_sqft` at zero."

    Design: Corner/entities/wave_create_computed_input_ignored
    """
    payload = create_wave_payload()
    payload["allocated_units"] = 99  # computed field supplied by client: ignored
    wave = validate_success(api.create_wave(payload, PL), 201)
    assert wave["allocated_units"] == 0
    assert wave["status"] == "PLANNED"
    assert isinstance(wave["version"], int)


def test_computed_fields_immediate_in_create_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "Creating a wave takes a `wave_date`, a `capacity_units` ceiling
    on total window units, and a `capacity_glass_sqft` ceiling on total glazing
    area; the wave starts `PLANNED` with `allocated_units` and
    `allocated_glass_sqft` at zero."

    Design: Corner/consistency_model/computed_fields_immediate_in_create_response
    """
    wave = validate_success(api.create_wave(create_wave_payload(), PL), 201)
    assert_production_wave(wave)
    assert wave["allocated_units"] == 0
    assert wave["allocated_glass_sqft"] == pytest.approx(0.0, abs=0.001)
    assert wave["status"] == "PLANNED"


def test_assign_to_planned_wave_returns_wave_not_open(api):
    """PRD §3.4: "Then come the state gates: the wave must be `OPEN`
    (`ERR_WAVE_NOT_OPEN`) and the order must be `CONFIRMED`
    (`ERR_ORDER_NOT_CONFIRMED`)."

    Design: Corner/errors/assign_to_planned_wave_returns_wave_not_open
    """
    env = setup_confirmed_order()
    wave = create_wave()  # left PLANNED, never opened
    res = api.assign_order_to_wave(
        wave["id"],
        {"order_id": env["order"]["id"], "expected_wave_version": wave["version"]},
        PL,
    )
    validate_error(res, ApiErrorId.ERR_WAVE_NOT_OPEN, expected_status=409)
    order = validate_success(api.get_order(env["order"]["id"], PM), 200)
    assert order["production_status"] == "CONFIRMED"


def test_wave_unit_capacity_equality_boundary_admitted(api):
    """PRD §3.4: "Finally the capacity gates, both with inclusive boundaries:
    the order's total line quantity, added to `allocated_units`, must not exceed
    `capacity_units` (`ERR_WAVE_CAPACITY_EXCEEDED`), and the order's glazing —
    each line's `glazing_sqft` times its `quantity`, summed — added to
    `allocated_glass_sqft`, must not exceed `capacity_glass_sqft`
    (`ERR_WAVE_GLASS_CAPACITY_EXCEEDED`). An exactly-full wave still accepts the
    assignment."

    Design: Difficulty/boundary_precision_check/wave_unit_capacity_equality_boundary
    """
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=6)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])
    add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=4)
    confirm_order(order_b["id"])

    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=2000)
    after_a = assign_order(wave["id"], order_a["id"])
    assert after_a["allocated_units"] == 6
    after_b = assign_order(wave["id"], order_b["id"])
    assert after_b["allocated_units"] == 10, "equality with capacity_units must be admitted"


def test_wave_unit_capacity_beyond_rejected(api):
    """PRD §3.4: "Finally the capacity gates, both with inclusive boundaries:
    the order's total line quantity, added to `allocated_units`, must not exceed
    `capacity_units` (`ERR_WAVE_CAPACITY_EXCEEDED`)"

    Design: Difficulty/boundary_precision_check/wave_unit_capacity_equality_boundary
    """
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=6)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])
    add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=4)
    confirm_order(order_b["id"])
    order_c = create_draft_order(cat["dealer"]["id"])
    add_line(order_c["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_c["id"])

    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=2000)
    assign_order(wave["id"], order_a["id"])
    assign_order(wave["id"], order_b["id"])

    current = get_success_data(api.get_wave(wave["id"], PL))
    res = api.assign_order_to_wave(
        wave["id"],
        {"order_id": order_c["id"], "expected_wave_version": current["version"]},
        PL,
    )
    validate_error(res, ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED, expected_status=409)
    order_c_after = validate_success(api.get_order(order_c["id"], PM), 200)
    assert order_c_after["production_status"] == "CONFIRMED"


def test_wave_glass_capacity_boundary(api):
    """PRD §3.4: "Finally the capacity gates, both with inclusive boundaries:
    the order's total line quantity, added to `allocated_units`, must not exceed
    `capacity_units` (`ERR_WAVE_CAPACITY_EXCEEDED`), and the order's glazing —
    each line's `glazing_sqft` times its `quantity`, summed — added to
    `allocated_glass_sqft`, must not exceed `capacity_glass_sqft`
    (`ERR_WAVE_GLASS_CAPACITY_EXCEEDED`). An exactly-full wave still accepts the
    assignment."
    PRD §3.4: "`allocated_units` is the sum of `quantity` over the counted
    lines; `allocated_glass_sqft` is the sum of each counted line's
    `glazing_sqft` times its `quantity`, rounded half-up to two decimal places
    after the summation."

    Design: Corner/calculations/wave_glass_capacity_boundary
    """
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=2)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])
    add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_b["id"])

    wave = create_open_wave(capacity_units=100, capacity_glass_sqft=50.0)
    after_a = assign_order(wave["id"], order_a["id"])
    # glazing 16.67 per unit x 2 = 33.34
    assert after_a["allocated_glass_sqft"] == pytest.approx(33.34, abs=0.001)

    current = get_success_data(api.get_wave(wave["id"], PL))
    res = api.assign_order_to_wave(
        wave["id"],
        {"order_id": order_b["id"], "expected_wave_version": current["version"]},
        PL,
    )
    # 33.34 + 16.67 = 50.01 > 50.0 even though 97 unit slots remain free
    validate_error(res, ApiErrorId.ERR_WAVE_GLASS_CAPACITY_EXCEEDED, expected_status=409)


def test_lead_time_gate_special_vs_standard(api):
    """PRD §3.4: "Next the temporal gate: the `wave_date` may not be earlier
    than the order's `order_date` plus the largest `lead_time_days` among its
    non-`CANCELLED` lines — an earlier wave date is rejected with
    `ERR_WAVE_BEFORE_LEAD_TIME`."
    PRD §3.2: "The order's `promised_date` is its `order_date` plus the largest
    `lead_time_days` among its non-`CANCELLED` lines, recomputed whenever a line
    is added, edited, or cancelled."

    Design: Corner/calculations/lead_time_gate_special_vs_standard
    """
    cat = setup_mn_catalog()
    order_s = create_draft_order(cat["dealer"]["id"])
    add_line(order_s["id"], cat["series"]["id"], cat["glass"]["id"],
             shape="ARCH", width_in=36, height_in=48)  # lead_time_days 25
    confirm_order(order_s["id"])
    order_r = create_draft_order(cat["dealer"]["id"])
    add_line(order_r["id"], cat["series"]["id"], cat["glass"]["id"])  # lead 10
    confirm_order(order_r["id"])

    wave_early = create_open_wave(wave_date="2026-08-26T00:00:00Z",
                                 capacity_units=100, capacity_glass_sqft=2000)
    wave_ok = create_open_wave(wave_date="2026-08-27T00:00:00Z",
                               capacity_units=100, capacity_glass_sqft=2000)

    # RECTANGLE order (2026-08-02 + 10d = 2026-08-12) fits the earlier wave
    after_r = assign_order(wave_early["id"], order_r["id"])
    assert after_r["allocated_units"] == 1

    current = get_success_data(api.get_wave(wave_early["id"], PL))
    too_early = api.assign_order_to_wave(
        wave_early["id"],
        {"order_id": order_s["id"], "expected_wave_version": current["version"]},
        PL,
    )
    validate_error(too_early, ApiErrorId.ERR_WAVE_BEFORE_LEAD_TIME, expected_status=409)

    admitted = assign_order(wave_ok["id"], order_s["id"])
    assert admitted["allocated_units"] == 1

    fetched = validate_success(api.get_order(order_s["id"], PM), 200)
    assert str(fetched["promised_date"]).startswith("2026-08-27"), (
        f"order_date + 25d special-shape lead, got {fetched['promised_date']!r}"
    )


def test_wave_assign_unassign_conserves_capacity(api):
    """PRD §3.4: "An assignment can be walked back before the wave releases:
    unassigning takes the `order_id`, moves the order `RELEASED → CONFIRMED` and
    its lines back to `CONFIRMED`, clears the order's `wave_id`, releases the
    allocation, and increments the wave's `version`."

    Design: Difficulty/compensating_invariant/wave_assign_unassign_conserves_capacity
    """
    env = setup_confirmed_order(quantity=4)
    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=500)
    assert wave["allocated_units"] == 0

    assigned = assign_order(wave["id"], env["order"]["id"])
    assert assigned["allocated_units"] == 4
    assert assigned["allocated_glass_sqft"] == pytest.approx(66.68, abs=0.001)

    unassigned = validate_success(api.unassign_order_from_wave(
        wave["id"], {"order_id": env["order"]["id"]}, PL
    ), 200)
    assert unassigned["allocated_units"] == 0
    assert unassigned["allocated_glass_sqft"] == pytest.approx(0.0, abs=0.001)

    order = validate_success(api.get_order(env["order"]["id"], PM), 200)
    assert order["production_status"] == "CONFIRMED"
    assert order["wave_id"] is None


def test_assign_and_unassign_each_increment_wave_version(api):
    """PRD §3.4: "On success the order moves `CONFIRMED → RELEASED` with its
    `wave_id` set to the wave, each of its lines moves `CONFIRMED → RELEASED`,
    the wave's allocation counters are recomputed upward, and the wave's
    `version` increments by one."
    PRD §3.4: "An assignment can be walked back before the wave releases:
    unassigning takes the `order_id`, moves the order `RELEASED → CONFIRMED` and
    its lines back to `CONFIRMED`, clears the order's `wave_id`, releases the
    allocation, and increments the wave's `version`."

    Design: Difficulty/compensating_invariant/wave_assign_unassign_conserves_capacity
    """
    env = setup_confirmed_order(quantity=4)
    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=500)
    v0 = wave["version"]

    assigned = assign_order(wave["id"], env["order"]["id"])
    assert assigned["version"] == v0 + 1
    unassigned = validate_success(api.unassign_order_from_wave(
        wave["id"], {"order_id": env["order"]["id"]}, PL
    ), 200)
    assert unassigned["version"] == v0 + 2
    line = validate_success(api.get_order_line(env["line"]["id"], PL), 200)
    assert line["status"] == "CONFIRMED"


def test_state_before_fiscal_on_wave_assignment(api):
    """PRD §2.10: "When several violations are present at once, the error
    returned is the one from the earliest stage in this order — later checks
    never mask earlier ones"
    PRD §3.4: "Then come the state gates: the wave must be `OPEN`
    (`ERR_WAVE_NOT_OPEN`) and the order must be `CONFIRMED`
    (`ERR_ORDER_NOT_CONFIRMED`)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_wave_assignment
    """
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])  # left DRAFT
    add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)

    wave = create_open_wave(capacity_units=1, capacity_glass_sqft=500)
    assign_order(wave["id"], order_a["id"])  # wave now exactly full

    current = get_success_data(api.get_wave(wave["id"], PL))
    res = api.assign_order_to_wave(
        wave["id"],
        {"order_id": order_b["id"], "expected_wave_version": current["version"]},
        PL,
    )
    # state (stage 7) beats capacity/fiscal (stage 11)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_CONFIRMED, expected_status=409)


def test_rejected_assignment_leaves_wave_and_order_untouched(api):
    """PRD §3.4: "Then come the state gates: the wave must be `OPEN`
    (`ERR_WAVE_NOT_OPEN`) and the order must be `CONFIRMED`
    (`ERR_ORDER_NOT_CONFIRMED`)."
    PRD §3.4: "`allocated_units` is the sum of `quantity` over the counted
    lines; `allocated_glass_sqft` is the sum of each counted line's
    `glazing_sqft` times its `quantity`, rounded half-up to two decimal places
    after the summation."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_wave_assignment
    """
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])
    add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)

    wave = create_open_wave(capacity_units=1, capacity_glass_sqft=500)
    assign_order(wave["id"], order_a["id"])

    current = get_success_data(api.get_wave(wave["id"], PL))
    validate_error(api.assign_order_to_wave(
        wave["id"],
        {"order_id": order_b["id"], "expected_wave_version": current["version"]},
        PL,
    ), ApiErrorId.ERR_ORDER_NOT_CONFIRMED)

    after = get_success_data(api.get_wave(wave["id"], PL))
    assert after["allocated_units"] == 1
    order_b_after = validate_success(api.get_order(order_b["id"], PM), 200)
    assert order_b_after["production_status"] == "DRAFT"


def test_stale_wave_version_returns_412(api):
    """PRD §2.8: "Assigning an order to a production wave requires the request
    to carry `expected_wave_version`, the `version` of the `ProductionWave` the
    client last observed. If the wave's current `version` does not match —
    because another assignment, unassignment, breakage cascade, or cancellation
    has advanced it since the client read the wave — the assignment is rejected
    with `ERR_STALE_VERSION` (HTTP 412), even when the remaining capacity would
    legitimately admit the order: the client's view of the wave is stale, and
    proceeding would overwrite changes the client never saw."

    Design: Corner/cross_cutting_complexity_layers/stale_wave_version_returns_412
    """
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])
    add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_b["id"])

    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=500)
    observed = get_success_data(api.get_wave(wave["id"], PL))["version"]

    accepted = validate_success(api.assign_order_to_wave(
        wave["id"], {"order_id": order_a["id"], "expected_wave_version": observed}, PL
    ), 200)
    assert accepted["version"] == observed + 1

    stale = api.assign_order_to_wave(
        wave["id"], {"order_id": order_b["id"], "expected_wave_version": observed}, PL
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    order_b_after = validate_success(api.get_order(order_b["id"], PM), 200)
    assert order_b_after["production_status"] == "CONFIRMED"
    wave_after = get_success_data(api.get_wave(wave["id"], PL))
    assert wave_after["allocated_units"] == 1


def test_wave_cancel_with_assignments_returns_error(api):
    """PRD §3.4: "Cancelling a wave is possible from `PLANNED` or `OPEN` only
    while it is empty — an `allocated_units` of zero; otherwise the cancel is
    rejected with `ERR_WAVE_HAS_ASSIGNMENTS`."

    Design: Corner/state_machines/wave_cancel_with_assignments_returns_error
    """
    env = setup_confirmed_order(quantity=1)
    wave = create_open_wave()
    assign_order(wave["id"], env["order"]["id"])

    res = api.cancel_wave(wave["id"], PL)
    validate_error(res, ApiErrorId.ERR_WAVE_HAS_ASSIGNMENTS, expected_status=409)
    after = get_success_data(api.get_wave(wave["id"], PL))
    assert after["status"] == "OPEN"


def test_wave_release_without_assignments_returns_invalid_state(api):
    """PRD §3.4: "Releasing a wave moves `LOCKED → RELEASED` and is allowed only
    when at least one assigned, non-`CANCELLED` order exists (otherwise
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/wave_release_without_assignments_returns_invalid_state
    """
    wave = create_open_wave()
    get_success_data(api.lock_wave(wave["id"], PL))
    res = api.release_wave(wave["id"], PL)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_wave(wave["id"], PL))
    assert after["status"] == "LOCKED"


def test_wave_close_blocked_while_orders_in_flight(api):
    """PRD §3.4: "Closing a wave (`RELEASED → CLOSED`) is allowed only when
    nothing is in flight: no assigned order may still be `RELEASED` or
    `IN_PROGRESS`, and no line may be on `GLASS_HOLD` (violations return
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/wave_close_blocked_while_orders_in_flight
    """
    env = setup_order_in_production(quantity=1)
    res = api.close_wave(env["wave"]["id"], PL)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_wave(env["wave"]["id"], PL))
    assert after["status"] == "RELEASED"
