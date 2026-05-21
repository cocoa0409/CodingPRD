"""Carrier / ELDDevice / Vehicle / Driver registration — PRD §3.1."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_carrier,
    assert_driver,
    assert_eld_device,
    assert_vehicle,
    create_carrier,
    create_carrier_payload,
    create_driver,
    create_driver_payload,
    create_eld_device,
    create_eld_device_payload,
    create_vehicle,
    create_vehicle_payload,
    random_dot_number,
    random_serial,
    random_vin,
    validate_error,
    validate_success,
)


# ===========================================================================
# Carrier — PRD §3.1
# ===========================================================================
class TestCarrier:

    def test_create_carrier_returns_201_with_fields(self, api):
        """PRD §3.1: "A `PlatformAdmin` registers a motor carrier by
        supplying a `dot_number` (digits only, five to eight characters
        long, unique across the system), a `legal_name`, and a
        `safety_contact_user_id`; the system mints the carrier and
        returns it."

        Claim: POST /carriers returns 201 with the requested fields
        echoed on the carrier.
        """
        payload = create_carrier_payload(
            dot_number="9876543",
            legal_name="Apex Freight LLC",
        )
        resp = api.create_carrier(payload, TEST_USERS["admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["dot_number"] == "9876543"
        assert data["legal_name"] == "Apex Freight LLC"
        assert_carrier(data)

    def test_create_carrier_requires_platform_admin(self, api):
        """PRD §4: "POST /carriers ... PlatformAdmin"; PRD §2.1: "If
        both headers are present but the role does not appear on the
        endpoint's allow-list, the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Claim: a CarrierSafetyOfficer cannot POST /carriers.
        """
        payload = create_carrier_payload()
        resp = api.create_carrier(payload, TEST_USERS["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# ELDDevice — PRD §3.1
# ===========================================================================
class TestELDDevice:

    def test_create_eld_device_defaults_certified_to_true(self, api):
        """PRD §3.1: "an optional `certified_for_fmcsa` flag that
        defaults to true".

        Claim: when `certified_for_fmcsa` is omitted, the created
        ELDDevice has `certified_for_fmcsa == true`.
        """
        payload = create_eld_device_payload()
        # Ensure caller did not supply it.
        payload.pop("certified_for_fmcsa", None)
        resp = api.create_eld_device(payload, TEST_USERS["admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["certified_for_fmcsa"] is True, (
            "PRD §3.1 default for certified_for_fmcsa is true"
        )
        assert_eld_device(data)

    def test_create_eld_device_uncertified_recorded(self, api):
        """PRD §3.1: "uncertified devices may be recorded for inventory
        purposes but cannot bind to a driver".

        Claim: creating an ELDDevice with certified_for_fmcsa=false
        succeeds (the bind-time check is exercised separately).
        """
        payload = create_eld_device_payload(certified_for_fmcsa=False)
        resp = api.create_eld_device(payload, TEST_USERS["admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["certified_for_fmcsa"] is False
        assert_eld_device(data)


# ===========================================================================
# Vehicle — PRD §3.1
# ===========================================================================
class TestVehicle:

    def test_create_vehicle_pairs_with_device(self, api):
        """PRD §3.1: "registering each `Vehicle` with a `vin` ... the
        owning `carrier_id`, and the `eld_device_id` of the device
        installed in that vehicle".

        Claim: created vehicle echoes the supplied vin, carrier_id,
        and eld_device_id.
        """
        carrier = create_carrier()
        device = create_eld_device()
        payload = create_vehicle_payload(
            vin=random_vin(),
            carrier_id=carrier["id"],
            eld_device_id=device["id"],
        )
        resp = api.create_vehicle(payload, TEST_USERS["officer_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["vin"] == payload["vin"]
        assert data["carrier_id"] == carrier["id"]
        assert data["eld_device_id"] == device["id"]
        assert_vehicle(data)


# ===========================================================================
# Driver — PRD §3.1
# ===========================================================================
class TestDriver:

    def test_create_driver_defaults_cycle_to_seventy_hour(self, api):
        """PRD §3.1: "an optional `cycle_type` that defaults to
        `SEVENTY_HOUR_EIGHT_DAY` (the alternative being
        `SIXTY_HOUR_SEVEN_DAY`)".

        Claim: when cycle_type is omitted, the created Driver carries
        cycle_type == "SEVENTY_HOUR_EIGHT_DAY".
        """
        carrier = create_carrier()
        payload = create_driver_payload(carrier_id=carrier["id"])
        # Ensure caller did not pass cycle_type.
        payload.pop("cycle_type", None)
        resp = api.create_driver(payload, TEST_USERS["officer_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["cycle_type"] == "SEVENTY_HOUR_EIGHT_DAY", (
            "PRD §3.1 default for cycle_type is SEVENTY_HOUR_EIGHT_DAY"
        )
        assert_driver(data)

    def test_create_driver_defaults_timezone_to_america_new_york(self, api):
        """PRD §3.1: "an optional `home_terminal_timezone` IANA name
        that defaults to `America/New_York`".

        Claim: when home_terminal_timezone is omitted, the created
        Driver carries home_terminal_timezone == "America/New_York".
        """
        carrier = create_carrier()
        payload = create_driver_payload(carrier_id=carrier["id"])
        payload.pop("home_terminal_timezone", None)
        resp = api.create_driver(payload, TEST_USERS["officer_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["home_terminal_timezone"] == "America/New_York", (
            "PRD §3.1 default for home_terminal_timezone is "
            "America/New_York"
        )

    def test_new_driver_starts_off_duty_and_unbound(self, api):
        """PRD §3.1: "A newly minted `Driver` has `duty_status` of
        `OFF_DUTY`, a null `bound_vehicle_id`, a null
        `bound_eld_device_id`, a null
        `last_34_hour_restart_completed_at`".

        Claim: a fresh Driver has duty_status="OFF_DUTY",
        bound_vehicle_id=None, bound_eld_device_id=None,
        last_34_hour_restart_completed_at=None.
        """
        carrier = create_carrier()
        driver = create_driver(carrier_id=carrier["id"])
        assert driver["duty_status"] == "OFF_DUTY"
        assert driver["bound_vehicle_id"] is None
        assert driver["bound_eld_device_id"] is None
        assert driver["last_34_hour_restart_completed_at"] is None
