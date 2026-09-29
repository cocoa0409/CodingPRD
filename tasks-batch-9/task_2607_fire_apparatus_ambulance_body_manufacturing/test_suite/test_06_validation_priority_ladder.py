"""The fixed rule ladder, walked rung by rung.

Each test arranges a request that violates two rungs at once and pins the error
the higher rung owns, then clears that rung and shows the lower one surface on
an otherwise identical call.
"""

from test_helpers import (
    BuildStatus,
    CertificationStatus,
    ChangeOrderStatus,
    ComplianceDisposition,
    ComplianceResponse,
    ErrorCode,
    LongLeadStatus,
    ProgramStatus,
    ReservationStatus,
    TripStatus,
    WeightStatus,
    add_clause,
    assert_program_ledger,
    assert_response_envelope,
    assert_slot_occupancy,
    assert_unit_dimensions,
    assert_unit_money,
    build_change_order_payload,
    build_compliance_entry_payload,
    build_line_item,
    build_reservation_payload,
    confirm_reservation,
    create_draft_specification,
    create_plant_bay,
    create_program,
    create_slot_line,
    fresh_unit_version,
    hold_trip,
    make_customer_committee_rep_headers,
    make_headers_missing_user_id,
    make_headers_with_unknown_role,
    raise_change_order,
    read_certification_test,
    read_change_order,
    read_slot_line,
    read_trip,
    read_unit,
    record_test_result,
    reserve_slot,
    schedule_trip,
    setup_awarded_unit,
    setup_unit_at_stage,
    soft_ceiling,
    submit_certification_test,
    submit_change_order,
    validate_error,
    validate_paginated,
    validate_success,
)

_GHOST_ONE = "00000000-0000-4000-8000-000000000000"
_GHOST_TWO = "00000000-0000-4000-8000-000000000001"
_GHOST_THREE = "00000000-0000-4000-8000-000000000002"


def test_the_identity_ladder_answers_401_then_403_then_404(api, admin_headers,
                                                           purchasing_headers):
    """One fabricated program id yields three different errors by header alone.

    PRD 2.9: "`X-User-Role` and `X-User-ID` are both present and the role is one
    of the five named roles — otherwise `ERR_MISSING_AUTH_HEADERS`, 401."
    PRD 2.9: "The acting role is authorised for the endpoint — otherwise
    `ERR_ROLE_NOT_PERMITTED`, 403. Applies to every endpoint."
    PRD 2.9: "Every identifier in the URL path resolves to an existing row,
    validated left to right — otherwise a 404 naming the first unresolved
    identifier".

    Design: Corner/validations/auth_and_role_gates_rejected_before_existence_is_checked
    """
    program = create_program(api, name="Ladder program")

    headerless = api.activate_program(_GHOST_ONE, {})
    validate_error(headerless, ErrorCode.ERR_MISSING_AUTH_HEADERS, 401)
    assert_response_envelope(headerless.json(), "error")

    validate_error(
        api.activate_program(_GHOST_ONE, make_headers_missing_user_id()),
        ErrorCode.ERR_MISSING_AUTH_HEADERS,
        401,
    )
    validate_error(
        api.activate_program(
            _GHOST_ONE, make_headers_with_unknown_role("mech-1", "FleetMechanic")
        ),
        ErrorCode.ERR_MISSING_AUTH_HEADERS,
        401,
    )

    role_refusal = api.activate_program(_GHOST_ONE, purchasing_headers)
    validate_error(role_refusal, ErrorCode.ERR_ROLE_NOT_PERMITTED, 403)
    assert_response_envelope(role_refusal.json(), "error")

    absent = api.activate_program(_GHOST_ONE, admin_headers)
    validate_error(absent, ErrorCode.ERR_PROGRAM_NOT_FOUND, 404)
    assert_response_envelope(absent.json(), "error")

    accepted = api.activate_program(program["id"], admin_headers)
    activated = validate_success(accepted)
    assert_response_envelope(accepted.json(), "object")
    assert activated["status"] == ProgramStatus.ACTIVE.value, activated
    assert activated["version"] == 2, activated
    assert activated["suspension_reason"] is None, activated


def test_a_malformed_body_is_rejected_before_its_references_resolve(api,
                                                                   engineer_headers):
    """An undeclared enum member beats a fabricated parent id, on writes and lists.

    PRD 2.9: "Request shape: every required input field is present, every field
    has the correct type, every enumerated field carries a declared member".
    PRD 2.9: "and pagination has `limit` between 1 and 100 with `offset` at least
    0 — otherwise `ERR_INVALID_REQUEST`, 400."
    PRD 2.9: "Every reference supplied in the request body resolves to an
    existing row".

    Design: Corner/validations/request_shape_check_rejects_before_foreign_keys_resolve
    """
    program = create_program(api, name="Shape program")
    spec = create_draft_specification(api, program["id"], title="Shape spec")
    clause = add_clause(api, spec["id"], clause_code="C1", category="PUMP",
                        requirement_text="1500 gpm single stage pump",
                        mandatory=True, is_restrictive=False)

    validate_error(
        api.create_compliance_entry(
            build_compliance_entry_payload(_GHOST_ONE, clause["id"], response="MAYBE"),
            engineer_headers,
        ),
        ErrorCode.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_compliance_entry(
            build_compliance_entry_payload(_GHOST_ONE, clause["id"]),
            engineer_headers,
        ),
        ErrorCode.ERR_SPECIFICATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_compliance_entries(engineer_headers, {"limit": 101}),
        ErrorCode.ERR_INVALID_REQUEST,
        400,
    )

    entry = validate_success(
        api.create_compliance_entry(
            build_compliance_entry_payload(spec["id"], clause["id"]),
            engineer_headers,
        ),
        201,
    )
    assert entry["response"] == ComplianceResponse.COMPLY.value, entry
    assert entry["disposition"] == ComplianceDisposition.PENDING.value, entry

    rows, meta = validate_paginated(
        api.list_compliance_entries(engineer_headers,
                                    {"specification_id": spec["id"]})
    )
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [entry["id"]], rows


def test_a_fabricated_parent_is_a_404_even_with_a_live_version_echo(api,
                                                                   admin_headers):
    """Both OCC-guarded writes answer 404, never 412, on an unresolvable parent.

    PRD 2.9: "Every reference supplied in the request body resolves to an
    existing row — `program_id`, `specification_id`, `supersedes_spec_id`,
    `clause_id`, `unit_order_id`, `slot_line_id`, `plant_bay_id` and
    `inspection_trip_id`".
    PRD 2.9: "`expected_unit_order_version` equals the unit order's current
    `version` — otherwise `ERR_STALE_UNIT_ORDER_VERSION`, 412. Applies to
    change-order raising."
    PRD 2.9: "`expected_slot_line_version` equals the supplier slot line's
    current `version` — otherwise `ERR_STALE_SLOT_LINE_VERSION`, 412."

    Design: Corner/validations/existence_checks_reject_before_optimistic_concurrency
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "OCC order program"})
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)
    unit_version = ctx["unit"]["version"]
    line_version = line["version"]
    committee = make_customer_committee_rep_headers(ctx["program_id"])

    validate_error(
        api.create_change_order(
            build_change_order_payload(
                _GHOST_ONE, _GHOST_TWO, unit_version,
                line_items=[build_line_item(description="Ghost line", quantity=1,
                                            unit_cost_cents=100_000, markup_pct=5.0,
                                            is_taxable=False)],
            ),
            committee,
        ),
        ErrorCode.ERR_UNIT_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_chassis_reservation(
            build_reservation_payload(ctx["program_id"], _GHOST_THREE, line_version),
            admin_headers,
        ),
        ErrorCode.ERR_SLOT_LINE_NOT_FOUND,
        404,
    )

    reservation = validate_success(
        api.create_chassis_reservation(
            build_reservation_payload(ctx["program_id"], line["id"], line_version),
            admin_headers,
        ),
        201,
    )
    assert reservation["status"] == ReservationStatus.RESERVED.value, reservation

    booked = read_slot_line(api, line["id"])
    assert_slot_occupancy(booked, reserved=1, available=1, total=2)
    assert booked["version"] == line_version + 1, booked
    assert read_unit(api, ctx["unit_id"])["version"] == unit_version

    _, meta = validate_paginated(api.list_change_orders(admin_headers))
    assert meta["total_count"] == 0, meta


def test_a_foreign_committee_is_out_of_scope_before_any_state_check(api):
    """The impostor rep is 403 where the rightful rep is 409, on two endpoints.

    PRD 2.9: "Committee scope: a `CustomerCommitteeRep`'s `X-User-ID` equals the
    program reached from the target resource — otherwise
    `ERR_COMMITTEE_SCOPE_VIOLATION`, 403. Applies to trip hold, trip cancel,
    change-order raise, change-order submit and change-order revise."
    PRD 2.9: "The change order is in the state its transition allows — `DRAFT` to
    submit, `SUBMITTED` to negotiate, `IN_NEGOTIATION` to revise".
    PRD 2.9: "The inspection trip's `status` is `SCHEDULED` — otherwise
    `ERR_INVALID_TRIP_STATE`, 409. Applies to trip hold and trip cancel."

    Design: Corner/validations/committee_scope_violation_rejected_before_change_order_state
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Scope program one"})
    other = create_program(api, name="Scope program two",
                           agency_name="County Fire Authority")
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                         trip_type="PRE_CONSTRUCTION", committee_size=4)
    hold_trip(api, trip["id"])
    change_order = raise_change_order(
        api, ctx["unit_id"], trip["id"], ctx["program_id"],
        line_items=[build_line_item(description="Extra compartment shelving",
                                    quantity=1, unit_cost_cents=200_000,
                                    markup_pct=10.0, is_taxable=False)],
        weight_delta_front_kg=0,
        weight_delta_rear_kg=0,
    )
    submit_change_order(api, change_order["id"], ctx["program_id"])

    impostor = make_customer_committee_rep_headers(other["id"])
    rightful = make_customer_committee_rep_headers(ctx["program_id"])

    validate_error(
        api.submit_change_order(change_order["id"], impostor),
        ErrorCode.ERR_COMMITTEE_SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api.submit_change_order(change_order["id"], rightful),
        ErrorCode.ERR_INVALID_CHANGE_ORDER_STATE,
        409,
    )
    validate_error(
        api.cancel_inspection_trip(trip["id"], impostor),
        ErrorCode.ERR_COMMITTEE_SCOPE_VIOLATION,
        403,
    )

    surviving = read_change_order(api, change_order["id"])
    assert surviving["status"] == ChangeOrderStatus.SUBMITTED.value, surviving
    assert surviving["revision_count"] == 0, surviving
    assert read_trip(api, trip["id"])["status"] == TripStatus.HELD.value
    assert_unit_money(read_unit(api, ctx["unit_id"]), open_change_order_count=1)


def test_a_stale_unit_version_outranks_the_markup_cap(api, admin_headers):
    """The same over-cap body is 412 on a stale echo and 422 on a fresh one.

    PRD 2.9: "`expected_unit_order_version` equals the unit order's current
    `version` — otherwise `ERR_STALE_UNIT_ORDER_VERSION`, 412."
    PRD 2.9: "Every change-order line item's `markup_pct` is at most 22.0 —
    otherwise `ERR_MARKUP_CAP_EXCEEDED`, 422. Applies to change-order raising and
    to change-order revision."
    PRD 3.8: "Raising it increases the unit's `open_change_order_count` by one and
    increments the unit's `version` — which, note, immediately invalidates any
    other client's cached unit version."

    Design: Corner/validations/stale_version_check_rejects_before_the_markup_cap
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Stale program"})
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                         trip_type="PRE_CONSTRUCTION", committee_size=4)
    hold_trip(api, trip["id"])

    stale_version = fresh_unit_version(api, ctx["unit_id"])
    first = raise_change_order(
        api, ctx["unit_id"], trip["id"], ctx["program_id"], stale_version,
        line_items=[build_line_item(description="Warning light upgrade", quantity=1,
                                    unit_cost_cents=150_000, markup_pct=10.0,
                                    is_taxable=False)],
        weight_delta_front_kg=0,
        weight_delta_rear_kg=0,
    )
    assert first["status"] == ChangeOrderStatus.DRAFT.value, first
    assert first["price_delta_cents"] == 165_000, first

    committee = make_customer_committee_rep_headers(ctx["program_id"])
    over_cap = {
        "line_items": [build_line_item(description="Gold leaf lettering", quantity=1,
                                       unit_cost_cents=400_000, markup_pct=30.0,
                                       is_taxable=True)],
        "weight_delta_front_kg": 0,
        "weight_delta_rear_kg": 0,
    }

    validate_error(
        api.create_change_order(
            build_change_order_payload(ctx["unit_id"], trip["id"], stale_version,
                                       **over_cap),
            committee,
        ),
        ErrorCode.ERR_STALE_UNIT_ORDER_VERSION,
        412,
    )

    refreshed = fresh_unit_version(api, ctx["unit_id"])
    assert refreshed == stale_version + 1

    validate_error(
        api.create_change_order(
            build_change_order_payload(ctx["unit_id"], trip["id"], refreshed,
                                       **over_cap),
            committee,
        ),
        ErrorCode.ERR_MARKUP_CAP_EXCEEDED,
        422,
    )

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_money(unit, change_order_total_cents=0, open_change_order_count=1)
    assert unit["version"] == refreshed, unit

    rows, meta = validate_paginated(
        api.list_change_orders(admin_headers, {"unit_order_id": ctx["unit_id"]})
    )
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [first["id"]], rows


def test_a_suspended_program_outranks_the_missing_chassis_confirmation(api,
                                                                      admin_headers):
    """Production start reports the program first, then the chassis, twice.

    PRD 2.9: "Cross-entity, unit against program: the owning program's `status` is
    `ACTIVE` — otherwise `ERR_PROGRAM_NOT_ACTIVE`, 409. Applies to unit-order
    award and to production start."
    PRD 2.9: "Cross-entity, unit against reservation: the unit's
    `chassis_reservation_id` is not null and that reservation's `status` is
    `CONFIRMED` — otherwise `ERR_CHASSIS_NOT_CONFIRMED`, 409."
    PRD 2.9: "The program's `committed_cents` is at most its soft ceiling before
    it may leave `SUSPENDED`".

    Design: Corner/validations/program_state_check_rejects_before_the_chassis_confirmation_check
    """
    ctx = setup_awarded_unit(api, program_overrides={"name": "Gate order program"})
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                         trip_type="PRE_CONSTRUCTION", committee_size=4)
    hold_trip(api, trip["id"])
    validate_success(api.suspend_program(ctx["program_id"], admin_headers))

    held = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(held, build_status=BuildStatus.PRE_CON_HELD.value,
                           long_lead_status=LongLeadStatus.NOT_RESERVED.value)
    assert held["chassis_reservation_id"] is None, held

    validate_error(
        api.start_production(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_PROGRAM_NOT_ACTIVE,
        409,
    )

    reactivated = validate_success(
        api.reactivate_program(ctx["program_id"], admin_headers)
    )
    assert_program_ledger(reactivated, committed_cents=68_276_000,
                          status=ProgramStatus.ACTIVE.value, suspension_reason=None)
    assert reactivated["committed_cents"] < soft_ceiling(400_000_000)

    validate_error(
        api.start_production(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_CHASSIS_NOT_CONFIRMED,
        409,
    )

    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)
    reservation = reserve_slot(api, ctx["program_id"], line["id"],
                              unit_order_id=ctx["unit_id"])
    assert reservation["status"] == ReservationStatus.RESERVED.value, reservation
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           long_lead_status=LongLeadStatus.RESERVED.value)

    validate_error(
        api.start_production(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_CHASSIS_NOT_CONFIRMED,
        409,
    )

    confirm_reservation(api, reservation["id"])
    in_production = validate_success(
        api.start_production(ctx["unit_id"], admin_headers)
    )
    assert_unit_dimensions(in_production,
                           build_status=BuildStatus.IN_PRODUCTION.value,
                           long_lead_status=LongLeadStatus.CONFIRMED.value)


def test_final_inspection_reports_the_certificate_before_the_open_change_order(
        api, admin_headers, purchasing_headers):
    """An uncertified unit with a draft amendment names the certificate first.

    PRD 2.9: "Safety: the unit's `certification_status` is `CERTIFIED` —
    otherwise `ERR_CERTIFICATION_NOT_PASSED`, 409. Applies to final inspection."
    PRD 2.9: "The unit's `open_change_order_count` is 0, meaning no draft,
    submitted or in-negotiation change order is outstanding against it —
    otherwise `ERR_OPEN_CHANGE_ORDERS`, 409."
    PRD 2.9: "on final inspection the axle-overload check sits *above* the
    certification check, which sits above the open-change-order check".

    Design: Corner/validations/certification_gate_rejects_before_the_open_change_order_gate
    """
    ctx = setup_unit_at_stage(
        api, "MID_CON_HELD",
        program_overrides={"name": "Final gate program"},
        pre_trip_overrides={"scheduled_start": "2026-08-03T08:00:00Z",
                            "scheduled_end": "2026-08-03T16:00:00Z"},
        mid_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
    )
    change_order = raise_change_order(
        api, ctx["unit_id"], ctx["mid_trip_id"], ctx["program_id"],
        line_items=[build_line_item(description="Hose bed cover", quantity=1,
                                    unit_cost_cents=250_000, markup_pct=10.0,
                                    is_taxable=False)],
        weight_delta_front_kg=0,
        weight_delta_rear_kg=0,
    )
    blocked = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(blocked, build_status=BuildStatus.MID_CON_HELD.value,
                           certification_status=CertificationStatus.NOT_SUBMITTED.value)
    assert blocked["weight_status"] == WeightStatus.WITHIN_LIMITS.value, blocked
    assert_unit_money(blocked, open_change_order_count=1)

    validate_error(
        api.final_inspection(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_CERTIFICATION_NOT_PASSED,
        409,
    )

    test = submit_certification_test(api, ctx["unit_id"], test_standard="NFPA_1901")
    passed = record_test_result(api, test["id"])
    assert passed["status"] == "PASSED", passed
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           certification_status=CertificationStatus.CERTIFIED.value)

    validate_error(
        api.final_inspection(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_OPEN_CHANGE_ORDERS,
        409,
    )

    submit_change_order(api, change_order["id"], ctx["program_id"])
    rejected = validate_success(
        api.reject_change_order(change_order["id"], purchasing_headers)
    )
    assert rejected["status"] == ChangeOrderStatus.REJECTED.value, rejected
    assert_unit_money(read_unit(api, ctx["unit_id"]), open_change_order_count=0)

    inspected = validate_success(
        api.final_inspection(ctx["unit_id"], admin_headers)
    )
    assert_unit_dimensions(inspected, build_status=BuildStatus.FINAL_INSPECTED.value,
                           certification_status=CertificationStatus.CERTIFIED.value)
    assert_unit_money(inspected, change_order_total_cents=0,
                      open_change_order_count=0)

    certificate = read_certification_test(api, test["id"])
    assert certificate["status"] == "PASSED", certificate
    assert certificate["result"] == "PASS", certificate
    assert certificate["signed_by_user_id"] == "eng-2", certificate
