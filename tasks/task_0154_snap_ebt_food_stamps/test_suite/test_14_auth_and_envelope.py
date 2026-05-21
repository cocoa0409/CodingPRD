"""Auth, RBAC, response envelope, and path-validation tests.

Covers PRD §2.1 (auth + role identity), §2.2 (envelope), §2.7 (path ordering).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_AUTH_MISSING, ERR_FORBIDDEN, ERR_NOT_FOUND,
    TEST_USERS, make_household_head_headers, make_merchant_headers,
    assert_envelope_success_object,
    create_household, setup_basic_household,
    setup_approved_household_with_active_card,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


class TestAuthHeaderRequired:
    def test_missing_both_headers(self, api):
        """PRD §2.1: "Both must be present and non-empty; missing either yields
        `ERR_AUTH_MISSING` with HTTP 401."

        Claim: a request with no auth headers yields ERR_AUTH_MISSING.
        """
        resp = api.list_households({})
        validate_error(resp, ERR_AUTH_MISSING)

    def test_missing_user_id(self, api):
        """PRD §2.1: "Both must be present and non-empty; missing either yields
        `ERR_AUTH_MISSING` with HTTP 401."

        Claim: missing X-User-ID yields ERR_AUTH_MISSING.
        """
        resp = api.list_households({"X-User-Role": "Caseworker"})
        validate_error(resp, ERR_AUTH_MISSING)

    def test_missing_user_role(self, api):
        """PRD §2.1: "Both must be present and non-empty; missing either yields
        `ERR_AUTH_MISSING` with HTTP 401."

        Claim: missing X-User-Role yields ERR_AUTH_MISSING.
        """
        resp = api.list_households({"X-User-ID": "x"})
        validate_error(resp, ERR_AUTH_MISSING)


class TestResponseEnvelope:
    def test_success_envelope_meta_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: a 2xx response carries a meta block with api_request_id
        starting with `req_` and an ISO 8601 timestamp.
        """
        resp = api.create_household(
            {"state_code": "CA", "address_zip": "94110"}, CASEWORKER
        )
        body = resp.json()
        assert_envelope_success_object(body)
        assert body["response_type"] == "object"


class TestPathOrdering:
    def test_unknown_household_then_unknown_member_returns_household_not_found(self, api):
        """PRD §2.7: "if `/households/{id}/members/{memberId}` is requested
        with an unknown `id`, the response is `ERR_NOT_FOUND` against the
        household — the server does not 'skip ahead' to the member id."

        Claim: unknown household id (regardless of member id) yields
        ERR_NOT_FOUND.
        """
        resp = api.get_member(NON_EXISTENT_UUID, NON_EXISTENT_UUID, CASEWORKER)
        validate_error(resp, ERR_NOT_FOUND)


class TestHouseholdHeadOwnership:
    def test_household_head_cannot_create_application_for_other_household(self, api):
        """PRD §2.1: "an attempt by a `HouseholdHead` to read or mutate another
        household's data yields `ERR_FORBIDDEN`."

        Claim: HouseholdHead with a different X-User-ID cannot create an
        application on someone else's household.
        """
        owner_hh, _ = setup_basic_household(size=1, age=30)
        other_hh = create_household()
        # HouseholdHead role with other_hh's id tries to mutate owner_hh's data
        other_headers = make_household_head_headers(other_hh["id"])
        resp = api.create_application(owner_hh["id"], other_headers)
        validate_error(resp, ERR_FORBIDDEN)


class TestMerchantOwnership:
    def test_merchant_cannot_post_transaction_for_other_merchant(self, api):
        """PRD §2.1: "a `Merchant` principal may only post or reverse
        transactions whose body `merchant_id` matches `X-User-ID`."

        Claim: a Merchant calling POST /transactions with a merchant_id !=
        X-User-ID yields ERR_FORBIDDEN.
        """
        from test_helpers import setup_authorized_merchant, create_transaction_payload
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        merchant_a = setup_authorized_merchant()
        merchant_b = setup_authorized_merchant()
        # Use merchant_b's identity headers but post a transaction for merchant_a
        wrong_headers = make_merchant_headers(merchant_b["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_a["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 100, "quantity": 1}],
        )
        resp = api.create_transaction(payload, wrong_headers)
        validate_error(resp, ERR_FORBIDDEN)
