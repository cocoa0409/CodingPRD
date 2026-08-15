"""Access control: header presence, role recognition, and role permission."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_member,
    create_tier,
    make_member_headers,
    validate_error,
)


class TestUserContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act. A request missing either header, or naming a role
        the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.list_tiers(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or naming a role the
        system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.list_tiers(headers={"X-User-Role": "ClubAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


class TestRolePermission:
    def test_member_denied_admin_only_operations(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.11: "First, header presence and role recognition
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT`), then role permission for the
        endpoint (`ERR_FORBIDDEN_ROLE`). Next, existence".
        PRD §4 restricts `POST /soaring/ops-day/close` and
        `POST /soaring/student-progress/{id}/verify` to ClubAdmin.

        Design: Corner/rbac/member_cannot_verify_progress_or_close_day
        """
        tier = create_tier(tier_code="RB", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Role Member")
        headers = make_member_headers(member["id"])

        resp = api.close_ops_day(headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        # Role permission is checked before existence, so even an unknown
        # record id surfaces the role denial.
        resp = api.verify_progress(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
