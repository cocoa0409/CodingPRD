"""Creation claims, listing/pagination envelope, and sub-resource reverse reachability."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_assignment,
    assert_assignment_charge,
    assert_equipment,
    assert_equipment_class,
    assert_lowboy,
    assert_mechanic,
    assert_project,
    close_assignment,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_active_assignment,
    make_class,
    make_equipment,
    make_fleet_bundle,
    make_lowboy,
    make_mechanic,
    make_project,
    make_reading,
    make_reserved_assignment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, make_mechanic_headers


_ADMIN = TEST_USERS["fleet_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_DISP = TEST_USERS["dispatcher_headers"]


class TestEquipmentClassCreation:
    def test_class_creation_persists_fields_and_returns_201(self, api):
        """PRD section 4: "POST /fleet/equipment-classes | Create an equipment
        class (rates, service interval, thresholds)" returns 201 Created per the
        section preamble ("Operations that create a new resource ... return
        `201 Created`"). PRD section 2.4: "All top-level resources ... carry a
        common set of system-managed properties" including id/created_at/
        updated_at/version.

        Design: Corner/entities/equipment_class_creation_returns_201_and_persists_fields
        """
        resp = api.create_equipment_class(
            {
                "class_code": "EXC-100",
                "daily_rate_cents": 15000,
                "external_daily_rate_cents": 18000,
                "weekend_multiplier_bp": 5000,
                "idle_day_multiplier_bp": 2500,
                "service_interval_hours": 250,
                "idle_alert_utilization_bp": 3000,
                "expected_life_hours": 12000,
                "salvage_value_cents": 800000,
            },
            _ADMIN,
        )
        assert resp.status_code == 201
        data = validate_success(resp, expected_status=201)
        assert_equipment_class(data)
        assert data["class_code"] == "EXC-100"
        assert data["daily_rate_cents"] == 15000
        assert data["weekend_multiplier_bp"] == 5000
        assert data["service_interval_hours"] == 250
        assert data["version"] == 1

    def test_class_get_after_create_echoes_inputs(self, api):
        """PRD section 2.2: "The `data` field contains the resource object or an
        array of resource objects"; PRD section 4 gives GET
        /fleet/equipment-classes/{id} returning an EquipmentClass.

        Design: Corner/entities/equipment_class_creation_returns_201_and_persists_fields
        """
        cls = make_class(class_code="EXC-100")
        got = validate_success(api.get_equipment_class(cls["id"], _ADMIN))
        assert_equipment_class(got)
        assert got["id"] == cls["id"]
        assert got["class_code"] == "EXC-100"
        assert got["daily_rate_cents"] == cls["daily_rate_cents"]


class TestEquipmentCreation:
    def test_equipment_born_idle_and_service_ok(self, api):
        """PRD section 3.1: "Every unit is born `IDLE` and `SERVICE_OK` with
        `engine_hours_milli` at zero and `hours_at_last_service_milli` at zero,
        so `hours_since_service_milli` — always the meter minus the at-last-
        service bookmark — starts at zero as well."

        Design: Corner/entities/equipment_creation_sets_initial_parallel_dimensions
        """
        cls = make_class()
        equip = make_equipment(cls["id"], unit_tag="UNIT-100")
        assert_equipment(equip)
        assert equip["availability_status"] == "IDLE"
        assert equip["maintenance_status"] == "SERVICE_OK"
        assert equip["engine_hours_milli"] == 0
        assert equip["hours_at_last_service_milli"] == 0

    def test_equipment_current_project_and_site_null_until_assignment(self, api):
        """PRD section 3.1: "A unit's `current_project_id` names the project
        renting it while an active assignment exists and is null otherwise".

        Design: Corner/entities/equipment_creation_sets_initial_parallel_dimensions
        """
        cls = make_class()
        equip = make_equipment(cls["id"], unit_tag="UNIT-100")
        assert equip["current_project_id"] is None
        assert equip["disposed_at"] is None


class TestProjectCreation:
    def test_project_opens_with_zero_ledger_and_count(self, api):
        """PRD section 3.1: "A project opens with `status` equal to `OPEN`,
        `billed_total_cents` at zero, and `active_assignment_count` at zero."

        Design: Corner/entities/project_creation_sets_initial_derived_fields
        """
        proj = make_project(project_code="PRJ-INIT", name="Init", equipment_budget_cents=500000)
        assert_project(proj)
        assert proj["status"] == "OPEN"
        assert proj["billed_total_cents"] == 0
        assert proj["active_assignment_count"] == 0
        assert proj["version"] == 1


class TestAssignmentCreation:
    def test_assignment_created_reserved_with_null_close_fields(self, api):
        """PRD section 3.2: "A successful reservation creates the assignment in
        `RESERVED`". PRD section 3.6 pins `closed_at` and `close_reason` as set
        only at close; section 3.2 pins `activated_at` as set at activation.

        Design: Corner/entities/assignment_creation_reserved_with_null_computed_fields
        """
        cls, project, equip = make_fleet_bundle()
        asg = make_reserved_assignment(equip, project)
        assert_assignment(asg)
        assert asg["status"] == "RESERVED"
        assert asg["activated_at"] is None
        assert asg["closed_at"] is None
        assert asg["close_reason"] is None


class TestMechanicAndLowboyCreation:
    def test_mechanic_starts_available_count_zero(self, api):
        """PRD section 3.4: "each mechanic is created with a unique
        `mechanic_code` ... and starts `AVAILABLE` with an
        `active_work_order_count` of zero."

        Design: Corner/entities/mechanic_and_lowboy_creation_initial_states
        """
        proj = make_project()
        mech = make_mechanic(proj["id"], mechanic_code="MECH-100", name="Mac Hundred")
        assert_mechanic(mech)
        assert mech["status"] == "AVAILABLE"
        assert mech["active_work_order_count"] == 0

    def test_lowboy_created_available(self, api):
        """PRD section 3.5: "A trailer is created `AVAILABLE` and can be taken
        `OUT_OF_SERVICE` and returned to `AVAILABLE` on demand".

        Design: Corner/entities/mechanic_and_lowboy_creation_initial_states
        """
        lb = make_lowboy(lowboy_code="LB-100", capacity_units=1)
        assert_lowboy(lb)
        assert lb["status"] == "AVAILABLE"


class TestPaginationEnvelope:
    def test_pagination_limit_offset_total_count_has_more(self, api):
        """PRD section 2.3: "The `limit` parameter sets the maximum number of
        items returned: it defaults to 10 ... The `offset` parameter sets how
        many items to skip and defaults to 0. ... List responses carry `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object."

        Design: Corner/endpoints/list_pagination_limit_offset_total_count_has_more
        """
        make_class(class_code="EC-A")
        make_class(class_code="EC-B")
        make_class(class_code="EC-C")

        data1, meta1 = validate_paginated(
            api.list_equipment_classes(_ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_equipment_classes(_ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_pagination_default_limit_10_returns_all(self, api):
        """PRD section 2.3: "The `limit` parameter sets the maximum number of
        items returned: it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter sets how many items to skip and
        defaults to 0."

        Design: Corner/endpoints/list_pagination_limit_offset_total_count_has_more
        """
        make_class(class_code="EC-A")
        make_class(class_code="EC-B")
        make_class(class_code="EC-C")
        data, meta = validate_paginated(api.list_equipment_classes(_ADMIN))
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestEquipmentListFilter:
    def test_filter_by_availability_status_narrows_results(self, api):
        """PRD section 2.5: "The first, `availability_status`, answers \"where
        can this unit go?\" and takes the values `IDLE`, `RESERVED`, `ON_RENT`,
        `IN_TRANSIT`, `DOWN`, and `DISPOSED`". Filtering the equipment list by
        that field must narrow the result set to the matching state.

        Design: Corner/endpoints/equipment_list_filter_by_availability_status
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip_a = make_fleet_bundle()
        equip_b = make_equipment(cls["id"], unit_tag="UNIT-B")
        asg = make_reserved_assignment(equip_b, project)
        validate_success(api.activate_assignment(asg["id"], _ADMIN))

        data_on_rent, meta_on_rent = validate_paginated(
            api.list_equipment(_ADMIN, params={"availability_status": "ON_RENT"})
        )
        assert len(data_on_rent) == 1
        assert data_on_rent[0]["id"] == equip_b["id"]

        data_idle, meta_idle = validate_paginated(
            api.list_equipment(_ADMIN, params={"availability_status": "IDLE"})
        )
        assert len(data_idle) == 1
        assert data_idle[0]["id"] == equip_a["id"]


class TestSubresourceListings:
    def test_equipment_readings_project_assignments_and_charges_visible(self, api):
        """PRD section 3.6: "a single immutable `AssignmentCharge` row is
        created carrying the `assignment_id`, the denormalized `project_id`,
        and the four computed figures — `allocated_cents`, `own_cost_cents`,
        `rent_cost_cents`, and `cheaper_variant` — and `allocated_cents` posts
        to the project's `billed_total_cents`."

        Design: Corner/endpoints/subresource_reverse_reachability_listings
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(service_interval_hours=250)
        project = make_project()
        equip = make_equipment(cls["id"])
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-05")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        set_clock("2026-08-05T09:00:00Z")
        close_assignment(asg["id"])

        readings, _ = validate_paginated(api.list_equipment_readings(equip["id"], _ADMIN))
        assert len(readings) == 2

        assignments, _ = validate_paginated(api.list_project_assignments(project["id"], _ADMIN))
        assert len(assignments) == 1
        assert assignments[0]["id"] == asg["id"]
        assert assignments[0]["status"] == "CLOSED"

        proj_charges, _ = validate_paginated(api.list_project_charges(project["id"], _ADMIN))
        assert len(proj_charges) == 1
        assert_assignment_charge(proj_charges[0])
        assert proj_charges[0]["allocated_cents"] == 20000
        assert proj_charges[0]["assignment_id"] == asg["id"]

        asg_charges, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        assert len(asg_charges) == 1
        assert asg_charges[0]["id"] == proj_charges[0]["id"]


class TestClock:
    def test_clock_set_echoes_current_utc(self, api):
        """PRD section 2.10: "A `FleetAdmin` advances it by supplying a
        `to_iso8601` instant; the response echoes the new `current_utc`."

        Design: Corner/endpoints/clock_set_endpoint_exposed_and_default
        """
        resp = api.set_clock({"to_iso8601": "2026-09-15T12:30:00Z"}, _ADMIN)
        data = validate_success(resp)
        assert data["current_utc"] == "2026-09-15T12:30:00Z"


class TestGetNotFound:
    def test_get_nonexistent_equipment_returns_404_not_found(self, api):
        """PRD section 2.7 priority 3: "Path existence — every path-template
        resource exists, checked left to right — else `ERR_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_equipment_returns_not_found
        """
        resp = api.get_equipment("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", _ADMIN)
        data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404
        assert data.get("message")

    def test_error_envelope_shape_on_404(self, api):
        """PRD section 2.2: "All error API responses (4xx status codes) follow
        this standard envelope format"; "The `meta` object for error responses
        contains only `api_request_id` and `api_request_timestamp`"; "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/entities/get_nonexistent_equipment_returns_not_found
        """
        resp = api.get_equipment(NON_EXISTENT_UUID, _ADMIN)
        body = resp.json()
        assert resp.status_code == 404
        assert body.get("response_type") == "error"
        assert body.get("data", {}).get("error_id") == "ERR_NOT_FOUND"
        assert isinstance(body.get("data", {}).get("message"), str)
        assert body.get("meta", {}).get("api_request_id")
        assert body.get("meta", {}).get("api_request_timestamp")
