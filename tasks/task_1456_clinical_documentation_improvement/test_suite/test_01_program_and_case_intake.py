"""Program setup, case intake defaults, and program lifecycle gating."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_cdi_program,
    assert_patient_case,
    assert_provider,
    create_case,
    create_cdi_program_payload,
    create_patient_case_payload,
    create_program,
    create_provider,
    get_success_data,
    validate_error,
    validate_success,
)


class TestProgramCreation:
    def test_program_creation_stores_all_input_fields(self, api, cdi_manager_headers):
        """PRD §3.1: "A `CDIManager` establishes a `CDIProgram` by supplying a
        `facility_name`, a unique `program_code`, and the program's `baseline_cmi`"
        PRD §3.1: "The new program begins in `ACTIVE` status with
        `current_period_index` set to 0."

        Design: Corner/entities/cdi_program_creation_stores_all_input_fields
        """
        payload = {"facility_name": "Metro", "program_code": "M1", "baseline_cmi": 1.2345}
        created = validate_success(
            api.create_cdi_program(payload, cdi_manager_headers), expected_status=201
        )
        assert_cdi_program(created)
        fetched = validate_success(api.get_cdi_program(created["id"], cdi_manager_headers))
        assert fetched["facility_name"] == "Metro"
        assert fetched["program_code"] == "M1"
        assert fetched["baseline_cmi"] == pytest.approx(1.2345, abs=1e-9)
        assert fetched["status"] == "ACTIVE"
        assert fetched["current_period_index"] == 0


class TestCaseIntakeDefaults:
    def test_case_creation_applies_system_defaults(self, api, him_coder_headers):
        """PRD §3.2: "At registration the case's working documentation mirrors the
        coder's first pass: `working_drg_code` and `working_drg_weight` start equal
        to the initial values, `working_soi` and `working_rom` both start at 1,
        `reconciliation_status` starts at `NOT_REQUIRED`, and `status` starts at
        `OPEN`."

        Design: Corner/entities/patient_case_creation_applies_system_defaults
        """
        program = create_program()
        provider = create_provider(program["id"])
        payload = create_patient_case_payload(
            program["id"], provider["id"],
            discharge_period=5, initial_drg_code="DRG-A", initial_drg_weight=1.2345,
        )
        case = validate_success(
            api.create_patient_case(payload, him_coder_headers), expected_status=201
        )
        assert_patient_case(case)
        assert case["working_soi"] == 1
        assert case["working_rom"] == 1
        assert case["working_drg_code"] == "DRG-A"
        assert case["working_drg_weight"] == pytest.approx(1.2345, abs=1e-9)
        assert case["status"] == "OPEN"
        assert case["reconciliation_status"] == "NOT_REQUIRED"

    def test_new_case_priority_score_starts_at_zero(self, api):
        """PRD §3.2: "Because a newly registered case has no queries at all, its
        initial `priority_score` uses the residual variant and therefore starts at
        zero."

        Design: Corner/entities/patient_case_creation_applies_system_defaults
        """
        program = create_program()
        provider = create_provider(program["id"])
        case = create_case(program["id"], provider["id"], initial_drg_weight=1.2345)
        assert case["priority_score"] == pytest.approx(0.0, abs=1e-9)


class TestProviderRegistration:
    def test_provider_education_score_is_computed_not_input(self):
        """PRD §3.1: "New providers start with an `education_score` of 100, an
        `education_flag` of `NONE`, and an empty `pattern_tally_json` map."

        Design: Corner/entities/provider_education_score_is_computed_not_input
        """
        program = create_program()
        provider = create_provider(program["id"])
        assert_provider(provider)
        assert provider["education_score"] == 100
        assert provider["education_flag"] == "NONE"
        assert provider["pattern_tally_json"] == {}


class TestExistenceAndSchema:
    def test_get_case_not_found(self, api, cdi_manager_headers):
        """PRD §2.9: "the system validates them sequentially from left to right and
        rejects the request with `ERR_NOT_FOUND` at the first identifier that does
        not resolve to an existing resource."

        Design: Corner/entities/patient_case_get_not_found
        """
        create_program()
        resp = api.get_patient_case(NON_EXISTENT_UUID, cdi_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_case_missing_mrn_returns_invalid_request(self, api, him_coder_headers):
        """PRD §3.2: "An `HIMCoder` registers a `PatientCase` by supplying the
        owning `cdi_program_id`, a medical record number `mrn` unique within the
        program, the `admission_period` and `discharge_period` ..."
        PRD §5: "`ERR_INVALID_REQUEST` | 400"

        Design: Corner/entities/patient_case_missing_mrn_returns_invalid_request
        """
        program = create_program()
        provider = create_provider(program["id"])
        payload = {
            "cdi_program_id": program["id"],
            "admission_period": 0,
            "discharge_period": 5,
            "attending_provider_id": provider["id"],
            "initial_drg_code": "A",
            "initial_drg_weight": 1.0,
        }
        resp = api.create_patient_case(payload, him_coder_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_denial_target_invalid_window_returns_invalid_request(self, api, cdi_manager_headers):
        """PRD §3.9: "A target whose `active_to_period` is earlier than its
        `active_from_period` is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/denial_target_invalid_window_returns_invalid_request
        """
        program = create_program()
        resp = api.create_denial_risk_target(
            {
                "cdi_program_id": program["id"],
                "drg_code": "A",
                "required_evidence_tags": ["t"],
                "severity_floor": 1,
                "active_from_period": 5,
                "active_to_period": 4,
            },
            cdi_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProgramLifecycle:
    def test_close_from_closed_returns_invalid_state(self, api, cdi_manager_headers):
        """PRD §3.1: "Closure moves a program from either `ACTIVE` or `SUSPENDED`
        to `CLOSED`; it is rejected with `ERR_INVALID_STATE` from any other state"

        Design: Corner/state_machines/cdi_program_close_from_closed_returns_invalid_state
        """
        program = create_program()
        validate_success(api.close_cdi_program(program["id"], cdi_manager_headers))
        resp = api.close_cdi_program(program["id"], cdi_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_suspend_blocks_patient_case_create(self, api, him_coder_headers, cdi_manager_headers):
        """PRD §2.6: "Any attempt to create or modify a resource belonging to a
        program in `SUSPENDED` or `CLOSED` status is rejected with
        `ERR_PROGRAM_NOT_ACTIVE`."

        Design: Corner/state_machines/cdi_program_suspend_blocks_patient_case_create
        """
        program = create_program()
        provider = create_provider(program["id"])
        validate_success(api.suspend_cdi_program(program["id"], cdi_manager_headers))
        payload = create_patient_case_payload(program["id"], provider["id"])
        resp = api.create_patient_case(payload, him_coder_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)

    def test_close_blocked_by_open_case(self, api, cdi_manager_headers):
        """PRD §3.1: "and with `ERR_OPEN_CASES_REMAIN` whenever any patient case in
        the program is still in `OPEN`, `UNDER_REVIEW`, or `RECONCILED` status."

        Design: Corner/state_machines/cdi_program_close_blocked_by_open_case
        """
        program = create_program()
        provider = create_provider(program["id"])
        create_case(program["id"], provider["id"])
        resp = api.close_cdi_program(program["id"], cdi_manager_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_CASES_REMAIN)
