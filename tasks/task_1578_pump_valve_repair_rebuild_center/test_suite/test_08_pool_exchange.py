"""Rotable spare pool: enrollment gating, reservation rules, the approval pool
gate, and exchange conservation at closeout."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_pool_unit,
    create_asset,
    create_customer,
    create_pool_unit,
    create_repair_order,
    drive_ro_to_quote_in_progress,
    get_customer,
    get_pool_unit,
    get_quote,
    get_repair_order,
    get_success_data,
    issue_quote_for,
    make_customer_headers,
    record_test_run,
    reserve_pool_unit,
    setup_authorized_shop,
    setup_issued_quote_shop,
    setup_pool_shop,
    validate_error,
    validate_paginated,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
TECH = TEST_USERS["technician_headers"]


class TestPoolGating:
    def test_pool_gating_violations(self, api):
        """PRD §3.1: "Under the pool program, an `IntakeCoordinator` enrolls a serialized unit by submitting the owning `customer_id` and the unit's `asset_id`; enrollment for a customer whose `pool_program` is false is rejected with `ERR_POOL_PROGRAM_REQUIRED`."
        PRD §3.1: "Reserving a unit binds it to an exchange: the coordinator names the target `repair_order_id`, and the reservation is permitted only when that repair order exists and is non-terminal, belongs to the same customer as the unit (a mismatch is rejected with `ERR_POOL_CUSTOMER_MISMATCH`), and has `exchange_requested` set (otherwise the reservation is rejected with `ERR_EXCHANGE_NOT_REQUESTED`)."

        Design: Corner/validations/pool_gating_violations
        """
        c1 = create_customer(name="Navasota", account_number="NA-470",
                             credit_limit_cents=99999999, warranty_terms_days=365,
                             pool_program=True)
        c2 = create_customer(name="Ozona", account_number="OZ-471",
                             credit_limit_cents=99999999, warranty_terms_days=365,
                             pool_program=False)
        a1 = create_asset(c1["id"], serial_number="P-4701", equipment_class="PUMP")
        a2 = create_asset(c2["id"], serial_number="P-4711", equipment_class="PUMP")
        unit = create_pool_unit(c1["id"], a1["id"])
        assert_pool_unit(unit)
        assert unit["pool_status"] == "IN_POOL"

        ro1 = create_repair_order(c1["id"], a1["id"])  # exchange_requested false
        ro2 = create_repair_order(c2["id"], a2["id"], exchange_requested=True)

        # Enrollment for a non-program customer.
        err1 = api_client.create_pool_unit(
            {"customer_id": c2["id"], "asset_id": a2["id"]}, IC)
        validate_error(err1, ApiErrorId.ERR_POOL_PROGRAM_REQUIRED)

        # Reservation against an order that did not request an exchange.
        err2 = api_client.reserve_pool_unit(unit["id"], ro1["id"], IC)
        validate_error(err2, ApiErrorId.ERR_EXCHANGE_NOT_REQUESTED)

        # Reservation across customers.
        err3 = api_client.reserve_pool_unit(unit["id"], ro2["id"], IC)
        validate_error(err3, ApiErrorId.ERR_POOL_CUSTOMER_MISMATCH)

        assert get_pool_unit(unit["id"])["pool_status"] == "IN_POOL", (
            "rejected reservations change nothing"
        )


class TestApprovalPoolGate:
    def test_approve_exchange_order_without_reserved_unit(self, api):
        """PRD §3.6: "When the order's `exchange_requested` is set, a pool unit must already stand `RESERVED` with `reserved_for_ro_id` pointing at this order, else approval is rejected with `ERR_POOL_UNIT_UNAVAILABLE`."

        Design: Corner/validations/approve_exchange_order_without_reserved_unit
        """
        shop = setup_issued_quote_shop(
            customer_over={"pool_program": True},
            ro_over={"exchange_requested": True})

        resp = api_client.approve_quote(
            shop["quote"]["id"], make_customer_headers(shop["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_POOL_UNIT_UNAVAILABLE)
        assert get_quote(shop["quote"]["id"])["status"] == "ISSUED"
        assert get_repair_order(shop["ro"]["id"])["status"] == "QUOTE_IN_PROGRESS"


class TestExchangeConservation:
    def test_close_with_exchange_issues_unit_and_replenishes_pool(self, api):
        """PRD §3.9: "Closing an order moves it `COMPLETE` → `CLOSED` and settles every open ledger at once: `closed_at` stamps the current logical clock; `invoiced_total_cents` snapshots the approved quote's `total_cents`; `repair_outcome` resolves to `FIRST_TIME_FIX` when `repair_round` is zero and `RE_REPAIR` otherwise; the order's `estimated_bay_hours` are subtracted from its window's `bay_hours_reserved`, recomputing the window's posture; and, where a pool unit stands `RESERVED` for this order, the exchange settles — the reserved unit moves `RESERVED` → `ISSUED`, and a fresh pool unit carrying this order's `customer_id` and `asset_id` is created `IN_POOL` as replenishment."
        PRD §3.1: "At onboarding the customer's `pool_available_count` starts at zero; thereafter it counts the customer's pool units whose `pool_status` is `IN_POOL` or `RESERVED` — `ISSUED` and `WITHDRAWN` units are not available — and is recomputed whenever a unit is enrolled, issued, or withdrawn."

        Design: Difficulty/compensating_invariant/pool_unit_exchange_conservation
        """
        # Pool customer; unit U1 sits on asset 1; the order repairs asset 2.
        shop = setup_pool_shop()
        unit = shop["pool_unit"]

        ro = create_repair_order(shop["customer"]["id"], shop["asset2"]["id"],
                                 failure_mode="SEAL_LEAK", exchange_requested=True,
                                 estimated_bay_hours=10)
        drive_ro_to_quote_in_progress(shop, ro)
        quote = issue_quote_for(shop)
        reserve_pool_unit(unit["id"], shop["ro"]["id"])
        get_success_data(api_client.approve_quote(
            quote["id"], make_customer_headers(shop["customer"]["id"])))
        quote = get_quote(quote["id"])

        get_success_data(api_client.start_repair(shop["ro"]["id"], TECH))
        get_success_data(api_client.submit_for_test(shop["ro"]["id"], TECH))
        record_test_run(shop["ro"]["id"])
        assert get_repair_order(shop["ro"]["id"])["status"] == "COMPLETE"

        # Before closeout the RESERVED unit still counts as available.
        assert get_customer(shop["customer"]["id"])["pool_available_count"] == 1

        closed = get_success_data(api_client.close_repair_order(shop["ro"]["id"], IC))
        assert closed["status"] == "CLOSED"
        assert closed["repair_outcome"] == "FIRST_TIME_FIX"
        assert closed["invoiced_total_cents"] == quote["total_cents"], (
            "closeout snapshots the approved quote's total"
        )

        assert get_pool_unit(unit["id"])["pool_status"] == "ISSUED"

        # Pool replenishment: a fresh unit carrying the order's customer + asset.
        data, meta = validate_paginated(api_client.list_pool_units(
            SM, params={"asset_id": shop["asset2"]["id"]}))
        assert meta["total_count"] == 1
        replenishment = data[0]
        assert replenishment["pool_status"] == "IN_POOL"
        assert replenishment["customer_id"] == shop["customer"]["id"]
        assert replenishment["id"] != unit["id"]

        # Issue (-1) paired with replenishment (+1) conserves the count.
        assert get_customer(shop["customer"]["id"])["pool_available_count"] == 1

    def test_pool_available_count_tracks_status_transitions(self, api):
        """PRD §3.1: "At onboarding the customer's `pool_available_count` starts at zero; thereafter it counts the customer's pool units whose `pool_status` is `IN_POOL` or `RESERVED` — `ISSUED` and `WITHDRAWN` units are not available — and is recomputed whenever a unit is enrolled, issued, or withdrawn."
        PRD §3.9: "A coordinator may issue a reserved unit — `RESERVED` → `ISSUED` — once its linked repair order has reached `AUTHORIZED`, `IN_REPAIR`, `IN_TEST`, `READY_FOR_CERT`, or `COMPLETE`. Issuing and withdrawing each recompute the customer's `pool_available_count`."

        Design: Difficulty/compensating_invariant/pool_unit_exchange_conservation
        """
        shop = setup_pool_shop()
        cust_id = shop["customer"]["id"]
        unit1 = shop["pool_unit"]
        assert get_customer(cust_id)["pool_available_count"] == 1

        unit2 = create_pool_unit(cust_id, shop["asset2"]["id"])
        assert get_customer(cust_id)["pool_available_count"] == 2

        # Reservation keeps the unit counted (RESERVED is available).
        ro = create_repair_order(cust_id, shop["asset2"]["id"],
                                 exchange_requested=True, estimated_bay_hours=5)
        reserve_pool_unit(unit1["id"], ro["id"])
        assert get_pool_unit(unit1["id"])["pool_status"] == "RESERVED"
        assert get_customer(cust_id)["pool_available_count"] == 2

        # The customer pulls its own second unit out of the pool.
        get_success_data(api_client.withdraw_pool_unit(
            unit2["id"], make_customer_headers(cust_id)))
        assert get_pool_unit(unit2["id"])["pool_status"] == "WITHDRAWN"
        assert get_customer(cust_id)["pool_available_count"] == 1

        # Drive the order to AUTHORIZED, then the manual issue path settles it.
        drive_ro_to_quote_in_progress(shop, ro)
        quote = issue_quote_for(shop)
        get_success_data(api_client.approve_quote(
            quote["id"], make_customer_headers(cust_id)))
        assert get_repair_order(ro["id"])["status"] == "AUTHORIZED"

        get_success_data(api_client.issue_pool_unit(unit1["id"], IC))
        assert get_pool_unit(unit1["id"])["pool_status"] == "ISSUED"
        assert get_customer(cust_id)["pool_available_count"] == 0, (
            "ISSUED and WITHDRAWN units are not available"
        )
