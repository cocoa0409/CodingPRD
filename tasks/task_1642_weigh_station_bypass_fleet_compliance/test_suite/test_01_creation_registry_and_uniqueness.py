"""Creation defaults, registry uniqueness, and read-back consistency.

Covers carrier onboarding defaults, required-field enforcement, the global
registry keys (dot_number, state_code, station_code, vin, device_serial),
the one-slot-per-device-type credential rule, and the credential's initial
state.
"""
from test_helpers import (
    ADMIN,
    SPM,
    ApiErrorId,
    assert_carrier,
    assert_credential,
    assert_vehicle,
    create_active_carrier,
    create_carrier,
    create_carrier_payload,
    create_config,
    create_credential_for,
    create_station,
    create_vehicle_for,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_vehicles_for,
    make_carrier_manager_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestCarrierCreation:
    def test_carrier_creation_applies_server_defaults(self, api):
        """PRD §3.1: "New carriers begin with `status` `ENROLLED`, an
        `eligibility_status` of `NOT_EVALUATED`, a `credit_balance_cents` of
        zero, an empty `credit_ledger`, and an empty `closed_billing_periods`
        history."
        PRD §2.5: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/carrier_creation_defaults_and_system_fields
        """
        set_clock()
        resp = api.create_carrier(
            create_carrier_payload(dot_number="100001", legal_name="Acme Hauling"),
            ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_carrier(data)
        assert data["status"] == "ENROLLED"
        assert data["eligibility_status"] == "NOT_EVALUATED"
        assert data["credit_balance_cents"] == 0
        assert data["credit_ledger"] == []
        assert data["closed_billing_periods"] == []
        assert isinstance(data["version"], int), "version is a system-managed integer"
        assert is_valid_uuid(data["id"]) and "-" in data["id"]
        assert is_iso8601_timestamp(data["created_at"])

    def test_carrier_create_missing_dot_number_rejected(self, api):
        """PRD §2.10: "Required fields present, enum members valid, numeric
        ranges respected — `ERR_INVALID_REQUEST`, `ERR_INVALID_ISS_SCORE`, and
        `ERR_CREDIT_AMOUNT_OUT_OF_RANGE`."
        PRD §3.1: "A carrier enters the program when a `PlatformAdmin`
        onboards it with its `dot_number` and `legal_name`."

        Design: Corner/entities/carrier_create_missing_dot_number_returns_invalid_request
        """
        resp = api.create_carrier({"legal_name": "No Dot"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_carrier_duplicate_dot_number_rejected(self, api):
        """PRD §2.6: "A carrier's `dot_number` must be globally unique
        (`ERR_DUPLICATE_DOT_NUMBER`)"

        Design: Corner/entities/carrier_duplicate_dot_number_returns_409
        """
        create_carrier(dot_number="100001", legal_name="Acme Hauling")
        resp = api.create_carrier(
            create_carrier_payload(dot_number="100001", legal_name="Copycat Lines"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DOT_NUMBER)

    def test_carrier_get_missing_returns_not_found(self, api):
        """PRD §2.10: "Path- and body-referenced resources are verified left
        to right — carrier, state config, station, vehicle, credential, bypass
        event, dispute, override, subscription, invoice — and the first missing
        reference yields its `ERR_CARRIER_NOT_FOUND` ..."

        Design: Corner/entities/carrier_get_not_found_returns_404
        """
        ghost = "11111111-2222-4333-8444-555555555555"
        resp = api.get_carrier(ghost, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)
        assert isinstance(err["message"], str) and err["message"].strip()


class TestFleetRegistry:
    def test_vehicle_gvwr_zero_rejected(self, api):
        """PRD §3.4: "the registered weight rating `gvwr_lbs` in pounds —
        which must be greater than zero, with violations rejected as
        `ERR_INVALID_REQUEST`"

        Design: Corner/entities/vehicle_gvwr_zero_returns_invalid_request
        """
        set_clock()
        carrier = create_active_carrier()
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_vehicle(
            {"carrier_id": carrier["id"], "vin": "VIN-0001",
             "plate_number": "P-1", "plate_state": "CA", "home_state_code": "CA",
             "gvwr_lbs": 0},
            cm)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert list_vehicles_for(carrier["id"]) == [], "no vehicle row created"

    def test_vehicle_duplicate_vin_rejected_across_carriers(self, api):
        """PRD §2.6: "On the fleet side, a vehicle's `vin`
        (`ERR_DUPLICATE_VIN`) and a credential's `device_serial`
        (`ERR_DUPLICATE_DEVICE_SERIAL`) are each globally unique."

        Design: Corner/entities/vehicle_duplicate_vin_returns_409
        """
        set_clock()
        carrier_a = create_active_carrier(dot_number="100001", legal_name="Carrier A")
        carrier_b = create_active_carrier(dot_number="100002", legal_name="Carrier B")
        create_vehicle_for(carrier_a["id"], vin="VIN-0001")
        cm_b = make_carrier_manager_headers(carrier_b["id"])
        resp = api.create_vehicle(
            {"carrier_id": carrier_b["id"], "vin": "VIN-0001",
             "plate_number": "P-9", "plate_state": "NV", "home_state_code": "NV",
             "gvwr_lbs": 60000},
            cm_b)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN)

    def test_credential_duplicate_device_serial_rejected(self, api):
        """PRD §2.6: "On the fleet side, a vehicle's `vin`
        (`ERR_DUPLICATE_VIN`) and a credential's `device_serial`
        (`ERR_DUPLICATE_DEVICE_SERIAL`) are each globally unique."

        Design: Corner/entities/credential_duplicate_serial_returns_409
        """
        set_clock()
        carrier = create_active_carrier()
        veh1 = create_vehicle_for(carrier["id"], vin="VIN-0001", plate_number="P-1")
        veh2 = create_vehicle_for(carrier["id"], vin="VIN-0002", plate_number="P-2")
        create_credential_for(veh1["id"], carrier["id"],
                              device_type="TRANSPONDER", device_serial="SN-0001")
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_credential(
            {"vehicle_id": veh2["id"], "device_type": "MOBILE_APP",
             "device_serial": "SN-0001"},
            cm)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DEVICE_SERIAL)

    def test_credential_second_same_type_rejected(self, api):
        """PRD §2.6: "A vehicle may hold at most one credential per
        `device_type` with a status of `PROVISIONED`, `ACTIVE`, or `SUSPENDED`
        (`ERR_CREDENTIAL_TYPE_ALREADY_ACTIVE`) — only deactivation frees the
        slot for a replacement device."

        Design: Corner/entities/credential_second_same_type_returns_409
        """
        set_clock()
        carrier = create_active_carrier()
        veh = create_vehicle_for(carrier["id"], vin="VIN-0001")
        create_credential_for(veh["id"], carrier["id"],
                              device_type="TRANSPONDER", device_serial="SN-0001")
        cm = make_carrier_manager_headers(carrier["id"])
        ok = api.create_credential(
            {"vehicle_id": veh["id"], "device_type": "MOBILE_APP",
             "device_serial": "SN-0002"}, cm)
        app_cred = validate_success(ok, expected_status=201)
        assert_credential(app_cred)
        assert app_cred["device_type"] == "MOBILE_APP", \
            "one credential per device_type is allowed"
        resp = api.create_credential(
            {"vehicle_id": veh["id"], "device_type": "TRANSPONDER",
             "device_serial": "SN-0003"}, cm)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_TYPE_ALREADY_ACTIVE)

    def test_config_duplicate_state_code_rejected(self, api):
        """PRD §2.6: "a state program config's `state_code` may be registered
        once (`ERR_DUPLICATE_STATE_CONFIG`)"

        Design: Corner/entities/config_duplicate_state_returns_409
        """
        create_config(state_code="CA")
        resp = api.create_config(
            {"state_code": "CA", "random_pull_in_rate_bps": 500}, SPM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_CONFIG)

    def test_station_duplicate_code_rejected_across_configs(self, api):
        """PRD §2.6: "a station's `station_code` is unique across the
        platform (`ERR_DUPLICATE_STATION_CODE`)"

        Design: Corner/entities/station_duplicate_code_returns_409
        """
        cfg_ca = create_config(state_code="CA")
        cfg_nv = create_config(state_code="NV")
        create_station(cfg_ca["id"], station_code="CA-S1")
        resp = api.create_station(
            {"state_program_config_id": cfg_nv["id"], "station_code": "CA-S1",
             "station_type": "WIM_ONLY", "supported_channel": "MOBILE_APP"},
            SPM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATION_CODE)


class TestInitialStatesAndReadback:
    def test_credential_begins_provisioned_with_reason_none(self, api):
        """PRD §3.4: "It begins `PROVISIONED` with `status_reason` `NONE`."

        Design: Corner/state_machines/credential_initial_state_provisioned
        """
        set_clock()
        carrier = create_active_carrier()
        veh = create_vehicle_for(carrier["id"], vin="VIN-0001")
        resp = api.create_credential(
            {"vehicle_id": veh["id"], "device_type": "TRANSPONDER",
             "device_serial": "SN-0001"},
            make_carrier_manager_headers(carrier["id"]))
        data = validate_success(resp, expected_status=201)
        assert_credential(data)
        assert data["status"] == "PROVISIONED"
        assert data["status_reason"] == "NONE"
        assert data["carrier_id"] == carrier["id"], \
            "carrier_id is denormalized from the vehicle at creation"

    def test_write_then_read_immediately_visible(self, api):
        """PRD §1: "every cascade triggered by a write is fully applied and
        visible in that write's response and in all subsequent reads."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/immediate_visibility_writes_then_reads
        """
        set_clock()
        carrier = create_active_carrier()
        cm = make_carrier_manager_headers(carrier["id"])
        resp = api.create_vehicle(
            {"carrier_id": carrier["id"], "vin": "VIN-0001",
             "plate_number": "P-1", "plate_state": "CA", "home_state_code": "CA",
             "gvwr_lbs": 80000},
            cm)
        created = validate_success(resp, expected_status=201)
        assert_vehicle(created)
        assert created["service_status"] == "IN_SERVICE"
        assert is_valid_uuid(created["id"])
        assert is_iso8601_timestamp(created["created_at"])
        assert isinstance(created["version"], int)

        rows = list_vehicles_for(carrier["id"])
        assert len(rows) == 1
        assert rows[0]["id"] == created["id"]
        assert rows[0]["vin"] == "VIN-0001"
        assert rows[0]["service_status"] == "IN_SERVICE"
