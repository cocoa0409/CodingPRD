"""The logical clock, the per-program sweep, listings and immediate consistency.

Covers the inertness of clock movement, the four ordered phases of the sweep and
its idempotence, filter-and-page composition on the read side, the two catalogue
errors reachable only from the trip and specification gates, and the rule that
every derived field is authoritative the instant its trigger returns.
"""

from test_helpers import (
    BuildStatus,
    ChangeOrderStatus,
    ErrorCode,
    LongLeadStatus,
    ProgramStatus,
    ReservationStatus,
    SpecificationStatus,
    TripStatus,
    WarrantyStatus,
    WeightStatus,
    add_clause,
    assert_axle_loads,
    assert_created_at_precision,
    assert_ids_in_order,
    assert_list_meta,
    assert_program_ledger,
    assert_response_envelope,
    assert_slot_occupancy,
    assert_sweep_report,
    assert_unit_dimensions,
    assert_unit_money,
    assert_updated_at_refreshed,
    assert_warranty_window,
    award_unit,
    build_line_item,
    build_reservation_payload,
    build_unit_order_payload,
    complete_training,
    confirm_reservation,
    create_active_program,
    create_draft_specification,
    create_plant_bay,
    create_program,
    create_released_specification,
    create_slot_line,
    deliver_unit,
    file_compliance_entry,
    fresh_slot_line_version,
    hold_trip,
    make_body_engineer_headers,
    make_customer_committee_rep_headers,
    make_purchasing_officer_headers,
    raise_change_order,
    read_change_order,
    read_program,
    read_reservation,
    read_slot_line,
    read_trip,
    read_unit,
    read_warranty,
    record_test_result,
    reserve_slot,
    run_sweep,
    schedule_trip,
    set_clock,
    submit_certification_test,
    submit_specification_for_review,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_for_unit,
)


THREE_CLAUSES = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
    {"clause_code": "C2", "category": "AERIAL",
     "requirement_text": "105 ft rear mount aerial",
     "mandatory": False, "is_restrictive": False},
    {"clause_code": "C3", "category": "ELECTRICAL",
     "requirement_text": "Multiplex electrical system",
     "mandatory": False, "is_restrictive": False},
]


def test_moving_the_clock_stamps_new_rows_and_transitions_nothing(api, admin_headers,
                                                                 committee_headers_for):
    """A reservation past its expiry instant stays RESERVED until a sweep runs.

    PRD 2.4: "Moving the clock is deliberately inert: it never itself transitions
    anything. A reservation whose expiry instant has passed stays `RESERVED`, and
    a warranty whose end date has passed stays `ACTIVE`, until the program's
    deterministic sweep is run."
    PRD 2.5: "a `created_at`, which is an ISO 8601 UTC timestamp with three
    fractional digits recording when the row was first written."

    Design: Corner/endpoints/logical_clock_endpoint_moves_time_without_transitioning_anything
    """
    before = create_program(api, name="Default clock program")
    assert_created_at_precision(before)

    moved = set_clock(api, "2026-08-05T09:30:00Z", make_body_engineer_headers())
    assert moved["current_utc"] == "2026-08-05T09:30:00Z", moved

    program = create_active_program(api, name="Moved clock program",
                                    agency_name="County Fire Authority")
    assert_created_at_precision(program)
    assert_updated_at_refreshed(program)

    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)
    reservation = validate_success(
        api.create_chassis_reservation(
            build_reservation_payload(program["id"], line["id"], line["version"],
                                      expiry_at="2026-09-02T00:00:00Z"),
            admin_headers,
        ),
        201,
    )
    assert_created_at_precision(reservation)
    assert reservation["status"] == ReservationStatus.RESERVED.value, reservation

    jumped = set_clock(api, "2026-09-10T00:00:00Z",
                       committee_headers_for(program["id"]))
    assert jumped["current_utc"] == "2026-09-10T00:00:00Z", jumped

    stale = read_reservation(api, reservation["id"])
    assert stale["status"] == ReservationStatus.RESERVED.value, stale
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=1, available=1,
                          total=2)


def test_filters_and_pages_compose_without_disturbing_the_total_count(api,
                                                                     admin_headers,
                                                                     engineer_headers,
                                                                     tester_headers):
    """Two pages of three clauses, then a category filter that narrows the count.

    PRD 4: "Lists specification clauses in `created_at` ascending order, filterable
    by specification or category."
    PRD 2.3: "`total_count` counts every row matching the filters before paging is
    applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/filtered_listings_and_computed_reads_agree_across_entities
    """
    program = create_active_program(api, name="Listing program")
    spec = create_released_specification(api, program["id"], clauses=THREE_CLAUSES,
                                        title="Listing spec")
    clause_ids = spec["clause_ids"]
    keeper = award_unit(api, program["id"], spec["specification_id"])
    doomed = award_unit(api, program["id"], spec["specification_id"])
    validate_success(api.cancel_unit_order(doomed["id"], admin_headers))

    first_response = api.list_clauses(engineer_headers,
                                      {"specification_id": spec["specification_id"],
                                       "limit": 2, "offset": 0})
    assert_response_envelope(first_response.json(), "array")
    first_page, first_meta = validate_paginated(first_response)
    assert_list_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)
    assert_ids_in_order(first_page, clause_ids[:2])

    second_page, second_meta = validate_paginated(
        api.list_clauses(engineer_headers,
                         {"specification_id": spec["specification_id"],
                          "limit": 2, "offset": 2})
    )
    assert_list_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)
    assert_ids_in_order(second_page, clause_ids[2:])

    pumps, pump_meta = validate_paginated(
        api.list_clauses(engineer_headers,
                         {"specification_id": spec["specification_id"],
                          "category": "PUMP"})
    )
    assert_list_meta(pump_meta, total_count=1, has_more=False)
    assert_ids_in_order(pumps, [clause_ids[0]])

    cancelled, cancelled_meta = validate_paginated(
        api.list_unit_orders(tester_headers, {"program_id": program["id"],
                                              "build_status": "CANCELLED"})
    )
    assert_list_meta(cancelled_meta, total_count=1, has_more=False)
    assert_ids_in_order(cancelled, [doomed["id"]])

    live, live_meta = validate_paginated(
        api.list_unit_orders(tester_headers, {"program_id": program["id"],
                                              "build_status": "SPEC_LOCKED"})
    )
    assert_list_meta(live_meta, total_count=1, has_more=False)
    assert_ids_in_order(live, [keeper["id"]])

    released, released_meta = validate_paginated(
        api.list_specifications(tester_headers, {"program_id": program["id"],
                                                 "status": "RELEASED"})
    )
    assert_list_meta(released_meta, total_count=1, has_more=False)
    assert released[0]["status"] == SpecificationStatus.RELEASED.value, released

    ledger = validate_success(api.get_program(program["id"], tester_headers))
    assert_program_ledger(ledger, 68_276_000, ProgramStatus.ACTIVE.value, None)
    assert ledger["committed_cents"] == \
        read_unit(api, keeper["id"])["price_cents"], ledger


def test_one_sweep_expires_a_hold_and_activates_a_warranty_then_reports_zeroes(
        api, admin_headers):
    """Four ordered phases, then an identical sweep that changes nothing.

    PRD 3.1: "First, every chassis reservation of that program that is still
    `RESERVED` and whose `expiry_at` is at or before the current logical clock
    moves `RESERVED` to `EXPIRED`, applying exactly the same slot-count and
    long-lead consequences as an operator-driven release."
    PRD 3.1: "Second, every warranty record of the program that is `ACTIVE` and
    whose `warranty_start_date` is at or before the current logical clock drives
    its unit order from `DELIVERED` to `WARRANTY_ACTIVE`."
    PRD 3.6: "only a `RESERVED` hold expires — a `CONFIRMED` hold is a firm
    supplier commitment and the sweep leaves it alone regardless of `expiry_at`."
    PRD 3.6: "when the unit the reservation is tied to starts production, the
    reservation moves from `CONFIRMED` to the terminal `CONSUMED` state" — so the
    hold unit B carried into production is `CONSUMED` by the time the sweep runs,
    and the sweep leaves that one alone too.
    PRD 3.6: "A `CONSUMED` reservation still occupies its slot".

    Design: Corner/endpoints/ops_run_sweep_expires_reservations_activates_warranties_and_is_idempotent
    """
    program = create_active_program(api, name="Sweep program")
    idle = create_program(api, name="Untouched draft program",
                          agency_name="County Fire Authority")
    spec = create_released_specification(api, program["id"],
                                        title="Pumper spec rev A")
    unit_a = award_unit(api, program["id"], spec["specification_id"])
    unit_b = award_unit(api, program["id"], spec["specification_id"])
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=4)

    reservation_a = reserve_slot(api, program["id"], line["id"],
                                unit_order_id=unit_a["id"],
                                expiry_at="2026-09-02T00:00:00Z")
    trip_a = schedule_trip(api, unit_a["id"], bay["id"],
                           trip_type="PRE_CONSTRUCTION",
                           scheduled_start="2026-08-20T08:00:00Z",
                           scheduled_end="2026-08-20T16:00:00Z", committee_size=4)
    reservation_b = reserve_slot(api, program["id"], line["id"],
                                unit_order_id=unit_b["id"],
                                slot_start_date="2026-10-01T00:00:00Z",
                                slot_end_date="2026-10-15T00:00:00Z")
    confirm_reservation(api, reservation_b["id"])
    pre_trip_b = schedule_trip(api, unit_b["id"], bay["id"],
                               trip_type="PRE_CONSTRUCTION",
                               scheduled_start="2026-08-21T08:00:00Z",
                               scheduled_end="2026-08-21T16:00:00Z",
                               committee_size=4)
    hold_trip(api, pre_trip_b["id"])
    validate_success(api.start_production(unit_b["id"], admin_headers))
    mid_trip_b = schedule_trip(api, unit_b["id"], bay["id"],
                               trip_type="MID_CONSTRUCTION",
                               scheduled_start="2026-09-18T08:00:00Z",
                               scheduled_end="2026-09-18T16:00:00Z",
                               committee_size=4)
    hold_trip(api, mid_trip_b["id"])
    test_b = submit_certification_test(api, unit_b["id"],
                                       test_standard="NFPA_1901")
    record_test_result(api, test_b["id"])
    validate_success(api.final_inspection(unit_b["id"], admin_headers))
    deliver_unit(api, unit_b["id"], delivery_date="2026-09-20T00:00:00Z",
                 training_hours=16.0, warranty_months=12)
    warranty = warranty_for_unit(api, unit_b["id"])
    activated = complete_training(api, warranty["id"], additional_training_hours=0.0)
    assert_warranty_window(activated, status=WarrantyStatus.ACTIVE.value,
                           training_hours=16.0, start_date="2026-09-20",
                           end_date="2027-09-20")

    validate_error(
        api.ops_run(idle["id"], admin_headers),
        ErrorCode.ERR_INVALID_PROGRAM_STATE,
        409,
    )

    set_clock(api, "2026-09-25T00:00:00Z")
    first = run_sweep(api, program["id"])
    assert_sweep_report(first, program["id"], expired_reservation_count=1,
                        warranty_activated_count=1, warranty_expired_count=0,
                        committed_cents=136_552_000,
                        program_status=ProgramStatus.ACTIVE.value)

    assert read_reservation(api, reservation_a["id"])["status"] == \
        ReservationStatus.EXPIRED.value
    stranded = read_unit(api, unit_a["id"])
    assert_unit_dimensions(stranded, build_status=BuildStatus.SPEC_LOCKED.value,
                           long_lead_status=LongLeadStatus.AT_RISK.value)
    assert stranded["chassis_reservation_id"] is None, stranded
    assert read_trip(api, trip_a["id"])["status"] == TripStatus.CANCELLED.value

    assert read_unit(api, unit_b["id"])["build_status"] == \
        BuildStatus.WARRANTY_ACTIVE.value
    assert read_reservation(api, reservation_b["id"])["status"] == \
        ReservationStatus.CONSUMED.value
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=1, available=3,
                          total=4)

    second = run_sweep(api, program["id"])
    assert_sweep_report(second, program["id"], expired_reservation_count=0,
                        warranty_activated_count=0, warranty_expired_count=0,
                        committed_cents=136_552_000,
                        program_status=ProgramStatus.ACTIVE.value)

    set_clock(api, "2027-09-21T00:00:00Z")
    third = run_sweep(api, program["id"])
    assert_sweep_report(third, program["id"], expired_reservation_count=0,
                        warranty_activated_count=0, warranty_expired_count=1,
                        committed_cents=136_552_000,
                        program_status=ProgramStatus.ACTIVE.value)
    assert read_warranty(api, warranty["id"])["status"] == \
        WarrantyStatus.EXPIRED.value
    assert read_unit(api, unit_b["id"])["build_status"] == \
        BuildStatus.WARRANTY_ACTIVE.value


def test_a_draft_change_order_waits_for_the_hold_and_an_unreleased_spec_wins_no_award(
        api, admin_headers, engineer_headers):
    """Two catalogue rejections, then the hold that clears the first of them.

    PRD 3.8: "A `CustomerCommitteeRep` submits a `DRAFT` change order, taking it to
    `SUBMITTED`; the cited trip must be `HELD` at that moment, or the submission is
    refused with `ERR_INSPECTION_TRIP_NOT_HELD`."
    PRD 3.5: "The pinned specification must be `RELEASED`, or the award is refused
    with `ERR_SPEC_NOT_RELEASED`."

    Design: Corner/errors/inspection_trip_not_held_and_spec_not_released_are_both_triggerable
    """
    program = create_active_program(api, name="Catalog program")
    committee = make_customer_committee_rep_headers(program["id"])
    released = create_released_specification(api, program["id"],
                                             title="Released spec")
    pending = create_draft_specification(api, program["id"],
                                         title="Still under review spec")
    pending_clause = add_clause(api, pending["id"], clause_code="C1",
                                category="AERIAL",
                                requirement_text="105 ft rear mount aerial",
                                mandatory=True, is_restrictive=False)
    file_compliance_entry(api, pending["id"], pending_clause["id"])
    submit_specification_for_review(api, pending["id"])

    unit = award_unit(api, program["id"], released["specification_id"])
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    trip = schedule_trip(api, unit["id"], bay["id"], trip_type="PRE_CONSTRUCTION",
                         scheduled_start="2026-08-10T08:00:00Z",
                         scheduled_end="2026-08-10T16:00:00Z", committee_size=4)
    change_order = raise_change_order(
        api, unit["id"], trip["id"], program["id"],
        line_items=[build_line_item(description="Compartment lighting",
                                    unit_cost_cents=120_000)],
    )
    assert change_order["status"] == ChangeOrderStatus.DRAFT.value, change_order

    validate_error(
        api.submit_change_order(change_order["id"], committee),
        ErrorCode.ERR_INSPECTION_TRIP_NOT_HELD,
        409,
    )
    assert read_change_order(api, change_order["id"])["status"] == \
        ChangeOrderStatus.DRAFT.value
    assert read_trip(api, trip["id"])["status"] == TripStatus.SCHEDULED.value

    validate_error(
        api.create_unit_order(
            build_unit_order_payload(program["id"], pending["id"],
                                     unit_type="AERIAL"),
            make_purchasing_officer_headers("po-releaser"),
        ),
        ErrorCode.ERR_SPEC_NOT_RELEASED,
        409,
    )
    assert_program_ledger(read_program(api, program["id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)
    assert_unit_money(read_unit(api, unit["id"]), change_order_total_cents=0,
                      open_change_order_count=1)

    held = hold_trip(api, trip["id"])
    assert held["status"] == TripStatus.HELD.value, held
    submitted = validate_success(api.submit_change_order(change_order["id"],
                                                         committee))
    assert submitted["status"] == ChangeOrderStatus.SUBMITTED.value, submitted
    assert_unit_money(read_unit(api, unit["id"]), change_order_total_cents=0,
                      open_change_order_count=1)

    rows, meta = validate_paginated(
        api.list_unit_orders(engineer_headers, {"program_id": program["id"]})
    )
    assert_list_meta(meta, total_count=1, has_more=False)
    assert_ids_in_order(rows, [unit["id"]])


def test_the_award_response_itself_carries_the_price_and_the_axle_loads(api,
                                                                       admin_headers,
                                                                       engineer_headers,
                                                                       tester_headers):
    """Every derived field is authoritative the instant its trigger returns.

    PRD 2.8: "This system has no eventual consistency and no background
    reconciliation other than the explicit per-program sweep. Every consequence of a
    write lands inside the same request that caused it, and by the time the response
    is emitted every affected row is already at its final value."
    PRD 2.10: "it is recomputed from the program's unit orders whenever anything
    that could change it happens, and its recomputed value is what gets persisted."
    PRD 3.6: "`reserved_slot_count` is the number of that line's reservations whose
    `status` is `RESERVED`, `CONFIRMED` or `CONSUMED`; `available_slot_count` is
    `total_slot_count` minus `reserved_slot_count`."

    Design: Corner/consistency_model/derived_fields_are_visible_immediately_in_the_same_request
    """
    program = create_active_program(api, name="Immediate program")
    spec = create_released_specification(api, program["id"], title="Immediate spec")
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)

    awarded = validate_success(
        api.create_unit_order(
            build_unit_order_payload(program["id"], spec["specification_id"]),
            make_purchasing_officer_headers("po-releaser"),
        ),
        201,
    )
    assert_unit_money(awarded, price_cents=68_276_000, change_order_total_cents=0,
                      open_change_order_count=0)
    assert_axle_loads(awarded, front_kg=5810, rear_kg=10110, gross_kg=15920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)

    assert_program_ledger(read_program(api, program["id"], engineer_headers),
                          68_276_000, ProgramStatus.ACTIVE.value, None)

    reservation = validate_success(
        api.create_chassis_reservation(
            build_reservation_payload(program["id"], line["id"],
                                      fresh_slot_line_version(api, line["id"]),
                                      unit_order_id=awarded["id"]),
            admin_headers,
        ),
        201,
    )
    assert reservation["status"] == ReservationStatus.RESERVED.value, reservation
    assert_slot_occupancy(read_slot_line(api, line["id"], tester_headers),
                          reserved=1, available=1, total=2)
    assert_unit_dimensions(read_unit(api, awarded["id"]),
                           long_lead_status=LongLeadStatus.RESERVED.value)

    validate_success(api.cancel_unit_order(awarded["id"], admin_headers))
    assert_program_ledger(read_program(api, program["id"], engineer_headers), 0,
                          ProgramStatus.ACTIVE.value, None)
    assert_slot_occupancy(read_slot_line(api, line["id"], tester_headers),
                          reserved=0, available=2, total=2)
    assert read_reservation(api, reservation["id"])["status"] == \
        ReservationStatus.RELEASED.value
