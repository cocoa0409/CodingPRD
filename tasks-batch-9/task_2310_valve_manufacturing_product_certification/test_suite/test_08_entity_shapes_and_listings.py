"""Entity shapes: what a create stores, what a read returns, and what a list reports.

Every primary resource carries the same server-managed property set, opens at the
values its own section declares, and is read back through the standard envelope. A
test record is the one deliberate exception to that property set.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    ComponentStatus,
    ErrorId,
    ModelStatus,
    assert_common_fields,
    assert_created,
    assert_immutable_test_record,
    assert_object_envelope,
    assert_ok,
    factories,
    fixtures,
    make_procurement_specialist_headers,
    make_product_engineer_headers,
    make_quality_manager_headers,
)

NON_EXISTENT_HEAT_LOT_ID = "00000000-0000-4000-8000-000000000000"


# ─── Creating and reading a product-line design ───


def test_01_creating_a_design_returns_the_declared_opening_values(api):
    """A create returns 201 with the design's opening values inside the standard
    object envelope.

    PRD §3.1: "On creation the design opens at `status` `DRAFT` with `spec_revision` 1, an
    empty `qualified_special_services` list, `authored_by_user_id` set from `X-User-ID`,
    `released_at` null and `version` 1." PRD §2.2: "The `api_request_id` is a
    server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/corner_valve_model_create_returns_all_declared_fields
    """
    response = api.create_valve_model(
        factories.valve_model_payload(
            "BV-300-CREATE", "BALL", 300, "CF8M", 100, "METAL", 420.0
        ),
        make_product_engineer_headers("pe-c1"),
    )

    model = assert_object_envelope(response, 201)

    assert model["model_code"] == "BV-300-CREATE"
    assert model["status"] == ModelStatus.DRAFT
    assert model["spec_revision"] == 1
    assert model["qualified_special_services"] == []
    assert model["authored_by_user_id"] == "pe-c1"
    assert model["released_at"] is None
    assert_common_fields(model, expected_version=1)


def test_02_reading_a_design_back_returns_the_stored_row(api):
    """A read reports the same field values the create stored and moves nothing.

    PRD §4: "Every operation that modifies an existing resource, including all action,
    disposition, decision, finding-entry, datasheet-revision and document-append endpoints,
    and every read, returns `200 OK`." PRD §3.1: "On creation the design opens at `status`
    `DRAFT` with `spec_revision` 1, an empty `qualified_special_services` list,
    `authored_by_user_id` set from `X-User-ID`, `released_at` null and `version` 1."

    Design: Corner/entities/corner_valve_model_get_by_id_returns_stored_row
    """
    created = fixtures.create_model(
        api,
        model_code="BV-300-GET",
        valve_type="BALL",
        pressure_class=300,
        body_material_grade="CF8M",
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=420.0,
    )

    model = assert_ok(api.get_valve_model(created["id"], make_quality_manager_headers()))

    assert model["id"] == created["id"]
    assert model["valve_type"] == "BALL"
    assert model["pressure_class"] == 300
    assert float(model["base_break_torque_nm"]) == 420.0
    assert model["body_material_grade"] == "CF8M"
    assert model["seat_type"] == "METAL"
    assert model["status"] == ModelStatus.DRAFT
    assert model["spec_revision"] == 1


def test_03_a_list_page_reports_the_total_count_and_the_has_more_flag(api):
    """Two of three rows come back on the first page, and the envelope says so.

    PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not be
    smaller than 1, and may not be larger than 100." PRD §2.3: "The `meta` object of a list
    response carries `limit`, `offset`, `total_count` and `has_more` alongside the two
    request-identification fields."

    Design: Corner/entities/corner_valve_models_list_paginates_with_total_count_and_has_more
    """
    fixtures.create_model(api, model_code="PG-1", valve_type="BALL", pressure_class=300)
    fixtures.create_model(
        api,
        model_code="PG-2",
        valve_type="BALL",
        pressure_class=300,
        seat_type="SOFT",
        base_break_torque_nm=300.0,
    )
    fixtures.create_model(
        api,
        model_code="PG-3",
        valve_type="GATE",
        pressure_class=150,
        body_material_grade="WCB",
        bore_size_mm=80,
        base_break_torque_nm=250.0,
    )

    response = api.list_valve_models(
        make_quality_manager_headers(), params={"limit": 2, "offset": 0}
    )

    rows, meta = validate_paginated(response)
    assert len(rows) == 2, "A limit of 2 caps the page at two rows"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert response.json()["response_type"] == "array"


def test_04_omitting_the_optional_inputs_applies_the_declared_defaults(api):
    """Each optional input has a declared default, and the server writes it.

    PRD §3.1: "Three inputs are optional: `required_special_services`, a subset of
    `FIRE_SAFE`, `CRYOGENIC` and `FUGITIVE_EMISSION` that the design claims, defaulting to
    the empty list; `repair_kit_stock_qty`, the aftermarket repair-kit units on hand for the
    line, defaulting to 0; and `supersedes_model_id`, naming the released design this one
    replaces, defaulting to null for a brand-new line."

    Design: Corner/entities/corner_valve_model_defaults_applied_when_optionals_omitted
    """
    response = api.create_valve_model(
        factories.valve_model_payload("BV-300-DEF", "BALL", 300, "CF8M", 100, "METAL", 420.0),
        make_product_engineer_headers(),
    )

    model = assert_created(response)

    assert model["required_special_services"] == []
    assert model["repair_kit_stock_qty"] == 0
    assert model["supersedes_model_id"] is None
    assert model["qualified_special_services"] == []


def test_05_client_supplied_server_managed_fields_are_not_honoured(api):
    """`status`, `spec_revision` and `version` are the server's to write, so a client that
    sends them still gets the declared opening values.

    PRD §2.4: "Every primary resource — product-line designs, foundries, foundry
    qualifications, heat lots, components, valve units, actuator packages, monogram licenses
    and engineered orders — carries a common set of server-managed properties:" PRD §3.1: "On
    creation the design opens at `status` `DRAFT` with `spec_revision` 1, an empty
    `qualified_special_services` list, `authored_by_user_id` set from `X-User-ID`,
    `released_at` null and `version` 1."

    Design: Corner/entities/corner_valve_model_system_fields_input_ignored
    """
    payload = factories.valve_model_payload(
        "BV-300-SYS", "BALL", 300, "CF8M", 100, "METAL", 420.0
    )
    payload["status"] = "RELEASED"
    payload["spec_revision"] = 9
    payload["version"] = 7

    model = assert_created(api.create_valve_model(payload, make_product_engineer_headers()))

    assert model["status"] == ModelStatus.DRAFT, "The client cannot release a design on create"
    assert model["spec_revision"] == 1
    assert model["version"] == 1


# ─── Request shape and referential existence ───


def test_06_a_heat_lot_missing_its_material_grade_is_refused(api):
    """A required input with no declared default may not be omitted, and nothing is stored.

    PRD §2.10: "Every input field with no declared default is present, types match, enum
    values are members of their declared sets, and array-valued fields contain no duplicates
    and no unknown members — otherwise `ERR_INVALID_REQUEST`." PRD §3.2: "A freshly registered
    foundry starts with `total_lot_count` 0, `rejected_lot_count` 0,
    `revoked_qualification_count` 0, a `quality_index` of 100.00 and a `status` of `ACTIVE`."

    Design: Corner/entities/corner_heat_lot_create_missing_material_grade_rejected
    """
    foundry = fixtures.create_foundry(
        api, foundry_code="FDY-C1", name="Corner Shape Castings", country_code="IN"
    )

    response = api.create_heat_lot(
        {
            "foundry_id": foundry["id"],
            "heat_number": "H-C101",
            "process": "CASTING",
            "qty_received_kg": 500.000,
            "mtr_document_ref": "MTR-C101",
            "carbon_equivalent_pct": 0.35,
            "impact_energy_j": 40,
        },
        make_procurement_specialist_headers(),
    )

    validate_error(response, ErrorId.INVALID_REQUEST, 400)
    unchanged = fixtures.read_foundry(api, foundry["id"])
    assert unchanged["total_lot_count"] == 0, "The refused declaration stored no lot"


def test_07_drawing_a_component_from_an_unknown_heat_lot_is_a_not_found(api):
    """The parent lot is resolved before any mass or qualification rule runs.

    PRD §2.10: "the heat lot referenced by the path or by `heat_lot_id`
    (`ERR_HEAT_LOT_NOT_FOUND`)" PRD §2.9: "The same left-to-right precedence applies to
    identifiers supplied in a request body: a creation referencing several parents resolves
    them in the order the existence rules are ranked in §2.10 and reports the first miss."

    Design: Corner/entities/corner_component_create_with_unknown_heat_lot_returns_not_found
    """
    model = fixtures.create_model(api, model_code="BV-300-NOLOT")

    response = api.create_component(
        factories.component_payload(NON_EXISTENT_HEAT_LOT_ID, model["id"], "BODY", 100.0),
        make_procurement_specialist_headers(),
    )

    validate_error(response, ErrorId.HEAT_LOT_NOT_FOUND, 404)


def test_08_a_body_cut_for_another_design_cannot_open_this_unit(api):
    """A component's `target_model_id` is part of the traceability contract, so a body cut
    for design B is not available to a unit of design A.

    PRD §3.3: "The named component must be in `CREATED` or `ISSUED_TO_MACHINING`, must not
    already be referenced by another unit, must be of `component_type` `BODY`, and must carry
    a `target_model_id` equal to the unit's `model_id`; any of those four failures is
    `ERR_COMPONENT_NOT_AVAILABLE`."

    Design: Corner/entities/corner_valve_unit_cannot_consume_component_of_another_model
    """
    qualified = fixtures.create_qualified_foundry(
        api, foundry_code="FDY-C2", name="Corner Cross Castings", country_code="IN"
    )
    lot = fixtures.create_released_lot(
        api,
        qualified["foundry"]["id"],
        heat_number="H-C201",
        mtr_document_ref="MTR-C201",
        qty_received_kg=500.000,
    )
    model_a = fixtures.create_model(api, model_code="BV-300-A")
    fixtures.submit_model_for_review(api, model_a["id"])
    model_b = fixtures.create_model(api, model_code="BV-300-B")
    component = fixtures.draw_component(api, lot["id"], model_b["id"], net_weight_kg=120.500)
    lic = fixtures.apply_for_license(
        api, license_code="MON-C2", facility_code="FAC-1", scope_valve_types=["BALL"]
    )

    response = api.create_valve_unit(
        factories.valve_unit_payload(
            model_a["id"], component["id"], lic["id"], "SN-C2-1"
        ),
        make_product_engineer_headers(),
    )

    validate_error(response, ErrorId.COMPONENT_NOT_AVAILABLE, 409)
    unchanged = fixtures.read_component(api, component["id"])
    assert unchanged["status"] == ComponentStatus.CREATED
    assert unchanged["target_model_id"] == model_b["id"]


# ─── The one entity outside the common property set ───


def test_09_a_test_record_carries_neither_updated_at_nor_version(api):
    """The written record exposes its append-time payload and the computed envelope, and
    none of the mutable bookkeeping the other resources carry.

    PRD §2.4: "Test records are the one exception. A `TestRecord` is immutable once written:
    it carries `id` and `created_at` only, and has neither an `updated_at` field nor a
    `version` field." PRD §3.4: "The server writes `performed_by_user_id` from `X-User-ID` —
    the field that later blocks the same person from certifying the unit — and stores the two
    computed envelope figures, `required_pressure_bar` and `required_hold_seconds`, on the
    record itself."

    Design: Corner/entities/corner_test_record_is_immutable_and_exposes_no_version
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C3",
        foundry_name="Corner Record Castings",
        heat_number="H-C301",
        mtr_document_ref="MTR-C301",
        model_code="BV-300-REC",
        license_code="MON-C3",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C3-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-c3")
    fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code="BENCH-C1",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
        technician_user_id="tech-c3",
    )

    rows, _meta = validate_paginated(
        api.list_test_records(
            unit["id"], make_quality_manager_headers(), params={"test_type": "SHELL"}
        )
    )

    assert len(rows) == 1
    record = rows[0]
    assert record["result"] == "PASS"
    assert record["performed_by_user_id"] == "tech-c3"
    # Class 300 is rated 51.1 bar and a shell test reaches 1.5 times that, rounded to 76.7.
    assert float(record["required_pressure_bar"]) == 76.7
    assert record["required_hold_seconds"] == 60
    assert_immutable_test_record(record)
