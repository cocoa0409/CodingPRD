"""Request guardrails: authentication, authorization, 404s, field-shape rules,
and role-exclusive denials (PRD §2.1, §2.8, §4, §5)."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId, create_nutrient_profile_payload, create_audit_payload,
    create_supplier_payload, create_system_user_payload, assert_system_user,
    create_released_batch_scenario,
)


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing, empty, or contains a role
        value the system does not recognize, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        res = api.list_nutrient_profiles(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_complaint_handler_cannot_create_nutrient_profile(self, api, users):
        """PRD §2.1: "If the role is recognized but not authorized for the
        requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)." POST /api/v1/nutrient-profiles is a REGULATORY_AFFAIRS
        endpoint (PRD §4), so a COMPLAINT_HANDLER caller is refused.

        Design: Corner/validations/unauthorized_role_returns_403
        """
        res = api.create_nutrient_profile(
            create_nutrient_profile_payload(), users["ch"]["headers"])
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


class TestSystemUserAdmin:
    def test_admin_creates_system_user(self, api, admin_headers):
        """PRD §2.1: "A `SystemUser` resource stores `username` (unique),
        `full_name`, `role`, and `department`. Only an `ADMIN` may create new
        `SystemUser` records." PRD §4: "Operations that create a new resource —
        whether a top-level resource or a child resource added to a parent's
        collection — return `201 Created`."

        Design: Corner/rbac/admin_can_access_system_users
        """
        res = api.create_system_user(
            create_system_user_payload(
                username="qa_mgr_01", full_name="QA Manager One",
                role="QA_MANAGER", department="Quality Assurance"),
            admin_headers)
        data = validate_success(res, 201)
        assert data["username"] == "qa_mgr_01"
        assert data["role"] == "QA_MANAGER"
        assert_system_user(data)


class TestFieldShapeRules:
    def test_missing_required_profile_code_rejected(self, api, users):
        """PRD §2.8: "Validation is applied in a fixed priority order across all
        endpoints. ... and finally field shape rules (required-field presence,
        enum membership, numeric range) with the OCC version check applied
        immediately before write commit." `profile_code` is a required input
        (PRD §3.1); the only 400-tier error in the catalogue (PRD §5) is
        `ERR_INVALID_REQUEST`.

        Design: Corner/entities/missing_required_field_returns_invalid_request
        """
        payload = create_nutrient_profile_payload()
        del payload["profile_code"]
        res = api.create_nutrient_profile(payload, users["ra1"]["headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_audit_score_above_100_rejected(self, api, users):
        """PRD §3.2: an AuditRecord carries "a numeric `score` between 0 and 100
        with 2 decimal places". PRD §2.8 lists "numeric range" among the field
        shape rules; the catalogue's numeric-range error is `ERR_INVALID_RANGE`
        (HTTP 422, PRD §5).

        Design: Corner/validations/invalid_numeric_range_returns_422
        """
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(), users["qm"]["headers"]), 201)
        res = api.create_audit(
            supplier["id"],
            create_audit_payload(score=101.00),
            users["qa"]["headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_RANGE)


class TestNotFound:
    def test_get_nonexistent_nutrient_profile_returns_404(self, api, users):
        """PRD §2.8: "the path parameters are validated left-to-right: the
        parent identifier is resolved first, and only if it exists does the
        system resolve the child identifier. A failure at any level is rejected
        with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_nutrient_profile_returns_404
        """
        res = api.get_nutrient_profile(NON_EXISTENT_UUID, users["ra1"]["headers"])
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestRoleExclusiveDenial:
    def test_production_supervisor_cannot_release_batch(self, api, users):
        """PRD §4: `POST /api/v1/production-batches/{id}/release` is authorized
        for QA_MANAGER only. PRD §2.1: "If the role is recognized but not
        authorized for the requested endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)." PRD §2.8: authorization runs before
        state-machine validity, so a PRODUCTION_SUPERVISOR caller is refused
        with 403 regardless of batch state.

        Design: Corner/rbac/production_supervisor_cannot_release_batch
        """
        scenario = create_released_batch_scenario(users)
        res = api.release_batch(scenario["batch"]["id"], users["ps"]["headers"])
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
