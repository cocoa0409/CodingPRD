"""Well-formedness, ownership typing, FK integrity, and RBAC coverage."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_equipment,
    get_success_data,
    make_active_assignment,
    make_class,
    make_damage_report,
    make_equipment,
    make_fleet_bundle,
    make_lowboy,
    make_mechanic,
    make_project,
    make_reading,
    make_reserved_assignment,
    make_work_order,
    dispatch_work_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, make_mechanic_headers

_ADMIN = TEST_USERS["fleet_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_DISP = TEST_USERS["dispatcher_headers"]


class TestMissingRequiredField:
    def test_equipment_missing_acquisition_date_returns_invalid_request(self, api):
        """PRD section 2.7 priority 5: "Well-formedness — required fields
        present, enums valid, dates parseable, numeric ranges and structural
        constraints respected — else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/equipment_missing_required_date_returns_invalid_request
        """
        cls = make_class()
        payload = {
            "unit_tag": "UNIT-106",
            "class_id": cls["id"],
            "ownership": "OWNED",
            "acquisition_cost_cents": 9000000,
            "useful_life_months": 48,
        }
        resp = api.create_equipment(payload, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestEnumViolation:
    def test_equipment_invalid_ownership_enum_returns_invalid_request(self, api):
        """PRD section 2.7 priority 5 (enums valid -> ERR_INVALID_REQUEST) and
        section 3.1: "its `ownership` is either `OWNED` or `RENTED`".

        Design: Corner/entities/equipment_invalid_ownership_enum_returns_invalid_request
        """
        cls = make_class()
        payload = {
            "unit_tag": "UNIT-107",
            "class_id": cls["id"],
            "ownership": "LEASED",
            "acquisition_cost_cents": 9000000,
            "acquisition_date": "2026-02-01",
            "useful_life_months": 48,
        }
        resp = api.create_equipment(payload, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestReadingDeltaRange:
    def test_reading_24000_accepted_24001_rejected(self, api):
        """PRD section 3.3: "`engine_hours_delta_milli` ... between 0 and 24000
        milli-hours, since a day holds no more than 24 hours".

        Design: Corner/entities/reading_delta_range_boundary_24000_ok_24001_rejected
        """
        cls = make_class(service_interval_hours=10000)
        equip = make_equipment(cls["id"])
        ok = api.create_reading(
            equip["id"],
            {"recorded_date": "2026-08-03", "engine_hours_delta_milli": 24000,
             "fuel_used_milliliters": 1000},
            _ADMIN,
        )
        assert ok.status_code == 201
        ok_data = validate_success(ok, expected_status=201)
        assert ok_data["status"] == "ACCEPTED"

        bad = api.create_reading(
            equip["id"],
            {"recorded_date": "2026-08-04", "engine_hours_delta_milli": 24001,
             "fuel_used_milliliters": 1000},
            _ADMIN,
        )
        validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST)
        assert bad.status_code == 400


class TestAssignmentWindowShape:
    def test_assignment_end_not_after_start_returns_invalid_request(self, api):
        """PRD section 3.2: "`end_date` must fall strictly after `start_date`".

        Design: Corner/entities/assignment_end_not_after_start_returns_invalid_request
        """
        cls, project, equip = make_fleet_bundle()
        payload = {
            "equipment_id": equip["id"],
            "project_id": project["id"],
            "start_date": "2026-08-05",
            "end_date": "2026-08-05",
            "expected_equipment_version": equip["version"],
        }
        resp = api.create_assignment(payload, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        equip_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert equip_after["availability_status"] == "IDLE"


class TestTransportStructural:
    def test_same_origin_destination_rejected(self, api):
        """PRD section 3.5: "the destination must differ from the origin".

        Design: Corner/entities/transport_structural_constraints_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, pa, equip = make_fleet_bundle()
        pb = make_project(project_code="PRJ-B")
        lb = make_lowboy()
        asg = make_active_assignment(equip, pa, start_date="2026-08-03", end_date="2026-08-06")
        set_clock("2026-08-04T09:00:00Z")
        from test_helpers import close_assignment
        close_assignment(asg["id"])

        resp = api.create_transport_job(
            {
                "equipment_id": equip["id"],
                "from_project_id": pa["id"],
                "to_project_id": pa["id"],
                "lowboy_id": lb["id"],
                "depart_at": "2026-08-12T08:00:00Z",
                "arrive_at": "2026-08-12T12:00:00Z",
            },
            _DISP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_arrive_before_depart_rejected(self, api):
        """PRD section 3.5: "`arrive_at` must be strictly after `depart_at`".

        Design: Corner/entities/transport_structural_constraints_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, pa, equip = make_fleet_bundle()
        pb = make_project(project_code="PRJ-B")
        lb = make_lowboy()
        asg = make_active_assignment(equip, pa, start_date="2026-08-03", end_date="2026-08-06")
        set_clock("2026-08-04T09:00:00Z")
        from test_helpers import close_assignment
        close_assignment(asg["id"])

        resp = api.create_transport_job(
            {
                "equipment_id": equip["id"],
                "from_project_id": pa["id"],
                "to_project_id": pb["id"],
                "lowboy_id": lb["id"],
                "depart_at": "2026-08-12T12:00:00Z",
                "arrive_at": "2026-08-12T08:00:00Z",
            },
            _DISP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        equip_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert equip_after["availability_status"] == "IDLE"


class TestDamageLineItemsCardinality:
    def test_empty_line_items_rejected(self, api):
        """PRD section 3.8: "`line_items` — between 1 and 20 repair lines".

        Design: Corner/entities/damage_line_items_cardinality_bounds
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")

        resp = api.create_damage_report(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "description": "empty items",
                "abuse_flag": False,
                "line_items": [],
            },
            _ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_twentyone_line_items_rejected(self, api):
        """PRD section 3.8: "`line_items` — between 1 and 20 repair lines".

        Design: Corner/entities/damage_line_items_cardinality_bounds
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        items = [{"description": f"i{k}", "amount_cents": 1} for k in range(1, 22)]
        resp = api.create_damage_report(
            {
                "equipment_id": equip["id"],
                "project_id": project["id"],
                "description": "too many",
                "abuse_flag": False,
                "line_items": items,
            },
            _ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestWorkOrderDefaults:
    def test_notes_default_empty_string_when_omitted(self, api):
        """PRD section 3.4: "A `FleetAdmin` can create a `REPAIR` work order by
        hand for any unit, supplying the `equipment_id`, the `kind`, and
        optional `notes` (which default to an empty string)".

        Design: Corner/entities/work_order_notes_default_and_damage_dispute_note_default
        """
        cls, project, equip = make_fleet_bundle()
        resp = api.create_work_order({"equipment_id": equip["id"], "kind": "REPAIR"}, _ADMIN)
        wo = validate_success(resp, expected_status=201)
        assert wo["notes"] == ""


class TestAssignmentChargeImmutability:
    def test_charge_row_has_no_version_or_updated_at(self, api):
        """PRD section 2.4: "An `AssignmentCharge` row and a `TelematicsReading`
        each carry only `id` and `created_at` — both `updated_at` and `version`
        are absent on those two resources".

        Design: Corner/entities/assignment_charge_rows_are_immutable_without_version
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        set_clock("2026-08-04T09:00:00Z")
        from test_helpers import close_assignment
        close_assignment(asg["id"])

        rows, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        assert len(rows) == 1
        row = rows[0]
        assert "id" in row and "created_at" in row
        assert "version" not in row
        assert "updated_at" not in row
        assert row["assignment_id"] == asg["id"]
        assert row["project_id"] == project["id"]
        for f in ("allocated_cents", "own_cost_cents", "rent_cost_cents", "cheaper_variant"):
            assert f in row


class TestFkIntegrity:
    def test_assignment_create_with_bogus_project_fk_returns_ref_not_found(self, api):
        """PRD section 2.7 priority 4: "Body references — every foreign-key id
        supplied in the body exists — else `ERR_REF_NOT_FOUND`."

        Design: Corner/entities/create_assignment_with_bogus_project_fk_returns_ref_not_found
        """
        cls = make_class()
        equip = make_equipment(cls["id"])
        resp = api.create_assignment(
            {
                "equipment_id": equip["id"],
                "project_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                "start_date": "2026-08-03",
                "end_date": "2026-08-10",
                "expected_equipment_version": equip["version"],
            },
            _ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REF_NOT_FOUND)
        assert resp.status_code == 422
        equip_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert equip_after["availability_status"] == "IDLE"


class TestOwnershipFieldMismatch:
    def test_owned_with_zero_cost_rejected(self, api):
        """PRD section 3.1: "an `OWNED` unit must arrive with
        `acquisition_cost_cents` greater than zero, an `acquisition_date`, and
        a `useful_life_months` greater than zero, while a `RENTED` unit must
        have `acquisition_cost_cents` exactly zero — any other combination is
        rejected with `ERR_OWNERSHIP_FIELD_MISMATCH`."

        Design: Corner/entities/ownership_field_constraints_enforced_both_directions
        """
        cls = make_class()
        resp = api.create_equipment(
            {
                "unit_tag": "UNIT-116A",
                "class_id": cls["id"],
                "ownership": "OWNED",
                "acquisition_cost_cents": 0,
                "acquisition_date": "2026-02-01",
                "useful_life_months": 48,
            },
            _ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_FIELD_MISMATCH)
        assert resp.status_code == 422

    def test_rented_with_positive_cost_rejected(self, api):
        """PRD section 3.1: "a `RENTED` unit must have `acquisition_cost_cents`
        exactly zero — any other combination is rejected with
        `ERR_OWNERSHIP_FIELD_MISMATCH`."

        Design: Corner/entities/ownership_field_constraints_enforced_both_directions
        """
        cls = make_class()
        resp = api.create_equipment(
            {
                "unit_tag": "UNIT-116B",
                "class_id": cls["id"],
                "ownership": "RENTED",
                "acquisition_cost_cents": 500000,
                "acquisition_date": "2026-02-01",
                "useful_life_months": 48,
            },
            _ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_FIELD_MISMATCH)
        assert resp.status_code == 422


class TestLowboyCapacity:
    def test_capacity_units_must_be_one(self, api):
        """PRD section 3.5: "in this version of the system every trailer is
        single-unit, so `capacity_units` must be 1".

        Design: Corner/entities/lowboy_capacity_units_must_be_one
        """
        resp = api.create_lowboy({"lowboy_code": "LB-200", "capacity_units": 2}, _DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestUnauthenticated:
    def test_unknown_role_header_returns_unauthenticated(self, api):
        """PRD section 2.1: "A request whose `X-User-Role` header is absent, or
        whose value does not match one of those four declared role names, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unknown_role_header_returns_unauthenticated
        """
        from test_helpers import build_user_headers
        resp = api.list_equipment(build_user_headers("some-user", "Anonymous"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestRbac:
    def test_mechanic_cannot_create_project(self, api):
        """PRD section 2.1: "A request whose role is valid but not among the
        roles permitted for the target endpoint (see §4) is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD section 4 gives POST
        /fleet/projects to FleetAdmin only.

        Design: Corner/rbac/mechanic_cannot_create_project_unauthorized
        """
        proj = make_project(project_code="PRJ-600")
        mech = make_mechanic(proj["id"], mechanic_code="MECH-600", name="Mac 600")
        resp = api.create_project(
            {"project_code": "PRJ-601", "name": "Sneaky", "equipment_budget_cents": 1},
            make_mechanic_headers(mech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        projects, meta = validate_paginated(api.list_projects(_ADMIN))
        codes = [p["project_code"] for p in projects]
        assert "PRJ-601" not in codes

    def test_dispatcher_cannot_ingest_reading(self, api):
        """PRD section 2.1: "A request whose role is valid but not among the
        roles permitted for the target endpoint (see §4) is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD section 4: POST
        /fleet/equipment/{id}/readings is FleetAdmin-only.

        Design: Corner/rbac/dispatcher_cannot_ingest_reading_unauthorized
        """
        cls = make_class()
        equip = make_equipment(cls["id"])
        resp = api.create_reading(
            equip["id"],
            {"recorded_date": "2026-08-03", "engine_hours_delta_milli": 1000,
             "fuel_used_milliliters": 500},
            _DISP,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        equip_after = validate_success(api.get_equipment(equip["id"], _ADMIN))
        assert equip_after["engine_hours_milli"] == 0

    def test_project_manager_cannot_assess_damage(self, api):
        """PRD section 2.1: "A request whose role is valid but not among the
        roles permitted for the target endpoint (see §4) is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD section 2.1 also states
        "`ProjectManager` is a project-side role that reads fleet state broadly
        and disputes assessed damage charges" — assess itself is
        FleetAdmin-only per PRD section 4.

        Design: Corner/rbac/project_manager_cannot_assess_damage_unauthorized
        """
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d = make_damage_report(equip["id"], project["id"],
                               description="crack",
                               line_items=[{"description": "x", "amount_cents": 1000}])
        resp = api.assess_damage_report(d["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        d_after = validate_success(api.get_damage_report(d["id"], _ADMIN))
        assert d_after["status"] == "FILED"

    def test_fleet_admin_cannot_start_work_order(self, api):
        """PRD section 2.1: "A request whose role is valid but not among the
        roles permitted for the target endpoint (see §4) is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD section 4 lists POST
        /fleet/work-orders/{id}/start with authorized role "Mechanic" only.

        Design: Corner/rbac/fleet_admin_cannot_start_work_order_unauthorized
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-603")
        wo = make_work_order(equip["id"], kind="REPAIR")
        dispatch_work_order(wo["id"], mech["id"])
        resp = api.start_work_order(wo["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        wo_after = validate_success(api.get_work_order(wo["id"], _ADMIN))
        assert wo_after["status"] == "DISPATCHED"

    def test_all_roles_can_read_equipment(self, api):
        """PRD section 2.1: "`FleetAdmin` is the division administrator ...";
        "`ProjectManager` is a project-side role that reads fleet state
        broadly"; "`Dispatcher` owns lowboy trailers and all haul scheduling";
        and Mechanic reads fleet state via the shared GET endpoints listed in
        PRD section 4 for "FleetAdmin, ProjectManager, Mechanic, Dispatcher".

        Design: Corner/rbac/all_roles_can_read_shared_get_endpoints
        """
        cls, project, equip = make_fleet_bundle()
        mech = make_mechanic(project["id"], mechanic_code="MECH-604")

        r1 = validate_success(api.get_equipment(equip["id"], _ADMIN))
        r2 = validate_success(api.get_equipment(equip["id"], _PM))
        r3 = validate_success(api.get_equipment(equip["id"], _DISP))
        r4 = validate_success(api.get_equipment(equip["id"], make_mechanic_headers(mech["id"])))
        for r in (r1, r2, r3, r4):
            assert r["id"] == equip["id"]
            assert r["unit_tag"] == equip["unit_tag"]


class TestErrorEnvelopeOnForbidden:
    def test_error_envelope_shape_on_403(self, api):
        """PRD section 2.2 Standard Error Response Format: "The `meta` object
        for error responses contains only `api_request_id` and
        `api_request_timestamp`"; body has response_type == "error" and
        data.error_id / data.message.

        Design: Corner/errors/error_envelope_shape_on_unauthorized
        """
        proj = make_project(project_code="PRJ-900")
        mech = make_mechanic(proj["id"], mechanic_code="MECH-900")
        resp = api.create_project(
            {"project_code": "PRJ-901", "name": "Denied", "equipment_budget_cents": 1},
            make_mechanic_headers(mech["id"]),
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body.get("response_type") == "error"
        assert body.get("data", {}).get("error_id") == "ERR_UNAUTHORIZED"
        assert isinstance(body.get("data", {}).get("message"), str) and body["data"]["message"]
        assert body.get("meta", {}).get("api_request_id")
        assert body.get("meta", {}).get("api_request_timestamp")
