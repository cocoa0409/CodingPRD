"""Facility / tank / component inventory: defaults, system fields, registration
constraints, activation & closure gates, cascades, and test-schedule projection."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_owner_headers,
    assert_facility, assert_tank_system, assert_ts_equal,
    create_facility_payload, create_tank_payload, create_component_payload,
    create_release_event_payload,
    create_facility, create_tank, add_component, setup_active_facility_with_tank,
    activate_facility, place_tank_in_service, create_operator, set_clock,
    get_facility, get_tank, get_component,
    FUND_YEAR_CAP_CENTS, AGGREGATE_YEAR_DEDUCTIBLE_CENTS,
    api_client,
)

OWNER = TEST_USERS["facility_owner_headers"]
OWNER2 = TEST_USERS["facility_owner_2_headers"]
ADMIN = TEST_USERS["contractor_admin_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]
READER = TEST_USERS["any_headers"]


class TestFacilityRegistration:
    def test_create_facility_applies_computed_defaults(self, api):
        """PRD §3.1: "when omitted, the election defaults to `PER_OCCURRENCE`.
        The new facility is stamped with the caller's identity as
        `owner_account_id`, enters in `REGISTERED` status, and is initialized with
        a `posture_score` of 100 and `compliance_posture` of `COMPLIANT`, a
        `fund_cap_remaining_cents` of 100000000 cents (one million dollars) for
        the fund year, and a `fund_year_deductible_remaining_cents` pool of
        2000000 cents (twenty thousand dollars)."

        Design: Corner/entities/create_facility_applies_computed_defaults
        """
        set_clock("2026-05-01T00:00:00Z")
        # fund_program_election deliberately omitted -> default applies
        facility = validate_success(
            api.create_facility(create_facility_payload(facility_name="Defaults Site"),
                                OWNER), 201)
        assert_facility(facility)
        assert facility["status"] == "REGISTERED"
        assert facility["posture_score"] == 100
        assert facility["compliance_posture"] == "COMPLIANT"
        assert facility["fund_cap_remaining_cents"] == FUND_YEAR_CAP_CENTS == 100000000
        assert (facility["fund_year_deductible_remaining_cents"]
                == AGGREGATE_YEAR_DEDUCTIBLE_CENTS == 2000000)
        assert facility["fund_program_election"] == "PER_OCCURRENCE"
        assert facility["owner_account_id"] == "owner-1"
        assert isinstance(facility["version"], int)

    def test_get_nonexistent_facility_not_found(self, api):
        """PRD §2.6: "the system validates existence in a strict left-to-right
        order, rejecting with the not-found error of the first missing resource
        before examining later ones" and "`ERR_FACILITY_NOT_FOUND`,
        `ERR_TANK_SYSTEM_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`" each name the
        resource type that failed lookup.

        Design: Corner/entities/get_nonexistent_facility_not_found
        """
        res = api.get_facility(NON_EXISTENT_UUID, READER)
        validate_error(res, ApiErrorId.ERR_FACILITY_NOT_FOUND, expected_status=404)


class TestTankRegistration:
    def test_create_tank_response_carries_common_fields(self, api):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix." and "`created_at` (string): an ISO 8601
        UTC timestamp with three fractional digits recording when the resource was
        created." and "`updated_at` (string): an ISO 8601 UTC timestamp, refreshed
        upon any change to the resource's properties."
        PRD §3.1: "A new tank enters in `REGISTERED` status."

        Design: Corner/entities/create_tank_response_carries_common_fields
        """
        facility = create_facility()
        tank = validate_success(api.create_tank_system(
            create_tank_payload(facility["id"]), OWNER), 201)
        assert_tank_system(tank)
        assert is_valid_uuid(tank["id"]), "server-minted id must be a UUID"
        assert is_iso8601_timestamp(tank["created_at"])
        assert is_iso8601_timestamp(tank["updated_at"])
        assert isinstance(tank["version"], int)
        assert tank["status"] == "REGISTERED"

    def test_manual_gauging_capacity_boundary(self, api):
        """PRD §3.1: "Manual gauging is only lawful on small tanks: choosing
        `MANUAL_GAUGING` with a `capacity_gallons` above 2000 is rejected with
        `ERR_MODE_NOT_ALLOWED_FOR_CAPACITY`."

        Design: Corner/entities/tank_manual_gauging_capacity_boundary
        """
        facility = create_facility()
        ok_res = api.create_tank_system(
            create_tank_payload(facility["id"], tank_tag="SMALL", capacity_gallons=2000,
                                piping_type="SUCTION",
                                release_detection_mode="MANUAL_GAUGING"), OWNER)
        tank = validate_success(ok_res, 201)
        assert tank["release_detection_mode"] == "MANUAL_GAUGING"
        assert tank["capacity_gallons"] == 2000

        err_res = api.create_tank_system(
            create_tank_payload(facility["id"], tank_tag="BIG", capacity_gallons=2001,
                                piping_type="SUCTION",
                                release_detection_mode="MANUAL_GAUGING"), OWNER)
        validate_error(err_res, ApiErrorId.ERR_MODE_NOT_ALLOWED_FOR_CAPACITY)

    def test_duplicate_tank_tag_rejected_and_scoped_per_facility(self, api):
        """PRD §3.1: "an operator-facing `tank_tag` that must be unique within the
        facility (a duplicate is rejected with `ERR_DUPLICATE_TANK_TAG`)"

        Design: Corner/validations/duplicate_tank_tag_rejected_and_scoped_per_facility
        """
        fac1 = create_facility("owner-1", facility_name="F1")
        fac2 = create_facility("owner-2", facility_name="F2")
        create_tank(fac1["id"], "owner-1", tank_tag="DUP")

        dup_res = api.create_tank_system(
            create_tank_payload(fac1["id"], tank_tag="DUP", substance="GASOLINE"),
            OWNER)
        validate_error(dup_res, ApiErrorId.ERR_DUPLICATE_TANK_TAG, expected_status=409)

        # Same tag under a different facility is a different uniqueness scope.
        other = validate_success(api.create_tank_system(
            create_tank_payload(fac2["id"], tank_tag="DUP", substance="GASOLINE"),
            OWNER2), 201)
        assert is_valid_uuid(other["id"])

        data, meta = validate_paginated(
            api.list_tank_systems(READER, params={"facility_id": fac1["id"]}))
        assert meta["total_count"] == 1


class TestFacilityListAndConsistency:
    def test_list_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100." and "The `meta`
        object of a list response carries the pagination fields `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_defaults_and_envelope
        """
        create_facility(facility_name="P1")
        create_facility(facility_name="P2")

        res = api.list_facilities(READER)
        data, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array"
        assert len(data) == 2 and meta["total_count"] == 2
        assert meta["has_more"] is False and meta["limit"] == 10 and meta["offset"] == 0

        data, meta = validate_paginated(api.list_facilities(READER, params={"limit": 1}))
        assert len(data) == 1 and meta["total_count"] == 2 and meta["has_more"] is True

        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    def test_immediate_read_after_write_matches(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that increments
        by 1 on every mutation of the resource, including mutations driven by
        system cascades."
        PRD §2.9: "A facility read returns the posture fields as of the latest
        recompute."

        Design: Corner/consistency_model/immediate_read_after_write_matches
        """
        facility = create_facility(facility_name="Immediate Site", state_code="WA",
                                   fund_program_election="AGGREGATE")
        read = validate_success(api.get_facility(facility["id"], READER), 200)
        assert read["facility_name"] == "Immediate Site"
        assert read["fund_program_election"] == "AGGREGATE"
        assert read["state_code"] == "WA"

        create_tank(facility["id"])
        before_version = read["version"]
        activated = validate_success(api.activate_facility(facility["id"], OWNER), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == before_version + 1, (
            "activation is one mutation -> version increments by exactly 1")

        reread = validate_success(api.get_facility(facility["id"], READER), 200)
        assert reread["status"] == "ACTIVE"
        assert reread["version"] == activated["version"]


class TestTechnicianRegistry:
    def test_list_technicians_filter_by_endorsement(self, api):
        """PRD §3.4: "A `ContractorAdmin` registers each technician with a
        `full_name`, an `endorsements` array drawn from `TIGHTNESS_TESTER`,
        `LLD_TESTER`, `CP_TESTER`, and `INSPECTOR`, and an optional `trainer` flag
        that defaults to false; new technicians are `active` by default, and an
        inactive technician cannot be scheduled. The technician directory lists
        with `endorsement` and `active` filters."

        Design: Corner/entities/list_technicians_filter_by_endorsement
        """
        from test_helpers import create_technician
        t_cp = create_technician(["CP_TESTER"], full_name="CP")
        create_technician(["TIGHTNESS_TESTER"], full_name="TT")
        create_technician([], trainer=True, full_name="Trainer")

        data, meta = validate_paginated(
            api.list_technicians(READER, params={"endorsement": "CP_TESTER"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == t_cp["id"]

        detail = validate_success(api.get_technician(t_cp["id"], READER), 200)
        assert detail["full_name"] == "CP"
        assert detail["active"] is True
        assert detail["trainer"] is False


class TestActivationAndClosureGates:
    def test_place_in_service_requires_active_facility(self, api):
        """PRD §3.1: "A tank moves from `REGISTERED` to `IN_SERVICE` when its owner
        places it in service, which requires the parent facility to be `ACTIVE`;
        otherwise the request fails with `ERR_FACILITY_NOT_ACTIVE`."

        Design: Corner/errors/place_in_service_requires_active_facility
        """
        facility = create_facility()
        tank = create_tank(facility["id"])
        res = api.place_in_service(tank["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_FACILITY_NOT_ACTIVE, expected_status=409)

    def test_facility_activate_without_tank_rejected(self, api):
        """PRD §3.1: "The facility itself moves from `REGISTERED` to `ACTIVE` only
        once at least one tank system exists for it; activation with no tank
        registered is rejected with `ERR_NO_TANK_REGISTERED`."

        Design: Corner/state_machines/facility_activate_without_tank_rejected
        """
        facility = create_facility(facility_name="Empty Site")
        res = api.activate_facility(facility["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_NO_TANK_REGISTERED, expected_status=409)

    def test_facility_close_with_open_tanks_rejected(self, api):
        """PRD §3.2: "The owner may close an `ACTIVE` facility only when every one
        of its tanks is `PERMANENTLY_CLOSED`; otherwise the request fails with
        `ERR_TANKS_NOT_CLOSED`."

        Design: Corner/state_machines/facility_close_with_open_tanks_rejected
        """
        facility, tank = setup_active_facility_with_tank()
        res = api.close_facility(facility["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_TANKS_NOT_CLOSED, expected_status=409)

    def test_facility_close_happy_path_cascades(self, api):
        """PRD §3.2: "On top of the same order-cancellation cascade, every
        component of the tank in `IN_SERVICE` or `DEFICIENT` is retired to
        `OUT_OF_SERVICE`." and "Closure cascades widely: every facility service
        order still in `REQUESTED` or `SCHEDULED` is cancelled (with the same
        re-test deficiency fallback to `CORRECTED`), and every operator of the
        facility in `DESIGNATED`, `ACTIVE`, or `LAPSED` is revoked. The facility
        ends in `CLOSED`."

        Design: Corner/state_machines/facility_close_happy_path_cascades
        """
        from test_helpers import create_order
        facility, tank = setup_active_facility_with_tank()
        comp = add_component(tank["id"], "SPILL_BUCKET", serial_no="SB-1")
        op = create_operator(facility["id"], "A")
        order = create_order(facility["id"], tank["id"], "TANK_TIGHTNESS")
        assert order["status"] == "REQUESTED"

        validate_success(
            api.close_tank(tank["id"], {"closure_type": "PERMANENT"}, OWNER), 200)
        closed = validate_success(api.close_facility(facility["id"], OWNER), 200)
        assert closed["status"] == "CLOSED"

        assert get_component(comp["id"])["status"] == "OUT_OF_SERVICE"
        assert validate_success(
            api.get_service_order(order["id"], READER), 200)["status"] == "CANCELLED"
        assert validate_success(
            api.get_operator(op["id"], READER), 200)["status"] == "REVOKED"


class TestReturnToServiceGates:
    def _setup_temporarily_closed_tank(self):
        facility, tank = setup_active_facility_with_tank()
        validate_success(
            api_client.close_tank(tank["id"], {"closure_type": "TEMPORARY"}, OWNER),
            200)
        return facility, tank

    def test_return_to_service_blocked_by_open_release(self, api):
        """PRD §3.2: "If any release event on the tank sits in `SUSPECTED`,
        `CONFIRMED`, or `CLEANUP_IN_PROGRESS`, the return is rejected with
        `ERR_OPEN_RELEASE_ON_TANK`. A clean return moves the tank
        `TEMPORARILY_CLOSED` → `IN_SERVICE`."

        Design: Corner/state_machines/return_to_service_blocked_by_open_release
        """
        set_clock("2026-05-01T00:00:00Z")
        facility, tank = self._setup_temporarily_closed_tank()
        release = validate_success(api.create_release_event(
            create_release_event_payload(facility["id"], tank_system_id=tank["id"]),
            OWNER), 201)

        res = api.return_to_service(tank["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_OPEN_RELEASE_ON_TANK, expected_status=409)

        validate_success(api.dismiss_release(release["id"], REGULATOR), 200)
        restored = validate_success(api.return_to_service(tank["id"], OWNER), 200)
        assert restored["status"] == "IN_SERVICE"

    def test_return_to_service_blocked_by_critical_deficiency(self, api):
        """PRD §3.2: "If any deficiency on the tank has severity `CRITICAL` and
        status `OPEN`, `CORRECTION_ORDERED`, or `ESCALATED`, the return is rejected
        with `ERR_CRITICAL_DEFICIENCY_OPEN`; a `CRITICAL` deficiency in `CORRECTED`
        or `RE_TEST_SCHEDULED` does not block, because the correction is applied
        and only verification remains."

        Design: Corner/errors/return_to_service_blocked_by_critical_deficiency
        """
        from test_helpers import (setup_started_tightness_order, record_results,
                                  tightness_readings)
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_started_tightness_order()
        record_results(ctx["order"]["id"], ctx["tester"]["id"],
                       tightness_readings(0.5))  # FAIL -> CRITICAL + SUSPECTED release
        tank = get_tank(ctx["tank"]["id"])
        assert tank["status"] == "TEMPORARILY_CLOSED"

        res = api.list_release_events(READER, params={"tank_system_id": tank["id"],
                                                      "status": "SUSPECTED"})
        release = res.json()["data"][0]
        validate_success(api.dismiss_release(release["id"], REGULATOR), 200)

        res = api.return_to_service(tank["id"], OWNER)
        validate_error(res, ApiErrorId.ERR_CRITICAL_DEFICIENCY_OPEN, expected_status=409)


class TestScheduleProjection:
    def test_test_schedule_projection_intervals(self, api):
        """PRD §3.1: "a `TANK_TIGHTNESS` test is required unless the tank's
        `release_detection_mode` is `INTERSTITIAL_MONITORING`, recurring every 12
        months for `ATG_INVENTORY` tanks and every 60 months for `MANUAL_GAUGING`
        tanks; a `LINE_TIGHTNESS` test is required only when the `piping_type` is
        `PRESSURIZED`, every 12 months; an `LLD_FUNCTION` check is required only
        when a `LINE_LEAK_DETECTOR` component exists on the tank, every 12 months;
        a `CP_SURVEY` is required only when a `CATHODIC_PROTECTION` component
        exists, every 36 months; and a `SPILL_OVERFILL_INSPECTION` is required
        only when a `SPILL_BUCKET` or `OVERFILL_DEVICE` component exists, every 36
        months." and "when no certified order of that type exists, the interval is
        added to the tank's `installed_on`" and "The projection's items are sorted
        by `due_at` ascending, with ties broken by the `test_type` name ascending."

        Design: Corner/calculations/test_schedule_projection_intervals
        """
        facility = create_facility(facility_name="Schedule Site")
        tank1 = create_tank(facility["id"], tank_tag="T1")  # ATG + PRESSURIZED
        tank2 = create_tank(facility["id"], tank_tag="T2", substance="KEROSENE",
                            capacity_gallons=5000, tank_construction="FRP",
                            piping_type="GRAVITY",
                            release_detection_mode="INTERSTITIAL_MONITORING")
        add_component(tank1["id"], "LINE_LEAK_DETECTOR", serial_no="LLD-1")
        add_component(tank1["id"], "CATHODIC_PROTECTION", serial_no="CP-1")
        add_component(tank1["id"], "SPILL_BUCKET", serial_no="SB-1")

        sched1 = validate_success(api.get_test_schedule(tank1["id"], READER), 200)
        assert sched1["tank_system_id"] == tank1["id"]
        items = sched1["items"]
        expected = [
            ("LINE_TIGHTNESS", "2019-01-01T00:00:00Z"),          # +12 months
            ("LLD_FUNCTION", "2019-01-01T00:00:00Z"),            # +12 months
            ("TANK_TIGHTNESS", "2019-01-01T00:00:00Z"),          # +12 months
            ("CP_SURVEY", "2021-01-01T00:00:00Z"),               # +36 months
            ("SPILL_OVERFILL_INSPECTION", "2021-01-01T00:00:00Z"),  # +36 months
        ]
        assert len(items) == len(expected)
        for item, (test_type, due_iso) in zip(items, expected):
            assert item["test_type"] == test_type, (
                "items sorted by due_at ascending, ties by test_type name ascending")
            assert_ts_equal(item["due_at"], due_iso, label=f"due_at[{test_type}]")

        sched2 = validate_success(api.get_test_schedule(tank2["id"], READER), 200)
        assert sched2["items"] == [], (
            "interstitial monitoring + gravity piping + no components -> no obligations")
