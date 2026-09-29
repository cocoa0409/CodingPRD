"""The read and write channels themselves: what a write path stores is what the read
path returns, filters and pages compose, cross-references are resolved, and the
computed assessment answers in the mode it was asked for."""

from test_helpers import (
    CLOCK_CONTRACT,
    CLOCK_EVENT_OPEN,
    CLOCK_LOT_CLOSE,
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    COUNTY_SECONDARY,
    OPS_CONTRACT,
    TEST_USERS,
    add_lot,
    api_client,
    assert_timestamp_equals,
    cleared_asset,
    close_contract_payload,
    close_lot,
    confirm_sale,
    create_auction_event_payload,
    create_event,
    create_exclusion,
    create_listing,
    create_offer,
    create_trustee_sale,
    disclosed_asset,
    eligibility_assessment,
    execute_contract,
    executed_contract,
    fallout_payload,
    funded_bidder,
    lift_exclusion,
    list_holds,
    live_lot,
    make_auction_ops_headers,
    make_bidder_headers,
    make_seller_headers,
    open_event,
    place_bid,
    read_bidder,
    read_contract,
    read_hold,
    read_listing,
    read_lot,
    read_offer,
    read_sale,
    read_seller,
    record_fallout,
    respond_to_offer,
    respond_to_offer_payload,
    scheduled_lot,
    second_chance_offer_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["auction_ops_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

EVENT_START = "2026-09-15T17:00:00Z"
EVENT_END = "2026-09-15T19:00:00Z"
WINDOW_START = "2026-09-15T17:00:00Z"
WINDOW_END = "2026-09-15T18:00:00Z"

MISSING_EVENT_ID = "00000000-0000-0000-0000-0000000000aa"
MISSING_SALE_ID = "00000000-0000-0000-0000-0000000000bb"
MISSING_CONTRACT_ID = "00000000-0000-0000-0000-0000000000cc"
MISSING_OFFER_ID = "00000000-0000-0000-0000-0000000000dd"


class TestAuctionEventChannels:
    def test_an_event_reads_back_as_written_and_one_query_composes_four_parameters(self):
        """Three sessions are scheduled, two of them in the same county, and a single
        query filters by county and status while paging past the first match; an unknown
        id answers with the 404 rather than an empty body.

        PRD: "Unless a specific endpoint states otherwise, every collection is ordered by
        `created_at` ascending, so that pagination over a growing collection remains stable
        for records already written."
        PRD: "List responses populate `limit`, `offset`, `total_count`, and `has_more` in
        the `meta` object, where `total_count` is the number of records matching the
        request's filters before pagination is applied and `has_more` indicates whether
        records remain beyond the current page."

        Design: Corner/endpoints/event_create_read_and_list_round_trip_with_filters
        """
        set_clock(CLOCK_SETUP)
        first = create_event(
            title="CRUD Event One",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )
        assert first["title"] == "CRUD Event One"
        assert first["event_status"] == "SCHEDULED"
        assert first["lot_count"] == 0

        second = create_event(
            title="CRUD Event Two",
            county_code=COUNTY_PRIMARY,
            starts_at="2026-09-15T19:31:00Z",
            ends_at="2026-09-15T20:30:00Z",
        )
        create_event(
            title="CRUD Event Three",
            county_code=COUNTY_SECONDARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )

        fetched = validate_success(api_client.get_auction_event(first["id"], ANONYMOUS))
        assert fetched["id"] == first["id"]
        assert fetched["title"] == "CRUD Event One"
        assert_timestamp_equals(fetched["starts_at"], EVENT_START)
        assert fetched["reschedule_count"] == 0

        page, meta = validate_paginated(
            api_client.list_auction_events(
                OPS,
                params={
                    "county_code": COUNTY_PRIMARY,
                    "event_status": "SCHEDULED",
                    "limit": 1,
                    "offset": 1,
                },
            )
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert [row["id"] for row in page] == [second["id"]]

        validate_error(
            api_client.get_auction_event(MISSING_EVENT_ID, OPS),
            "ERR_AUCTION_EVENT_NOT_FOUND",
            404,
        )

    def test_binding_a_session_to_the_county_leg_demands_a_notice_that_exists(self):
        """The optional county link is a real cross-reference: an unknown sale id creates
        nothing at all, while a valid one leaves the session reachable from both ends
        without disturbing the notice's own status.

        PRD: "`ERR_TRUSTEE_SALE_NOT_FOUND` (404) — a trustee sale id in the path or body
        resolves to a `TrusteeSale`. Applies to `GET /trustee-sales/{id}`,
        `GET /trustee-sales/{id}/auction-events`, `POST /trustee-sales/{id}/confirm`,
        `POST /trustee-sales/{id}/postpone`, `POST /trustee-sales/{id}/cancel`, and
        `POST /auction-events`."
        PRD: "Binding to the county leg is optional: `trustee_sale_id` may be supplied to
        tie the session to a statutory sale, or omitted entirely, in which case the event is
        a pure real-estate-owned online session with no county linkage — and, as §3.7
        explains, with no postponement carry in its pricing."

        Design: Corner/endpoints/event_to_trustee_sale_link_requires_an_existing_sale
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Link Servicing",
            seller_type="SERVICER",
            contact_email="reo@link.example",
            settlement_account_ref="ACH-LINK-1",
            street_address="1 Link Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        sale = create_trustee_sale(bundle.listing_id, "2026-09-15T18:00:00Z")

        validate_error(
            api_client.create_auction_event(
                create_auction_event_payload(
                    title="Dangling Link Event",
                    county_code=COUNTY_PRIMARY,
                    starts_at=EVENT_START,
                    ends_at=EVENT_END,
                    trustee_sale_id=MISSING_SALE_ID,
                ),
                OPS,
            ),
            "ERR_TRUSTEE_SALE_NOT_FOUND",
            404,
        )

        event = create_event(
            title="Linked Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            trustee_sale_id=sale["id"],
        )
        assert event["trustee_sale_id"] == sale["id"]

        events, events_meta = validate_paginated(
            api_client.list_auction_events(OPS, params={"county_code": COUNTY_PRIMARY})
        )
        assert events_meta["total_count"] == 1
        assert [row["id"] for row in events] == [event["id"]]

        back_reference, back_meta = validate_paginated(
            api_client.list_trustee_sale_auction_events(sale["id"], TRUSTEE)
        )
        assert back_meta["total_count"] == 1
        assert [row["id"] for row in back_reference] == [event["id"]]
        assert read_sale(sale["id"])["status"] == "PENDING"


class TestComputedAssessmentRead:
    def test_an_audit_needs_a_lot_and_then_reconstructs_from_the_event_start(self):
        """An audit has no reference instant without a lot, so it is refused; supplied with
        one it reads identity as of the session's start — verified five days earlier, so no
        identity points — while the deposit penalty still reads the empty ledger of today.

        PRD: "It accepts `mode`, which defaults to `SCREEN` when omitted, and
        `auction_lot_id`, which is optional in `SCREEN` mode and mandatory in `AUDIT` mode —
        requesting an audit without it is `ERR_AUDIT_MODE_REQUIRES_LOT`."
        PRD: "In `AUDIT` mode — the chronological post-auction reconstruction — a lot is
        mandatory, and that lot's auction event's `starts_at` becomes the reference instant.
        The identity penalty applies when `identity_verified_at` is unset, or when it is
        later than the reference instant. The counted exclusions are those whose
        `effective_at` is at or before the reference instant and whose scope is either `ALL`
        or the event's `county_code`, and which were either still `ACTIVE` or were `LIFTED`
        with a `lifted_at` later than the reference instant. Future-dated exclusions are
        therefore excluded and since-lifted exclusions are resurrected — the exact mirror
        image of the screen. The deposit penalty, by deliberate exception, uses the bidder's
        **current** `deposit_available_cents`, because the audit reconstructs eligibility,
        not the ledger."

        Design: Corner/endpoints/audit_assessment_requires_a_lot_and_uses_the_event_start_as_reference
        """
        scenario = scheduled_lot(
            clock="2026-09-10T00:00:00Z",
            org_name="Audit Read Bank",
            seller_type="BANK",
            contact_email="reo@auditread.example",
            settlement_account_ref="ACH-AUDT-1",
            street_address="1 Auditread Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Alameda Audit Read Session",
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        assert read_lot(scenario.lot_id)["required_deposit_cents"] == 1000000

        bidder = funded_bidder(
            0,
            legal_name="Audit Read Bidder LLC",
            email="bid@auditread.example",
            mailing_address="2 Auditread Rd, Oakland CA",
            document_reference="KYC-AUDT-1",
        )
        assert_timestamp_equals(bidder["identity_verified_at"], "2026-09-10T00:00:00Z")

        set_clock("2026-09-16T00:00:00Z")
        validate_error(
            api_client.get_eligibility_assessment(
                bidder["id"], COMPLIANCE, params={"mode": "AUDIT"}
            ),
            "ERR_AUDIT_MODE_REQUIRES_LOT",
            422,
        )

        assessment = eligibility_assessment(
            bidder["id"], mode="AUDIT", auction_lot_id=scenario.lot_id
        )
        assert assessment["mode"] == "AUDIT"
        assert assessment["identity_penalty_applied"] == 0
        assert assessment["counted_exclusion_count"] == 0
        assert assessment["exclusion_penalty_applied"] == 0
        assert assessment["fallout_penalty_applied"] == 0
        assert assessment["deposit_penalty_applied"] == 10
        assert assessment["risk_score"] == 10
        assert assessment["eligible"] is True


class TestContractEndOfLifeChannels:
    def test_the_closing_deadline_gates_escrow_but_never_the_fallout(self):
        """A day past the closing deadline the escrow close is refused and stores no
        reference, while the fallout action — deliberately ungated by the clock — still
        runs and makes any second fallout impossible.

        PRD: "Execution stamps `execution_at` with the logical clock, records the acting
        operator as `executed_by_user_id`, sets `contract_status` to `EXECUTED`, and computes
        `closing_deadline_at` as `execution_at` advanced by `closing_window_days` days."
        PRD: "An `AuctionOps` operator records it with a `closing_reference` from escrow
        while the contract is still `EXECUTED` and the logical clock is at or before
        `closing_deadline_at`; closing late is `ERR_CLOSING_DEADLINE_PASSED`, and closing a
        contract that has already closed or fallen out is `ERR_CONTRACT_NOT_EXECUTED`."

        Design: Corner/endpoints/closing_after_the_deadline_is_refused_but_fallout_is_still_allowed
        """
        scenario = executed_contract(
            clear_title_before_close=True,
            org_name="Deadline Bank",
            seller_type="BANK",
            contact_email="reo@deadline.example",
            settlement_account_ref="ACH-DEAD-1",
            default_commission_bps=500,
            street_address="1 Deadline Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Alameda Deadline Session",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
            bid_amount_cents=20000000,
            funded_cents=1000000,
            bidder_legal_name="Deadline Bidder LLC",
            bidder_email="bid@deadline.example",
            closing_window_days=21,
        )
        contract = scenario.contract
        assert contract["closing_window_days"] == 21
        assert_timestamp_equals(contract["closing_deadline_at"], "2026-10-06T18:10:00Z")

        set_clock("2026-10-07T00:00:00Z")
        validate_error(
            api_client.close_sale_contract(
                MISSING_CONTRACT_ID,
                close_contract_payload(closing_reference="ESCROW-NONE"),
                make_auction_ops_headers(OPS_CONTRACT),
            ),
            "ERR_SALE_CONTRACT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.close_sale_contract(
                contract["id"],
                close_contract_payload(closing_reference="ESCROW-LATE"),
                make_auction_ops_headers(OPS_CONTRACT),
            ),
            "ERR_CLOSING_DEADLINE_PASSED",
            409,
        )
        assert read_contract(contract["id"]).get("closing_reference") is None

        fallen = record_fallout(contract["id"], reason="buyer never funded escrow")
        assert fallen["contract_status"] == "FALLOUT"
        assert fallen["forfeited_deposit_cents"] == 1000000

        validate_error(
            api_client.record_fallout(
                contract["id"],
                fallout_payload(fallout_reason="duplicate fallout entry"),
                make_auction_ops_headers(OPS_CONTRACT),
            ),
            "ERR_CONTRACT_NOT_EXECUTED",
            409,
        )

        final = read_contract(contract["id"])
        assert final["settlement_status"] == "VOID"
        assert_timestamp_equals(final["fallout_at"], "2026-10-07T00:00:00Z")
        assert read_listing(scenario.listing_id)["listing_status"] == "RELIST_PENDING"
        assert read_bidder(scenario.bidder_id)["fallout_count"] == 1


class TestSecondChanceOfferLifecycle:
    def test_one_backup_bidder_walks_the_whole_offer_lifecycle(self):
        """A duplicate offer is refused, the winner cannot answer the backup's offer, a
        late answer expires the offer before refusing it, a replacement offer is then
        allowed, and the decline is terminal.

        PRD: "The offer is created `OUTSTANDING`, and only one may be outstanding per lot
        at a time: a second attempt while one is still live is `ERR_DUPLICATE_ACTIVE_OFFER`."
        PRD: "If the logical clock is past the offer's `expires_at`, the platform first
        moves the offer `OUTSTANDING → EXPIRED` and only then rejects the request with
        `ERR_OFFER_EXPIRED`; `responded_at` is left unset, because the bidder never validly
        answered."
        PRD: "A **decline** is far quieter: `responded_at` is stamped, the asset stays
        `RELIST_PENDING` so the seller may relist it, and `second_chance_eligible` is set to
        false."

        Design: Corner/endpoints/second_chance_offer_lifecycle_expiry_then_decline
        """
        scenario = live_lot(
            org_name="Lifecycle Bank",
            seller_type="BANK",
            contact_email="reo@lifecycle.example",
            settlement_account_ref="ACH-LIFE-1",
            street_address="1 Lifecycle Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Alameda Lifecycle Session",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        backup = funded_bidder(
            1000000,
            legal_name="Lifecycle Backup LLC",
            email="backup@lifecycle.example",
            mailing_address="2 Lifecycle Rd, Oakland CA",
            document_reference="KYC-LIFE-B",
            funding_reference="WIRE-LIFE-B",
        )
        winner = funded_bidder(
            1000000,
            legal_name="Lifecycle Winner LLC",
            email="winner@lifecycle.example",
            mailing_address="3 Lifecycle Rd, Oakland CA",
            document_reference="KYC-LIFE-W",
            funding_reference="WIRE-LIFE-W",
        )
        place_bid(scenario.lot_id, backup["id"], 20000000)
        place_bid(scenario.lot_id, winner["id"], 20500000)

        set_clock(CLOCK_LOT_CLOSE)
        close_lot(scenario.lot_id)

        set_clock(CLOCK_CONTRACT)
        offer = create_offer(scenario.lot_id, expires_at="2026-09-16T00:00:00Z")
        assert offer["offered_bidder_id"] == backup["id"]
        assert offer["offer_price_cents"] == 20000000

        validate_error(
            api_client.create_second_chance_offer(
                scenario.lot_id,
                second_chance_offer_payload(expires_at="2026-09-17T00:00:00Z"),
                make_auction_ops_headers(OPS_CONTRACT),
            ),
            "ERR_DUPLICATE_ACTIVE_OFFER",
            409,
        )
        validate_error(
            api_client.respond_to_offer(
                offer["id"],
                respond_to_offer_payload("ACCEPTED"),
                make_bidder_headers(winner["id"]),
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        validate_error(
            api_client.respond_to_offer(
                MISSING_OFFER_ID,
                respond_to_offer_payload("ACCEPTED"),
                make_bidder_headers(backup["id"]),
            ),
            "ERR_OFFER_NOT_FOUND",
            404,
        )

        set_clock("2026-09-16T00:00:01Z")
        validate_error(
            api_client.respond_to_offer(
                offer["id"],
                respond_to_offer_payload("ACCEPTED"),
                make_bidder_headers(backup["id"]),
            ),
            "ERR_OFFER_EXPIRED",
            409,
        )
        expired = read_offer(offer["id"])
        assert expired["status"] == "EXPIRED"
        assert expired.get("responded_at") is None

        replacement = create_offer(scenario.lot_id)
        assert_timestamp_equals(replacement["expires_at"], "2026-09-19T00:00:01Z")

        declined = respond_to_offer(replacement["id"], backup["id"], "DECLINED")
        assert declined["status"] == "DECLINED"
        assert_timestamp_equals(declined["responded_at"], "2026-09-16T00:00:01Z")
        assert read_listing(scenario.listing_id)["second_chance_eligible"] is False

        validate_error(
            api_client.respond_to_offer(
                replacement["id"],
                respond_to_offer_payload("ACCEPTED"),
                make_bidder_headers(backup["id"]),
            ),
            "ERR_OFFER_NOT_OUTSTANDING",
            409,
        )
        assert read_lot(scenario.lot_id)["hammer_price_cents"] == 20500000


class TestEveryRemainingReadChannel:
    def test_one_completed_auction_reads_back_through_every_remaining_channel(self):
        """One worked auction — noticed, confirmed, bid up, hammered, contracted and
        re-offered — is then read back through each remaining channel, every list honouring
        its own filter and every detail row carrying what the write path left behind.

        PRD: "Beyond pagination, each collection endpoint accepts a small set of exact-match
        filters, and filters combine conjunctively."
        PRD: "`settlement_status` enumerates `DRAFT`, `POSTED` and `VOID`; the settlement is
        posted in the execution request itself, so a freshly executed contract reads
        `POSTED`, and the seller's `settled_net_cents` rises by this contract's
        `seller_net_cents` at that moment."
        PRD: "If the lot's event is bound to a trustee sale that is `CONFIRMED`, that sale
        moves `CONFIRMED → HELD`."
        PRD: "The winner's deposit hold is re-purposed rather than released: it becomes
        `EXTENDED` with its `expires_at` rewritten to the contract's `closing_deadline_at`,
        and — unlike the postponement path of §3.2 — its `extension_count` is **not**
        incremented, because it is the closing window and not the postponement policy that
        sets this expiry."

        Design: Corner/endpoints/every_declared_read_channel_answers_for_one_completed_auction
        """
        set_clock(CLOCK_SETUP)
        bundle = cleared_asset(
            org_name="Readback Bank",
            seller_type="BANK",
            contact_email="reo@readback.example",
            settlement_account_ref="ACH-READ-1",
            street_address="1 Readback Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        intake_only = create_listing(
            bundle.seller,
            street_address="2 Readback Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        sale = create_trustee_sale(bundle.listing_id, "2026-09-15T18:00:00Z")
        event = create_event(
            title="Alameda Readback Session",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            trustee_sale_id=sale["id"],
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

        winner = funded_bidder(
            1000000,
            legal_name="Readback Winner LLC",
            email="winner@readback.example",
            mailing_address="3 Readback Rd, Oakland CA",
            document_reference="KYC-READ-A",
            funding_reference="WIRE-READ-A",
        )
        backup = funded_bidder(
            1000000,
            legal_name="Readback Backup LLC",
            email="backup@readback.example",
            mailing_address="4 Readback Rd, Oakland CA",
            document_reference="KYC-READ-B",
            funding_reference="WIRE-READ-B",
        )
        exclusion = create_exclusion(
            backup["id"],
            "SANCTIONS_LIST",
            "2026-08-01T00:00:00Z",
            county_code="ALL",
            notes="screening hit",
        )
        lifted = lift_exclusion(exclusion["id"], notes="false positive cleared")
        assert lifted["status"] == "LIFTED"
        assert_timestamp_equals(lifted["lifted_at"], CLOCK_SETUP)

        set_clock("2026-09-14T00:00:00Z")
        confirm_sale(sale["id"], confirmation_reference="CONF-READ-1")
        set_clock(CLOCK_EVENT_OPEN)
        open_event(event["id"])

        set_clock("2026-09-15T17:10:00Z")
        backup_bid = place_bid(lot["id"], backup["id"], 20000000)
        set_clock("2026-09-15T17:15:00Z")
        place_bid(lot["id"], winner["id"], 20500000)

        encumbered = list_holds(auction_lot_id=lot["id"], status="HELD")
        assert len(encumbered) == 1
        hold_id = encumbered[0]["id"]

        set_clock(CLOCK_LOT_CLOSE)
        close_lot(lot["id"])
        set_clock(CLOCK_CONTRACT)
        contract = execute_contract(lot["id"])
        set_clock("2026-09-15T18:15:00Z")
        offer = create_offer(lot["id"])

        seller = read_seller(bundle.seller_id)
        assert seller["org_name"] == "Readback Bank"
        assert seller["seller_type"] == "BANK"
        assert seller["default_commission_bps"] == 500
        assert seller["settled_net_cents"] == contract["seller_net_cents"] == 19403250

        intake_rows, intake_meta = validate_paginated(
            api_client.list_seller_asset_listings(
                bundle.seller_id, ADMIN, params={"listing_status": "INTAKE"}
            )
        )
        assert intake_meta["total_count"] == 1
        assert [row["id"] for row in intake_rows] == [intake_only["id"]]

        sale_rows, sale_meta = validate_paginated(
            api_client.list_asset_listing_trustee_sales(
                bundle.listing_id, TRUSTEE, params={"status": "HELD"}
            )
        )
        assert sale_meta["total_count"] == 1
        assert [row["id"] for row in sale_rows] == [sale["id"]]

        noticed = read_sale(sale["id"], TRUSTEE)
        assert noticed["status"] == "HELD"
        assert noticed["confirmation_reference"] == "CONF-READ-1"
        assert noticed["postponement_count"] == 0
        assert noticed["statutory_max_postponements"] == 3

        lot_rows, lot_meta = validate_paginated(
            api_client.list_auction_lots(
                OPS, params={"auction_event_id": event["id"], "lot_status": "CLOSED_SOLD"}
            )
        )
        assert lot_meta["total_count"] == 1
        assert [row["id"] for row in lot_rows] == [lot["id"]]
        assert lot_rows[0]["hammer_price_cents"] == 20500000

        contract_rows, contract_meta = validate_paginated(
            api_client.list_lot_sale_contracts(
                lot["id"],
                make_seller_headers(bundle.seller_id),
                params={"contract_status": "EXECUTED"},
            )
        )
        assert contract_meta["total_count"] == 1
        assert [row["id"] for row in contract_rows] == [contract["id"]]
        assert contract_rows[0]["contract_price_cents"] == 20500000

        outbid_rows, outbid_meta = validate_paginated(
            api_client.list_bids(
                OPS, params={"auction_lot_id": lot["id"], "bid_status": "OUTBID"}
            )
        )
        assert outbid_meta["total_count"] == 1
        assert [row["id"] for row in outbid_rows] == [backup_bid["id"]]
        assert outbid_rows[0]["bidder_id"] == backup["id"]

        exclusion_rows, exclusion_meta = validate_paginated(
            api_client.list_bidder_exclusions(
                backup["id"], COMPLIANCE, params={"status": "LIFTED"}
            )
        )
        assert exclusion_meta["total_count"] == 1
        assert [row["id"] for row in exclusion_rows] == [exclusion["id"]]
        assert exclusion_rows[0]["county_code"] == "ALL"
        assert_timestamp_equals(exclusion_rows[0]["lifted_at"], CLOCK_SETUP)

        hold = read_hold(hold_id, OPS)
        assert hold["status"] == "EXTENDED"
        assert hold["amount_cents"] == 1000000
        assert hold["bidder_id"] == winner["id"]
        assert_timestamp_equals(hold["expires_at"], "2026-10-06T18:10:00Z")

        offer_rows, offer_meta = validate_paginated(
            api_client.list_second_chance_offers(
                OPS, params={"auction_lot_id": lot["id"], "status": "OUTSTANDING"}
            )
        )
        assert offer_meta["total_count"] == 1
        assert [row["id"] for row in offer_rows] == [offer["id"]]

        outstanding = read_offer(offer["id"], OPS)
        assert outstanding["status"] == "OUTSTANDING"
        assert outstanding["offered_bidder_id"] == backup["id"]
        assert outstanding["offer_price_cents"] == 20000000
        assert_timestamp_equals(outstanding["expires_at"], "2026-09-18T18:15:00Z")
        assert read_bidder(backup["id"])["registration_status"] == "REGISTERED"
