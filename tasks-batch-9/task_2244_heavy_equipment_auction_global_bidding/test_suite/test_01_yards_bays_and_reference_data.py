"""Reference data owned by the back office: yards, load-out bays and bidder records."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bidder,
    assert_loadout_bay,
    assert_yard,
    create_loadout_bay_payload,
    create_yard_payload,
    headers_without_user_id,
    new_yard,
    reset_clock,
    set_clock,
    update_loadout_bay_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, OPERATOR
from test_helpers.constants import CLOCK_EPOCH


class TestYardRegistration:
    def test_yard_creation_returns_the_stored_record_in_the_object_envelope(self):
        """A fully specified yard is persisted exactly as supplied and returned at version 1.

        PRD 2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
        refreshed on every mutation, and `version`, an integer that starts at 1 when the
        resource is created and increments by exactly 1 on every mutation".
        PRD 3.1: "A **yard** is a physical auction and load-out site, registered with a
        human-readable `code` — unique across yards, between 3 and 32 characters — and a
        `country_code`, exactly two uppercase letters naming the ISO-3166 country of the site."

        Design: Corner/entities/yard_creation_returns_persisted_record_with_envelope
        """
        set_clock(CLOCK_EPOCH)

        response = api_client.create_yard(
            create_yard_payload(
                code="YRD-HOU",
                country_code="US",
                teardown_buffer_minutes=90,
                loadout_deadline_days=14,
                currency_code="USD",
            ),
            ADMIN,
        )

        yard = validate_success(response, expected_status=201)
        assert_yard(yard)
        assert yard["code"] == "YRD-HOU"
        assert yard["country_code"] == "US"
        assert yard["teardown_buffer_minutes"] == 90
        assert yard["loadout_deadline_days"] == 14
        assert yard["currency_code"] == "USD"
        assert yard["version"] == 1

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

    def test_omitted_yard_settings_fall_back_to_their_declared_defaults(self):
        """Leaving the three operational settings out yields the declared defaults, not nulls.

        PRD 3.1: "`teardown_buffer_minutes`, the ring teardown time required between two
        live on-site events at that yard, defaults to two hours and may be anything from
        zero up to 2880 minutes; `loadout_deadline_days`, the number of days after an event
        closes by which all load-out must finish, defaults to 10 and must be between 1 and
        60; and `currency_code`, the ISO-4217 alpha-3 settlement currency for auctions held
        there, defaults to `USD`."

        Design: Corner/entities/yard_optional_fields_fall_back_to_declared_defaults
        """
        set_clock(CLOCK_EPOCH)

        yard = validate_success(
            api_client.create_yard({"code": "YRD-BNE", "country_code": "AU"}, ADMIN),
            expected_status=201,
        )

        assert yard["teardown_buffer_minutes"] == 120
        assert yard["loadout_deadline_days"] == 10
        assert yard["currency_code"] == "USD"


class TestLoadoutBayLifecycle:
    def test_bays_are_created_active_with_no_tonnage_reserved(self):
        """Both bays come back at version 1, in service, and reserving nothing yet.

        PRD 3.1: "A bay is created with `is_active` true unless the request says otherwise,
        and its derived `reserved_tonnage_kg` starts at zero."

        Design: Corner/endpoints/loadout_bay_create_read_list_and_deactivate_round_trip
        """
        reset_clock()
        yard = new_yard()

        bay_one = validate_success(
            api_client.create_loadout_bay(
                create_loadout_bay_payload(yard["id"], bay_number=1, crane_capacity_kg=40_000),
                ADMIN,
            ),
            expected_status=201,
        )
        bay_two = validate_success(
            api_client.create_loadout_bay(
                create_loadout_bay_payload(yard["id"], bay_number=2, crane_capacity_kg=15_000),
                ADMIN,
            ),
            expected_status=201,
        )

        for bay in (bay_one, bay_two):
            assert_loadout_bay(bay)
            assert bay["is_active"] is True
            assert bay["reserved_tonnage_kg"] == 0
            assert bay["version"] == 1

        stored = validate_success(api_client.get_loadout_bay(bay_one["id"], OPERATOR))
        assert stored["crane_capacity_kg"] == 40_000
        assert stored["bay_number"] == 1

    def test_deactivating_one_bay_bumps_its_version_and_narrows_the_active_listing(self):
        """Taking a bay out of service touches only `is_active`, and the filtered listing
        counts just the bay that is still in service.

        PRD 3.1: "A bay may later be taken in or out of service by supplying a new
        `is_active` value; doing so bumps the bay's `version` and does not disturb bookings
        that already exist, though an inactive bay accepts no new ones."
        PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` counts every record matching the
        filters before pagination is applied."

        Design: Corner/endpoints/loadout_bay_create_read_list_and_deactivate_round_trip
        """
        reset_clock()
        yard = new_yard()
        bay_one = validate_success(
            api_client.create_loadout_bay(
                create_loadout_bay_payload(yard["id"], bay_number=1, crane_capacity_kg=40_000),
                ADMIN,
            ),
            expected_status=201,
        )
        bay_two = validate_success(
            api_client.create_loadout_bay(
                create_loadout_bay_payload(yard["id"], bay_number=2, crane_capacity_kg=15_000),
                ADMIN,
            ),
            expected_status=201,
        )

        deactivated = validate_success(
            api_client.update_loadout_bay(
                bay_two["id"], update_loadout_bay_payload(is_active=False), ADMIN
            )
        )
        assert deactivated["is_active"] is False
        assert deactivated["version"] == 2

        rows, meta = validate_paginated(
            api_client.list_yard_loadout_bays(
                yard["id"], OPERATOR, params={"is_active": True, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [bay_one["id"]]

        untouched = validate_success(api_client.get_loadout_bay(bay_two["id"], OPERATOR))
        assert untouched["crane_capacity_kg"] == 15_000


class TestBidderReferenceRecord:
    def test_bidder_tier_and_deposit_ledger_are_server_computed(self):
        """A Brazilian buyer is banded TIER_B and every money counter opens at zero.

        PRD 3.5: "`TIER_B` covers Mexico, the United Arab Emirates, Brazil and South
        Africa — `MX`, `AE`, `BR` and `ZA`."
        PRD 3.5: "All six money counters — `deposit_total_cents`, `deposit_held_cents`,
        `deposit_available_cents`, `deposit_forfeited_cents`, `open_exposure_cents` and
        `lifetime_purchase_cents` — start at zero, as does `default_strike_count`."

        Design: Corner/entities/bidder_tier_and_deposit_ledger_fields_are_computed
        """
        set_clock(CLOCK_EPOCH)

        bidder = validate_success(
            api_client.create_bidder(
                {
                    "legal_name": "Andes Maquinaria Ltda",
                    "country_code": "BR",
                    "tax_id": "BR-4711",
                },
                ADMIN,
            ),
            expected_status=201,
        )

        assert_bidder(bidder)
        assert bidder["country_tier"] == "TIER_B"
        assert bidder["deposit_total_cents"] == 0
        assert bidder["deposit_held_cents"] == 0
        assert bidder["deposit_available_cents"] == 0
        assert bidder["deposit_forfeited_cents"] == 0
        assert bidder["open_exposure_cents"] == 0
        assert bidder["default_strike_count"] == 0
        assert bidder["lifetime_purchase_cents"] == 0


class TestRequestAdmission:
    def test_unknown_auction_identifier_reports_the_auction_not_found_error(self):
        """A well-formed but unknown auction id is a 404 naming the auction collection.

        PRD 2.4: "`auction_id` yields `ERR_AUCTION_NOT_FOUND`".

        Design: Corner/entities/get_unknown_auction_returns_404_auction_not_found
        """
        set_clock(CLOCK_EPOCH)

        response = api_client.get_auction("00000000-0000-4000-8000-000000000000", OPERATOR)

        validate_error(response, ApiErrorId.ERR_AUCTION_NOT_FOUND, expected_status=404)
        assert response.json()["response_type"] == "error"

    def test_a_write_without_the_user_id_header_is_rejected_before_the_body_is_read(self):
        """Dropping `X-User-ID` refuses the create outright and stores nothing.

        PRD 2.1: "If either header is missing or empty, or if `X-User-Role` does not name a
        role the system recognises, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401) before the body is inspected at all."

        Design: Corner/errors/a_write_with_no_x_user_id_header_is_unauthenticated
        """
        set_clock(CLOCK_EPOCH)

        response = api_client.create_yard(
            create_yard_payload(code="YRD-NOAUTH"), headers_without_user_id("PlatformAdmin")
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

        _, meta = validate_paginated(api_client.list_yards(ADMIN))
        assert meta["total_count"] == 0
