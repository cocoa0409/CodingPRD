"""Payer policy configuration, patient intake, requirement lookup, and the
response envelope / authentication contract."""
from test_helpers import (
    ApiErrorId,
    create_patient_payload,
    create_policy_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
    assert_payer_policy,
    NON_EXISTENT_UUID,
    POLICY_ADMIN_HEADERS,
    AUTH_COORDINATOR_HEADERS,
    SCHEDULER_HEADERS,
)


class TestPolicyDefaults:
    def test_policy_creation_applies_declared_defaults(self, api):
        """PRD §3.1: "Policies are assumed to require prior authorization unless
        `requires_prior_auth` is explicitly set false on creation."
        PRD §3.1: "When `buy_and_bill_required` is true (it defaults to false),
        the provider must procure the drug under the medical channel, and a later
        pharmacy-channel verification is refused as a routing violation (§3.3)."
        PRD §3.1: "Authorization longevity is governed by `validity_days` for the
        medical channel and `pharmacy_validity_days` for the pharmacy channel,
        the latter defaulting to 30 days, while `max_course_days` caps the total
        course of therapy regardless of channel."
        PRD §3.1: "Financial behavior is shaped by `allowed_amount_known`
        (default true), which selects the estimation method described in §3.6;
        by the `discount_rate` (default 0.80) applied to billed charges when
        allowed amounts are not published; and by the reference values
        `deductible_cents`, `coinsurance_pct`, and `oop_max_cents`."
        PRD §3.1: "Site-of-care posture lives in `site_policy`, one of
        `NO_STEERING` (the default), `STEER_TO_HOME`, or `STEER_TO_OFFICE`,
        paired with `steer_threshold` (default 1.50), the score at or above
        which steering fires."
        PRD §2.5: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/payer_policy_create_defaults_applied
        """
        payload = {
            "payer_code": "PAYERD",
            "drug_code": "J9100",
            "regimen_name": "Defaults",
            "benefit_channel": "MEDICAL",
            "validity_days": 90,
            "max_course_days": 60,
            "max_dose_mg": 1000,
            "deductible_cents": 100000,
            "coinsurance_pct": 0.20,
            "oop_max_cents": 500000,
            "prepay_limit_cents": 250000,
        }
        policy = validate_success(
            api.create_payer_policy(payload, POLICY_ADMIN_HEADERS), 201)
        assert_payer_policy(policy)
        assert policy["requires_prior_auth"] is True
        assert policy["buy_and_bill_required"] is False
        assert policy["pharmacy_validity_days"] == 30
        assert policy["allowed_amount_known"] is True
        assert policy["discount_rate"] == 0.80
        assert policy["site_policy"] == "NO_STEERING"
        assert policy["steer_threshold"] == 1.50
        assert is_valid_uuid(policy["id"]), "id is a server-minted bare UUID"


class TestPatientIntake:
    def test_create_patient_missing_required_field_rejected(self, api):
        """PRD §2.9: "**Request-body shape** — required fields present, enum
        values valid, datetime fields parseable, and wherever a time window is
        supplied the `scheduled_end` strictly after the `scheduled_start`;
        violations carry `ERR_VALIDATION_FAILED` (400)."
        PRD §3.2: "An `AuthCoordinator` registers each patient with the payer's
        `member_id`, the patient's `full_name`, the primary `diagnosis_code`
        (ICD-10), and the `payer_code` the patient is enrolled with."

        Design: Corner/entities/create_patient_missing_required_returns_validation_failed
        """
        payload = create_patient_payload(full_name="No Member")
        del payload["member_id"]
        resp = api.create_patient(payload, AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


class TestPolicyUniqueness:
    def test_duplicate_payer_drug_pair_rejected(self, api):
        """PRD §3.1: "The combination of `payer_code` and `drug_code` is unique
        across the system: attempting to author a second policy with a pair
        already on file is rejected with `ERR_DUPLICATE_POLICY` (409)."

        Design: Corner/validations/duplicate_policy_rejected
        """
        first = create_policy_payload(drug_code="J9140", regimen_name="Dup")
        validate_success(api.create_payer_policy(first, POLICY_ADMIN_HEADERS), 201)

        duplicate = create_policy_payload(
            drug_code="J9140", regimen_name="Dup2", validity_days=30,
            max_course_days=30, max_dose_mg=500, deductible_cents=0,
            coinsurance_pct=0.10, oop_max_cents=100000, prepay_limit_cents=50000)
        resp = api.create_payer_policy(duplicate, POLICY_ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLICY)

        other = create_policy_payload(drug_code="J9141", regimen_name="Ok")
        created = validate_success(
            api.create_payer_policy(other, POLICY_ADMIN_HEADERS), 201)
        assert is_valid_uuid(created["id"]), "A different drug_code succeeds"


class TestRequirementLookup:
    def test_lookup_returns_policy_profile_and_404_on_miss(self, api):
        """PRD §3.1: "Any authorized role may run the authorization-requirement
        lookup, passing a `payer_code` and a `drug_code`; the response carries
        the matching policy's `policy_id`, `requires_prior_auth`,
        `benefit_channel`, `validity_days`, `pharmacy_validity_days`,
        `max_dose_mg`, `site_policy`, and `buy_and_bill_required`."
        PRD §3.1: "When no policy matches the pair, the lookup is rejected with
        `ERR_POLICY_NOT_FOUND`."

        Design: Corner/endpoints/lookup_requirement_profile_hit_and_miss
        """
        policy = validate_success(api.create_payer_policy(
            create_policy_payload(drug_code="J9161", regimen_name="Lookup"),
            POLICY_ADMIN_HEADERS), 201)

        hit = validate_success(api.lookup_authorization_requirements(
            AUTH_COORDINATOR_HEADERS,
            params={"payer_code": "PAYERX", "drug_code": "J9161"}))
        assert hit["policy_id"] == policy["id"]
        assert hit["requires_prior_auth"] is True
        assert hit["benefit_channel"] == "MEDICAL"
        assert hit["validity_days"] == 90
        assert hit["pharmacy_validity_days"] == 30
        assert hit["max_dose_mg"] == 1000
        assert hit["site_policy"] == "NO_STEERING"
        assert hit["buy_and_bill_required"] is False

        miss = api.lookup_authorization_requirements(
            AUTH_COORDINATOR_HEADERS,
            params={"payer_code": "PAYERX", "drug_code": "JXXXX"})
        validate_error(miss, ApiErrorId.ERR_POLICY_NOT_FOUND)


class TestAuthentication:
    def test_request_without_auth_headers_is_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside this declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/create_policy_missing_auth_header_unauthenticated
        """
        resp = api.create_payer_policy(
            create_policy_payload(drug_code="J9130", regimen_name="NoHdr"), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_scheduler_cannot_create_policy(self, api):
        """PRD §2.1: "A well-formed request whose role is not listed among the
        endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: POST /infusion/payer-policies is authorized for PolicyAdmin
        only.

        Design: Corner/rbac/scheduler_cannot_create_policy
        """
        resp = api.create_payer_policy(
            create_policy_payload(drug_code="J9171", regimen_name="RBAC2"),
            SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        miss = api.lookup_authorization_requirements(
            AUTH_COORDINATOR_HEADERS,
            params={"payer_code": "PAYERX", "drug_code": "J9171"})
        validate_error(miss, ApiErrorId.ERR_POLICY_NOT_FOUND)


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.9: "the first missing reference yields that resource's dedicated
        404: `ERR_PATIENT_NOT_FOUND`"

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.get_patient(NON_EXISTENT_UUID, AUTH_COORDINATOR_HEADERS)
        error = validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["message"].strip(), "data.message must be non-empty"
        meta = body["meta"]
        assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
            f"error meta must carry only the two request fields, got {sorted(meta)}"
        )
