"""Authentication and RBAC tests (PRD §2.1)."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_member_payload,
    create_subscription_payload,
    discover_or_create_store,
    make_billing_admin_headers,
    make_member_headers,
    setup_active_member_with_subscription,
    validate_error,
)


class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or that supplies a role
        string outside this enumeration, is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: empty headers → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        store = discover_or_create_store("CA")
        res = api.create_member(
            create_member_payload(home_store_id=store["id"]),
            headers={"Content-Type": "application/json"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_missing_user_id_header(self, api):
        """PRD §2.1: "A request that omits either header, or that supplies a role
        string outside this enumeration, is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: missing X-User-ID → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        store = discover_or_create_store("CA")
        res = api.create_member(
            create_member_payload(home_store_id=store["id"]),
            headers={"X-User-Role": "Any", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_missing_user_role_header(self, api):
        """PRD §2.1: "A request that omits either header, or that supplies a role
        string outside this enumeration, is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: missing X-User-Role → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        store = discover_or_create_store("CA")
        res = api.create_member(
            create_member_payload(home_store_id=store["id"]),
            headers={"X-User-ID": "some-id", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    @pytest.mark.parametrize(
        "bad_role", ["admin", "MEMBER", "Owner", "billing_admin", "", "Customer"]
    )
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "A request that omits either header, or that supplies a role
        string outside this enumeration, is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

        Claim: any role string outside the five recognised roles → header error.
        """
        store = discover_or_create_store("CA")
        res = api.create_member(
            create_member_payload(home_store_id=store["id"]),
            headers=build_user_headers("test-id", bad_role),
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


class TestRbacForbidden:
    """PRD §2.1: "A request whose role is recognised but is not in the authorising
    set for the addressed endpoint is rejected with ERR_INSUFFICIENT_PERMISSIONS." """

    def test_any_cannot_create_class_session(self, api):
        """PRD §4: POST /stores/{storeId}/class-sessions is authorized only for
        StoreManager.

        Claim: Any role attempting to schedule a class session → ERR_INSUFFICIENT_PERMISSIONS.
        """
        store = discover_or_create_store("CA")
        res = api.create_class_session(
            store["id"],
            {
                "class_type": "YOGA",
                "trainer_id": NON_EXISTENT_UUID,
                "starts_at": "2099-01-01T00:00:00.000Z",
                "ends_at": "2099-01-01T01:00:00.000Z",
                "capacity": 10,
            },
            TEST_USERS["any_headers"],
        )
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")

    def test_member_cannot_mint_coupon(self, api):
        """PRD §4: POST /coupons is authorized only for BillingAdmin.

        Claim: Member role attempting to mint a coupon → ERR_INSUFFICIENT_PERMISSIONS.
        """
        member, _ = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        headers = make_member_headers(member["id"])
        res = api.create_coupon(
            {
                "code": "TESTBLOCK",
                "kind": "PERCENT_OFF",
                "value": 10,
                "applicable_to": "BOTH",
                "valid_from": "2099-01-01T00:00:00.000Z",
                "valid_until": "2099-12-31T00:00:00.000Z",
                "max_redemptions": 1,
            },
            headers,
        )
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")

    def test_store_manager_cannot_advance_clock(self, api):
        """PRD §2.14 / §4: POST /_clock/advance is reserved for BillingAdmin.

        Claim: StoreManager attempting clock advance → ERR_INSUFFICIENT_PERMISSIONS.
        """
        res = api.advance_clock("2099-01-01T00:00:00.000Z", TEST_USERS["store_manager_headers"])
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")

    def test_member_cannot_reinstate_subscription(self, api):
        """PRD §4: POST /members/{memberId}/subscriptions/{subId}/reinstate is
        authorized only for BillingAdmin.

        Claim: Member attempting reinstatement on own subscription → ERR_INSUFFICIENT_PERMISSIONS.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        headers = make_member_headers(member["id"])
        res = api.reinstate_subscription(member["id"], sub["id"], headers)
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


class TestNotFoundOrderingLeftToRight:
    """PRD §2.5: "The server resolves path parameters strictly from left to right
    and aborts at the first missing identifier." """

    def test_missing_member_yields_member_not_found_before_subscription(self, api):
        """PRD §2.5: "A request to fetch a payment attempt under a non-existent
        memberId is rejected with ERR_MEMBER_NOT_FOUND and the server never opens
        the Subscription table; only after the Member exists is the Subscription
        identified by subId looked up, with ERR_SUBSCRIPTION_NOT_FOUND as the next
        failure mode."

        Claim: missing memberId on payment-attempts list → ERR_MEMBER_NOT_FOUND.
        """
        res = api.list_payment_attempts(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            TEST_USERS["billing_admin_headers"],
        )
        validate_error(res, "ERR_MEMBER_NOT_FOUND")

    def test_missing_subscription_under_real_member(self, api):
        """PRD §2.5: "only after the Member exists is the Subscription identified
        by subId looked up, with ERR_SUBSCRIPTION_NOT_FOUND as the next failure mode."

        Claim: real memberId + bogus subId → ERR_SUBSCRIPTION_NOT_FOUND.
        """
        member, _ = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        res = api.get_subscription(
            member["id"], NON_EXISTENT_UUID, make_member_headers(member["id"])
        )
        validate_error(res, "ERR_SUBSCRIPTION_NOT_FOUND")
