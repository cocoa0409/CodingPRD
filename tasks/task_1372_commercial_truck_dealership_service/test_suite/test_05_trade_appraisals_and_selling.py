"""Trade appraisals (book/market variants, offer cycle) and unit selling rules
(PRD §3.4, §3.3, §2.10)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_account, create_appraisal, offer_appraisal, create_new_unit,
    create_ready_unit, create_slot_pool, create_order,
    make_fleet_customer_headers,
)

MGR = TEST_USERS["sales_manager_headers"]
CONSULTANT = TEST_USERS["sales_consultant_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _get_appraisal(appraisal_id):
    return get_success_data(api_client.get_trade_appraisal(appraisal_id, MGR))


# ---------------------------------------------------------------- Queue A ---

class TestAppraisalBookVsMarketVariants:
    def _setup(self):
        acct = create_account("FLEET", tier="GOLD", credit_limit_cents=100000000, name="HaulCo")
        appraisal = create_appraisal(acct["id"], trade_vin="1FUJA6CV42LW77412",
                                     model_year=2022, mileage=280000,
                                     condition_grade="B", base_book_value_cents=8000000)
        return acct, appraisal

    def test_book_estimate_computed_at_creation(self, api):
        """PRD §3.4: "the vehicle's age is the clock's year minus `model_year`,
        floored at zero; the book value depreciates twelve percent per year of
        age from the base book value, never below zero; and the estimate
        subtracts a mileage penalty of 5 cents for every mile beyond the first
        150,000 free miles, rounded half-up to integer cents and floored at
        zero."

        Design: Difficulty/dual_variant_calc/appraisal_book_estimate_vs_market_acv_offer
        """
        _, appraisal = self._setup()
        # clock year 2026, age 4: 8000000 * (1 - 0.48) - (280000-150000) * 5
        assert appraisal["book_estimate_cents"] == 3510000
        assert appraisal["status"] == "DRAFT"

    def test_market_acv_computed_at_offer_and_caps_allowance(self, api):
        """PRD §3.4: "The actual cash value is the book estimate scaled by a
        condition multiplier — 1.10 for grade `A`, 1.00 for `B`, 0.85 for `C` —
        and by the market index divided by 10,000, rounded half-up to integer
        cents, and stored as `offer_acv_cents`."
        PRD §3.4: "The two allowance variants intentionally disagree for
        identical inputs — the book estimate anchors intake while only the
        market figure disciplines the offer."

        Design: Difficulty/dual_variant_calc/appraisal_book_estimate_vs_market_acv_offer
        """
        _, appraisal = self._setup()
        data = validate_success(api_client.offer_trade_appraisal(
            appraisal["id"], {"market_index_bp": 10800, "offered_allowance_cents": 3700000},
            MGR), 200)
        # round_half_up(3510000 * 1.00 * 10800/10000)
        assert data["offer_acv_cents"] == 3790800
        assert data["offer_acv_cents"] != data["book_estimate_cents"]
        assert data["status"] == "OFFERED"
        assert data["offered_allowance_cents"] == 3700000


class TestAppraisalCounterOfferCycle:
    def _setup(self):
        acct = create_account("FLEET", credit_limit_cents=50000000, name="CycleFleet")
        appraisal = create_appraisal(acct["id"], trade_vin="3AKJHHDR5LSMW4451",
                                     model_year=2024, mileage=100000,
                                     condition_grade="B", base_book_value_cents=5000000)
        offer_appraisal(appraisal["id"], market_index_bp=10000,
                        offered_allowance_cents=3500000)
        return acct, appraisal

    def test_counter_moves_to_negotiating(self, api):
        """PRD §3.4: "Countering moves the appraisal to `NEGOTIATING`, from
        which the manager may issue a fresh offer under the same ceiling rule."

        Design: Difficulty/non_linear_state_machine/trade_appraisal_counter_offer_cycle
        """
        acct, appraisal = self._setup()
        data = validate_success(api_client.counter_trade_appraisal(
            appraisal["id"], make_fleet_customer_headers(acct["id"])), 200)
        assert data["status"] == "NEGOTIATING"

    def test_reoffer_recomputes_acv_and_increments_round(self, api):
        """PRD §3.4: "A successful offer moves the appraisal to `OFFERED`,
        stores the allowance, stamps `offer_expires_at` ten days out, and
        increments `offer_round` by one."
        PRD §3.4: "The actual cash value is the book estimate scaled by a
        condition multiplier — 1.10 for grade `A`, 1.00 for `B`, 0.85 for `C` —
        and by the market index divided by 10,000".

        Design: Difficulty/non_linear_state_machine/trade_appraisal_counter_offer_cycle
        """
        acct, appraisal = self._setup()
        api_client.counter_trade_appraisal(
            appraisal["id"], make_fleet_customer_headers(acct["id"]))
        data = validate_success(api_client.offer_trade_appraisal(
            appraisal["id"], {"market_index_bp": 10200, "offered_allowance_cents": 3800000},
            MGR), 200)
        assert data["status"] == "OFFERED"
        assert data["offer_round"] == 2
        # book estimate 3800000 * 1.00 * 1.02
        assert data["offer_acv_cents"] == 3876000
        assert data["offered_allowance_cents"] == 3800000


class TestSellRequiresAcceptedAppraisal:
    def _setup(self):
        unit = create_ready_unit(vin="1FUJGBDV1CLW88324")
        buyer = create_account("FLEET", credit_limit_cents=50000000, name="BuyerCo")
        appraisal = create_appraisal(buyer["id"], trade_vin="3AKJHHDR5LSMW4452",
                                     model_year=2023, mileage=120000,
                                     condition_grade="B", base_book_value_cents=6000000)
        offer_appraisal(appraisal["id"], market_index_bp=10000,
                        offered_allowance_cents=3800000)
        return unit, buyer, appraisal

    def test_offered_appraisal_blocks_sell(self, api):
        """PRD §3.3: "When a trade appraisal is referenced it must be
        `ACCEPTED` and belong to the buyer, otherwise `ERR_APPRAISAL_STATE`."

        Design: Difficulty/cross_entity_state_dependency/sell_requires_accepted_trade_appraisal
        """
        unit, buyer, appraisal = self._setup()
        resp = api_client.sell_unit(unit["id"], {
            "customer_account_id": buyer["id"], "sale_price_cents": 12000000,
            "trade_appraisal_id": appraisal["id"]}, CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_STATE)
        assert get_success_data(api_client.get_unit(unit["id"], CONTROLLER))["status"] == "READY"
        assert _get_appraisal(appraisal["id"])["status"] == "OFFERED"

    def test_accepted_appraisal_is_consumed_at_sell(self, api):
        """PRD §3.3: "On success the system first brings floor-plan interest
        current with an `INTEREST_ACCRUAL` entry through the clock date
        (floor-plan units only), then posts a `PAYOFF` entry of the negative
        balance, driving `floorplan_balance_cents` to zero; `sold_price_cents`
        and `sold_at` are set, the unit becomes `SOLD`, and a referenced
        appraisal is consumed to `CONSUMED`."

        Design: Difficulty/cross_entity_state_dependency/sell_requires_accepted_trade_appraisal
        """
        unit, buyer, appraisal = self._setup()
        accepted = validate_success(api_client.accept_trade_appraisal(
            appraisal["id"], make_fleet_customer_headers(buyer["id"])), 200)
        assert accepted["status"] == "ACCEPTED"
        data = validate_success(api_client.sell_unit(unit["id"], {
            "customer_account_id": buyer["id"], "sale_price_cents": 12000000,
            "trade_appraisal_id": appraisal["id"]}, CONSULTANT), 200)
        assert data["status"] == "SOLD"
        assert data["floorplan_balance_cents"] == 0
        assert data["sold_price_cents"] == 12000000
        assert _get_appraisal(appraisal["id"])["status"] == "CONSUMED"


class TestSellStateErrorOutranksCreditHold:
    def _make_held_buyer(self):
        buyer = create_account("FLEET", credit_limit_cents=50000, name="HoldCo")
        validate_success(api_client.patch_customer_account(
            buyer["id"], {"status": "CREDIT_HOLD",
                          "expected_customer_account_version": buyer["version"]}, MGR), 200)
        return buyer

    def test_not_ready_unit_wins_over_credit_hold(self, api):
        """PRD §2.10(7): "Target-entity state permitting the transition — the
        domain state errors at 409."
        PRD §2.10(20): "Fiscal posture at sale and invoicing —
        `ERR_CREDIT_LIMIT_EXCEEDED` (402) / `ERR_ACCOUNT_ON_CREDIT_HOLD` (409)."
        PRD §2.10: "When a request fails several rules, the first failing check
        by the following fixed priority determines the error returned".

        Design: Difficulty/priority_pair_validation_conflict/sell_rejected_state_error_outranks_credit_hold_fiscal
        """
        unit = create_new_unit(vin="1FUJGBDV1CLW88322")  # IN_STOCK, never inspected
        buyer = self._make_held_buyer()
        resp = api_client.sell_unit(unit["id"], {
            "customer_account_id": buyer["id"], "sale_price_cents": 12000000}, CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_SELLABLE)
        unit_after = get_success_data(api_client.get_unit(unit["id"], CONTROLLER))
        assert unit_after["status"] == "IN_STOCK"
        entries, _ = validate_paginated(api_client.list_floor_plan_entries(unit["id"], CONTROLLER))
        assert all(e["entry_type"] != "PAYOFF" for e in entries)

    def test_credit_hold_buyer_rejected_in_isolation(self, api):
        """PRD §3.3: "The buyer's account must be `ACTIVE`; a `CREDIT_HOLD` or
        `CLOSED` buyer is rejected with `ERR_ACCOUNT_ON_CREDIT_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/sell_rejected_state_error_outranks_credit_hold_fiscal
        """
        unit = create_ready_unit(vin="1FUJGBDV1CLW88322")
        buyer = self._make_held_buyer()
        resp = api_client.sell_unit(unit["id"], {
            "customer_account_id": buyer["id"], "sale_price_cents": 12000000}, CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_CREDIT_HOLD)
        assert get_success_data(api_client.get_unit(unit["id"], CONTROLLER))["status"] == "READY"


# ---------------------------------------------------------------- Queue B ---

def test_appraisal_accept_creates_used_unit_in_reconditioning(api):
    """PRD §3.4: "Accepting requires the clock still be before
    `offer_expires_at` and produces the dealership's newest used unit: a `Unit`
    with `unit_kind` `USED`, status `RECONDITIONING` (it must pass inspection
    before sale), `vin` equal to `trade_vin`, `invoice_cost_cents` equal to
    `offered_allowance_cents`, `stocking_date` the clock date,
    `floorplan_active` false, and `trade_appraisal_id` linking back; the
    appraisal's `created_unit_id` records it."

    Design: Corner/state_machines/appraisal_accept_creates_used_unit_in_reconditioning
    """
    acct = create_account("FLEET", credit_limit_cents=50000000, name="TradeCo")
    appraisal = create_appraisal(acct["id"], trade_vin="3AKJHHDR5LSMW4454",
                                 model_year=2023, mileage=120000,
                                 condition_grade="B", base_book_value_cents=6000000)
    offer_appraisal(appraisal["id"], market_index_bp=10000, offered_allowance_cents=3800000)
    data = validate_success(api_client.accept_trade_appraisal(
        appraisal["id"], make_fleet_customer_headers(acct["id"])), 200)
    assert data["status"] == "ACCEPTED"
    assert data["created_unit_id"]
    units, meta = validate_paginated(api_client.list_units(
        MGR, params={"trade_appraisal_id": appraisal["id"]}))
    assert meta["total_count"] == 1
    unit = units[0]
    assert unit["unit_kind"] == "USED"
    assert unit["status"] == "RECONDITIONING"
    assert unit["invoice_cost_cents"] == 3800000
    assert unit["floorplan_active"] is False
    assert unit["floorplan_balance_cents"] == 0
    assert unit["vin"] == "3AKJHHDR5LSMW4454"


def test_fleet_customer_cannot_act_on_other_accounts_appraisal(api):
    """PRD §3.4: "these three actions belong to the `FleetCustomer` whose
    identity matches the appraisal's `customer_account_id`; anyone else is
    refused with `ERR_INSUFFICIENT_PERMISSIONS`".
    PRD §2.1: "When `X-User-Role` is `FleetCustomer`, `X-User-ID` is the `id`
    of the acting `CustomerAccount`; ownership checks on any resource that
    references a `CustomerAccount` compare the resource's foreign-key field to
    `X-User-ID`."

    Design: Corner/validations/fleet_customer_cannot_act_on_other_accounts_appraisal
    """
    acct_a = create_account("FLEET", credit_limit_cents=50000000, name="OwnA")
    acct_b = create_account("FLEET", credit_limit_cents=50000000, name="OwnB")
    appraisal = create_appraisal(acct_a["id"], trade_vin="3AKJHHDR5LSMW4455",
                                 model_year=2023, mileage=90000,
                                 condition_grade="A", base_book_value_cents=7000000)
    offer_appraisal(appraisal["id"], market_index_bp=10000, offered_allowance_cents=4900000)
    resp = api_client.accept_trade_appraisal(
        appraisal["id"], make_fleet_customer_headers(acct_b["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    assert _get_appraisal(appraisal["id"])["status"] == "OFFERED"


def test_offer_capped_by_market_acv(api):
    """PRD §3.4: "The offered allowance may not exceed that ceiling; an
    over-ceiling offer is rejected with `ERR_APPRAISAL_OFFER_EXCEEDS_ACV`."

    Design: Corner/validations/offer_capped_by_market_acv
    """
    acct = create_account("FLEET", credit_limit_cents=50000000, name="AcvCo")
    appraisal = create_appraisal(acct["id"], trade_vin="3AKJHHDR5LSMW4456",
                                 model_year=2023, mileage=120000,
                                 condition_grade="B", base_book_value_cents=6000000)
    # book estimate = 6000000 * (1 - 0.12*3) = 3840000; ACV at parity = 3840000
    resp = api_client.offer_trade_appraisal(
        appraisal["id"], {"market_index_bp": 10000, "offered_allowance_cents": 3840001}, MGR)
    validate_error(resp, ApiErrorId.ERR_APPRAISAL_OFFER_EXCEEDS_ACV)
    assert _get_appraisal(appraisal["id"])["status"] == "DRAFT"
    data = validate_success(api_client.offer_trade_appraisal(
        appraisal["id"], {"market_index_bp": 10000, "offered_allowance_cents": 3840000}, MGR), 200)
    assert data["status"] == "OFFERED"


def test_terminal_lockdown_cancelled_order_and_declined_appraisal(api):
    """PRD §3.2: "Committing an order — permitted to a `SalesConsultant` while
    the order is `SLOT_HELD` ... both violations surface `ERR_ORDER_STATE`" and
    "Cancelling is permitted from either `SLOT_HELD` or `COMMITTED`".
    PRD §3.4: "Declining is terminal at `DECLINED`." and "acting on an
    appraisal not in `OFFERED` is `ERR_APPRAISAL_STATE`."

    Design: Corner/state_machines/terminal_lockdown_cancelled_order_and_declined_appraisal
    """
    slot = create_slot_pool(build_month="2026-10", capacity=3)
    acct = create_account("FLEET", credit_limit_cents=50000000, name="TermCo")
    order = create_order(slot["id"], account_id=acct["id"])
    api_client.cancel_factory_order(order["id"], CONSULTANT)

    appraisal = create_appraisal(acct["id"], trade_vin="3AKJHHDR5LSMW4453",
                                 model_year=2023, mileage=90000,
                                 condition_grade="A", base_book_value_cents=7000000)
    offer_appraisal(appraisal["id"], market_index_bp=10000, offered_allowance_cents=4900000)
    api_client.decline_trade_appraisal(
        appraisal["id"], make_fleet_customer_headers(acct["id"]))

    validate_error(api_client.commit_factory_order(order["id"], CONSULTANT),
                   ApiErrorId.ERR_ORDER_STATE)
    validate_error(api_client.cancel_factory_order(order["id"], CONSULTANT),
                   ApiErrorId.ERR_ORDER_STATE)
    validate_error(api_client.offer_trade_appraisal(
        appraisal["id"], {"market_index_bp": 10000, "offered_allowance_cents": 5000000}, MGR),
        ApiErrorId.ERR_APPRAISAL_STATE)
    validate_error(api_client.accept_trade_appraisal(
        appraisal["id"], make_fleet_customer_headers(acct["id"])),
        ApiErrorId.ERR_APPRAISAL_STATE)
