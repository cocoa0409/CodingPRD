"""Rolling forward and terminating: the successor contract, the two damages
variants, the grace period and the segregation-of-duties gate on cancellation."""

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    cancel_contract,
    make_merchandiser_headers,
    make_risk_officer_headers,
    mark_position,
    new_bid,
    new_contract,
    new_hedge_position,
    new_location,
    read_contract,
    read_desk,
    read_position,
    setup_contract_scenario,
    setup_default_ready,
    setup_trading_floor,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


MERCH = TEST_USERS["merchandiser_headers"]
RISK = TEST_USERS["risk_officer_headers"]


class TestRollingForward:

    def test_the_roll_retires_the_original_and_mints_a_successor(self, api):
        """PRD §3.9: "The roll retires the original and mints a successor in one
        request. The original moves `ACTIVE → ROLLED` and releases its hedge lots.
        The successor is created carrying `rolled_from_contract_id` pointing back at
        the original — the one self-referential link in the model — with `bushels`
        set to the original's `bushels` less its `delivered_bushels`,
        `futures_month` taken from the new position, and `roll_adjustment_cents` set
        to the supplied `roll_spread_cents` less a roll service fee of 2.0 cents per
        bushel that the desk charges for handling the roll."
        PRD §3.9: "Contract type, `settlement_basis`, `bid_id`, `seller_name` and
        `basis_cents` all carry across unchanged, and the successor's own
        `hedge_lots_assigned` is computed from its reduced bushel quantity and
        committed on the new position."

        Design: Corner/state_machines/contract_roll_creates_successor_and_retires_predecessor
        """
        floor = setup_trading_floor(desk_code="CD18", desk_name="Corner Desk 18",
                                    with_schedule=False, lots_open=10,
                                    avg_entry_price_cents=448)
        march_position = new_hedge_position(
            floor["desk"]["id"], commodity_code="CORN", futures_month="2027-03",
            side="SHORT", lots_open=10, avg_entry_price_cents=456,
        )
        original = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=20000, seller_name="Bell Farms", futures_price_cents=448,
        )

        successor = validate_success(api.roll_purchase_contract(
            original["id"],
            {"new_hedge_position_id": march_position["id"],
             "new_delivery_start": "2026-12-01", "new_delivery_end": "2026-12-31",
             "roll_spread_cents": 8},
            MERCH,
        ), 201)

        assert successor["rolled_from_contract_id"] == original["id"]
        assert successor["status"] == "ACTIVE"
        assert successor["bushels"] == pytest.approx(20000.00, abs=0.01)
        assert successor["roll_adjustment_cents"] == pytest.approx(6, abs=0.0001), (
            f"the 8-cent spread less the 2.0-cent roll service fee = 6, got "
            f"{successor['roll_adjustment_cents']}"
        )
        assert successor["futures_month"] == "2027-03"
        assert successor["contract_type"] == "CASH"
        assert successor["seller_name"] == "Bell Farms"
        assert successor["bid_id"] == floor["bid"]["id"]
        assert successor["basis_cents"] == pytest.approx(-32, abs=0.0001)
        assert successor["hedge_lots_assigned"] == 4

        assert read_contract(original["id"])["status"] == "ROLLED"
        assert read_position(floor["position"]["id"])["lots_committed"] == 0
        assert read_position(march_position["id"])["lots_committed"] == 4

        rows, meta = validate_paginated(api.list_purchase_contracts(
            RISK, params={"rolled_from_contract_id": original["id"]}
        ))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == successor["id"]


class TestCancellationDamagesVariants:
    """Two byte-identical contracts cancelled against the same 470-cent mark
    settle at different figures under the two damages methods."""

    def _damages_scenario(self):
        floor = setup_trading_floor(
            desk_code="GD2", desk_name="Corn Belt Desk", with_schedule=False,
            lots_open=20, avg_entry_price_cents=448,
        )
        far_location = new_location(
            floor["desk"]["id"], location_code="ELV2", name="Seneca Elevator",
            intake_capacity_bushels=5000000, rail_served=False,
        )
        new_bid(far_location["id"], activate=True, commodity_code="CORN",
                futures_month="2026-12", basis_cents=-10)

        market_loss_contract = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=50000, seller_name="Bell Farms", futures_price_cents=448,
        )
        replacement_contract = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=50000, seller_name="Halberd Farms", futures_price_cents=448,
        )
        mark_position(floor["position"]["id"], 470)

        floor["market_loss_contract"] = market_loss_contract
        floor["replacement_contract"] = replacement_contract
        return floor

    def test_market_loss_prices_damages_off_the_local_bid(self, api):
        """PRD §3.9: "Under `MARKET_LOSS` — the choice on cancel, and the only
        behaviour on default — the reference basis comes from the **local** pool:
        bids whose `status` is `ACTIVE`, whose `location_id` equals the contract's
        own `location_id`, whose `commodity_code` matches the contract's, whose
        `delivery_period_start` is at or before the contract's `delivery_end`, and
        whose `delivery_period_end` is at or after that same `delivery_end`."
        PRD §3.9: "Damages are then the amount by which the market unit price
        exceeds the contract's `gross_unit_price_cents`, floored at zero so a market
        that has fallen produces exactly 0.00 rather than a credit to the seller,
        multiplied by the undelivered bushels, divided by 100, rounded half-up to 2
        decimal places — plus the variant's administrative fee, added after that
        rounding."

        Design: Difficulty/dual_variant_calc/cancellation_damages_market_loss_vs_replacement_cost
        """
        scenario = self._damages_scenario()

        cancelled = validate_success(api.cancel_purchase_contract(
            scenario["market_loss_contract"]["id"],
            {"damages_method": "MARKET_LOSS", "cancellation_reason": "producer buyout"},
            RISK,
        ), 200)

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["damages_usd"] == pytest.approx(11000.00, abs=0.01), (
            f"(470 - 32 - 416) x 50,000 / 100 = 11,000.00 with no admin fee, got "
            f"{cancelled['damages_usd']}"
        )

    def test_replacement_cost_prices_damages_off_the_dearest_desk_wide_bid(self, api):
        """PRD §3.9: "Under `REPLACEMENT_COST` — available only on cancel — the
        reference basis comes from the **desk-wide** pool: bids whose `status` is
        `ACTIVE`, whose `commodity_code` matches the contract's, posted at any
        elevator belonging to the contract's own desk, and satisfying the same
        delivery-window containment, namely `delivery_period_start` at or before the
        contract's `delivery_end` and `delivery_period_end` at or after it."
        PRD §3.9: "This pool is ranked by `basis_cents` descending — the dearest
        basis the desk would have to pay to replace the bushels — with `created_at`
        ascending as the tie-break. An empty pool refuses the request with
        `ERR_NO_REPLACEMENT_BID`. The administrative fee under this variant is
        250.00 dollars, added to the rounded damages figure."

        Design: Difficulty/dual_variant_calc/cancellation_damages_market_loss_vs_replacement_cost
        """
        scenario = self._damages_scenario()

        cancelled = validate_success(api.cancel_purchase_contract(
            scenario["replacement_contract"]["id"],
            {"damages_method": "REPLACEMENT_COST",
             "cancellation_reason": "producer buyout"},
            RISK,
        ), 200)

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["damages_usd"] == pytest.approx(22250.00, abs=0.01), (
            f"(470 - 10 - 416) x 50,000 / 100 = 22,000.00 plus the 250.00 admin "
            f"fee = 22,250.00, got {cancelled['damages_usd']}"
        )

    def test_the_two_variants_diverge_and_both_release_their_hedge_lots(self, api):
        """PRD §3.9: "The futures reference is the `last_settlement_price_cents`
        carried on the contract's hedge position."
        PRD §3.9: "Both release the contract's hedge lots back to its position and
        recompute the elevator's `committed_intake_bushels` alongside the desk's
        `committed_hedge_lots`, `open_bushel_commitment` and `unpriced_bushels`,
        restoring the conserved quantities to their pre-contract readings."

        Design: Difficulty/dual_variant_calc/cancellation_damages_market_loss_vs_replacement_cost
        """
        scenario = self._damages_scenario()

        market_loss = cancel_contract(
            scenario["market_loss_contract"]["id"], damages_method="MARKET_LOSS",
            cancellation_reason="producer buyout",
        )
        replacement = cancel_contract(
            scenario["replacement_contract"]["id"],
            damages_method="REPLACEMENT_COST", cancellation_reason="producer buyout",
        )

        assert market_loss["damages_usd"] != replacement["damages_usd"], (
            "identical contracts must settle differently under the two variants"
        )
        assert read_position(scenario["position"]["id"])["lots_committed"] == 0
        assert read_desk(scenario["desk"]["id"])["committed_hedge_lots"] == 0


class TestSellerDefault:

    def test_default_after_the_grace_date_uses_the_market_loss_variant(self, api):
        """PRD §3.9: "Default always assesses damages under `MARKET_LOSS`; it
        accepts no choice of method."
        PRD §3.9: "Both paths write the reason text into the contract's
        `termination_reason` — `cancellation_reason` on the cancel path,
        `default_reason` on the default path — store the computed damages in
        `damages_usd`, and land the contract in `CANCELLED` or `DEFAULTED`
        respectively."
        PRD §3.9: "The administrative fee under this variant is 0.00."

        Design: Corner/calculations/declare_default_after_grace_uses_the_market_loss_variant
        """
        scenario = setup_default_ready(
            desk_code="CD24", contract_bushels=20000, settlement_price_cents=470,
            clock_to="2026-12-11T00:00:00Z",
        )

        defaulted = validate_success(api.declare_default(
            scenario["contract"]["id"],
            {"default_reason": "no bushels delivered by the grace date"},
            RISK,
        ), 200)

        assert defaulted["status"] == "DEFAULTED"
        assert defaulted["damages_usd"] == pytest.approx(4400.00, abs=0.01), (
            f"(470 - 32 - 416) x 20,000 / 100 = 4,400.00 with no admin fee, got "
            f"{defaulted['damages_usd']}"
        )
        assert defaulted["termination_reason"] == "no bushels delivered by the grace date"

        assert read_position(scenario["position"]["id"])["lots_committed"] == 0
        desk = read_desk(scenario["desk"]["id"])
        assert desk["committed_hedge_lots"] == 0
        assert desk["open_bushel_commitment"] == pytest.approx(0.00, abs=0.01)

    def test_declaring_default_before_the_grace_date_is_refused(self, api):
        """PRD §3.9: "Declaring seller default takes a `default_reason`, requires
        the contract to be `ACTIVE`, requires its delivery axis not to have reached
        `COMPLETE`, and requires that the delivery grace period have run out: the
        logical clock must be strictly after the last millisecond of the
        `delivery_end` date — that is, `23:59:59.999Z` on that date — plus a further
        10 days. A declaration made any earlier is refused with
        `ERR_GRACE_PERIOD_NOT_ELAPSED`."

        Design: Corner/validations/declaring_default_before_the_grace_date_returns_grace_period_not_elapsed
        """
        scenario = setup_contract_scenario(
            desk_code="CD27", desk_name="Corner Desk 27", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )
        advance_clock("2026-12-05T00:00:00Z")

        validate_error(api.declare_default(
            scenario["contract"]["id"], {"default_reason": "too early"}, RISK
        ), ApiErrorId.ERR_GRACE_PERIOD_NOT_ELAPSED.value, 422)

        contract = read_contract(scenario["contract"]["id"])
        assert contract["status"] == "ACTIVE"
        assert contract["damages_usd"] == pytest.approx(0, abs=0.01)
        assert read_position(scenario["position"]["id"])["lots_committed"] == 4


class TestDamagesPriceSourceAndDuties:

    def test_a_withdrawn_bid_leaves_both_damages_pools_empty(self, api):
        """PRD §3.9: "An empty pool refuses the whole request with
        `ERR_NO_MARKET_BID`. The administrative fee under this variant is 0.00."
        PRD §3.9: "In both variants only `ACTIVE` bids are eligible: a `DRAFT`,
        `SUSPENDED`, `WITHDRAWN` or `EXPIRED` bid is never a price source."
        PRD §3.9: "This pool is ranked by `basis_cents` descending — the dearest
        basis the desk would have to pay to replace the bushels — with `created_at`
        ascending as the tie-break. An empty pool refuses the request with
        `ERR_NO_REPLACEMENT_BID`. The administrative fee under this variant is
        250.00 dollars, added to the rounded damages figure."

        Design: Corner/validations/cancelling_with_market_loss_and_no_active_bid_returns_no_market_bid
        """
        scenario = setup_contract_scenario(
            desk_code="CD28", desk_name="Corner Desk 28", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )
        validate_success(api.withdraw_bid(scenario["bid"]["id"], MERCH), 200)

        validate_error(api.cancel_purchase_contract(
            scenario["contract"]["id"],
            {"damages_method": "MARKET_LOSS", "cancellation_reason": "no market"},
            RISK,
        ), ApiErrorId.ERR_NO_MARKET_BID.value, 422)

        validate_error(api.cancel_purchase_contract(
            scenario["contract"]["id"],
            {"damages_method": "REPLACEMENT_COST", "cancellation_reason": "no market"},
            RISK,
        ), ApiErrorId.ERR_NO_REPLACEMENT_BID.value, 422)

        assert read_contract(scenario["contract"]["id"])["status"] == "ACTIVE"
        assert read_position(scenario["position"]["id"])["lots_committed"] == 4

    def test_the_user_who_struck_the_contract_may_not_cancel_it(self, api):
        """PRD §3.9: "Mutual cancellation takes a `damages_method` of either
        `MARKET_LOSS` or `REPLACEMENT_COST` together with a `cancellation_reason`,
        requires the contract to be `ACTIVE`, and — this is the segregation of
        duties the role split exists for — requires that the acting `X-User-ID`
        differ from the contract's `created_by_user_id`; a `RiskOfficer` cancelling
        a contract they themselves struck is refused with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.1: "Only one of those recorded values is ever compared against a
        caller: the contract's `created_by_user_id`, at cancellation time, where a
        match means the same person is cancelling what they wrote and the request is
        refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/cancelling_as_the_creating_user_returns_segregation_of_duties
        """
        scenario = setup_contract_scenario(
            desk_code="CD40", desk_name="Corner Desk 40", with_schedule=False,
            lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
            contract_headers=make_merchandiser_headers("u-dual-1"),
        )
        contract_id = scenario["contract"]["id"]
        assert scenario["contract"]["created_by_user_id"] == "u-dual-1"

        validate_error(api.cancel_purchase_contract(
            contract_id,
            {"damages_method": "MARKET_LOSS",
             "cancellation_reason": "self-approved unwind"},
            make_risk_officer_headers("u-dual-1"),
        ), ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        assert read_contract(contract_id)["status"] == "ACTIVE"

        cancelled = validate_success(api.cancel_purchase_contract(
            contract_id,
            {"damages_method": "MARKET_LOSS",
             "cancellation_reason": "independent unwind"},
            make_risk_officer_headers("u-risk-1"),
        ), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["damages_usd"] == pytest.approx(0.00, abs=0.01), (
            "an unmarked board leaves the market unit price equal to the contract "
            "price, so the floored difference is exactly zero"
        )
