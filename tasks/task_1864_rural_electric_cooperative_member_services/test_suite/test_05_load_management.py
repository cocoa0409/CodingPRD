"""Load-management devices: activation gating, credit snapshot, cascades
(PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_device_payload,
    get_success_data,
    setup_cooperative,
    setup_energized_location,
    setup_published_schedule,
    validate_error,
    validate_success,
)

REP = TEST_USERS["rep"]
FIELD = TEST_USERS["field_ops"]


class TestDeviceActivationGates:
    def test_irrigation_interruptible_requires_irrigation_rate_class(self, api):
        """PRD §3.5: "Activation is a field-operations step with two guards: the
        location must be `ENERGIZED`, and an `IRRIGATION_INTERRUPTIBLE` device
        may only live on an `IRRIGATION`-class location — a mismatch is rejected
        with `ERR_LMD_RATE_CLASS_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/lmd_activate_requires_irrigation_rate_class
        """
        setup_cooperative()
        member, _loc, _order, _row = setup_energized_location(
            member_overrides={"legal_name": "M", "member_type": "IRRIGATION"},
            rate_class="RESIDENTIAL", address="Res")
        loc_irr = None
        member, loc_irr, _o2, _r2 = setup_energized_location(
            member=member, rate_class="IRRIGATION", address="Irr",
            location_overrides={"irrigation_connected_load_kw": 20})
        dev_res = validate_success(api.enroll_device(
            create_device_payload(
                service_location_id=_loc["id"], device_type="IRRIGATION_INTERRUPTIBLE"),
            REP), expected_status=201)
        dev_irr = validate_success(api.enroll_device(
            create_device_payload(
                service_location_id=loc_irr["id"], device_type="IRRIGATION_INTERRUPTIBLE"),
            REP), expected_status=201)
        resp = api.activate_device(dev_res["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_LMD_RATE_CLASS_MISMATCH)
        ok = validate_success(api.activate_device(dev_irr["id"], FIELD), 200)
        assert ok["status"] == "ACTIVE"

    def test_device_credit_snapshot_from_published_schedule(self, api):
        """PRD §3.5: "At the moment of activation the device's
        `monthly_credit_cents` is snapshotted from the currently `PUBLISHED`
        rate schedule for the location's `rate_class`, so later rate redesigns
        do not retroactively rewrite the device's entitlement."

        Design: Difficulty/cross_entity_state_dependency/lmd_activate_requires_irrigation_rate_class
        """
        setup_cooperative()
        member, location, _order, _row = setup_energized_location(rate_class="IRRIGATION",
                                                                  location_overrides={
                                                                      "irrigation_connected_load_kw": 20})
        setup_published_schedule(
            rate_class="IRRIGATION", code="IR-9", load_management_credit_cents=750)
        device = validate_success(api.enroll_device(
            create_device_payload(
                service_location_id=location["id"], device_type="IRRIGATION_INTERRUPTIBLE"),
            REP), expected_status=201)
        activated = validate_success(api.activate_device(device["id"], FIELD), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["monthly_credit_cents"] == 750


class TestDeviceCascade:
    def test_member_suspend_cascades_device_to_suspended(self, api):
        """PRD §3.5: "suspension also arrives by cascade — a member suspension
        or a location disconnect drops `ENROLLED` and `ACTIVE` devices to
        `SUSPENDED`." and "At the moment of activation the device's
        `monthly_credit_cents` is snapshotted from the currently `PUBLISHED`
        rate schedule for the location's `rate_class`".

        Design: Corner/cross_cutting_layers/lmd_suspend_cascade_from_member_suspend
        """
        setup_cooperative()
        member, location, _order, _row = setup_energized_location()
        setup_published_schedule(rate_class="RESIDENTIAL", load_management_credit_cents=500)
        device = validate_success(api.enroll_device(
            create_device_payload(service_location_id=location["id"],
                                  device_type="WATER_HEATER"),
            REP), expected_status=201)
        device = get_success_data(api.activate_device(device["id"], FIELD), 200)
        assert device["status"] == "ACTIVE"
        assert device["monthly_credit_cents"] == 500

        get_success_data(api.suspend_member(member["id"], REP), 200)
        after = get_success_data(api.get_device(device["id"], FIELD), 200)
        assert after["status"] == "SUSPENDED"
        assert after["monthly_credit_cents"] == 500


class TestMemberTerminateCascade:
    def test_terminate_cascades_locations_and_devices(self, api):
        """PRD §3.1: "Termination stamps `terminated_at` (null while the member
        is non-terminal), disconnects every `ENERGIZED` location, unenrolls
        every device still in `ENROLLED`, `ACTIVE`, or `SUSPENDED`".

        Design: Difficulty/transitive_cascade/member_terminate_full_cascade
        """
        setup_cooperative()
        member, location, _order, _row = setup_energized_location()
        setup_published_schedule(rate_class="RESIDENTIAL", load_management_credit_cents=500)
        device = validate_success(api.enroll_device(
            create_device_payload(service_location_id=location["id"],
                                  device_type="WATER_HEATER"),
            REP), expected_status=201)
        device = get_success_data(api.activate_device(device["id"], FIELD), 200)
        assert device["status"] == "ACTIVE"

        terminated = validate_success(api.terminate_member(member["id"], REP), 200)
        assert terminated["status"] == "TERMINATED"
        loc_after = get_success_data(api.get_service_location(location["id"], FIELD), 200)
        assert loc_after["status"] == "DISCONNECTED"
        dev_after = get_success_data(api.get_device(device["id"], FIELD), 200)
        assert dev_after["status"] == "UNENROLLED"

    def test_terminate_enrolled_device_unenrolls_without_activation(self, api):
        """PRD §3.1: "Termination ... unenrolls every device still in
        `ENROLLED`, `ACTIVE`, or `SUSPENDED`".

        Design: Difficulty/transitive_cascade/member_terminate_full_cascade
        """
        setup_cooperative()
        member, location, _order, _row = setup_energized_location()
        device = validate_success(api.enroll_device(
            create_device_payload(service_location_id=location["id"],
                                  device_type="WATER_HEATER"),
            REP), expected_status=201)
        assert device["status"] == "ENROLLED"
        terminated = validate_success(api.terminate_member(member["id"], REP), 200)
        assert terminated["status"] == "TERMINATED"
        dev_after = get_success_data(api.get_device(device["id"], FIELD), 200)
        assert dev_after["status"] == "UNENROLLED"
