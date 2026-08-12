"""Court and attorney registration: creation, retrieval, listing, uniqueness."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId,
    assert_court, assert_attorney,
    assert_instant_equal,
    create_court_payload, create_attorney_payload,
    create_court, create_attorney, set_clock,
    TEST_DEFAULTS,
)


class TestCourtCreation:
    def test_court_creation_returns_201_with_server_defaults(self, api, court_admin_headers):
        """PRD §3.1: "A newly registered court starts at `version` 1."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/court_creation_returns_201_and_computed_defaults
        """
        set_clock(TEST_DEFAULTS["BOOT_CLOCK"])
        res = api.create_court(create_court_payload(code="CT1", name="Court 1"),
                               court_admin_headers)
        court = validate_success(res, 201)
        assert_court(court)
        assert is_valid_uuid(court["id"]), "id must be a server-minted UUID"
        assert court["version"] == 1, "newly registered court must start at version 1"
        assert court["code"] == "CT1"

    def test_court_get_by_id_returns_stored_data(self, api, court_admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."

        Design: Corner/entities/court_get_by_id_returns_stored_data
        """
        court = create_court(code="CT1", name="Court 1", jurisdiction_type="FEDERAL")
        res = api.get_court(court["id"], court_admin_headers)
        fetched = validate_success(res, 200)
        assert_court(fetched)
        assert fetched["id"] == court["id"]
        assert fetched["code"] == "CT1"
        assert fetched["jurisdiction_type"] == "FEDERAL"


class TestCourtListing:
    def test_court_list_pagination(self, api, court_admin_headers):
        """PRD §2.3: "Every list endpoint accepts two query parameters: `limit`,
        defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`,
        defaulting to 0 and never negative."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/entities/court_list_pagination
        """
        create_court(code="L1")
        create_court(code="L2", jurisdiction_type="STATE", uses_word_count=False,
                     max_words_opening=0, max_pages_opening=40,
                     max_words_reply=0, max_pages_reply=20)
        create_court(code="L3", jurisdiction_type="TRIBAL")
        res = api.list_courts(court_admin_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        assert len(data) == 2, f"expected 2 rows under limit=2, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestCourtErrors:
    def test_court_get_not_found_returns_404(self, api, court_admin_headers):
        """PRD §2.8: "the first identifier that does not resolve to an existing
        resource yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/court_get_not_found_returns_404
        """
        res = api.get_court(NON_EXISTENT_UUID, court_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_court_missing_required_field_returns_invalid_request(self, api, court_admin_headers):
        """PRD §2.9: "a request whose body is malformed, carries an unrecognized
        enum value, or fails a field type check is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/court_missing_required_field_returns_invalid_request
        """
        payload = create_court_payload()
        del payload["code"]
        res = api.create_court(payload, court_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    def test_court_duplicate_code_returns_duplicate(self, api, court_admin_headers):
        """PRD §3.1: "Registering a court whose `code` is already taken fails with
        `ERR_DUPLICATE`."

        Design: Corner/entities/court_duplicate_code_returns_duplicate
        """
        create_court(code="DUP")
        res = api.create_court(create_court_payload(code="DUP", name="Second"),
                               court_admin_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE.value, expected_status=409)


class TestAttorneyRegistration:
    def test_attorney_created_with_system_fields(self, api, court_admin_headers):
        """PRD §2.4: "The `version` is an integer that starts at 1 when the
        resource is created and increments by exactly 1 on every mutation of that
        resource, including system-driven mutations described in §3."
        PRD §2.4: "The `created_at` timestamp records creation time, and
        `updated_at` records the most recent mutation; both are ISO 8601 UTC
        timestamps rendered with three fractional digits."

        Design: Corner/entities/attorney_computed_fields_not_settable_by_input
        """
        set_clock(TEST_DEFAULTS["BOOT_CLOCK"])
        court = create_court(code="CF1")
        res = api.create_attorney(
            create_attorney_payload(bar_number="BAR-CF1", admitted_court_ids=[court["id"]]),
            court_admin_headers,
        )
        attorney = validate_success(res, 201)
        assert_attorney(attorney)
        assert attorney["version"] == 1, "new attorney must start at version 1"
        assert_instant_equal(
            attorney["created_at"], TEST_DEFAULTS["BOOT_CLOCK"],
            "created_at must record the logical clock at creation",
        )
        assert attorney["admitted_court_ids"] == [court["id"]]
