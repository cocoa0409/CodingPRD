"""Reservation, trip, certification, change-order and warranty state machines.

Covers the single-shot nature of each resource transition, the two coupling
points between the build and certification dimensions, and the terminal states
that lock a row down.
"""

from test_helpers import (
    BuildStatus,
    CertificationStatus,
    ChangeOrderStatus,
    DEFAULT_CLOCK,
    ErrorCode,
    LongLeadStatus,
    ReservationStatus,
    TripStatus,
    WarrantyStatus,
    WeightStatus,
    assert_axle_loads,
    assert_clock_stamp,
    assert_price_reconciliation,
    assert_slot_occupancy,
    assert_unit_dimensions,
    assert_unit_money,
    assert_warranty_window,
    build_line_item,
    confirm_reservation,
    create_plant_bay,
    create_slot_line,
    hold_trip,
    raise_change_order,
    read_change_order,
    read_program,
    read_reservation,
    read_slot_line,
    read_trip,
    read_unit,
    read_warranty,
    reserve_slot,
    schedule_trip,
    setup_awarded_unit,
    setup_unit_at_stage,
    submit_change_order,
    submit_certification_test,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_confirming_a_hold_needs_a_named_unit_and_happens_once(api, admin_headers):
    """An unassigned hold cannot be confirmed, and neither can a confirmed one twice.

    PRD 3.6: "only a reservation that actually names a unit may be confirmed — a
    speculative hold with a null `unit_order_id` is refused with
    `ERR_RESERVATION_UNASSIGNED`."
    PRD 3.6: "The line's slot counts do not move, because `RESERVED` and
    `CONFIRMED` both occupy a slot".

    Design: Corner/state_machines/reservation_confirm_requires_named_unit_then_locks_out_repeats
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Reservation program"})
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)
    unassigned = reserve_slot(api, ctx["program_id"], line["id"])
    assigned = reserve_slot(
        api, ctx["program_id"], line["id"], unit_order_id=ctx["unit_id"],
        slot_start_date="2026-10-01T00:00:00Z",
        slot_end_date="2026-10-15T00:00:00Z",
    )
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=2, available=0,
                          total=2)

    validate_error(
        api.confirm_chassis_reservation(unassigned["id"], admin_headers),
        ErrorCode.ERR_RESERVATION_UNASSIGNED,
        409,
    )
    still_held = read_reservation(api, unassigned["id"])
    assert still_held["status"] == ReservationStatus.RESERVED.value, still_held
    assert still_held["confirmed_at"] is None, still_held

    confirmed = validate_success(
        api.confirm_chassis_reservation(assigned["id"], admin_headers)
    )
    assert confirmed["status"] == ReservationStatus.CONFIRMED.value, confirmed
    assert_clock_stamp(confirmed["confirmed_at"], DEFAULT_CLOCK)
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           long_lead_status=LongLeadStatus.CONFIRMED.value)
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=2, available=0,
                          total=2)

    validate_error(
        api.confirm_chassis_reservation(assigned["id"], admin_headers),
        ErrorCode.ERR_INVALID_RESERVATION_STATE,
        409,
    )

    released = validate_success(
        api.release_chassis_reservation(assigned["id"], admin_headers)
    )
    assert released["status"] == ReservationStatus.RELEASED.value, released
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=1, available=1,
                          total=2)

    validate_error(
        api.release_chassis_reservation(assigned["id"], admin_headers),
        ErrorCode.ERR_INVALID_RESERVATION_STATE,
        409,
    )


def test_a_trip_is_held_once_and_only_one_trip_per_type_per_unit(api, admin_headers):
    """A held trip refuses a re-hold and a cancel, and blocks its sibling's hold.

    PRD 3.7: "At most one trip of a given `trip_type` may ever be held on a given
    unit; a second attempt is refused with `ERR_TRIP_TYPE_ALREADY_HELD`."
    PRD 3.7: "Only a `SCHEDULED` trip may be held or cancelled; either operation
    against a trip that is already `HELD` or `CANCELLED` is refused with
    `ERR_INVALID_TRIP_STATE`."

    Design: Corner/state_machines/trip_hold_and_cancel_are_single_shot_per_unit_and_trip_type
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Trip program"})
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    first = schedule_trip(api, ctx["unit_id"], bay["id"],
                          trip_type="PRE_CONSTRUCTION", committee_size=4)
    second = schedule_trip(api, ctx["unit_id"], bay["id"],
                           trip_type="PRE_CONSTRUCTION", committee_size=4)

    held = validate_success(api.hold_inspection_trip(first["id"], admin_headers))
    assert held["status"] == TripStatus.HELD.value, held
    assert_clock_stamp(held["held_at"], DEFAULT_CLOCK)
    assert held["version"] == 2, held
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value)

    validate_error(
        api.hold_inspection_trip(first["id"], admin_headers),
        ErrorCode.ERR_INVALID_TRIP_STATE,
        409,
    )
    assert read_trip(api, first["id"])["version"] == 2

    validate_error(
        api.cancel_inspection_trip(first["id"], admin_headers),
        ErrorCode.ERR_INVALID_TRIP_STATE,
        409,
    )

    validate_error(
        api.hold_inspection_trip(second["id"], admin_headers),
        ErrorCode.ERR_TRIP_TYPE_ALREADY_HELD,
        409,
    )
    assert read_trip(api, second["id"])["status"] == TripStatus.SCHEDULED.value

    cancelled = validate_success(
        api.cancel_inspection_trip(second["id"], admin_headers)
    )
    assert cancelled["status"] == TripStatus.CANCELLED.value, cancelled
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value)


def test_a_test_result_is_recorded_exactly_once(api, tester_headers):
    """A contradicting second result cannot undo a passed certificate.

    PRD 3.9: "A `ThirdPartyTester` records the outcome on a test whose `status`
    is `SUBMITTED` — any other test status is refused with
    `ERR_INVALID_TEST_STATE`."
    PRD 3.9: "On a `PASS` the test moves `SUBMITTED` to `PASSED` with `result`
    set to `PASS`, and the unit's `certification_status` moves `IN_TESTING` to
    `CERTIFIED`."

    Design: Corner/state_machines/certification_result_is_recorded_exactly_once_per_test
    """
    ctx = setup_unit_at_stage(api, "MID_CON_HELD",
                              program_overrides={"name": "Test result program"})
    test = submit_certification_test(api, ctx["unit_id"], test_standard="NFPA_1901")

    passed = validate_success(
        api.record_test_result(
            test["id"], {"result": "PASS", "signed_by_user_id": "eng-2"},
            tester_headers,
        )
    )
    assert passed["status"] == "PASSED", passed
    assert passed["result"] == "PASS", passed
    assert passed["signed_by_user_id"] == "eng-2", passed
    assert passed["version"] == 2, passed
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.MID_CON_HELD.value,
                           certification_status=CertificationStatus.CERTIFIED.value)

    validate_error(
        api.record_test_result(
            test["id"], {"result": "FAIL", "signed_by_user_id": "eng-2"},
            tester_headers,
        ),
        ErrorCode.ERR_INVALID_TEST_STATE,
        409,
    )
    unchanged = validate_success(api.get_certification_test(test["id"], tester_headers))
    assert unchanged["result"] == "PASS", unchanged
    assert unchanged["version"] == 2, unchanged
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           certification_status=CertificationStatus.CERTIFIED.value)


def test_rejecting_a_change_order_is_terminal_and_money_free(api, purchasing_headers):
    """Rejection frees the open count without ever touching the ledger.

    PRD 3.8: "This has no price or weight consequence whatsoever, because a
    rejected change order never entered the unit's change-order total in the
    first place; the only effect on the unit is that its
    `open_change_order_count` is rebuilt and therefore drops by one."
    PRD 2.9: "The change order is in the state its transition allows — `DRAFT` to
    submit, `SUBMITTED` to negotiate, `IN_NEGOTIATION` to revise, `SUBMITTED` to
    approve, `SUBMITTED` to reject and `APPROVED` to rescind".

    Design: Corner/state_machines/change_order_rejection_is_terminal_and_frees_the_open_count
    """
    ctx = setup_unit_at_stage(api, "MID_CON_HELD",
                              program_overrides={"name": "Rejection program"})
    change_order = raise_change_order(
        api, ctx["unit_id"], ctx["mid_trip_id"], ctx["program_id"],
        line_items=[build_line_item(description="Extra compartment shelving",
                                    quantity=1, unit_cost_cents=1_000_000,
                                    markup_pct=10.0, is_taxable=False)],
        weight_delta_front_kg=0,
        weight_delta_rear_kg=0,
    )
    submit_change_order(api, change_order["id"], ctx["program_id"])

    assert change_order["price_delta_cents"] == 1_100_000, change_order
    assert_unit_money(read_unit(api, ctx["unit_id"]), open_change_order_count=1)

    rejected = validate_success(
        api.reject_change_order(change_order["id"], purchasing_headers)
    )
    assert rejected["status"] == ChangeOrderStatus.REJECTED.value, rejected
    assert rejected["approved_by_user_id"] is None, rejected

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_money(unit, change_order_total_cents=0, open_change_order_count=0)
    assert_axle_loads(unit, front_kg=5810, rear_kg=10110, gross_kg=15920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert read_program(api, ctx["program_id"])["committed_cents"] == 68_276_000

    for call in (api.negotiate_change_order, api.approve_change_order,
                 api.rescind_change_order):
        validate_error(
            call(change_order["id"], purchasing_headers),
            ErrorCode.ERR_INVALID_CHANGE_ORDER_STATE,
            409,
        )
    assert read_change_order(api, change_order["id"])["status"] == \
        ChangeOrderStatus.REJECTED.value


def test_a_warranty_activates_only_at_sixteen_cumulative_training_hours(api,
                                                                       admin_headers):
    """Delivery defers the start thirty days; reaching 16.0 hours pulls it back.

    PRD 3.9: "its `warranty_start_date` is the `delivery_date` moved thirty whole
    days later, and its `warranty_end_date` is that start date plus
    `warranty_months` whole calendar months".
    PRD 3.9: "Exactly 16.0 cumulative hours activates the warranty and pulls the
    start back to the delivery date; 15.9 does not."

    Design: Corner/state_machines/warranty_activation_requires_sixteen_cumulative_hours
    """
    ctx = setup_unit_at_stage(api, "FINAL_INSPECTED",
                              program_overrides={"name": "Warranty program"})

    delivered = validate_success(
        api.deliver_unit_order(
            ctx["unit_id"],
            {"delivery_date": "2026-10-15T00:00:00Z", "training_hours": 4.0,
             "warranty_months": 24},
            admin_headers,
        )
    )
    assert delivered["build_status"] == BuildStatus.DELIVERED.value, delivered
    assert_clock_stamp(delivered["delivered_at"], DEFAULT_CLOCK)

    rows, _ = validate_paginated(
        api.list_warranty_startups(admin_headers, {"unit_order_id": ctx["unit_id"]})
    )
    assert len(rows) == 1, rows
    warranty = rows[0]
    assert_warranty_window(warranty, status=WarrantyStatus.PENDING_TRAINING.value,
                           training_hours=4.0, start_date="2026-11-14",
                           end_date="2028-11-14")
    assert_price_reconciliation(warranty, final_price_cents=70_068_750,
                                price_variance_cents=1_792_750)

    validate_error(
        api.complete_training(warranty["id"], {"additional_training_hours": 5.0},
                              admin_headers),
        ErrorCode.ERR_TRAINING_HOURS_NOT_MET,
        422,
    )
    still_pending = read_warranty(api, warranty["id"])
    assert_warranty_window(still_pending,
                           status=WarrantyStatus.PENDING_TRAINING.value,
                           training_hours=4.0, start_date="2026-11-14")

    activated = validate_success(
        api.complete_training(warranty["id"], {"additional_training_hours": 12.0},
                              admin_headers)
    )
    assert_warranty_window(activated, status=WarrantyStatus.ACTIVE.value,
                           training_hours=16.0, start_date="2026-10-15",
                           end_date="2028-10-15")

    validate_error(
        api.complete_training(warranty["id"], {"additional_training_hours": 1.0},
                              admin_headers),
        ErrorCode.ERR_INVALID_WARRANTY_STATE,
        409,
    )
    assert float(read_warranty(api, warranty["id"])["training_hours"]) == 16.0
    assert read_unit(api, ctx["unit_id"])["build_status"] == \
        BuildStatus.DELIVERED.value


def test_the_build_and_certification_dimensions_move_independently(api, admin_headers,
                                                                  tester_headers):
    """Three build hops leave certification still; two certification hops leave build.

    PRD 3.9: "The two dimensions advance on entirely different triggers and touch
    each other at exactly two points: final inspection requires the certification
    dimension to read `CERTIFIED`, and a certification reset out of `CERTIFIED`
    drags the build dimension backwards out of `FINAL_INSPECTED`."
    PRD 3.6: "A `CONSUMED` reservation still occupies its slot, so the line's
    `reserved_slot_count` and `available_slot_count` are recomputed on that
    transition and come out unchanged".

    Design: Corner/state_machines/build_and_certification_dimensions_advance_independently
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Parallel program"})
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)

    pre_trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                             trip_type="PRE_CONSTRUCTION", committee_size=4)
    hold_trip(api, pre_trip["id"])
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value,
                           long_lead_status=LongLeadStatus.NOT_RESERVED.value)

    reservation = reserve_slot(api, ctx["program_id"], line["id"],
                              unit_order_id=ctx["unit_id"])
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value,
                           long_lead_status=LongLeadStatus.RESERVED.value)

    confirm_reservation(api, reservation["id"])
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value,
                           long_lead_status=LongLeadStatus.CONFIRMED.value)

    in_production = validate_success(api.start_production(ctx["unit_id"], admin_headers))
    assert_unit_dimensions(in_production,
                           build_status=BuildStatus.IN_PRODUCTION.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value)
    assert read_reservation(api, reservation["id"])["status"] == \
        ReservationStatus.CONSUMED.value
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=1, available=1,
                          total=2)

    mid_trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                             trip_type="MID_CONSTRUCTION",
                             scheduled_start="2026-09-20T08:00:00Z",
                             scheduled_end="2026-09-20T16:00:00Z", committee_size=4)
    hold_trip(api, mid_trip["id"])
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.MID_CON_HELD.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value)

    test = submit_certification_test(api, ctx["unit_id"], test_standard="NFPA_1901")
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.MID_CON_HELD.value,
                           certification_status=CertificationStatus.IN_TESTING.value)

    validate_success(
        api.record_test_result(
            test["id"], {"result": "PASS", "signed_by_user_id": "eng-2"},
            tester_headers,
        )
    )
    final = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(final, build_status=BuildStatus.MID_CON_HELD.value,
                           certification_status=CertificationStatus.CERTIFIED.value,
                           long_lead_status=LongLeadStatus.CONFIRMED.value)
    assert final["weight_status"] == WeightStatus.WITHIN_LIMITS.value, final


def test_the_build_dimension_refuses_out_of_order_and_post_cancel_hops(api,
                                                                      admin_headers):
    """From SPEC_LOCKED only a pre-construction hold or a cancel is legal.

    PRD 2.9 rung 12: "The unit's `build_status` permits the operation —
    `PRE_CON_HELD` to start production, `MID_CON_HELD` for final inspection,
    `FINAL_INSPECTED` to deliver, and either `SPEC_LOCKED` or `PRE_CON_HELD` to
    cancel — otherwise `ERR_INVALID_BUILD_STATE`, 409."
    PRD 2.9 rung 22: "Cross-entity, unit against reservation: the unit's
    `chassis_reservation_id` is not null and that reservation's `status` is
    `CONFIRMED` — otherwise `ERR_CHASSIS_NOT_CONFIRMED`, 409. Applies to production
    start."
    PRD 3.9: "A `ProgramAdmin` may cancel a unit that has not yet entered
    production — `build_status` of `SPEC_LOCKED` or `PRE_CON_HELD`, and nothing
    later — taking it to the terminal `CANCELLED` state."
    PRD 3.9: "The program's `committed_cents` is recomputed with the cancelled unit
    no longer in the input set, so its price and change-order total are decommitted
    from the ledger."

    Design: Corner/state_machines/build_status_rejects_out_of_order_and_post_cancel_transitions
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Build order program"})
    assert_unit_dimensions(ctx["unit"], build_status=BuildStatus.SPEC_LOCKED.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value,
                           long_lead_status=LongLeadStatus.NOT_RESERVED.value)
    assert ctx["unit"]["chassis_reservation_id"] is None, ctx["unit"]

    validate_error(
        api.final_inspection(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_INVALID_BUILD_STATE,
        409,
    )

    validate_error(
        api.deliver_unit_order(
            ctx["unit_id"],
            {"delivery_date": "2026-10-15T00:00:00Z", "training_hours": 16.0,
             "warranty_months": 24},
            admin_headers,
        ),
        ErrorCode.ERR_INVALID_BUILD_STATE,
        409,
    )
    _, meta = validate_paginated(
        api.list_warranty_startups(admin_headers, {"unit_order_id": ctx["unit_id"]})
    )
    assert meta["total_count"] == 0, meta

    # Rung 12 precedes rung 22, so the missing chassis reservation is never reached.
    validate_error(
        api.start_production(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_INVALID_BUILD_STATE,
        409,
    )

    cancelled = validate_success(api.cancel_unit_order(ctx["unit_id"], admin_headers))
    assert cancelled["build_status"] == BuildStatus.CANCELLED.value, cancelled
    assert read_program(api, ctx["program_id"])["committed_cents"] == 0

    validate_error(
        api.cancel_unit_order(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_INVALID_BUILD_STATE,
        409,
    )
    final = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(final, build_status=BuildStatus.CANCELLED.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value,
                           long_lead_status=LongLeadStatus.NOT_RESERVED.value)
