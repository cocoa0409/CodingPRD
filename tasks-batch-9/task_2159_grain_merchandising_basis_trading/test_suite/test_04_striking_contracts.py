"""Striking a purchase contract: the copied fields, the hedge-lot arithmetic,
the referential gates on the strike, and the conserved desk aggregates."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_contract_pricing_invariants,
    assert_purchase_contract,
    cancel_contract,
    create_purchase_contract_payload,
    new_bid,
    new_contract,
    new_desk,
    new_hedge_position,
    new_location,
    read_bid,
    read_contract,
    read_desk,
    read_location,
    read_position,
    setup_trading_floor,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


MERCH = TEST_USERS["merchandiser_headers"]
RISK = TEST_USERS["risk_officer_headers"]


class TestStrikingAContract:

    def test_a_deferred_contract_is_born_on_all_three_initial_axes(self, api):
        """PRD §3.4: "`DEFERRED` fixes neither and is therefore the type that
        carries the most naked exposure."
        PRD §3.4: "a `DEFERRED` contract is born with both at zero and a
        `pricing_status` of `UNPRICED`."
        PRD §3.4: "`rolled_from_contract_id` is null on a directly struck contract,
        `roll_adjustment_cents` starts at zero, `damages_usd` starts at zero,
        `termination_reason` is null, `delivered_bushels` and `settled_value_usd`
        start at zero, `pricing_locked` starts false, `delivery_status` starts at
        `OPEN`, and the lifecycle `status` starts at `ACTIVE`."
        PRD §3.4: "The `gross_unit_price_cents` a contract trades at is the sum of
        three components — `futures_price_cents`, `basis_cents` and
        `roll_adjustment_cents` — and it remains null for as long as either of the
        first two is unset."

        Design: Corner/state_machines/deferred_contract_starts_active_open_and_unpriced
        """
        floor = setup_trading_floor(desk_code="CD13", desk_name="Corner Desk 13",
                                    with_schedule=False, lots_open=10)

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"],
            contract_type="DEFERRED", bushels=20000, seller_name="Bell Farms",
        )
        contract = validate_success(api.create_purchase_contract(payload, MERCH), 201)
        assert_purchase_contract(contract)

        assert contract["status"] == "ACTIVE"
        assert contract["delivery_status"] == "OPEN"
        assert contract["pricing_status"] == "UNPRICED"
        assert contract["futures_price_cents"] is None
        assert contract["basis_cents"] is None
        assert contract["gross_unit_price_cents"] is None
        assert contract["unpriced_bushels"] == pytest.approx(20000.00, abs=0.01)
        assert contract["hedge_lots_assigned"] == 4
        assert contract["created_by_user_id"] == "u-merch-1"
        assert contract["rolled_from_contract_id"] is None
        assert contract["pricing_locked"] is False
        assert_contract_pricing_invariants(contract)

    def test_twelve_thousand_five_hundred_bushels_reserves_three_lots(self, api):
        """PRD §3.4: "`hedge_lots_assigned` is the contract's `bushels` divided by
        5,000 bushels per lot, rounded half-up to a whole number of lots — so 12,500
        bushels, which is two and a half lots, reserves three."
        PRD §3.3: "`lots_available` on any position is simply its open lots less its
        committed lots."

        Design: Corner/calculations/hedge_lots_round_half_up_at_the_exact_half_lot
        """
        floor = setup_trading_floor(desk_code="CD19", desk_name="Corner Desk 19",
                                    with_schedule=False, lots_open=3)

        contract = new_contract(
            floor["bid"]["id"], floor["position"]["id"],
            contract_type="CASH", bushels=12500, seller_name="Bell Farms",
            futures_price_cents=448,
        )
        assert contract["hedge_lots_assigned"] == 3, (
            f"12,500 bushels is two and a half lots and must reserve three, got "
            f"{contract['hedge_lots_assigned']}"
        )

        position = read_position(floor["position"]["id"])
        assert position["lots_committed"] == 3
        assert position["lots_available"] == 0
        assert read_desk(floor["desk"]["id"])["committed_hedge_lots"] == 3

    def test_the_create_response_already_carries_the_hedge_commitment(self, api):
        """PRD §3.4: "A successful strike commits the assigned lots on the hedge
        position and recomputes, in one pass, the bid's `contracted_bushels`, the
        elevator's `committed_intake_bushels`, and the desk's
        `committed_hedge_lots`, `open_bushel_commitment` and `unpriced_bushels`."
        PRD §3.4: "a `CASH` contract is born with both `priced_futures_bushels` and
        `priced_basis_bushels` equal to its `bushels` and a `pricing_status` of
        `FULLY_PRICED`"

        Design: Corner/consistency_model/contract_create_response_already_reflects_the_hedge_commitment
        """
        floor = setup_trading_floor(desk_code="CD54", desk_name="Corner Desk 54",
                                    with_schedule=False, lots_open=10)

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"],
            contract_type="CASH", bushels=20000, seller_name="Bell Farms",
            futures_price_cents=448,
        )
        contract = validate_success(api.create_purchase_contract(payload, MERCH), 201)

        assert contract["hedge_lots_assigned"] == 4, (
            "the 201 body already reflects the commitment, with no intervening call"
        )
        assert contract["gross_unit_price_cents"] == pytest.approx(416, abs=0.0001)
        assert contract["pricing_status"] == "FULLY_PRICED"

        position = read_position(floor["position"]["id"])
        assert position["lots_committed"] == 4
        assert position["lots_available"] == 6

        desk = read_desk(floor["desk"]["id"])
        assert desk["committed_hedge_lots"] == 4
        assert desk["open_bushel_commitment"] == pytest.approx(20000.00, abs=0.01)
        assert read_location(floor["location"]["id"])[
            "committed_intake_bushels"] == pytest.approx(20000.00, abs=0.01)
        assert read_bid(floor["bid"]["id"])["contracted_bushels"] == pytest.approx(
            20000.00, abs=0.01
        )

    def test_an_unresolvable_bid_id_in_the_body_is_a_not_found(self, api):
        """PRD §2.8: "Every foreign-key id in the request body resolves to a stored
        row, checked in the order the fields appear in the endpoint's input list,
        yielding `ERR_TRADING_DESK_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`,
        `ERR_BID_NOT_FOUND`, `ERR_HEDGE_POSITION_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_RAIL_FLEET_NOT_FOUND` or
        `ERR_FREIGHT_BOOKING_NOT_FOUND` at HTTP 404."

        Design: Corner/entities/create_purchase_contract_with_unknown_bid_id_returns_not_found
        """
        desk = new_desk(desk_code="CD09", name="Corner Desk 9")
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=10, avg_entry_price_cents=448,
        )

        payload = create_purchase_contract_payload(
            UNKNOWN_UUID, position["id"], contract_type="CASH", bushels=10000,
            seller_name="Bell Farms", futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_BID_NOT_FOUND.value, 404)
        assert read_position(position["id"])["lots_committed"] == 0

    def test_contracts_are_reachable_through_the_hedge_position_filter(self, api):
        """PRD §3.9: "purchase contracts by `bid_id`, `desk_id`, `location_id`,
        `hedge_position_id`, `rolled_from_contract_id` and `status`; delivery
        tickets by `contract_id`, `location_id`, `freight_booking_id`,
        `discount_schedule_id` and `status`; and freight bookings by `fleet_id`,
        `contract_id` and `status`."
        PRD §3.4: "The contract's `desk_id` and `location_id` are taken from the
        bid's elevator, and its `commodity_code` and `futures_month` are taken from
        the bid."

        Design: Corner/entities/purchase_contract_filtered_list_resolves_every_declared_foreign_key
        """
        floor = setup_trading_floor(desk_code="CD10", desk_name="Corner Desk 10",
                                    with_schedule=False, lots_open=10)
        desk_id, location_id = floor["desk"]["id"], floor["location"]["id"]

        position_b = new_hedge_position(
            desk_id, commodity_code="CORN", futures_month="2027-03",
            side="SHORT", lots_open=10, avg_entry_price_cents=460,
        )
        bid_b = new_bid(location_id, activate=True, commodity_code="CORN",
                        futures_month="2027-03",
                        delivery_period_start="2026-11-01",
                        delivery_period_end="2026-12-31", basis_cents=-28)

        contract_a = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=10000, seller_name="Bell Farms", futures_price_cents=448,
        )
        contract_b = new_contract(
            bid_b["id"], position_b["id"], contract_type="CASH", bushels=10000,
            seller_name="Halberd Farms", delivery_start="2026-12-01",
            delivery_end="2026-12-31", futures_price_cents=460,
        )

        rows, meta = validate_paginated(api.list_purchase_contracts(
            RISK, params={"hedge_position_id": floor["position"]["id"]}
        ))
        assert meta["total_count"] == 1
        assert [r["id"] for r in rows] == [contract_a["id"]]
        assert contract_b["id"] not in [r["id"] for r in rows]

        assert contract_a["desk_id"] == desk_id
        assert contract_a["location_id"] == location_id
        assert contract_a["rolled_from_contract_id"] is None


class TestStrikeReferentialGates:

    def test_a_window_starting_before_the_bid_period_is_invalid(self, api):
        """PRD §3.4: "The requested delivery window must sit wholly inside the bid's
        posted period: the bid's `delivery_period_start` must be at or before
        `delivery_start`, `delivery_start` must be at or before `delivery_end`, and
        `delivery_end` must be at or before the bid's `delivery_period_end`."
        PRD §3.4: "Containment is on the closed interval, so a window whose
        endpoints coincide exactly with the bid's is acceptable; anything else is
        `ERR_DELIVERY_WINDOW_INVALID`."

        Design: Corner/validations/contract_delivery_window_outside_the_bid_period_returns_delivery_window_invalid
        """
        floor = setup_trading_floor(desk_code="CD30", desk_name="Corner Desk 30",
                                    with_schedule=False, lots_open=10)

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=10000, seller_name="Bell Farms",
            delivery_start="2026-09-15", delivery_end="2026-10-15",
            futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_DELIVERY_WINDOW_INVALID.value, 422)

        assert read_bid(floor["bid"]["id"])["contracted_bushels"] == pytest.approx(
            0, abs=0.01
        )
        assert read_position(floor["position"]["id"])["lots_committed"] == 0

    def test_the_bid_allowance_ceiling_is_aggregate_not_per_request(self, api):
        """PRD §3.4: "Finally, the bid's `contracted_bushels` plus the new
        contract's `bushels` must not exceed the bid's `max_bushels`, or
        `ERR_BID_MAX_BUSHELS_EXCEEDED` answers."
        PRD §3.2: "It is the sum of contracted bushels over every purchase contract
        referencing this bid whose `status` is `ACTIVE`, `SETTLED` or `ROLLED`."

        Design: Corner/validations/contract_over_the_bid_max_bushels_returns_bid_max_bushels_exceeded
        """
        floor = setup_trading_floor(desk_code="CD31", desk_name="Corner Desk 31",
                                    with_schedule=False, lots_open=10,
                                    bid_max_bushels=10000)
        first = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=6000, seller_name="Bell Farms", futures_price_cents=448,
        )
        assert read_bid(floor["bid"]["id"])["contracted_bushels"] == pytest.approx(
            6000.00, abs=0.01
        )

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=6000, seller_name="Halberd Farms", futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_BID_MAX_BUSHELS_EXCEEDED.value, 422)

        assert read_contract(first["id"])["status"] == "ACTIVE"
        _, meta = validate_paginated(api.list_purchase_contracts(
            RISK, params={"bid_id": floor["bid"]["id"]}
        ))
        assert meta["total_count"] == 1

    def test_a_position_in_the_wrong_board_month_is_a_mismatch(self, api):
        """PRD §3.4: "The position must agree with the bid on all three of desk,
        commodity and board month — the position's `desk_id` equal to the desk
        owning the bid's elevator, its `commodity_code` equal to the bid's, and its
        `futures_month` equal to the bid's — with any disagreement reported as
        `ERR_HEDGE_POSITION_MISMATCH`."

        Design: Corner/validations/hedge_position_in_the_wrong_futures_month_returns_hedge_position_mismatch
        """
        desk = new_desk(desk_code="CD32", name="Corner Desk 32")
        location = new_location(desk["id"], location_code="E1", name="One")
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2027-03",
            side="SHORT", lots_open=10, avg_entry_price_cents=456,
        )
        bid = new_bid(location["id"], activate=True, futures_month="2026-12")

        payload = create_purchase_contract_payload(
            bid["id"], position["id"], contract_type="CASH", bushels=10000,
            seller_name="Bell Farms", futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_HEDGE_POSITION_MISMATCH.value, 422)
        assert read_position(position["id"])["lots_committed"] == 0

    def test_a_position_without_enough_free_lots_refuses_the_strike(self, api):
        """PRD §3.4: "The nominated position's open lots less its committed lots
        must be at least that many, or the strike is refused with
        `ERR_INSUFFICIENT_HEDGE_LOTS`; the committed figure counts only contracts on
        that same position whose `status` is `ACTIVE`."

        Design: Corner/validations/contract_beyond_available_hedge_lots_returns_insufficient_hedge_lots
        """
        floor = setup_trading_floor(desk_code="CD35", desk_name="Corner Desk 35",
                                    with_schedule=False, lots_open=1)

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=20000, seller_name="Bell Farms", futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_INSUFFICIENT_HEDGE_LOTS.value, 422)

        position = read_position(floor["position"]["id"])
        assert position["lots_committed"] == 0
        assert position["lots_available"] == 1
        assert read_location(floor["location"]["id"])[
            "committed_intake_bushels"] == pytest.approx(0, abs=0.01)


class TestElevatorIntakeCapacity:
    """Capacity is aggregated over CLOSED delivery intervals where touching
    endpoints count as overlapping."""

    def _capacity_floor(self):
        return setup_trading_floor(
            desk_code="GD21", desk_name="Capacity Desk", with_schedule=False,
            location_code="ELV3", location_name="Ottawa Elevator",
            intake_capacity_bushels=100000, rail_served=False, lots_open=30,
        )

    def test_a_window_touching_at_a_single_date_counts_as_overlapping(self, api):
        """PRD §3.4: "The contracts already booked at the same elevator whose closed
        delivery date interval overlaps the new contract's closed interval are
        summed by contracted bushels — counting only contracts whose `status` is
        `ACTIVE` — and adding the new contract's bushels must not push that sum past
        the elevator's `intake_capacity_bushels`."
        PRD §3.4: "Overlap here is generous: two windows that merely touch at a
        single date, one ending on the day the other begins, **do** count as
        overlapping, because the same pit is receiving both loads."
        PRD §2.8: "Elevator intake capacity over overlapping delivery windows is
        not exceeded — otherwise `ERR_LOCATION_CAPACITY_EXCEEDED` (409). Applies to
        `POST /grain/purchase-contracts` and
        `POST /grain/purchase-contracts/{contractId}/roll`."

        Design: Difficulty/resource_temporal_overlap/elevator_intake_capacity_over_closed_interval_intersection
        """
        floor = self._capacity_floor()
        first = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=60000, seller_name="Bell Farms",
            delivery_start="2026-10-01", delivery_end="2026-10-31",
            futures_price_cents=448,
        )

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=45000, seller_name="Halberd Farms",
            delivery_start="2026-10-31", delivery_end="2026-11-15",
            futures_price_cents=448,
        )
        validate_error(api.create_purchase_contract(payload, MERCH),
                       ApiErrorId.ERR_LOCATION_CAPACITY_EXCEEDED.value, 409)

        assert read_contract(first["id"])["status"] == "ACTIVE"

    def test_a_window_starting_the_day_after_does_not_overlap_at_all(self, api):
        """PRD §3.4: "Overlap here is generous: two windows that merely touch at a
        single date, one ending on the day the other begins, **do** count as
        overlapping, because the same pit is receiving both loads."
        PRD §3.4: "`hedge_lots_assigned` is the contract's `bushels` divided by
        5,000 bushels per lot, rounded half-up to a whole number of lots — so 12,500
        bushels, which is two and a half lots, reserves three."

        Design: Difficulty/resource_temporal_overlap/elevator_intake_capacity_over_closed_interval_intersection
        """
        floor = self._capacity_floor()
        new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=60000, seller_name="Bell Farms",
            delivery_start="2026-10-01", delivery_end="2026-10-31",
            futures_price_cents=448,
        )

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=45000, seller_name="Halberd Farms",
            delivery_start="2026-11-01", delivery_end="2026-11-15",
            futures_price_cents=448,
        )
        accepted = validate_success(api.create_purchase_contract(payload, MERCH), 201)
        assert accepted["hedge_lots_assigned"] == 9, (
            f"45,000 bushels is nine lots, got {accepted['hedge_lots_assigned']}"
        )
        assert read_location(floor["location"]["id"])[
            "committed_intake_bushels"] == pytest.approx(105000.00, abs=0.01), (
            "committed_intake_bushels sums every ACTIVE contract at the elevator"
        )


class TestCommittedHedgeLotsAreConserved:
    """Striking a contract raises committed_hedge_lots and cancelling it must
    return the figure to exactly where it was."""

    def _lot_floor(self):
        return setup_trading_floor(desk_code="GD23", desk_name="Lot Invariant Desk",
                                   with_schedule=False, lots_open=10)

    def test_striking_a_contract_raises_the_desk_committed_lot_count(self, api):
        """PRD §2.9: "`committed_hedge_lots` is the sum of committed lots over the
        same `OPEN`-or-`MARGIN_CALL` position set, and it is the conserved quantity
        behind the contract create-and-cancel invariant: striking a contract raises
        it and cancelling that contract must return it to exactly where it was."
        PRD §3.4: "`hedge_lots_assigned` is the contract's `bushels` divided by
        5,000 bushels per lot, rounded half-up to a whole number of lots — so 12,500
        bushels, which is two and a half lots, reserves three."

        Design: Difficulty/compensating_invariant/committed_hedge_lots_conserved_by_contract_create_then_cancel
        """
        floor = self._lot_floor()
        assert read_desk(floor["desk"]["id"])["committed_hedge_lots"] == 0

        new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=25000, seller_name="Bell Farms", futures_price_cents=448,
        )

        assert read_desk(floor["desk"]["id"])["committed_hedge_lots"] == 5, (
            "25,000 bushels is five lots"
        )
        position = read_position(floor["position"]["id"])
        assert position["lots_committed"] == 5
        assert position["lots_available"] == 5

    def test_cancelling_that_contract_returns_the_lot_count_to_zero(self, api):
        """PRD §3.9: "Both release the contract's hedge lots back to its position
        and recompute the elevator's `committed_intake_bushels` alongside the desk's
        `committed_hedge_lots`, `open_bushel_commitment` and `unpriced_bushels`,
        restoring the conserved quantities to their pre-contract readings."
        PRD §3.9: "Damages are then the amount by which the market unit price
        exceeds the contract's `gross_unit_price_cents`, floored at zero so a market
        that has fallen produces exactly 0.00 rather than a credit to the seller,
        multiplied by the undelivered bushels, divided by 100, rounded half-up to 2
        decimal places — plus the variant's administrative fee, added after that
        rounding."

        Design: Difficulty/compensating_invariant/committed_hedge_lots_conserved_by_contract_create_then_cancel
        """
        floor = self._lot_floor()
        contract = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=25000, seller_name="Bell Farms", futures_price_cents=448,
        )

        cancelled = cancel_contract(
            contract["id"], damages_method="MARKET_LOSS",
            cancellation_reason="mutual unwind at flat market",
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["damages_usd"] == pytest.approx(0.00, abs=0.01), (
            "an unmarked 448-cent board against a 416-cent contract price and a "
            "-32 local basis leaves the market price equal to the contract price"
        )

        desk = read_desk(floor["desk"]["id"])
        assert desk["committed_hedge_lots"] == 0
        assert desk["open_bushel_commitment"] == pytest.approx(0, abs=0.01)

        position = read_position(floor["position"]["id"])
        assert position["lots_committed"] == 0
        assert position["lots_available"] == 10
        assert position["lots_open"] == 10, (
            "cancelling releases committed lots without closing the position"
        )
