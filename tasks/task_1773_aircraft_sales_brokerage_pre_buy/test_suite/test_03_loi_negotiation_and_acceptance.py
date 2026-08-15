"""LOI counter loop, optimistic concurrency, disclosure axis, and acceptance
cascades."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    acknowledge_disclosure,
    assert_money,
    book_inspection,
    complete_delivery_conditions,
    counter_loi,
    counter_loi_payload,
    create_draft_listing,
    create_facility,
    create_loi_payload,
    fund_escrow,
    get_escrow_for_transaction,
    get_success_data,
    get_transaction_for_listing,
    run_valuation,
    setup_accepted_deal,
    setup_active_listing,
    setup_canonical_comps,
    setup_qualified_buyer,
    submit_loi,
    terminate_deal,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_principal_headers"]
LISTING_AGENT = TEST_USERS["listing_agent_headers"]
BUYER_AGENT = TEST_USERS["buyer_agent_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]


class TestCounterLoop:
    def test_counter_moves_submitted_to_countered(self, api):
        """PRD §3.4: "A counter on a `SUBMITTED` LOI moves it to `COUNTERED`,
        and a counter on a `COUNTERED` LOI moves it back to `SUBMITTED`; in both
        directions the `current_price_usd` is replaced by the supplied
        `new_price_usd` and the LOI's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/loi_negotiation_cycle_submitted_countered
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi = submit_loi(listing["id"], buyer["id"], offer=2000000.00,
                         deposit=100000.00)
        v0 = loi["version"]
        resp = api.counter_loi(loi["id"], counter_loi_payload(1900000.00, v0),
                               LISTING_AGENT)
        countered = validate_success(resp)
        assert countered["status"] == "COUNTERED"
        assert_money(countered["current_price_usd"], 1900000.00, "current_price_usd")
        assert countered["version"] == v0 + 1, "Each counter increments version"

    def test_counter_moves_countered_back_to_submitted(self, api):
        """PRD §3.4: "A counter on a `SUBMITTED` LOI moves it to `COUNTERED`,
        and a counter on a `COUNTERED` LOI moves it back to `SUBMITTED`; in both
        directions the `current_price_usd` is replaced by the supplied
        `new_price_usd` and the LOI's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/loi_negotiation_cycle_submitted_countered
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi = submit_loi(listing["id"], buyer["id"], offer=2000000.00,
                         deposit=100000.00)
        v0 = loi["version"]
        first = counter_loi(loi["id"], 1900000.00, v0, as_role=LISTING_AGENT)
        assert first["version"] == v0 + 1
        resp = api.counter_loi(loi["id"], counter_loi_payload(1950000.00, v0 + 1),
                               BUYER_AGENT)
        second = validate_success(resp)
        assert second["status"] == "SUBMITTED", "Counter loop returns to SUBMITTED"
        assert_money(second["current_price_usd"], 1950000.00, "current_price_usd")
        assert second["version"] == v0 + 2


class TestCounterOptimisticConcurrency:
    def test_occ_counter_with_stale_version_rejected(self, api):
        """PRD §2.6: "Countering an LOI requires the request to carry
        `expected_loi_version`, a non-optional field holding the LOI's `version`
        as the client last observed it. If the LOI's current `version` on the
        server has advanced beyond the supplied value — because another counter
        has already landed since the client last read the LOI — the counter is
        rejected with `ERR_STALE_VERSION` (HTTP 412), so a client holding a
        stale view can never silently overwrite the newest negotiated price."

        Design: Corner/cross_cutting_layers/occ_counter_with_stale_version_rejected
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi = submit_loi(listing["id"], buyer["id"], offer=2000000.00,
                         deposit=100000.00)
        v0 = loi["version"]
        counter_loi(loi["id"], 1900000.00, v0, as_role=LISTING_AGENT)
        # The second counter carries the version observed before the first
        # counter landed.
        resp = api.counter_loi(loi["id"], counter_loi_payload(1850000.00, v0),
                               BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fetched = validate_success(api.get_loi(loi["id"], LISTING_AGENT))
        assert_money(fetched["current_price_usd"], 1900000.00,
                     "The first counter's price is retained")
        assert fetched["status"] == "COUNTERED"
        assert fetched["version"] == v0 + 1


class TestWithdrawAndTerminalStates:
    def test_withdraw_accepted_loi_returns_invalid_state(self, api):
        """PRD §3.4: "A `BuyerAgent` may instead withdraw a pending LOI — from
        either `SUBMITTED` or `COUNTERED` — moving it to `WITHDRAWN`.
        `ACCEPTED`, `REJECTED`, and `WITHDRAWN` are the terminal negotiation
        states"
        PRD §2.8: "5. **State preconditions**, evaluated in three sub-steps: (a)
        the target resource is in a state that permits the requested transition,
        failing with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/withdraw_accepted_loi_returns_invalid_state
        """
        deal = setup_accepted_deal()
        resp = api.withdraw_loi(deal["loi"]["id"], BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_loi(deal["loi"]["id"], BUYER_AGENT))
        assert fetched["status"] == "ACCEPTED", "Terminal LOI is untouched"


class TestDualAgencyDisclosure:
    def test_duplicate_disclosure_ack_returns_already_acknowledged(self, api):
        """PRD §3.5: "Acknowledging a party that has already acknowledged — or
        attempting an acknowledgment on an LOI whose `dual_agency` is false,
        where disclosure is not required at all — is rejected with
        `ERR_ALREADY_ACKNOWLEDGED` (HTTP 409)."
        PRD §3.5: "it begins at `PENDING` for a dual-agency LOI, moves to
        `PARTIAL` when the first party acknowledges, and reaches `FULLY_ACKED`
        when the remaining party acknowledges."

        Design: Corner/errors/duplicate_disclosure_ack_returns_already_acknowledged
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi = submit_loi(listing["id"], buyer["id"], dual_agency=True)
        first = acknowledge_disclosure(loi["id"], "BUYER")
        assert first["disclosure_status"] == "PARTIAL"
        resp = api.ack_disclosure(loi["id"], {"party": "BUYER"}, BROKER)
        validate_error(resp, ApiErrorId.ERR_ALREADY_ACKNOWLEDGED)
        fetched = validate_success(api.get_loi(loi["id"], BROKER))
        assert fetched["disclosure_status"] == "PARTIAL"
        assert fetched["buyer_acked"] is True
        assert fetched["seller_acked"] is False

    def test_accept_dual_agency_loi_pending_disclosure_returns_error(self, api):
        """PRD §3.6: "when the LOI's `dual_agency` is true, its
        `disclosure_status` must be `FULLY_ACKED`, otherwise the acceptance is
        rejected with `ERR_DUAL_AGENCY_DISCLOSURE_PENDING`."
        PRD §3.5: "accepting a dual-agency LOI whose disclosure has not reached
        `FULLY_ACKED` is rejected with `ERR_DUAL_AGENCY_DISCLOSURE_PENDING`
        (HTTP 409)"

        Design: Corner/validations/accept_dual_agency_loi_pending_disclosure_returns_error
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi = submit_loi(listing["id"], buyer["id"], dual_agency=True)
        assert loi["disclosure_status"] == "PENDING"
        resp = api.accept_loi(loi["id"], LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_DUAL_AGENCY_DISCLOSURE_PENDING)
        fetched = validate_success(api.get_listing(listing["id"], LISTING_AGENT))
        assert fetched["status"] == "ACTIVE", "Rejected acceptance does not lock the listing"


class TestAcceptanceRbac:
    def test_buyer_agent_cannot_accept_loi(self, api):
        """PRD §2.1: "Each endpoint declares the roles authorized to invoke it,
        and a caller whose role is not in that list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST `/api/lois/{id}/accept` | Accept an LOI; opens Transaction
        + EscrowDeposit and locks the listing | ListingAgent"

        Design: Corner/rbac/buyer_agent_cannot_accept_loi
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi = submit_loi(listing["id"], buyer["id"])
        resp = api.accept_loi(loi["id"], BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        fetched = validate_success(api.get_loi(loi["id"], LISTING_AGENT))
        assert fetched["status"] == "SUBMITTED"


class TestAcceptanceCascade:
    def test_accept_locks_listing_and_rejects_sibling_loi(self, api):
        """PRD §3.6: "Acceptance simultaneously locks the aircraft: the listing
        cascades from `ACTIVE` to `UNDER_CONTRACT`, and the same cascade runs
        the auto-reject sweep — every other LOI on that listing still sitting in
        `SUBMITTED` or `COUNTERED` is moved to `REJECTED`, ending those
        negotiations deterministically."

        Design: Difficulty/transitive_cascade/accept_cascade_sibling_loi_rejected
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi_a = submit_loi(listing["id"], buyer["id"], offer=2000000.00,
                           deposit=100000.00)
        loi_b = submit_loi(listing["id"], buyer["id"], offer=1900000.00,
                           deposit=95000.00)
        accepted = validate_success(api.accept_loi(loi_a["id"], LISTING_AGENT))
        assert accepted["status"] == "ACCEPTED"
        fetched_listing = validate_success(api.get_listing(listing["id"], LISTING_AGENT))
        assert fetched_listing["status"] == "UNDER_CONTRACT"
        sibling = validate_success(api.get_loi(loi_b["id"], LISTING_AGENT))
        assert sibling["status"] == "REJECTED", (
            "The listing cascade rejects every sibling LOI in SUBMITTED/COUNTERED")

    def test_accept_spawns_transaction_and_escrow_deposit(self, api):
        """PRD §3.6: "A Transaction is created with its `loi_id`, `listing_id`,
        and `buyer_id` copied from the LOI, its `agreed_price_usd` set to the
        LOI's `current_price_usd` at the moment of acceptance, and its
        `dual_agency` flag copied from the LOI"
        PRD §3.6: "Alongside the transaction, an EscrowDeposit is created
        one-to-one: its `transaction_id` points at the new transaction, the
        server generates an `escrow_ref` account reference, `deposit_amount_usd`
        is copied from the LOI's pledged deposit, and it begins in
        `AWAITING_FUNDS` status with `funding_reference` null and
        `released_usd`, `refunded_usd`, and `forfeited_usd` all at 0."

        Design: Difficulty/transitive_cascade/accept_cascade_sibling_loi_rejected
        """
        listing = setup_active_listing()
        buyer = setup_qualified_buyer(budget=3000000.00)
        loi_a = submit_loi(listing["id"], buyer["id"], offer=2000000.00,
                           deposit=100000.00)
        loi_b = submit_loi(listing["id"], buyer["id"], offer=1900000.00,
                           deposit=95000.00)
        validate_success(api.accept_loi(loi_a["id"], LISTING_AGENT))
        rows, meta = validate_paginated(
            api.list_transactions(LISTING_AGENT, {"listing_id": listing["id"]}))
        assert meta["total_count"] == 1
        tx = rows[0]
        assert tx["status"] == "OPENED"
        assert tx["loi_id"] == loi_a["id"]
        assert_money(tx["agreed_price_usd"], 2000000.00, "agreed_price_usd")
        escrow_rows, escrow_meta = validate_paginated(
            api.list_escrow_deposits(ESCROW, {"transaction_id": tx["id"]}))
        assert escrow_meta["total_count"] == 1
        escrow = escrow_rows[0]
        assert escrow["status"] == "AWAITING_FUNDS"
        assert_money(escrow["deposit_amount_usd"], 100000.00, "deposit_amount_usd")
        assert escrow["funding_reference"] is None
        assert float(escrow["released_usd"]) == 0
        assert float(escrow["refunded_usd"]) == 0
        assert float(escrow["forfeited_usd"]) == 0
        assert loi_b["id"] != loi_a["id"]


class TestListingContractCycle:
    def test_listing_returns_to_active_after_termination(self, api):
        """PRD §3.6: "Acceptance simultaneously locks the aircraft: the listing
        cascades from `ACTIVE` to `UNDER_CONTRACT`"
        PRD §3.9: "In every termination the listing cascades from
        `UNDER_CONTRACT` back to `ACTIVE` and becomes marketable again, and the
        transaction's `version` increments."

        Design: Difficulty/non_linear_state_machine/listing_contract_cycle_active_under_contract_active_sold
        """
        deal = setup_accepted_deal()
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "UNDER_CONTRACT"
        terminated = terminate_deal(deal["transaction"]["id"], as_role=LISTING_AGENT)
        assert terminated["status"] == "TERMINATED"
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "ACTIVE", "Termination re-opens the listing"

    def test_listing_cycle_ends_sold_after_close(self, api):
        """PRD §3.9: "The listing moves from `UNDER_CONTRACT` to `SOLD`, its
        terminal state"
        PRD §3.9: "In every termination the listing cascades from
        `UNDER_CONTRACT` back to `ACTIVE` and becomes marketable again, and the
        transaction's `version` increments."

        Design: Difficulty/non_linear_state_machine/listing_contract_cycle_active_under_contract_active_sold
        """
        deal = setup_accepted_deal()
        listing_id = deal["listing"]["id"]
        buyer_id = deal["buyer"]["id"]
        assert validate_success(api.get_listing(listing_id, LISTING_AGENT))["status"] == "UNDER_CONTRACT"
        terminate_deal(deal["transaction"]["id"], as_role=LISTING_AGENT)
        assert validate_success(api.get_listing(listing_id, LISTING_AGENT))["status"] == "ACTIVE"

        # Second negotiation round on the re-marketed listing.
        loi_2 = submit_loi(listing_id, buyer_id)
        validate_success(api.accept_loi(loi_2["id"], LISTING_AGENT))
        assert validate_success(api.get_listing(listing_id, LISTING_AGENT))["status"] == "UNDER_CONTRACT"
        tx_2 = get_transaction_for_listing(listing_id, status="OPENED")
        escrow_2 = get_escrow_for_transaction(tx_2["id"])
        fund_escrow(escrow_2["id"], "WIRE-22")
        facility = create_facility()
        booking = book_inspection(tx_2["id"], facility["id"])
        get_success_data(api.confirm_booking(booking["id"], TEST_USERS["facility_scheduler_headers"]))
        get_success_data(api.complete_booking(booking["id"], TEST_USERS["facility_scheduler_headers"]))
        get_success_data(api.accept_as_is(tx_2["id"], BUYER_AGENT))
        complete_delivery_conditions(tx_2["id"])
        closed = validate_success(api.close_transaction(tx_2["id"], BROKER))
        assert closed["status"] == "CLOSED"
        listing = validate_success(api.get_listing(listing_id, LISTING_AGENT))
        assert listing["status"] == "SOLD", (
            "ACTIVE -> UNDER_CONTRACT -> ACTIVE -> UNDER_CONTRACT -> SOLD")


class TestOpenTransactionCardinality:
    def test_accept_then_terminate_restores_zero_open_transactions(self, api):
        """PRD §3.6: "Acceptance simultaneously locks the aircraft: the listing
        cascades from `ACTIVE` to `UNDER_CONTRACT`"
        PRD §3.9: "In every termination the listing cascades from
        `UNDER_CONTRACT` back to `ACTIVE` and becomes marketable again, and the
        transaction's `version` increments. `CLOSED` and `TERMINATED` are the
        transaction's terminal states"

        Design: Difficulty/compensating_invariant/listing_open_transaction_cardinality_conserved
        """
        deal = setup_accepted_deal()
        rows, meta = validate_paginated(
            api.list_transactions(LISTING_AGENT, {"listing_id": deal["listing"]["id"]}))
        assert meta["total_count"] == 1, "Accept opens exactly one transaction"
        assert rows[0]["status"] == "OPENED"
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "UNDER_CONTRACT"

        terminate_deal(deal["transaction"]["id"], as_role=BROKER)
        open_rows, open_meta = validate_paginated(
            api.list_transactions(LISTING_AGENT,
                                  {"listing_id": deal["listing"]["id"],
                                   "status": "OPENED"}))
        assert open_meta["total_count"] == 0, (
            "Termination restores the open-transaction count to zero")
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "ACTIVE"

    def test_second_accept_reestablishes_single_open_transaction(self, api):
        """PRD §3.6: "An accepted LOI moves to `ACCEPTED` and opens the deal in
        a single atomic cascade."
        PRD §3.9: "`CLOSED` and `TERMINATED` are the transaction's terminal
        states; any further transition attempt on a terminal resource is
        rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/listing_open_transaction_cardinality_conserved
        """
        deal = setup_accepted_deal()
        tx_1_id = deal["transaction"]["id"]
        terminate_deal(tx_1_id, as_role=BROKER)

        loi_2 = submit_loi(deal["listing"]["id"], deal["buyer"]["id"])
        validate_success(api.accept_loi(loi_2["id"], LISTING_AGENT))
        open_rows, open_meta = validate_paginated(
            api.list_transactions(LISTING_AGENT,
                                  {"listing_id": deal["listing"]["id"],
                                   "status": "OPENED"}))
        assert open_meta["total_count"] == 1, "Second accept re-establishes exactly one"
        assert open_rows[0]["loi_id"] == loi_2["id"]
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "UNDER_CONTRACT"
        first = validate_success(api.get_transaction(tx_1_id, LISTING_AGENT))
        assert first["status"] == "TERMINATED", (
            "The terminal first transaction remains queryable and does not count")
