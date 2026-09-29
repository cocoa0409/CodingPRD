"""Referential, temporal and aggregate validation rules.

Covers the certification gates on an ambulance body, clause-code uniqueness
scoped to one specification, the two strict-inequality window rules, the four
cross-parent mismatch rules that must not degrade to 404, the delivery boundary
against the mid-construction trip, and the soft-ceiling recovery path.
"""

from test_helpers import (
    BuildStatus,
    CertificationStatus,
    CertificationTestStatus,
    ErrorCode,
    ProgramStatus,
    ReservationStatus,
    SpecificationStatus,
    SuspensionReason,
    TripStatus,
    WarrantyStatus,
    WeightStatus,
    add_clause,
    assert_axle_loads,
    assert_price_reconciliation,
    assert_program_ledger,
    assert_slot_occupancy,
    assert_spec_scores,
    assert_unit_dimensions,
    assert_unit_money,
    assert_warranty_window,
    award_unit,
    build_certification_test_payload,
    build_change_order_payload,
    build_inspection_trip_payload,
    build_line_item,
    build_reservation_payload,
    build_test_result_payload,
    build_unit_order_payload,
    create_active_program,
    create_draft_specification,
    create_plant_bay,
    create_program,
    create_slot_line,
    file_compliance_entry,
    hold_trip,
    make_customer_committee_rep_headers,
    make_purchasing_officer_headers,
    read_program,
    read_slot_line,
    read_unit,
    schedule_trip,
    setup_awarded_unit,
    setup_program_with_released_spec,
    setup_unit_at_stage,
    soft_ceiling,
    submit_specification_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)


AMBULANCE_UNIT = {
    "unit_type": "AMBULANCE",
    "gvwr_kg": 4000,
    "front_axle_rating_kg": 1800,
    "rear_axle_rating_kg": 2800,
    "base_curb_front_kg": 1000,
    "base_curb_rear_kg": 1400,
    "crew_seat_count": 8,
}


def test_the_missing_mid_construction_hold_outranks_the_wrong_standard(api,
                                                                     admin_headers,
                                                                     tester_headers):
    """A pumper standard on an ambulance is only reported once the trip is held.

    PRD 3.9: "An inspection trip of that unit with `trip_type`
    `MID_CONSTRUCTION` and `status` `HELD` must exist, or the submission is
    refused with `ERR_MID_CON_INSPECTION_NOT_HELD`".
    PRD 3.9: "a `PUMPER` is tested against `NFPA_1901`, an `AERIAL` against
    `NFPA_1911`, and an `AMBULANCE` against either `NFPA_1917` or
    `AMD_STD_003`; any other pairing is refused with
    `ERR_TEST_STANDARD_MISMATCH`."

    Design: Corner/validations/mid_construction_hold_gate_rejects_before_the_standard_match_check
    """
    ctx = setup_unit_at_stage(
        api, "IN_PRODUCTION",
        program_overrides={"name": "Ambulance program",
                           "agency_name": "Metro EMS Authority"},
        clauses=[{"clause_code": "C1", "category": "PATIENT_COMPARTMENT",
                  "requirement_text": "170 inch patient compartment",
                  "mandatory": True, "is_restrictive": False}],
        unit_overrides=dict(AMBULANCE_UNIT),
        bay_overrides={"name": "Bay B", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-03T08:00:00Z",
                            "scheduled_end": "2026-08-03T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Vanmaster Cutaway Chassis",
                             "total_slot_count": 2},
        reservation_overrides={"reserved_price_cents": 12_000_000},
    )
    mid_trip = schedule_trip(api, ctx["unit_id"], ctx["bay_id"],
                             trip_type="MID_CONSTRUCTION",
                             scheduled_start="2026-08-10T08:00:00Z",
                             scheduled_end="2026-08-10T16:00:00Z",
                             committee_size=4)
    assert mid_trip["status"] == TripStatus.SCHEDULED.value, mid_trip

    pumper_body = build_certification_test_payload(ctx["unit_id"],
                                                   test_standard="NFPA_1901")
    validate_error(
        api.create_certification_test(pumper_body, tester_headers),
        ErrorCode.ERR_MID_CON_INSPECTION_NOT_HELD,
        409,
    )

    hold_trip(api, mid_trip["id"])
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.MID_CON_HELD.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value)

    validate_error(
        api.create_certification_test(pumper_body, tester_headers),
        ErrorCode.ERR_TEST_STANDARD_MISMATCH,
        422,
    )

    first = validate_success(
        api.create_certification_test(
            build_certification_test_payload(ctx["unit_id"],
                                             test_standard="AMD_STD_003"),
            tester_headers,
        ),
        201,
    )
    assert first["status"] == CertificationTestStatus.SUBMITTED.value, first
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           certification_status=CertificationStatus.IN_TESTING.value)

    failed = validate_success(
        api.record_test_result(first["id"], build_test_result_payload(result="FAIL"),
                               tester_headers)
    )
    assert failed["status"] == CertificationTestStatus.FAILED.value, failed
    assert_unit_dimensions(
        read_unit(api, ctx["unit_id"]),
        certification_status=CertificationStatus.REJECTED_TESTING.value,
    )

    retest = validate_success(
        api.create_certification_test(
            build_certification_test_payload(ctx["unit_id"],
                                             test_standard="NFPA_1917"),
            tester_headers,
        ),
        201,
    )
    assert retest["status"] == CertificationTestStatus.SUBMITTED.value, retest
    final = validate_success(api.get_unit_order(ctx["unit_id"], admin_headers))
    assert_unit_dimensions(final,
                           certification_status=CertificationStatus.IN_TESTING.value)
    assert_axle_loads(final, front_kg=1360, rear_kg=2480, gross_kg=3840,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)


def test_an_empty_specification_and_a_repeated_clause_code_are_both_refused(api,
                                                                           admin_headers):
    """Uniqueness is scoped to one document, so a sibling reuses the same code.

    PRD 3.2: "Each **clause** carries a `clause_code` of 1 to 24 characters that
    must be unique within its specification (a repeat is refused with
    `ERR_DUPLICATE_CLAUSE_CODE`)".
    PRD 2.9: "`clause_code` is unique within the specification — otherwise
    `ERR_DUPLICATE_CLAUSE_CODE`, 409."

    Design: Corner/validations/empty_specification_and_duplicate_clause_code_rejected
    """
    author = make_purchasing_officer_headers("po-author")
    program = create_program(api, name="Clause program")
    spec_one = create_draft_specification(api, program["id"], title="Spec one")
    spec_two = create_draft_specification(api, program["id"], title="Spec two")

    validate_error(
        api.submit_specification_for_review(spec_one["id"], author),
        ErrorCode.ERR_SPEC_HAS_NO_CLAUSES,
        422,
    )
    empty = validate_success(api.get_specification(spec_one["id"], admin_headers))
    assert empty["status"] == SpecificationStatus.DRAFT.value, empty
    assert empty["version"] == 1, empty

    original = add_clause(api, spec_one["id"], clause_code="C1", category="PUMP",
                          requirement_text="1500 gpm single stage pump",
                          mandatory=True, is_restrictive=False)

    validate_error(
        api.add_clause(
            spec_one["id"],
            {"clause_code": "C1", "category": "AERIAL",
             "requirement_text": "Duplicate code, different content",
             "mandatory": True, "is_restrictive": False},
            author,
        ),
        ErrorCode.ERR_DUPLICATE_CLAUSE_CODE,
        409,
    )
    assert_spec_scores(
        validate_success(api.get_specification(spec_one["id"], admin_headers)),
        clause_count=1, mandatory_clause_count=1,
    )

    twin = validate_success(
        api.add_clause(
            spec_two["id"],
            {"clause_code": "C1", "category": "PUMP",
             "requirement_text": "1500 gpm single stage pump",
             "mandatory": True, "is_restrictive": False},
            author,
        ),
        201,
    )
    assert twin["clause_code"] == "C1", twin
    assert twin["specification_id"] == spec_two["id"], twin
    assert twin["id"] != original["id"], twin

    file_compliance_entry(api, spec_one["id"], original["id"])
    under_review = validate_success(
        api.submit_specification_for_review(spec_one["id"], author)
    )
    assert under_review["status"] == SpecificationStatus.UNDER_REVIEW.value, under_review

    rows, meta = validate_paginated(
        api.list_clauses(admin_headers, {"specification_id": spec_one["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [original["id"]], rows


def test_zero_length_windows_are_refused_and_one_second_windows_are_admitted(api,
                                                                            admin_headers):
    """Both window rules are strict, so equal endpoints fail and a second passes.

    PRD 3.6: "the window must be coherent in itself: `slot_end_date` must be
    strictly later than `slot_start_date`, and `expiry_at` must be strictly later
    than `slot_start_date`; a violation of either is refused with
    `ERR_INVALID_SLOT_WINDOW`."
    PRD 3.7: "`scheduled_end` must be strictly later than `scheduled_start`, or
    the trip is refused with `ERR_INVALID_TRIP_WINDOW`. A newly scheduled trip
    lands in `SCHEDULED` with `held_at` at null."

    Design: Corner/validations/temporal_window_checks_reject_zero_length_and_inverted_ranges
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Window program"})
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)
    line_version = line["version"]

    validate_error(
        api.create_chassis_reservation(
            build_reservation_payload(ctx["program_id"], line["id"], line_version,
                                      slot_end_date="2026-09-01T00:00:00Z"),
            admin_headers,
        ),
        ErrorCode.ERR_INVALID_SLOT_WINDOW,
        422,
    )

    validate_error(
        api.create_chassis_reservation(
            build_reservation_payload(ctx["program_id"], line["id"], line_version,
                                      expiry_at="2026-09-01T00:00:00Z"),
            admin_headers,
        ),
        ErrorCode.ERR_INVALID_SLOT_WINDOW,
        422,
    )

    validate_error(
        api.create_inspection_trip(
            build_inspection_trip_payload(ctx["unit_id"], bay["id"],
                                          scheduled_end="2026-08-10T08:00:00Z"),
            admin_headers,
        ),
        ErrorCode.ERR_INVALID_TRIP_WINDOW,
        422,
    )

    trip = validate_success(
        api.create_inspection_trip(
            build_inspection_trip_payload(ctx["unit_id"], bay["id"],
                                          scheduled_end="2026-08-10T08:00:01Z"),
            admin_headers,
        ),
        201,
    )
    assert trip["status"] == TripStatus.SCHEDULED.value, trip
    assert trip["held_at"] is None, trip

    reservation = validate_success(
        api.create_chassis_reservation(
            build_reservation_payload(ctx["program_id"], line["id"], line_version,
                                      slot_end_date="2026-09-01T00:00:01Z",
                                      expiry_at="2026-09-01T00:00:01Z"),
            admin_headers,
        ),
        201,
    )
    assert reservation["status"] == ReservationStatus.RESERVED.value, reservation
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=1, available=1,
                          total=2)
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.SPEC_LOCKED.value)


def test_four_foreign_parent_references_each_report_a_mismatch_not_a_404(api,
                                                                       admin_headers):
    """Every cited row exists, so each rule reports its own referential failure.

    PRD 3.5: "That specification's `program_id` must equal the `program_id` on the
    request, or the award is refused with `ERR_SPEC_PROGRAM_MISMATCH`."
    PRD 3.4: "that predecessor must itself be `RELEASED` (otherwise
    `ERR_PREDECESSOR_NOT_RELEASED`)".
    PRD 3.6: "When a `unit_order_id` *is* supplied, that unit's `program_id` must
    equal the reservation's `program_id`, or the booking is refused with
    `ERR_RESERVATION_UNIT_MISMATCH`."
    PRD 3.8: "That cited trip must belong to the same unit: if the trip's own
    `unit_order_id` differs from the `unit_order_id` on the request, the write is
    refused with `ERR_TRIP_UNIT_MISMATCH`."

    Design: Corner/validations/cross_parent_mismatch_checks_reject_foreign_children
    """
    author = make_purchasing_officer_headers("po-author")
    releaser = make_purchasing_officer_headers("po-releaser")
    first = create_active_program(api, name="Mismatch program one")
    spec_a = create_draft_specification(api, first["id"], title="P1 spec rev A")
    spec_b = create_draft_specification(api, first["id"], title="P1 spec rev B",
                                        supersedes_spec_id=spec_a["id"])
    clause_b = add_clause(api, spec_b["id"], clause_code="C1", category="PUMP",
                          requirement_text="1500 gpm single stage pump",
                          mandatory=True, is_restrictive=False)
    file_compliance_entry(api, spec_b["id"], clause_b["id"])
    submit_specification_for_review(api, spec_b["id"])

    second = setup_program_with_released_spec(
        api, program_overrides={"name": "Mismatch program two",
                                "agency_name": "County Fire Authority"}
    )
    unit_a = award_unit(api, second["program_id"], second["specification_id"])
    unit_b = award_unit(api, second["program_id"], second["specification_id"])
    unit_b_version = unit_b["version"]
    bay = create_plant_bay(api, name="Bay C", max_concurrent_visitors=10)
    trip_a = schedule_trip(api, unit_a["id"], bay["id"],
                           trip_type="PRE_CONSTRUCTION", committee_size=4)
    hold_trip(api, trip_a["id"])
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=3)

    validate_error(
        api.create_unit_order(
            build_unit_order_payload(first["id"], second["specification_id"]),
            releaser,
        ),
        ErrorCode.ERR_SPEC_PROGRAM_MISMATCH,
        422,
    )
    assert read_program(api, first["id"])["committed_cents"] == 0

    validate_error(
        api.release_specification(spec_b["id"], releaser),
        ErrorCode.ERR_PREDECESSOR_NOT_RELEASED,
        409,
    )
    successor = validate_success(api.get_specification(spec_b["id"], author))
    assert successor["status"] == SpecificationStatus.UNDER_REVIEW.value, successor
    predecessor = validate_success(api.get_specification(spec_a["id"], author))
    assert predecessor["status"] == SpecificationStatus.DRAFT.value, predecessor

    validate_error(
        api.create_chassis_reservation(
            build_reservation_payload(first["id"], line["id"], line["version"],
                                      unit_order_id=unit_a["id"]),
            admin_headers,
        ),
        ErrorCode.ERR_RESERVATION_UNIT_MISMATCH,
        422,
    )
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=0, available=3,
                          total=3)

    validate_error(
        api.create_change_order(
            build_change_order_payload(
                unit_b["id"], trip_a["id"], unit_b_version,
                line_items=[build_line_item(description="Foreign trip line",
                                            quantity=1, unit_cost_cents=100_000,
                                            markup_pct=5.0, is_taxable=False)],
                weight_delta_front_kg=0, weight_delta_rear_kg=0,
            ),
            make_customer_committee_rep_headers(second["program_id"]),
        ),
        ErrorCode.ERR_TRIP_UNIT_MISMATCH,
        422,
    )
    untouched = read_unit(api, unit_b["id"])
    assert_unit_money(untouched, open_change_order_count=0)
    assert untouched["version"] == unit_b_version, untouched


def test_delivery_is_admitted_exactly_on_the_mid_construction_trip_end(api,
                                                                      admin_headers):
    """One second early is refused; the trip's own end instant hands the unit over.

    PRD 3.9: "the `delivery_date` must not precede the `scheduled_end` of that
    unit's `HELD` `MID_CONSTRUCTION` inspection trip, or delivery is refused with
    `ERR_DELIVERY_BEFORE_MID_CON`."
    PRD 3.9: "The number of whole months elapsed is the delivery year minus the
    program's `base_year`, multiplied by twelve, plus the delivery month minus
    one".
    PRD 3.9: "`price_variance_cents` is then `final_price_cents` minus the unit's
    frozen `price_cents`".

    Design: Corner/validations/delivery_before_the_mid_construction_trip_end_rejected
    """
    ctx = setup_unit_at_stage(
        api, "FINAL_INSPECTED",
        program_overrides={"name": "Delivery gate program"},
        pre_trip_overrides={"scheduled_start": "2026-08-03T08:00:00Z",
                            "scheduled_end": "2026-08-03T16:00:00Z"},
        mid_trip_overrides={"scheduled_start": "2026-09-20T08:00:00Z",
                            "scheduled_end": "2026-09-20T16:00:00Z"},
    )

    validate_error(
        api.deliver_unit_order(
            ctx["unit_id"],
            {"delivery_date": "2026-09-19T23:59:59Z", "training_hours": 8.0,
             "warranty_months": 12},
            admin_headers,
        ),
        ErrorCode.ERR_DELIVERY_BEFORE_MID_CON,
        422,
    )
    refused = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(refused, build_status=BuildStatus.FINAL_INSPECTED.value)
    assert refused["delivered_at"] is None, refused
    _, empty_meta = validate_paginated(
        api.list_warranty_startups(admin_headers, {"unit_order_id": ctx["unit_id"]})
    )
    assert empty_meta["total_count"] == 0, empty_meta

    delivered = validate_success(
        api.deliver_unit_order(
            ctx["unit_id"],
            {"delivery_date": "2026-09-20T16:00:00Z", "training_hours": 8.0,
             "warranty_months": 12},
            admin_headers,
        )
    )
    assert delivered["build_status"] == BuildStatus.DELIVERED.value, delivered

    rows, meta = validate_paginated(
        api.list_warranty_startups(admin_headers, {"unit_order_id": ctx["unit_id"]})
    )
    assert meta["total_count"] == 1, meta
    warranty = rows[0]
    assert_warranty_window(warranty, status=WarrantyStatus.PENDING_TRAINING.value,
                           training_hours=8.0, start_date="2026-10-20",
                           end_date="2027-10-20")
    assert_price_reconciliation(warranty, final_price_cents=69_858_334,
                                price_variance_cents=1_582_334)


def test_a_soft_ceiling_suspension_lifts_only_after_a_cancellation_and_a_reactivate(
        api, admin_headers):
    """The award that breaches still succeeds, and recovery takes three deliberate steps.

    PRD 2.10: "Recovery from a soft-ceiling suspension is never automatic.
    Cancelling a unit or rescinding a change order may pull `committed_cents` back
    under the soft ceiling, but the program stays `SUSPENDED` until a
    `ProgramAdmin` explicitly reactivates it".
    PRD 3.1: "the parent may close only when *every* unit order of the program has
    a `build_status` of either `WARRANTY_ACTIVE` or `CANCELLED`. One unit still in
    production blocks the close with `ERR_UNITS_NOT_TERMINAL`."

    Design: Corner/validations/soft_ceiling_suspension_blocks_reactivation_until_a_unit_is_cancelled
    """
    ctx = setup_program_with_released_spec(
        api, program_overrides={"name": "Ceiling program",
                                "contract_ceiling_cents": 140_000_000}
    )
    assert soft_ceiling(140_000_000) == 126_000_000

    unit_a = award_unit(api, ctx["program_id"], ctx["specification_id"])
    assert_unit_money(unit_a, price_cents=68_276_000)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)

    unit_b = award_unit(api, ctx["program_id"], ctx["specification_id"])
    assert_unit_money(unit_b, price_cents=68_276_000)
    breached = read_program(api, ctx["program_id"])
    assert_program_ledger(breached, 136_552_000, ProgramStatus.SUSPENDED.value,
                          SuspensionReason.SOFT_CEILING_BREACH.value)
    assert breached["committed_cents"] <= 140_000_000, breached
    assert breached["committed_cents"] > soft_ceiling(140_000_000), breached

    validate_error(
        api.reactivate_program(ctx["program_id"], admin_headers),
        ErrorCode.ERR_SOFT_CEILING_STILL_BREACHED,
        409,
    )
    validate_error(
        api.close_program(ctx["program_id"], admin_headers),
        ErrorCode.ERR_INVALID_PROGRAM_STATE,
        409,
    )
    assert read_program(api, ctx["program_id"])["status"] == \
        ProgramStatus.SUSPENDED.value

    cancelled_b = validate_success(
        api.cancel_unit_order(unit_b["id"], admin_headers)
    )
    assert cancelled_b["build_status"] == BuildStatus.CANCELLED.value, cancelled_b
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.SUSPENDED.value,
                          SuspensionReason.SOFT_CEILING_BREACH.value)

    reactivated = validate_success(
        api.reactivate_program(ctx["program_id"], admin_headers)
    )
    assert_program_ledger(reactivated, 68_276_000, ProgramStatus.ACTIVE.value, None)

    validate_error(
        api.close_program(ctx["program_id"], admin_headers),
        ErrorCode.ERR_UNITS_NOT_TERMINAL,
        409,
    )
    assert read_unit(api, unit_a["id"])["build_status"] == \
        BuildStatus.SPEC_LOCKED.value

    validate_success(api.cancel_unit_order(unit_a["id"], admin_headers))
    closed = validate_success(api.close_program(ctx["program_id"], admin_headers))
    assert_program_ledger(closed, 0, ProgramStatus.CLOSED.value, None)
