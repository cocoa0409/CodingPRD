"""Guards that refuse a write: the amount and interval constraints, the county-date
guards, the four-eyes rule, and the pairs where two guards fail at once and the
ladder of §2.9 decides which one the caller hears about."""

from test_helpers import (
    CLOCK_CONTRACT,
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    OPS_CLOSER,
    OPS_CONTRACT,
    TEST_USERS,
    add_lot,
    add_lot_payload,
    api_client,
    assert_timestamp_equals,
    confirm_sale,
    create_event,
    create_trustee_sale,
    create_trustee_sale_payload,
    disclosed_asset,
    disclosures_payload,
    funded_bidder,
    list_holds,
    live_lot,
    make_auction_ops_headers,
    make_bidder_headers,
    place_bid,
    place_bid_payload,
    postpone_sale,
    postpone_trustee_sale_payload,
    read_bid,
    read_bidder,
    read_event,
    read_listing,
    read_lot,
    read_sale,
    read_seller,
    reserve_price_payload,
    sale_contract_payload,
    set_clock,
    sold_lot,
    title_clearance_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["auction_ops_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
TITLE_OFFICER = TEST_USERS["title_officer_headers"]
SELLER_ROLE_ONLY = TEST_USERS["seller_headers"]

EVENT_START = "2026-09-15T17:00:00Z"
EVENT_END = "2026-09-15T19:00:00Z"
WINDOW_START = "2026-09-15T17:00:00Z"
WINDOW_END = "2026-09-15T18:00:00Z"

COUNTY_CLOCK = "2026-09-20T00:00:00Z"
MISSING_LISTING_ID = "00000000-0000-0000-0000-0000000000ff"


class TestAmountConstraints:
    def test_a_raise_short_of_the_increment_is_refused_and_the_exact_increment_lands(self):
        """With an `ACTIVE` bid of 20000000 standing on a lot whose increment is the
        default 500000, a bid of 20300000 is refused and stores nothing, while exactly
        20500000 is accepted — the increment is inclusive at its own value.

        PRD: "The amount must clear the lot's minimum: on a lot with no standing bid,
        where `current_high_bid_cents` is 0, the bid must be at least `opening_bid_cents`;
        on a lot that already has a standing bid, the bid must be at least
        `current_high_bid_cents` plus `min_increment_cents`."

        Design: Corner/validations/bid_below_min_increment_rejected_then_exact_increment_accepted
        """
        scenario = live_lot(
            org_name="Increment Bank",
            seller_type="BANK",
            contact_email="reo@increment.example",
            settlement_account_ref="ACH-INCR-1",
            street_address="1 Increment Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Alameda Increment Session",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        assert read_lot(scenario.lot_id)["min_increment_cents"] == 500000

        one = funded_bidder(
            1000000,
            legal_name="Increment Bidder One LLC",
            email="one@increment.example",
            mailing_address="2 Increment Rd, Oakland CA",
            document_reference="KYC-INCR-1",
            funding_reference="WIRE-INCR-1",
        )
        two = funded_bidder(
            1000000,
            legal_name="Increment Bidder Two LLC",
            email="two@increment.example",
            mailing_address="3 Increment Rd, Oakland CA",
            document_reference="KYC-INCR-2",
            funding_reference="WIRE-INCR-2",
        )
        first_bid = place_bid(scenario.lot_id, one["id"], 20000000)

        response = api_client.place_bid(
            scenario.lot_id,
            place_bid_payload(two["id"], 20300000),
            make_bidder_headers(two["id"]),
        )
        validate_error(response, "ERR_BID_BELOW_MINIMUM", 422)

        assert read_bid(first_bid["id"])["bid_status"] == "ACTIVE"
        assert read_bidder(two["id"])["deposit_available_cents"] == 1000000
        assert list_holds(bidder_id=two["id"]) == []

        winner = place_bid(scenario.lot_id, two["id"], 20500000)
        assert winner["bid_status"] == "ACTIVE"
        assert winner["amount_cents"] == 20500000

        assert read_bid(first_bid["id"])["bid_status"] == "OUTBID"
        assert read_bidder(one["id"])["deposit_available_cents"] == 1000000
        assert read_bidder(two["id"])["deposit_available_cents"] == 0

        _bids, meta = validate_paginated(
            api_client.list_bids(ADMIN, params={"auction_lot_id": scenario.lot_id})
        )
        assert meta["total_count"] == 2

    def test_a_deposit_one_cent_short_fails_where_the_exact_amount_passes(self):
        """The funding gate compares available against required, so 999999 against a
        requirement of 1000000 is refused while exactly 1000000 buys a bid and is taken
        whole into the hold.

        PRD: "Finally the bidder's `deposit_available_cents` must be at least the lot's
        `required_deposit_cents`, or the bid is refused with `ERR_DEPOSIT_INSUFFICIENT` —
        unless the bidder already holds a deposit hold on this very lot whose `status` is
        `HELD` or `EXTENDED`, in which case the funding check is skipped entirely and the
        bidder may raise their own bid without posting a second deposit."

        Design: Corner/validations/deposit_exactly_equal_to_requirement_passes_one_cent_short_fails
        """
        scenario = live_lot(
            org_name="One Cent Servicing",
            seller_type="SERVICER",
            contact_email="reo@onecent.example",
            settlement_account_ref="ACH-CENT-1",
            street_address="1 Onecent Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Alameda One Cent Session",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        assert read_lot(scenario.lot_id)["required_deposit_cents"] == 1000000

        short = funded_bidder(
            999999,
            legal_name="Short Funded Buyers LLC",
            email="short@onecent.example",
            mailing_address="2 Onecent Rd, Oakland CA",
            document_reference="KYC-CENT-1",
            funding_reference="WIRE-CENT-1",
        )
        exact = funded_bidder(
            1000000,
            legal_name="Exact Funded Buyers LLC",
            email="exact@onecent.example",
            mailing_address="3 Onecent Rd, Oakland CA",
            document_reference="KYC-CENT-2",
            funding_reference="WIRE-CENT-2",
        )

        response = api_client.place_bid(
            scenario.lot_id,
            place_bid_payload(short["id"], 20000000),
            make_bidder_headers(short["id"]),
        )
        validate_error(response, "ERR_DEPOSIT_INSUFFICIENT", 402)
        assert read_bidder(short["id"])["deposit_available_cents"] == 999999

        bid = place_bid(scenario.lot_id, exact["id"], 20000000)
        assert bid["bid_status"] == "ACTIVE"
        assert read_bidder(exact["id"])["deposit_available_cents"] == 0

        holds = list_holds(auction_lot_id=scenario.lot_id)
        assert len(holds) == 1
        assert holds[0]["amount_cents"] == 1000000
        assert holds[0]["status"] == "HELD"

        _bids, meta = validate_paginated(
            api_client.list_bids(ADMIN, params={"auction_lot_id": scenario.lot_id})
        )
        assert meta["total_count"] == 1


class TestReserveInvariantOnBothWritePaths:
    def test_a_reserve_under_the_opening_is_refused_when_the_lot_is_born_and_when_it_is_revised(
        self,
    ):
        """The reserve-at-or-above-opening invariant guards both writes: the lot-add is
        refused without consuming the event version, and a later revision that would dip
        under the opening is refused without consuming the lot version.

        PRD: "An `AuctionOps` operator may rewrite `reserve_price_cents` while presenting
        the `expected_auction_lot_version` required by §2.7; the new reserve must still be
        at or above `opening_bid_cents`, or the request is `ERR_RESERVE_BELOW_OPENING`."

        Design: Corner/validations/reserve_below_opening_rejected_on_add_and_on_patch
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Reserve Line Bank",
            seller_type="BANK",
            contact_email="reo@reserveline.example",
            settlement_account_ref="ACH-RESV-1",
            street_address="1 Reserve Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Alameda Reserve Session",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        event_version = event["version"]

        refused = api_client.add_lot(
            event["id"],
            add_lot_payload(
                bundle.listing_id,
                event_version,
                lot_number=1,
                lot_window_start_at=WINDOW_START,
                lot_window_end_at=WINDOW_END,
                opening_bid_cents=20000000,
                reserve_price_cents=19999999,
            ),
            OPS,
        )
        validate_error(refused, "ERR_RESERVE_BELOW_OPENING", 422)

        untouched = read_event(event["id"])
        assert untouched["lot_count"] == 0
        assert untouched["version"] == event_version

        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_number=1,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
            expected_auction_event_version=event_version,
        )
        assert lot["reserve_price_cents"] == 20000000
        lot_version = lot["version"]

        validate_error(
            api_client.update_reserve_price(
                lot["id"], reserve_price_payload(19999999, lot_version), OPS
            ),
            "ERR_RESERVE_BELOW_OPENING",
            422,
        )

        revised = validate_success(
            api_client.update_reserve_price(
                lot["id"], reserve_price_payload(24000000, lot_version), OPS
            )
        )
        assert revised["reserve_price_cents"] == 24000000
        assert revised["version"] == 2
        assert revised["opening_bid_cents"] == 20000000


class TestLadderOrderWhenTwoGuardsFailAtOnce:
    def test_authentication_and_role_answer_before_the_listing_is_looked_up(self):
        """The same call against a listing id that does not exist tells three different
        stories: no `X-User-ID` is refused as unauthenticated, a `Seller` is refused on
        role, and only the `TitleOfficer` gets as far as the 404.

        PRD: "The ladder is grouped into bands: authentication, then existence, then
        ownership, then request shape, then entity state, then optimistic concurrency, then
        compliance and safety, then referential consistency, then temporal windows, then
        value constraints, and finally the fiscal check."

        Design: Corner/validations/auth_then_role_outrank_existence_on_a_missing_listing
        """
        headerless = {"X-User-Role": "TitleOfficer", "Content-Type": "application/json"}

        unauthenticated = validate_error(
            api_client.record_title_clearance(
                MISSING_LISTING_ID, title_clearance_payload(), headerless
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )
        refused_role = validate_error(
            api_client.record_title_clearance(
                MISSING_LISTING_ID, title_clearance_payload(), SELLER_ROLE_ONLY
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            api_client.record_title_clearance(
                MISSING_LISTING_ID, title_clearance_payload(), TITLE_OFFICER
            ),
            "ERR_ASSET_LISTING_NOT_FOUND",
            404,
        )

        assert unauthenticated["error_id"] != "ERR_ASSET_LISTING_NOT_FOUND"
        assert refused_role["error_id"] != "ERR_ASSET_LISTING_NOT_FOUND"

    def test_a_malformed_enum_is_reported_before_the_listing_state(self):
        """A second disclosure filing carrying an occupancy value outside the declared
        set breaks the shape contract and the `INTAKE` precondition at once, and the shape
        error is the one returned; the well-formed retry then surfaces the state error.

        PRD: "`ERR_INVALID_REQUEST` (400) — the body conforms to the endpoint's input
        contract: required fields present, enumerated fields carrying a member of their
        declared set, integers inside their declared ranges, every amount in cents strictly
        greater than zero, datetimes valid ISO 8601 UTC, an end instant strictly after its
        start instant, `limit` between 1 and 100 inclusive, and `offset` not negative.
        Applies to every endpoint."

        Design: Corner/validations/invalid_enum_outranks_the_listing_state_check
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Enum Guard Bank",
            seller_type="BANK",
            contact_email="reo@enumguard.example",
            settlement_account_ref="ACH-ENUM-1",
            street_address="1 Enum Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            occupancy_status="VACANT",
            title_condition="CLEAR",
        )

        malformed = validate_error(
            api_client.file_disclosures(
                bundle.listing_id,
                disclosures_payload("SQUATTER_OCCUPIED", "CLEAR"),
                bundle.seller_headers,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        assert malformed["error_id"] != "ERR_LISTING_NOT_IN_INTAKE"

        validate_error(
            api_client.file_disclosures(
                bundle.listing_id,
                disclosures_payload("OWNER_OCCUPIED", "CLOUDED"),
                bundle.seller_headers,
            ),
            "ERR_LISTING_NOT_IN_INTAKE",
            409,
        )

        listing = read_listing(bundle.listing_id)
        assert listing["occupancy_status"] == "VACANT"
        assert listing["title_condition"] == "CLEAR"

    def test_the_lot_window_must_sit_inside_the_event_before_the_reserve_is_weighed(self):
        """A lot-add that both overruns the session window and prices the reserve under
        the opening is refused on the window; fixing only the window then exposes the
        reserve failure from the very same payload.

        PRD: "`ERR_LOT_WINDOW_OUTSIDE_EVENT` (422) — `lot_window_start_at` is at or after
        the event's `starts_at` and `lot_window_end_at` is at or before the event's
        `ends_at`. Applies to `POST /auction-events/{id}/lots`."

        Design: Corner/validations/window_containment_is_checked_before_the_reserve_rule
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Cascade Check Bank",
            seller_type="BANK",
            contact_email="reo@cascadechk.example",
            settlement_account_ref="ACH-CCHK-1",
            street_address="1 Cascadechk Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Alameda Cascade Check Session",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        event_version = event["version"]

        overrunning = api_client.add_lot(
            event["id"],
            add_lot_payload(
                bundle.listing_id,
                event_version,
                lot_number=1,
                lot_window_start_at="2026-09-15T18:30:00Z",
                lot_window_end_at="2026-09-15T19:30:00Z",
                opening_bid_cents=20000000,
                reserve_price_cents=19000000,
            ),
            OPS,
        )
        window_error = validate_error(overrunning, "ERR_LOT_WINDOW_OUTSIDE_EVENT", 422)
        assert window_error["error_id"] != "ERR_RESERVE_BELOW_OPENING"

        contained = api_client.add_lot(
            event["id"],
            add_lot_payload(
                bundle.listing_id,
                event_version,
                lot_number=1,
                lot_window_start_at="2026-09-15T18:30:00Z",
                lot_window_end_at="2026-09-15T19:00:00Z",
                opening_bid_cents=20000000,
                reserve_price_cents=19000000,
            ),
            OPS,
        )
        validate_error(contained, "ERR_RESERVE_BELOW_OPENING", 422)

        untouched = read_event(event["id"])
        assert untouched["lot_count"] == 0
        assert untouched["version"] == event_version
        assert read_listing(bundle.listing_id)["listing_status"] == "DISCLOSURE_READY"


class TestCountySaleDateGuards:
    def test_a_noticed_date_in_the_past_is_refused_on_creation_and_on_postponement(self):
        """Both county write paths compare against the logical clock rather than against
        the date they are replacing: with the clock at 2026-09-20 a notice for 09-15 never
        exists, and a postponement to 09-16 leaves the confirmed 10-15 notice standing.

        PRD: "`ERR_SALE_DATE_NOT_FUTURE` (422) — the noticed sale instant is strictly after
        the logical clock: `sale_scheduled_at` on creation, `new_sale_at` on postponement,
        and the standing `sale_scheduled_at` on confirmation. Applies to
        `POST /trustee-sales`, `POST /trustee-sales/{id}/postpone`, and
        `POST /trustee-sales/{id}/confirm`."

        Design: Corner/validations/trustee_sale_dates_must_lie_in_the_future_on_create_and_on_postpone
        """
        set_clock(COUNTY_CLOCK)
        bundle = disclosed_asset(
            org_name="Future Date Servicing",
            seller_type="SERVICER",
            contact_email="reo@futuredate.example",
            settlement_account_ref="ACH-FUTR-1",
            street_address="1 Future Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )

        validate_error(
            api_client.create_trustee_sale(
                create_trustee_sale_payload(bundle.listing_id, "2026-09-15T18:00:00Z"),
                TRUSTEE,
            ),
            "ERR_SALE_DATE_NOT_FUTURE",
            422,
        )

        sale = create_trustee_sale(bundle.listing_id, "2026-10-15T18:00:00Z")
        confirm_sale(sale["id"], confirmation_reference="TS-FUTR-1")

        validate_error(
            api_client.postpone_trustee_sale(
                sale["id"],
                postpone_trustee_sale_payload(
                    "2026-09-16T18:00:00Z",
                    postponement_reason="clerk requested an earlier date",
                ),
                TRUSTEE,
            ),
            "ERR_SALE_DATE_NOT_FUTURE",
            422,
        )

        standing = read_sale(sale["id"])
        assert standing["status"] == "CONFIRMED"
        assert_timestamp_equals(standing["sale_scheduled_at"], "2026-10-15T18:00:00Z")
        assert standing["postponement_count"] == 0

        _sales, meta = validate_paginated(
            api_client.list_asset_listing_trustee_sales(bundle.listing_id, ADMIN)
        )
        assert meta["total_count"] == 1

    def test_the_statutory_cap_stops_the_third_postponement_though_its_date_is_valid(self):
        """Every date offered here is in the future, so only the count is at issue: under
        a cap of 2 the notice may be pushed twice and the third attempt is refused, leaving
        the count at 2 and the date at the second postponement's value.

        PRD: "Two guards apply before anything moves: the resulting count — the current
        `postponement_count` plus one — may not exceed `statutory_max_postponements`, or the
        request is `ERR_POSTPONEMENT_LIMIT_EXCEEDED`; and `new_sale_at` must be strictly
        after the logical clock, or the request is `ERR_SALE_DATE_NOT_FUTURE`."

        Design: Corner/validations/postponements_are_capped_by_the_statutory_maximum
        """
        set_clock(COUNTY_CLOCK)
        bundle = disclosed_asset(
            org_name="Cap Postpone Servicing",
            seller_type="SERVICER",
            contact_email="reo@cappost.example",
            settlement_account_ref="ACH-CAPP-1",
            street_address="1 Cappost Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        sale = create_trustee_sale(
            bundle.listing_id, "2026-10-15T18:00:00Z", statutory_max_postponements=2
        )
        assert sale["statutory_max_postponements"] == 2
        confirm_sale(sale["id"], confirmation_reference="TS-CAPP-1")

        first = postpone_sale(sale["id"], "2026-10-22T18:00:00Z", reason="bankruptcy stay")
        assert first["postponement_count"] == 1
        assert first["status"] == "POSTPONED"

        confirm_sale(sale["id"], confirmation_reference="TS-CAPP-2")
        second = postpone_sale(
            sale["id"], "2026-10-29T18:00:00Z", reason="loss mitigation review"
        )
        assert second["postponement_count"] == 2

        confirm_sale(sale["id"], confirmation_reference="TS-CAPP-3")
        validate_error(
            api_client.postpone_trustee_sale(
                sale["id"],
                postpone_trustee_sale_payload(
                    "2026-11-05T18:00:00Z", postponement_reason="third attempt"
                ),
                TRUSTEE,
            ),
            "ERR_POSTPONEMENT_LIMIT_EXCEEDED",
            409,
        )

        capped = read_sale(sale["id"])
        assert capped["postponement_count"] == 2
        assert_timestamp_equals(capped["sale_scheduled_at"], "2026-10-29T18:00:00Z")


class TestFourEyesRule:
    def test_the_four_eyes_rule_bites_on_the_identity_and_not_on_the_role(self):
        """The operator who hammered the lot down is refused the contract while a second
        operator of the very same role executes the identical request, so the rule is
        keyed on the acting identity rather than on authorization.

        PRD: "And the four-eyes rule of §2.1 applies: the acting `X-User-ID` must differ
        from the lot's `closed_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES` —
        the operator who hammered the lot down may not also be the operator who binds the
        buyer to it."

        Design: Corner/validations/segregation_of_duties_only_bites_when_the_same_user_acts_twice
        """
        scenario = sold_lot(
            org_name="Four Eyes Bank",
            seller_type="BANK",
            contact_email="reo@foureyes.example",
            settlement_account_ref="ACH-4EYE-1",
            default_commission_bps=500,
            street_address="1 Foureyes Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Alameda Four Eyes Session",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
            clear_title=True,
            bid_amount_cents=20000000,
            funded_cents=1000000,
            bidder_legal_name="Four Eyes Bidder LLC",
            bidder_email="bid@foureyes.example",
            closer_user_id=OPS_CLOSER,
        )
        assert read_lot(scenario.lot_id)["closed_by_user_id"] == OPS_CLOSER

        set_clock(CLOCK_CONTRACT)
        collided = validate_error(
            api_client.execute_sale_contract(
                scenario.lot_id,
                sale_contract_payload(closing_window_days=21),
                make_auction_ops_headers(OPS_CLOSER),
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        assert collided["error_id"] != "ERR_FORBIDDEN_ROLE"

        _contracts, meta = validate_paginated(
            api_client.list_lot_sale_contracts(scenario.lot_id, OPS)
        )
        assert meta["total_count"] == 0

        contract = validate_success(
            api_client.execute_sale_contract(
                scenario.lot_id,
                sale_contract_payload(closing_window_days=21),
                make_auction_ops_headers(OPS_CONTRACT),
            ),
            201,
        )
        assert contract["contract_status"] == "EXECUTED"
        assert contract["executed_by_user_id"] == OPS_CONTRACT
        assert read_listing(scenario.listing_id)["listing_status"] == "SOLD_PENDING_CONTRACT"
        assert read_seller(scenario.seller_id)["settled_net_cents"] == 18930000
