"""Merchant onboarding and authorization mutations.

Covers PRD §3.6 (onboarding) and authorization status transitions.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_FORBIDDEN,
    TEST_USERS, make_merchant_headers,
    assert_merchant,
    create_merchant_payload, setup_authorized_merchant,
    iso_future,
)


STATE_ADMIN = TEST_USERS["state_admin_headers"]


class TestMerchantCreation:
    def test_create_merchant_returns_authorized(self, api):
        """PRD §3.6: "Merchants are created with `snap_authorization_status`
        = `AUTHORIZED`."

        Claim: a fresh merchant is created in AUTHORIZED state.
        """
        resp = api.create_merchant(create_merchant_payload(), STATE_ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_merchant(data)
        assert data["snap_authorization_status"] == "AUTHORIZED"

    def test_create_merchant_default_hot_food_pilot_false(self, api):
        """PRD §3.6: "optionally `hot_food_pilot` (default false)."

        Claim: omitting hot_food_pilot defaults to false.
        """
        payload = create_merchant_payload()
        payload.pop("hot_food_pilot", None)
        resp = api.create_merchant(payload, STATE_ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["hot_food_pilot"] is False

    @pytest.mark.parametrize("bad_name", ["", "x" * 101])
    def test_create_merchant_bad_name(self, api, bad_name):
        """PRD §3.6: "supplying `name` (1–100 characters)."

        Claim: empty or over-length name yields ERR_VALIDATION.
        """
        payload = create_merchant_payload(name=bad_name)
        resp = api.create_merchant(payload, STATE_ADMIN)
        validate_error(resp, ERR_VALIDATION)

    def test_create_merchant_caseworker_forbidden(self, api):
        """PRD §4 table: "POST /merchants — Onboard a merchant — StateAdministrator."

        Claim: a Caseworker cannot create a merchant.
        """
        resp = api.create_merchant(
            create_merchant_payload(), TEST_USERS["caseworker_headers"]
        )
        validate_error(resp, ERR_FORBIDDEN)


class TestMerchantUpdate:
    def test_update_authorization_status_to_suspended(self, api):
        """PRD §3.6: "setting `snap_authorization_status` to `SUSPENDED` or
        `REVOKED`, or letting `authorization_expires_at` fall at or before
        `Clock.now`, causes all subsequent purchase attempts against this
        merchant to fail with `ERR_MERCHANT_NOT_AUTHORIZED`."

        Claim: PATCH can move authorization status to SUSPENDED.
        """
        m = setup_authorized_merchant()
        resp = api.update_merchant(
            m["id"], {"snap_authorization_status": "SUSPENDED"}, STATE_ADMIN
        )
        data = validate_success(resp)
        assert data["snap_authorization_status"] == "SUSPENDED"

    def test_update_authorization_status_to_revoked(self, api):
        """PRD §3.6: "setting `snap_authorization_status` to `SUSPENDED` or
        `REVOKED`."

        Claim: PATCH to REVOKED succeeds.
        """
        m = setup_authorized_merchant()
        resp = api.update_merchant(
            m["id"], {"snap_authorization_status": "REVOKED"}, STATE_ADMIN
        )
        data = validate_success(resp)
        assert data["snap_authorization_status"] == "REVOKED"

    def test_update_unknown_merchant_404(self, api):
        """PRD §2.12: "Path-resource existence, validated left-to-right
        (`ERR_NOT_FOUND`)."

        Claim: PATCH on unknown merchant id yields ERR_NOT_FOUND.
        """
        resp = api.update_merchant(
            NON_EXISTENT_UUID, {"hot_food_pilot": True}, STATE_ADMIN
        )
        validate_error(resp, ERR_NOT_FOUND)


class TestMerchantGet:
    def test_get_merchant_by_admin(self, api):
        """PRD §4 table: "GET /merchants/{merchantId} — Fetch a merchant —
        StateAdministrator, Merchant."

        Claim: StateAdministrator can read any merchant.
        """
        m = setup_authorized_merchant()
        resp = api.get_merchant(m["id"], STATE_ADMIN)
        data = validate_success(resp)
        assert data["id"] == m["id"]

    def test_merchant_cannot_read_another_merchant(self, api):
        """PRD §2.1: "a `Merchant` principal may only post or reverse
        transactions whose body `merchant_id` matches `X-User-ID`, and may only
        `GET` transactions and merchants tied to that same id."
        PRD §3.6: "`Merchant` principals may read their own record and their
        own transactions, but never another merchant's."

        Claim: Merchant role with mismatched X-User-ID yields ERR_FORBIDDEN.
        """
        m1 = setup_authorized_merchant()
        m2 = setup_authorized_merchant()
        other_headers = make_merchant_headers(m2["id"])
        resp = api.get_merchant(m1["id"], other_headers)
        validate_error(resp, ERR_FORBIDDEN)
