"""Portfolio register and task library: creation defaults, computed fields,
type constraints, and template soft-delete filtering."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_property, create_building, create_unit, create_asset,
    create_template, set_clock,
    create_property_payload, create_asset_payload, create_plan_payload,
)

TEST_PM = TEST_USERS["property_manager_headers"]


class TestPropertyAndPlanCreationDefaults:
    def test_property_created_active(self, api):
        """PRD §3.1: "New properties are `ACTIVE`."

        Design: Corner/entities/property_creation_defaults_and_computed_init
        """
        resp = api.create_property(create_property_payload(), TEST_PM)
        prop = validate_success(resp, expected_status=201)
        assert prop["status"] == "ACTIVE", f"expected ACTIVE, got {prop['status']}"
        assert prop["property_code"] is not None

    def test_plan_created_draft_with_zero_aggregates(self, api):
        """PRD §3.2: "a new plan is `DRAFT` with `planned_labor_hours`,
        `actual_labor_minutes`, `committed_cents`, and `spent_cents` all zero."

        Design: Corner/entities/property_creation_defaults_and_computed_init
        """
        prop = create_property()
        resp = api.create_plan(create_plan_payload(prop["id"], plan_year=2027, budget_cents=500000), TEST_PM)
        plan = validate_success(resp, expected_status=201)
        assert plan["status"] == "DRAFT"
        assert plan["planned_labor_hours"] == 0
        assert plan["actual_labor_minutes"] == 0
        assert plan["committed_cents"] == 0
        assert plan["spent_cents"] == 0
        assert isinstance(plan["version"], int)


class TestAssetComputedAgeAndWarranty:
    def _setup_asset(self):
        prop = create_property()
        building = create_building(prop["id"])
        unit = create_unit(building["id"], occupancy_status="OCCUPIED")
        asset = create_asset(
            unit["id"],
            installed_on="2020-08-15T00:00:00Z",
            warranty_months=72,
            expected_life_months=120,
            replacement_cost_cents=400000,
        )
        return asset

    def test_age_months_floors_by_day_of_month_and_warranty_active(self, api):
        """PRD §3.1: "a whole month counts only once the clock date's day-of-month
        has reached the day-of-month of `installed_on`; before that day in the
        current month, one fewer month is counted." At the default clock
        2026-08-01 an asset installed 2020-08-15 is 71 months old and, with
        warranty_months=72, still under warranty.

        Design: Corner/entities/asset_computed_age_and_warranty_fields
        """
        asset = self._setup_asset()
        data = validate_success(api.get_asset(asset["id"], TEST_PM))
        assert data["age_months"] == 71, f"expected 71 whole months, got {data['age_months']}"
        assert data["warranty_active"] is True

    def test_warranty_expires_on_strict_less_than_at_boundary(self, api):
        """PRD §3.1: "`warranty_active` is true only while `age_months` is strictly
        less than `warranty_months`". At clock 2026-08-15 the same asset is
        exactly 72 months old, equal to warranty_months=72, so coverage has ended.

        Design: Corner/entities/asset_computed_age_and_warranty_fields
        """
        asset = self._setup_asset()
        set_clock("2026-08-15T00:00:00Z")
        data = validate_success(api.get_asset(asset["id"], TEST_PM))
        assert data["age_months"] == 72, f"expected 72 whole months, got {data['age_months']}"
        assert data["warranty_active"] is False


class TestInvalidEnumRejected:
    def test_component_type_outside_declared_set_rejected(self, api):
        """PRD §2.6 (stage 15): "Required fields present, enum values within their
        declared sets, integers positive or non-negative where constrained,
        `window_end` strictly after `window_start`, forecast horizon within range,
        and `property_code` unique (`ERR_INVALID_REQUEST`, HTTP 400)."
        PRD §3.1: "a `component_type` of `HVAC`, `WATER_HEATER`, or `APPLIANCE`".

        Design: Corner/entities/invalid_enum_rejected
        """
        prop = create_property()
        building = create_building(prop["id"])
        unit = create_unit(building["id"], occupancy_status="OCCUPIED")
        payload = create_asset_payload(unit["id"], component_type="ELEVATOR")
        resp = api.create_asset(payload, TEST_PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTemplateRetireSoftDelete:
    def test_retired_template_excluded_from_default_listing(self, api):
        """PRD §3.2: "Retiring a template is a soft delete: `retired_at` is stamped
        with the current logical clock, the template disappears from the default
        library listing (the listing accepts an optional `component_type` filter,
        and retired rows surface only when `include_retired` is true)".

        Design: Corner/endpoints/template_retire_soft_delete_filtering
        """
        prop = create_property()
        template = create_template(prop["id"])
        retired = validate_success(api.retire_template(template["id"], TEST_PM))
        assert retired["retired_at"] is not None, "retire must stamp retired_at"

        data, meta = validate_paginated(api.list_templates(prop["id"], TEST_PM))
        assert data == [], f"default listing must exclude retired templates, got {data}"
        assert meta["total_count"] == 0

        data_all, meta_all = validate_paginated(
            api.list_templates(prop["id"], TEST_PM, params={"include_retired": "true"})
        )
        assert len(data_all) == 1, f"include_retired=true must surface the retired row, got {data_all}"
        assert data_all[0]["id"] == template["id"]
        assert data_all[0]["retired_at"] is not None
