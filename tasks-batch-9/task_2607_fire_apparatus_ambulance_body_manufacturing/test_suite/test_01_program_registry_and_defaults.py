"""Opening apparatus programs, reading them back, and the declared defaults.

Covers the program create/read/list surface, the server-minted audit fields, the
optional inputs that carry defaults, and the two resources that are immutable
once created.
"""

from test_helpers import (
    ProgramStatus,
    assert_audit_fields,
    assert_created_at_precision,
    assert_immutable_record_fields,
    assert_list_meta,
    assert_slot_occupancy,
    assert_spec_scores,
    build_program_payload,
    create_draft_specification,
    create_program,
    is_valid_uuid,
    make_body_engineer_headers,
    make_purchasing_officer_headers,
    make_third_party_tester_headers,
    validate_paginated,
    validate_success,
)


def test_opening_a_program_returns_the_declared_system_defaults(api, admin_headers):
    """A create call supplying only the declared inputs mints every system field.

    PRD 3.1: "A newly opened program lands in `DRAFT` with
    `options_exercised_count` at 0, `committed_cents` at 0 and
    `suspension_reason` at null."
    PRD 2.5: "Every resource the API mints carries an `id`, which is a
    server-generated UUID with no type prefix".

    Design: Corner/entities/program_creation_returns_201_with_system_defaults
    """
    payload = build_program_payload(
        name="Metro FD 2024-2029 Apparatus",
        agency_name="Metro Fire District",
        base_year=2024,
        base_unit_price_cents=62_500_000,
        escalation_index_pct_per_year=4.0,
        max_option_units=3,
        contract_ceiling_cents=400_000_000,
    )
    response = api.create_program(payload, admin_headers)
    program = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert response.json()["meta"]["api_request_id"].startswith("req_")
    assert response.json()["meta"]["api_request_timestamp"]

    assert program["name"] == "Metro FD 2024-2029 Apparatus"
    assert program["agency_name"] == "Metro Fire District"
    assert program["base_year"] == 2024
    assert program["base_unit_price_cents"] == 62_500_000
    assert float(program["escalation_index_pct_per_year"]) == 4.0
    assert program["max_option_units"] == 3
    assert program["contract_ceiling_cents"] == 400_000_000

    assert program["status"] == ProgramStatus.DRAFT.value
    assert program["committed_cents"] == 0
    assert program["options_exercised_count"] == 0
    assert program["suspension_reason"] is None

    assert is_valid_uuid(program["id"])
    assert not program["id"].startswith("prog")
    assert_audit_fields(program, expected_version=1)
    assert_created_at_precision(program)
    assert program["updated_at"] == program["created_at"]


def test_reading_one_program_returns_the_persisted_row_for_every_role(api):
    """The single-resource read is a shared operation and never mutates the row.

    PRD 4: "`Any` means all five roles — `ProgramAdmin`, `PurchasingOfficer`,
    `BodyEngineer`, `ThirdPartyTester` and `CustomerCommitteeRep` — are
    accepted."

    Design: Corner/entities/program_retrieval_returns_stored_row
    """
    program = create_program(api, name="Metro FD 2024-2029 Apparatus")

    engineer_read = validate_success(
        api.get_program(program["id"], make_body_engineer_headers())
    )
    tester_read = validate_success(
        api.get_program(program["id"], make_third_party_tester_headers())
    )

    for row in (engineer_read, tester_read):
        assert row["id"] == program["id"]
        assert row["status"] == ProgramStatus.DRAFT.value
        assert row["committed_cents"] == 0
        assert row["version"] == 1

    assert tester_read["updated_at"] == program["updated_at"]
    assert tester_read["version"] == 1


def test_program_listing_pages_and_filters_in_created_at_order(api, admin_headers):
    """Three programs page two-then-one and the status filter narrows to one.

    PRD 2.3: "it defaults to 10 when omitted, may not be smaller than 1, and
    may not be larger than 100."
    PRD 2.3: "`total_count` counts every row matching the filters before paging
    is applied and `has_more` is true when rows remain beyond the current
    window."

    Design: Corner/entities/program_listing_paginates_with_total_count_and_has_more
    """
    alpha = create_program(api, name="Alpha program", agency_name="Alpha Fire")
    bravo = create_program(api, name="Bravo program", agency_name="Bravo Fire")
    charlie = create_program(api, name="Charlie program", agency_name="Charlie Fire")
    validate_success(api.activate_program(bravo["id"], admin_headers))

    first_page, first_meta = validate_paginated(
        api.list_programs(admin_headers, {"limit": 2, "offset": 0})
    )
    assert_list_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)
    assert [row["id"] for row in first_page] == [alpha["id"], bravo["id"]]

    second_page, second_meta = validate_paginated(
        api.list_programs(admin_headers, {"limit": 2, "offset": 2})
    )
    assert_list_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)
    assert [row["id"] for row in second_page] == [charlie["id"]]

    active_page, active_meta = validate_paginated(
        api.list_programs(admin_headers, {"status": ProgramStatus.ACTIVE.value})
    )
    assert active_meta["total_count"] == 1
    assert [row["id"] for row in active_page] == [bravo["id"]]

    default_page, default_meta = validate_paginated(api.list_programs(admin_headers))
    assert_list_meta(default_meta, total_count=3, has_more=False, limit=10, offset=0)
    assert [row["id"] for row in default_page] == [
        alpha["id"], bravo["id"], charlie["id"]
    ]


def test_program_system_fields_supplied_by_the_client_are_ignored(api, admin_headers):
    """A create body naming id, version and status is admitted with server values.

    PRD 2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`".
    PRD 3.1: "A newly opened program lands in `DRAFT` with
    `options_exercised_count` at 0, `committed_cents` at 0 and
    `suspension_reason` at null."

    Design: Corner/entities/program_system_fields_input_ignored
    """
    payload = build_program_payload(
        name="System field program",
        agency_name="Metro Fire District",
        max_option_units=3,
        id="11111111-1111-1111-1111-111111111111",
        created_at="2001-01-01T00:00:00.000Z",
        updated_at="2001-01-01T00:00:00.000Z",
        version=99,
        status=ProgramStatus.CLOSED.value,
        suspension_reason="MANUAL",
        options_exercised_count=5,
        committed_cents=12_345,
    )
    program = validate_success(api.create_program(payload, admin_headers), 201)

    assert program["id"] != "11111111-1111-1111-1111-111111111111"
    assert_created_at_precision(program)
    assert program["version"] == 1
    assert program["status"] == ProgramStatus.DRAFT.value
    assert program["suspension_reason"] is None
    assert program["options_exercised_count"] == 0
    assert program["committed_cents"] == 0

    reread = validate_success(api.get_program(program["id"], admin_headers))
    assert reread["id"] == program["id"]
    assert reread["created_at"] == program["created_at"]
    assert reread["version"] == 1
    assert reread["status"] == ProgramStatus.DRAFT.value
    assert reread["suspension_reason"] is None
    assert reread["options_exercised_count"] == 0
    assert reread["committed_cents"] == 0


def test_omitted_optional_inputs_take_their_declared_defaults(api, admin_headers):
    """A slot line defaults to a seven-day buffer and a clause to mandatory true.

    PRD 3.6: "optionally a `changeover_buffer_days` between 0 and 30 which
    defaults to 7".
    PRD 3.2: "a `mandatory` flag that defaults to true, and an `is_restrictive`
    flag that defaults to false".
    PRD 3.3: "a clause with no entry at all is non-compliant in both scores."

    Design: Corner/entities/slot_line_and_clause_defaults_applied_when_omitted
    """
    program = create_program(api, name="Defaults program")
    spec = create_draft_specification(api, program["id"], title="Defaults spec")

    line = validate_success(
        api.create_slot_line(
            {
                "supplier_name": "Freightline Custom Chassis",
                "component_type": "CHASSIS",
                "total_slot_count": 3,
            },
            admin_headers,
        ),
        201,
    )
    assert line["changeover_buffer_days"] == 7
    assert_slot_occupancy(line, reserved=0, available=3, total=3)

    clause = validate_success(
        api.add_clause(
            spec["id"],
            {
                "clause_code": "D1",
                "category": "ELECTRICAL",
                "requirement_text": "Load manager required",
            },
            make_purchasing_officer_headers("po-author"),
        ),
        201,
    )
    assert clause["mandatory"] is True
    assert clause["is_restrictive"] is False

    reread = validate_success(api.get_specification(spec["id"], admin_headers))
    assert_spec_scores(
        reread,
        strict=0.00,
        provisional=0.00,
        restrictive_ratio=0.00,
        clause_count=1,
        mandatory_clause_count=1,
    )


def test_bays_and_clauses_carry_no_version_or_updated_at(api, admin_headers):
    """The two immutable resources expose only id and created_at.

    PRD 2.5: "Two resources are immutable once created and therefore carry
    **only** `id` and `created_at` — both `updated_at` and `version` are absent
    from them entirely."

    Design: Corner/entities/immutable_entities_carry_no_version_or_updated_at
    """
    program = create_program(api, name="Immutability program")
    spec = create_draft_specification(api, program["id"], title="Immutability spec")

    bay = validate_success(
        api.create_plant_bay({"name": "Bay Z", "max_concurrent_visitors": 12},
                             admin_headers),
        201,
    )
    clause = validate_success(
        api.add_clause(
            spec["id"],
            {
                "clause_code": "Z1",
                "category": "PAINT",
                "requirement_text": "Two tone paint",
                "mandatory": False,
                "is_restrictive": False,
            },
            make_purchasing_officer_headers("po-author"),
        ),
        201,
    )

    bay_read = validate_success(api.get_plant_bay(bay["id"], admin_headers))
    clause_read = validate_success(api.get_clause(clause["id"], admin_headers))

    assert_immutable_record_fields(bay_read)
    assert set(bay_read) == {"id", "created_at", "name", "max_concurrent_visitors"}
    assert bay_read["name"] == "Bay Z"
    assert bay_read["max_concurrent_visitors"] == 12

    assert_immutable_record_fields(clause_read)
    assert set(clause_read) == {
        "id", "created_at", "specification_id", "clause_code", "category",
        "requirement_text", "mandatory", "is_restrictive",
    }
    assert clause_read["specification_id"] == spec["id"]

    assert_created_at_precision(bay_read)
    assert_created_at_precision(clause_read)
