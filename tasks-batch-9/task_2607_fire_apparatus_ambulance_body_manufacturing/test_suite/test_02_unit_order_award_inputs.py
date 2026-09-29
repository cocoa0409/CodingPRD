"""Reads of unknown ids, the award payload's shape rules, and matrix filing.

Covers the twelve per-entity 404s, the mandatory/typed/ranged inputs of the
award payload, the computed fields a client may not dictate, body-reference
resolution, and what a compliance response records.
"""

from test_helpers import (
    ComplianceDisposition,
    ComplianceResponse,
    ErrorCode,
    UnitType,
    WeightStatus,
    assert_axle_loads,
    assert_spec_scores,
    assert_unit_dimensions,
    assert_unit_money,
    build_unit_order_payload,
    create_draft_specification,
    create_program,
    add_clause,
    make_body_engineer_headers,
    make_purchasing_officer_headers,
    read_program,
    setup_program_with_released_spec,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN_PROBES = (
    ("get_program", "00000000-0000-0000-0000-000000000001",
     ErrorCode.ERR_PROGRAM_NOT_FOUND),
    ("get_specification", "00000000-0000-0000-0000-000000000002",
     ErrorCode.ERR_SPECIFICATION_NOT_FOUND),
    ("get_clause", "00000000-0000-0000-0000-000000000003",
     ErrorCode.ERR_CLAUSE_NOT_FOUND),
    ("get_compliance_entry", "00000000-0000-0000-0000-000000000004",
     ErrorCode.ERR_COMPLIANCE_ENTRY_NOT_FOUND),
    ("get_unit_order", "00000000-0000-0000-0000-000000000005",
     ErrorCode.ERR_UNIT_ORDER_NOT_FOUND),
    ("get_slot_line", "00000000-0000-0000-0000-000000000006",
     ErrorCode.ERR_SLOT_LINE_NOT_FOUND),
    ("get_chassis_reservation", "00000000-0000-0000-0000-000000000007",
     ErrorCode.ERR_RESERVATION_NOT_FOUND),
    ("get_plant_bay", "00000000-0000-0000-0000-000000000008",
     ErrorCode.ERR_PLANT_BAY_NOT_FOUND),
    ("get_inspection_trip", "00000000-0000-0000-0000-000000000009",
     ErrorCode.ERR_INSPECTION_TRIP_NOT_FOUND),
    ("get_change_order", "00000000-0000-0000-0000-00000000000a",
     ErrorCode.ERR_CHANGE_ORDER_NOT_FOUND),
    ("get_certification_test", "00000000-0000-0000-0000-00000000000b",
     ErrorCode.ERR_CERTIFICATION_TEST_NOT_FOUND),
    ("get_warranty_startup", "00000000-0000-0000-0000-00000000000c",
     ErrorCode.ERR_WARRANTY_STARTUP_NOT_FOUND),
)


def test_each_single_resource_read_has_its_own_not_found_identifier(api, admin_headers):
    """Twelve reads of absent rows answer with twelve distinct 404 identifiers.

    PRD 2.9: "Every identifier in the URL path resolves to an existing row,
    validated left to right — otherwise a 404 naming the first unresolved
    identifier".

    Design: Corner/entities/all_entity_reads_return_not_found_for_unknown_uuid
    """
    seen = []
    for method_name, unknown_id, expected in _ADMIN_PROBES:
        response = getattr(api, method_name)(unknown_id, admin_headers)
        validate_error(response, expected, 404)
        body = response.json()
        assert body["response_type"] == "error", body
        assert body["data"]["message"], body
        assert set(body["data"]) <= {"error_id", "message", "details"}, body
        seen.append(body["data"]["error_id"])

    assert len(set(seen)) == 12, seen


def test_award_payload_missing_a_mandatory_input_is_rejected(api):
    """Dropping gvwr, the engineer or the seat count each fails the shape rung.

    PRD 2.9: "Request shape: every required input field is present, every field
    has the correct type, every enumerated field carries a declared member,
    every numeric field falls inside its declared range".
    PRD 2.9: "The first rule that fails determines the response, nothing is
    persisted, and no lower rung is consulted."

    Design: Corner/entities/unit_order_missing_required_fields_rejected
    """
    ctx = setup_program_with_released_spec(
        api, program_overrides={"name": "Metro FD 2024-2029 Apparatus",
                                "max_option_units": 3}
    )
    officer = make_purchasing_officer_headers("po-releaser")
    before = read_program(api, ctx["program_id"])
    full = build_unit_order_payload(ctx["program_id"], ctx["specification_id"])

    for omitted in ("gvwr_kg", "weight_calc_engineer_user_id", "crew_seat_count"):
        payload = {k: v for k, v in full.items() if k != omitted}
        validate_error(
            api.create_unit_order(payload, officer),
            ErrorCode.ERR_INVALID_REQUEST,
            400,
        )

    rows, meta = validate_paginated(
        api.list_unit_orders(officer, {"program_id": ctx["program_id"]})
    )
    assert meta["total_count"] == 0, meta
    assert rows == []

    after = read_program(api, ctx["program_id"])
    assert after["committed_cents"] == 0, after
    assert after["version"] == before["version"], after


def test_client_supplied_computed_award_values_are_discarded(api):
    """The server's own price and weight model wins over the request body.

    PRD 3.5: "`price_cents` is computed at award time under the
    *award-year-locked* pricing rule and then frozen for the life of the unit".
    PRD 3.5: "A successful award lands the unit with `build_status` at
    `SPEC_LOCKED`, `certification_status` at `NOT_SUBMITTED`, `long_lead_status`
    at `NOT_RESERVED`, `spec_drift_flag` at false, `chassis_reservation_id` at
    null, `open_change_order_count` at 0, `change_order_total_cents` at 0 and
    `delivered_at` at null."

    Design: Corner/entities/unit_order_computed_fields_input_ignored
    """
    ctx = setup_program_with_released_spec(
        api, program_overrides={"name": "Metro FD 2024-2029 Apparatus",
                                "max_option_units": 3}
    )
    payload = build_unit_order_payload(
        ctx["program_id"],
        ctx["specification_id"],
        price_cents=1,
        front_axle_load_kg=1,
        rear_axle_load_kg=1,
        gross_weight_kg=1,
        weight_status=WeightStatus.OVER_GVWR.value,
        change_order_total_cents=999,
        open_change_order_count=7,
        build_status="DELIVERED",
    )
    unit = validate_success(
        api.create_unit_order(payload, make_purchasing_officer_headers("po-releaser")),
        201,
    )

    assert_unit_money(unit, price_cents=68_276_000, change_order_total_cents=0,
                      open_change_order_count=0)
    assert_axle_loads(unit, front_kg=5810, rear_kg=10110, gross_kg=15920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert_unit_dimensions(unit, build_status="SPEC_LOCKED",
                           certification_status="NOT_SUBMITTED",
                           long_lead_status="NOT_RESERVED", spec_drift_flag=False)
    assert unit["chassis_reservation_id"] is None, unit
    assert unit["delivered_at"] is None, unit

    program = read_program(api, ctx["program_id"])
    assert program["committed_cents"] == 68_276_000, program


def test_award_enum_and_range_edges_are_enforced_not_coerced(api):
    """Three out-of-domain payloads fail; the payload sitting on both bounds passes.

    PRD 3.5: "a `gvwr_kg` between 4,000 and 40,000 giving the chassis gross
    vehicle weight rating in kilograms".
    PRD 3.5: "Payload capacity is the smaller of a fixed tank-or-module cap and
    a percentage of the chassis rating, where the percentage leg is truncated
    downwards to a whole kilogram."

    Design: Corner/entities/unit_order_enum_and_range_constraints_rejected
    """
    ctx = setup_program_with_released_spec(
        api,
        program_overrides={"name": "Constraint program", "max_option_units": 3},
        clauses=[{
            "clause_code": "C1",
            "category": "PATIENT_COMPARTMENT",
            "requirement_text": "Type I module",
            "mandatory": True,
            "is_restrictive": False,
        }],
    )
    officer = make_purchasing_officer_headers("po-releaser")

    def award(**overrides):
        return api.create_unit_order(
            build_unit_order_payload(
                ctx["program_id"], ctx["specification_id"], **overrides
            ),
            officer,
        )

    validate_error(award(unit_type="TANKER"), ErrorCode.ERR_INVALID_REQUEST, 400)
    validate_error(award(crew_seat_count=9), ErrorCode.ERR_INVALID_REQUEST, 400)
    validate_error(
        award(unit_type=UnitType.AMBULANCE.value, gvwr_kg=3999,
              front_axle_rating_kg=2600, rear_axle_rating_kg=3800,
              base_curb_front_kg=2100, base_curb_rear_kg=3080, crew_seat_count=2),
        ErrorCode.ERR_INVALID_REQUEST,
        400,
    )

    edge = validate_success(
        award(unit_type=UnitType.AMBULANCE.value, gvwr_kg=4000,
              front_axle_rating_kg=2000, rear_axle_rating_kg=2600,
              base_curb_front_kg=1000, base_curb_rear_kg=1400, crew_seat_count=8),
        201,
    )
    assert_axle_loads(edge, front_kg=1360, rear_kg=2480, gross_kg=3840,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)

    _, meta = validate_paginated(
        api.list_unit_orders(officer, {"program_id": ctx["program_id"]})
    )
    assert meta["total_count"] == 1, meta


def test_award_body_references_resolve_before_any_state_rule(api):
    """An unknown program, specification or clause in the body is its own 404.

    PRD 2.9: "Every reference supplied in the request body resolves to an
    existing row — `program_id`, `specification_id`, `supersedes_spec_id`,
    `clause_id`, `unit_order_id`, `slot_line_id`, `plant_bay_id` and
    `inspection_trip_id`".

    Design: Corner/entities/unit_order_foreign_keys_validated_not_found
    """
    ctx = setup_program_with_released_spec(
        api, program_overrides={"name": "FK program"}
    )
    officer = make_purchasing_officer_headers("po-releaser")

    validate_error(
        api.create_unit_order(
            build_unit_order_payload(
                "00000000-0000-0000-0000-0000000000ff", ctx["specification_id"]
            ),
            officer,
        ),
        ErrorCode.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_unit_order(
            build_unit_order_payload(
                ctx["program_id"], "00000000-0000-0000-0000-0000000000fe"
            ),
            officer,
        ),
        ErrorCode.ERR_SPECIFICATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_compliance_entry(
            {
                "specification_id": ctx["specification_id"],
                "clause_id": "00000000-0000-0000-0000-0000000000fd",
                "response": ComplianceResponse.COMPLY.value,
            },
            make_body_engineer_headers(),
        ),
        ErrorCode.ERR_CLAUSE_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(api.list_unit_orders(officer))
    assert meta["total_count"] == 0, meta

    spec = validate_success(
        api.get_specification(ctx["specification_id"], officer)
    )
    assert_spec_scores(spec, strict=100.00)


def test_a_compliance_response_records_its_engineer_and_stays_pending(api):
    """The response pins the acting engineer and a second one on the clause is 409.

    PRD 3.3: "The entry lands with `disposition` at `PENDING`,
    `disposition_note` at null and `responded_by_user_id` pinned to the
    engineer's `X-User-ID`."
    PRD 3.3: "At most one entry may exist for a given specification-and-clause
    pair, and the clause must actually belong to that specification; either
    violation is refused with `ERR_DUPLICATE_COMPLIANCE_ENTRY`."

    Design: Corner/entities/compliance_entry_creation_records_responder_and_pending_disposition
    """
    program = create_program(api, name="Matrix program")
    spec = create_draft_specification(api, program["id"], title="Matrix spec rev A")
    clause = add_clause(
        api, spec["id"], clause_code="C1", category="AERIAL",
        requirement_text="105 ft rear mount aerial", mandatory=True,
        is_restrictive=False,
    )
    engineer = make_body_engineer_headers("eng-7")

    entry = validate_success(
        api.create_compliance_entry(
            {
                "specification_id": spec["id"],
                "clause_id": clause["id"],
                "response": ComplianceResponse.EXCEPTION.value,
                "exception_text": "Offering 100 ft rear mount",
            },
            engineer,
        ),
        201,
    )
    assert entry["response"] == ComplianceResponse.EXCEPTION.value, entry
    assert entry["exception_text"] == "Offering 100 ft rear mount", entry
    assert entry["disposition"] == ComplianceDisposition.PENDING.value, entry
    assert entry["disposition_note"] is None, entry
    assert entry["responded_by_user_id"] == "eng-7", entry
    assert entry["version"] == 1, entry

    scored = validate_success(api.get_specification(spec["id"], engineer))
    assert_spec_scores(scored, strict=0.00, provisional=100.00)

    validate_error(
        api.create_compliance_entry(
            {
                "specification_id": spec["id"],
                "clause_id": clause["id"],
                "response": ComplianceResponse.COMPLY.value,
            },
            engineer,
        ),
        ErrorCode.ERR_DUPLICATE_COMPLIANCE_ENTRY,
        409,
    )

    _, meta = validate_paginated(
        api.list_compliance_entries(engineer, {"clause_id": clause["id"]})
    )
    assert meta["total_count"] == 1, meta
