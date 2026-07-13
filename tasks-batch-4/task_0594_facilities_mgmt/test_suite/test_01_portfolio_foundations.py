"""Buildings, spaces, assets and preventive-maintenance plans — the portfolio
foundations: creation defaults, uniqueness codes, the condition-score decay curve,
request-shape rejection, and list pagination.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    asset_payload,
    assert_asset,
    assert_building,
    assert_space,
    assert_utility_reading,
    building_payload,
    create_asset,
    create_building,
    create_pm_plan,
    create_space,
    create_work_order,
    is_valid_uuid,
    pm_plan_payload,
    report_failure,
    set_clock,
    space_payload,
    utility_reading_payload,
    validate_error,
    validate_paginated,
    validate_success,
    work_order_payload,
)

FM = TEST_USERS["facility_manager_headers"]
SA = TEST_USERS["sustainability_analyst_headers"]


def test_new_building_starts_open_with_zeroed_counters(api):
    """PRD §3.1: "A newly registered building comes up with `operating_posture` at
    `OPEN`, `oos_critical_asset_count` at 0, and `open_p1_work_order_count` at 0."
    PRD §2.4: "Every persisted resource carries a server-minted `id`, a UUID string
    with no type prefix, allocated by the server and never supplied by a client."
    PRD §2.4: "Almost every resource additionally carries an `updated_at` timestamp
    in the same format and an integer `version` that starts at 1 on creation and
    increments by 1 on every mutation of that resource; `updated_at` is refreshed on
    every mutation as well."

    Design: Corner/entities/building_create_returns_system_fields_and_open_posture
    """
    set_clock("2026-05-04T09:00:00Z")
    response = api.create_building(
        building_payload(name="Tower One", code="BLD-1", gross_area_sqm=1000,
                         region="APAC"),
        FM,
    )
    data = validate_success(response, 201)
    assert_building(data)

    assert data["operating_posture"] == "OPEN"
    assert data["oos_critical_asset_count"] == 0
    assert data["open_p1_work_order_count"] == 0
    assert data["version"] == 1, "version starts at 1 on creation"
    assert is_valid_uuid(data["id"]), "id must be a bare UUID with no type prefix"
    assert len(data["id"]) == 36, f"id must be a bare 36-char UUID, got {data['id']!r}"

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_get_unknown_building_returns_not_found(api):
    """PRD §2.5: "When a client addresses a space through its building, the building
    is looked up first; if it does not exist the request fails with
    `ERR_BUILDING_NOT_FOUND` (HTTP 404) and the space is never consulted."

    Design: Corner/entities/get_building_with_unknown_id_not_found
    """
    create_building()

    response = api.get_building("00000000-0000-4000-8000-000000000000", FM)
    validate_error(response, ApiErrorId.ERR_BUILDING_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"


def test_work_order_missing_estimated_parts_cost_rejected(api):
    """PRD §3.4: "A `FacilityManager` or `PlatformAdmin` raises an order by naming the
    `building_id` it belongs to, its `wo_type` (`CORRECTIVE`, `PREVENTIVE`, or
    `SOFT_SERVICE`), its `priority` (`P1`, `P2`, `P3`, or `P4`), and the two estimates
    the provisional cost is derived from: `estimated_labor_hours` and
    `estimated_parts_cost`, each at least zero."
    PRD §2.6: "**Request shape** — every required field present, every enum value
    legal, every numeric constraint honoured, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/work_order_create_missing_required_field_invalid_request
    """
    building = create_building()

    response = api.create_work_order(
        {
            "building_id": building["id"],
            "wo_type": "CORRECTIVE",
            "priority": "P3",
            "estimated_labor_hours": 2,
        },
        FM,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400

    _, meta = validate_paginated(
        api.list_work_orders(FM, params={"building_id": building["id"]})
    )
    assert meta["total_count"] == 0, "the rejected order must not have been created"


def test_work_order_illegal_priority_enum_rejected(api):
    """PRD §3.4: "A `FacilityManager` or `PlatformAdmin` raises an order by naming the
    `building_id` it belongs to, its `wo_type` (`CORRECTIVE`, `PREVENTIVE`, or
    `SOFT_SERVICE`), its `priority` (`P1`, `P2`, `P3`, or `P4`), and the two estimates
    the provisional cost is derived from: `estimated_labor_hours` and
    `estimated_parts_cost`, each at least zero."
    PRD §2.6: "**Request shape** — every required field present, every enum value
    legal, every numeric constraint honoured, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/work_order_create_invalid_enum_priority_rejected
    """
    building = create_building()

    response = api.create_work_order(
        work_order_payload(building["id"], priority="P9", estimated_labor_hours=2,
                           estimated_parts_cost=0),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400


def test_asset_condition_score_computed_from_registered_runtime(api):
    """PRD §3.1: "Start from 100. Subtract 5 points for each *complete* block of 1000
    runtime hours the asset has accumulated — 999 hours cost nothing, 1000 hours cost
    5, 1999 hours still cost 5, 2000 hours cost 10 — and subtract a further 12 points
    for every failure in `failure_count`."
    PRD §3.1: "A fresh asset enters `IN_SERVICE` with `failure_count` at 0 and
    `last_pm_at` unset, and its `condition_score` is computed immediately from the
    runtime it was registered with."

    Design: Corner/entities/asset_condition_score_computed_from_runtime_hours
    """
    building = create_building()

    response = api.create_asset(
        asset_payload(building["id"], asset_tag="AHU-01", category="HVAC",
                      criticality="STANDARD", runtime_hours=2500),
        FM,
    )
    data = validate_success(response, 201)
    assert_asset(data)

    assert data["condition_score"] == pytest.approx(90.00, abs=0.01), (
        "2500 hours is two complete 1000-hour blocks, costing 10 points"
    )
    assert data["status"] == "IN_SERVICE"
    assert data["failure_count"] == 0
    assert data["last_pm_at"] is None


def test_new_space_is_vacant_with_full_free_share(api):
    """PRD §3.1: "Every space is born empty: `allocated_share_pct` at 0,
    `free_share_pct` at 100, and `occupancy_status` at `VACANT`."
    PRD §2.4: "Almost every resource additionally carries an `updated_at` timestamp
    in the same format and an integer `version` that starts at 1 on creation and
    increments by 1 on every mutation of that resource; `updated_at` is refreshed on
    every mutation as well."

    Design: Corner/entities/space_defaults_to_vacant_with_full_free_share
    """
    building = create_building()

    response = api.create_space(
        building["id"],
        space_payload(space_code="S1", floor=3, area_sqm=150, space_type="LAB"),
        FM,
    )
    data = validate_success(response, 201)
    assert_space(data)

    assert data["allocated_share_pct"] == pytest.approx(0, abs=0.01)
    assert data["free_share_pct"] == pytest.approx(100, abs=0.01)
    assert data["occupancy_status"] == "VACANT"
    assert data["version"] == 1


def test_utility_reading_is_append_only_without_version(api):
    """PRD §2.4: "The one exception is `UtilityReading`, which is an append-only
    measurement record: a reading exposes only `id` and `created_at`, and carries
    neither `updated_at` nor `version`, because it is never modified after it is
    written."
    PRD §3.9: "Readings are immutable once written, and a building's readings can be
    listed and narrowed by `meter_type`."

    Design: Corner/entities/utility_reading_is_immutable_event_without_version
    """
    building = create_building()

    response = api.create_utility_reading(
        utility_reading_payload(
            building["id"], meter_type="WATER",
            period_start="2026-05-01T00:00:00Z", period_end="2026-05-31T23:59:59Z",
            consumption_kwh=0, cost=100.00,
        ),
        SA,
    )
    data = validate_success(response, 201)
    assert_utility_reading(data)

    assert "id" in data and "created_at" in data
    assert "version" not in data, "an append-only reading must not expose a version"
    assert "updated_at" not in data, "an append-only reading must not expose updated_at"

    readings, meta = validate_paginated(
        api.list_building_utility_readings(building["id"], SA)
    )
    assert meta["total_count"] == 1
    assert readings[0]["id"] == data["id"]


def test_work_order_list_reports_total_count_and_has_more(api):
    """PRD §2.3: "List responses set `response_type` to `"array"` and place four
    pagination fields in `meta`: `limit` and `offset` echo the effective values used,
    `total_count` reports the number of rows matching the filters before the page
    window is applied, and `has_more` is true exactly when rows remain beyond the
    current page."

    Design: Corner/entities/work_order_list_paginates_with_total_count_and_has_more
    """
    building = create_building()
    for _ in range(3):
        create_work_order(building["id"], priority="P3", wo_type="CORRECTIVE",
                          estimated_labor_hours=1, estimated_parts_cost=0)

    first_page, meta = validate_paginated(
        api.list_work_orders(
            FM, params={"building_id": building["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, "limit 2 must yield 2 rows"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second_page, meta2 = validate_paginated(
        api.list_work_orders(
            FM, params={"building_id": building["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1, "one row remains beyond the first page"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_duplicate_asset_tag_rejected_across_buildings(api):
    """PRD §3.1: "Registering one requires the `building_id` it serves, an `asset_tag`
    that is unique across the whole estate (a repeat is refused with
    `ERR_DUPLICATE_ASSET_TAG`), a `category` drawn from `HVAC`, `ELEVATOR`, `FIRE`,
    `ELECTRICAL`, or `PLUMBING`, and a `criticality` of `CRITICAL`, `STANDARD`, or
    `LOW`."

    Design: Corner/validations/duplicate_asset_tag_rejected
    """
    first = create_building(code="BLD-1")
    second = create_building(name="Tower Two", code="BLD-2")
    create_asset(first["id"], asset_tag="AHU-01", category="HVAC",
                 criticality="STANDARD")

    response = api.create_asset(
        asset_payload(second["id"], asset_tag="AHU-01", category="HVAC",
                      criticality="STANDARD"),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ASSET_TAG.value)
    assert response.status_code == 409

    _, meta = validate_paginated(api.list_building_assets(second["id"], FM))
    assert meta["total_count"] == 0, "the duplicate-tag asset must not exist"


def test_building_code_is_global_while_space_code_is_per_building(api):
    """PRD §3.1: "The `code` must be unique across the entire portfolio; a repeat is
    refused with `ERR_DUPLICATE_BUILDING_CODE`."
    PRD §3.1: "Each is created inside its parent building with a `space_code` that
    must be unique within that building — a repeat is refused with
    `ERR_DUPLICATE_SPACE_CODE`, and note that two buildings may freely use the same
    space code."

    Design: Corner/validations/duplicate_building_code_and_space_code_rejected
    """
    first = create_building(code="BLD-1")
    second = create_building(name="Tower Two", code="BLD-2")
    create_space(first["id"], space_code="S1", floor=1, area_sqm=100,
                 space_type="OFFICE")

    duplicate_building = api.create_building(
        building_payload(name="Clone", code="BLD-1", gross_area_sqm=500), FM
    )
    validate_error(duplicate_building, ApiErrorId.ERR_DUPLICATE_BUILDING_CODE.value)
    assert duplicate_building.status_code == 409

    duplicate_space = api.create_space(
        first["id"],
        space_payload(space_code="S1", floor=2, area_sqm=50, space_type="OFFICE"),
        FM,
    )
    validate_error(duplicate_space, ApiErrorId.ERR_DUPLICATE_SPACE_CODE.value)
    assert duplicate_space.status_code == 409

    reused_in_other_building = api.create_space(
        second["id"],
        space_payload(space_code="S1", floor=1, area_sqm=50, space_type="OFFICE"),
        FM,
    )
    reused = validate_success(reused_in_other_building, 201)
    assert reused["space_code"] == "S1", (
        "two buildings may freely use the same space code"
    )


def test_work_order_pm_plan_must_cover_the_named_asset(api):
    """PRD §3.4: "The plan named by `pm_plan_id` must cover the very asset named by
    `asset_id`, or the request is refused with `ERR_PM_PLAN_ASSET_MISMATCH` (HTTP 422)."

    Design: Corner/validations/pm_plan_asset_mismatch_rejected
    """
    building = create_building()
    asset_one = create_asset(building["id"], asset_tag="AHU-01", category="HVAC",
                             criticality="STANDARD")
    asset_two = create_asset(building["id"], asset_tag="AHU-02", category="HVAC",
                             criticality="STANDARD")
    plan_on_two = create_pm_plan(asset_two["id"], interval_days=30, grace_days=5,
                                 next_due_at="2026-06-01T00:00:00Z")

    response = api.create_work_order(
        work_order_payload(
            building["id"], asset_id=asset_one["id"], pm_plan_id=plan_on_two["id"],
            wo_type="PREVENTIVE", priority="P2", estimated_labor_hours=3,
            estimated_parts_cost=200.00,
        ),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_PM_PLAN_ASSET_MISMATCH.value)
    assert response.status_code == 422

    _, meta = validate_paginated(
        api.list_work_orders(FM, params={"building_id": building["id"]})
    )
    assert meta["total_count"] == 0


def test_second_failure_report_on_out_of_service_asset_rejected(api):
    """PRD §3.1: "When a `FacilityManager` or `PlatformAdmin` reports a failure, the
    asset moves `IN_SERVICE → OUT_OF_SERVICE`; reporting a failure on an asset that is
    not `IN_SERVICE` is refused with `ERR_ASSET_NOT_IN_SERVICE`."
    PRD §3.1: "The report increments `failure_count` by 1, recomputes
    `condition_score`, and recomputes the parent building's `oos_critical_asset_count`."

    Design: Corner/validations/report_failure_twice_rejected_asset_not_in_service
    """
    building = create_building()
    asset = create_asset(building["id"], asset_tag="AHU-01", category="HVAC",
                         criticality="STANDARD")
    report_failure(asset["id"])

    response = api.report_asset_failure(asset["id"], FM)
    validate_error(response, ApiErrorId.ERR_ASSET_NOT_IN_SERVICE.value)
    assert response.status_code == 409

    asset_now = validate_success(api.get_asset(asset["id"], FM))
    assert asset_now["failure_count"] == 1, "the refused report must not double-penalise"
    assert asset_now["condition_score"] == pytest.approx(88.00, abs=0.01), (
        "one failure costs 12 points off a full score of 100"
    )
    assert asset_now["status"] == "OUT_OF_SERVICE"
