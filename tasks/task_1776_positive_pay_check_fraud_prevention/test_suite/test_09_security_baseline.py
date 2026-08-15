"""Authentication and role-authorization baseline checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_enrollment_payload,
    validate_error,
)

BANK_OPS = TEST_USERS["bank_ops_headers"]


class TestAuthBaseline:
    def test_missing_auth_headers_rejected_before_lookup(self, api):
        """PRD §2.1: "A request in which either header is missing or malformed,
        or whose role name is not recognized, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.10: header presence and role recognition is priority 1, ahead of
        existence (priority 5), so even a nonexistent resource id yields the
        header error.

        Design: Corner/validations/missing_auth_headers
        """
        resp = api.get_enrollment(NON_EXISTENT_UUID, None)
        validate_error(resp,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_bankops_cannot_create_enrollment(self, api):
        """PRD §2.1: "A caller whose role is not listed for the endpoint, or a
        customer-role caller whose `EnrollmentUser.user_role` does not match the
        claimed role, is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: `POST /treasury/enrollments` authorizes BankTreasuryManager
        only.

        Design: Corner/rbac/bankops_cannot_create_enrollment
        """
        resp = api.create_enrollment(
            create_enrollment_payload(business_name="Nope"), BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
