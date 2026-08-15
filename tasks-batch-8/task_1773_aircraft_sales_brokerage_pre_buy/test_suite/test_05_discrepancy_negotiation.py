"""Discrepancy findings: raising, countering, resolution paths, and bubble-ups."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_money,
    counter_discrepancy,
    create_buyer_payload,
    create_discrepancy_item_payload,
    get_success_data,
    raise_discrepancy,
    setup_discrepancy_negotiation_deal,
    setup_inspection_complete_deal,
    validate_error,
    validate_success,
)

BROKER = TEST_USERS["broker_principal_headers"]
LISTING_AGENT = TEST_USERS["listing_agent_headers"]
BUYER_AGENT = TEST_USERS["buyer_agent_headers"]
SCHEDULER = TEST_USERS["facility_scheduler_headers"]


class TestFindingBubbleUps:
    def test_first_discrepancy_moves_transaction_to_negotiation(self, api):
        """PRD §3.8: "Each finding starts in `RAISED` status with
        `proposed_credit_usd`, `credit_amount_usd`, and `resolution` all null.
        The very first finding raised on a transaction moves it from
        `INSPECTION_COMPLETE` to `DISCREPANCY_NEGOTIATION`, formally opening the
        airworthiness-and-cosmetic negotiation phase."

        Design: Corner/state_machines/first_discrepancy_moves_transaction_to_negotiation
        """
        deal = setup_inspection_complete_deal()
        assert deal["transaction"]["status"] == "INSPECTION_COMPLETE"
        resp = api.raise_discrepancy_item(
            deal["transaction"]["id"],
            create_discrepancy_item_payload(deal["booking"]["id"]),
            SCHEDULER)
        item = validate_success(resp, 201)
        assert item["status"] == "RAISED"
        assert item["proposed_credit_usd"] is None
        assert item["credit_amount_usd"] is None
        assert item["resolution"] is None
        tx = validate_success(api.get_transaction(deal["transaction"]["id"], BROKER))
        assert tx["status"] == "DISCREPANCY_NEGOTIATION"

    def test_last_resolution_bubbles_to_delivery_pending(self, api):
        """PRD §3.8: "Every resolution recomputes the transaction's
        `credits_total_usd`, which is the sum of `credit_amount_usd` over the
        transaction's resolved items whose `resolution` is `CREDIT` — repairs
        and waivers contribute nothing. And when a resolution leaves every item
        of the transaction in `RESOLVED`, the transaction bubbles up from
        `DISCREPANCY_NEGOTIATION` to `DELIVERY_PENDING` with the recomputed
        credits in place."

        Design: Corner/state_machines/last_resolution_bubbles_to_delivery_pending
        """
        deal = setup_inspection_complete_deal()
        tx_id = deal["transaction"]["id"]
        item_1 = raise_discrepancy(tx_id, deal["booking"]["id"],
                                   description="Corrosion at MLG trunnion",
                                   estimated_cost_usd=185000.00)
        item_2 = raise_discrepancy(tx_id, deal["booking"]["id"],
                                   description="Cabin sidewall delamination",
                                   estimated_cost_usd=42000.00)
        counter_discrepancy(item_1["id"], proposed_credit_usd=100000.25)
        get_success_data(api.agree_credit(item_1["id"], BUYER_AGENT))
        tx = validate_success(api.get_transaction(tx_id, BROKER))
        assert tx["status"] == "DISCREPANCY_NEGOTIATION", (
            "One item still open: no bubble-up yet")

        resolved = validate_success(api.waive_discrepancy_item(item_2["id"], BUYER_AGENT))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution"] == "WAIVED"
        tx = validate_success(api.get_transaction(tx_id, BROKER))
        assert tx["status"] == "DELIVERY_PENDING"
        assert_money(tx["credits_total_usd"], 100000.25, "credits_total_usd")


class TestAcceptAsIsGate:
    def test_accept_as_is_with_open_items_returns_open_discrepancies(self, api):
        """PRD §3.9: "accepting the aircraft as-is, by the `BuyerAgent`, moves
        the transaction from `INSPECTION_COMPLETE` to `DELIVERY_PENDING`, but
        only while zero discrepancy items exist for the transaction — otherwise
        it is rejected with `ERR_OPEN_DISCREPANCIES` (HTTP 409)"

        Design: Corner/state_machines/accept_as_is_with_open_items_returns_open_discrepancies
        """
        deal = setup_discrepancy_negotiation_deal()  # one RAISED item
        resp = api.accept_as_is(deal["transaction"]["id"], BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_OPEN_DISCREPANCIES)
        tx = validate_success(api.get_transaction(deal["transaction"]["id"], BROKER))
        assert tx["status"] == "DISCREPANCY_NEGOTIATION"


class TestAirworthinessSafety:
    def test_waive_open_airworthiness_item_returns_not_waivable(self, api):
        """PRD §3.8: "Waiving moves a `RAISED` or `COUNTERED` item to `RESOLVED`
        with `resolution` recorded as `WAIVED`, but only for
        `NON_AIRWORTHINESS` findings: an airworthiness item may never be waived,
        and the attempt is rejected with `ERR_AIRWORTHINESS_NOT_WAIVABLE` (HTTP
        422)."

        Design: Corner/state_machines/waive_open_airworthiness_item_returns_not_waivable
        """
        deal = setup_discrepancy_negotiation_deal(severity="AIRWORTHINESS",
                                                  estimated_cost_usd=240000.00)
        assert deal["discrepancy"]["status"] == "RAISED"
        resp = api.waive_discrepancy_item(deal["discrepancy"]["id"], BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_AIRWORTHINESS_NOT_WAIVABLE)
        fetched = validate_success(
            api.get_discrepancy_item(deal["discrepancy"]["id"], SCHEDULER))
        assert fetched["status"] == "RAISED"

    def test_waive_resolved_airworthiness_item_returns_invalid_state(self, api):
        """PRD §2.8: "Every request is validated against a fixed pipeline of
        checks, evaluated in the following order, and the first failing check
        determines the error returned"
        PRD §2.8: "5. **State preconditions**, evaluated in three sub-steps: (a)
        the target resource is in a state that permits the requested transition,
        failing with `ERR_INVALID_STATE` (HTTP 409)"
        PRD §2.8: "6. **Business safety** — an AIRWORTHINESS-severity finding
        may never be waived; failures return `ERR_AIRWORTHINESS_NOT_WAIVABLE`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/waive_resolved_airworthiness_state_beats_safety
        """
        deal = setup_discrepancy_negotiation_deal(severity="AIRWORTHINESS",
                                                  estimated_cost_usd=240000.00)
        get_success_data(api.commit_repair(deal["discrepancy"]["id"], LISTING_AGENT))
        # The item is terminal RESOLVED: the state check (step 5) fires at 409
        # before the safety rule (step 6, HTTP 422) is ever evaluated.
        resp = api.waive_discrepancy_item(deal["discrepancy"]["id"], BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_waive_leaves_resolution_and_transaction_untouched(self, api):
        """PRD §3.8: "Alternatively, the seller may commit to repair the finding
        before delivery: committing moves the item from `RAISED` or `COUNTERED`
        to `RESOLVED` with its `resolution` recorded as `REPAIR`."
        PRD §2.8: "5. **State preconditions**, evaluated in three sub-steps: (a)
        the target resource is in a state that permits the requested transition,
        failing with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/waive_resolved_airworthiness_state_beats_safety
        """
        deal = setup_discrepancy_negotiation_deal(severity="AIRWORTHINESS",
                                                  estimated_cost_usd=240000.00)
        get_success_data(api.commit_repair(deal["discrepancy"]["id"], LISTING_AGENT))
        tx = validate_success(api.get_transaction(deal["transaction"]["id"], BROKER))
        assert tx["status"] == "DELIVERY_PENDING", "Single resolved item bubbles up"
        resp = api.waive_discrepancy_item(deal["discrepancy"]["id"], BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        item = validate_success(
            api.get_discrepancy_item(deal["discrepancy"]["id"], SCHEDULER))
        assert item["status"] == "RESOLVED"
        assert item["resolution"] == "REPAIR"
        tx = validate_success(api.get_transaction(deal["transaction"]["id"], BROKER))
        assert tx["status"] == "DELIVERY_PENDING"


class TestCreditAgreement:
    def test_agree_credit_without_proposal_returns_credit_not_proposed(self, api):
        """PRD §3.8: "Agreeing to the seller's credit moves a `COUNTERED` item
        to `RESOLVED` with `resolution` recorded as `CREDIT` and
        `credit_amount_usd` set to the previously proposed `proposed_credit_usd`;
        attempting it when no credit was proposed — when `proposed_credit_usd`
        is still null — is rejected with `ERR_CREDIT_NOT_PROPOSED` (HTTP 409)."

        Design: Corner/validations/agree_credit_without_proposal_returns_credit_not_proposed
        """
        deal = setup_discrepancy_negotiation_deal()
        counter_discrepancy(deal["discrepancy"]["id"],
                            repair_offer_note="Seller will reskin trunnion before delivery")
        resp = api.agree_credit(deal["discrepancy"]["id"], BUYER_AGENT)
        validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_PROPOSED)
        fetched = validate_success(
            api.get_discrepancy_item(deal["discrepancy"]["id"], SCHEDULER))
        assert fetched["status"] == "COUNTERED"

    def test_credits_total_recomputed_on_credit_resolution(self, api):
        """PRD §3.8: "Agreeing to the seller's credit moves a `COUNTERED` item
        to `RESOLVED` with `resolution` recorded as `CREDIT` and
        `credit_amount_usd` set to the previously proposed `proposed_credit_usd`"
        PRD §3.8: "Every resolution recomputes the transaction's
        `credits_total_usd`, which is the sum of `credit_amount_usd` over the
        transaction's resolved items whose `resolution` is `CREDIT` — repairs
        and waivers contribute nothing."
        PRD §3.6: "The transaction starts in `OPENED` status with
        `logbook_complete` and `registration_docs_complete` both false,
        `tax_planning_notes` and `termination_reason` null, `credits_total_usd`
        at 0, and the three closing outputs — `commission_amount_usd`,
        `settlement_buyer_due_usd`, and `settlement_seller_net_usd` — null until
        closing computes them."

        Design: Corner/calculations/credits_total_recomputed_on_credit_resolution
        """
        deal = setup_discrepancy_negotiation_deal()
        tx_id = deal["transaction"]["id"]
        tx = validate_success(api.get_transaction(tx_id, BROKER))
        assert float(tx["credits_total_usd"]) == 0, "credits_total_usd starts at 0"
        counter_discrepancy(deal["discrepancy"]["id"], proposed_credit_usd=100000.25)
        resolved = validate_success(api.agree_credit(deal["discrepancy"]["id"],
                                                     BUYER_AGENT))
        assert resolved["resolution"] == "CREDIT"
        assert_money(resolved["credit_amount_usd"], 100000.25, "credit_amount_usd")
        tx = validate_success(api.get_transaction(tx_id, BROKER))
        assert_money(tx["credits_total_usd"], 100000.25, "credits_total_usd")


class TestCrossEntityCoherence:
    def test_discrepancy_booking_mismatch_returns_unprocessable(self, api):
        """PRD §3.8: "The referenced booking must belong to the transaction
        under which the finding is raised; a booking from a different
        transaction is rejected with `ERR_BOOKING_NOT_FOR_TRANSACTION` (HTTP
        422)."

        Design: Corner/validations/discrepancy_booking_mismatch_returns_unprocessable
        """
        deal_1 = setup_inspection_complete_deal()
        deal_2 = setup_inspection_complete_deal(
            listing_overrides={"tail_number": "N1002GS", "year": 2016,
                               "total_time_hours": 3050,
                               "asking_price_usd": 11800000.00,
                               "seller_name": "Meridian Air LLC"},
            start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T14:00:00Z")
        # Raise on transaction 2 citing the booking that belongs to transaction 1.
        resp = api.raise_discrepancy_item(
            deal_2["transaction"]["id"],
            create_discrepancy_item_payload(
                deal_1["booking"]["id"],
                description="Misfiled finding from another deal",
                estimated_cost_usd=1000.00),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOR_TRANSACTION)


class TestDiscrepancyNotFound:
    def test_get_discrepancy_item_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_discrepancy_item_not_found_returns_404
        """
        get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        resp = api.get_discrepancy_item(NON_EXISTENT_UUID, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_DISCREPANCY_ITEM_NOT_FOUND)
