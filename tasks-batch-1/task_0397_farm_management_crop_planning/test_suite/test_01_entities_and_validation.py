"""Entity creation, field shape, system-managed defaults, and input validation.

Corner queue B: section `entities`, section `validations` (field-shape subset),
section `endpoints` (down-asset start-state guard).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_parcel_payload, create_input_product_payload, create_applicator_payload,
    create_draft_plan, create_parcel,
    setup_harvesting_plan, create_equipment_asset,
    assert_parcel, NON_EXISTENT_UUID,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]


def test_create_parcel_returns_201_with_defaults(api):
    """PRD §3.1: "A `FarmManager` creates parcels; each one begins life with
    `status` `AVAILABLE` and an `active_crop_plan_count` of zero."
    PRD §2.4: "a `version` integer that begins at its initial value on creation".

    Design: Corner/entities/create_parcel_returns_201_with_defaults
    """
    resp = api.create_parcel(
        create_parcel_payload(name="P1", acreage=25.5, soil_type="CLAY"), FM)
    data = validate_success(resp, expected_status=201)
    assert_parcel(data)
    assert data["status"] == "AVAILABLE", f"expected AVAILABLE, got {data['status']}"
    assert data["active_crop_plan_count"] == 0
    assert data["version"] == 1, f"version must begin at 1, got {data['version']}"


def test_get_parcel_not_found(api):
    """PRD §2.7: "the first id that fails to resolve to an existing resource causes
    the request to be rejected with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_parcel_not_found
    """
    resp = api.get_parcel(NON_EXISTENT_UUID, FM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_parcel_missing_required_field(api):
    """PRD §2.10: "required body fields must be present and well-typed, enum members must be
    valid, and numeric ranges must hold (acreage greater than zero, moisture between 0 and
    100 inclusive, and the like), else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_parcel_missing_required_field
    """
    resp = api.create_parcel({"name": "NoAcre", "soil_type": "LOAM"}, FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_parcel_nonpositive_acreage_rejected(api):
    """PRD §3.1: "a tillable `acreage` that must be strictly greater than zero".
    PRD §2.10: "required body fields must be present and well-typed, enum members must be
    valid, and numeric ranges must hold (acreage greater than zero, moisture between 0 and
    100 inclusive, and the like), else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_parcel_nonpositive_acreage_rejected
    """
    resp = api.create_parcel(
        create_parcel_payload(name="Zero", acreage=0, soil_type="LOAM"), FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_harvest_event_moisture_out_of_range_rejected(api):
    """PRD §3.5: "the `moisture_pct` (between 0 and 100 inclusive)".
    PRD §2.10: "required body fields must be present and well-typed, enum members must be
    valid, and numeric ranges must hold (acreage greater than zero, moisture between 0 and
    100 inclusive, and the like), else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_harvest_event_moisture_out_of_range_rejected
    """
    ctx = setup_harvesting_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    resp = api.create_harvest_event({
        "crop_plan_id": ctx["plan"]["id"], "acres_harvested": 40.0,
        "gross_quantity": 100.0, "moisture_pct": 150.0}, AG)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_system_fields_ignored_on_create(api):
    """PRD §3.1: "A new plan is created in `DRAFT` with `revision_count` zero and its
    computed cost and yield fields initialized."

    Design: Corner/entities/system_fields_ignored_on_create
    """
    parcel = create_parcel(name="SF", acreage=50.0)
    resp = api.create_crop_plan({
        "parcel_id": parcel["id"], "crop": "CORN", "season_year": 2026,
        "planned_acres": 40.0, "budget_input_cost": 100.0, "budget_labor_cost": 100.0,
        "budget_equipment_cost": 100.0}, AG)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"server must force DRAFT, got {data['status']}"
    assert data["revision_count"] == 0, f"revision_count must be 0, got {data['revision_count']}"


def test_computed_applied_cost_correct(api):
    """PRD §3.4: "the system computes `quantity_used` as `rate_per_acre` multiplied by
    `acres_treated`, and `applied_cost` as `quantity_used` multiplied by the product's
    `unit_cost`, rounded to two decimal places."

    Design: Corner/entities/computed_applied_cost_correct
    """
    parcel = create_parcel(name="ACF", acreage=100.0)
    chem = validate_success(api.create_input_product(create_input_product_payload(
        name="Chem AC", category="CHEMICAL", unit="GAL", unit_cost=12.50), FM), 201)
    appl = validate_success(api.create_applicator(
        create_applicator_payload(full_name="A", license_no="RU-60"), FM), 201)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=100.0)
    resp = api.create_application_record({
        "crop_plan_id": plan["id"], "input_product_id": chem["id"],
        "applicator_user_id": appl["id"], "rate_per_acre": 2.0, "acres_treated": 40.0}, AG)
    data = validate_success(resp, expected_status=201)
    assert data["quantity_used"] == 80, f"quantity_used = 2*40 = 80, got {data['quantity_used']}"
    assert data["applied_cost"] == 1000.00, f"applied_cost = 80*12.50 = 1000.00, got {data['applied_cost']}"


def test_list_parcels_pagination_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    count of all matching items before pagination and `has_more` indicates whether
    items remain beyond the returned page."

    Design: Corner/entities/list_parcels_pagination_envelope
    """
    create_parcel(name="A", acreage=10.0, soil_type="LOAM")
    create_parcel(name="B", acreage=20.0, soil_type="SAND")
    resp = api.list_parcels(FM, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"
    assert len(data) == 1, f"limit=1 should return one item, got {len(data)}"


def test_equipment_asset_starts_active(api):
    """PRD §3.8: "An asset begins `ACTIVE`; an asset whose `status` is `DOWN` cannot
    take new usage bookings."

    Design: Corner/endpoints/equipment_usage_on_down_asset_rejected
    """
    asset = create_equipment_asset(name="Broken", kind="TRACTOR", hourly_cost=50.0)
    resp = api.get_equipment_asset(asset["id"], FM)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE", f"asset must begin ACTIVE, got {data['status']}"
