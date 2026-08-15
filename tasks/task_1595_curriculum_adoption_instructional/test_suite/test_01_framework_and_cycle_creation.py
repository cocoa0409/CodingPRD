"""Framework registration, cycle creation, and material submission rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cycle,
    assert_framework,
    create_cycle,
    create_cycle_payload,
    create_framework,
    create_framework_payload,
    create_material_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["district_admin_headers"]
DIRECTOR = TEST_USERS["curriculum_director_headers"]


class TestFrameworkCreation:
    def test_framework_create_defaults(self, api):
        """PRD §3.1: "A framework is born `ACTIVE` unless its `status` is
        supplied otherwise, and only an `ACTIVE` framework may back a new
        cycle"
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/framework_create_defaults
        """
        payload = create_framework_payload(
            code="FW-ELA-68", subject_area="ENGLISH_LANGUAGE_ARTS",
            grade_band="GRADES_6_8", standards_required_count=12,
            effective_year=2026)
        data = validate_success(api.create_framework(payload, ADMIN),
                                expected_status=201)
        assert_framework(data)
        assert data["status"] == "ACTIVE", "status defaults to ACTIVE when omitted"
        assert data["standards_required_count"] == 12, "input echoed"
        assert is_valid_uuid(data["id"]), "id is a bare UUID with no type prefix"

        fetched = validate_success(api.get_framework(data["id"], DIRECTOR))
        assert fetched == data, "GET returns the same entity with identical values"


class TestCycleCreation:
    def test_cycle_create_missing_required_returns_validation(self, api):
        """PRD §2.7: "4. Request shape: required fields are present, enum
        values are in range, integer quantities and counts meet their bounds,
        prices are non-negative, payment and appropriation amounts are
        positive, an end date follows its start date, and pagination
        parameters are in range (`ERR_VALIDATION`, or
        `ERR_INVALID_PAGINATION_PARAMETERS` on list endpoints)."
        PRD §3.1: "a `CurriculumDirector` opens an adoption cycle by naming
        the `subject_area`, `grade_band`, the `school_year_start` in which the
        adopted materials will take effect, the backing `framework_id`, the
        `district_enrollment` for the grade band"

        Design: Corner/entities/cycle_create_missing_required_returns_validation
        """
        payload = {
            "subject_area": "MATHEMATICS",
            "grade_band": "K_5",
            "school_year_start": 2027,
            "district_enrollment": 100,
        }  # framework_id deliberately omitted
        err = validate_error(api.create_cycle(payload, DIRECTOR),
                             ApiErrorId.ERR_VALIDATION)
        assert err["message"].strip(), "error envelope carries a non-empty message"

    def test_cycle_create_framework_mismatch_rejected(self, api):
        """PRD §3.1: "The referenced framework must exist, be `ACTIVE`, and
        match the cycle on both subject area and grade band; a missing,
        retired, or mismatched framework is rejected with
        `ERR_FRAMEWORK_MISMATCH`."

        Design: Corner/entities/cycle_create_framework_mismatch_rejected
        """
        science = create_framework(
            code="FW-SCI-K5", subject_area="SCIENCE", grade_band="K_5",
            standards_required_count=1)
        retired = create_framework(
            code="FW-OLD", subject_area="MATHEMATICS", grade_band="K_5",
            standards_required_count=1, effective_year=2020, status="RETIRED")

        payload = create_cycle_payload(framework_id=science["id"])
        validate_error(api.create_cycle(payload, DIRECTOR),
                       ApiErrorId.ERR_FRAMEWORK_MISMATCH)

        payload = create_cycle_payload(framework_id=retired["id"])
        validate_error(api.create_cycle(payload, DIRECTOR),
                       ApiErrorId.ERR_FRAMEWORK_MISMATCH)

    def test_cycle_create_system_field_input_ignored(self, api):
        """PRD §3.1: "A new cycle starts in `DRAFT` status, and its budget
        ledger is created alongside it with all totals at zero."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments with every mutation of the resource."

        Design: Corner/entities/cycle_create_system_field_input_ignored
        """
        framework = create_framework()
        payload = create_cycle_payload(framework_id=framework["id"])
        payload["status"] = "ACTIVE"   # system-managed field supplied by client
        payload["version"] = 99        # system-managed field supplied by client
        data = validate_success(api.create_cycle(payload, DIRECTOR),
                                expected_status=201)
        assert_cycle(data)
        assert data["status"] == "DRAFT", "server stamps DRAFT, not the supplied value"
        assert data["version"] != 99, "server-managed version ignores the supplied 99"


class TestMaterialSubmission:
    def test_material_invalid_enum_rejected(self, api):
        """PRD §3.2: "an optional `material_type` that defaults to `CORE` and
        may instead be `SUPPLEMENTAL`"
        PRD §2.7: "4. Request shape: required fields are present, enum values
        are in range, integer quantities and counts meet their bounds, prices
        are non-negative, payment and appropriation amounts are positive, an
        end date follows its start date, and pagination parameters are in
        range (`ERR_VALIDATION`, or `ERR_INVALID_PAGINATION_PARAMETERS` on
        list endpoints)."

        Design: Corner/entities/material_invalid_enum_rejected
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        payload = create_material_payload(material_type="BOGUS")
        validate_error(api.create_material(cycle["id"], payload, DIRECTOR),
                       ApiErrorId.ERR_VALIDATION)
