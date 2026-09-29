"""Operations on one entity that are fenced by the state of another: taking a
session live behind the county notice, and binding a buyer behind the title axis."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_settlement_conserved,
    assert_timestamp_equals,
    confirm_sale,
    execute_contract,
    expected_buyer_premium,
    expected_doc_fee,
    expected_platform_fee,
    list_lot_contracts,
    open_event,
    open_event_payload,
    read_event,
    read_listing,
    read_lot,
    read_sale,
    read_seller,
    record_title_clearance,
    sale_contract_payload,
    scheduled_lot,
    set_clock,
    sold_lot,
    validate_error,
)
from test_helpers import make_auction_ops_headers

OPS = TEST_USERS["auction_ops_headers"]
SALE_NOTICED_AT = "2026-09-15T18:00:00Z"
OPEN_ATTEMPT_AT = "2026-09-15T17:05:00Z"


def _event_bound_to_an_unconfirmed_sale():
    """A scheduled event linked to a county notice that is still `PENDING`."""
    return scheduled_lot(
        org_name="Redwood Trust Servicing",
        seller_type="SERVICER",
        contact_email="reo@redwoodtrust.example",
        settlement_account_ref="ACH-RED-3",
        street_address="77 Redwood Way",
        estimated_value_cents=28000000,
        event_title="Alameda Notice-Linked Session",
        trustee_sale_at=SALE_NOTICED_AT,
        confirm_trustee_sale=False,
    )


class TestEventOpenDependsOnTrusteeSale:
    def test_open_is_refused_while_the_linked_sale_is_unconfirmed(self):
        """An event carrying a `trustee_sale_id` cannot be taken live until the
        trustee has confirmed the notice, and the refusal leaves the event and its
        lot untouched.

        PRD: "Taking a session live is a single operator action with no request body,
        and it is fenced by four conditions. The event must be `SCHEDULED`, or
        `ERR_EVENT_NOT_SCHEDULED`; it must hold at least one lot, so a `lot_count` of
        0 is `ERR_EVENT_HAS_NO_LOTS`; the logical clock must have reached or passed the
        event's `starts_at`, or `ERR_EVENT_NOT_STARTED`; and if the event carries a
        `trustee_sale_id`, that sale's `status` must be `CONFIRMED`, or
        `ERR_TRUSTEE_SALE_NOT_CONFIRMED` — an event with no county linkage passes this
        gate unconditionally."

        Design: Difficulty/cross_entity_state_dependency/event_open_blocked_until_trustee_sale_confirmed
        """
        scenario = _event_bound_to_an_unconfirmed_sale()
        set_clock(OPEN_ATTEMPT_AT)

        response = api_client.open_auction_event(
            scenario.event_id, open_event_payload(), OPS
        )
        validate_error(response, "ERR_TRUSTEE_SALE_NOT_CONFIRMED", 409)

        event = read_event(scenario.event_id)
        assert event["event_status"] == "SCHEDULED"
        assert event["opened_at"] is None
        assert read_lot(scenario.lot_id)["lot_status"] == "PENDING"
        assert read_sale(scenario.sale_id)["status"] == "PENDING"

    def test_open_succeeds_once_the_trustee_confirms_the_notice(self):
        """Confirming the county notice removes the block, and the same open request
        then takes the event live and opens its pending lot.

        PRD: "The event then moves `SCHEDULED → LIVE`, `opened_at` is stamped with the
        logical clock, and every lot of the event whose `lot_status` is `PENDING` or
        `SUSPENDED` moves to `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/event_open_blocked_until_trustee_sale_confirmed
        """
        scenario = _event_bound_to_an_unconfirmed_sale()
        set_clock(OPEN_ATTEMPT_AT)
        validate_error(
            api_client.open_auction_event(scenario.event_id, open_event_payload(), OPS),
            "ERR_TRUSTEE_SALE_NOT_CONFIRMED",
            409,
        )

        sale = confirm_sale(scenario.sale_id)
        assert sale["status"] == "CONFIRMED"

        event = open_event(scenario.event_id)
        assert event["event_status"] == "LIVE"
        assert_timestamp_equals(event["opened_at"], OPEN_ATTEMPT_AT)

        lot = read_lot(scenario.lot_id)
        assert lot["lot_status"] == "OPEN"
        assert_timestamp_equals(lot["bid_close_at"], "2026-09-15T18:00:00Z")


def _sold_lot_with_pending_title():
    """A lot hammered down at 20000000 whose asset has had no title finding
    recorded, so its `title_clearance_status` is still `PENDING`."""
    return sold_lot(
        org_name="Golden Oak Bank",
        seller_type="BANK",
        contact_email="reo@goldenoak.example",
        settlement_account_ref="ACH-GOLD-2",
        default_commission_bps=500,
        street_address="310 Oak Grove Rd",
        estimated_value_cents=26000000,
        event_title="Alameda Title-Axis Session",
        bid_amount_cents=20000000,
        funded_cents=2000000,
        bid_at="2026-09-15T17:10:00Z",
        close_at="2026-09-15T18:05:00Z",
    )


class TestContractExecutionDependsOnTitleAxis:
    def test_execution_is_refused_while_the_title_axis_is_pending(self):
        """A sold lot is not enough: the asset's title work must have landed, and
        the refusal writes no contract at all.

        PRD: "The asset's title work must have landed: its `title_clearance_status`
        must be `CLEARED` or `CLOUDED_DISCLOSED`, so executing while the title axis is
        still `PENDING` is `ERR_TITLE_CLEARANCE_PENDING`, and executing against a
        `DEFECTIVE` finding is `ERR_TITLE_DEFECTIVE`."

        Design: Difficulty/cross_entity_state_dependency/contract_execution_blocked_until_title_axis_cleared
        """
        scenario = _sold_lot_with_pending_title()
        set_clock("2026-09-15T18:10:00Z")

        response = api_client.execute_sale_contract(
            scenario.lot_id,
            sale_contract_payload(closing_window_days=21),
            make_auction_ops_headers("ops-contract-2"),
        )
        validate_error(response, "ERR_TITLE_CLEARANCE_PENDING", 409)

        assert list_lot_contracts(scenario.lot_id) == []
        assert read_lot(scenario.lot_id)["lot_status"] == "CLOSED_SOLD"
        listing = read_listing(scenario.listing_id)
        assert listing["listing_status"] == "SOLD_PENDING_CONTRACT"
        assert listing["title_clearance_status"] == "PENDING"

    def test_execution_succeeds_and_prices_the_contract_once_title_is_cleared(self):
        """Once the title officer records a clear finding, the same request executes
        and posts the full settlement off the cleared title condition.

        PRD: "`platform_fee_cents` is the exact integer sum of those three rounded
        components. `seller_net_cents` is `contract_price_cents` less
        `platform_fee_cents`."

        Design: Difficulty/cross_entity_state_dependency/contract_execution_blocked_until_title_axis_cleared
        """
        scenario = _sold_lot_with_pending_title()
        set_clock("2026-09-15T18:10:00Z")
        validate_error(
            api_client.execute_sale_contract(
                scenario.lot_id,
                sale_contract_payload(closing_window_days=21),
                make_auction_ops_headers("ops-contract-2"),
            ),
            "ERR_TITLE_CLEARANCE_PENDING",
            409,
        )

        listing = record_title_clearance(scenario.listing_id, "CLEARED", "CLEAR")
        assert listing["title_clearance_status"] == "CLEARED"
        assert listing["title_condition"] == "CLEAR"

        contract = execute_contract(scenario.lot_id, closing_window_days=21)

        assert contract["contract_status"] == "EXECUTED"
        assert contract["settlement_status"] == "POSTED"
        assert contract["contract_price_cents"] == 20000000
        premium = expected_buyer_premium(20000000, "VACANT", "CLEAR")
        assert contract["final_buyer_premium_cents"] == premium == 1600000
        assert contract["doc_fee_cents"] == expected_doc_fee(20000000, premium) == 95000
        assert contract["total_due_cents"] == 21695000
        assert (
            contract["platform_fee_cents"]
            == expected_platform_fee(20000000, 500, "CLEAR")
            == 1070000
        )
        assert contract["seller_net_cents"] == 18930000
        assert contract["settlement_gross_cents"] == 21600000
        assert_settlement_conserved(contract)

    def test_closing_deadline_is_measured_from_the_execution_instant(self):
        """The deadline is the execution instant advanced by the closing window, so a
        contract executed at 18:10 on 15 September with a 21-day window is due at
        18:10 on 6 October — not from the earlier hammer instant.

        PRD: "Execution stamps `execution_at` with the logical clock, records the
        acting operator as `executed_by_user_id`, sets `contract_status` to `EXECUTED`,
        and computes `closing_deadline_at` as `execution_at` advanced by
        `closing_window_days` days."

        Design: Difficulty/cross_entity_state_dependency/contract_execution_blocked_until_title_axis_cleared
        """
        scenario = _sold_lot_with_pending_title()
        record_title_clearance(scenario.listing_id, "CLEARED", "CLEAR")
        set_clock("2026-09-15T18:10:00Z")

        contract = execute_contract(scenario.lot_id, closing_window_days=21)

        assert_timestamp_equals(contract["execution_at"], "2026-09-15T18:10:00Z")
        assert_timestamp_equals(contract["closing_deadline_at"], "2026-10-06T18:10:00Z")
        # The seller is credited at execution, on the settlement axis.
        assert read_seller(scenario.seller_id)["settled_net_cents"] == 18930000
