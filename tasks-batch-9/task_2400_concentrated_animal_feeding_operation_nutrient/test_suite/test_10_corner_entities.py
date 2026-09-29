"""Entity-level corner cases: creation, retrieval, listing, not-found codes,
required inputs, declared defaults, computed-field rejection, server-minted
system fields, type constraints, immutable registers and parent relationships.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_immutable_register,
    assert_operation_sizing,
    assert_posture,
    assert_quantity,
    assert_storage_balance,
    assert_storage_capacities,
)
from test_helpers.factories import (
    budget_payload,
    operation_payload,
    transfer_payload,
)
from test_helpers.fixtures import (
    cover_permit,
    create_plan,
    file_soil_test,
    file_storage_inspection,
    register_field,
    register_operation,
    register_storage,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    make_operator_headers,
)

# A second well-formed identifier that resolves to no row of any entity.
ANOTHER_MISSING_UUID = "11111111-1111-4111-8111-111111111111"


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
def test_create_operation_computes_animal_units_and_returns_envelope(client):
    """Registering Willow Creek Dairy derives every sizing and production figure.

    PRD: "The operation's `animal_units` is the `head_count` multiplied by that factor, rounded half up to 2 decimal places."
    PRD: "A `MEDIUM` operation requires coverage when its `discharge_potential` is `STORMWATER_ONLY` or `CONTINUOUS`, and not when it is `NONE`."
    PRD: "`design_annual_manure_gallons` is the `head_count` multiplied by the per-head volume multiplied by the dilution factor, plus that lot precipitation volume, the sum rounded half up to 2 decimal places."
    PRD: "A newly registered operation starts with `recorded_annual_manure_gallons` and `design_storage_days` at 0, both counters at 0, and a `compliance_posture` of `OPEN`."
    PRD: "Every record the API creates receives an `id`: a server-minted UUID with no type prefix and no embedded meaning."
    Design: Corner/entities/create_operation_computes_animal_units_and_returns_envelope
    """
    response = client.create_operation(operation_payload(), ADMIN_HEADERS)
    data = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object", (
        f"response_type: expected object, got {body['response_type']}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {body['meta']['api_request_id']}"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
        f"api_request_timestamp is not ISO 8601: {body['meta']['api_request_timestamp']}"
    )

    assert_operation_sizing(data, 420.00, "MEDIUM", True, 3374298.00, 9244.65)
    assert data["design_storage_days"] == 0, (
        f"design_storage_days: expected 0 with no storage structure, "
        f"got {data['design_storage_days']}"
    )
    assert_quantity(
        data["recorded_annual_manure_gallons"], 0.00, "recorded_annual_manure_gallons"
    )
    assert_posture(data, "OPEN", findings=0, discharges=0)

    assert_common_fields(data, "operation")
    assert data["version"] == 1, f"version: expected 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), f"id is not a bare UUID: {data['id']}"
    assert "_" not in data["id"], f"id carries a type prefix: {data['id']}"


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def test_get_operation_returns_the_stored_and_computed_row(client):
    """A read echoes the stored inputs plus the derived figures and writes nothing.

    PRD: "`version` is an integer that starts at 1 and increments by one on every such mutation."
    PRD: "`daily_production_gallons` is `design_annual_manure_gallons` divided by 365, rounded half up to 2 decimal places."
    Design: Corner/entities/get_operation_returns_the_stored_and_computed_row
    """
    operation = register_operation()

    data = validate_success(
        client.get_operation(operation["id"], REVIEWER_HEADERS), 200
    )

    assert data["name"] == "Willow Creek Dairy", f"name: got {data['name']}"
    assert data["county"] == "Linn", f"county: got {data['county']}"
    assert data["animal_type"] == "DAIRY_COW", f"animal_type: got {data['animal_type']}"
    assert data["head_count"] == 300, f"head_count: got {data['head_count']}"
    assert data["manure_handling"] == "LIQUID", (
        f"manure_handling: got {data['manure_handling']}"
    )
    assert_quantity(data["open_lot_area_sqft"], 40000, "open_lot_area_sqft")
    assert data["has_conservation_plan"] is True, (
        f"has_conservation_plan: got {data['has_conservation_plan']}"
    )

    assert_quantity(data["animal_units"], 420.00, "animal_units")
    assert_quantity(
        data["design_annual_manure_gallons"], 3374298.00, "design_annual_manure_gallons"
    )
    assert_quantity(
        data["daily_production_gallons"], 9244.65, "daily_production_gallons"
    )
    assert data["version"] == 1, (
        f"version: a read must not write, expected 1, got {data['version']}"
    )


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
def test_list_operations_defaults_to_limit_ten_and_reports_total_count(client):
    """Eleven rows page as ten plus one, and the county filter narrows the total.

    PRD: "`limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
    PRD: "`offset` is the number of records to skip before the first returned record and defaults to 0."
    PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object, where `total_count` is the number of records matching the filters before pagination and `has_more` indicates whether records remain beyond the current page."
    PRD: "A `SMALL` operation requires coverage only when its `discharge_potential` is `CONTINUOUS`."
    Design: Corner/entities/list_operations_defaults_to_limit_ten_and_reports_total_count
    """
    last_id = None
    for index in range(1, 12):
        payload = {
            "name": f"Op {index:02d}",
            "county": "Benton" if index == 11 else "Linn",
            "animal_type": "SWINE_FINISHING",
            "head_count": 100,
            "manure_handling": "LIQUID",
            "discharge_potential": "NONE",
        }
        created = validate_success(client.create_operation(payload, ADMIN_HEADERS), 201)
        last_id = created["id"]

    first_page_response = client.list_operations(REVIEWER_HEADERS)
    assert first_page_response.json()["response_type"] == "array", (
        "a list endpoint must declare response_type array"
    )
    first_page, meta = validate_paginated(first_page_response)
    assert len(first_page) == 10, f"default page size: got {len(first_page)} rows"
    assert meta["limit"] == 10, f"limit: expected the default 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset: expected the default 0, got {meta['offset']}"
    assert meta["total_count"] == 11, f"total_count: got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with a row left over"

    assert_quantity(first_page[0]["animal_units"], 40.00, "animal_units")
    for row in first_page:
        assert row["size_class"] == "SMALL", (
            f"{row['name']} size_class: got {row['size_class']}"
        )
        assert row["permit_required"] is False, (
            f"{row['name']} permit_required: got {row['permit_required']}"
        )

    remainder, meta = validate_paginated(
        client.list_operations(REVIEWER_HEADERS, {"offset": 10})
    )
    assert len(remainder) == 1, f"offset 10 should leave 1 row, got {len(remainder)}"
    assert meta["limit"] == 10, f"limit: got {meta['limit']}"
    assert meta["offset"] == 10, f"offset: got {meta['offset']}"
    assert meta["total_count"] == 11, f"total_count: got {meta['total_count']}"
    assert meta["has_more"] is False, "has_more must be false on the last page"

    filtered, meta = validate_paginated(
        client.list_operations(REVIEWER_HEADERS, {"county": "Benton", "limit": 5})
    )
    assert len(filtered) == 1, f"county filter should match 1 row, got {len(filtered)}"
    assert filtered[0]["id"] == last_id, "the Benton row must be the eleventh operation"
    assert meta["limit"] == 5, f"limit: expected the supplied 5, got {meta['limit']}"
    assert meta["total_count"] == 1, (
        f"total_count counts matches before pagination, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "has_more must be false for a single match"


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------
def test_get_by_unknown_id_returns_entity_specific_not_found(client):
    """One absent identifier yields fourteen different entity-specific codes.

    PRD: "Path existence — every identifier embedded in the request path resolves to an existing record, validated left to right, returning the not-found code of the failing segment."
    PRD: "Identifiers are resolved strictly left to right and the response names the *first* segment that fails, using the entity-specific code: `ERR_OPERATION_NOT_FOUND`, `ERR_HAULER_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_FIELD_NOT_FOUND`, `ERR_SOIL_TEST_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_STORAGE_NOT_FOUND`, `ERR_STORAGE_INSPECTION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND` or `ERR_REPORT_NOT_FOUND`."
    Design: Corner/entities/get_by_unknown_id_returns_entity_specific_not_found
    """
    cases = (
        (client.get_operation, ApiErrorId.ERR_OPERATION_NOT_FOUND),
        (client.get_hauler, ApiErrorId.ERR_HAULER_NOT_FOUND),
        (client.get_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (client.get_nutrient_plan, ApiErrorId.ERR_PLAN_NOT_FOUND),
        (client.get_field, ApiErrorId.ERR_FIELD_NOT_FOUND),
        (client.get_soil_test, ApiErrorId.ERR_SOIL_TEST_NOT_FOUND),
        (client.get_field_budget, ApiErrorId.ERR_BUDGET_NOT_FOUND),
        (client.get_manure_storage, ApiErrorId.ERR_STORAGE_NOT_FOUND),
        (client.get_storage_inspection, ApiErrorId.ERR_STORAGE_INSPECTION_NOT_FOUND),
        (client.get_application_event, ApiErrorId.ERR_EVENT_NOT_FOUND),
        (client.get_manure_transfer, ApiErrorId.ERR_TRANSFER_NOT_FOUND),
        (client.get_incident_report, ApiErrorId.ERR_INCIDENT_NOT_FOUND),
        (client.get_inspection, ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (client.get_annual_report, ApiErrorId.ERR_REPORT_NOT_FOUND),
    )

    for getter, expected in cases:
        response = getter(NON_EXISTENT_UUID, ADMIN_HEADERS)
        assert response.status_code == 404, (
            f"{expected.value}: expected HTTP 404, got {response.status_code}"
        )
        error = validate_error(response, expected.value)
        assert error["message"].strip(), f"{expected.value} carried an empty message"


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------
def test_create_field_missing_required_input_is_rejected(client):
    """slope_pct and water_frontage_ft carry no default, so omitting either is a 400.

    PRD: "The physical description comprises `total_acres`, which must be greater than 0; `distance_to_water_ft`, the shortest distance from the field edge to surface water, which may not be negative; `has_tile_inlet`, a flag for the presence of a surface tile inlet that defaults to false; `slope_pct`, the dominant slope percentage, which may not be negative; and `water_frontage_ft`, the length of field boundary that adjoins surface water, which may not be negative either."
    PRD: "Request shape — required fields present, no unknown fields, declared types, enum members and range constraints satisfied, and the polymorphic incident-subject rule honoured (`ERR_INVALID_REQUEST`)."
    Design: Corner/entities/create_field_missing_required_input_is_rejected
    """
    operation = register_operation()
    base = {
        "operation_id": operation["id"],
        "field_name": "North 40",
        "total_acres": 42.5,
        "distance_to_water_ft": 150,
    }

    without_slope = client.create_field(
        dict(base, water_frontage_ft=900), PLANNER_HEADERS
    )
    assert without_slope.status_code == 400, (
        f"omitting slope_pct: expected HTTP 400, got {without_slope.status_code}"
    )
    validate_error(without_slope, ApiErrorId.ERR_INVALID_REQUEST.value)

    without_frontage = client.create_field(dict(base, slope_pct=4.0), PLANNER_HEADERS)
    assert without_frontage.status_code == 400, (
        f"omitting water_frontage_ft: expected HTTP 400, "
        f"got {without_frontage.status_code}"
    )
    error = validate_error(without_frontage, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert error["message"].strip(), "the rejection must carry a message"

    _, meta = validate_paginated(
        client.list_fields(PLANNER_HEADERS, {"operation_id": operation["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no field may have been written, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
def test_omitted_optional_operation_and_storage_inputs_apply_declared_defaults(client):
    """An omitted lot area zeroes the precipitation term and freeboard defaults to 24 in.

    PRD: "Two further inputs are optional: `open_lot_area_sqft`, the uncovered lot area whose precipitation runoff reaches storage, which defaults to 0; and `has_conservation_plan`, a flag recording whether an accepted conservation plan is on file, which defaults to false."
    PRD: "`required_freeboard_in`, the freeboard that must be preserved above the liquid surface, defaults to 24 inches; it may not be negative and must be strictly less than `total_depth_in`."
    PRD: "`operating_capacity_gallons` is `design_capacity_gallons` less `freeboard_reserve_gallons` — the volume the structure may lawfully hold."
    PRD: "The operation-wide `design_storage_days` is the sum of `operating_capacity_gallons` across every storage structure of the operation, regardless of each structure's `storage_status`, divided by the same effective daily production and floored to a whole day; because it ignores current contents and commitments entirely, it moves only with herd size, structure geometry and the clock's month — and it is this figure that plan certification tests against the 180-day minimum."
    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    operation = validate_success(
        client.create_operation(
            {
                "name": "Dry Lot Dairy",
                "county": "Linn",
                "animal_type": "DAIRY_COW",
                "head_count": 300,
                "manure_handling": "LIQUID",
                "discharge_potential": "CONTINUOUS",
            },
            ADMIN_HEADERS,
        ),
        201,
    )
    operation_id = operation["id"]

    assert_quantity(operation["open_lot_area_sqft"], 0, "open_lot_area_sqft")
    assert operation["has_conservation_plan"] is False, (
        f"has_conservation_plan must default to false, "
        f"got {operation['has_conservation_plan']}"
    )
    assert_quantity(
        operation["design_annual_manure_gallons"],
        3105000.00,
        "design_annual_manure_gallons",
    )
    assert_quantity(
        operation["daily_production_gallons"], 8506.85, "daily_production_gallons"
    )

    storage = validate_success(
        client.create_manure_storage(
            {
                "operation_id": operation_id,
                "structure_name": "Lagoon 1",
                "structure_type": "EARTHEN_LAGOON",
                "surface_area_sqft": 60000,
                "total_depth_in": 144,
            },
            make_operator_headers(operation_id),
        ),
        201,
    )
    assert_quantity(storage["required_freeboard_in"], 24, "required_freeboard_in")
    assert_storage_capacities(storage, reserve=897660.00, operating=4488300.00)

    refreshed = validate_success(
        client.get_operation(operation_id, ADMIN_HEADERS), 200
    )
    assert refreshed["design_storage_days"] == 527, (
        f"design_storage_days: expected floor(4488300.00 / 8506.85) == 527, "
        f"got {refreshed['design_storage_days']}"
    )


def test_omitted_hauler_endorsement_defaults_to_false(client):
    """certified_applicator defaults to false and hauler_status derives to ACTIVE.

    PRD: "Haulers themselves are registered by a `ComplianceAdmin` with a `business_name`, a state `license_number`, and a `license_expires_on` instant at which the licence lapses; `certified_applicator`, recording whether the hauler holds a certified applicator endorsement, defaults to false."
    PRD: "A hauler's `hauler_status` is derived, not supplied: it is `ACTIVE` while the logical clock is at or before `license_expires_on` and `LAPSED` thereafter, and it is re-evaluated on every read and again whenever the logical clock is set — the clock response reports how many lapsed as `haulers_lapsed_count`."
    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    hauler = validate_success(
        client.create_hauler(
            {
                "business_name": "Prairie Pumping LLC",
                "license_number": "HL-4417",
                "license_expires_on": "2027-12-31T00:00:00Z",
            },
            ADMIN_HEADERS,
        ),
        201,
    )

    assert hauler["certified_applicator"] is False, (
        f"certified_applicator must default to false, "
        f"got {hauler['certified_applicator']}"
    )
    assert hauler["hauler_status"] == "ACTIVE", (
        f"hauler_status: expected ACTIVE, got {hauler['hauler_status']}"
    )


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------
def test_client_supplied_computed_field_is_rejected_as_unknown_field(client):
    """Posting a derived figure is an unknown body field, not a silent overwrite.

    PRD: "Request shape — required fields present, no unknown fields, declared types, enum members and range constraints satisfied, and the polymorphic incident-subject rule honoured (`ERR_INVALID_REQUEST`)."
    PRD: "From those inputs the system immediately derives the operation's regulatory size."
    Design: Corner/entities/client_supplied_computed_field_is_rejected_as_unknown_field
    """
    with_units = client.create_operation(
        operation_payload(animal_units=9999.0), ADMIN_HEADERS
    )
    assert with_units.status_code == 400, (
        f"supplying animal_units: expected HTTP 400, got {with_units.status_code}"
    )
    validate_error(with_units, ApiErrorId.ERR_INVALID_REQUEST.value)

    with_class = client.create_operation(
        operation_payload(size_class="SMALL"), ADMIN_HEADERS
    )
    assert with_class.status_code == 400, (
        f"supplying size_class: expected HTTP 400, got {with_class.status_code}"
    )
    error = validate_error(with_class, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert error["message"].strip(), "the rejection must carry a message"

    _, meta = validate_paginated(client.list_operations(ADMIN_HEADERS))
    assert meta["total_count"] == 0, (
        f"neither create may have partially applied, got {meta['total_count']} rows"
    )


# ---------------------------------------------------------------------------
# System fields
# ---------------------------------------------------------------------------
def test_system_fields_are_server_minted_and_version_increments_on_patch(client):
    """id and created_at survive a patch while version moves 1 to 2 and sizing re-derives.

    PRD: "Every record also receives a `created_at`, an ISO 8601 UTC timestamp with three fractional digits, marking the moment the record was written."
    PRD: "Any such revision re-derives `animal_units`, `size_class`, `permit_required`, `design_annual_manure_gallons` and `daily_production_gallons`; recomputes the operation's `design_storage_days`; recomputes `days_of_storage_available` on every storage structure of the operation, since the daily production figure is the denominator of both; and increments the operation's `version` by 1."
    Design: Corner/entities/system_fields_are_server_minted_and_version_increments_on_patch
    """
    operation = register_operation()
    operation_id = operation["id"]
    created_at = operation["created_at"]

    data = validate_success(
        client.update_operation(
            operation_id, {"head_count": 400}, make_operator_headers(operation_id)
        ),
        200,
    )

    assert data["id"] == operation_id, f"id must not move: got {data['id']}"
    assert data["created_at"] == created_at, (
        f"created_at must not move: expected {created_at}, got {data['created_at']}"
    )
    assert data["version"] == 2, f"version: expected 2 after one patch, got {data['version']}"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at is not ISO 8601: {data['updated_at']}"
    )
    assert data["updated_at"] >= data["created_at"], (
        f"updated_at {data['updated_at']} precedes created_at {data['created_at']}"
    )

    assert_quantity(data["animal_units"], 560.00, "animal_units")
    assert data["size_class"] == "MEDIUM", f"size_class: got {data['size_class']}"
    assert_quantity(
        data["design_annual_manure_gallons"], 4409298.00, "design_annual_manure_gallons"
    )
    assert_quantity(
        data["daily_production_gallons"], 12080.27, "daily_production_gallons"
    )


# ---------------------------------------------------------------------------
# Type constraints
# ---------------------------------------------------------------------------
def test_invalid_enum_and_out_of_range_values_are_rejected(client):
    """An undeclared enum member and a negative measurement are both 400s that persist nothing.

    PRD: "`animal_type` is one of `DAIRY_COW`, `BEEF_FEEDER`, `SWINE_FINISHING` or `LAYER_HEN`; `manure_handling` is either `LIQUID` or `DRY`; `discharge_potential` is one of `NONE`, `STORMWATER_ONLY` or `CONTINUOUS`."
    PRD: "Each records `inspected_on`, the instant of the inspection, which may not be later than the logical clock; `inspector_name`, the person who performed it; `measured_freeboard_in`, the vertical distance from the liquid surface to the top of the structure, which may not be negative and may not exceed the structure's `total_depth_in`; and `visual_condition`, the recorded state of berms, liner and outlets, being one of `NORMAL`, `SEEPAGE`, `EROSION` or `CRACKING`."
    Design: Corner/entities/invalid_enum_and_out_of_range_values_are_rejected
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)

    bad_enum = client.create_operation(
        {
            "name": "Goat Dairy",
            "county": "Linn",
            "animal_type": "GOAT",
            "head_count": 300,
            "manure_handling": "LIQUID",
            "discharge_potential": "CONTINUOUS",
        },
        ADMIN_HEADERS,
    )
    assert bad_enum.status_code == 400, (
        f"animal_type GOAT: expected HTTP 400, got {bad_enum.status_code}"
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value)

    inspection_body = {
        "storage_id": storage["id"],
        "inspected_on": "2026-07-30T00:00:00Z",
        "inspector_name": "T. Beck",
        "measured_freeboard_in": -3,
        "visual_condition": "NORMAL",
    }
    negative = client.create_storage_inspection(inspection_body, operator_headers)
    assert negative.status_code == 400, (
        f"negative measured_freeboard_in: expected HTTP 400, got {negative.status_code}"
    )
    validate_error(negative, ApiErrorId.ERR_INVALID_REQUEST.value)

    bad_condition = client.create_storage_inspection(
        dict(inspection_body, measured_freeboard_in=30, visual_condition="MUDDY"),
        operator_headers,
    )
    assert bad_condition.status_code == 400, (
        f"visual_condition MUDDY: expected HTTP 400, got {bad_condition.status_code}"
    )
    validate_error(bad_condition, ApiErrorId.ERR_INVALID_REQUEST.value)

    refreshed = validate_success(
        client.get_manure_storage(storage["id"], operator_headers), 200
    )
    assert refreshed["storage_status"] == "IN_SERVICE", (
        f"storage_status: no rejected inspection may land, got {refreshed['storage_status']}"
    )
    assert refreshed["last_inspected_on"] is None, (
        f"last_inspected_on must still be null, got {refreshed['last_inspected_on']}"
    )

    _, meta = validate_paginated(client.list_operations(ADMIN_HEADERS))
    assert meta["total_count"] == 1, (
        f"exactly one operation may exist, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------
def test_soil_test_is_an_append_only_register(client):
    """A soil test carries id and created_at only, while still exposing its index.

    PRD: "Two record kinds are **immutable registers**: a soil test and a storage inspection are written once, are never edited, and consequently carry only `id` and `created_at`."
    PRD: "Neither `updated_at` nor `version` exists on them at all, and their absence is deliberate rather than an omission."
    PRD: "`p_index` is `soil_test_p_ppm` multiplied by one plus the parent field's `slope_pct` divided by 100, rounded half up to 2 decimal places — so steeper ground converts the same measured concentration into a higher runoff risk index."
    PRD: "A soil test also carries `is_valid`, which is true while the logical clock is strictly earlier than four years after `sampled_on`."
    Design: Corner/entities/soil_test_and_storage_inspection_are_append_only_records
    """
    operation = register_operation()
    field = register_field(operation["id"])

    soil_test = file_soil_test(field["id"])

    assert_immutable_register(soil_test, "soil test")
    assert_quantity(soil_test["p_index"], 43.68, "p_index")
    assert soil_test["p_index_category"] == "MEDIUM", (
        f"p_index_category: got {soil_test['p_index_category']}"
    )
    assert soil_test["is_valid"] is True, (
        f"is_valid: a 2026-03-15 sample is current, got {soil_test['is_valid']}"
    )


def test_storage_inspection_is_an_append_only_register(client):
    """A storage inspection carries no version, yet reconciles the volume balance.

    PRD: "Two record kinds are **immutable registers**: a soil test and a storage inspection are written once, are never edited, and consequently carry only `id` and `created_at`."
    PRD: "Liquid depth is `total_depth_in` less `measured_freeboard_in`; `measured_volume_gallons` is `surface_area_sqft` multiplied by that liquid depth divided by 12, multiplied by 7.4805, rounded half up to 2 decimal places."
    PRD: "`freeboard_deficit_in` is the structure's `required_freeboard_in` less `measured_freeboard_in`, with any negative result replaced by 0, rounded half up to 2 decimal places."
    PRD: "The reconciliation term is then rewritten: `precipitation_adjustment_gallons` becomes `measured_volume_gallons` less `cumulative_intake_gallons` plus `cumulative_outflow_gallons`, rounded half up to 2 decimal places, which is precisely the value that makes the volume-balance invariant exact against what the inspector measured."
    Design: Corner/entities/soil_test_and_storage_inspection_are_append_only_records
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)

    inspection = file_storage_inspection(
        operation_id,
        storage["id"],
        operator_headers,
        inspected_on="2026-07-30T00:00:00Z",
        inspector_name="T. Beck",
        measured_freeboard_in=30,
        visual_condition="NORMAL",
    )

    assert_immutable_register(inspection, "storage inspection")
    assert_quantity(
        inspection["measured_volume_gallons"], 4263885.00, "measured_volume_gallons"
    )
    assert_quantity(inspection["freeboard_deficit_in"], 0.00, "freeboard_deficit_in")
    assert inspection["alert_raised"] is False, (
        f"alert_raised: 30 in of freeboard raises nothing, got {inspection['alert_raised']}"
    )

    refreshed = validate_success(
        client.get_manure_storage(storage["id"], operator_headers), 200
    )
    assert_storage_balance(
        refreshed,
        intake=0.00,
        precipitation=4263885.00,
        outflow=0.00,
        current=4263885.00,
        committed=0.00,
    )
    assert refreshed["last_inspected_on"].startswith("2026-07-30"), (
        f"last_inspected_on: got {refreshed['last_inspected_on']}"
    )
    assert refreshed["storage_status"] == "IN_SERVICE", (
        f"storage_status: got {refreshed['storage_status']}"
    )


# ---------------------------------------------------------------------------
# Parent relationships
# ---------------------------------------------------------------------------
def test_budget_rejects_soil_test_belonging_to_another_field(client):
    """A real but cross-field soil test is refused on field ownership, not validity.

    PRD: "Only the named soil test participates — other tests on the same field are ignored entirely — and that test must have `is_valid` true and must belong to the same field as the budget, or the request is refused with `ERR_NO_VALID_SOIL_TEST`."
    PRD: "A base setback is selected by a strict precedence: a field with a tile inlet takes 300 feet regardless of anything else, because a tile inlet is a direct conduit to surface water; a field with no tile inlet whose `distance_to_water_ft` is 200 feet or less takes 200 feet; and every other field takes 100 feet."
    PRD: "`net_applicable_acres` is `total_acres` less `excluded_acres`, rounded half up to 2 decimal places."
    Design: Corner/entities/budget_rejects_soil_test_belonging_to_another_field
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit = cover_permit(operation_id, operator_headers)

    north = register_field(operation_id, PLANNER_HEADERS)
    south = register_field(
        operation_id,
        PLANNER_HEADERS,
        field_name="South 20",
        total_acres=20.0,
        distance_to_water_ft=900,
        slope_pct=2.0,
        water_frontage_ft=0,
    )
    file_soil_test(north["id"], PLANNER_HEADERS)
    south_soil = file_soil_test(
        south["id"],
        PLANNER_HEADERS,
        soil_test_p_ppm=30,
        soil_test_k_ppm=150,
        organic_matter_pct=3.1,
    )

    plan = create_plan(
        operation_id,
        permit["id"],
        PLANNER_HEADERS,
        allowed_application_methods=["INJECTION"],
    )

    response = client.create_field_budget(
        budget_payload(plan["id"], north["id"], south_soil["id"]), PLANNER_HEADERS
    )
    assert response.status_code == 422, (
        f"cross-field soil test: expected HTTP 422, got {response.status_code}"
    )
    validate_error(response, ApiErrorId.ERR_NO_VALID_SOIL_TEST.value)

    read_back = validate_success(
        client.get_soil_test(south_soil["id"], PLANNER_HEADERS), 200
    )
    assert read_back["is_valid"] is True, (
        "the rejection must be about field ownership, not staleness"
    )

    _, meta = validate_paginated(
        client.list_field_budgets(PLANNER_HEADERS, {"plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no budget may have been written, got {meta['total_count']}"
    )

    south_read = validate_success(client.get_field(south["id"], PLANNER_HEADERS), 200)
    assert_quantity(south_read["required_setback_ft"], 100, "required_setback_ft")
    assert_quantity(south_read["excluded_acres"], 0.00, "excluded_acres")
    assert_quantity(south_read["net_applicable_acres"], 20.00, "net_applicable_acres")


# ---------------------------------------------------------------------------
# Flat body-reference ordering
# ---------------------------------------------------------------------------
def test_body_foreign_keys_are_validated_in_declaration_order(client):
    """With both references absent the storage code surfaces first, the hauler code second.

    PRD: "Body reference existence — every foreign key supplied in the request body resolves to an existing record, validated in the declaration order of the target entity's fields, returning the not-found code of the failing field."
    PRD: "An `Operator` initiates a transfer naming its own `operation_id`, the `storage_id` the load is drawn from, and the `hauler_id` moving it."
    Design: Corner/entities/body_foreign_keys_are_validated_in_declaration_order
    """
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    cover_permit(operation_id, operator_headers)

    recipient = {
        "recipient_name": "Kroeger Row Crops",
        "recipient_address": "1188 County Road E, Linn",
        "transferred_on": "2026-07-28T00:00:00Z",
        "gallons_transferred": 100000,
        "nutrient_analysis_provided": True,
    }

    both_missing = client.create_manure_transfer(
        transfer_payload(
            operation_id, NON_EXISTENT_UUID, ANOTHER_MISSING_UUID, **recipient
        ),
        operator_headers,
    )
    assert both_missing.status_code == 404, (
        f"storage_id is declared first: expected HTTP 404, got {both_missing.status_code}"
    )
    validate_error(both_missing, ApiErrorId.ERR_STORAGE_NOT_FOUND.value)

    hauler_missing = client.create_manure_transfer(
        transfer_payload(
            operation_id, storage["id"], ANOTHER_MISSING_UUID, **recipient
        ),
        operator_headers,
    )
    assert hauler_missing.status_code == 404, (
        f"hauler_id absent: expected HTTP 404, got {hauler_missing.status_code}"
    )
    validate_error(hauler_missing, ApiErrorId.ERR_HAULER_NOT_FOUND.value)

    _, meta = validate_paginated(
        client.list_manure_transfers(operator_headers, {"operation_id": operation_id})
    )
    assert meta["total_count"] == 0, (
        f"no transfer may have been written, got {meta['total_count']}"
    )

    refreshed = validate_success(
        client.get_manure_storage(storage["id"], operator_headers), 200
    )
    assert_quantity(
        refreshed["committed_outflow_gallons"], 0.00, "committed_outflow_gallons"
    )
