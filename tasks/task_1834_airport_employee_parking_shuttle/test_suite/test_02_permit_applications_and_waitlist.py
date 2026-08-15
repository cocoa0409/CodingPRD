"""Permit applications, lot capacity, and the waitlist: availability boundary,
duplicate-permit gate, capacity PATCH rules, promotion ranking, and the
offer-expiry sweep."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_permit,
    apply_for_permit,
    assert_instant_equals,
    assert_lot,
    create_employee,
    create_lot,
    create_lot_payload,
    create_permit_payload,
    create_program,
    get_lot,
    make_employee_headers,
    open_billing_cycle,
    permits_of_lot,
    set_logical_clock,
    setup_offered_permit,
    setup_program_lot_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]


def test_lot_computed_and_system_fields_input_ignored(api):
    """PRD section 2.4: "Fields described in this document as computed or
    system-managed are never accepted from clients. A client that supplies values
    for such fields does not cause an error; the supplied values are silently
    ignored."
    PRD section 3.2: "Initial status depends on tier: a `CORE` lot starts
    `ACTIVE`, while a `REMOTE` lot starts `STANDBY`."

    Design: Corner/entities/lot_computed_fields_input_ignored
    """
    program = create_program(name="P-E2")

    payload = create_lot_payload(program["id"], code="CORE-A", tier="CORE",
                                 capacity=10)
    payload["occupied_slots"] = 99
    payload["reserved_slots"] = 99
    payload["version"] = 42
    lot = validate_success(api.create_lot(payload, ADMIN), 201)

    assert_lot(lot)
    assert lot["occupied_slots"] == 0, "client-supplied occupied_slots ignored"
    assert lot["reserved_slots"] == 0, "client-supplied reserved_slots ignored"
    assert lot["version"] != 42, "client-supplied version ignored"
    assert lot["status"] == "ACTIVE", "a CORE lot starts ACTIVE"


def test_lot_availability_exactly_one_slot(api):
    """PRD section 3.2: "The available-slot figure is `capacity` minus
    `occupied_slots` minus `reserved_slots`, and it routes new applications: at
    least one available slot yields an offer, while zero yields the waitlist. The
    boundary is inclusive — a lot with exactly one available slot still makes an
    offer."
    PRD section 3.2: "`occupied_slots` counts the lot's permits in `ACTIVE`
    status; `reserved_slots` counts the lot's permits in `OFFERED` status whose
    `offer_expires_at` has not yet passed relative to the logical clock — expired
    offers are excluded from the reservation."

    Design: Corner/calculations/lot_availability_exactly_one_slot
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_program_lot_cycle(lot_overrides={"capacity": 1}, with_cycle=False)
    e1 = create_employee(bundle["program"]["id"], badge_number="B001")
    e2 = create_employee(bundle["program"]["id"], badge_number="B002")

    pa = apply_for_permit(e1, bundle["lot"], vehicle_plate="P001")
    pb = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")

    assert pa["status"] == "OFFERED", "exactly one available slot satisfies >= 1"
    assert pb["status"] == "WAITLISTED", "zero available slots yields the waitlist"

    lot = get_lot(bundle["lot"]["id"])
    assert lot["occupied_slots"] == 0
    assert lot["reserved_slots"] == 1, "the outstanding offer counts as reserved"


def test_employee_second_permit_rejected(api):
    """PRD section 3.3: "Three structural gates guard the application: the program
    must not be `PROGRAM_FROZEN` or `PROGRAM_CLOSED` (`ERR_PROGRAM_FROZEN`); the
    target lot must be bookable (`ERR_LOT_NOT_BOOKABLE`); and the employee may
    hold at most one non-terminal permit — a second application while any permit
    of theirs sits in `REQUESTED`, `WAITLISTED`, `OFFERED`, `ACTIVE`, or
    `SUSPENDED` is rejected with `ERR_DUPLICATE_ACTIVE_PERMIT`."
    PRD section 3.3: "Cancellation — `event_type` `CANCEL` — is permitted from
    `REQUESTED`, `WAITLISTED`, or `OFFERED`; only the `OFFERED` cancellation
    releases a reservation and runs a promotion pass, the other two have no lot
    effects."

    Design: Corner/validations/employee_second_permit_rejected
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_program_lot_cycle(lot_overrides={"capacity": 3}, with_cycle=False)
    employee = create_employee(bundle["program"]["id"], badge_number="B001")
    headers = make_employee_headers(employee["id"])
    first = apply_for_permit(employee, bundle["lot"], vehicle_plate="P001")
    assert first["status"] == "OFFERED"

    dup = api.create_permit(
        create_permit_payload(employee["id"], bundle["lot"]["id"],
                              vehicle_plate="P002"),
        headers,
    )
    validate_error(dup, "ERR_DUPLICATE_ACTIVE_PERMIT", expected_status=409)

    # CANCELLED is terminal, so after cancelling the first permit a fresh
    # application succeeds.
    validate_success(
        api.permit_event(first["id"], {"event_type": "CANCEL"}, headers), 200
    )
    second = apply_for_permit(employee, bundle["lot"], vehicle_plate="P003")
    assert second["status"] == "OFFERED"


def test_capacity_patch_below_occupancy_then_increase_promotes(api):
    """PRD section 3.2: "Capacity can be revised by a `ParkingAdmin`, but never
    below the sum of `occupied_slots` and `reserved_slots`
    (`ERR_CAPACITY_BELOW_OCCUPANCY`). A capacity increase triggers an immediate
    waitlist promotion pass on that lot."

    Design: Corner/validations/capacity_patch_below_occupancy_then_increase_promotes
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_program_lot_cycle(lot_overrides={"capacity": 1})
    e1 = create_employee(bundle["program"]["id"], badge_number="B001")
    e2 = create_employee(bundle["program"]["id"], badge_number="B002")
    p1 = apply_for_permit(e1, bundle["lot"], vehicle_plate="P001")
    accept_permit(p1, e1)
    p2 = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")
    assert p2["status"] == "WAITLISTED"

    too_low = api.patch_lot(bundle["lot"]["id"], {"capacity": 0}, ADMIN)
    validate_error(too_low, "ERR_CAPACITY_BELOW_OCCUPANCY", expected_status=409)

    grown = validate_success(
        api.patch_lot(bundle["lot"]["id"], {"capacity": 2}, ADMIN), 200
    )
    assert grown["capacity"] == 2

    promoted = validate_success(api.get_permit(p2["id"], ADMIN), 200)
    assert promoted["status"] == "OFFERED", (
        "the capacity increase ran an immediate promotion pass"
    )
    assert_instant_equals(promoted["offer_expires_at"], "2026-08-04T00:00:00Z",
                          label="promoted offer_expires_at (ttl 72h)")


def test_waitlist_promotion_shift_priority_over_arrival(api):
    """PRD section 3.3: "Ranking is by shift-class priority descending — `NIGHT`
    ranks highest (priority 3), then `ROTATING` (2), then `SPLIT` (1), then `DAY`
    (0) — with ties broken first by `created_at` ascending and finally by
    `badge_number` ascending; resource ids are never used as tie-breakers."
    PRD section 3.3: "Declining — via a permit event whose `event_type` is
    `DECLINE`, available to the owning employee or a `ParkingAdmin` — moves
    `OFFERED` to `DECLINED`, releases the reservation, and runs an immediate
    promotion pass on the lot."

    Design: Corner/state_machines/waitlist_promotion_shift_priority_over_arrival
    """
    set_logical_clock("2026-08-01T09:00:00Z")
    bundle = setup_program_lot_cycle(lot_overrides={"capacity": 1}, with_cycle=False)
    e1 = create_employee(bundle["program"]["id"], badge_number="B001",
                         shift_pattern="DAY")
    e2 = create_employee(bundle["program"]["id"], badge_number="B002",
                         shift_pattern="DAY")
    e3 = create_employee(bundle["program"]["id"], badge_number="B003",
                         shift_pattern="NIGHT")

    p1 = apply_for_permit(e1, bundle["lot"], vehicle_plate="P001")
    assert p1["status"] == "OFFERED"
    set_logical_clock("2026-08-01T09:01:00Z")
    p2 = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")
    assert p2["status"] == "WAITLISTED"
    set_logical_clock("2026-08-01T09:02:00Z")
    p3 = apply_for_permit(e3, bundle["lot"], vehicle_plate="P003")
    assert p3["status"] == "WAITLISTED"

    set_logical_clock("2026-08-01T09:05:00Z")
    validate_success(
        api.permit_event(p1["id"], {"event_type": "DECLINE"},
                         make_employee_headers(e1["id"])),
        200,
    )

    pr3 = validate_success(api.get_permit(p3["id"], ADMIN), 200)
    pr2 = validate_success(api.get_permit(p2["id"], ADMIN), 200)
    assert pr3["status"] == "OFFERED", "NIGHT class beats DAY despite later arrival"
    assert_instant_equals(pr3["offered_at"], "2026-08-01T09:05:00Z",
                          label="promoted offered_at")
    assert_instant_equals(pr3["offer_expires_at"], "2026-08-04T09:05:00Z",
                          label="promoted offer_expires_at")
    assert pr2["status"] == "WAITLISTED", "the single freed slot went to the NIGHT entry"

    lot = get_lot(bundle["lot"]["id"])
    assert lot["reserved_slots"] == 1


def test_offer_expiry_sweep_promotes_waitlist(api):
    """PRD section 3.3: "Expiry is the system's path: at the ops checkpoint, any
    offer whose `offer_expires_at` is strictly earlier than the current logical
    time moves `OFFERED` to `EXPIRED`, releases the reservation, and the promotion
    pass continues within the same checkpoint."
    PRD section 3.3: "An offer stamps `offered_at` with the current logical time,
    sets `offer_expires_at` to `offered_at` plus the program's
    `waitlist_offer_ttl_hours`, and raises the lot's derived reservation count by
    one."
    PRD section 3.9: "Seventh, the program's `ops_run_index` increments by one."

    Design: Corner/state_machines/offer_expiry_sweep_promotes_waitlist
    """
    set_logical_clock("2026-08-01T09:00:00Z")
    bundle = setup_program_lot_cycle(lot_overrides={"capacity": 1}, with_cycle=False)
    e1 = create_employee(bundle["program"]["id"], badge_number="B001")
    e2 = create_employee(bundle["program"]["id"], badge_number="B002")
    p1 = apply_for_permit(e1, bundle["lot"], vehicle_plate="P001")
    assert p1["status"] == "OFFERED"
    assert_instant_equals(p1["offer_expires_at"], "2026-08-04T09:00:00Z",
                          label="initial offer_expires_at")
    p2 = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")
    assert p2["status"] == "WAITLISTED"

    set_logical_clock("2026-08-04T09:00:01Z")
    program = validate_success(
        api.run_program_ops(bundle["program"]["id"], ADMIN), 200
    )
    assert program["ops_run_index"] == 1

    pp1 = validate_success(api.get_permit(p1["id"], ADMIN), 200)
    pp2 = validate_success(api.get_permit(p2["id"], ADMIN), 200)
    assert pp1["status"] == "EXPIRED", "offer_expires_at strictly in the past sweeps it"
    assert pp2["status"] == "OFFERED", "the promotion pass continues in the same checkpoint"
    assert_instant_equals(pp2["offer_expires_at"], "2026-08-07T09:00:01Z",
                          label="promoted offer_expires_at anchored to sweep time")


class TestSlotOccupancyConservation:
    """Conserved quantity: ParkingLot.occupied_slots across forward (accept) and
    compensating (revoke) actions."""

    def _setup_two_offers(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_program_lot_cycle(lot_overrides={"capacity": 2})
        e1 = create_employee(bundle["program"]["id"], badge_number="B001")
        e2 = create_employee(bundle["program"]["id"], badge_number="B002")
        p1 = apply_for_permit(e1, bundle["lot"], vehicle_plate="P001")
        p2 = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")
        assert p1["status"] == "OFFERED" and p2["status"] == "OFFERED"
        return bundle, e1, e2, p1, p2

    def test_accept_revoke_returns_occupied_to_baseline(self, api):
        """PRD section 3.2: "`occupied_slots` counts the lot's permits in `ACTIVE`
        status; `reserved_slots` counts the lot's permits in `OFFERED` status whose
        `offer_expires_at` has not yet passed relative to the logical clock —
        expired offers are excluded from the reservation."
        PRD section 3.5: "From `ACTIVE`, revocation applies the same span truncation
        as suspension — the pending fee entry whose span contains the revocation
        date is reversed and reposted through the revocation date, earlier ended
        spans untouched, skipped without an `OPEN` cycle — then releases the
        occupied slot and runs an immediate waitlist promotion pass on the lot."

        Design: Difficulty/compensating_invariant/slot_occupancy_forward_reverse_conservation
        """
        bundle, e1, e2, p1, p2 = self._setup_two_offers(api)
        lot_id = bundle["lot"]["id"]
        assert get_lot(lot_id)["occupied_slots"] == 0

        accept_permit(p1, e1)
        assert get_lot(lot_id)["occupied_slots"] == 1
        accept_permit(p2, e2)
        mid = get_lot(lot_id)
        assert mid["occupied_slots"] == 2
        assert mid["reserved_slots"] == 0, "accepted offers consume reservations"

        validate_success(
            api.permit_event(p1["id"], {"event_type": "REVOKE"}, ADMIN), 200
        )
        assert get_lot(lot_id)["occupied_slots"] == 1
        validate_success(
            api.permit_event(p2["id"], {"event_type": "REVOKE"}, ADMIN), 200
        )
        assert get_lot(lot_id)["occupied_slots"] == 0, (
            "each forward action is exactly undone by its compensating action"
        )

    def test_occupied_matches_active_permit_count_at_each_step(self, api):
        """PRD section 2.10: "Derived figures — a lot's `occupied_slots` and
        `reserved_slots`, an employee's `balance_due_cents` and `standing`, a
        cycle's `total_charges_cents` — are always recomputed from their defining
        source rows rather than stored independently, so they stay correct after
        every direct write and every cascade."

        Design: Difficulty/compensating_invariant/slot_occupancy_forward_reverse_conservation
        """
        bundle, e1, e2, p1, p2 = self._setup_two_offers(api)
        lot_id = bundle["lot"]["id"]

        def check(expected):
            lot = get_lot(lot_id)
            active_rows = permits_of_lot(lot_id, status="ACTIVE")
            assert lot["occupied_slots"] == expected
            assert lot["occupied_slots"] == len(active_rows), (
                "occupied_slots must equal the count of ACTIVE permits on the lot"
            )

        check(0)
        accept_permit(p1, e1)
        check(1)
        accept_permit(p2, e2)
        check(2)
        validate_success(
            api.permit_event(p1["id"], {"event_type": "REVOKE"}, ADMIN), 200
        )
        check(1)
        validate_success(
            api.permit_event(p2["id"], {"event_type": "REVOKE"}, ADMIN), 200
        )
        check(0)
