"""Confined-space permits: segregation of duties, certification and gas-test
gates, the suspend/resume loop, and the 12-hour validity window."""
from test_helpers import (
    ApiErrorId,
    add_operator,
    assert_instant_equal,
    create_draft_permit,
    create_permit_trio,
    create_station,
    get_permit,
    issue_permit,
    make_operator_headers,
    reset_clock,
    setup_issued_permit,
    setup_station_with_pumps,
    validate_error,
    validate_success,
)


class TestPermitSegregation:
    def test_segregation_of_duties_supervisor_equals_entrant(self, api, operations_supervisor_headers):
        """PRD §3.9: "Segregation of duties is enforced hard: the entrant,
        attendant, and supervisor must be three distinct operators. Any
        collision — supervisor equal to entrant, supervisor equal to attendant,
        or entrant equal to attendant — is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 422), both when the permit
        is created and when it is issued."

        Design: Corner/validations/segregation_of_duties_supervisor_equals_entrant
        """
        reset_clock()
        station = create_station()
        op = add_operator(full_name="Same", certifications=["CSE_1"])
        res = api.create_confined_space_permit(
            station["id"],
            {
                "work_description": "inspect",
                "authorized_entrant_id": op["id"],
                "attendant_operator_id": op["id"],
                "entry_supervisor_id": op["id"],
                "gas_test_passed": True,
            },
            operations_supervisor_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)


class TestPermitCertificationAndGas:
    def test_entrant_without_cse_cert_rejected_at_create(self, api, operations_supervisor_headers):
        """PRD §3.9: "Certification is checked at both moments as well: the
        named entrant and the named attendant must each hold `CSE_1` or `CSE_2`
        among their `certifications`, or the request is rejected with
        `ERR_INSUFFICIENT_CERTIFICATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_permit
        """
        reset_clock()
        station = create_station()
        entrant = add_operator(full_name="E1", certifications=[])
        attendant = add_operator(full_name="A1", certifications=["CSE_2"])
        supervisor = add_operator(full_name="S1", certifications=["CSE_1"])
        res = api.create_confined_space_permit(
            station["id"],
            {
                "work_description": "inspect",
                "authorized_entrant_id": entrant["id"],
                "attendant_operator_id": attendant["id"],
                "entry_supervisor_id": supervisor["id"],
                "gas_test_passed": True,
            },
            operations_supervisor_headers,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CERTIFICATION)

    def test_gas_test_required_at_issue(self, api):
        """PRD §3.9: "Beyond segregation and certification, issuance requires
        `gas_test_passed` to be true (a false flag is rejected with
        `ERR_GAS_TEST_REQUIRED`, HTTP 422) and requires the station's posture to
        be neither `FROZEN` nor `EMERGENCY`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_permit
        """
        reset_clock()
        station, _ = setup_station_with_pumps()
        trio = create_permit_trio()
        permit = create_draft_permit(station["id"], *trio, gas_test_passed=False)
        res = api.issue_permit(permit["id"], make_operator_headers(trio[2]["id"]))
        validate_error(res, ApiErrorId.ERR_GAS_TEST_REQUIRED)
        assert get_permit(permit["id"])["status"] == "DRAFT"


class TestPermitSuspendResumeLoop:
    def test_suspend_then_reactivate_within_validity(self, api):
        """PRD §3.9: "Once issued, the permit may be activated (`ISSUED →
        ACTIVE`, and likewise `SUSPENDED → ACTIVE`) — but only while the current
        time is still before `valid_until`; activating at or after expiry is
        rejected with `ERR_PERMIT_EXPIRED` (HTTP 422). An `ACTIVE` permit may be
        suspended and re-activated within its validity window."
        PRD §3.9: "Issuance stamps `issued_at` and fixes `valid_until` at 12
        hours after issuance."

        Design: Difficulty/non_linear_state_machine/confined_space_permit_suspend_resume
        """
        reset_clock()
        station, trio, permit = setup_issued_permit()
        assert_instant_equal(permit["valid_until"], "2026-08-01T12:00:00Z")
        supervisor_headers = make_operator_headers(trio[2]["id"])
        res = api.activate_permit(permit["id"], supervisor_headers)
        assert validate_success(res, 200)["status"] == "ACTIVE"
        res = api.suspend_permit(permit["id"], supervisor_headers)
        assert validate_success(res, 200)["status"] == "SUSPENDED"
        res = api.activate_permit(permit["id"], supervisor_headers)
        reactivated = validate_success(res, 200)
        assert reactivated["status"] == "ACTIVE", "SUSPENDED -> ACTIVE loop closes"
        assert_instant_equal(reactivated["valid_until"], "2026-08-01T12:00:00Z")

    def test_full_loop_then_supervisor_close(self, api):
        """PRD §3.9: "Closing (`ACTIVE → CLOSED`) is again restricted to the
        named supervisor and stamps `closed_at`."
        PRD §3.9: "`CLOSED` and `CANCELLED` are terminal."

        Design: Difficulty/non_linear_state_machine/confined_space_permit_suspend_resume
        """
        reset_clock()
        station, trio, permit = setup_issued_permit()
        supervisor_headers = make_operator_headers(trio[2]["id"])
        api.activate_permit(permit["id"], supervisor_headers)
        api.suspend_permit(permit["id"], supervisor_headers)
        api.activate_permit(permit["id"], supervisor_headers)
        res = api.close_permit(permit["id"], supervisor_headers)
        closed = validate_success(res, 200)
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None
        res = api.activate_permit(permit["id"], supervisor_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestPermitValidityWindow:
    def test_activate_at_exactly_valid_until_rejected(self, api):
        """PRD §3.9: "Once issued, the permit may be activated (`ISSUED →
        ACTIVE`, and likewise `SUSPENDED → ACTIVE`) — but only while the current
        time is still before `valid_until`; activating at or after expiry is
        rejected with `ERR_PERMIT_EXPIRED` (HTTP 422)."
        PRD §3.9: "Issuance stamps `issued_at` and fixes `valid_until` at 12
        hours after issuance."

        Design: Difficulty/resource_temporal_overlap/confined_space_permit_validity_window
        """
        reset_clock()
        station, trio, permit = setup_issued_permit()
        assert_instant_equal(permit["valid_until"], "2026-08-01T12:00:00Z")
        reset_clock("2026-08-01T12:00:00Z")
        res = api.activate_permit(permit["id"], make_operator_headers(trio[2]["id"]))
        validate_error(res, ApiErrorId.ERR_PERMIT_EXPIRED)
        assert get_permit(permit["id"])["status"] == "ISSUED"

    def test_activate_one_second_before_valid_until_succeeds(self, api):
        """PRD §3.9: "Once issued, the permit may be activated (`ISSUED →
        ACTIVE`, and likewise `SUSPENDED → ACTIVE`) — but only while the current
        time is still before `valid_until`; activating at or after expiry is
        rejected with `ERR_PERMIT_EXPIRED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/confined_space_permit_validity_window
        """
        reset_clock()
        station, trio, permit = setup_issued_permit()
        reset_clock("2026-08-01T11:59:59Z")
        res = api.activate_permit(permit["id"], make_operator_headers(trio[2]["id"]))
        activated = validate_success(res, 200)
        assert activated["status"] == "ACTIVE", "strictly before valid_until is valid"
