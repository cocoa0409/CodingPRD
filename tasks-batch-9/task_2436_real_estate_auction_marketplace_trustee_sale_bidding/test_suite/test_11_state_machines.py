"""Transitions, refusals from the wrong state, terminal lockdowns and the cascades
one transition sets off across the county, marketplace and bidder axes."""

from test_helpers import (
    CLOCK_EVENT_OPEN,
    CLOCK_LOT_CLOSE,
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    OPS_CLOSER,
    TEST_USERS,
    add_lot,
    api_client,
    assert_timestamp_equals,
    cancel_sale,
    cancel_trustee_sale_payload,
    cleared_asset,
    close_contract,
    close_lot,
    close_lot_payload,
    confirm_sale,
    confirm_trustee_sale_payload,
    create_event,
    create_exclusion,
    create_listing,
    create_seller,
    create_trustee_sale,
    disclosed_asset,
    disclosures_payload,
    execute_contract,
    executed_contract,
    file_disclosures,
    funded_bidder,
    lift_exclusion,
    list_exclusions,
    list_holds,
    live_lot,
    make_auction_ops_headers,
    make_seller_headers,
    open_event,
    place_bid,
    postpone_trustee_sale_payload,
    read_bid,
    read_bidder,
    read_contract,
    read_event,
    read_listing,
    read_lot,
    read_sale,
    read_seller,
    record_fallout,
    register_bidder,
    relist_payload,
    reschedule_payload,
    respond_to_offer,
    scheduled_lot,
    set_clock,
    sold_lot,
    title_clearance_payload,
    validate_error,
    verify_bidder,
)
from test_helpers import create_offer as issue_offer

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["auction_ops_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
TITLE_OFFICER = TEST_USERS["title_officer_headers"]

SALE_AT = "2026-09-15T18:00:00Z"
EVENT_WINDOW = ("2026-09-15T17:00:00Z", "2026-09-15T19:00:00Z")


class TestValidTransitions:
    def test_confirming_a_pending_notice_stores_the_docket_reference(self):
        """The county leg leaves `PENDING` for `CONFIRMED`, the trustee's reference is
        written to the row, and neither the noticed date nor the postponement counter moves.

        PRD: "It accepts a `confirmation_reference`, the trustee's docket reference, which
        is stored on the record, and it is permitted from `PENDING` or from `POSTPONED` —
        the latter being the re-confirmation that closes the postponement loop, moving
        `POSTPONED → CONFIRMED`."

        Design: Corner/state_machines/trustee_sale_confirm_moves_pending_to_confirmed
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Confirm Path Servicing",
            seller_type="SERVICER",
            contact_email="c@confirm.example",
            settlement_account_ref="ACH-CONF",
            street_address="3 Confirm Way",
            city="Oakland",
            estimated_value_cents=25000000,
        )
        sale = create_trustee_sale(bundle.listing_id, SALE_AT)
        assert sale["status"] == "PENDING"

        confirmed = confirm_sale(sale["id"], "TS-ALA-CONF-1")

        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmation_reference"] == "TS-ALA-CONF-1"
        assert confirmed["postponement_count"] == 0
        assert_timestamp_equals(confirmed["sale_scheduled_at"], SALE_AT)
        assert read_listing(bundle.listing_id)["listing_status"] == "DISCLOSURE_READY"

    def test_an_accepted_second_chance_offer_reseats_the_backup_bidder(self):
        """Acceptance runs the auction result both ways at once: the backup's outbid bid
        is promoted, the defaulter's is demoted, the hammer drops to the offer price with a
        re-derived premium, a fresh deposit is held, and the asset is under contract again.

        PRD: "`responded_at` is stamped from the logical clock; a fresh deposit hold of
        exactly the lot's `required_deposit_cents` is created for the accepting bidder with
        a `status` of `HELD`, and that bidder's deposit ledger is recomputed; the accepting
        bidder's bid on the lot becomes `WINNING` while the bid that had been `WINNING`
        becomes `OUTBID`; the lot's `hammer_price_cents` is rewritten to the offer's
        `offer_price_cents` and its `provisional_buyer_premium_cents` is recomputed under
        the provisional rule against that new price; and the asset moves
        `RELIST_PENDING → SOLD_PENDING_CONTRACT` with `second_chance_eligible` set to
        false, so that a fresh purchase contract can be executed against the lot exactly as
        if it had just been hammered down."

        Design: Corner/state_machines/accepted_second_chance_offer_reseats_the_backup_bidder
        """
        set_clock(CLOCK_SETUP)
        bundle = cleared_asset(
            org_name="Reseat Bank",
            seller_type="BANK",
            contact_email="r@reseat.example",
            settlement_account_ref="ACH-RSET",
            street_address="1 Reseat Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Reseat Event", starts_at=EVENT_WINDOW[0], ends_at=EVENT_WINDOW[1]
        )
        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T18:00:00Z",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        backup = funded_bidder(
            1000000,
            legal_name="Reseat Backup LLC",
            email="backup@reseat.example",
            mailing_address="2 Reseat Rd, Oakland CA",
            document_reference="KYC-RSET-1",
            funding_reference="WIRE-RSET-1",
        )
        winner = funded_bidder(
            1000000,
            legal_name="Reseat Winner LLC",
            email="winner@reseat.example",
            mailing_address="3 Reseat Rd, Oakland CA",
            document_reference="KYC-RSET-2",
            funding_reference="WIRE-RSET-2",
        )

        set_clock(CLOCK_EVENT_OPEN)
        open_event(event["id"])
        backup_bid = place_bid(lot["id"], backup["id"], 20000000)
        winner_bid = place_bid(lot["id"], winner["id"], 20500000)

        set_clock(CLOCK_LOT_CLOSE)
        hammered = close_lot(lot["id"])
        assert hammered["hammer_price_cents"] == 20500000
        assert hammered["provisional_buyer_premium_cents"] == 1640000

        set_clock("2026-09-15T18:10:00Z")
        contract = execute_contract(lot["id"])
        set_clock("2026-09-20T00:00:00Z")
        record_fallout(contract["id"])
        fallen = read_listing(bundle.listing_id)
        assert fallen["listing_status"] == "RELIST_PENDING"
        assert fallen["second_chance_eligible"] is True

        set_clock("2026-09-20T01:00:00Z")
        offer = issue_offer(lot["id"])
        assert offer["offer_price_cents"] == 20000000
        assert_timestamp_equals(offer["expires_at"], "2026-09-23T01:00:00Z")

        set_clock("2026-09-20T02:00:00Z")
        answered = respond_to_offer(offer["id"], backup["id"], "ACCEPTED")

        assert answered["status"] == "ACCEPTED"
        assert_timestamp_equals(answered["responded_at"], "2026-09-20T02:00:00Z")

        reseated = read_lot(lot["id"])
        assert reseated["hammer_price_cents"] == 20000000
        assert reseated["provisional_buyer_premium_cents"] == 1600000
        assert reseated["lot_status"] == "CLOSED_SOLD"

        assert read_bid(backup_bid["id"])["bid_status"] == "WINNING"
        assert read_bid(winner_bid["id"])["bid_status"] == "OUTBID"

        listing = read_listing(bundle.listing_id)
        assert listing["listing_status"] == "SOLD_PENDING_CONTRACT"
        assert listing["second_chance_eligible"] is False

        backup_after = read_bidder(backup["id"])
        assert backup_after["deposit_available_cents"] == 0
        assert backup_after["deposit_forfeited_cents"] == 0
        fresh_holds = list_holds(bidder_id=backup["id"], status="HELD")
        assert len(fresh_holds) == 1
        assert fresh_holds[0]["amount_cents"] == 1000000
        assert fresh_holds[0]["auction_lot_id"] == lot["id"]

        assert read_bidder(winner["id"])["deposit_forfeited_cents"] == 1000000
        assert read_seller(bundle.seller["id"])["settled_net_cents"] == 600000


class TestSideEffectFanOut:
    def test_opening_a_session_opens_every_pending_lot_on_its_own_window(self):
        """One open call stamps `opened_at` from the clock and fans out to both pending
        lots, each taking its close instant from its own window rather than the event's end.

        PRD: "The event then moves `SCHEDULED → LIVE`, `opened_at` is stamped with the
        logical clock, and every lot of the event whose `lot_status` is `PENDING` or
        `SUSPENDED` moves to `OPEN`."

        Design: Corner/state_machines/open_event_stamps_opened_at_and_opens_every_pending_lot
        """
        set_clock(CLOCK_SETUP)
        first = disclosed_asset(
            org_name="Fanout REO",
            seller_type="BANK",
            contact_email="f@fanout.example",
            settlement_account_ref="ACH-FAN",
            street_address="1 Fanout Rd",
            city="Oakland",
            estimated_value_cents=24000000,
        )
        second = disclosed_asset(
            seller=first.seller,
            street_address="2 Fanout Rd",
            city="Oakland",
            estimated_value_cents=25000000,
        )
        event = create_event(
            title="Fanout Event", starts_at=EVENT_WINDOW[0], ends_at=EVENT_WINDOW[1]
        )
        lot_a = add_lot(
            event["id"],
            first.listing_id,
            lot_number=1,
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T17:30:00Z",
        )
        lot_b = add_lot(
            event["id"],
            second.listing_id,
            lot_number=2,
            lot_window_start_at="2026-09-15T17:30:00Z",
            lot_window_end_at="2026-09-15T19:00:00Z",
            opening_bid_cents=21000000,
            reserve_price_cents=21000000,
        )

        set_clock(CLOCK_EVENT_OPEN)
        opened = open_event(event["id"])

        assert opened["event_status"] == "LIVE"
        assert_timestamp_equals(opened["opened_at"], CLOCK_EVENT_OPEN)

        refreshed_a = read_lot(lot_a["id"])
        assert refreshed_a["lot_status"] == "OPEN"
        assert_timestamp_equals(refreshed_a["bid_close_at"], "2026-09-15T17:30:00Z")
        assert refreshed_a["extension_count"] == 0

        refreshed_b = read_lot(lot_b["id"])
        assert refreshed_b["lot_status"] == "OPEN"
        assert_timestamp_equals(refreshed_b["bid_close_at"], "2026-09-15T19:00:00Z")
        assert refreshed_b["extension_count"] == 0

        assert read_event(event["id"])["lot_count"] == 2


class TestRefusalsFromTheWrongState:
    def test_a_second_disclosure_filing_is_refused_and_overwrites_nothing(self):
        """Disclosures are a one-shot transition out of `INTAKE`, so the endpoint is not
        an upsert: the rejected filing leaves both disclosure axes and the ack stamp intact.

        PRD: "Disclosures may be filed exactly once from `INTAKE`; a second attempt, or an
        attempt on an asset that has already moved on, is refused with
        `ERR_LISTING_NOT_IN_INTAKE`."

        Design: Corner/state_machines/disclosures_on_already_disclosed_listing_rejected
        """
        set_clock(CLOCK_SETUP)
        seller = create_seller(
            org_name="Single Filing Bank",
            seller_type="BANK",
            contact_email="s@single.example",
            settlement_account_ref="ACH-SING",
        )
        listing = create_listing(
            seller, street_address="6 Single St", city="Oakland",
            estimated_value_cents=24000000,
        )
        first = file_disclosures(seller, listing, "VACANT", "CLEAR")

        validate_error(
            api_client.file_disclosures(
                listing["id"],
                disclosures_payload("OWNER_OCCUPIED", "CLOUDED"),
                make_seller_headers(seller["id"]),
            ),
            "ERR_LISTING_NOT_IN_INTAKE",
            409,
        )

        refreshed = read_listing(listing["id"])
        assert refreshed["occupancy_status"] == "VACANT"
        assert refreshed["title_condition"] == "CLEAR"
        assert refreshed["eviction_risk_tier"] == "LOW"
        assert refreshed["listing_status"] == "DISCLOSURE_READY"
        assert_timestamp_equals(refreshed["disclosure_ack_at"], first["disclosure_ack_at"])

    def test_a_listed_asset_cannot_be_relisted_out_from_under_its_roster(self):
        """Relist is reachable only from the two unsold states, so an asset sitting on an
        auction roster keeps its status, its counter and its pending title axis.

        PRD: "A relist attempted from any other `listing_status` is
        `ERR_LISTING_NOT_RELISTABLE`, one attempted by a seller that does not own the asset
        is `ERR_NOT_RESOURCE_OWNER`, and one attempted while the title axis reads
        `DEFECTIVE` is `ERR_TITLE_DEFECTIVE`."

        Design: Corner/state_machines/relist_on_listed_asset_rejected
        """
        scenario = scheduled_lot(
            org_name="Relist Guard Bank",
            seller_type="BANK",
            contact_email="r@relist.example",
            settlement_account_ref="ACH-REL",
            street_address="8 Relist Rd",
            city="Oakland",
            estimated_value_cents=23000000,
            event_title="Relist Guard Event",
            starts_at=EVENT_WINDOW[0],
            ends_at=EVENT_WINDOW[1],
        )
        assert read_listing(scenario.listing_id)["listing_status"] == "LISTED"

        validate_error(
            api_client.relist_asset_listing(
                scenario.listing_id,
                relist_payload(),
                make_seller_headers(scenario.seller_id),
            ),
            "ERR_LISTING_NOT_RELISTABLE",
            409,
        )

        listing = read_listing(scenario.listing_id)
        assert listing["listing_status"] == "LISTED"
        assert listing["relist_count"] == 0
        assert listing["title_clearance_status"] == "PENDING"
        assert read_lot(scenario.lot_id)["lot_status"] == "PENDING"

    def test_reschedule_is_not_a_generic_window_editor(self):
        """A session that was never postponed cannot be moved, and the refusal leaves the
        original window and the loop counter exactly where they were.

        PRD: "The operator supplies `new_starts_at` and `new_ends_at`; the event must be
        `POSTPONED`, or `ERR_EVENT_NOT_POSTPONED`, and the new start must be strictly after
        the logical clock with the new end strictly after the new start, or the request is
        `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/reschedule_on_scheduled_event_rejected
        """
        set_clock(CLOCK_SETUP)
        event = create_event(
            title="Never Postponed Event",
            starts_at=EVENT_WINDOW[0],
            ends_at=EVENT_WINDOW[1],
        )

        validate_error(
            api_client.reschedule_auction_event(
                event["id"],
                reschedule_payload("2026-09-22T17:00:00Z", "2026-09-22T19:00:00Z"),
                OPS,
            ),
            "ERR_EVENT_NOT_POSTPONED",
            409,
        )

        refreshed = read_event(event["id"])
        assert refreshed["event_status"] == "SCHEDULED"
        assert refreshed["reschedule_count"] == 0
        assert_timestamp_equals(refreshed["starts_at"], EVENT_WINDOW[0])
        assert_timestamp_equals(refreshed["ends_at"], EVENT_WINDOW[1])

    def test_the_title_axis_leaves_pending_exactly_once(self):
        """A recorded clouded finding cannot be quietly upgraded to clear by a second
        filing, so bidders keep pricing the risk the first search disclosed.

        PRD: "The title axis may be written only once per search cycle — the second attempt
        on a row that has left `PENDING` is `ERR_TITLE_CLEARANCE_ALREADY_SET`."

        Design: Corner/state_machines/second_title_clearance_filing_rejected
        """
        set_clock(CLOCK_SETUP)
        bundle = cleared_asset(
            occupancy_status="VACANT",
            title_condition="UNKNOWN",
            clearance_outcome="CLOUDED_DISCLOSED",
            verified_title_condition="CLOUDED",
            org_name="Title Once Bank",
            seller_type="BANK",
            contact_email="t@once.example",
            settlement_account_ref="ACH-ONCE",
            street_address="7 Title Rd",
            city="Oakland",
            estimated_value_cents=27000000,
        )
        assert bundle.listing["title_clearance_status"] == "CLOUDED_DISCLOSED"

        validate_error(
            api_client.record_title_clearance(
                bundle.listing_id,
                title_clearance_payload("CLEARED", "CLEAR", title_report_reference="TR-ONCE-2"),
                TITLE_OFFICER,
            ),
            "ERR_TITLE_CLEARANCE_ALREADY_SET",
            409,
        )

        listing = read_listing(bundle.listing_id)
        assert listing["title_clearance_status"] == "CLOUDED_DISCLOSED"
        assert listing["title_condition"] == "CLOUDED"
        assert listing["listing_status"] == "DISCLOSURE_READY"

    def test_re_closing_a_closed_lot_names_the_lot_not_the_event(self):
        """A sibling lot deliberately keeps the session live, so the second close of an
        already-terminal lot is refused for the lot's own state.

        PRD: "The lot must be `OPEN` or `EXTENDED` under a `LIVE` event, and the logical
        clock must have reached or passed the lot's `bid_close_at` — closing early,
        including closing before an extension that a late bid has just pushed out, is
        `ERR_LOT_WINDOW_STILL_OPEN`."

        Design: Corner/state_machines/second_close_of_the_same_lot_rejected
        """
        set_clock(CLOCK_SETUP)
        first = disclosed_asset(
            org_name="Double Close Bank",
            seller_type="BANK",
            contact_email="d@double.example",
            settlement_account_ref="ACH-DBL",
            street_address="1 Double Rd",
            city="Oakland",
            estimated_value_cents=24000000,
        )
        second = disclosed_asset(
            seller=first.seller,
            street_address="2 Double Rd",
            city="Oakland",
            estimated_value_cents=24500000,
        )
        event = create_event(
            title="Double Close Event", starts_at=EVENT_WINDOW[0], ends_at=EVENT_WINDOW[1]
        )
        lot_a = add_lot(
            event["id"],
            first.listing_id,
            lot_number=1,
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T17:30:00Z",
        )
        lot_b = add_lot(
            event["id"],
            second.listing_id,
            lot_number=2,
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T19:00:00Z",
        )

        set_clock(CLOCK_EVENT_OPEN)
        open_event(event["id"])
        set_clock("2026-09-15T17:35:00Z")
        closed = close_lot(lot_a["id"])
        assert closed["lot_status"] == "CLOSED_NO_SALE"
        assert_timestamp_equals(closed["closed_at"], "2026-09-15T17:35:00Z")

        response = api_client.close_lot(
            lot_a["id"], close_lot_payload(), make_auction_ops_headers(OPS_CLOSER)
        )
        error = validate_error(response, "ERR_LOT_NOT_OPEN", 409)
        assert error["error_id"] != "ERR_EVENT_NOT_LIVE"

        unchanged = read_lot(lot_a["id"])
        assert unchanged["lot_status"] == "CLOSED_NO_SALE"
        assert_timestamp_equals(unchanged["closed_at"], "2026-09-15T17:35:00Z")
        assert read_event(event["id"])["event_status"] == "LIVE"
        assert read_lot(lot_b["id"])["lot_status"] == "OPEN"
        assert read_listing(first.listing_id)["listing_status"] == "UNSOLD"


class TestInitialAndTerminalStates:
    def test_every_fresh_row_lands_in_its_own_declared_initial_state(self):
        """Five machines are seeded in one chain, and creating a child never advances the
        parent: the sale stays `PENDING` and the event stays `SCHEDULED`.

        PRD: "A created lot begins `PENDING` with `extension_count`,
        `current_high_bid_cents`, `hammer_price_cents` and `provisional_buyer_premium_cents`
        all at 0, and with `bid_close_at` — the effective close instant that late bidding
        can push forward — initialised to `lot_window_end_at`."

        Design: Corner/state_machines/fresh_entities_start_in_their_declared_initial_states
        """
        set_clock(CLOCK_SETUP)
        seller = create_seller(
            org_name="Initial States Inc",
            seller_type="GSE",
            contact_email="i@initial.example",
            settlement_account_ref="ACH-INIT",
        )
        listing = create_listing(
            seller, street_address="1 Initial Way", city="Oakland",
            estimated_value_cents=22000000,
        )
        assert listing["listing_status"] == "INTAKE"

        file_disclosures(seller, listing, "VACANT", "CLEAR")
        sale = create_trustee_sale(listing["id"], SALE_AT)
        assert sale["status"] == "PENDING"

        event = create_event(
            title="Initial States Event",
            starts_at=EVENT_WINDOW[0],
            ends_at=EVENT_WINDOW[1],
            trustee_sale_id=sale["id"],
        )
        assert event["event_status"] == "SCHEDULED"

        lot = add_lot(
            event["id"],
            listing["id"],
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T18:00:00Z",
        )
        assert lot["lot_status"] == "PENDING"
        assert lot["extension_count"] == 0
        assert lot["current_high_bid_cents"] == 0
        assert lot["hammer_price_cents"] == 0
        assert lot["provisional_buyer_premium_cents"] == 0
        assert_timestamp_equals(lot["bid_close_at"], "2026-09-15T18:00:00Z")

        bidder = register_bidder(
            legal_name="Initial State Bidder LLC",
            email="b@initial.example",
            mailing_address="2 Initial Way, Oakland CA",
        )
        assert bidder["registration_status"] == "PENDING_REVIEW"

        assert read_listing(listing["id"])["title_clearance_status"] == "PENDING"
        assert read_event(event["id"])["event_status"] == "SCHEDULED"
        assert read_sale(sale["id"])["status"] == "PENDING"

    def test_a_cancelled_notice_admits_no_further_county_action(self):
        """`CANCELLED` is terminal on the county axis: confirm, postpone and cancel all
        bounce off it, and the record keeps the reference and reason it had.

        PRD: "`ERR_TRUSTEE_SALE_NOT_ACTIONABLE` (409) — the sale's `status` admits the
        requested transition: `PENDING` or `POSTPONED` for a confirmation, `PENDING` or
        `CONFIRMED` for a postponement, and `PENDING`, `CONFIRMED` or `POSTPONED` for a
        cancellation. Applies to `POST /trustee-sales/{id}/confirm`,
        `POST /trustee-sales/{id}/postpone`, and `POST /trustee-sales/{id}/cancel`."

        Design: Corner/state_machines/cancelled_trustee_sale_cannot_be_confirmed_again
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            org_name="Terminal Lock Servicing",
            seller_type="SERVICER",
            contact_email="t@terminal.example",
            settlement_account_ref="ACH-TERM",
            street_address="4 Terminal Ct",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        sale = create_trustee_sale(bundle.listing_id, SALE_AT)
        confirm_sale(sale["id"], "TS-TERM-1")
        cancelled = cancel_sale(sale["id"], "borrower reinstated the loan")
        assert cancelled["status"] == "CANCELLED"

        validate_error(
            api_client.confirm_trustee_sale(
                sale["id"],
                confirm_trustee_sale_payload(confirmation_reference="TS-TERM-2"),
                TRUSTEE,
            ),
            "ERR_TRUSTEE_SALE_NOT_ACTIONABLE",
            409,
        )
        validate_error(
            api_client.postpone_trustee_sale(
                sale["id"],
                postpone_trustee_sale_payload(
                    "2026-09-22T18:00:00Z", postponement_reason="attempt after cancellation"
                ),
                TRUSTEE,
            ),
            "ERR_TRUSTEE_SALE_NOT_ACTIONABLE",
            409,
        )
        validate_error(
            api_client.cancel_trustee_sale(
                sale["id"],
                cancel_trustee_sale_payload(cancellation_reason="second cancellation attempt"),
                TRUSTEE,
            ),
            "ERR_TRUSTEE_SALE_NOT_ACTIONABLE",
            409,
        )

        refreshed = read_sale(sale["id"])
        assert refreshed["status"] == "CANCELLED"
        assert refreshed["postponement_count"] == 0
        assert refreshed["confirmation_reference"] == "TS-TERM-1"
        assert refreshed["cancellation_reason"] == "borrower reinstated the loan"


class TestCascadesAcrossAxes:
    def test_a_county_cancellation_unwinds_the_whole_live_roster(self):
        """One trustee call cancels the session, withdraws the lot and its bid, releases
        the deposit for the cancellation and lands the asset in `UNSOLD` — not
        `RELIST_PENDING`, which belongs to fallout alone.

        PRD: "The cascade is the one spelled out in §2.11: bound events in `SCHEDULED`,
        `LIVE` or `POSTPONED` become `CANCELLED`; their non-terminal lots become
        `WITHDRAWN`; the `ACTIVE` and `OUTBID` bids on those lots become `WITHDRAWN`; the
        `HELD` and `EXTENDED` holds on those lots become `RELEASED` with a
        `released_reason` of `EVENT_CANCELLED`; every affected bidder's ledger is
        recomputed; and every asset that was `LISTED` on one of those lots becomes
        `UNSOLD`, ready to be relisted."

        Design: Corner/state_machines/trustee_cancel_cascades_to_event_lots_bids_holds_and_listing
        """
        scenario = live_lot(
            org_name="Cascade Cancel Servicing",
            seller_type="SERVICER",
            contact_email="c@cancel.example",
            settlement_account_ref="ACH-CANC",
            street_address="5 Cancel Ct",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Cancel Cascade Event",
            starts_at=EVENT_WINDOW[0],
            ends_at=EVENT_WINDOW[1],
            trustee_sale_at=SALE_AT,
        )
        bidder = funded_bidder(
            2000000, legal_name="Cancel Cascade Bidder LLC", email="b@cancel.example"
        )
        bid = place_bid(scenario.lot_id, bidder["id"], 20000000)

        set_clock("2026-09-15T17:20:00Z")
        cancelled = cancel_sale(
            scenario.sale_id, "county cancelled the sale after reinstatement"
        )

        assert cancelled["status"] == "CANCELLED"
        assert read_event(scenario.event_id)["event_status"] == "CANCELLED"

        lot = read_lot(scenario.lot_id)
        assert lot["lot_status"] == "WITHDRAWN"
        assert lot["hammer_price_cents"] == 0
        assert read_bid(bid["id"])["bid_status"] == "WITHDRAWN"

        holds = list_holds(bidder_id=bidder["id"])
        assert len(holds) == 1
        assert holds[0]["status"] == "RELEASED"
        assert holds[0]["released_reason"] == "EVENT_CANCELLED"

        refreshed = read_bidder(bidder["id"])
        assert refreshed["deposit_available_cents"] == 2000000
        assert refreshed["deposit_forfeited_cents"] == 0

        listing = read_listing(scenario.listing_id)
        assert listing["listing_status"] == "UNSOLD"
        assert listing["relist_count"] == 0
        assert listing["listing_status"] != "RELIST_PENDING"

    def test_closing_the_last_lot_bubbles_the_event_closed_and_the_sale_held(self):
        """No client ever closes a session or spends a notice: hammering the last lot down
        closes the event and moves the confirmed county sale to its terminal `HELD`.

        PRD: "The county axis has one transition no client can request. When a lot bound to
        a `CONFIRMED` sale is hammered down sold, that sale moves `CONFIRMED → HELD` as a
        system bubble-up: the statutory sale is deemed to have been conducted, and the
        notice is spent."

        Design: Corner/state_machines/closing_last_lot_bubbles_event_closed_and_sale_held
        """
        scenario = sold_lot(
            org_name="Bubble Up Servicing",
            seller_type="SERVICER",
            contact_email="b@bubble.example",
            settlement_account_ref="ACH-BUB",
            street_address="9 Bubble Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Bubble Up Event",
            starts_at=EVENT_WINDOW[0],
            ends_at=EVENT_WINDOW[1],
            trustee_sale_at=SALE_AT,
            bid_amount_cents=20000000,
            funded_cents=2000000,
            bidder_legal_name="Bubble Up Bidder LLC",
            bidder_email="bid@bubble.example",
        )
        lot = scenario.lot

        assert lot["lot_status"] == "CLOSED_SOLD"
        assert lot["hammer_price_cents"] == 20000000
        assert lot["provisional_buyer_premium_cents"] == 1600000
        assert lot["closed_by_user_id"] == OPS_CLOSER

        assert read_event(scenario.event_id)["event_status"] == "CLOSED"
        assert read_sale(scenario.sale_id)["status"] == "HELD"
        assert read_listing(scenario.listing_id)["listing_status"] == "SOLD_PENDING_CONTRACT"

        bid = read_bid(scenario.bids[0]["id"])
        assert bid["bid_status"] == "WINNING"
        assert bid["is_above_reserve"] is True
        assert read_bidder(scenario.bidder_id)["deposit_available_cents"] == 1000000

    def test_escrow_closing_returns_the_deposit_and_seals_the_asset(self):
        """The only path into the terminal `SOLD_CLOSED` releases the buyer's hold for the
        closing and credits the seller nothing further — the ledger was posted at execution.

        PRD: "The buyer's deposit hold on the lot is `RELEASED` with a `released_reason` of
        `CONTRACT_CLOSED` and that bidder's deposit ledger is recomputed — the buyer's
        deposit comes back because the purchase money arrived through escrow instead."

        Design: Corner/state_machines/contract_close_releases_hold_and_seals_the_listing
        """
        scenario = executed_contract(
            clear_title_before_close=True,
            org_name="Escrow Close Bank",
            seller_type="BANK",
            contact_email="e@escrow.example",
            settlement_account_ref="ACH-ESC",
            default_commission_bps=500,
            street_address="11 Escrow Way",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Escrow Close Event",
            starts_at=EVENT_WINDOW[0],
            ends_at=EVENT_WINDOW[1],
            bid_amount_cents=20000000,
            funded_cents=2000000,
            bidder_legal_name="Escrow Close Bidder LLC",
            bidder_email="bid@escrow.example",
            closing_window_days=21,
        )
        assert scenario.contract["seller_net_cents"] == 18930000
        assert_timestamp_equals(
            scenario.contract["closing_deadline_at"], "2026-10-06T18:10:00Z"
        )

        set_clock("2026-09-25T00:00:00Z")
        closed = close_contract(scenario.contract_id, "ESCROW-77120")

        assert closed["contract_status"] == "CLOSED"
        assert_timestamp_equals(closed["closed_at"], "2026-09-25T00:00:00Z")
        assert closed["closing_reference"] == "ESCROW-77120"
        assert read_contract(scenario.contract_id)["settlement_status"] == "POSTED"
        assert read_listing(scenario.listing_id)["listing_status"] == "SOLD_CLOSED"

        holds = list_holds(auction_lot_id=scenario.lot_id)
        assert len(holds) == 1
        assert holds[0]["status"] == "RELEASED"
        assert holds[0]["released_reason"] == "CONTRACT_CLOSED"

        buyer = read_bidder(scenario.bidder_id)
        assert buyer["deposit_available_cents"] == 2000000
        assert buyer["deposit_forfeited_cents"] == 0
        assert read_seller(scenario.seller_id)["settled_net_cents"] == 18930000

    def test_a_platform_wide_exclusion_suspends_the_bidder_and_the_lift_restores_it(self):
        """The scope keyword drives the bidder's own machine: an `ALL`-scoped exclusion
        already in force suspends and re-scores, and lifting it walks both back.

        PRD: "Recording an exclusion suspends the bidder only when the exclusion is both
        platform-wide and already in force: if its `county_code` is `ALL` and its
        `effective_at` is at or before the logical clock, a bidder whose
        `registration_status` is `REGISTERED` moves `REGISTERED → SUSPENDED`."

        Design: Corner/state_machines/all_county_exclusion_suspends_bidder_and_lift_restores
        """
        set_clock("2026-09-10T00:00:00Z")
        bidder = register_bidder(
            legal_name="Scope Test Bidder LLC",
            email="s@scope.example",
            mailing_address="3 Scope Rd, Oakland CA",
        )
        verified = verify_bidder(bidder["id"], "VERIFIED", "KYC-SCOPE-1")
        assert verified["registration_status"] == "REGISTERED"
        assert verified["screen_risk_score"] == 0

        exclusion = create_exclusion(
            bidder["id"],
            "SANCTIONS_LIST",
            "2026-09-10T00:00:00Z",
            notes="national list match",
        )
        assert exclusion["county_code"] == "ALL"

        suspended = read_bidder(bidder["id"])
        assert suspended["registration_status"] == "SUSPENDED"
        assert suspended["screen_risk_score"] == 20

        lifted = lift_exclusion(
            exclusion["id"], notes="false positive cleared by manual review"
        )
        assert lifted["status"] == "LIFTED"
        assert_timestamp_equals(lifted["lifted_at"], "2026-09-10T00:00:00Z")

        restored = read_bidder(bidder["id"])
        assert restored["registration_status"] == "REGISTERED"
        assert restored["screen_risk_score"] == 0

        recorded = list_exclusions(bidder["id"])
        assert len(recorded) == 1
        assert recorded[0]["status"] == "LIFTED"

    def test_the_no_sale_lot_gives_the_deposit_back_while_the_sold_lot_keeps_it(self):
        """One bidder, one funded pool, two lots closed seconds apart: the reserve-missing
        lot returns its hold and the reserve-clearing lot keeps the identical one.

        PRD: "No deposit holds are released by a sold close: the losing bidders' holds were
        already released the moment they were outbid, so the winner's hold is the only one
        still encumbered, and it is exactly the one the platform needs to keep."

        Design: Corner/state_machines/no_sale_close_releases_holds_but_sold_close_retains_them
        """
        set_clock(CLOCK_SETUP)
        first = disclosed_asset(
            org_name="Conditional Cascade Bank",
            seller_type="BANK",
            contact_email="c@cond.example",
            settlement_account_ref="ACH-COND",
            street_address="1 Cond Rd",
            city="Oakland",
            estimated_value_cents=30000000,
        )
        second = disclosed_asset(
            seller=first.seller,
            street_address="2 Cond Rd",
            city="Oakland",
            estimated_value_cents=26000000,
        )
        event = create_event(
            title="Conditional Cascade Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_WINDOW[0],
            ends_at=EVENT_WINDOW[1],
        )
        lot_a = add_lot(
            event["id"],
            first.listing_id,
            lot_number=1,
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T18:00:00Z",
            opening_bid_cents=20000000,
            reserve_price_cents=25000000,
        )
        lot_b = add_lot(
            event["id"],
            second.listing_id,
            lot_number=2,
            lot_window_start_at="2026-09-15T17:00:00Z",
            lot_window_end_at="2026-09-15T18:00:00Z",
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        bidder = funded_bidder(
            3000000, legal_name="Conditional Bidder LLC", email="b@cond.example"
        )

        set_clock(CLOCK_EVENT_OPEN)
        open_event(event["id"])
        bid_a = place_bid(lot_a["id"], bidder["id"], 20000000)
        bid_b = place_bid(lot_b["id"], bidder["id"], 20000000)
        assert bid_a["is_above_reserve"] is False
        assert bid_b["is_above_reserve"] is True

        set_clock(CLOCK_LOT_CLOSE)
        closed_a = close_lot(lot_a["id"])
        closed_b = close_lot(lot_b["id"])

        assert closed_a["lot_status"] == "CLOSED_NO_SALE"
        assert read_lot(lot_a["id"])["hammer_price_cents"] == 0
        assert closed_b["lot_status"] == "CLOSED_SOLD"
        assert closed_b["hammer_price_cents"] == 20000000

        holds_a = list_holds(auction_lot_id=lot_a["id"])
        assert len(holds_a) == 1
        assert holds_a[0]["status"] == "RELEASED"
        assert holds_a[0]["released_reason"] == "NO_SALE"

        holds_b = list_holds(auction_lot_id=lot_b["id"])
        assert len(holds_b) == 1
        assert holds_b[0]["status"] in {"HELD", "EXTENDED"}
        assert holds_b[0]["released_reason"] is None

        assert read_bidder(bidder["id"])["deposit_available_cents"] == 2000000
        assert read_listing(first.listing_id)["listing_status"] == "UNSOLD"
        assert read_listing(second.listing_id)["listing_status"] == "SOLD_PENDING_CONTRACT"
        assert read_event(event["id"])["event_status"] == "CLOSED"

        # Each lot ranks its own bids: only the reserve-clearing lot produced a winner.
        assert read_bid(bid_a["id"])["bid_status"] == "ACTIVE"
        assert read_bid(bid_b["id"])["bid_status"] == "WINNING"
