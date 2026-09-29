"""Role exclusivity, separation of duties and the genuinely shared operations.

Covers the role gate that fires before any id resolves, the two separation
rules that compare recorded user ids rather than roles, and the operations the
document opens to every role.
"""

from test_helpers import (
    assert_clock_stamp,
    BuildStatus,
    CertificationStatus,
    CertificationTestStatus,
    ComplianceDisposition,
    ErrorCode,
    ProgramStatus,
    SpecificationStatus,
    TripStatus,
    add_clause,
    assert_spec_scores,
    assert_unit_dimensions,
    award_unit,
    build_program_payload,
    build_slot_line_payload,
    build_specification_payload,
    confirm_reservation,
    create_active_program,
    create_draft_specification,
    create_plant_bay,
    create_program,
    file_compliance_entry,
    hold_trip,
    make_body_engineer_headers,
    make_program_admin_headers,
    make_purchasing_officer_headers,
    make_third_party_tester_headers,
    make_customer_committee_rep_headers,
    read_trip,
    read_unit,
    reserve_slot,
    schedule_trip,
    setup_awarded_unit,
    submit_certification_test,
    submit_specification_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)


_GHOST_ID = "00000000-0000-4000-8000-000000000000"


def test_every_single_role_operation_refuses_the_other_four_roles(api, admin_headers,
                                                                 purchasing_headers,
                                                                 engineer_headers,
                                                                 tester_headers):
    """Seven cross-role calls are 403, three of them against fabricated ids.

    PRD 2.9: "The acting role is authorised for the endpoint — otherwise
    `ERR_ROLE_NOT_PERMITTED`, 403. Applies to every endpoint."
    PRD 4: "The Authorized Role(s) column lists the roles permitted to call the
    endpoint; `Any` means all five roles".

    Design: Corner/rbac/each_role_is_rejected_from_other_roles_exclusive_operations
    """
    author = make_purchasing_officer_headers("po-author")
    program = create_program(api, name="Matrix program")
    spec = create_draft_specification(api, program["id"], title="Matrix spec")
    clause_one = add_clause(api, spec["id"], clause_code="C1", category="PUMP",
                            requirement_text="1500 gpm single stage pump",
                            mandatory=True, is_restrictive=False)
    clause_two = add_clause(api, spec["id"], clause_code="C2", category="AERIAL",
                            requirement_text="105 ft rear mount aerial",
                            mandatory=False, is_restrictive=False)
    entry = file_compliance_entry(api, spec["id"], clause_one["id"],
                                  response="EXCEPTION",
                                  exception_text="Two stage pump offered")

    validate_error(
        api.create_specification(
            build_specification_payload(program["id"], title="Admin authored spec"),
            admin_headers,
        ),
        ErrorCode.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_program(
            build_program_payload(name="Officer opened program",
                                  agency_name="County Fire Authority"),
            purchasing_headers,
        ),
        ErrorCode.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_compliance_entry(
            {"specification_id": spec["id"], "clause_id": clause_two["id"],
             "response": "COMPLY"},
            purchasing_headers,
        ),
        ErrorCode.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.dispose_compliance_entry(entry["id"], {"disposition": "ACCEPTED"},
                                     engineer_headers),
        ErrorCode.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    validate_error(
        api.start_production(_GHOST_ID, tester_headers),
        ErrorCode.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_certification_test(
            {"unit_order_id": _GHOST_ID, "test_standard": "NFPA_1901"},
            engineer_headers,
        ),
        ErrorCode.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.approve_change_order(_GHOST_ID,
                                 make_customer_committee_rep_headers(program["id"])),
        ErrorCode.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    second_entry = validate_success(
        api.create_compliance_entry(
            {"specification_id": spec["id"], "clause_id": clause_two["id"],
             "response": "COMPLY"},
            engineer_headers,
        ),
        201,
    )
    assert second_entry["clause_id"] == clause_two["id"], second_entry

    disposed = validate_success(
        api.dispose_compliance_entry(entry["id"], {"disposition": "ACCEPTED"}, author)
    )
    assert disposed["disposition"] == ComplianceDisposition.ACCEPTED.value, disposed

    line = validate_success(
        api.create_slot_line(
            build_slot_line_payload(supplier_name="Ladder Works Aerial Devices",
                                    component_type="AERIAL_DEVICE",
                                    total_slot_count=2),
            admin_headers,
        ),
        201,
    )
    assert line["total_slot_count"] == 2, line

    untouched = validate_success(api.get_specification(spec["id"], admin_headers))
    assert untouched["status"] == SpecificationStatus.DRAFT.value, untouched
    assert_spec_scores(untouched, clause_count=2, mandatory_clause_count=1)

    _, spec_meta = validate_paginated(
        api.list_specifications(admin_headers, {"program_id": program["id"]})
    )
    assert spec_meta["total_count"] == 1, spec_meta
    _, program_meta = validate_paginated(api.list_programs(admin_headers))
    assert program_meta["total_count"] == 1, program_meta


def test_neither_the_author_nor_the_weight_engineer_may_sign_their_own_work(api,
                                                                           admin_headers,
                                                                           tester_headers):
    """Both separation rules compare recorded user ids, and a peer clears both.

    PRD 3.4: "the releasing officer's `X-User-ID` must differ from the
    specification's `authored_by_user_id`, or the release is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.9: "that signer must differ from the unit's
    `weight_calc_engineer_user_id` or the call is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 2.11: "The engineer who computed the load distribution may not be the
    signature on the certificate that says the load distribution is compliant."

    Design: Corner/rbac/segregation_of_duties_blocks_self_release_and_self_signed_certification
    """
    author = make_purchasing_officer_headers("po-author")
    peer = make_purchasing_officer_headers("po-releaser")
    program = create_active_program(api, name="SoD program")
    spec = create_draft_specification(api, program["id"], title="SoD spec")
    clause = add_clause(api, spec["id"], clause_code="C1", category="PUMP",
                        requirement_text="1500 gpm single stage pump",
                        mandatory=True, is_restrictive=False)
    file_compliance_entry(api, spec["id"], clause["id"])
    submit_specification_for_review(api, spec["id"])

    validate_error(
        api.release_specification(spec["id"], author),
        ErrorCode.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    blocked = validate_success(api.get_specification(spec["id"], admin_headers))
    assert blocked["status"] == SpecificationStatus.UNDER_REVIEW.value, blocked

    released = validate_success(api.release_specification(spec["id"], peer))
    assert released["status"] == SpecificationStatus.RELEASED.value, released
    assert released["authored_by_user_id"] == "po-author", released
    assert released["released_by_user_id"] == "po-releaser", released

    unit = award_unit(api, program["id"], spec["id"])
    assert unit["weight_calc_engineer_user_id"] == "eng-1", unit
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    pre_trip = schedule_trip(api, unit["id"], bay["id"],
                             trip_type="PRE_CONSTRUCTION",
                             scheduled_start="2026-08-03T08:00:00Z",
                             scheduled_end="2026-08-03T16:00:00Z", committee_size=4)
    hold_trip(api, pre_trip["id"])
    line = validate_success(
        api.create_slot_line(
            build_slot_line_payload(supplier_name="Freightline Custom Chassis",
                                    component_type="CHASSIS", total_slot_count=2),
            admin_headers,
        ),
        201,
    )
    reservation = reserve_slot(api, program["id"], line["id"],
                              unit_order_id=unit["id"])
    confirm_reservation(api, reservation["id"])
    validate_success(api.start_production(unit["id"], admin_headers))
    mid_trip = schedule_trip(api, unit["id"], bay["id"],
                             trip_type="MID_CONSTRUCTION",
                             scheduled_start="2026-09-18T08:00:00Z",
                             scheduled_end="2026-09-18T16:00:00Z", committee_size=4)
    hold_trip(api, mid_trip["id"])
    test = submit_certification_test(api, unit["id"], test_standard="NFPA_1901")

    validate_error(
        api.record_test_result(test["id"],
                              {"result": "PASS", "signed_by_user_id": "eng-1"},
                              tester_headers),
        ErrorCode.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    unsigned = validate_success(api.get_certification_test(test["id"], admin_headers))
    assert unsigned["status"] == CertificationTestStatus.SUBMITTED.value, unsigned
    assert unsigned["signed_by_user_id"] is None, unsigned
    assert_unit_dimensions(read_unit(api, unit["id"]),
                           certification_status=CertificationStatus.IN_TESTING.value)

    signed = validate_success(
        api.record_test_result(test["id"],
                              {"result": "PASS", "signed_by_user_id": "eng-2"},
                              tester_headers)
    )
    assert signed["status"] == CertificationTestStatus.PASSED.value, signed
    assert signed["signed_by_user_id"] == "eng-2", signed
    assert signed["submitted_by_user_id"] == "tester-1", signed
    assert_unit_dimensions(read_unit(api, unit["id"]),
                           build_status=BuildStatus.MID_CON_HELD.value,
                           certification_status=CertificationStatus.CERTIFIED.value)


def test_reads_the_clock_and_the_trip_pair_are_open_to_the_shared_roles(api,
                                                                       admin_headers,
                                                                       committee_headers_for):
    """Five roles list programs, a tester moves the clock, the committee holds a trip.

    PRD 4: "Sets the logical plant clock that every deadline, expiry and window
    rule reads instead of wall-clock time. Moving the clock never itself
    transitions any record."
    PRD 4: "Moves a trip from `SCHEDULED` to the terminal `HELD` state, advancing
    the unit's `build_status` for pre-construction and mid-construction trips".

    Design: Corner/rbac/shared_operations_work_for_every_permitted_role
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Shared program"})
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    first = schedule_trip(api, ctx["unit_id"], bay["id"],
                          trip_type="PRE_CONSTRUCTION",
                          scheduled_start="2026-08-10T08:00:00Z",
                          scheduled_end="2026-08-10T16:00:00Z", committee_size=4)
    second = schedule_trip(api, ctx["unit_id"], bay["id"],
                           trip_type="PRE_CONSTRUCTION",
                           scheduled_start="2026-08-12T08:00:00Z",
                           scheduled_end="2026-08-12T16:00:00Z", committee_size=4)

    readers = (
        make_program_admin_headers(),
        make_purchasing_officer_headers("po-author"),
        make_body_engineer_headers(),
        make_third_party_tester_headers(),
        committee_headers_for(ctx["program_id"]),
    )
    for headers in readers:
        rows, meta = validate_paginated(api.list_programs(headers))
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == ctx["program_id"], rows
        assert rows[0]["status"] == ProgramStatus.ACTIVE.value, rows

    moved = validate_success(
        api.set_clock("2026-08-02T00:00:00Z", make_third_party_tester_headers())
    )
    assert moved["current_utc"] == "2026-08-02T00:00:00Z", moved

    held = validate_success(
        api.hold_inspection_trip(first["id"], committee_headers_for(ctx["program_id"]))
    )
    assert held["status"] == TripStatus.HELD.value, held
    assert_clock_stamp(held["held_at"], "2026-08-02T00:00:00Z")
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value)

    cancelled = validate_success(
        api.cancel_inspection_trip(second["id"], admin_headers)
    )
    assert cancelled["status"] == TripStatus.CANCELLED.value, cancelled
    assert read_trip(api, second["id"])["status"] == TripStatus.CANCELLED.value
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value)

    rows, meta = validate_paginated(
        api.list_inspection_trips(admin_headers,
                                  {"unit_order_id": ctx["unit_id"], "status": "HELD"})
    )
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [first["id"]], rows
