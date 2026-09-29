"""The carrier registry: create, read, list and the unknown-identifier read."""
import pytest
from test_helpers import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_carrier
from test_helpers.fixtures import ADMIN, RISK, onboard_carrier


ANCHOR = {
    "legal_name": "Anchor Life",
    "naic_code": "71001",
    "am_best_rating": "A",
    "statutory_surplus_usd": 1_000_000_000.00,
    "domicile_state": "IA",
}


class TestCarrierCreate:
    def test_create_returns_the_standard_envelope_and_every_opening_value(self, api):
        """Onboarding answers with the standard envelope and the declared opening state.

        "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`." "The `response_type` is either "object"
        for a single resource or "array" for a list of resources." "A newly
        onboarded carrier begins life in `PENDING_DILIGENCE` with
        `watch_list_flag` false, with `reserved_premium_usd`,
        `in_force_premium_usd` and `in_force_cash_value_usd` all at 0.00, with
        `concentration_bps` and `regulatory_notice_count` at 0, and with
        `last_approved_review_year` unset." "`version` is an integer that starts
        at 1 when the resource is created".

        Design: Corner/entities/carrier_create_returns_envelope_and_every_declared_field
        """
        response = api.create_carrier(ANCHOR, ADMIN)
        body = response.json()

        assert response.status_code == 201, "creating a resource responds with HTTP 201"
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        carrier = validate_success(response, 201)
        assert_carrier(carrier)
        assert is_valid_uuid(carrier["id"])
        assert carrier["legal_name"] == "Anchor Life"
        assert carrier["naic_code"] == "71001"
        assert carrier["am_best_rating"] == "A"
        assert carrier["statutory_surplus_usd"] == pytest.approx(1_000_000_000.00, abs=0.01)
        assert carrier["domicile_state"] == "IA"
        assert carrier["status"] == "PENDING_DILIGENCE"
        assert carrier["watch_list_flag"] is False
        assert carrier["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["in_force_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["in_force_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["concentration_bps"] == 0
        assert carrier["regulatory_notice_count"] == 0
        assert carrier["last_approved_review_year"] is None
        assert carrier["version"] == 1

    def test_client_supplied_identity_and_version_values_are_ignored(self, api):
        """The server mints the identity quartet whatever the body claims.

        "Every resource the platform persists carries a server-minted `id` in
        canonical UUID form. Identifiers never carry a type prefix, and clients
        must never supply one on a create — an `id` present in a create body is
        ignored, and clients must treat identifiers as opaque strings."
        "`version` is an integer that starts at 1 when the resource is created",
        and "any request that changes a resource's persisted state bumps
        `version` by 1 and refreshes `updated_at` to the current logical clock
        instant" — which, with no clock move yet, still reads exactly
        "`2026-08-01T00:00:00Z`".

        Design: Corner/entities/carrier_create_extra_field_input_ignored_for_system_fields
        """
        carrier = validate_success(
            api.create_carrier(
                {
                    "legal_name": "Harbor Life",
                    "naic_code": "71008",
                    "am_best_rating": "A",
                    "statutory_surplus_usd": 500_000_000.00,
                    "domicile_state": "WA",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "version": 99,
                    "created_at": "2020-01-01T00:00:00.000Z",
                },
                ADMIN,
            ),
            201,
        )

        assert carrier["id"] != "00000000-0000-0000-0000-000000000001", (
            "an id supplied on a create is ignored"
        )
        assert is_valid_uuid(carrier["id"]), "the minted id is a bare UUID with no type prefix"
        assert carrier["version"] == 1, "a client-supplied version is ignored"
        assert not carrier["created_at"].startswith("2020-"), (
            "a client-supplied created_at is ignored"
        )
        assert carrier["updated_at"].startswith("2026-08-01T00:00:00"), (
            "the timestamps come from the logical clock, which has not been moved"
        )
        assert carrier["legal_name"] == "Harbor Life"


class TestCarrierRead:
    def test_reading_a_carrier_returns_it_exactly_as_stored(self, api):
        """A read is not a mutation, so every field comes back as filed.

        Carriers can be "read individually — the individual read is how a
        controller obtains the carrier `version` it will have to echo before
        reserving capacity", and "every other successful operation, including
        every state-advancing action and every read, responds with HTTP 200".

        Design: Corner/entities/carrier_get_returns_the_stored_entity_unchanged
        """
        created = onboard_carrier(
            api,
            legal_name="Beacon Life",
            naic_code="71002",
            am_best_rating="A_MINUS",
            statutory_surplus_usd=750_000_000.00,
            domicile_state="NE",
        )

        response = api.get_carrier(created["id"], RISK)
        assert response.status_code == 200
        fetched = validate_success(response)

        assert fetched["id"] == created["id"]
        assert fetched["legal_name"] == "Beacon Life"
        assert fetched["naic_code"] == "71002"
        assert fetched["am_best_rating"] == "A_MINUS"
        assert fetched["statutory_surplus_usd"] == pytest.approx(750_000_000.00, abs=0.01)
        assert fetched["domicile_state"] == "NE"
        assert fetched["status"] == "PENDING_DILIGENCE"
        assert fetched["version"] == 1, "a read never bumps the version counter"

    def test_reading_an_unknown_carrier_reports_the_carrier_not_found_error(self, api):
        """An identifier that names nothing gets the carrier-specific 404.

        The not-found band is entity specific, and "`ERR_CARRIER_NOT_FOUND`" is
        the identifier reported for a carrier. The error envelope carries only
        the two declared fields, since "The `error_id` is a unique,
        machine-readable string that identifies the specific error" and "The
        `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/carrier_get_with_unknown_id_returns_carrier_not_found
        """
        response = api.get_carrier("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", RISK)
        body = response.json()

        assert body["response_type"] == "error"
        error = validate_error(response, "ERR_CARRIER_NOT_FOUND", 404)
        assert error["message"], "the error carries a human-readable message"


class TestCarrierList:
    def test_listing_pages_by_limit_and_offset_and_filters_by_status(self, api):
        """Paging reports the filtered population, not the page size.

        "The `meta` object of a list response carries `limit` and `offset`
        echoing the effective values used, `total_count` giving the number of
        rows matching the filters before pagination is applied, and `has_more`
        indicating whether any rows remain beyond the current page." Filtering on
        a status no carrier holds yet returns nothing, because "`total_count`
        always reflects the filtered population rather than the whole table".

        Design: Corner/entities/carrier_list_paginates_and_filters_by_status
        """
        for name, naic, state in (
            ("Cove Life", "71003", "MT"),
            ("Delta Life", "71004", "ND"),
            ("Ember Life", "71005", "SD"),
        ):
            onboard_carrier(api, legal_name=name, naic_code=naic, domicile_state=state)

        first_page, first_meta = validate_paginated(
            api.list_carriers(RISK, params={"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_carriers(RISK, params={"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        names = [c["legal_name"] for c in first_page + second_page]
        assert names == ["Cove Life", "Delta Life", "Ember Life"], (
            "list results are ordered by created_at ascending"
        )

        filtered, filtered_meta = validate_paginated(
            api.list_carriers(RISK, params={"status": "AUTHORIZED"})
        )
        assert filtered == []
        assert filtered_meta["total_count"] == 0
