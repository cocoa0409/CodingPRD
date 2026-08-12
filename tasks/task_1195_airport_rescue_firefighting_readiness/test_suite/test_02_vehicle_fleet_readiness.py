"""Vehicle fleet, readiness measurement, equipment-supported index."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_readiness_check_payload,
    create_vehicle_payload,
    get_success_data,
    get_vehicle,
    record_readiness_check,
    set_clock,
    setup_compliant_index_c_airport,
    setup_profile_only,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]


class TestVehicleLatestReadiness:
    def test_vehicle_latest_readiness_none_fail_pass_recency(self, api):
        """PRD §3.2: "The vehicle's `latest_readiness_result` updates to this
        result, with ties in `checked_at` broken by `created_at` descending so
        the most recently created check wins."

        Design: Corner/entities/ent_vehicle_latest_readiness_none_fail_pass_recency
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        resp = api.create_vehicle(
            create_vehicle_payload(call_sign="RED-1",
                                   water_capacity_gal=2000,
                                   dry_chem_capacity_lb=500),
            AC,
        )
        vehicle = validate_success(resp, expected_status=201)
        assert vehicle["latest_readiness_result"] == "NONE"

        rc_fail = validate_success(
            api.create_readiness_check(
                create_readiness_check_payload(
                    vehicle["id"], water_available_gal=2000,
                    dry_chem_available_lb=500, discharge_system_ok=False,
                ),
                AC,
            ),
            expected_status=201,
        )
        assert rc_fail["result"] == "FAIL"
        v = get_vehicle(vehicle["id"])
        assert v["latest_readiness_result"] == "FAIL"

        set_clock("2026-05-02T00:00:00Z")
        rc_pass = validate_success(
            api.create_readiness_check(
                create_readiness_check_payload(
                    vehicle["id"], water_available_gal=2000,
                    dry_chem_available_lb=500, discharge_system_ok=True,
                ),
                AC,
            ),
            expected_status=201,
        )
        assert rc_pass["result"] == "PASS"
        v = get_vehicle(vehicle["id"])
        assert v["latest_readiness_result"] == "PASS"


class TestVehicleSystemFieldsIgnored:
    def test_vehicle_system_fields_input_ignored(self, api):
        """PRD §2.4: "Every persisted entity carries an `id` (a server-minted
        UUID with no type prefix), a `created_at` timestamp, an `updated_at`
        timestamp, and an integer `version`."

        Design: Corner/entities/ent_vehicle_system_fields_input_ignored
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        resp = api.create_vehicle(
            {
                "call_sign": "RED-1",
                "water_capacity_gal": 2000,
                "dry_chem_capacity_lb": 500,
                "id": "11111111-1111-1111-1111-111111111111",
                "created_at": "1999-01-01T00:00:00Z",
                "version": 99,
            },
            AC,
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"] != "11111111-1111-1111-1111-111111111111"
        assert data["created_at"] == "2026-05-01T00:00:00.000Z"
        assert data["version"] == 1


class TestVehicleRequiredField:
    def test_vehicle_missing_call_sign_returns_validation_failed(self, api):
        """PRD §2.10: "(3.5) required body-field presence and types
        (`ERR_VALIDATION_FAILED`)."

        Design: Corner/entities/ent_vehicle_missing_required_call_sign_returns_invalid_request
        """
        setup_profile_only()
        resp = api.create_vehicle(
            {"water_capacity_gal": 2000, "dry_chem_capacity_lb": 500},
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)
        data, meta = validate_paginated(api.list_vehicles(AC))
        assert meta["total_count"] == 0


class TestMeasuredExceedsCapacity:
    def test_measured_exceeds_capacity_rejected(self, api):
        """PRD §3.2: "Measured quantities must be non-negative and may not
        exceed the vehicle's rated `water_capacity_gal` and
        `dry_chem_capacity_lb` — a measurement above rated capacity is
        rejected with `ERR_MEASURED_EXCEEDS_CAPACITY`."

        Design: Corner/validations/val_measured_exceeds_capacity_rejected
        """
        setup_profile_only()
        v = validate_success(
            api.create_vehicle(
                create_vehicle_payload(call_sign="RED-1",
                                       water_capacity_gal=2000,
                                       dry_chem_capacity_lb=500),
                AC,
            ),
            expected_status=201,
        )
        resp = api.create_readiness_check(
            create_readiness_check_payload(
                v["id"], water_available_gal=2500,
                dry_chem_available_lb=500, discharge_system_ok=True,
            ),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_MEASURED_EXCEEDS_CAPACITY)


class TestReadinessBodyFkMustExist:
    def test_readiness_check_unknown_vehicle_returns_404(self, api):
        """PRD §2.10: "(3) path-id existence, then body foreign-key existence,
        evaluated left-to-right (`ERR_<RESOURCE>_NOT_FOUND`)."

        Design: Corner/validations/val_body_fk_must_exist
        """
        setup_profile_only()
        resp = api.create_readiness_check(
            create_readiness_check_payload(
                NON_EXISTENT_UUID, water_available_gal=100,
                dry_chem_available_lb=100, discharge_system_ok=True,
            ),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND)


class TestSubResourceListScoping:
    def test_subresource_lists_are_scoped_to_parent(self, api):
        """PRD §2.9: "Endpoints that nest one resource under another (for
        example, a vehicle's readiness checks, an incident's reports, an
        aircraft's incidents) validate path identifiers from left to right."

        Design: Corner/endpoints/ep_filtered_subresource_lists_are_scoped
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        v1 = validate_success(
            api.create_vehicle(
                create_vehicle_payload(call_sign="RED-1",
                                       water_capacity_gal=2000,
                                       dry_chem_capacity_lb=500),
                AC,
            ),
            expected_status=201,
        )
        v2 = validate_success(
            api.create_vehicle(
                create_vehicle_payload(call_sign="RED-2",
                                       water_capacity_gal=2000,
                                       dry_chem_capacity_lb=500),
                AC,
            ),
            expected_status=201,
        )
        record_readiness_check(v1["id"], 2000, 500, True)
        record_readiness_check(v2["id"], 1500, 500, True)
        ff1 = validate_success(
            api.create_firefighter(
                {"employee_no": "FF-101", "full_name": "Ann Lee"}, AC,
            ),
            expected_status=201,
        )
        ff2 = validate_success(
            api.create_firefighter(
                {"employee_no": "FF-102", "full_name": "Ben Kim"}, AC,
            ),
            expected_status=201,
        )
        api.create_training_record(
            {
                "firefighter_id": ff1["id"],
                "completed_on": "2026-04-15",
                "drill_type": "AIRCRAFT",
                "result": "PASS",
            },
            AC,
        )
        api.create_training_record(
            {
                "firefighter_id": ff2["id"],
                "completed_on": "2026-04-10",
                "drill_type": "STRUCTURAL",
                "result": "PASS",
            },
            AC,
        )

        data, meta = validate_paginated(
            api.list_vehicle_readiness_checks(v1["id"], AC)
        )
        assert meta["total_count"] == 1
        assert data[0]["water_available_gal"] == 2000

        data, meta = validate_paginated(
            api.list_vehicle_readiness_checks(v2["id"], AC)
        )
        assert meta["total_count"] == 1
        assert data[0]["water_available_gal"] == 1500

        data, meta = validate_paginated(
            api.list_firefighter_training_records(ff1["id"], AC)
        )
        assert meta["total_count"] == 1
        assert data[0]["completed_on"] == "2026-04-15"


class TestReadinessComputedViewAllFields:
    def test_readiness_view_full_field_values(self, api):
        """PRD §3.2: "For audit comparison the readiness detail view also
        exposes a rated-basis variant named `rated_basis_supported_index`...
        The same readiness view surfaces
        `effective_water_gal_at_certificated_index` (the effective-water
        figure evaluated at the profile's certificated index) and
        `in_service_passing_vehicle_count`."

        Design: Corner/endpoints/ep_readiness_computed_read_all_fields
        """
        setup_compliant_index_c_airport()
        resp = api.get_readiness(TEST_USERS["faa_inspector_headers"])
        rd = validate_success(resp)
        assert rd["certificated_index"] == "C"
        assert rd["required_index_by_aircraft"] == "C"
        assert rd["supported_index_by_equipment"] == "C"
        assert rd["supported_index_by_staffing"] == "D"
        assert rd["effective_index"] == "C"
        assert rd["index_compliance_status"] == "COMPLIANT"
        assert rd["rated_basis_supported_index"] == "C"
        assert rd["roster_basis_supported_index"] == "D"
        assert rd["effective_water_gal_at_certificated_index"] == 5200
        assert rd["in_service_passing_vehicle_count"] == 2
        assert rd["roster_active_count"] == 4
        assert rd["deployment_ready_count"] == 4
        assert rd["open_notification_id"] is None


class TestImmediateConsistency:
    def test_computed_fields_visible_in_write_response(self, api):
        """PRD §2.4: "Entities with computed fields recompute those fields
        whenever the inputs change and bump their own `version` accordingly."

        Design: Corner/consistency_model/cons_immediate_computed_fields_visible_in_write_response
        """
        set_clock("2026-05-01T00:00:00Z")
        setup_profile_only()
        resp = api.create_vehicle(
            create_vehicle_payload(call_sign="RED-1",
                                   water_capacity_gal=2000,
                                   dry_chem_capacity_lb=500),
            AC,
        )
        v = validate_success(resp, expected_status=201)
        assert v["status"] == "IN_SERVICE"
        assert v["latest_readiness_result"] == "NONE"

        resp = api.create_readiness_check(
            create_readiness_check_payload(
                v["id"], water_available_gal=2000,
                dry_chem_available_lb=500, discharge_system_ok=True,
            ),
            AC,
        )
        rc = validate_success(resp, expected_status=201)
        assert rc["result"] == "PASS"
        assert rc["checked_at"] == "2026-05-01T00:00:00Z"
