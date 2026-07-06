"""Cross-entity state gates (order<-COI, reservation<-order) and temporal-overlap
capacity (equipment aggregate-day windows, crew turnaround buffer), plus the
reserve/release equipment-unit conservation invariant."""
from test_helpers import (
    validate_success, validate_error,
    set_clock, new_customer, new_venue, new_equipment, new_crew_member, new_order,
    add_reservation, add_crew_assignment, submit_coi, approve_coi, order_version,
    confirm_fresh, setup_quoted_order_single_led, setup_confirmed_order_single_led,
    create_reservation_payload, create_crew_assignment_payload,
)


# ─── cross_entity_state_dependency / order_confirm_requires_coi_approved ──
def test_confirm_blocked_while_coi_only_submitted(api, account_manager_headers):
    """PRD §3.7: "The order must have a valid certificate on file — an `APPROVED`
    certificate whose coverage is at least the venue's `required_coverage_cents` and
    whose expiry is strictly after `event_end_date` — or it is refused with
    `ERR_COI_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_coi_approved
    """
    ctx = setup_quoted_order_single_led(qty=1, credit_limit_cents=100_000_000)
    submit_coi(ctx["ord_id"], ctx["cust_id"], coverage_amount_cents=100000)  # left SUBMITTED
    version = order_version(ctx["ord_id"])

    res = api.confirm_order(ctx["ord_id"], {"expected_order_version": version},
                            account_manager_headers)
    validate_error(res, "ERR_COI_NOT_APPROVED", expected_status=409)


def test_confirm_succeeds_after_coi_approved(api, account_manager_headers):
    """PRD §3.5: "A successful approval sets the order's `has_approved_coi` to true."
    PRD §3.7: "An `AccountManager` confirms a `QUOTED` order, advancing it to
    `CONFIRMED`, and several guards apply in the priority order of §2.7."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_coi_approved
    """
    ctx = setup_quoted_order_single_led(qty=1, credit_limit_cents=100_000_000)
    coi = submit_coi(ctx["ord_id"], ctx["cust_id"], coverage_amount_cents=100000)
    approve_coi(coi["id"])

    confirmed = confirm_fresh(ctx["ord_id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["has_approved_coi"] is True


# ─── cross_entity_state_dependency / reservation_checkout_requires_order_loaded_out ──
def test_checkout_blocked_before_order_loaded_out(api, warehouse_manager_headers):
    """PRD §3.8: "A `WarehouseManager` then checks out each reservation, moving it from
    `HELD` to `CHECKED_OUT`; a check-out attempted while the parent order is not
    `LOADED_OUT` is refused with `ERR_ORDER_NOT_LOADED_OUT`."

    Design: Difficulty/cross_entity_state_dependency/reservation_checkout_requires_order_loaded_out
    """
    ctx = setup_confirmed_order_single_led()  # order CONFIRMED, not yet LOADED_OUT

    res = api.check_out_reservation(ctx["res_id"], warehouse_manager_headers)
    validate_error(res, "ERR_ORDER_NOT_LOADED_OUT", expected_status=409)


def test_checkout_succeeds_after_order_loaded_out(api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.8: "A `WarehouseManager` records load-out, advancing the order from
    `CONFIRMED` to `LOADED_OUT`; this is what makes the order's reservations eligible for
    individual check-out."

    Design: Difficulty/cross_entity_state_dependency/reservation_checkout_requires_order_loaded_out
    """
    ctx = setup_confirmed_order_single_led()
    validate_success(api.load_out_order(ctx["ord_id"], warehouse_manager_headers), 200)

    checked = validate_success(
        api.check_out_reservation(ctx["res_id"], warehouse_manager_headers), 200)
    assert checked["status"] == "CHECKED_OUT"


# ─── resource_temporal_overlap / equipment_window_overlap_aggregate_capacity ──
def _order_with_led_hold_15(clock="2026-05-01T00:00:00Z"):
    set_clock(clock)
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-15")
    add_reservation(order["id"], led["id"], qty=15,
                    reserve_start_date="2026-06-10", reserve_end_date="2026-06-12")
    return order, led


def test_overlapping_window_over_capacity_rejected(api, warehouse_manager_headers):
    """PRD §3.2: "the system determines, for each calendar day in the window, how many
    units of that item are already committed by reservations in `HELD` or `CHECKED_OUT`
    status whose own window covers that day, and takes the peak of those daily
    commitments."

    Design: Difficulty/resource_temporal_overlap/equipment_window_overlap_aggregate_capacity
    """
    order, led = _order_with_led_hold_15()
    # qty8 over 06-12..06-14 shares day 06-12 with the qty15 hold: peak 23 > 20.
    res = api.create_reservation(
        order["id"],
        create_reservation_payload(led["id"], qty=8, reserve_start_date="2026-06-12",
                                   reserve_end_date="2026-06-14"),
        warehouse_manager_headers)
    validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE", expected_status=409)


def test_non_overlapping_window_admitted(api, warehouse_manager_headers):
    """PRD §3.2: "The reservation is admitted only when that effective supply, minus the
    peak already-committed units over the window (excluding the reservation being
    created), is at least the requested `qty`; reserving exactly the number of remaining
    units succeeds, while a request for even one more unit than remains is rejected with
    `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/equipment_window_overlap_aggregate_capacity
    """
    order, led = _order_with_led_hold_15()
    # qty8 over 06-13..06-15 shares no day with the qty15 hold (which ends 06-12): peak 8.
    ok = validate_success(api.create_reservation(
        order["id"],
        create_reservation_payload(led["id"], qty=8, reserve_start_date="2026-06-13",
                                   reserve_end_date="2026-06-15"),
        warehouse_manager_headers), 201)
    assert ok["status"] == "HELD"


# ─── resource_temporal_overlap / crew_shift_turnaround_buffer ─────────
def _order_with_crew_shift_8_to_16():
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    crew = new_crew_member(name="Tech One", crew_role="TECH", hourly_rate_cents=4000)
    order = new_order(cust["id"], ven["id"])
    add_crew_assignment(order["id"], crew["id"], assignment_role="TECH",
                        shift_start="2026-06-10T08:00:00Z",
                        shift_end="2026-06-10T16:00:00Z", scheduled_hours=8)
    return order, crew


def test_zero_gap_shift_rejected(api, crew_chief_headers):
    """PRD §3.3: "A request that violates this turnaround is rejected with
    `ERR_CREW_DOUBLE_BOOKED`."
    PRD §3.3: "any new shift for that same person must be separated from every one of
    their other active assignments by at least a turnaround buffer of 60 minutes"

    Design: Difficulty/resource_temporal_overlap/crew_shift_turnaround_buffer
    """
    order, crew = _order_with_crew_shift_8_to_16()
    # New shift starts exactly at the prior shift's end (0-minute gap).
    res = api.create_crew_assignment(
        order["id"],
        create_crew_assignment_payload(crew["id"], assignment_role="TECH",
                                       shift_start="2026-06-10T16:00:00Z",
                                       shift_end="2026-06-10T20:00:00Z", scheduled_hours=4),
        crew_chief_headers)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)


def test_shift_with_full_turnaround_admitted(api, crew_chief_headers):
    """PRD §3.3: "the gap between the end of one shift and the start of the next must be at
    least one hour, evaluated symmetrically so that the new shift may neither begin within
    60 minutes of an existing shift's end nor end within 60 minutes of an existing shift's
    start, and the two intervals may not overlap."

    Design: Difficulty/resource_temporal_overlap/crew_shift_turnaround_buffer
    """
    order, crew = _order_with_crew_shift_8_to_16()
    # New shift starts 60 minutes after the prior shift's 16:00 end.
    ok = validate_success(api.create_crew_assignment(
        order["id"],
        create_crew_assignment_payload(crew["id"], assignment_role="TECH",
                                       shift_start="2026-06-10T17:00:00Z",
                                       shift_end="2026-06-10T21:00:00Z", scheduled_hours=4),
        crew_chief_headers), 201)
    assert ok["status"] == "SCHEDULED"


# ─── compensating_invariant / equipment_units_reserve_release_conserved ──
def test_release_returns_reservation_to_released_state(api, warehouse_manager_headers):
    """PRD §3.2: "A `WarehouseManager` may release a `HELD` reservation while the order is
    in `DRAFT`, `QUOTED`, or `CONFIRMED`, moving it to `RELEASED`; a release attempted from
    any other reservation state or order state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/equipment_units_reserve_release_conserved
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    reservation = add_reservation(order["id"], led["id"], qty=5)

    released = validate_success(
        api.release_reservation(reservation["id"], warehouse_manager_headers), 200)
    assert released["status"] == "RELEASED"


def test_availability_conserved_after_reserve_then_release(api, warehouse_manager_headers):
    """PRD §3.2: "Releasing returns the reserved units to the item's availability pool for
    the window and, if a confirmed inbound sub-rental was linked to that reservation,
    cancels that sub-rental and removes its cost from the order's `sub_rental_cost_cents`."
    PRD §3.2: "`available_units` is the difference between the two."

    Design: Difficulty/compensating_invariant/equipment_units_reserve_release_conserved
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    reservation = add_reservation(order["id"], led["id"], qty=5)
    validate_success(api.release_reservation(reservation["id"], warehouse_manager_headers), 200)

    avail = validate_success(api.get_equipment_availability(
        led["id"], warehouse_manager_headers,
        params={"start_date": "2026-06-10", "end_date": "2026-06-12"}), 200)
    assert avail["available_units"] == 20, avail["available_units"]
