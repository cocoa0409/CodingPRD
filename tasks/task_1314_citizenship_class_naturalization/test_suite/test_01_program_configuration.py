"""Program configuration: singleton creation and declared defaults (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    PROGRAM_DEFAULTS,
    TEST_USERS,
    assert_program,
    create_program,
    is_valid_uuid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestProgramConfiguration:
    def test_program_creation_applies_declared_defaults(self, api):
        """PRD §3.1: "A `ProgramAdmin` creates it once, supplying a `name` and
        optionally overriding any parameter; every omitted parameter takes its
        declared default."
        PRD §3.1: "The fee schedule comprises three lines in integer cents:
        `n400_fee_cents` (default 76000) for the N-400 application fee,
        `biometric_fee_cents` (default 8501) for biometric services, and
        `translation_stipend_cents` (default 3001) as a document translation
        pass-through."
        PRD §3.1: "`poverty_base_cents` (default 1565000, the guideline for a
        household of one) and `poverty_per_additional_cents` (default 550000 for each
        additional household member), together with `full_waiver_threshold_pct`
        (default 150) and `partial_waiver_threshold_pct` (default 200)."

        Design: Corner/entities/program_creation_applies_declared_defaults
        """
        created = validate_success(api.create_program({"name": "Main"}, ADMIN), 201)
        assert_program(created)
        assert is_valid_uuid(created["id"]), "id must be a bare UUID with no type prefix"
        assert created["version"] == 1

        current = validate_success(api.get_current_program(ADMIN), 200)
        assert_program(current)
        assert current["id"] == created["id"]
        for field, expected in PROGRAM_DEFAULTS.items():
            assert current[field] == expected, (
                f"Program.{field}: expected declared default {expected}, "
                f"got {current[field]}"
            )

    def test_program_second_create_rejected_singleton(self, api):
        """PRD §3.1: "A second attempt to create the Program is rejected with
        `ERR_PROGRAM_EXISTS`."

        Design: Corner/entities/program_second_create_rejected_singleton
        """
        create_program()
        response = api.create_program({"name": "Second"}, ADMIN)
        validate_error(response, ApiErrorId.ERR_PROGRAM_EXISTS)
