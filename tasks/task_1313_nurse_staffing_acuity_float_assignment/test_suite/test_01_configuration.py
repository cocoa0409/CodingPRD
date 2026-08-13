"""Configuration surface: units, nurses, and the staffing matrix."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_nursing_unit,
    create_unit,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestUnitCreation:

    def test_unit_creation_computed_defaults(self):
        """PRD section 3.1: "The unit's `incentive_reserved_cents` and
        `incentive_spent_cents` are computed ledger fields, initialized to zero
        at creation and maintained thereafter per §2.10."
        PRD section 2.4: "`id` (string): a server-minted UUID, with no type
        prefix."

        Design: Corner/entities/unit_creation_computed_defaults
        """
        resp = api_client.create_unit(
            {"name": "Tele 3", "unit_type": "TELEMETRY", "bed_count": 24,
             "incentive_budget_cents": 250000},
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_nursing_unit(data)
        assert data["incentive_reserved_cents"] == 0
        assert data["incentive_spent_cents"] == 0
        assert is_valid_uuid(data["id"])
        assert isinstance(data["version"], int)


class TestNurseCreation:

    def test_nurse_core_without_home_unit_rejected(self):
        """PRD section 3.1: "Violating either half of that rule — a core nurse
        without a home unit, or a float-pool nurse with one — is rejected with
        `ERR_HOME_UNIT_RULE_VIOLATED`."

        Design: Corner/entities/nurse_core_without_home_unit_rejected
        """
        resp = api_client.create_nurse(
            {"full_name": "No Home", "employment_type": "CORE",
             "competencies": ["ICU"], "base_hourly_rate_cents": 5000},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_HOME_UNIT_RULE_VIOLATED)

    def test_nurse_float_with_home_unit_rejected(self):
        """PRD section 3.1: "Violating either half of that rule — a core nurse
        without a home unit, or a float-pool nurse with one — is rejected with
        `ERR_HOME_UNIT_RULE_VIOLATED`."

        Design: Corner/entities/nurse_float_with_home_unit_rejected
        """
        unit = create_unit(name="ICU X", unit_type="ICU", bed_count=10,
                           incentive_budget_cents=100000)
        resp = api_client.create_nurse(
            {"full_name": "Float Frank", "employment_type": "FLOAT_POOL",
             "competencies": ["ICU"], "base_hourly_rate_cents": 6000,
             "home_unit_id": unit["id"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_HOME_UNIT_RULE_VIOLATED)

    def test_nurse_invalid_employment_enum_rejected(self):
        """PRD section 3.1: "an `employment_type` of `CORE` or `FLOAT_POOL`".
        PRD section 2.5: "Required fields are present, enum values are
        in-domain, numeric ranges are valid, an observation window's `end_at`
        is strictly after its `start_at`, and a week ledger query's
        `week_start` falls on a Monday — any violation yields
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/nurse_invalid_employment_enum_rejected
        """
        resp = api_client.create_nurse(
            {"full_name": "Bad Enum", "employment_type": "AGENCY",
             "competencies": ["ICU"], "base_hourly_rate_cents": 5000},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMatrixRules:

    def test_matrix_rule_duplicate_rejected(self):
        """PRD section 3.1: "The (unit type, acuity level) pair is unique
        across the matrix: a second rule for the same pair is rejected with
        `ERR_MATRIX_RULE_EXISTS`."

        Design: Corner/entities/matrix_rule_duplicate_rejected
        """
        first = api_client.create_matrix_rule(
            {"unit_type": "ICU", "acuity_level": "LOW",
             "patients_per_nurse": 4},
            ADMIN,
        )
        validate_success(first, expected_status=201)
        resp = api_client.create_matrix_rule(
            {"unit_type": "ICU", "acuity_level": "LOW",
             "patients_per_nurse": 3},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_MATRIX_RULE_EXISTS)
