"""Authentication and role-based access control checks."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_period_payload,
    set_clock, create_period,
    CONTROLLER, PREPARER, APPROVER, AUDITOR,
)
from test_helpers import api_client


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD §2.1: "A request with a missing or invalid role header — or, where a
        role requires it, a missing user header — is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        set_clock()
        # call without any role/user headers
        res = api.list_periods(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_forbidden_role_on_exclusive_endpoint(self, api):
        """PRD §2.1: "A `Controller` is the corporate controller: owner of the
        close calendar, close periods, legal-entity registrations, FX rates, locks
        and reopens, finalization, flux adjudication, and task waivers".
        PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/forbidden_role_on_exclusive_endpoint
        """
        set_clock()
        res = api.create_period(create_period_payload(), PREPARER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_auditor_read_only_cannot_mutate(self, api):
        """PRD §2.1: "An `Auditor` is a read-only post-close reviewer with access
        to the full read surface, including the audit event trail, and no mutation
        rights whatsoever."
        PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/auditor_read_only_cannot_mutate
        """
        set_clock()
        period = create_period()
        res = api.open_period(period["id"], AUDITOR)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        # Auditor CAN still read the period
        fetched = validate_success(api.get_period(period["id"], AUDITOR), 200)
        assert fetched["id"] == period["id"]
