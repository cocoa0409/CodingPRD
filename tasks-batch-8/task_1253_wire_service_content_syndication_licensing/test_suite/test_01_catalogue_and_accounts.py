"""Catalogue and subscriber account basics: creation, required fields,
defaults, not-found, and list pagination envelope."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_content_package,
    assert_subscriber,
    create_package_payload,
    create_subscriber,
    create_subscriber_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["salesops_headers"]


class TestPackageCreation:
    def test_create_package_returns_201_and_persists_fields(self, api):
        """PRD §4: "Creating a new resource returns HTTP 201; every other
        successful operation — reads, state transitions, modifications —
        returns HTTP 200."
        PRD §3.1: "A package is born `ACTIVE`; retiring it flips its `status`
        to `RETIRED`, and a retired package may no longer be referenced by new
        subscriptions — activation against a retired package is refused."

        Design: Corner/entities/create_package_returns_201_and_persists_fields
        """
        res = api.create_package(
            create_package_payload(
                code="NP",
                display_name="NatPlus",
                media_rights="TEXT_PHOTO_VIDEO",
                base_monthly_fee_cents=250000,
            ),
            ADMIN,
        )
        pkg = validate_success(res, 201)
        assert_content_package(pkg)
        assert pkg["status"] == "ACTIVE"

        fetched = validate_success(api.get_package(pkg["id"], ADMIN), 200)
        assert fetched["code"] == "NP"
        assert fetched["status"] == "ACTIVE"
        assert fetched["base_monthly_fee_cents"] == 250000

    def test_create_package_missing_required_field_returns_validation(self, api):
        """PRD §2.8: "Independent of the ordered list above, any request that
        is missing a required field or carries a malformed value — an unknown
        enum literal, an out-of-range number — is rejected with
        `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "A content package is created with a unique wire service
        `code` such as NATIONAL_NEWS_PLUS, a human-readable `display_name`, a
        `media_rights` class, and a `base_monthly_fee_cents` — the list price
        per calendar month before any circulation multiplier is applied."

        Design: Corner/entities/create_package_missing_required_field_returns_validation
        """
        payload = {
            "code": "XX",
            "display_name": "X",
            "media_rights": "TEXT_ONLY",
            # base_monthly_fee_cents omitted
        }
        res = api.create_package(payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


class TestSubscriberAccount:
    def test_get_nonexistent_subscriber_returns_404(self, api):
        """PRD §2.8: "every path identifier and every request-body foreign key
        resolves to an existing entity; failure yields `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_nonexistent_subscriber_returns_404
        """
        res = api.get_subscriber(NON_EXISTENT_UUID, SALES)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_subscriber_default_member_flag_and_credit_balance(self, api):
        """PRD §3.2: "A `SalesOps` operator registers each subscriber with its
        `legal_name` (the publication's legal entity name), a `billing_email`,
        a `declared_audience` — the self-declared average circulation that will
        later drive tier resolution — and an optional `is_member` flag,
        defaulting to false, marking the subscriber as a contributing
        wire-service member."
        PRD §3.2: "A subscriber is born `ACTIVE`, and its
        `member_credit_balance_cents` — the running balance of credit earned
        from accepted member contributions — accumulates from zero."

        Design: Corner/entities/subscriber_default_member_flag_and_credit_balance
        """
        payload = create_subscriber_payload(
            legal_name="D", billing_email="d@d.com", declared_audience=1000
        )
        assert "is_member" not in payload
        created = validate_success(api.create_subscriber(payload, SALES), 201)
        fetched = validate_success(api.get_subscriber(created["id"], SALES), 200)
        assert_subscriber(fetched)
        assert fetched["is_member"] is False
        assert fetched["member_credit_balance_cents"] == 0
        assert fetched["status"] == "ACTIVE"

    def test_subscriber_list_pagination_returns_envelope(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` envelope."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/subscriber_list_pagination_returns_envelope
        """
        create_subscriber(legal_name="S1", declared_audience=1000)
        create_subscriber(legal_name="S2", declared_audience=2000)

        res = api.list_subscribers(SALES, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(res)
        body = res.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["response_type"] == "array"
        assert meta["total_count"] >= 2
        assert meta["has_more"] is True
        assert len(data) == 1
