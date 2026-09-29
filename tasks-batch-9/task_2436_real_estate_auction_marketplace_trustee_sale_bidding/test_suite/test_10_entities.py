"""Entity-shaped claims: what a create echoes, what a read returns, what the server
mints on its own, and how the lot junction slices the event-by-asset graph."""

from test_helpers import (
    CLOCK_SETUP,
    CLOCK_STARTUP_DEFAULT,
    COUNTY_PRIMARY,
    COUNTY_SECONDARY,
    STATE_CODE,
    TEST_USERS,
    add_lot,
    api_client,
    assert_common_fields,
    assert_timestamp_equals,
    close_lot,
    confirmed_sale,
    create_asset_listing_payload,
    create_auction_event_payload,
    create_bidder_payload,
    create_event,
    create_listing,
    create_seller,
    create_seller_payload,
    execute_contract,
    file_disclosures,
    funded_bidder,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_lots,
    make_seller_headers,
    open_event,
    place_bid,
    read_bidder,
    read_event,
    read_listing,
    read_lot,
    record_title_clearance,
    register_bidder,
    scheduled_lot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_bidder,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["auction_ops_headers"]
ANON = TEST_USERS["anonymous_headers"]

UNASSIGNED_BIDDER_ID = "11111111-2222-4333-8444-555555555555"
UNASSIGNED_SELLER_ID = "99999999-8888-4777-8666-555544443333"


class TestSellerCreation:
    def test_seller_creation_echoes_inputs_and_seeds_the_ledger(self):
        """Onboarding echoes every submitted field, mints the four common properties at
        version 1, and seeds the settlement ledger at zero rather than omitting it.

        PRD: "A newly onboarded seller's `settled_net_cents` — the running total of net
        proceeds the platform has posted to it — starts at 0."

        Design: Corner/entities/seller_creation_echoes_inputs_and_seeds_settlement_ledger
        """
        response = api_client.create_seller(
            create_seller_payload(
                org_name="Meridian Loan Servicing",
                seller_type="SERVICER",
                contact_email="reo@meridian.example",
                settlement_account_ref="ACH-MER-1",
                default_commission_bps=650,
            ),
            ADMIN,
        )
        seller = validate_success(response, expected_status=201)

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        assert seller["org_name"] == "Meridian Loan Servicing"
        assert seller["seller_type"] == "SERVICER"
        assert seller["contact_email"] == "reo@meridian.example"
        assert seller["settlement_account_ref"] == "ACH-MER-1"
        assert seller["default_commission_bps"] == 650
        assert seller["settled_net_cents"] == 0
        assert_common_fields(seller, expected_version=1)
        assert_timestamp_equals(seller["created_at"], CLOCK_STARTUP_DEFAULT)


class TestAssetListingReads:
    def test_asset_listing_get_returns_the_stored_row(self):
        """A read returns exactly what intake wrote, including the two axis defaults the
        client never sent.

        PRD: "Its `listing_status` begins at `INTAKE` and its `title_clearance_status` at
        `PENDING`; `occupancy_status` and `title_condition` both begin at `UNKNOWN`;
        `relist_count` is 0 and `second_chance_eligible` is false; and `disclosure_ack_at`
        — the instant the seller acknowledged the disclosures — is not yet set."

        Design: Corner/entities/asset_listing_get_returns_stored_row
        """
        seller = create_seller(
            org_name="Harbor Vale Bank",
            seller_type="BANK",
            contact_email="reo@harborvale.example",
            settlement_account_ref="ACH-HV-2",
        )
        created = create_listing(
            seller,
            street_address="18 Harbor Way",
            city="Alameda",
            estimated_value_cents=41000000,
        )

        listing = validate_success(
            api_client.get_asset_listing(created["id"], make_seller_headers(seller["id"]))
        )

        assert listing["seller_id"] == seller["id"]
        assert listing["street_address"] == "18 Harbor Way"
        assert listing["city"] == "Alameda"
        assert listing["county_code"] == COUNTY_PRIMARY
        assert listing["state_code"] == STATE_CODE
        assert listing["estimated_value_cents"] == 41000000
        assert listing["listing_status"] == "INTAKE"
        assert listing["title_clearance_status"] == "PENDING"
        assert listing["occupancy_status"] == "UNKNOWN"
        assert listing["title_condition"] == "UNKNOWN"
        assert listing["relist_count"] == 0
        assert listing["second_chance_eligible"] is False
        assert listing["disclosure_ack_at"] is None

    def test_asset_listing_list_filters_by_seller_and_paginates(self):
        """Three listings under one seller and one under another: the filter narrows the
        collection before paging, and the page metadata counts the filtered rows.

        PRD: "List responses populate `limit`, `offset`, `total_count`, and `has_more` in
        the `meta` object, where `total_count` is the number of records matching the
        request's filters before pagination is applied and `has_more` indicates whether
        records remain beyond the current page."

        Design: Corner/entities/asset_listing_list_filters_by_seller_and_paginates
        """
        seller_a = create_seller(
            org_name="Seller A Holdings",
            seller_type="BANK",
            contact_email="a@sellera.example",
            settlement_account_ref="ACH-A",
        )
        seller_b = create_seller(
            org_name="Seller B Holdings",
            seller_type="GSE",
            contact_email="b@sellerb.example",
            settlement_account_ref="ACH-B",
        )
        owned = [
            create_listing(
                seller_a, street_address=f"{n} Main St", city="Oakland",
                estimated_value_cents=20000000 + n,
            )["id"]
            for n in (1, 2, 3)
        ]
        other = create_listing(
            seller_b,
            street_address="4 Fourth St",
            city="Richmond",
            county_code=COUNTY_SECONDARY,
            estimated_value_cents=23000000,
        )["id"]

        first_rows, first_meta = validate_paginated(
            api_client.list_asset_listings(ADMIN, {"seller_id": seller_a["id"], "limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_rows, second_meta = validate_paginated(
            api_client.list_asset_listings(ADMIN, {"seller_id": seller_a["id"], "limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        seen = {row["id"] for row in first_rows + second_rows}
        assert seen == set(owned)
        assert other not in seen

        _all_rows, all_meta = validate_paginated(api_client.list_asset_listings(ADMIN))
        assert all_meta["total_count"] == 4


class TestExistenceAndShapeBands:
    def test_bidder_get_with_an_unassigned_uuid_is_not_found(self):
        """A well-formed but unused id is a 404 on the existence band, not an empty 200.

        PRD: "`ERR_BIDDER_NOT_FOUND` (404) — a bidder id in the path or body resolves to a
        `Bidder`. Applies to `GET /bidders/{id}`, `GET /bidders/{id}/eligibility-exclusions`,
        `GET /bidders/{id}/eligibility-assessment`, `POST /bidders/{id}/identity-verification`,
        `POST /bidders/{id}/deposits`, and `POST /eligibility-exclusions`."

        Design: Corner/entities/bidder_get_with_unknown_id_returns_not_found
        """
        real = register_bidder(
            legal_name="Unrelated Bidder LLC",
            email="u@unrelated.example",
            mailing_address="9 Nowhere Rd, Oakland CA",
        )

        response = api_client.get_bidder(UNASSIGNED_BIDDER_ID, ADMIN)
        validate_error(response, "ERR_BIDDER_NOT_FOUND", 404)
        assert response.json()["response_type"] == "error"
        assert response.json()["data"]["message"].strip()

        assert validate_success(api_client.get_bidder(real["id"], ADMIN))["id"] == real["id"]

    def test_asset_listing_missing_its_city_is_an_invalid_request(self):
        """`city` has no default, so omitting it fails on the shape band and no row is
        persisted with a null city.

        PRD: "The seller submits the subject property with its `seller_id`,
        `street_address`, `city`, `county_code` (an uppercase recording-jurisdiction code of
        between 3 and 32 characters, such as `CA-ALAMEDA`), the two-letter uppercase
        `state_code`, and `estimated_value_cents`, the seller's own estimate of fair market
        value in cents, which must be strictly greater than zero."

        Design: Corner/entities/asset_listing_missing_required_city_returns_invalid_request
        """
        seller = create_seller(
            org_name="Northshore Bank",
            seller_type="BANK",
            contact_email="reo@northshore.example",
            settlement_account_ref="ACH-NS-3",
        )
        payload = create_asset_listing_payload(
            seller["id"], street_address="40 Shoreline Dr", estimated_value_cents=25000000
        )
        payload.pop("city")

        validate_error(
            api_client.create_asset_listing(payload, make_seller_headers(seller["id"])),
            "ERR_INVALID_REQUEST",
            400,
        )

        _rows, meta = validate_paginated(
            api_client.list_seller_asset_listings(seller["id"], ADMIN)
        )
        assert meta["total_count"] == 0

    def test_bad_enum_inverted_window_and_zero_amount_all_fail_the_shape_band(self):
        """Three unrelated shape violations collapse to the same rung: an unknown enum
        member, an end instant that is not strictly after its start, and a zero amount.

        PRD: "`ERR_INVALID_REQUEST` (400) — the body conforms to the endpoint's input
        contract: required fields present, enumerated fields carrying a member of their
        declared set, integers inside their declared ranges, every amount in cents strictly
        greater than zero, datetimes valid ISO 8601 UTC, an end instant strictly after its
        start instant, `limit` between 1 and 100 inclusive, and `offset` not negative."

        Design: Corner/entities/invalid_enum_and_inverted_window_are_rejected
        """
        seller = create_seller(
            org_name="Shape Check Bank",
            seller_type="BANK",
            contact_email="shape@check.example",
            settlement_account_ref="ACH-SHAPE",
        )

        validate_error(
            api_client.create_seller(
                create_seller_payload(
                    org_name="Bad Enum Co",
                    seller_type="AUCTIONEER",
                    contact_email="bad@enum.example",
                    settlement_account_ref="ACH-BAD",
                ),
                ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.create_auction_event(
                create_auction_event_payload(
                    title="Inverted Window",
                    starts_at="2026-09-15T19:00:00Z",
                    ends_at="2026-09-15T19:00:00Z",
                ),
                OPS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.create_asset_listing(
                create_asset_listing_payload(
                    seller["id"], street_address="0 Zero Value Rd", city="Oakland",
                    estimated_value_cents=0,
                ),
                make_seller_headers(seller["id"]),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        _events, event_meta = validate_paginated(api_client.list_auction_events(OPS))
        assert event_meta["total_count"] == 0
        _listings, listing_meta = validate_paginated(api_client.list_asset_listings(ADMIN))
        assert listing_meta["total_count"] == 0

    def test_asset_listing_under_an_unknown_seller_reports_the_missing_parent(self):
        """A fully well-formed body still fails, because the parent named by `seller_id`
        does not exist.

        PRD: "`ERR_SELLER_NOT_FOUND` (404) — a seller id in the path or body resolves to a
        `Seller`. Applies to `GET /sellers/{id}`, `GET /sellers/{id}/asset-listings`, and
        `POST /asset-listings`."

        Design: Corner/entities/asset_listing_with_unknown_seller_returns_seller_not_found
        """
        validate_error(
            api_client.create_asset_listing(
                create_asset_listing_payload(
                    UNASSIGNED_SELLER_ID, street_address="12 Orphan Ct", city="Oakland",
                    estimated_value_cents=24000000,
                ),
                make_seller_headers(UNASSIGNED_SELLER_ID),
            ),
            "ERR_SELLER_NOT_FOUND",
            404,
        )

        _rows, meta = validate_paginated(api_client.list_asset_listings(ADMIN))
        assert meta["total_count"] == 0


class TestDeclaredDefaults:
    def test_every_omitted_optional_input_takes_its_declared_default(self):
        """Four independent defaults land on one chain: the commission, the statutory
        postponement cap, the bid increment and the closing window.

        PRD: "The only input is the optional `closing_window_days`, the buyer's closing
        window in days measured from execution, which must lie between 1 and 90 inclusive
        and is set to 21 when omitted."

        Design: Corner/entities/omitted_commission_and_increment_take_declared_defaults
        """
        set_clock(CLOCK_SETUP)
        seller = create_seller(
            org_name="Default Values Bank",
            seller_type="BANK",
            contact_email="reo@defaults.example",
            settlement_account_ref="ACH-DEF-1",
        )
        assert seller["default_commission_bps"] == 500

        listing = create_listing(
            seller,
            street_address="77 Default Ave",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        file_disclosures(seller, listing, "VACANT", "CLEAR")
        record_title_clearance(listing["id"], "CLEARED", "CLEAR", "TR-DEF-1")

        sale = confirmed_sale(listing["id"], "2026-09-15T18:00:00Z")
        assert sale["statutory_max_postponements"] == 3

        event = create_event(title="Defaults Event", trustee_sale_id=sale["id"])
        lot = add_lot(event["id"], listing["id"])
        assert lot["min_increment_cents"] == 500000
        assert lot["required_deposit_cents"] == 1000000

        bidder = funded_bidder(
            2000000, legal_name="Defaults Bidder LLC", email="bid@defaults.example"
        )
        set_clock("2026-09-15T17:05:00Z")
        open_event(event["id"])
        place_bid(lot["id"], bidder["id"], 20000000)
        set_clock("2026-09-15T18:05:00Z")
        close_lot(lot["id"])

        contract = execute_contract(lot["id"])
        assert contract["closing_window_days"] == 21
        assert_timestamp_equals(contract["closing_deadline_at"], "2026-10-06T18:05:00Z")


class TestComputedAndSystemFields:
    def test_eviction_risk_tier_is_derived_from_both_disclosure_axes(self):
        """Three sibling assets differing only in occupancy resolve `HIGH`, `MEDIUM` and
        `LOW` under the top-down clause order, and an undisclosed asset stays `HIGH`.

        PRD: "The disclosures are not published raw to bidders. What bidders see is
        `eviction_risk_tier`, one of `LOW`, `MEDIUM` or `HIGH`, derived from the two
        disclosure fields by a three-clause rule evaluated top to bottom, where **the first
        matching clause wins**:"

        Design: Corner/entities/eviction_risk_tier_computed_from_both_disclosure_axes
        """
        set_clock(CLOCK_SETUP)
        seller = create_seller(
            org_name="Tier Test Servicing",
            seller_type="SERVICER",
            contact_email="tier@test.example",
            settlement_account_ref="ACH-TIER",
        )
        rows = [
            create_listing(
                seller, street_address=f"{n} Tier St", city="Oakland",
                estimated_value_cents=20000000,
            )
            for n in (1, 2, 3, 4)
        ]
        assert rows[0]["eviction_risk_tier"] == "HIGH"

        high = file_disclosures(seller, rows[0], "TENANT_OCCUPIED", "CLEAR")
        medium = file_disclosures(seller, rows[1], "OWNER_OCCUPIED", "CLEAR")
        low = file_disclosures(seller, rows[2], "VACANT", "CLEAR")

        assert high["eviction_risk_tier"] == "HIGH"
        assert medium["eviction_risk_tier"] == "MEDIUM"
        assert low["eviction_risk_tier"] == "LOW"

        assert high["listing_status"] == "DISCLOSURE_READY"
        assert_timestamp_equals(high["disclosure_ack_at"], CLOCK_SETUP)

        untouched = read_listing(rows[3]["id"])
        assert untouched["eviction_risk_tier"] == "HIGH"
        assert untouched["listing_status"] == "INTAKE"

    def test_bidder_system_fields_are_server_minted_and_version_starts_at_one(self):
        """Registration mints the identity and registration axes plus the risk score the
        client cannot set, and the first mutation advances the version.

        PRD: "The new bidder starts with `identity_verification_status` of `UNVERIFIED` and
        `registration_status` of `PENDING_REVIEW`, with `deposit_funded_cents`,
        `deposit_forfeited_cents` and `fallout_count` all at 0, and with `screen_risk_score`
        computed immediately — which for an unverified bidder with no history evaluates
        to 25."

        Design: Corner/entities/system_fields_are_server_minted_and_version_starts_at_one
        """
        set_clock(CLOCK_SETUP)
        created = validate_success(
            api_client.create_bidder(
                create_bidder_payload(
                    legal_name="System Fields LLC",
                    email="sys@fields.example",
                    mailing_address="11 System Rd, Oakland CA",
                ),
                ANON,
            ),
            expected_status=201,
        )

        assert_common_fields(created, expected_version=1)
        assert is_valid_uuid(created["id"])
        assert created["identity_verification_status"] == "UNVERIFIED"
        assert created["registration_status"] == "PENDING_REVIEW"
        assert created["screen_risk_score"] == 25
        assert created["deposit_funded_cents"] == 0
        assert created["deposit_available_cents"] == 0
        assert created["deposit_forfeited_cents"] == 0
        assert created["fallout_count"] == 0

        # `updated_at` is the logical-clock instant of the most recent mutation, so the
        # clock is advanced before the verification to make the refresh observable.
        verification_at = "2026-08-06T00:00:00Z"
        set_clock(verification_at)
        verified = verify_bidder(created["id"], "VERIFIED", "KYC-SYS-1")
        assert verified["version"] == 2
        assert verified["identity_verification_status"] == "VERIFIED"
        assert verified["registration_status"] == "REGISTERED"
        assert_timestamp_equals(verified["identity_verified_at"], verification_at)
        assert_timestamp_equals(verified["created_at"], CLOCK_SETUP)
        assert_timestamp_equals(verified["updated_at"], verification_at)
        assert verified["updated_at"] != created["updated_at"]
        assert read_bidder(created["id"])["screen_risk_score"] == 0


class TestLotJunction:
    def test_the_lot_slices_the_event_by_asset_graph_in_both_directions(self):
        """One asset carried by two events and one event holding two assets: the two
        filters return different, non-nested slices of the same three lots.

        PRD: "Adding an asset to a `SCHEDULED` event creates an **auction lot**, the
        junction where the marketplace axis and the county axis finally meet."

        Design: Corner/entities/auction_lot_acts_as_event_asset_junction_in_both_directions
        """
        scenario = scheduled_lot(
            event_title="Junction Event A",
            org_name="Junction Assets Inc",
            seller_type="PRIVATE_SELLER",
            contact_email="j@junction.example",
            settlement_account_ref="ACH-JUNC",
            street_address="10 Junction Rd",
            city="Oakland",
            estimated_value_cents=30000000,
            starts_at="2026-09-15T17:00:00Z",
            ends_at="2026-09-15T18:00:00Z",
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T17:30:00Z",
        )
        asset_x = scenario.listing_id
        event_a = scenario.event_id
        lot_ax = scenario.lot_id

        second = create_listing(
            scenario.seller,
            street_address="12 Junction Rd",
            city="Oakland",
            estimated_value_cents=31000000,
        )
        file_disclosures(scenario.seller, second, "VACANT", "CLEAR")
        lot_ay = add_lot(
            event_a,
            second["id"],
            lot_number=2,
            lot_window_start_at="2026-09-15T17:30:00Z",
            lot_window_end_at="2026-09-15T18:00:00Z",
            opening_bid_cents=21000000,
            reserve_price_cents=21000000,
        )
        event_b = create_event(
            title="Junction Event B",
            county_code=COUNTY_SECONDARY,
            starts_at="2026-09-15T18:00:00Z",
            ends_at="2026-09-15T19:00:00Z",
        )
        lot_bx = add_lot(
            event_b["id"],
            asset_x,
            lot_number=1,
            lot_window_start_at="2026-09-15T18:00:00Z",
            lot_window_end_at="2026-09-15T19:00:00Z",
            opening_bid_cents=22000000,
            reserve_price_cents=22000000,
        )

        by_event_a = list_lots(auction_event_id=event_a)
        assert {row["id"] for row in by_event_a} == {lot_ax, lot_ay["id"]}
        by_event_b = list_lots(auction_event_id=event_b["id"])
        assert {row["id"] for row in by_event_b} == {lot_bx["id"]}
        by_asset_x = list_lots(asset_listing_id=asset_x)
        assert {row["id"] for row in by_asset_x} == {lot_ax, lot_bx["id"]}
        by_asset_y = list_lots(asset_listing_id=second["id"])
        assert {row["id"] for row in by_asset_y} == {lot_ay["id"]}

        assert read_event(event_a)["lot_count"] == 2
        assert read_event(event_b["id"])["lot_count"] == 1
        assert read_listing(asset_x)["listing_status"] == "LISTED"
        assert read_listing(second["id"])["listing_status"] == "LISTED"
        assert read_lot(lot_bx["id"])["auction_event_id"] == event_b["id"]
