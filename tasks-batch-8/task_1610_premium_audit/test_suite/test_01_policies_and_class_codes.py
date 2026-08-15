"""Policy and classification-code onboarding: defaults, shape validation,
uniqueness constraints."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_policy,
    create_class_code,
    create_classification_code_payload,
    create_policy,
    create_policy_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

UNDERWRITER = TEST_USERS["underwriter_headers"]
MANAGER = TEST_USERS["audit_manager_headers"]


class TestPolicyCreation:
    def test_policy_creation_applies_defaults_and_system_fields(self, api):
        """PRD: "The `experience_mod_factor` is optional and defaults to 1.00"
        PRD: "A new policy begins life `ACTIVE`."
        PRD: "`version` (integer): starts at 1 and increments by one on every
        mutation of the resource."

        Design: Corner/entities/policy_creation_defaults_and_system_fields
        """
        cc = create_class_code()

        resp = api.create_policy(
            create_policy_payload(policy_number="WC-D1",
                                  class_code_ids=[cc["id"]]),
            UNDERWRITER)
        policy = validate_success(resp, 201)

        assert_policy(policy)
        assert policy["experience_mod_factor"] == 1.00, (
            f"Omitted experience_mod_factor must default to 1.00, got "
            f"{policy['experience_mod_factor']!r}")
        assert policy["status"] == "ACTIVE"
        assert policy["version"] == 1
        assert is_valid_uuid(policy["id"])
        assert is_iso8601_timestamp(policy["created_at"])

    def test_policy_creation_rejects_undeclared_status_field(self, api):
        """PRD: "2. **Request shape** — required fields present, types valid,
        enum members valid, date orderings respected (`effective_date` strictly
        before `expiration_date`; `scheduled_end` strictly after
        `scheduled_start`; `coverage_effective_date` at or before
        `coverage_expiration_date`; `period_start` strictly before
        `period_end`), amounts non-negative, `minimum_premium_cents` not
        exceeding `estimated_annual_premium_cents`, a WC policy's
        `experience_mod_factor` within the inclusive band from 0.75 to 1.50, a
        GL policy's `experience_mod_factor` exactly 1.00, and no undeclared
        fields; any failure yields `ERR_VALIDATION` (400)."

        Design: Corner/entities/policy_creation_unknown_field_rejected
        """
        cc = create_class_code()

        payload = create_policy_payload(policy_number="WC-D2",
                                        class_code_ids=[cc["id"]])
        payload["status"] = "CANCELLED"  # system-owned, undeclared input
        resp = api.create_policy(payload, UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_policy_not_found_returns_404(self, api):
        """PRD: "Wherever a request carries path identifiers or foreign-key
        references, the server validates existence from left to right,
        rejecting with the not-found code of the first unresolvable
        identifier."
        PRD: "6. **Existence** — path identifiers and foreign-key inputs
        resolve, validated left to right; failure yields the matching one of
        `ERR_POLICY_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`,
        `ERR_CLASS_CODE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_SUB_EXPOSURE_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_AUDIT_RESULT_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_BILLING_NOT_FOUND`, or
        `ERR_MOD_REVISION_NOT_FOUND` (all 404)."

        Design: Corner/entities/policy_get_not_found_returns_404
        """
        resp = api.get_policy(NON_EXISTENT_UUID, MANAGER)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_FOUND)

    def test_gl_policy_with_non_default_mod_rejected(self, api):
        """PRD: "The `experience_mod_factor` is optional and defaults to 1.00;
        on a WC policy it must sit within the inclusive band 0.75 to 1.50,
        while on a GL policy it must equal exactly 1.00."

        Design: Corner/entities/gl_policy_mod_constraint_rejected
        """
        cc = create_class_code(code="1001", description="GL Retail",
                               coverage_line="GL", rate_per_100_cents=300)

        resp = api.create_policy(
            create_policy_payload(policy_number="GL-1", coverage_line="GL",
                                  experience_mod_factor=1.10,
                                  class_code_ids=[cc["id"]]),
            UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_duplicate_policy_number_rejected(self, api):
        """PRD: "An `Underwriter` onboards a policy by supplying its
        `policy_number` — unique across the carrier, with duplicates rejected
        by `ERR_DUPLICATE_POLICY_NUMBER`"

        Design: Corner/entities/duplicate_policy_number_rejected
        """
        cc = create_class_code()
        create_policy("WC-DUP", [cc["id"]], expiration_date="2026-12-31T00:00:00Z")

        resp = api.create_policy(
            create_policy_payload(policy_number="WC-DUP", insured_name="Second",
                                  expiration_date="2026-12-31T00:00:00Z",
                                  estimated_annual_premium_cents=700000,
                                  class_code_ids=[cc["id"]]),
            UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLICY_NUMBER)

    def test_duplicate_class_code_triple_rejected(self, api):
        """PRD: "The triple of code digits, state, and coverage line is
        unique; reusing it is rejected with `ERR_DUPLICATE_CLASS_CODE`."

        Design: Corner/entities/duplicate_class_code_rejected
        """
        create_class_code(code="8810", state_code="CA", coverage_line="WC")

        dup = api.create_classification_code(
            create_classification_code_payload(code="8810", state_code="CA",
                                               coverage_line="WC",
                                               rate_per_100_cents=41),
            UNDERWRITER)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_CLASS_CODE)

        other_state = api.create_classification_code(
            create_classification_code_payload(code="8810", state_code="NY",
                                               coverage_line="WC",
                                               rate_per_100_cents=55),
            UNDERWRITER)
        created = validate_success(other_state, 201)
        assert created["state_code"] == "NY"
        assert created["code"] == "8810"


class TestPolicyShapeValidation:
    def test_policy_create_missing_policy_number_returns_400(self, api):
        """PRD: "2. **Request shape** — required fields present, types valid,
        enum members valid, date orderings respected (`effective_date` strictly
        before `expiration_date`; `scheduled_end` strictly after
        `scheduled_start`; `coverage_effective_date` at or before
        `coverage_expiration_date`; `period_start` strictly before
        `period_end`), amounts non-negative, `minimum_premium_cents` not
        exceeding `estimated_annual_premium_cents`, a WC policy's
        `experience_mod_factor` within the inclusive band from 0.75 to 1.50, a
        GL policy's `experience_mod_factor` exactly 1.00, and no undeclared
        fields; any failure yields `ERR_VALIDATION` (400)."

        Design: Corner/validations/policy_create_missing_required_field_returns_400
        """
        cc = create_class_code()

        payload = create_policy_payload(class_code_ids=[cc["id"]])
        del payload["policy_number"]
        resp = api.create_policy(payload, UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_policy_create_invalid_coverage_line_returns_400(self, api):
        """PRD: "2. **Request shape** — required fields present, types valid,
        enum members valid, date orderings respected (`effective_date` strictly
        before `expiration_date`; `scheduled_end` strictly after
        `scheduled_start`; `coverage_effective_date` at or before
        `coverage_expiration_date`; `period_start` strictly before
        `period_end`), amounts non-negative, `minimum_premium_cents` not
        exceeding `estimated_annual_premium_cents`, a WC policy's
        `experience_mod_factor` within the inclusive band from 0.75 to 1.50, a
        GL policy's `experience_mod_factor` exactly 1.00, and no undeclared
        fields; any failure yields `ERR_VALIDATION` (400)."
        PRD: "the `coverage_line` (either `WC` for workers' compensation or
        `GL` for general liability)"

        Design: Corner/validations/policy_create_invalid_enum_returns_400
        """
        cc = create_class_code()

        resp = api.create_policy(
            create_policy_payload(policy_number="WC-BADENUM",
                                  coverage_line="AUTO",
                                  class_code_ids=[cc["id"]]),
            UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_policy_create_expiration_before_effective_returns_400(self, api):
        """PRD: "the `effective_date` and `expiration_date` bounding the term
        (the former strictly earlier than the latter)"
        PRD: "2. **Request shape** — required fields present, types valid,
        enum members valid, date orderings respected (`effective_date` strictly
        before `expiration_date`; `scheduled_end` strictly after
        `scheduled_start`; `coverage_effective_date` at or before
        `coverage_expiration_date`; `period_start` strictly before
        `period_end`), amounts non-negative, `minimum_premium_cents` not
        exceeding `estimated_annual_premium_cents`, a WC policy's
        `experience_mod_factor` within the inclusive band from 0.75 to 1.50, a
        GL policy's `experience_mod_factor` exactly 1.00, and no undeclared
        fields; any failure yields `ERR_VALIDATION` (400)."

        Design: Corner/validations/policy_create_expiration_before_effective_returns_400
        """
        cc = create_class_code()

        resp = api.create_policy(
            create_policy_payload(policy_number="WC-BADDATES",
                                  effective_date="2026-07-01T00:00:00Z",
                                  expiration_date="2026-01-01T00:00:00Z",
                                  class_code_ids=[cc["id"]]),
            UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
