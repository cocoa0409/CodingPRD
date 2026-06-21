"""Difficulty Rule 1 — dual_variant_calc.

The same input pool (R, P, C in one instance; P, D in the other) yields two
demonstrably different numbers under two valid algorithms baked into the PRD:
provisional vs final co-pay on the same claim once the return-visit guarantee
fires, and early-renewal vs at-expiry pricing on otherwise-identical contracts.
"""
from test_helpers import (
    validate_success,
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
    make_dispatcher_headers,
    setup_active_contract,
)


_ADMIN = make_admin_headers()
_DISPATCHER = make_dispatcher_headers()


class TestCopayProvisionalVsFinalDivergeOnReturnVisit:
    """Same R = 30000 on the same claim produces different provisional and final
    co-pays because the dispatch step pins service_fee_charged_cents to 0 on a
    return visit. PRD §3.5 + §3.7."""

    def test_provisional_includes_service_fee_then_final_waives_it(self, api):
        """PRD §3.7: "The provisional co-pay always assumes the Trip Charge will apply,
        because at assessment time the return-visit evaluation has not yet happened;
        it therefore reads `service_fee_cents` directly from the package."
        PRD §3.7: "The final co-pay uses the Trip Charge that was pinned at dispatch
        — the claim's `service_fee_charged_cents`, which is zero when `is_return_visit`
        is true and equals the package's `service_fee_cents` otherwise."

        Design: Difficulty/dual_variant_calc/copay_provisional_vs_final_diverge_on_return_visit
        """
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(
            code="PLUS",
            annual_premium_cents=50_000,
            service_fee_cents=7_500,
            copay_cap_cents=25_000,
            copay_share_pct=0.20,
            return_visit_window_days=30,
            max_covered_items=5,
        )
        customer = register_customer(email="alice-cv@example.com", full_name="Alice")
        pending = create_pending_contract(customer, package)
        contract = activate_contract(pending)

        # Register a covered item (default pre_existing_flag = false).
        from test_helpers import create_covered_item_payload
        cust_h = make_customer_headers(customer["id"])
        item = get_success_data(api.create_covered_item(
            create_covered_item_payload(contract["id"], category="HVAC"),
            cust_h,
        ))

        # First claim: file → assess → dispatch → start → complete → resolve.
        claim1 = file_claim(contract, customer, item, issue="First failure")
        assess_claim(claim1, 30_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(claim1, "tech-001", "2026-02-01T09:00:00Z")
        d1 = get_dispatch_for_claim(claim1["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d1)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d1)
        resolve_claim(claim1, 30_000)

        # Second claim on the SAME item, within the 30-day return-visit window.
        set_clock("2026-02-05T12:00:00Z")
        claim2 = file_claim(contract, customer, item, issue="Same issue recurs")
        ac = assess_claim(claim2, 30_000)
        # Provisional uses package.service_fee_cents (7500), so:
        #   excess = 30000 - 25000 = 5000
        #   above_cap = round_half_up(5000 * 0.20) = 1000
        #   provisional = 1000 + 7500 = 8500
        assert ac["provisional_copay_cents"] == 8500, (
            f"provisional_copay_cents must include the service fee at ASSESSED, "
            f"got {ac['provisional_copay_cents']}"
        )

        dispatched = dispatch_claim(claim2, "tech-002", "2026-02-06T09:00:00Z")
        # Dispatch pins is_return_visit=True and service_fee_charged_cents=0.
        assert dispatched["is_return_visit"] is True
        assert dispatched["service_fee_charged_cents"] == 0

        d2 = get_dispatch_for_claim(dispatched["id"])
        set_clock("2026-02-06T09:30:00Z")
        start_dispatch(d2)
        complete_dispatch(d2)
        resolved = resolve_claim(claim2, 30_000)
        # Final reads pinned SF=0; final = 1000 + 0 = 1000.
        assert resolved["final_copay_cents"] == 1000
        # The whole point: same R, two algorithms, different result.
        assert resolved["provisional_copay_cents"] != resolved["final_copay_cents"]

    def test_provisional_and_final_diverge_by_pinned_service_fee_amount(self, api):
        """PRD §3.7: "The final co-pay uses the Trip Charge that was pinned at dispatch
        — the claim's `service_fee_charged_cents`, which is zero when `is_return_visit`
        is true and equals the package's `service_fee_cents` otherwise."

        Design: Difficulty/dual_variant_calc/copay_provisional_vs_final_diverge_on_return_visit
        """
        # Identical setup to the test above but assert on the magnitude of divergence.
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSB")
        customer = register_customer(email="alice-cv2@example.com")
        pending = create_pending_contract(customer, package)
        contract = activate_contract(pending)
        cust_h = make_customer_headers(customer["id"])
        from test_helpers import create_covered_item_payload
        item = get_success_data(api.create_covered_item(
            create_covered_item_payload(contract["id"], category="WATER_HEATER"),
            cust_h,
        ))
        # First claim, resolved → stamps last_dispatch_completed_utc.
        c1 = file_claim(contract, customer, item)
        assess_claim(c1, 30_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(c1, "techZ", "2026-02-01T09:00:00Z")
        d1 = get_dispatch_for_claim(c1["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d1)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d1)
        resolve_claim(c1, 30_000)
        # Second claim within window.
        set_clock("2026-02-05T12:00:00Z")
        c2 = file_claim(contract, customer, item, issue="Within window")
        ac = assess_claim(c2, 30_000)
        provisional = ac["provisional_copay_cents"]
        dispatched = dispatch_claim(c2, "techY", "2026-02-06T09:00:00Z")
        d2 = get_dispatch_for_claim(dispatched["id"])
        set_clock("2026-02-06T09:30:00Z")
        start_dispatch(d2)
        complete_dispatch(d2)
        resolved = resolve_claim(c2, 30_000)
        final = resolved["final_copay_cents"]
        # provisional reads package.service_fee_cents (7500); final reads pinned 0.
        # Difference = service_fee_cents.
        assert provisional - final == 7500, (
            f"provisional and final must diverge by the pinned service fee (7500); "
            f"got provisional={provisional}, final={final}"
        )


class TestRenewalPremiumEarlyVsAtExpiryDiverge:
    """Same package premium P = 50000 with zero covered items produces 45000 when
    renewed at D = 20 (early) and 50000 when renewed at D = 5 (at expiry).
    PRD §3.8."""

    def test_early_renewal_applies_ten_percent_discount(self, api):
        """PRD §3.8: "When the days-remaining figure is at least 15, the renewal is
        considered early and receives a 10% discount: the base equals the package
        premium minus ten percent of the package premium, where the ten-percent figure
        is computed by multiplying the package premium by 0.10 and rounding to the
        nearest cent using round half up."

        Design: Difficulty/dual_variant_calc/renewal_premium_early_vs_at_expiry_diverge
        """
        # Activate a contract on 2026-01-01 → coverage_end_utc = 2027-01-01.
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
            code="PLUSE", annual_premium_cents=50_000,
        )
        # No covered items registered → extra_items = 0; surcharge = 0.
        # Tick into EXPIRING_SOON at D=20.
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        es = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert es["status"] == "EXPIRING_SOON"

        from test_helpers import renew_contract_payload
        cust_h = make_customer_headers(customer["id"])
        renewed = get_success_data(api.renew_contract(
            contract["id"],
            renew_contract_payload(es["version"]),
            cust_h,
        ))
        # 50000 - round_half_up(50000 * 0.10) = 50000 - 5000 = 45000.
        assert renewed["annual_premium_due_cents"] == 45_000

    def test_at_expiry_renewal_applies_no_discount(self, api):
        """PRD §3.8: "When the days-remaining figure is at most 14, no discount applies
        and the base equals the package premium directly."

        Design: Difficulty/dual_variant_calc/renewal_premium_early_vs_at_expiry_diverge
        """
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
            code="PLUSF", annual_premium_cents=50_000,
        )
        # Tick into EXPIRING_SOON at D=20 first (only the early-tick fires the transition).
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        # Now advance to D=5 and renew (still EXPIRING_SOON until clock crosses end).
        set_clock("2026-12-27T00:00:00Z")
        tick_clock()
        es = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert es["status"] == "EXPIRING_SOON", (
            f"contract should still be EXPIRING_SOON at D=5, got {es['status']}"
        )

        from test_helpers import renew_contract_payload
        cust_h = make_customer_headers(customer["id"])
        renewed = get_success_data(api.renew_contract(
            contract["id"],
            renew_contract_payload(es["version"]),
            cust_h,
        ))
        # D = 5 <= 14 → no discount, base = 50000, no items → surcharge = 0.
        assert renewed["annual_premium_due_cents"] == 50_000
