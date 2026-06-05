"""Difficulty Rule 2 — combinatorial_formula.

Two complex formulas with branching/rounding semantics PRD pins explicitly:
final_copay's four-input branching, and renewal_premium's per-item surcharge
whose rounding ORDER (round-each-item then sum) PRD calls out as load-bearing.
"""
from test_helpers import (
    get_success_data,
    set_clock,
    tick_clock,
    create_default_package,
    register_customer,
    create_pending_contract,
    activate_contract,
    file_claim,
    assess_claim,
    dispatch_claim,
    resolve_claim,
    get_dispatch_for_claim,
    start_dispatch,
    complete_dispatch,
    make_customer_headers,
    make_admin_headers,
    setup_active_contract,
    create_covered_item_payload,
    renew_contract_payload,
)


_ADMIN = make_admin_headers()


class TestFinalCopayFourInputNonlinearBranching:
    """First visit + over cap: final_copay = SF + round_half_up((R-C)*P). With
    R=30000, C=25000, P=0.20, SF=7500 → 7500 + 1000 = 8500. PRD §3.7."""

    def test_first_visit_over_cap_combines_service_fee_and_share(self, api):
        """PRD §3.7: "First visit, over cap. When `is_return_visit` is false and the
        actual repair amount exceeds `copay_cap_cents`, the final co-pay equals the
        package's `service_fee_cents` plus the rounded share of the excess."

        Design: Difficulty/combinatorial_formula/final_copay_four_input_nonlinear_branching
        """
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(
            code="PREM",
            annual_premium_cents=60_000,
            service_fee_cents=7_500,
            copay_cap_cents=25_000,
            copay_share_pct=0.20,
            return_visit_window_days=30,
            max_covered_items=5,
        )
        customer = register_customer(email="carol-cf@example.com")
        pending = create_pending_contract(customer, package)
        contract = activate_contract(pending)
        cust_h = make_customer_headers(customer["id"])
        item = get_success_data(api.create_covered_item(
            create_covered_item_payload(
                contract["id"], category="REFRIGERATOR",
                brand="Whirlpool", model="WRF555", install_year=2023,
            ),
            cust_h,
        ))
        claim = file_claim(contract, customer, item, issue="Compressor failure")
        assess_claim(claim, 30_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatched = dispatch_claim(claim, "tech-A", "2026-02-01T09:00:00Z")
        # First visit (no prior completion) → is_return_visit false, SF pinned to 7500.
        assert dispatched["is_return_visit"] is False
        assert dispatched["service_fee_charged_cents"] == 7500

        d = get_dispatch_for_claim(dispatched["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d)
        resolved = resolve_claim(claim, 30_000)
        # final = 7500 + round_half_up((30000 - 25000) * 0.20) = 7500 + 1000 = 8500.
        assert resolved["final_copay_cents"] == 8500

    def test_first_visit_over_cap_excess_share_added_to_trip_charge(self, api):
        """PRD §3.7: "Multiply the excess by the package's `copay_share_pct` and
        round the product to the nearest cent using round half up."
        PRD §3.7: "Add the applicable Trip Charge to that figure to obtain the co-pay."

        Design: Difficulty/combinatorial_formula/final_copay_four_input_nonlinear_branching
        """
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(
            code="PREMQ",
            service_fee_cents=7_500,
            copay_cap_cents=25_000,
            copay_share_pct=0.20,
        )
        customer = register_customer(email="carol-cf2@example.com")
        pending = create_pending_contract(customer, package)
        contract = activate_contract(pending)
        cust_h = make_customer_headers(customer["id"])
        item = get_success_data(api.create_covered_item(
            create_covered_item_payload(contract["id"], category="OVEN"),
            cust_h,
        ))
        claim = file_claim(contract, customer, item)
        assess_claim(claim, 30_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(claim, "tech-B", "2026-02-01T09:00:00Z")
        d = get_dispatch_for_claim(claim["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d)
        resolved = resolve_claim(claim, 30_000)
        # Components of the assertion:
        excess = max(0, 30_000 - package["copay_cap_cents"])  # 5000
        # round_half_up of an integer*0.20 of exactly 5000 → 1000.0 → 1000
        above_cap = 1000
        expected = above_cap + package["service_fee_cents"]
        assert resolved["final_copay_cents"] == expected
        # Excess explanation: R=30000 > C=25000 confirms over_cap branch.
        assert excess > 0


class TestRenewalPremiumPerItemSurchargeRoundingOrder:
    """The pinned rounding order (round-each-item then sum) diverges from
    sum-then-round when P=12325 cents, extra_items=3:
       per_item = round_half_up(12325 * 0.02) = round_half_up(246.5) = 247
       total = 247 * 3 = 741 (pinned)
       vs. round_half_up(12325 * 0.02 * 3) = round_half_up(739.5) = 740 (rejected)
    PRD §3.8.
    """

    def test_per_item_surcharge_rounded_per_item_then_summed(self, api):
        """PRD §3.8: "The per-item surcharge is two percent of the package premium,
        rounded to the nearest cent using round half up, **rounded once per item
        before summation**."
        PRD §3.8: "Computing the un-rounded product across all items and rounding
        once at the end is not equivalent and is rejected"

        Design: Difficulty/combinatorial_formula/renewal_premium_per_item_surcharge_rounding_order
        """
        # Activate a fresh contract on 2026-01-01 → coverage_end = 2027-01-01.
        # P = 12325 cents (12325 * 0.02 = 246.5 → 247 per item).
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
            code="SURCH",
            annual_premium_cents=12_325,
            service_fee_cents=7_500,
            copay_cap_cents=25_000,
            copay_share_pct=0.20,
            return_visit_window_days=30,
            max_covered_items=10,
        )
        # Register 4 covered items → extra_items = 3.
        cust_h = make_customer_headers(customer["id"])
        for cat, model in [("HVAC", "M1"), ("WATER_HEATER", "M2"),
                           ("REFRIGERATOR", "M3"), ("DISHWASHER", "M4")]:
            get_success_data(api.create_covered_item(
                create_covered_item_payload(
                    contract["id"], category=cat, brand="B", model=model,
                    install_year=2022,
                ),
                cust_h,
            ))

        # Tick into EXPIRING_SOON at D = 20 (= early-renewal tier).
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        es = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert es["status"] == "EXPIRING_SOON"

        # Renew. Expected:
        #   base = 12325 - round_half_up(12325*0.10) = 12325 - round_half_up(1232.5) = 12325 - 1233 = 11092
        #   per_item = round_half_up(12325 * 0.02) = round_half_up(246.5) = 247
        #   surcharge = 247 * 3 = 741
        #   total = 11092 + 741 = 11833
        # The rejected "sum then round" alternative: round_half_up(12325*0.02*3) =
        # round_half_up(739.5) = 740 ⇒ 11092 + 740 = 11832.
        renewed = get_success_data(api.renew_contract(
            contract["id"],
            renew_contract_payload(es["version"]),
            cust_h,
        ))
        assert renewed["annual_premium_due_cents"] == 11_833, (
            f"per-item rounding ORDER must be round-each then sum; "
            f"got {renewed['annual_premium_due_cents']}, expected 11833 (rejected: 11832)"
        )

    def test_per_item_surcharge_is_two_percent_of_premium(self, api):
        """PRD §3.8: "The per-item surcharge is two percent of the package premium,
        rounded to the nearest cent using round half up, **rounded once per item
        before summation**."

        Design: Difficulty/combinatorial_formula/renewal_premium_per_item_surcharge_rounding_order
        """
        # Use a premium that rounds cleanly so the rounding direction can't hide a bug.
        # P = 50000 → per_item = round_half_up(50000 * 0.02) = 1000 exactly.
        # extra_items = 2 → surcharge = 2000.
        # Tick D = 20 → early renewal → base = 50000 - 5000 = 45000.
        # Total = 45000 + 2000 = 47000.
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
            code="SURCC",
            annual_premium_cents=50_000,
            max_covered_items=10,
        )
        cust_h = make_customer_headers(customer["id"])
        # 3 items total → extra_items = 2.
        for cat, model in [("HVAC", "A"), ("DRYER", "B"), ("OVEN", "C")]:
            get_success_data(api.create_covered_item(
                create_covered_item_payload(
                    contract["id"], category=cat, brand="X", model=model,
                    install_year=2022,
                ),
                cust_h,
            ))
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        es = get_success_data(api.get_contract(contract["id"], _ADMIN))
        renewed = get_success_data(api.renew_contract(
            contract["id"],
            renew_contract_payload(es["version"]),
            cust_h,
        ))
        # 45000 + 1000*2 = 47000.
        assert renewed["annual_premium_due_cents"] == 47_000
