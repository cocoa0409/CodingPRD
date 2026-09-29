"""Record shape: envelopes, echoed inputs, declared defaults, derived fields.

These tests read the plant's records the way a client first meets them — one
POST, one GET — and hold the server to the identity, audit-field and default
rules before any workflow is exercised.
"""

import pytest

from test_helpers import (
    BILLING,
    BUYER,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    QE_TESTER,
    QE_TESTER_USER_ID,
    SENTINEL_UUID,
    THHN_12_CU_MARKING,
    assert_append_only_common_fields,
    assert_envelope_meta,
    assert_pagination_meta,
    assert_versioned_common_fields,
    create_catalog_product_payload,
    create_customer_order_payload,
    create_customer_payload,
    create_insulation_compound_payload,
    create_listing_certification_payload,
    create_metal_price_quote_payload,
    create_production_lot_payload,
    create_rod_purchase_lot_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_baseline,
    setup_definitions_and_rod,
    setup_lv_catalog,
    setup_returned_reel,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_settlement_price_creation_answers_an_object_envelope_with_no_version(api):
    """A settlement quote is append-only history, so its creation response
    carries id and created_at and neither of the mutation audit fields.

    PRD 2.4: "Three record types are append-only history and therefore carry
    neither field: a settlement price quote, a cable test row and a reel return
    row each expose only `id` and `created_at`, with no `updated_at` and no
    `version`."

    Design: Corner/entities/metal_price_quote_creation_returns_object_envelope_without_version
    """
    response = api.create_metal_price_quote(
        create_metal_price_quote_payload(
            metal="COPPER", effective_date="2026-07-30",
            settlement_price_usd_per_lb=4.10, source="COMEX",
        ),
        BUYER,
    )
    assert response.status_code == 201, (
        f"Recording a settlement price brings a new resource into existence and "
        f"answers 201, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["response_type"] == "object", (
        f"A single resource is wrapped as an object, got {body['response_type']!r}"
    )
    assert_envelope_meta(body)

    quote = body["data"]
    assert_append_only_common_fields(quote)
    assert quote["metal"] == "COPPER"
    assert quote["effective_date"] == "2026-07-30"
    assert quote["settlement_price_usd_per_lb"] == pytest.approx(4.10, abs=0.005)
    assert quote["source"] == "COMEX"


def test_rod_receipt_echoes_its_inputs_and_opens_the_three_mass_buckets(api):
    """Receiving rod initialises the mass ledger from the arrival weight and
    leaves the committed and scrap buckets empty.

    PRD 3.1: "Receipt initialises the three mass buckets described in §2.8:
    `remaining_lbs` is set to `purchase_weight_lbs`, while `committed_lbs` and
    `scrapped_lbs` both start at 0.00, and `status` starts at `RECEIVED`."

    Design: Corner/entities/rod_purchase_lot_retrieval_echoes_input_and_initialised_ledger
    """
    payload = create_rod_purchase_lot_payload(
        metal="COPPER", supplier_code="SUP-1", rod_diameter_mm=8.0,
        heat_number="H-77Q", purchase_weight_lbs=20000.00,
        purchase_price_usd_per_lb=4.05, pricing_basis="SPOT",
        received_date="2026-07-25",
    )
    created = validate_success(api.create_rod_purchase_lot(payload, BUYER), 201)
    fetched = validate_success(api.get_rod_purchase_lot(created["id"], BUYER), 200)

    assert fetched["id"] == created["id"]
    for field, expected in payload.items():
        actual = fetched[field]
        matches = (
            actual == pytest.approx(expected, abs=0.01)
            if isinstance(expected, float)
            else actual == expected
        )
        assert matches, (
            f"{field} must be echoed as supplied: expected {expected!r}, got {actual!r}"
        )
    assert fetched["remaining_lbs"] == pytest.approx(20000.00, abs=0.01)
    assert fetched["committed_lbs"] == pytest.approx(0.00, abs=0.01)
    assert fetched["scrapped_lbs"] == pytest.approx(0.00, abs=0.01)
    assert fetched["status"] == "RECEIVED"
    assert_versioned_common_fields(fetched)
    assert fetched["version"] == 1, (
        f"version starts at 1 when the record is created, got {fetched['version']}"
    )


def test_settlement_price_series_reads_newest_first_and_narrows_by_metal(api):
    """The price series deviates from the default ordering on purpose, and it
    pages and filters like every other collection.

    PRD 2.3: "The settlement-price collection is ordered by `effective_date`
    descending — newest price first — because it exists to be read as a price
    series."

    Design: Corner/entities/metal_price_quote_listing_paginates_filters_and_orders_newest_first
    """
    for date, price in (("2026-07-28", 3.90), ("2026-07-30", 4.10), ("2026-07-29", 4.00)):
        get_success_data(
            api.create_metal_price_quote(
                create_metal_price_quote_payload(
                    metal="COPPER", effective_date=date,
                    settlement_price_usd_per_lb=price,
                ),
                BUYER,
            )
        )
    get_success_data(
        api.create_metal_price_quote(
            create_metal_price_quote_payload(
                metal="ALUMINUM", effective_date="2026-07-31",
                settlement_price_usd_per_lb=1.20,
            ),
            BUYER,
        )
    )

    rows, meta = validate_paginated(api.list_metal_price_quotes(BUYER))
    assert [row["effective_date"] for row in rows] == [
        "2026-07-31", "2026-07-30", "2026-07-29", "2026-07-28",
    ], "the series must read newest effective date first"
    assert_pagination_meta(meta, expected_total_count=4, expected_limit=10,
                           expected_offset=0, expected_has_more=False)

    copper, copper_meta = validate_paginated(
        api.list_metal_price_quotes(BUYER, {"metal": "COPPER"})
    )
    assert [row["effective_date"] for row in copper] == [
        "2026-07-30", "2026-07-29", "2026-07-28",
    ]
    assert_pagination_meta(copper_meta, expected_total_count=3)

    windowed, _ = validate_paginated(
        api.list_metal_price_quotes(
            BUYER,
            {"metal": "COPPER", "effective_date_from": "2026-07-29",
             "effective_date_to": "2026-07-30"},
        )
    )
    assert [row["effective_date"] for row in windowed] == ["2026-07-30", "2026-07-29"]

    page, page_meta = validate_paginated(
        api.list_metal_price_quotes(BUYER, {"limit": 1, "offset": 1})
    )
    assert [row["effective_date"] for row in page] == ["2026-07-30"], (
        "the second row of the newest-first series is the 2026-07-30 copper quote"
    )
    assert_pagination_meta(page_meta, expected_total_count=4, expected_limit=1,
                           expected_offset=1, expected_has_more=True)


@pytest.mark.parametrize(
    "reader,expected_error_id",
    [
        (lambda a: a.get_rod_purchase_lot(SENTINEL_UUID, BUYER), "ERR_ROD_LOT_NOT_FOUND"),
        (lambda a: a.get_compound(SENTINEL_UUID, ENGINEER), "ERR_COMPOUND_NOT_FOUND"),
        (lambda a: a.get_listing_certification(SENTINEL_UUID, CERT_OFFICER),
         "ERR_CERTIFICATION_NOT_FOUND"),
        (lambda a: a.get_catalog_product(SENTINEL_UUID, ENGINEER), "ERR_PRODUCT_NOT_FOUND"),
        (lambda a: a.get_customer(SENTINEL_UUID, BILLING), "ERR_CUSTOMER_NOT_FOUND"),
        (lambda a: a.get_customer_order(SENTINEL_UUID, BILLING), "ERR_ORDER_NOT_FOUND"),
        (lambda a: a.get_production_lot(SENTINEL_UUID, ENGINEER), "ERR_LOT_NOT_FOUND"),
        (lambda a: a.get_reel(SENTINEL_UUID, CLERK), "ERR_REEL_NOT_FOUND"),
        (lambda a: a.get_shipment(SENTINEL_UUID, CLERK), "ERR_SHIPMENT_NOT_FOUND"),
    ],
)
def test_an_unknown_identifier_reports_the_addressed_entitys_own_not_found_code(
    api, reader, expected_error_id
):
    """Each entity owns a distinct not-found code, so a stray identifier names
    the record type that was missing rather than a generic failure.

    PRD 2.10: "The first unresolvable reference determines which not-found error
    the caller receives: `ERR_ROD_LOT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_REEL_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_COMPOUND_NOT_FOUND` or `ERR_CERTIFICATION_NOT_FOUND` respectively, each
    with HTTP 404."

    Design: Corner/entities/unknown_ids_map_to_entity_specific_error_ids
    """
    validate_error(reader(api), expected_error_id, 404)


@pytest.mark.parametrize(
    "omitted",
    ["product_code", "awg_size", "conductor_metal", "conductor_construction",
     "application_rating", "voltage_class", "temp_rating_c",
     "insulation_thickness_mils", "conductor_lbs_per_kft",
     "insulation_compound_id", "listing_certification_id", "base_target_kft"],
)
def test_a_sku_definition_missing_any_mandatory_field_is_a_shape_error(api, omitted):
    """The SKU recipe has no optional stand-in for its mandatory fields, so
    dropping any one of them is caught at the request-shape rung.

    PRD 2.11: "Request shape: required fields present, types correct, enum
    members recognised, numeric bounds from the field definitions respected, a
    scheduled line window whose end is strictly later than its start, a
    non-empty requested cut list on a cut-to-length order, partial-discharge
    level present on a partial-discharge test, applied test voltage present on a
    high-potential test, and pagination bounds respected —
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/catalog_product_missing_required_inputs_return_invalid_request
    """
    world = setup_lv_catalog(api)
    payload = create_catalog_product_payload(
        world["insulation"]["id"], world["certification"]["id"],
        product_code="THHN-12-CU-2",
    )
    payload.pop(omitted)
    validate_error(api.create_catalog_product(payload, ENGINEER), "ERR_INVALID_REQUEST", 400)


def test_omitted_optional_inputs_take_the_values_the_contract_declares(api):
    """Every optional field has a stated default, and a caller that stays silent
    gets exactly that value rather than a null.

    PRD 3.2: "Two optional characteristics round out the formulation:
    `wet_rated` states whether the compound is qualified for wet locations and
    defaults to false, and `filler_pct` gives the mineral filler loading as a
    percentage, defaulting to 0 and constrained to at least 0 and at most 40."

    Design: Corner/entities/omitted_optional_inputs_receive_declared_defaults
    """
    quote_payload = create_metal_price_quote_payload()
    quote_payload.pop("source")
    quote = validate_success(api.create_metal_price_quote(quote_payload, BUYER), 201)
    assert quote["source"] == "COMEX", "`source` defaults to COMEX when omitted"

    compound_payload = create_insulation_compound_payload()
    compound_payload.pop("wet_rated")
    compound_payload.pop("filler_pct")
    compound = validate_success(api.create_compound(compound_payload, ENGINEER), 201)
    assert compound["wet_rated"] is False, "`wet_rated` defaults to false"
    assert compound["filler_pct"] == pytest.approx(0, abs=0.01), "`filler_pct` defaults to 0"
    assert compound["status"] == "DRAFT"
    assert compound["qualification_date"] is None
    assert compound["suspension_reason"] is None
    get_success_data(api.qualify_compound(compound["id"], ENGINEER))

    cert_payload = create_listing_certification_payload()
    cert_payload.pop("inspection_interval_days")
    cert = validate_success(
        api.create_listing_certification(cert_payload, CERT_OFFICER), 201
    )
    assert cert["inspection_interval_days"] == 90, (
        "the follow-up inspection interval defaults to 90 days"
    )
    get_success_data(
        api.create_factory_inspection(
            cert["id"],
            {"inspection_date": "2026-06-05", "inspector_code": "INS-7",
             "findings_count": 0, "outcome": "PASS"},
            CERT_OFFICER,
        )
    )

    product = validate_success(
        api.create_catalog_product(
            create_catalog_product_payload(compound["id"], cert["id"]), ENGINEER
        ),
        201,
    )
    assert product["min_wall_pct"] == pytest.approx(90, abs=0.01), "`min_wall_pct` defaults to 90"
    assert product["concentricity_min_pct"] == pytest.approx(85, abs=0.01), (
        "`concentricity_min_pct` defaults to 85"
    )
    assert product["demand_index"] == pytest.approx(1.0, abs=0.0001), (
        "`demand_index` defaults to 1.0"
    )
    assert product["jacket_compound_id"] is None, "`jacket_compound_id` defaults to null"
    assert product["volatility_index"] == pytest.approx(0.0, abs=0.00005)
    assert product["target_inventory_kft"] == pytest.approx(
        product["base_target_kft"], abs=0.05
    )
    get_success_data(api.release_catalog_product(product["id"], ENGINEER))

    customer_payload = create_customer_payload()
    customer_payload.pop("pass_through_enabled")
    customer_payload.pop("reel_program")
    customer = validate_success(api.create_customer(customer_payload, BILLING), 201)
    assert customer["pass_through_enabled"] is True, "pass-through defaults to true"
    assert customer["reel_program"] == "RETURNABLE", "`reel_program` defaults to RETURNABLE"

    order_payload = create_customer_order_payload(customer["id"], product["id"])
    order = validate_success(api.create_customer_order(order_payload, BILLING), 201)
    assert order["cut_to_length_service"] is False, "cut-to-length service defaults to false"
    assert order["requested_cut_lengths_ft"] == [], "the cut list defaults to empty"
    assert order["hold_reason"] is None


@pytest.mark.parametrize(
    "voltage_class,application_rating,expected_voltage,expected_marking,expected_pd",
    [
        ("LV_600", "THHN", 600, True, False),
        ("LV_600", "THWN_2", 600, True, False),
        ("LV_600", "SOOW", 600, False, False),
        ("MV_5KV", "MV_105", 5000, False, True),
        ("MV_15KV", "MV_105", 15000, False, True),
        ("MV_35KV", "MV_105", 35000, False, True),
    ],
)
def test_sku_gating_fields_are_derived_from_voltage_class_and_application_rating(
    api, voltage_class, application_rating, expected_voltage, expected_marking, expected_pd
):
    """Three of the SKU's gating fields are computed at definition time, and each
    reads a different input than the others.

    PRD 3.4: "`marking_required` is true exactly when the `application_rating`
    is one of `THHN`, `THWN_2`, `XHHW_2` or `USE_2` — the building-wire ratings —
    and false for `MV_105` and `SOOW`."

    Design: Corner/entities/catalog_product_computed_gating_fields_derived_from_class_and_rating
    """
    world = setup_lv_catalog(api)
    product = validate_success(
        api.create_catalog_product(
            create_catalog_product_payload(
                world["insulation"]["id"], world["certification"]["id"],
                product_code=f"SKU-{voltage_class}-{application_rating}",
                voltage_class=voltage_class,
                application_rating=application_rating,
                conductor_construction="COMPRESSED_37",
            ),
            ENGINEER,
        ),
        201,
    )
    assert product["voltage_rating_v"] == expected_voltage, (
        f"{voltage_class} maps to {expected_voltage} volts, got "
        f"{product['voltage_rating_v']}"
    )
    assert product["marking_required"] is expected_marking, (
        f"marking_required for {application_rating} must be {expected_marking}"
    )
    assert product["pd_test_required"] is expected_pd, (
        f"pd_test_required for {voltage_class} must be {expected_pd}"
    )


def test_lot_and_test_system_fields_are_minted_by_the_server_not_the_caller(api):
    """A lot's traceability string and consumed mass, and a test row's operator
    and instant, are all server-derived from inputs the caller never supplies.

    PRD 3.6: "The lot's `traceability_code` is composed as the rod lot's
    `heat_number`, then a single hyphen, then the lot's own `lot_code`, so that a
    reel of finished wire can always be walked back to the heat it was drawn
    from."

    Design: Corner/entities/production_lot_and_cable_test_system_fields_minted_by_server
    """
    world = setup_definitions_and_rod(api)
    rod_version = get_success_data(
        api.get_rod_purchase_lot(world["rod_lot"]["id"], BUYER)
    )["version"]
    lot = validate_success(
        api.create_production_lot(
            create_production_lot_payload(
                world["product"]["id"], world["rod_lot"]["id"], rod_version,
                lot_code="LOT-A", planned_length_ft=5000,
            ),
            ENGINEER,
        ),
        201,
    )
    assert_versioned_common_fields(lot)
    assert is_valid_uuid(lot["id"])
    assert lot["traceability_code"] == "H-77Q-LOT-A", (
        f"heat number, one hyphen and the lot code, got {lot['traceability_code']!r}"
    )
    assert lot["consumed_rod_lbs"] == pytest.approx(99.00, abs=0.01), (
        "5000 ft of a 19.8 lbs/kft SKU draws 99.00 lbs"
    )
    assert lot["process_state"] == "QUEUED"
    assert lot["quality_state"] == "PENDING"
    assert lot["rework_count"] == 0
    assert lot["packaged_length_ft"] == 0
    for field in ("measured_min_wall_mils", "measured_max_wall_mils",
                  "measured_avg_od_mm", "concentricity_pct", "surface_marking_text"):
        assert lot[field] is None, f"{field} starts null on a freshly scheduled lot"

    get_success_data(api.create_process_step(lot["id"], {"step": "DRAWING"}, ENGINEER))
    get_success_data(api.create_process_step(lot["id"], {"step": "STRANDING"}, ENGINEER))
    get_success_data(
        api.create_process_step(
            lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": THHN_12_CU_MARKING},
            ENGINEER,
        )
    )
    test_row = validate_success(
        api.create_cable_test(
            lot["id"], {"test_type": "SPARK", "faults_detected": 0, "duration_sec": 60},
            QE_TESTER,
        ),
        201,
    )
    assert_append_only_common_fields(test_row)
    assert test_row["operator_user_id"] == QE_TESTER_USER_ID, (
        "operator_user_id is copied verbatim from X-User-ID"
    )
    assert test_row["lot_id"] == lot["id"]
    assert test_row["result"] == "PASS", "the verdict is derived, never supplied"
    assert is_iso8601_timestamp(test_row["tested_at"])
    assert test_row["tested_at"].startswith("2026-08-01T00:00:00"), (
        f"tested_at is the logical-clock instant, got {test_row['tested_at']!r}"
    )


@pytest.mark.parametrize(
    "call,expected_error_id",
    [
        (lambda a, w: a.create_compound(
            create_insulation_compound_payload(flame_test="VW_9"), ENGINEER),
         "ERR_INVALID_REQUEST"),
        (lambda a, w: a.create_compound(
            create_insulation_compound_payload(temp_rating_c=100), ENGINEER),
         "ERR_INVALID_REQUEST"),
        (lambda a, w: a.create_compound(
            create_insulation_compound_payload(filler_pct=41.0), ENGINEER),
         "ERR_INVALID_REQUEST"),
        (lambda a, w: a.create_compound(
            create_insulation_compound_payload(max_voltage_v=1200), ENGINEER),
         "ERR_INVALID_REQUEST"),
        (lambda a, w: a.list_metal_price_quotes(BUYER, {"limit": 0}),
         "ERR_INVALID_REQUEST"),
        (lambda a, w: a.list_metal_price_quotes(BUYER, {"limit": 101}),
         "ERR_INVALID_REQUEST"),
        (lambda a, w: a.list_metal_price_quotes(BUYER, {"offset": -1}),
         "ERR_INVALID_REQUEST"),
    ],
)
def test_unrecognised_enums_out_of_range_numbers_and_bad_pages_are_shape_errors(
    api, call, expected_error_id
):
    """Enum membership, numeric bounds and pagination bounds are all decided at
    the same rung, so all of them answer with the one shape code.

    PRD 2.3: "A `limit` outside the inclusive range from 1 to 100, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/invalid_enum_range_and_pagination_inputs_return_shape_errors
    """
    validate_error(call(api, None), expected_error_id, 400)


def test_append_only_rows_expose_no_version_and_a_repeat_quote_is_refused(api):
    """All three append-only record types answer with the same reduced field set,
    and the one of them with a uniqueness key refuses to be restated.

    PRD 3.1: "Settlement prices are immutable historical facts: there is no
    operation that edits or deletes one, which is why a quote row carries only
    its identifier and creation timestamp and has no version counter."

    Design: Corner/entities/append_only_children_carry_no_version_and_cannot_be_restated
    """
    state = setup_returned_reel(
        api, returned_date="2026-08-10", return_clock="2026-08-10T09:00:00Z"
    )
    quote = state["world"]["quote"]
    assert_append_only_common_fields(quote)

    tests, _ = validate_paginated(api.list_cable_tests(state["lot"]["id"], QE_TESTER))
    assert tests, "the lifecycle recorded inline tests on the lot"
    for row in tests:
        assert_append_only_common_fields(row)

    assert_append_only_common_fields(state["reel_return"])

    repeat = api.create_metal_price_quote(
        create_metal_price_quote_payload(
            metal=quote["metal"], effective_date=quote["effective_date"],
            settlement_price_usd_per_lb=9.99,
        ),
        BUYER,
    )
    validate_error(repeat, "ERR_DUPLICATE_METAL_QUOTE", 409)
    survivor, meta = validate_paginated(api.list_metal_price_quotes(BUYER))
    assert_pagination_meta(meta, expected_total_count=1)
    assert survivor[0]["settlement_price_usd_per_lb"] == pytest.approx(
        quote["settlement_price_usd_per_lb"], abs=0.005
    ), "the incumbent quote is never overwritten by the refused repeat"


def test_path_parents_resolve_before_children_and_body_keys_in_declared_order(api):
    """A sub-resource's parent is resolved before the child segment matters, and
    body references are tried in the order the contract fixes.

    PRD 2.10: "Path parameters are validated strictly left to right. When a
    request addresses a sub-resource — the inspections under a listing file, the
    tests under a production lot, the returns under a reel, or the reel returns
    settled against a shipment — the parent `id` in the path is resolved first,
    and a missing parent produces the parent's own not-found error before the
    child segment is considered at all."

    Design: Corner/entities/child_and_body_foreign_keys_resolve_against_declared_parents
    """
    world = setup_baseline(api)

    validate_error(
        api.list_factory_inspections(SENTINEL_UUID, CERT_OFFICER),
        "ERR_CERTIFICATION_NOT_FOUND", 404,
    )
    validate_error(
        api.list_cable_tests(SENTINEL_UUID, QE_TESTER), "ERR_LOT_NOT_FOUND", 404,
    )
    validate_error(
        api.list_reel_returns(SENTINEL_UUID, CLERK), "ERR_REEL_NOT_FOUND", 404,
    )
    validate_error(
        api.list_shipment_reel_returns(SENTINEL_UUID, CLERK),
        "ERR_SHIPMENT_NOT_FOUND", 404,
    )

    both_unknown = create_production_lot_payload(
        SENTINEL_UUID, SENTINEL_UUID, 1, lot_code="LOT-FK",
    )
    validate_error(
        api.create_production_lot(both_unknown, ENGINEER), "ERR_ROD_LOT_NOT_FOUND", 404,
    )

    rod_version = get_success_data(
        api.get_rod_purchase_lot(world["rod_lot"]["id"], BUYER)
    )["version"]
    unknown_product = create_production_lot_payload(
        SENTINEL_UUID, world["rod_lot"]["id"], rod_version, lot_code="LOT-FK2",
    )
    validate_error(
        api.create_production_lot(unknown_product, ENGINEER), "ERR_PRODUCT_NOT_FOUND", 404,
    )

    unknown_customer = create_customer_order_payload(
        SENTINEL_UUID, world["product"]["id"], order_number="SO-FK",
    )
    validate_error(
        api.create_customer_order(unknown_customer, BILLING), "ERR_CUSTOMER_NOT_FOUND", 404,
    )
