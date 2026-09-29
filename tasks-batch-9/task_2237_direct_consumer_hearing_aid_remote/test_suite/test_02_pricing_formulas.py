"""Combinatorial money formulas: restocking components, care-plan cycle charge, warranty deductible.

Each suite pins a formula whose evaluation ORDER changes the answer in cents:
per-component rounding before summation, the five-step cycle charge, and the
rounded multiplicative product plus an integer surcharge.
"""
from datetime import datetime

from test_helpers import (
    ADMIN,
    CARE_OPS,
    COMPLIANCE,
    REPAIR_TECH,
    api_client,
    make_patient_headers,
    set_clock,
    setup_active_care_plan,
    setup_delivered_order,
    setup_return_inspected,
    validate_success,
)

NV_PER_COMPONENT_POLICY = {
    "state_code": "NV",
    "otc_sales_permitted": True,
    "telehealth_fitting_permitted": True,
    "min_age_years": 18,
    "trial_period_days": 30,
    "restocking_fee_mode": "FLAT_PCT",
    "restocking_fee_pct": 0.0725,
    "restocking_fee_cap_cents": 20000,
    "shipping_refundable": True,
    "referral_validity_days": 180,
    "waiver_required": False,
}

CA_POLICY = {
    "state_code": "CA",
    "otc_sales_permitted": True,
    "telehealth_fitting_permitted": True,
    "min_age_years": 18,
    "trial_period_days": 30,
    "restocking_fee_mode": "FLAT_PCT",
    "restocking_fee_pct": 0.1000,
    "restocking_fee_cap_cents": 0,
    "shipping_refundable": False,
    "referral_validity_days": 180,
    "waiver_required": False,
    "max_loss_damage_claims": 2,
}


def _instant(value: str) -> datetime:
    """Parse a logical-clock instant so equality is on the instant, not its rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_refurbishable_nevada_return() -> dict:
    """A Nevada order whose three restocking components all land on non-trivial fractions."""
    return setup_return_inspected(
        inspection_grade="REFURBISHABLE",
        at_iso="2026-08-04T00:00:00Z",
        policy_overrides=NV_PER_COMPONENT_POLICY,
        pool_overrides={
            "sku": "NEO-S-CLOSED",
            "model": "NEO",
            "dome_size": "S",
            "tip_type": "CLOSED",
        },
        restock_units=3,
        patient_overrides={"age_years": 70},
        order_overrides={
            "model": "NEO",
            "dome_size": "S",
            "tip_type": "CLOSED",
            "list_price_cents": 110000,
            "discount_cents": 9950,
            "accessory_subtotal_cents": 3333,
            "shipping_cents": 1495,
        },
    )


def _setup_premium_plan_through_seven_cycles() -> dict:
    """A PREMIUM plan whose subtotal sits exactly on the inclusive service-fee threshold.

    Seven successful cycles are run, each at that cycle's own `cycle_end_utc`, so the
    seventh run is computed with a `cycle_ordinal` that is unambiguously in the 0.10
    loyalty tier.
    """
    env = setup_active_care_plan(
        policy_overrides=CA_POLICY,
        pool_overrides={
            "sku": "NEO-M-OPEN",
            "model": "NEO",
            "dome_size": "M",
            "tip_type": "OPEN",
        },
        restock_units=5,
        patient_overrides={"age_years": 66},
        order_overrides={
            "model": "NEO",
            "dome_size": "M",
            "tip_type": "OPEN",
            "list_price_cents": 100000,
            "discount_cents": 0,
            "accessory_subtotal_cents": 0,
            "shipping_cents": 0,
        },
        plan_overrides={
            "plan_tier": "PREMIUM",
            "base_fee_cents": 7900,
            "firmware_auto_update_enabled": True,
        },
    )

    cycle_ends = [
        "2026-08-31T00:00:00Z",
        "2026-09-30T00:00:00Z",
        "2026-10-30T00:00:00Z",
        "2026-11-29T00:00:00Z",
        "2026-12-29T00:00:00Z",
        "2027-01-28T00:00:00Z",
        "2027-02-27T00:00:00Z",
    ]
    for cycle_end in cycle_ends:
        set_clock(cycle_end)
        env["plan"] = validate_success(
            api_client.run_billing_cycle(
                env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN
            )
        )
    return env


def _setup_device_at_twelve_months_with_two_claims() -> dict:
    """A device exactly 12 months old with a decided DEFECT claim and a filed DAMAGE claim."""
    env = setup_delivered_order(
        policy_overrides=CA_POLICY,
        pool_overrides={
            "sku": "NEO-M-OPEN",
            "model": "NEO",
            "dome_size": "M",
            "tip_type": "OPEN",
        },
        restock_units=5,
        patient_overrides={"age_years": 68},
        order_overrides={
            "model": "NEO",
            "dome_size": "M",
            "tip_type": "OPEN",
            "list_price_cents": 199900,
            "discount_cents": 9900,
            "accessory_subtotal_cents": 4500,
            "shipping_cents": 1495,
        },
    )
    device_id = env["assigned_device"]["id"]
    patient_headers = make_patient_headers(env["patient"]["id"])

    # Exactly 12 months after shipment: the inclusive upper edge of the first age tier.
    set_clock("2027-08-01T00:00:00Z")

    claim_one = validate_success(
        api_client.create_warranty_claim(
            {"device_id": device_id, "claim_kind": "DEFECT"}, patient_headers
        ),
        201,
    )
    validate_success(api_client.triage_warranty_claim(claim_one["id"], REPAIR_TECH))
    claim_one = validate_success(
        api_client.decide_warranty_claim(claim_one["id"], {"decision": "REPAIR"}, COMPLIANCE)
    )

    claim_two = validate_success(
        api_client.create_warranty_claim(
            {"device_id": device_id, "claim_kind": "DAMAGE"}, patient_headers
        ),
        201,
    )

    env["claim_one"] = claim_one
    env["claim_two"] = claim_two
    return env


# ---------------------------------------------------------------------------
# combinatorial_formula: restocking components round before they sum
# ---------------------------------------------------------------------------
class TestRestockingPerComponentRounding:
    """Three components round independently and only then sum."""

    def test_three_components_round_independently_and_sum_to_12378_cents(self, api):
        """PRD §2.6: "In restocking settlement, each component is rounded to the cent independently and only then summed; summing first and rounding the total is forbidden and produces a different number of cents."

        PRD §3.6: "Step three computes per-component restocking, **rounding each component to the cent before anything is summed**. Under `FLAT_PCT`, the device portion is the device component multiplied by the policy's `restocking_fee_pct`, rounded half up; the accessory portion is the accessory component multiplied by `restocking_fee_pct` and again by an accessory factor of 0.5 — accessories restock at half the device rate — rounded half up."

        PRD §3.6: "Step four adds a **third, independently rounded component**: a damage surcharge. A `DAMAGED` grade surcharges the device component multiplied by 0.15, rounded half up; a `REFURBISHABLE` grade surcharges the device component multiplied by 0.05, rounded half up; a `RESELLABLE` grade surcharges nothing."

        PRD §3.6: "Step five sums the three already-rounded components and applies the cap: when the pinned policy's `restocking_fee_cap_cents` is 0 the raw sum stands unchanged; otherwise `restocking_fee_cents` is the lesser of the raw sum and the cap. Summing the components first and rounding the total once is explicitly forbidden and yields a different number of cents."

        Design: Difficulty/combinatorial_formula/restocking_per_component_rounding_before_sum
        """
        env = _setup_refurbishable_nevada_return()

        rma = validate_success(api.get_return_authorization(env["rma"]["id"], CARE_OPS))
        assert rma["status"] == "INSPECTED", (
            f"inspection moves the authorization to INSPECTED, got {rma['status']}"
        )
        assert rma["inspection_grade"] == "REFURBISHABLE", (
            f"the supplied grade is recorded on the authorization, got {rma['inspection_grade']}"
        )
        assert rma["days_used_at_issue"] == 3, (
            f"three whole trial days elapsed before the return was issued, got "
            f"{rma['days_used_at_issue']}"
        )
        assert rma["restocking_variant"] == "FLAT_PCT", (
            "a non-zero day count under a FLAT_PCT pinned mode selects FLAT_PCT, got "
            f"{rma['restocking_variant']}"
        )
        assert rma["restocking_fee_cents"] == 12378, (
            "the device portion 7254, the half-rate accessory portion 121 and the "
            f"refurbishable surcharge 5003 sum to 12378, got {rma['restocking_fee_cents']}"
        )
        assert rma["restocking_fee_cents"] != 12377, (
            "12377 is the forbidden result of summing the unrounded components first"
        )
        assert rma["restocking_fee_cents"] != 20000, (
            "the cap of 20000 sits above the raw sum, so it must not bind"
        )

    def test_refundable_shipping_is_returned_and_the_refund_lands_on_99995_cents(self, api):
        """PRD §3.6: "Step six sets `non_refundable_shipping_cents` to 0 when the pinned policy's `shipping_refundable` is true, and to the order's `shipping_cents` otherwise. Step seven sets `refund_amount_cents` to the order's `captured_cents` minus `restocking_fee_cents` minus `non_refundable_shipping_cents`, floored at 0."

        PRD §3.5: "`tax_cents` is the taxable base multiplied by the sales-tax rate of 0.0725 (7.25 percent), rounded half up — this is the single rounding in the whole composition. `total_cents` is the device subtotal plus `accessory_subtotal_cents` plus `shipping_cents` plus `tax_cents`."

        Design: Difficulty/combinatorial_formula/restocking_per_component_rounding_before_sum
        """
        env = _setup_refurbishable_nevada_return()

        order = validate_success(api.get_device_order(env["order"]["id"], CARE_OPS))
        assert order["tax_cents"] == 7495, (
            f"the taxable base of 103383 cents taxes to 7495 cents, got {order['tax_cents']}"
        )
        assert order["total_cents"] == 112373, (
            f"the composed order total is 112373 cents, got {order['total_cents']}"
        )
        assert order["captured_cents"] == 112373, (
            f"shipping captured the whole total, got {order['captured_cents']}"
        )

        rma = validate_success(api.get_return_authorization(env["rma"]["id"], CARE_OPS))
        assert rma["non_refundable_shipping_cents"] == 0, (
            "the Nevada policy makes shipping refundable, so nothing is retained for it, got "
            f"{rma['non_refundable_shipping_cents']}"
        )
        assert rma["refund_amount_cents"] == 99995, (
            f"112373 - 12378 - 0 is 99995, got {rma['refund_amount_cents']}"
        )
        assert rma["refund_amount_cents"] != 99996, (
            "99996 is the refund implied by the forbidden sum-then-round restocking fee"
        )


# ---------------------------------------------------------------------------
# combinatorial_formula: the five-step care-plan cycle charge
# ---------------------------------------------------------------------------
class TestCarePlanCycleChargeOrdering:
    """The service-fee waiver is tested on the subtotal, never on the discounted amount."""

    def test_premium_subtotal_exactly_on_the_threshold_waives_the_service_fee(self, api):
        """PRD §3.8: "Step one: the subtotal is `base_fee_cents`, plus a premium surcharge of 2,000 cents ($20.00) when `plan_tier` is `PREMIUM`. Step two: `service_fee_cents` is 0 when that subtotal is at least 9,900 cents ($99.00) — the threshold is inclusive, so a subtotal of exactly 9,900 waives the fee — and 495 cents ($4.95) otherwise."

        PRD §3.8: "Testing the **discounted** amount against the service-fee waiver threshold is forbidden and produces a different total."

        Design: Difficulty/combinatorial_formula/care_plan_service_fee_waiver_evaluated_on_subtotal_not_discounted
        """
        env = _setup_premium_plan_through_seven_cycles()

        plan = validate_success(api.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
        assert plan["status"] == "ACTIVE", (
            f"a successful billing run self-loops the plan on ACTIVE, got {plan['status']}"
        )
        assert plan["service_fee_cents"] == 0, (
            "a PREMIUM base fee of 7900 plus the 2000 surcharge is exactly the inclusive "
            f"9900 threshold, so the fee is waived, got {plan['service_fee_cents']}"
        )
        assert plan["last_charge_cents"] != 9405, (
            "9405 is the forbidden reading that tests the discounted amount against the "
            "waiver threshold and so re-introduces the 495-cent fee"
        )
        assert plan["last_charge_cents"] != 9355, (
            "9355 is the forbidden reading that charges the fee and then discounts a "
            "10395-cent base"
        )

    def test_seventh_cycle_applies_the_ten_percent_loyalty_rate_to_the_fee_inclusive_base(self, api):
        """PRD §3.8: "Step three: the fee-inclusive base is the subtotal plus `service_fee_cents`. Step four: the loyalty rate is 0.15 when `cycle_ordinal` is at least 12, otherwise 0.10 when `cycle_ordinal` is at least 6, otherwise 0.0; `loyalty_discount_cents` is the lesser of 1,500 cents ($15.00) and the fee-inclusive base multiplied by that rate, rounded half up. Step five: `last_charge_cents` is the fee-inclusive base minus `loyalty_discount_cents`, floored at 0."

        Design: Difficulty/combinatorial_formula/care_plan_service_fee_waiver_evaluated_on_subtotal_not_discounted
        """
        env = _setup_premium_plan_through_seven_cycles()

        plan = validate_success(api.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
        assert plan["loyalty_discount_cents"] == 990, (
            "10 percent of the 9900-cent fee-inclusive base is 990, below the 1500 cap, got "
            f"{plan['loyalty_discount_cents']}"
        )
        assert plan["last_charge_cents"] == 8910, (
            f"9900 minus the 990-cent loyalty discount is 8910, got {plan['last_charge_cents']}"
        )
        assert plan["credit_balance_cents"] == 0, (
            f"no credit was ever posted to this plan, got {plan['credit_balance_cents']}"
        )
        assert plan["dunning_attempts"] == 0, (
            f"every charge succeeded, so no dunning occurred, got {plan['dunning_attempts']}"
        )

    def test_seven_successful_runs_advance_the_ordinal_and_the_thirty_day_cycle_window(self, api):
        """PRD §3.8: "On success the plan self-loops `ACTIVE → ACTIVE`: the five-step computation writes `service_fee_cents`, `loyalty_discount_cents` and `last_charge_cents`, credit is consumed, `cycle_ordinal` increments, `cycle_start_utc` advances to the old `cycle_end_utc` and `cycle_end_utc` becomes the new `cycle_start_utc` plus 30 days."

        PRD §3.8: "Delivery of the attached order moves the plan `TRIALING → ACTIVE`, setting `cycle_start_utc` to the order's `delivered_at`, `cycle_end_utc` to `cycle_start_utc` plus 30 days, and `cycle_ordinal` to 0."

        Design: Difficulty/combinatorial_formula/care_plan_service_fee_waiver_evaluated_on_subtotal_not_discounted
        """
        env = _setup_premium_plan_through_seven_cycles()

        plan = validate_success(api.get_care_plan_subscription(env["plan"]["id"], CARE_OPS))
        assert plan["cycle_ordinal"] == 7, (
            f"seven successful runs each incremented the ordinal from 0, got {plan['cycle_ordinal']}"
        )
        assert _instant(plan["cycle_start_utc"]) == _instant("2027-02-27T00:00:00Z"), (
            "the new cycle starts at the previous cycle_end_utc, got "
            f"{plan['cycle_start_utc']}"
        )
        assert _instant(plan["cycle_end_utc"]) == _instant("2027-03-29T00:00:00Z"), (
            f"the new cycle ends 30 days later, got {plan['cycle_end_utc']}"
        )


# ---------------------------------------------------------------------------
# combinatorial_formula: warranty deductible product then integer surcharge
# ---------------------------------------------------------------------------
class TestWarrantyDeductibleComposition:
    """Age multiplier and kind factor multiply and round; the ordinal surcharge is added after."""

    def test_defect_claim_at_ordinal_one_collapses_the_deductible_to_zero(self, api):
        """PRD §3.7: "The kind factor is 0.0 for `DEFECT`, 0.75 for `DAMAGE` and 1.0 for `LOSS`, so a manufacturing defect is never charged a deductible. The ordinal surcharge is 0 when `claim_ordinal` is 1 and 5,000 cents ($50.00) otherwise."

        PRD §3.7: "`claim_ordinal` is one more than the number of prior claims on the same `device_id` whose `status` is `APPROVED_REPLACEMENT`, `APPROVED_REPAIR` or `FULFILLED`, ordered by `created_at` ascending, and is at least 1; withdrawn claims are excluded from the count."

        PRD §3.7: "A `REPAIR` decision moves the claim `TRIAGED → APPROVED_REPAIR`; it requires `claim_kind` to be `DEFECT` or `DAMAGE` and `warranty_expires_at` to be strictly after the clock."

        Design: Difficulty/combinatorial_formula/warranty_deductible_tier_product_then_integer_surcharge
        """
        env = _setup_device_at_twelve_months_with_two_claims()

        claim = validate_success(api.get_warranty_claim(env["claim_one"]["id"], CARE_OPS))
        assert claim["status"] == "APPROVED_REPAIR", (
            f"the REPAIR decision approves the defect claim for repair, got {claim['status']}"
        )
        assert claim["device_age_months"] == 12, (
            f"the device is exactly 12 whole months old, got {claim['device_age_months']}"
        )
        assert claim["claim_ordinal"] == 1, (
            f"this is the device's first counted claim, got {claim['claim_ordinal']}"
        )
        assert claim["deductible_cents"] == 0, (
            "a DEFECT kind factor of 0.0 with no ordinal surcharge leaves nothing to pay, got "
            f"{claim['deductible_cents']}"
        )

    def test_second_damage_claim_at_the_inclusive_twelve_month_edge_deducts_8713_cents(self, api):
        """PRD §3.7: "The **deductible** is tiered on device age and scaled by claim nature. An age of at most 12 months — inclusive — takes a multiplier of 0.5; an age from 13 through 24 months takes 1.0; an age above 24 months takes 1.5. The kind factor is 0.0 for `DEFECT`, 0.75 for `DAMAGE` and 1.0 for `LOSS`, so a manufacturing defect is never charged a deductible. The ordinal surcharge is 0 when `claim_ordinal` is 1 and 5,000 cents ($50.00) otherwise. `deductible_cents` is the base of 9,900 cents ($99.00) multiplied by the age multiplier and by the kind factor, rounded half up, with the integer surcharge added afterwards — the rounding touches the multiplicative part only."

        PRD §2.6: "In warranty deductibles, rounding is applied to the multiplicative part only, and the integer surcharge is added afterwards."

        Design: Difficulty/combinatorial_formula/warranty_deductible_tier_product_then_integer_surcharge
        """
        env = _setup_device_at_twelve_months_with_two_claims()

        claim = validate_success(
            api.triage_warranty_claim(env["claim_two"]["id"], REPAIR_TECH)
        )
        assert claim["status"] == "TRIAGED", (
            f"triage moves the filed claim to TRIAGED, got {claim['status']}"
        )
        assert claim["device_age_months"] == 12, (
            f"the device is exactly 12 whole months old, got {claim['device_age_months']}"
        )
        assert claim["claim_ordinal"] == 2, (
            "the approved defect claim counts, so this is the second claim, got "
            f"{claim['claim_ordinal']}"
        )
        assert claim["deductible_cents"] == 8713, (
            "9900 * 0.5 * 0.75 rounds half up to 3713 and the 5000-cent ordinal surcharge is "
            f"added afterwards, got {claim['deductible_cents']}"
        )
        assert claim["deductible_cents"] != 12425, (
            "12425 reads the 12-month tier boundary exclusively and applies the 1.0 multiplier"
        )
        assert claim["deductible_cents"] != 8712, (
            "8712 either rounds the exact half down or folds the surcharge into the rounded product"
        )
        assert claim["deductible_paid_cents"] == 0, (
            f"nothing has been paid against the deductible yet, got {claim['deductible_paid_cents']}"
        )

    def test_shipment_stamps_the_warranty_term_the_deductible_age_is_measured_from(self, api):
        """PRD §3.5: "stamps the device's `shipped_at` from the logical clock and sets its `warranty_expires_at` to `shipped_at` plus 730 days (two years)"

        PRD §3.7: "`device_age_months` is the whole number of months between the device's `shipped_at` and the logical clock, floored."

        Design: Difficulty/combinatorial_formula/warranty_deductible_tier_product_then_integer_surcharge
        """
        env = _setup_device_at_twelve_months_with_two_claims()

        device = validate_success(api.get_device(env["assigned_device"]["id"], CARE_OPS))
        assert _instant(device["shipped_at"]) == _instant("2026-08-01T00:00:00Z"), (
            f"the device shipped at the startup instant, got {device['shipped_at']}"
        )
        assert _instant(device["warranty_expires_at"]) == _instant("2028-07-31T00:00:00Z"), (
            f"730 days after shipment is 2028-07-31, got {device['warranty_expires_at']}"
        )
