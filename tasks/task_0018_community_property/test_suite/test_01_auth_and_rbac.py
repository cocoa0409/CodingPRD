"""Auth and RBAC tests (PRD §2.1, §2.6).

Covers:
- Missing / malformed auth headers → ERR_AUTH_MISSING
- Unrecognized X-User-Role → ERR_AUTH_INVALID_ROLE
- Role recognized but not permitted for endpoint → ERR_FORBIDDEN
- Identity mismatch on Owner-bound resources → ERR_FORBIDDEN
- MaintenanceStaff identity binding after dispatch (PRD §2.1)
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    create_owner_payload,
    create_owner_with_property,
    create_work_order_payload,
    dispatch_work_order_payload,
    make_maintenance_headers,
    make_owner_headers,
    progress_work_order_to_resolved,
    submit_work_order,
    validate_error,
)


class TestAuthHeadersMissing:
    """PRD §2.1: "If either header is missing or empty the request is rejected
    with ERR_AUTH_MISSING (HTTP 401)." """

    def test_missing_both_headers(self, api):
        """PRD §2.1: "If either header is missing or empty the request is rejected
        with ERR_AUTH_MISSING (HTTP 401)."

        Claim: empty headers → ERR_AUTH_MISSING.
        """
        res = api.create_owner(create_owner_payload(), headers={})
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_id_header(self, api):
        """PRD §2.1: "If either header is missing or empty the request is rejected
        with ERR_AUTH_MISSING (HTTP 401)."

        Claim: only X-User-Role present → ERR_AUTH_MISSING.
        """
        res = api.create_owner(
            create_owner_payload(),
            headers={"X-User-Role": "PropertyManager", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header(self, api):
        """PRD §2.1: "If either header is missing or empty the request is rejected
        with ERR_AUTH_MISSING (HTTP 401)."

        Claim: only X-User-ID present → ERR_AUTH_MISSING.
        """
        res = api.create_owner(
            create_owner_payload(),
            headers={"X-User-ID": "some-id", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_empty_user_id_header(self, api):
        """PRD §2.1: "If either header is missing or empty the request is rejected
        with ERR_AUTH_MISSING (HTTP 401)."

        Claim: X-User-ID set to empty string → ERR_AUTH_MISSING.
        """
        res = api.create_owner(
            create_owner_payload(),
            headers={
                "X-User-ID": "",
                "X-User-Role": "PropertyManager",
                "Content-Type": "application/json",
            },
        )
        validate_error(res, "ERR_AUTH_MISSING")


class TestAuthInvalidRole:
    """PRD §2.1: "If X-User-Role is present but is not one of the four declared
    role names, the request is rejected with ERR_AUTH_INVALID_ROLE (HTTP 401)." """

    @pytest.mark.parametrize(
        "bad_role", ["Admin", "owner", "PROPERTYMANAGER", "Tenant", "RandomRole"]
    )
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "If X-User-Role is present but is not one of the four declared
        role names, the request is rejected with ERR_AUTH_INVALID_ROLE (HTTP 401)."

        Claim: any X-User-Role outside the four declared names → ERR_AUTH_INVALID_ROLE.
        """
        res = api.create_owner(
            create_owner_payload(),
            headers=build_user_headers("test-id", bad_role),
        )
        validate_error(res, "ERR_AUTH_INVALID_ROLE")


class TestRbacEndpointMatrix:
    """PRD §2.1: "If the role is valid but is not authorized for the target endpoint,
    or the role-bound ownership check fails, the request is rejected with ERR_FORBIDDEN
    (HTTP 403)." """

    def test_owner_cannot_register_owner(self, api):
        """PRD §4: POST /communities/owners is authorized only for PropertyManager.

        Claim: Owner role calling POST /owners → ERR_FORBIDDEN.
        """
        headers = build_user_headers("some-owner-id", "Owner")
        res = api.create_owner(create_owner_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_maintenance_cannot_create_facility(self, api):
        """PRD §4: POST /communities/facilities is authorized only for PropertyManager.

        Claim: MaintenanceStaff role calling POST /facilities → ERR_FORBIDDEN.
        """
        headers = build_user_headers("some-maint-id", "MaintenanceStaff")
        res = api.create_facility(
            {"facility_type": "GYM", "name": "x", "slot_minutes": 60}, headers
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_committee_chair_cannot_issue_bills(self, api):
        """PRD §4: POST /communities/fee-bills/issue is authorized only for PropertyManager.

        Claim: CommitteeChair role calling POST /fee-bills/issue → ERR_FORBIDDEN.
        """
        headers = build_user_headers("some-chair-id", "CommitteeChair")
        res = api.issue_fee_bills({"period_year": 2025, "period_month": 1}, headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_property_manager_cannot_cast_vote(self, api):
        """PRD §4: POST /communities/proposals/{id}/votes is authorized only for Owner.

        Claim: PropertyManager calling POST /proposals/{id}/votes → ERR_FORBIDDEN.
        """
        headers = build_user_headers("test-pm-1", "PropertyManager")
        res = api.cast_vote(NON_EXISTENT_UUID, {"property_id": NON_EXISTENT_UUID, "choice": "YES"}, headers)
        validate_error(res, "ERR_FORBIDDEN")


class TestOwnerOwnershipChecks:
    """PRD §2.1: "When X-User-Role is Owner, X-User-ID is the id of the acting
    Owner entity; ownership checks on any resource that references an Owner ...
    compare the resource's foreign-key field to X-User-ID and reject mismatches
    with ERR_FORBIDDEN." """

    def test_owner_cannot_create_work_order_on_other_owners_property(self, api):
        """PRD §2.1: "When X-User-Role is Owner, X-User-ID is the id of the acting
        Owner entity; ownership checks on any resource that references an Owner
        (a work order whose reporter_owner_id does not match, a reservation whose
        owner_id does not match, a parking application or vote whose owner_id does
        not match) compare the resource's foreign-key field to X-User-ID and reject
        mismatches with ERR_FORBIDDEN."

        Claim: an Owner trying to file a work order against another owner's property
        is rejected with ERR_FORBIDDEN.
        """
        owner_a, prop_a = create_owner_with_property()
        owner_b, _prop_b = create_owner_with_property()
        # owner_b posts against prop_a (owned by owner_a) — ownership mismatch.
        headers_b = make_owner_headers(owner_b["id"])
        payload = create_work_order_payload(prop_a["id"])
        res = api.create_work_order(payload, headers_b)
        validate_error(res, "ERR_FORBIDDEN")

    def test_owner_cannot_cancel_other_owners_work_order(self, api):
        """PRD §2.1 + §3.2: "the cancel is permitted only when X-User-ID matches
        reporter_owner_id."

        Claim: an Owner attempting to cancel a work order whose reporter_owner_id
        belongs to another owner is rejected with ERR_FORBIDDEN.
        """
        owner_a, prop_a = create_owner_with_property()
        owner_b, _ = create_owner_with_property()
        wo = submit_work_order(owner_a, prop_a)
        headers_b = make_owner_headers(owner_b["id"])
        res = api.cancel_work_order(wo["id"], headers_b)
        validate_error(res, "ERR_FORBIDDEN")


class TestMaintenanceStaffIdentityBinding:
    """PRD §2.1: "For MaintenanceStaff specifically, once a work order has been
    dispatched the server enforces that the operator acting on subsequent
    transitions is the one whose opaque id was recorded as assigned_staff_id." """

    def test_other_maintenance_staff_cannot_start_work_order(self, api):
        """PRD §2.1: "For MaintenanceStaff specifically, once a work order has been
        dispatched the server enforces that the operator acting on subsequent
        transitions is the one whose opaque id was recorded as assigned_staff_id;
        this is an equality check between X-User-ID and the previously recorded value."

        Claim: a maintenance operator other than the one named at dispatch attempting
        to /start the work order is rejected with ERR_FORBIDDEN.
        """
        owner, prop = create_owner_with_property()
        wo = submit_work_order(owner, prop)
        # Dispatch to staff "alice"; another staff "bob" tries to start.
        from test_helpers import api_client, dispatch_work_order_payload, get_success_data
        from test_helpers import TEST_USERS as TU
        get_success_data(
            api_client.dispatch_work_order(
                wo["id"], dispatch_work_order_payload("staff-alice"), TU["property_manager_headers"]
            )
        )
        bob_headers = make_maintenance_headers("staff-bob")
        res = api.start_work_order(wo["id"], bob_headers)
        validate_error(res, "ERR_FORBIDDEN")
