"""Capacity boundary tests: window slot capacity, park gate capacity, redeem
window boundary, and admit/exit conservation.

Covers the boundary-precision, resource-temporal-overlap, and compensating-
invariant difficulty instances plus the consistency-model corner instance.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park, set_clock, create_ride, create_window, create_guest,
    create_day_ticket, admit, book_vq, confirm,
    setup_park_ride_window, setup_booked_reservation,
    make_park_admin_headers, make_ride_operator_headers, make_guest_headers,
)

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


def test_window_capacity_boundary_rejects_overfill(api):
    """PRD §3.3: "for a `VIRTUAL_QUEUE` booking, the window must have room: its
    `reserved_count` must be strictly below its `slot_capacity`, or the request is
    rejected with `ERR_WINDOW_EXHAUSTED`."

    Ride R5 -> 60-min window capacity exactly 2; two bookings succeed, the third
    (reserved_count would reach 3 > 2) is rejected.

    Design: Difficulty/boundary_precision_check/window_capacity_boundary_at_slot_capacity
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5)
    ga = create_guest(park["id"], full_name="GA")
    gb = create_guest(park["id"], full_name="GB")
    gc = create_guest(park["id"], full_name="GC")
    res_a = book_vq(ride["id"], ga["id"], window["id"], window["version"])
    res_b = book_vq(ride["id"], gb["id"], window["id"], res_a["version"])
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": gc["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": res_b["version"]},
        make_guest_headers(gc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_EXHAUSTED)


def test_window_aggregate_capacity_overlap_rejected(api):
    """PRD §3.3: "for a `VIRTUAL_QUEUE` booking, the window must have room: its
    `reserved_count` must be strictly below its `slot_capacity`, or the request is
    rejected with `ERR_WINDOW_EXHAUSTED`."

    All reservations share one half-open window; a new occupation is rejected once
    the aggregate reserved_count equals slot_capacity (2).

    Design: Difficulty/resource_temporal_overlap/window_aggregate_capacity_overlap_on_return_window
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=5, clock="2026-06-15T09:30:00.000Z")
    ga = create_guest(park["id"], full_name="GA")
    gb = create_guest(park["id"], full_name="GB")
    gc = create_guest(park["id"], full_name="GC")
    res_a = book_vq(ride["id"], ga["id"], window["id"], window["version"])
    res_b = book_vq(ride["id"], gb["id"], window["id"], res_a["version"])
    resp = api.create_reservation(
        {"ride_id": ride["id"], "guest_id": gc["id"], "return_window_id": window["id"],
         "queue_type": "VIRTUAL_QUEUE", "expected_return_window_id_version": res_b["version"]},
        make_guest_headers(gc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_EXHAUSTED)


def test_park_admission_boundary_rejects_over_capacity(api):
    """PRD §3.2: "Admission may proceed only when the ticket is `ISSUED`, its
    `ticket_date` equals the park's `operating_date`, and the park is not full
    (`admitted_count` strictly less than `gate_capacity`); if the park is already at
    or above its gate capacity, admission is rejected with `ERR_PARK_AT_CAPACITY`."

    gate_capacity 2: two admissions succeed (admitted_count reaches 2, FULL); the
    third is rejected.

    Design: Difficulty/boundary_precision_check/park_admission_boundary_at_gate_capacity
    """
    park = create_park(gate_capacity=2)
    tickets = []
    for i in range(3):
        g = create_guest(park["id"], full_name=f"G{i}")
        t = create_day_ticket(park["id"], g["id"])
        tickets.append(t["id"])
    admit(park["id"], tickets[0])
    admit(park["id"], tickets[1])
    resp = api.admit(park["id"], {"ticket_id": tickets[2]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PARK_AT_CAPACITY)


def test_redeem_at_exclusive_end_boundary_rejected(api):
    """PRD §3.4: "A booked reservation may be redeemed only when it is `BOOKED`, its
    parent ride is `OPEN`, and — for a `VIRTUAL_QUEUE` reservation — the park's
    `current_utc` falls within the window: at or after `window_start_utc` and
    strictly before `window_end_utc`. A redemption attempted outside that interval
    is rejected with `ERR_WINDOW_NOT_REDEEMABLE`".

    Clock at exactly 11:00:00 == window_end_utc is OUTSIDE [10:00, 11:00).

    Design: Difficulty/resource_temporal_overlap/redeem_exclusive_end_boundary_on_reservation
    """
    park, ride, window, guest, booked = setup_booked_reservation(clock="2026-06-15T10:30:00.000Z")
    set_clock(park["id"], "2026-06-15T11:00:00.000Z")
    resp = api.redeem_reservation(booked["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_REDEEMABLE)


def test_admission_count_conserved_under_admit_then_exit(api):
    """PRD §3.2: "The complementary exit, also performed by a `ParkAdmin` by
    supplying the `ticket_id`, may proceed only when the ticket is `ADMITTED`; it
    moves the ticket from `ADMITTED` to `EXITED`, decreases `admitted_count` by one,
    recomputes `day_phase` (which may relax the park from `FULL` toward `PEAK` and
    then `OPEN`), and advances `Park.version`."

    gate_capacity 1: admit (admitted_count 1, FULL) then exit (back to 0, OPEN).

    Design: Difficulty/compensating_invariant/park_admission_count_conserved_under_admit_then_exit
    """
    park = create_park(gate_capacity=1)
    guest = create_guest(park["id"], full_name="GA")
    ticket = create_day_ticket(park["id"], guest["id"])
    admit(park["id"], ticket["id"])
    data = validate_success(api.exit_guest(park["id"], {"ticket_id": ticket["id"]}, ADMIN), expected_status=201)
    assert data["admission_status"] == "EXITED"

    park_data = validate_success(api.get_park(park["id"], ADMIN))
    assert park_data["admitted_count"] == 0, \
        f"admitted_count must return to 0, got {park_data['admitted_count']}"
    assert park_data["day_phase"] == "OPEN", \
        f"day_phase must relax to OPEN, got {park_data['day_phase']}"


def test_admission_to_full_visible_in_same_response(api):
    """PRD §2.8: "it is `FULL` once `admitted_count` reaches `gate_capacity` or more."
    PRD §3.2: "A successful admission moves the ticket from `ISSUED` to `ADMITTED`,
    increases the park's `admitted_count` by one, recomputes the park's `day_phase`
    from the new occupancy".

    gate_capacity 1: the admission crossing capacity returns the ticket ADMITTED;
    the park then reads day_phase FULL and admitted_count 1.

    Design: Corner/consistency_model/admission_day_phase_visible_in_same_response
    """
    park = create_park(gate_capacity=1)
    guest = create_guest(park["id"], full_name="G1")
    ticket = create_day_ticket(park["id"], guest["id"])
    data = validate_success(api.admit(park["id"], {"ticket_id": ticket["id"]}, ADMIN), expected_status=201)
    assert data["admission_status"] == "ADMITTED"

    park_data = validate_success(api.get_park(park["id"], ADMIN))
    assert park_data["admitted_count"] == 1, f"expected admitted_count 1, got {park_data['admitted_count']}"
    assert park_data["day_phase"] == "FULL", f"expected day_phase FULL, got {park_data['day_phase']}"
