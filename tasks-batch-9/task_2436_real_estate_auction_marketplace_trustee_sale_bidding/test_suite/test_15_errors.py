"""The refusals themselves: each family of failure reports its own identifier, and
where one request violates two rules at once the global ladder decides which
identifier the caller hears."""

from test_helpers import (
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    OPS_CLOSER,
    OPS_CONTRACT,
    TEST_USERS,
    add_lot,
    add_lot_payload,
    api_client,
    assert_timestamp_equals,
    cleared_asset,
    close_lot,
    close_lot_payload,
    create_event,
    create_exclusion,
    create_exclusion_payload,
    create_listing,
    disclosed_asset,
    execute_contract,
    file_disclosures,
    fund_deposit_payload,
    funded_bidder,
    lift_exclusion_payload,
    make_auction_ops_headers,
    make_bidder_headers,
    open_event,
    open_event_payload,
    place_bid,
    place_bid_payload,
    read_bidder,
    read_contract,
    read_event,
    read_listing,
    read_lot,
    record_fallout,
    record_title_clearance,
    register_bidder,
    reserve_price_payload,
    sale_contract_payload,
    second_chance_offer_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_bidder,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["auction_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

EVENT_START = "2026-09-15T17:00:00Z"
EVENT_END = "2026-09-15T19:00:00Z"
WINDOW_START = "2026-09-15T17:00:00Z"
WINDOW_END = "2026-09-15T18:00:00Z"

MISSING_LOT_ID = "00000000-0000-0000-0000-0000000000ee"
MISSING_EXCLUSION_ID = "00000000-0000-0000-0000-0000000000f1"
MISSING_BID_ID = "00000000-0000-0000-0000-0000000000f2"
MISSING_BIDDER_ID = "00000000-0000-0000-0000-0000000000f3"


class TestSessionAdmissionErrors:
    def test_the_open_call_fails_three_ways_in_the_ladder_s_own_order(self):
        """An empty roster answers before the clock does, a stocked session before its
        start instant answers with the clock rule, and once the session is live both the
        open call and a late lot addition answer that it is no longer scheduled.

        PRD: "To make the API deterministic, every check the server performs occupies a
        fixed rung on a single global ladder, the ladder is walked in ascending order, and
        **the first failing check decides the response**; no later check can mask an earlier
        one, and no earlier check is skipped because a later one would also fail."
        PRD: "The event must be `SCHEDULED`, or `ERR_EVENT_NOT_SCHEDULED`; it must hold at
        least one lot, so a `lot_count` of 0 is `ERR_EVENT_HAS_NO_LOTS`; the logical clock
        must have reached or passed the event's `starts_at`, or `ERR_EVENT_NOT_STARTED`; and
        if the event carries a `trustee_sale_id`, that sale's `status` must be `CONFIRMED`,
        or `ERR_TRUSTEE_SALE_NOT_CONFIRMED` — an event with no county linkage passes this
        gate unconditionally."
        PRD: "The event then moves `SCHEDULED → LIVE`, `opened_at` is stamped with the
        logical clock, and every lot of the event whose `lot_status` is `PENDING` or
        `SUSPENDED` moves to `OPEN`."
        PRD: "The event must still be `SCHEDULED`: lots cannot be added to a session that
        has already gone live, which is `ERR_EVENT_NOT_SCHEDULED`."

        Design: Corner/errors/open_event_ladder_no_lots_then_not_started_then_not_scheduled
        """
        set_clock("2026-09-15T16:00:00Z")
        bundle = disclosed_asset(
            org_name="Open Ladder Bank",
            seller_type="BANK",
            contact_email="reo@openladder.example",
            settlement_account_ref="ACH-OPLD-1",
            street_address="1 Openladder Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        second_listing = create_listing(
            bundle.seller,
            street_address="2 Openladder Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        second_listing = file_disclosures(bundle.seller, second_listing, "VACANT", "CLEAR")
        event = create_event(
            title="Open Ladder Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )

        empty = validate_error(
            api_client.open_auction_event(event["id"], open_event_payload(), OPS),
            "ERR_EVENT_HAS_NO_LOTS",
            409,
        )
        assert empty["error_id"] != "ERR_EVENT_NOT_STARTED"

        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        validate_error(
            api_client.open_auction_event(event["id"], open_event_payload(), OPS),
            "ERR_EVENT_NOT_STARTED",
            409,
        )

        set_clock(EVENT_START)
        live = open_event(event["id"])
        assert live["event_status"] == "LIVE"
        assert_timestamp_equals(live["opened_at"], EVENT_START)

        validate_error(
            api_client.open_auction_event(event["id"], open_event_payload(), OPS),
            "ERR_EVENT_NOT_SCHEDULED",
            409,
        )
        validate_error(
            api_client.add_lot(
                event["id"],
                add_lot_payload(
                    second_listing["id"],
                    read_event(event["id"])["version"],
                    lot_number=2,
                    lot_window_start_at=WINDOW_START,
                    lot_window_end_at=WINDOW_END,
                ),
                OPS,
            ),
            "ERR_EVENT_NOT_SCHEDULED",
            409,
        )

        assert read_event(event["id"])["lot_count"] == 1
        assert read_lot(lot["id"])["lot_status"] == "OPEN"
        assert read_listing(second_listing["id"])["listing_status"] == "DISCLOSURE_READY"

    def test_three_different_admission_refusals_leave_the_roster_untouched(self):
        """A re-used lot number is reported before the unlistable state of the very same
        asset, a free lot number then uncovers that state, a defective title is refused on
        its own rung, and no refusal consumes the session's version.

        PRD: "To make the API deterministic, every check the server performs occupies a
        fixed rung on a single global ladder, the ladder is walked in ascending order, and
        **the first failing check decides the response**; no later check can mask an earlier
        one, and no earlier check is skipped because a later one would also fail."
        PRD: "`ERR_DUPLICATE_LOT_NUMBER` (409) — no other lot of the same auction event
        already uses the submitted `lot_number`. Applies to `POST /auction-events/{id}/lots`."
        PRD: "The asset itself must be listable — `listing_status` of `DISCLOSURE_READY` or
        `LISTED`, otherwise `ERR_LISTING_NOT_LISTABLE` — and its title axis must not read
        `DEFECTIVE`, otherwise `ERR_TITLE_DEFECTIVE`."

        Design: Corner/errors/lot_admission_ladder_duplicate_then_unlistable_then_defective
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Admission Bank",
            seller_type="BANK",
            contact_email="reo@admission.example",
            settlement_account_ref="ACH-ADMS-1",
            street_address="1 Admission Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        raw = create_listing(
            bundle.seller,
            street_address="2 Admission Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        assert raw["listing_status"] == "INTAKE"

        bad_title = create_listing(
            bundle.seller,
            street_address="3 Admission Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        bad_title = file_disclosures(bundle.seller, bad_title, "VACANT", "UNKNOWN")
        bad_title = record_title_clearance(
            bad_title["id"], "DEFECTIVE", "CLOUDED", title_report_reference="TR-ADMS-BAD"
        )
        assert bad_title["title_clearance_status"] == "DEFECTIVE"
        assert bad_title["listing_status"] == "DISCLOSURE_READY"

        event = create_event(
            title="Admission Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        version = read_event(event["id"])["version"]

        def attempt(listing_id, lot_number):
            return api_client.add_lot(
                event["id"],
                add_lot_payload(
                    listing_id,
                    version,
                    lot_number=lot_number,
                    lot_window_start_at="2026-09-15T18:00:00Z",
                    lot_window_end_at="2026-09-15T19:00:00Z",
                ),
                OPS,
            )

        duplicate = validate_error(
            attempt(raw["id"], 1), "ERR_DUPLICATE_LOT_NUMBER", 409
        )
        assert duplicate["error_id"] != "ERR_LISTING_NOT_LISTABLE"
        validate_error(attempt(raw["id"], 2), "ERR_LISTING_NOT_LISTABLE", 409)
        validate_error(attempt(bad_title["id"], 3), "ERR_TITLE_DEFECTIVE", 409)

        after = read_event(event["id"])
        assert after["lot_count"] == 1
        assert after["version"] == version
        assert read_listing(raw["id"])["listing_status"] == "INTAKE"
        assert read_listing(bad_title["id"])["listing_status"] == "DISCLOSURE_READY"


class TestBidderStandingErrors:
    def test_the_two_bidder_gates_stay_separately_reachable(self):
        """The registration rung refuses only a suspended bidder, so an unverified one
        falls through to the identity rung, while a bidder suspended by a platform-wide
        exclusion is told about its registration rather than the exclusion.

        PRD: "`ERR_BIDDER_NOT_REGISTERED` (409) — for an identity-verification decision, the
        bidder's `identity_verification_status` is `UNVERIFIED`; for bidding and for
        responding to an offer, the bidder's `registration_status` is anything other than
        `SUSPENDED`."
        PRD: "This rung deliberately does not demand `REGISTERED`, so that a
        `PENDING_REVIEW` or `REJECTED` bidder is caught one band lower by rung 34 and a
        `BARRED` bidder by rung 35, keeping all three errors reachable."
        PRD: "Recording an exclusion suspends the bidder only when the exclusion is both
        platform-wide and already in force: if its `county_code` is `ALL` and its
        `effective_at` is at or before the logical clock, a bidder whose
        `registration_status` is `REGISTERED` moves `REGISTERED → SUSPENDED`."
        PRD: "The ordering of those five compliance checks is the one fixed in §2.9, so a
        suspended bidder whose identity is also unverified is told
        `ERR_BIDDER_NOT_REGISTERED`."

        Design: Corner/errors/unverified_and_suspended_bidders_hit_different_gates
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Gate Bank",
            seller_type="BANK",
            contact_email="reo@gate.example",
            settlement_account_ref="ACH-GATE-1",
            street_address="1 Gate Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Gate Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        assert lot["required_deposit_cents"] == 1000000

        pending = funded_bidder(
            1000000,
            legal_name="Pending Review Bidder LLC",
            email="pending@gate.example",
            mailing_address="2 Gate Rd, Oakland CA",
            funding_reference="WIRE-GATE-P",
            verified=False,
        )
        assert pending["registration_status"] == "PENDING_REVIEW"

        suspended = funded_bidder(
            1000000,
            legal_name="Suspended Bidder LLC",
            email="susp@gate.example",
            mailing_address="3 Gate Rd, Oakland CA",
            document_reference="KYC-GATE-S",
            funding_reference="WIRE-GATE-S",
        )

        set_clock("2026-09-15T17:05:00Z")
        open_event(event["id"])
        set_clock("2026-09-15T17:10:00Z")
        create_exclusion(
            suspended["id"],
            "SANCTIONS_LIST",
            "2026-09-01T00:00:00Z",
            county_code="ALL",
            notes="list match",
        )
        assert read_bidder(suspended["id"])["registration_status"] == "SUSPENDED"

        unverified_refusal = validate_error(
            api_client.place_bid(
                lot["id"],
                place_bid_payload(pending["id"], 20000000),
                make_bidder_headers(pending["id"]),
            ),
            "ERR_IDENTITY_UNVERIFIED",
            409,
        )
        assert unverified_refusal["error_id"] != "ERR_BIDDER_NOT_REGISTERED"

        suspended_refusal = validate_error(
            api_client.place_bid(
                lot["id"],
                place_bid_payload(suspended["id"], 20000000),
                make_bidder_headers(suspended["id"]),
            ),
            "ERR_BIDDER_NOT_REGISTERED",
            409,
        )
        assert suspended_refusal["error_id"] != "ERR_BIDDER_EXCLUDED"

        standing = read_lot(lot["id"])
        assert standing["current_high_bid_cents"] == 0
        assert standing["lot_status"] == "OPEN"
        assert read_bidder(pending["id"])["deposit_available_cents"] == 1000000
        assert read_bidder(suspended["id"])["deposit_available_cents"] == 1000000

    def test_the_second_fallout_bars_the_bidder_and_closes_the_wallet(self):
        """One bidder wins two lots and walks away from both: the first default leaves the
        registration intact, the second bars it and writes the platform's own exclusion,
        after which even an incoming wire is refused.

        PRD: "`forfeiture_seller_net_cents` is the `forfeited_deposit_cents` multiplied by
        6000 basis points and divided by ten thousand — sixty percent — rounded half up to
        whole cents, and `forfeiture_platform_fee_cents` is whatever remains after
        subtracting the seller's share from the forfeited amount."
        PRD: "When the increment brings a bidder's `fallout_count` to 2 or more, that
        bidder's `registration_status` moves to `BARRED` — reachable from either `REGISTERED`
        or `SUSPENDED`, and terminal from both — and the platform writes an eligibility
        exclusion of its own accord, with an `exclusion_type` of `PRIOR_FALLOUT`, a
        `county_code` of `ALL`, an `effective_at` equal to the logical clock, and a `status`
        of `ACTIVE`."
        PRD: "A bidder that has been barred may not fund at all — the attempt is
        `ERR_BIDDER_BARRED` — and a bidder may only fund its own wallet, on pain of
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/errors/barred_bidder_cannot_fund_after_the_second_fallout
        """
        set_clock(CLOCK_SETUP)
        first_bundle = cleared_asset(
            org_name="Barred Bank",
            seller_type="BANK",
            contact_email="reo@barred.example",
            settlement_account_ref="ACH-BARR-1",
            default_commission_bps=500,
            street_address="1 Barred Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        second_listing = create_listing(
            first_bundle.seller,
            street_address="2 Barred Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        second_listing = file_disclosures(
            first_bundle.seller, second_listing, "VACANT", "CLEAR"
        )
        second_listing = record_title_clearance(
            second_listing["id"], "CLEARED", "CLEAR", title_report_reference="TR-BARR-B"
        )

        event = create_event(
            title="Barred Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        lot_a = add_lot(
            event["id"],
            first_bundle.listing_id,
            lot_number=1,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        lot_b = add_lot(
            event["id"],
            second_listing["id"],
            lot_number=2,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        bidder = funded_bidder(
            2000000,
            legal_name="Serial Fallout Bidder LLC",
            email="serial@barred.example",
            mailing_address="3 Barred Rd, Oakland CA",
            document_reference="KYC-BARR-1",
            funding_reference="WIRE-BARR-1",
        )

        set_clock("2026-09-15T17:05:00Z")
        open_event(event["id"])
        place_bid(lot_a["id"], bidder["id"], 20000000)
        place_bid(lot_b["id"], bidder["id"], 20000000)

        set_clock("2026-09-15T18:05:00Z")
        close_lot(lot_a["id"], OPS_CLOSER)
        close_lot(lot_b["id"], OPS_CLOSER)

        set_clock("2026-09-15T18:10:00Z")
        contract_a = execute_contract(lot_a["id"])
        set_clock("2026-09-15T18:11:00Z")
        contract_b = execute_contract(lot_b["id"])

        set_clock("2026-10-01T00:00:00Z")
        first_fallout = record_fallout(contract_a["id"], reason="first failure to close")
        assert first_fallout["forfeiture_seller_net_cents"] == 600000
        after_first = read_bidder(bidder["id"])
        assert after_first["fallout_count"] == 1
        assert after_first["registration_status"] == "REGISTERED"

        set_clock("2026-10-02T00:00:00Z")
        second_fallout = record_fallout(contract_b["id"], reason="second failure to close")
        assert second_fallout["forfeiture_seller_net_cents"] == 600000
        after_second = read_bidder(bidder["id"])
        assert after_second["fallout_count"] == 2
        assert after_second["registration_status"] == "BARRED"

        auto_exclusions, auto_meta = validate_paginated(
            api_client.list_bidder_exclusions(
                bidder["id"], COMPLIANCE, params={"exclusion_type": "PRIOR_FALLOUT"}
            )
        )
        assert auto_meta["total_count"] == 1
        assert auto_exclusions[0]["county_code"] == "ALL"
        assert auto_exclusions[0]["status"] == "ACTIVE"
        assert_timestamp_equals(
            auto_exclusions[0]["effective_at"], "2026-10-02T00:00:00Z"
        )

        validate_error(
            api_client.fund_deposit(
                bidder["id"],
                fund_deposit_payload(500000, funding_reference="WIRE-BARR-2"),
                make_bidder_headers(bidder["id"]),
            ),
            "ERR_BIDDER_BARRED",
            403,
        )

        final = read_bidder(bidder["id"])
        assert final["deposit_funded_cents"] == 2000000
        assert final["deposit_forfeited_cents"] == 2000000
        assert final["deposit_available_cents"] == 0
        assert read_listing(first_bundle.listing_id)["listing_status"] == "RELIST_PENDING"
        assert read_listing(second_listing["id"])["listing_status"] == "RELIST_PENDING"
        assert read_contract(contract_a["id"])["settlement_status"] == "VOID"
        assert read_contract(contract_b["id"])["settlement_status"] == "VOID"


class TestReserveRewriteErrors:
    def test_the_reserve_path_fails_by_existence_then_version_then_standing_bid(self):
        """An unknown lot is a plain 404, replaying a consumed version is the concurrency
        refusal, and once a bid stands the current version passes the concurrency check only
        to meet the frozen-reserve rule.

        PRD: "`ERR_AUCTION_LOT_NOT_FOUND` (404) — the auction lot id resolves to an
        `AuctionLot`."
        PRD: "A mismatch against the lot's current `version` is rejected with
        `ERR_STALE_LOT_VERSION` (HTTP 412)."
        PRD: "The moment a bid stands on the lot — that is, as soon as
        `current_high_bid_cents` is anything other than 0 — the reserve is frozen, and a
        revision attempt is `ERR_LOT_HAS_BIDS`."
        PRD: "A successful revision advances the lot's `version` by 1."

        Design: Corner/errors/reserve_rewrite_ladder_missing_lot_then_stale_version_then_standing_bid
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Reserve Ladder Bank",
            seller_type="BANK",
            contact_email="reo@rladder.example",
            settlement_account_ref="ACH-RLDR-1",
            street_address="1 Rladder Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Reserve Ladder Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        assert lot["version"] == 1
        bidder = funded_bidder(
            1000000,
            legal_name="Reserve Ladder Bidder LLC",
            email="bid@rladder.example",
            mailing_address="2 Rladder Rd, Oakland CA",
            document_reference="KYC-RLDR-1",
            funding_reference="WIRE-RLDR-1",
        )

        validate_error(
            api_client.update_reserve_price(
                MISSING_LOT_ID, reserve_price_payload(24000000, 1), OPS
            ),
            "ERR_AUCTION_LOT_NOT_FOUND",
            404,
        )

        revised = validate_success(
            api_client.update_reserve_price(
                lot["id"], reserve_price_payload(24000000, 1), OPS
            )
        )
        assert revised["reserve_price_cents"] == 24000000
        assert revised["version"] == 2

        validate_error(
            api_client.update_reserve_price(
                lot["id"], reserve_price_payload(26000000, 1), OPS
            ),
            "ERR_STALE_LOT_VERSION",
            412,
        )
        held = read_lot(lot["id"])
        assert held["reserve_price_cents"] == 24000000
        assert held["version"] == 2

        set_clock("2026-09-15T17:05:00Z")
        open_event(event["id"])
        bid = place_bid(lot["id"], bidder["id"], 20000000)
        assert bid["amount_cents"] == 20000000
        current_version = read_lot(lot["id"])["version"]
        assert read_lot(lot["id"])["current_high_bid_cents"] == 20000000

        frozen = validate_error(
            api_client.update_reserve_price(
                lot["id"], reserve_price_payload(21000000, current_version), OPS
            ),
            "ERR_LOT_HAS_BIDS",
            409,
        )
        assert frozen["error_id"] != "ERR_STALE_LOT_VERSION"
        assert read_lot(lot["id"])["reserve_price_cents"] == 24000000


class TestPrematureCloseAndContractErrors:
    def test_the_lot_cannot_close_early_and_no_contract_precedes_the_hammer(self):
        """Half an hour before the bidding window ends the close is refused and stamps
        nothing, and both writes that presuppose a hammered lot — the purchase contract and
        the second-chance offer — refuse on the same precondition.

        PRD: "The lot must be `OPEN` or `EXTENDED` under a `LIVE` event, and the logical
        clock must have reached or passed the lot's `bid_close_at` — closing early, including
        closing before an extension that a late bid has just pushed out, is
        `ERR_LOT_WINDOW_STILL_OPEN`."
        PRD: "`ERR_LOT_NOT_CLOSED_SOLD` (409) — the lot's `lot_status` is `CLOSED_SOLD`.
        Applies to `POST /auction-lots/{id}/sale-contract` and
        `POST /auction-lots/{id}/second-chance-offers`."

        Design: Corner/errors/lot_close_before_its_window_ends_and_contract_before_the_sale
        """
        set_clock(CLOCK_SETUP)
        bundle = cleared_asset(
            org_name="Early Close Bank",
            seller_type="BANK",
            contact_email="reo@earlyclose.example",
            settlement_account_ref="ACH-EARL-1",
            street_address="1 Earlyclose Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Early Close Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        bidder = funded_bidder(
            1000000,
            legal_name="Early Close Bidder LLC",
            email="bid@earlyclose.example",
            mailing_address="2 Earlyclose Rd, Oakland CA",
            document_reference="KYC-EARL-1",
            funding_reference="WIRE-EARL-1",
        )

        set_clock("2026-09-15T17:05:00Z")
        open_event(event["id"])
        place_bid(lot["id"], bidder["id"], 20000000)

        set_clock("2026-09-15T17:30:00Z")
        validate_error(
            api_client.close_lot(
                lot["id"], close_lot_payload(), make_auction_ops_headers(OPS_CLOSER)
            ),
            "ERR_LOT_WINDOW_STILL_OPEN",
            409,
        )
        standing = read_lot(lot["id"])
        assert standing["lot_status"] == "OPEN"
        assert standing.get("closed_at") is None
        assert standing.get("closed_by_user_id") is None

        validate_error(
            api_client.execute_sale_contract(
                lot["id"], sale_contract_payload(), make_auction_ops_headers(OPS_CONTRACT)
            ),
            "ERR_LOT_NOT_CLOSED_SOLD",
            409,
        )
        validate_error(
            api_client.create_second_chance_offer(
                lot["id"],
                second_chance_offer_payload(),
                make_auction_ops_headers(OPS_CONTRACT),
            ),
            "ERR_LOT_NOT_CLOSED_SOLD",
            409,
        )

        _, contracts_meta = validate_paginated(
            api_client.list_lot_sale_contracts(lot["id"], OPS)
        )
        assert contracts_meta["total_count"] == 0
        assert read_listing(bundle.listing_id)["listing_status"] == "LISTED"


class TestNotFoundIdentifiers:
    def test_each_resource_family_reports_its_own_not_found_identifier(self):
        """Lifting an exclusion that does not exist, reading a bid that does not exist and
        excluding a bidder that does not exist each answer with their own identifier rather
        than a shared 404.

        PRD: "`ERR_EXCLUSION_NOT_FOUND` (404) — the exclusion id in the path resolves to an
        `EligibilityExclusion`. Applies to `POST /eligibility-exclusions/{id}/lift`."
        PRD: "`ERR_BID_NOT_FOUND` (404) — the bid id in the path resolves to a `Bid`.
        Applies to `GET /bids/{id}`."
        PRD: "`ERR_BIDDER_NOT_FOUND` (404) — a bidder id in the path or body resolves to a
        `Bidder`."

        Design: Corner/errors/lift_and_bid_lookups_report_their_own_not_found_ids
        """
        set_clock("2026-09-10T00:00:00Z")
        bidder = register_bidder(
            legal_name="Lookup Bidder LLC",
            email="lookup@lookup.example",
            mailing_address="1 Lookup Rd, Oakland CA",
        )
        bidder = verify_bidder(bidder["id"], "VERIFIED", "KYC-LOOK-1")

        validate_error(
            api_client.lift_eligibility_exclusion(
                MISSING_EXCLUSION_ID,
                lift_exclusion_payload(notes="no such exclusion"),
                COMPLIANCE,
            ),
            "ERR_EXCLUSION_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_bid(MISSING_BID_ID, OPS), "ERR_BID_NOT_FOUND", 404
        )
        validate_error(
            api_client.create_eligibility_exclusion(
                create_exclusion_payload(
                    MISSING_BIDDER_ID, "SANCTIONS_LIST", "2026-09-10T00:00:00Z"
                ),
                COMPLIANCE,
            ),
            "ERR_BIDDER_NOT_FOUND",
            404,
        )

        assert read_bidder(bidder["id"])["registration_status"] == "REGISTERED"
        _, exclusions_meta = validate_paginated(
            api_client.list_bidder_exclusions(bidder["id"], COMPLIANCE)
        )
        assert exclusions_meta["total_count"] == 0
