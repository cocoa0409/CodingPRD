"""Posting bids: the DRAFT → ACTIVE ↔ SUSPENDED loop, the terminal exits, and
the way a bid's own status gates striking a contract against it."""

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_bid,
    create_bid_payload,
    create_purchase_contract_payload,
    new_bid,
    new_desk,
    new_location,
    read_bid,
    read_position,
    setup_trading_floor,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


ADMIN = TEST_USERS["desk_admin_headers"]
MERCH = TEST_USERS["merchandiser_headers"]


class TestBidValidation:

    def test_bid_with_an_undeclared_commodity_is_an_invalid_request(self, api):
        """PRD §2.8: "Required fields are present, enum values are members of their
        declared sets, numbers respect their declared ranges, dates parse as
        `YYYY-MM-DD` and datetimes as ISO 8601 UTC — otherwise
        `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."
        PRD §3.1: "A `DeskAdmin` drafts one by naming its `commodity_code` — one of
        `CORN`, `SOYBEANS` or `HRW_WHEAT` — an `effective_from` instant at or after
        which it may be put into force, and a non-empty array of `tiers`."

        Design: Corner/entities/create_bid_with_invalid_commodity_enum_returns_invalid_request
        """
        desk = new_desk(desk_code="CD06", name="Corner Desk 6",
                        credit_line_usd=250000.00)
        location = new_location(desk["id"], location_code="E1", name="One",
                                intake_capacity_bushels=100000, rail_served=True)

        payload = create_bid_payload(
            location["id"], commodity_code="OATS", max_bushels=100000,
        )
        validate_error(api.create_bid(payload, MERCH),
                       ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        listed = validate_success(
            api.list_bids(MERCH, params={"location_id": location["id"]}), 200
        )
        assert listed == [], "the rejected draft must not persist a bid row"


class TestBidStateMachine:

    def test_activating_an_already_active_bid_is_an_invalid_state(self, api):
        """PRD §2.8: "The target row's own lifecycle state permits the requested
        transition — otherwise `ERR_INVALID_STATE` (409). Applies to
        `POST /grain/bids/{bidId}/activate`, `POST /grain/bids/{bidId}/suspend`,
        `POST /grain/bids/{bidId}/withdraw`,
        `POST /grain/discount-schedules/{scheduleId}/activate`,
        `POST /grain/freight-bookings/{bookingId}/confirm`,
        `POST /grain/freight-bookings/{bookingId}/substitute`,
        `POST /grain/freight-bookings/{bookingId}/cancel`,
        `POST /grain/margin-calls/{marginCallId}/cure`,
        `POST /grain/hedge-positions/{positionId}/add-lots`,
        `POST /grain/hedge-positions/{positionId}/mark-to-market` and
        `POST /grain/hedge-positions/{positionId}/liquidate`."
        PRD §3.2: "A bid may be activated from `DRAFT` or re-activated from
        `SUSPENDED`, but in either case two conditions must hold."

        Design: Corner/state_machines/activate_an_already_active_bid_returns_invalid_state
        """
        desk = new_desk(desk_code="CD11", name="Corner Desk 11",
                        credit_line_usd=250000.00)
        location = new_location(desk["id"], location_code="E1", name="One",
                                intake_capacity_bushels=100000, rail_served=True)
        bid = new_bid(location["id"], activate=True, max_bushels=100000)

        validate_error(api.activate_bid(bid["id"], MERCH),
                       ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert read_bid(bid["id"])["status"] == "ACTIVE"

    def test_a_withdrawn_bid_can_no_longer_be_suspended(self, api):
        """PRD §3.2: "Withdrawal is the permanent exit: a bid in either `ACTIVE` or
        `SUSPENDED` may be withdrawn, landing in `WITHDRAWN`, after which it is
        neither a contract source nor an eligible damages price source."
        PRD §3.2: "Suspending an `ACTIVE` bid moves it `ACTIVE → SUSPENDED`, which
        takes it off the board without destroying it; contract creation against a
        suspended bid is refused with `ERR_BID_NOT_ACTIVE`."

        Design: Corner/state_machines/withdrawn_bid_cannot_be_suspended_from_terminal_state
        """
        desk = new_desk(desk_code="CD12", name="Corner Desk 12",
                        credit_line_usd=250000.00)
        location = new_location(desk["id"], location_code="E1", name="One",
                                intake_capacity_bushels=100000, rail_served=True)
        bid = new_bid(location["id"], activate=True, max_bushels=100000)
        validate_success(api.withdraw_bid(bid["id"], MERCH), 200)

        validate_error(api.suspend_bid(bid["id"], MERCH),
                       ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert read_bid(bid["id"])["status"] == "WITHDRAWN"

    def test_activating_at_the_exact_expiry_instant_is_refused(self, api):
        """PRD §3.2: "Second, the logical clock must be strictly before the bid's
        `expires_at` — a bid whose expiry the clock has already reached or passed is
        refused with `ERR_BID_EXPIRED`, even when it is still nominally sitting in
        `DRAFT`."
        PRD §2.5: "Advancing the clock has exactly one automatic consequence: any
        bid whose status is `ACTIVE` or `SUSPENDED` and whose `expires_at` is at or
        before the new clock reading transitions to `EXPIRED`, and its id appears in
        `expired_bid_ids`."

        Design: Corner/validations/activating_a_bid_at_its_expiry_instant_returns_bid_expired
        """
        desk = new_desk(desk_code="CD25", name="Corner Desk 25",
                        credit_line_usd=250000.00)
        location = new_location(desk["id"], location_code="E1", name="One",
                                intake_capacity_bushels=100000, rail_served=True)
        bid = new_bid(location["id"], activate=False, max_bushels=100000,
                      expires_at="2026-08-10T00:00:00Z")

        advance_clock("2026-08-10T00:00:00Z")

        validate_error(api.activate_bid(bid["id"], MERCH),
                       ApiErrorId.ERR_BID_EXPIRED.value, 422)
        assert read_bid(bid["id"])["status"] == "DRAFT", (
            "a DRAFT bid is never auto-expired by the clock"
        )

    def test_activating_a_bid_that_collides_on_the_market_slot_is_refused(self, api):
        """PRD §3.2: "First, no other bid whose status is `ACTIVE` or `SUSPENDED`
        may already occupy the same market slot, where the slot is the combination
        of `location_id`, `commodity_code`, `futures_month` and
        `delivery_period_start`; a collision is refused with `ERR_DUPLICATE_BID`."

        Design: Corner/validations/activating_a_colliding_bid_returns_duplicate_bid
        """
        desk = new_desk(desk_code="CD26", name="Corner Desk 26",
                        credit_line_usd=250000.00)
        location = new_location(desk["id"], location_code="E1", name="One",
                                intake_capacity_bushels=100000, rail_served=True)
        first = new_bid(location["id"], activate=True, max_bushels=100000)

        colliding = validate_success(api.create_bid(create_bid_payload(
            location["id"], commodity_code="CORN", futures_month="2026-12",
            delivery_period_start="2026-10-01", delivery_period_end="2026-11-30",
            basis_cents=-28, max_bushels=100000,
        ), MERCH), 201)
        assert_bid(colliding)

        validate_error(api.activate_bid(colliding["id"], MERCH),
                       ApiErrorId.ERR_DUPLICATE_BID.value, 409)
        assert read_bid(colliding["id"])["status"] == "DRAFT"
        assert read_bid(first["id"])["status"] == "ACTIVE"

    def test_moving_the_clock_past_expiry_retires_the_active_bid_only(self, api):
        """PRD §2.5: "Advancing the clock has exactly one automatic consequence: any
        bid whose status is `ACTIVE` or `SUSPENDED` and whose `expires_at` is at or
        before the new clock reading transitions to `EXPIRED`, and its id appears in
        `expired_bid_ids`."
        PRD §2.5: "A `DeskAdmin` moves it by supplying a `to_iso8601` instant to the
        clock-setting capability, whose response reports the new `current_utc`
        together with `expired_bid_ids`, the list of bid identifiers that the move
        retired."

        Design: Corner/endpoints/clock_endpoint_expires_an_active_bid_and_returns_its_id
        """
        desk = new_desk(desk_code="CD43", name="Corner Desk 43",
                        credit_line_usd=250000.00)
        location = new_location(desk["id"], location_code="E1", name="One",
                                intake_capacity_bushels=100000, rail_served=True)
        active_bid = new_bid(location["id"], activate=True, max_bushels=100000,
                             expires_at="2026-08-10T00:00:00Z")
        draft_bid = new_bid(location["id"], activate=False, commodity_code="SOYBEANS",
                            futures_month="2027-01", basis_cents=-60,
                            max_bushels=100000, expires_at="2026-08-10T00:00:00Z")

        result = validate_success(
            api.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, ADMIN), 200
        )
        assert result["current_utc"] == "2026-08-10T00:00:00.000Z"
        assert result["expired_bid_ids"] == [active_bid["id"]], (
            f"Expected only the ACTIVE bid to be retired, got "
            f"{result['expired_bid_ids']}"
        )
        assert read_bid(active_bid["id"])["status"] == "EXPIRED"
        assert read_bid(draft_bid["id"])["status"] == "DRAFT"


class TestBidStatusGatesContractCreation:
    """The Bid ACTIVE ↔ SUSPENDED cycle, observed through what contract
    creation does on either side of the trough."""

    def test_suspending_a_bid_blocks_contract_creation_against_it(self, api):
        """PRD §3.2: "Suspending an `ACTIVE` bid moves it `ACTIVE → SUSPENDED`,
        which takes it off the board without destroying it; contract creation
        against a suspended bid is refused with `ERR_BID_NOT_ACTIVE`."
        PRD §3.4: "The bid must be `ACTIVE`, or `ERR_BID_NOT_ACTIVE` answers."

        Design: Difficulty/non_linear_state_machine/bid_active_suspended_active_cycle_gates_contract_creation
        """
        floor = setup_trading_floor(desk_code="GD7", desk_name="Bid Cycle Desk",
                                    with_schedule=False, lots_open=10)
        validate_success(api.suspend_bid(floor["bid"]["id"], MERCH), 200)
        assert read_bid(floor["bid"]["id"])["status"] == "SUSPENDED"

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"],
            contract_type="CASH", bushels=10000, seller_name="Bell Farms",
            futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_BID_NOT_ACTIVE.value, 409)
        assert read_position(floor["position"]["id"])["lots_committed"] == 0

    def test_reactivating_a_suspended_bid_reopens_contract_creation(self, api):
        """PRD §3.2: "Re-activation moves it `SUSPENDED → ACTIVE`, subject to the
        same duplicate-slot and expiry checks as a first activation, and this
        `ACTIVE ↔ SUSPENDED` loop may be traversed any number of times."
        PRD §3.2: "It is the sum of contracted bushels over every purchase contract
        referencing this bid whose `status` is `ACTIVE`, `SETTLED` or `ROLLED`."

        Design: Difficulty/non_linear_state_machine/bid_active_suspended_active_cycle_gates_contract_creation
        """
        floor = setup_trading_floor(desk_code="GD7", desk_name="Bid Cycle Desk",
                                    with_schedule=False, lots_open=10)
        bid_id = floor["bid"]["id"]
        validate_success(api.suspend_bid(bid_id, MERCH), 200)

        reactivated = validate_success(api.activate_bid(bid_id, MERCH), 200)
        assert reactivated["status"] == "ACTIVE", (
            "SUSPENDED → ACTIVE closes the loop and returns the bid to the board"
        )

        payload = create_purchase_contract_payload(
            bid_id, floor["position"]["id"], contract_type="CASH", bushels=10000,
            seller_name="Bell Farms", futures_price_cents=448,
        )
        contract = validate_success(api.create_purchase_contract(payload, MERCH), 201)
        assert contract["status"] == "ACTIVE"
        assert contract["hedge_lots_assigned"] == 2, (
            f"10,000 bushels is two lots, got {contract['hedge_lots_assigned']}"
        )
        assert read_bid(bid_id)["contracted_bushels"] == pytest.approx(10000.00, abs=0.01)

    def test_a_withdrawn_bid_cannot_carry_a_new_contract(self, api):
        """PRD §3.2: "Withdrawal is the permanent exit: a bid in either `ACTIVE` or
        `SUSPENDED` may be withdrawn, landing in `WITHDRAWN`, after which it is
        neither a contract source nor an eligible damages price source."
        PRD §3.4: "The bid must be `ACTIVE`, or `ERR_BID_NOT_ACTIVE` answers."

        Design: Difficulty/cross_entity_state_dependency/contract_creation_gated_by_withdrawn_bid_state
        """
        floor = setup_trading_floor(desk_code="GD17", desk_name="Withdrawn Bid Desk",
                                    with_schedule=False, lots_open=10)
        validate_success(api.withdraw_bid(floor["bid"]["id"], MERCH), 200)

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=10000, seller_name="Bell Farms", futures_price_cents=448,
        )
        resp = api.create_purchase_contract(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_BID_NOT_ACTIVE.value, 409)
        assert resp.status_code == 409

        assert read_bid(floor["bid"]["id"])["status"] == "WITHDRAWN"

    def test_a_withdrawn_bid_leaves_hedge_lots_and_allowance_untouched(self, api):
        """PRD §3.4: "The bid must be `ACTIVE`, or `ERR_BID_NOT_ACTIVE` answers."
        PRD §3.4: "A successful strike commits the assigned lots on the hedge
        position and recomputes, in one pass, the bid's `contracted_bushels`, the
        elevator's `committed_intake_bushels`, and the desk's
        `committed_hedge_lots`, `open_bushel_commitment` and `unpriced_bushels`."

        Design: Difficulty/cross_entity_state_dependency/contract_creation_gated_by_withdrawn_bid_state
        """
        floor = setup_trading_floor(desk_code="GD17", desk_name="Withdrawn Bid Desk",
                                    with_schedule=False, lots_open=10)
        validate_success(api.withdraw_bid(floor["bid"]["id"], MERCH), 200)

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=10000, seller_name="Bell Farms", futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_BID_NOT_ACTIVE.value, 409)

        bid = read_bid(floor["bid"]["id"])
        assert bid["contracted_bushels"] == pytest.approx(0, abs=0.01), (
            "a rejected strike consumes none of the bid's allowance"
        )
        position = read_position(floor["position"]["id"])
        assert position["lots_committed"] == 0
        assert position["lots_available"] == 10
