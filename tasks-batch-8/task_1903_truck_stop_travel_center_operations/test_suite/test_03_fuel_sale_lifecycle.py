"""Fuel-sale lifecycle: parallel status dimensions, invalid transitions,
loyalty accrual rounding, validation ordering, and network retirement."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_fuel_sale_payload,
    create_store_sale_payload,
    setup_enrolled_member,
    setup_fuel_site,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.fixtures import (
    CASH_1,
    GM,
    SM_2,
    authorize_retail_sale,
    create_member,
    create_parking_space,
    create_stock_item,
    create_vendor,
    dispensing_complete,
    dispensing_start,
    finalize_fuel_sale,
    finalize_sale,
    pay_sale_cash,
    reload_member,
    reload_pump,
    reload_shift,
    void_sale,
)


def _setup_member_sale(redeem=200, max_gallons=40.0):
    ctx = setup_fuel_site("Site F", diesel_cents=385, clock=TEST_CLOCK_ISO)
    env = setup_enrolled_member(points=9000)
    sale = authorize_retail_sale(
        ctx, member_id=env.member["id"], redeem_points=redeem,
        max_gallons=max_gallons,
    )
    return ctx, env, sale


class TestParallelStatusDimensions:
    def test_pay_before_complete_and_re_dispense_rejected(self, api):
        """PRD section 3.2: "Payment requires the sale to be `COMPLETED`
        first, and a cash payment requires the sale's attribution shift to
        still be `OPEN`."
        PRD section 2.10: "the generic rule that the target entity must be in
        a state from which the requested transition exists fails with
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Difficulty/non_linear_state_machine/fuel_sale_parallel_status_dimensions
        """
        _, _, sale = _setup_member_sale()

        early_pay = api.fuel_sale_pay(sale["id"], {"tender_type": "CASH"}, CASH_1)
        validate_error(early_pay, ApiErrorId.ERR_INVALID_STATE)

        dispensing_start(sale["id"])
        dispensing_complete(sale["id"], 38.0)
        finalized = finalize_sale(sale["id"])
        assert finalized["status"] == "COMPLETED"
        assert finalized["payment_status"] == "UNPAID", (
            "status and payment_status evolve independently"
        )

        re_dispense = api.fuel_sale_dispensing_start(sale["id"], CASH_1)
        validate_error(re_dispense, ApiErrorId.ERR_INVALID_STATE)

    def test_paid_completed_sale_refund_void_reverses_cash_and_points(self, api):
        """PRD section 3.2: "With tender `CASH` or `CARD` it becomes `PAID`"
        and "Cash moves the shift ledger: `expected_cash_cents` grows by
        `total_cents` and the register's posture is recomputed".
        PRD section 3.2: "Voiding a `COMPLETED` sale is a refund-void: when
        payment was `PAID` or `BILLED` it becomes `REFUNDED` (an `UNPAID`
        completed sale stays `UNPAID`); a cash-paid sale decrements the
        shift's `expected_cash_cents` by `total_cents` and recomputes
        posture" and "loyalty reverses with an `ADJUSTMENT` lot of the
        redeemed points returned, expiring 360 days out, and a negative lot of
        the earned points clawed back newest-first".

        Design: Difficulty/non_linear_state_machine/fuel_sale_parallel_status_dimensions
        """
        ctx, env, sale = _setup_member_sale()
        finalize_fuel_sale(sale["id"], 38.0)

        paid = pay_sale_cash(sale["id"])
        assert paid["payment_status"] == "PAID"
        assert paid["status"] == "COMPLETED"
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 30450

        voided = void_sale(sale["id"], "customer dispute")
        assert voided["status"] == "VOIDED"
        assert voided["payment_status"] == "REFUNDED"
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 20000

        member = reload_member(env.member["id"])
        assert member["points_balance"] == 9000, (
            "burn 200 and earn 52 at finalize, then +200 restore and -52 "
            "clawback at refund-void"
        )


class TestPerLineAccrualRounding:
    def _setup_accrual(self):
        ctx = setup_fuel_site("Site D", diesel_cents=385, clock=TEST_CLOCK_ISO)
        env = setup_enrolled_member(points=0, full_name="Driver M",
                                    email="m@x.com")
        item_a = create_stock_item(
            ctx.site["id"], sku="SNACK-A", name="Snack A", category="RETAIL",
            unit_price_cents=999, reorder_point=5, initial_on_hand_quantity=50,
        )
        item_b = create_stock_item(
            ctx.site["id"], sku="DRINK-B", name="Drink B", category="RETAIL",
            unit_price_cents=150, reorder_point=5, initial_on_hand_quantity=50,
        )
        sale = authorize_retail_sale(
            ctx, member_id=env.member["id"], redeem_points=0, max_gallons=40.0
        )
        finalized = finalize_fuel_sale(sale["id"], 38.0)
        store = validate_success(
            api_client.create_store_sale(
                ctx.site["id"],
                create_store_sale_payload(
                    ctx.shift["id"],
                    [{"stock_item_id": item_a["id"], "quantity": 1},
                     {"stock_item_id": item_b["id"], "quantity": 1}],
                    tender_type="CASH",
                    loyalty_member_id=env.member["id"],
                ),
                CASH_1,
            ),
            201,
        )
        return ctx, env, finalized, store, item_a, item_b

    def test_fuel_and_store_accrual_round_per_line(self, api):
        """PRD section 2.9: "each activity rounds its own points independently
        — fuel accrues half a point per dollar, while store sales, services,
        and parking each accrue one full point per dollar — and summing
        unrounded dollar amounts across sources and rounding once is
        expressly forbidden, because it produces different totals."

        Design: Difficulty/combinatorial_formula/loyalty_accrual_per_line_rounding
        """
        _, _, finalized, store, _, _ = self._setup_accrual()
        assert finalized["total_cents"] == 14250  # (385 - 10) x 38.000
        assert finalized["points_earned"] == 71   # round_half_up(71.25)
        assert store["total_cents"] == 1149
        assert store["points_earned"] == 11       # round_half_up(11.49)

    def test_member_balance_sums_per_line_points(self, api):
        """PRD section 2.9: "A member's `points_balance` is always the sum of
        `remaining_points` across lots whose `expires_at` is strictly later
        than the current logical clock; it is recomputed after every grant,
        burn, and clawback."
        PRD section 3.6: "then stock is decremented and `is_low_stock`
        recomputed".

        Design: Difficulty/combinatorial_formula/loyalty_accrual_per_line_rounding
        """
        from test_helpers.fixtures import reload_stock_item

        _, env, _, _, item_a, item_b = self._setup_accrual()
        member = reload_member(env.member["id"])
        assert member["points_balance"] == 82, (
            "71 + 11 per-line; sum-then-round of 82.74 would give 83"
        )
        assert reload_stock_item(item_a["id"])["on_hand_quantity"] == 49
        assert reload_stock_item(item_b["id"])["on_hand_quantity"] == 49


class TestValidationOrdering:
    def test_dual_failure_returns_pump_not_available(self, api):
        """PRD section 3.2: "Authorization enforces its checks in a fixed
        order, and the order decides which error a multiply-broken request
        surfaces. State guards run first: the pump must be `IDLE` and must
        serve the requested `fuel_type`, else `ERR_PUMP_NOT_AVAILABLE`
        (HTTP 409)" and "The fiscal guards evaluate last, after price
        existence: the member's redeemable balance must cover
        `requested_redeem_points` (`ERR_NO_POINTS`)".

        Design: Difficulty/priority_pair_validation_conflict/pump_state_beats_points_fiscal
        """
        ctx = setup_fuel_site("Site J", diesel_cents=385, clock=TEST_CLOCK_ISO)
        env = setup_enrolled_member(points=9000)
        sale1 = authorize_retail_sale(
            ctx, member_id=env.member["id"], redeem_points=100, max_gallons=10.0
        )

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="RETAIL",
            fuel_type="DIESEL", tender_type="CASH", max_gallons=10.0,
            loyalty_member_id=env.member["id"], requested_redeem_points=9500,
        )
        resp = api.create_fuel_sale(ctx.site["id"], payload, CASH_1)
        validate_error(resp, ApiErrorId.ERR_PUMP_NOT_AVAILABLE)

    def test_rejected_authorize_leaves_no_sale_and_pump_held(self, api):
        """PRD section 3.2: "The sale is born `AUTHORIZED` with
        `payment_status` `UNPAID`, and its pump cascades to `IN_USE`." — a
        rejected authorize must not create a sale nor disturb the pump held
        by the earlier one.
        PRD section 2.3: "`total_count` is the full filtered result size".

        Design: Difficulty/priority_pair_validation_conflict/pump_state_beats_points_fiscal
        """
        ctx = setup_fuel_site("Site J", diesel_cents=385, clock=TEST_CLOCK_ISO)
        env = setup_enrolled_member(points=9000)
        authorize_retail_sale(
            ctx, member_id=env.member["id"], redeem_points=100, max_gallons=10.0
        )

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="RETAIL",
            fuel_type="DIESEL", tender_type="CASH", max_gallons=10.0,
            loyalty_member_id=env.member["id"], requested_redeem_points=9500,
        )
        validate_error(
            api.create_fuel_sale(ctx.site["id"], payload, CASH_1),
            ApiErrorId.ERR_PUMP_NOT_AVAILABLE,
        )

        _, meta = validate_paginated(api.list_fuel_sales(ctx.site["id"], GM))
        assert meta["total_count"] == 1
        assert reload_pump(ctx.pumps[0]["id"])["status"] == "IN_USE"


class TestFuelSaleStateRules:
    def test_initial_states_on_create(self, api):
        """PRD section 3.3: "It is born `PENDING` with
        `volume_delivered_gallons` at zero".
        PRD section 3.6: "Purchasing runs on `PurchaseOrder` records created
        in `DRAFT`".
        PRD section 3.5: "The ticket is born `QUEUED` and `UNPAID`" and
        "`queue_position` is one plus the current maximum `queue_position`
        among all tickets ever created at this site for this service type".

        Design: Corner/state_machines/sm_initial_states_on_create
        """
        from test_helpers.fixtures import (
            create_contract,
            create_fleet,
            create_service_ticket,
            setup_contract_site,
        )

        ctx = setup_contract_site("Site S1", clock=TEST_CLOCK_ISO)
        fleet = create_fleet("Fleet A", 50_000_000, "T1")
        contract = create_contract(fleet["id"], "C-1", "T1", 0.0)
        assert contract["status"] == "PENDING"

        vendor = create_vendor(ctx.site["id"], "Parts R Us", "GENERAL")
        po = validate_success(
            api.create_purchase_order(
                ctx.site["id"],
                {"vendor_id": vendor["id"],
                 "lines": [{"sku": "FILTER-X", "quantity": 5,
                            "unit_price_cents": 3000}]},
                GM,
            ),
            201,
        )
        assert po["status"] == "DRAFT"

        ticket = create_service_ticket(ctx.site["id"], "LAUNDRY",
                                       shift_id=ctx.shift["id"])
        assert ticket["status"] == "QUEUED"
        assert ticket["payment_status"] == "UNPAID"
        assert ticket["queue_position"] == 1

    def test_finalize_from_authorized_rejected(self, api):
        """PRD section 3.2: "Finalization moves the sale `PENDING_FINALIZE →
        COMPLETED`."
        PRD section 2.10: "the generic rule that the target entity must be in
        a state from which the requested transition exists fails with
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/sm_finalize_from_authorized_invalid
        """
        ctx = setup_fuel_site("Site S2", diesel_cents=385, clock=TEST_CLOCK_ISO)
        sale = authorize_retail_sale(ctx, max_gallons=10.0)

        resp = api.fuel_sale_finalize(sale["id"], CASH_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        sale_now = validate_success(api.get_fuel_sale(sale["id"], CASH_1))
        assert sale_now["status"] == "AUTHORIZED"

    def test_void_fueling_sale_frees_pump_without_reversals(self, api):
        """PRD section 3.2: "Voiding a live but unfinished sale — from
        `AUTHORIZED`, `FUELING`, or `PENDING_FINALIZE` — requires
        `payment_status` `UNPAID` and simply moves the sale to `VOIDED`,
        freeing the pump if it is still held; no money or points ever moved,
        so nothing reverses."

        Design: Corner/state_machines/sm_void_from_fueling_frees_pump
        """
        ctx, env, sale = _setup_member_sale()
        dispensing_start(sale["id"])
        assert reload_pump(ctx.pumps[0]["id"])["status"] == "IN_USE"

        voided = void_sale(sale["id"], "customer drove off")
        assert voided["status"] == "VOIDED"
        assert voided["payment_status"] == "UNPAID"
        assert reload_pump(ctx.pumps[0]["id"])["status"] == "IDLE"
        assert reload_shift(ctx.shift["id"])["expected_cash_cents"] == 20000
        assert reload_member(env.member["id"])["points_balance"] == 9000


class TestNetworkRetireCascade:
    def test_network_retire_cascades_and_drops_discount(self, api):
        """PRD section 3.4: "Retirement moves it `ACTIVE → RETIRED` and
        cascades every enrollment of the network in `PENDING`, `ACTIVE`, or
        `SUSPENDED` to `RETIRED`; a retired network no longer contributes
        discounts to any retail quote."
        PRD section 3.2: "pinned as `network_discount_snapshot`, or zero when
        nothing qualifies".

        Design: Corner/state_machines/sm_network_retire_cascades_enrollments
        """
        from test_helpers.fixtures import (
            create_active_network,
            enroll_member,
            reload_network,
        )

        ctx = setup_fuel_site("Site S7", diesel_cents=385, clock=TEST_CLOCK_ISO)
        member_a = create_member(points=0, full_name="Driver A", email="a@x.com")
        member_b = create_member(points=0, full_name="Driver B", email="b@x.com")
        network = create_active_network("FleetPass", 0.10, ("DIESEL",), 5)
        enroll_member(member_a["id"], network["id"], activate=True)
        enroll_member(member_b["id"], network["id"], activate=False)

        retired = validate_success(api.network_retire(network["id"], GM))
        assert retired["status"] == "RETIRED"

        rows, meta = validate_paginated(
            api.list_network_enrollments(network["id"], GM)
        )
        assert meta["total_count"] == 2
        assert {row["status"] for row in rows} == {"RETIRED"}

        sale = authorize_retail_sale(
            ctx, member_id=member_a["id"], max_gallons=10.0
        )
        assert sale["authorized_quote_cents_per_gallon"] == 385
        assert sale["network_discount_snapshot"] == 0


class TestPricingModeCombos:
    def test_invalid_pricing_mode_combos(self, api):
        """PRD section 3.2: "`CONTRACT` requires both `fleet_account_id` and
        `contract_id`, `RETAIL` forbids them, and the `FLEET_BILLING` tender
        is lawful only on a `CONTRACT` sale, violations being
        `ERR_INVALID_PRICING_MODE` (HTTP 422)".

        Design: Corner/validations/validation_invalid_pricing_mode_combos
        """
        from test_helpers.fixtures import setup_fleet_with_contract

        ctx = setup_fuel_site("Site V14", diesel_cents=385,
                              clock=TEST_CLOCK_ISO, num_pumps=3)
        fc = setup_fleet_with_contract()

        missing_contract = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
            fuel_type="DIESEL", tender_type="FLEET_BILLING", max_gallons=50.0,
            fleet_account_id=fc.fleet["id"],
        )
        resp1 = api.create_fuel_sale(ctx.site["id"], missing_contract, CASH_1)
        validate_error(resp1, ApiErrorId.ERR_INVALID_PRICING_MODE)

        retail_with_contract = create_fuel_sale_payload(
            ctx.pumps[1]["id"], ctx.shift["id"], pricing_mode="RETAIL",
            fuel_type="DIESEL", tender_type="CASH", max_gallons=50.0,
            contract_id=fc.contract["id"],
        )
        resp2 = api.create_fuel_sale(ctx.site["id"], retail_with_contract, CASH_1)
        validate_error(resp2, ApiErrorId.ERR_INVALID_PRICING_MODE)

        retail_fleet_billing = create_fuel_sale_payload(
            ctx.pumps[2]["id"], ctx.shift["id"], pricing_mode="RETAIL",
            fuel_type="DIESEL", tender_type="FLEET_BILLING", max_gallons=50.0,
        )
        resp3 = api.create_fuel_sale(ctx.site["id"], retail_fleet_billing, CASH_1)
        validate_error(resp3, ApiErrorId.ERR_INVALID_PRICING_MODE)
