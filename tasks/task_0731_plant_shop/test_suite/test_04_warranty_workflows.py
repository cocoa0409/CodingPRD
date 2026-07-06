"""Warranty adjudication: dual-variant refund, cascade, and boundary."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order, deliver,
    append_care_log, get_orderline_id_for_order,
    TEST_USERS, make_customer_headers, make_delivery_driver_headers,
)


# -----------------------------------------------------------------------------
# Difficulty Rule 1 (instance 2): Warranty refund provisional vs final
# -----------------------------------------------------------------------------

class TestWarrantyRefundDualVariant:

    def _setup_delivered_with_one_care_log(self, email: str):
        """Deliver an order on 2026-04-05, add a single WATER care log (2 events missing),
        advance clock to 2026-04-15. Returns (customer, orderline_id)."""
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email=email, delivery_zone="ZONE_A")
        driver = create_driver(name=f"drv-{email}")
        plant = create_plant(
            name=f"Pothos-{email}", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=5000, warranty_days=30,
        )
        stock = intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        d = dispatch_order(
            order["id"], driver["id"], "2026-04-05T09:00:00Z", "2026-04-05T11:00:00Z"
        )
        set_clock("2026-04-05T10:00:00Z")
        deliver(d["id"], driver["id"])
        set_clock("2026-04-15T00:00:00Z")
        # 1 mandatory care event present → missing_events = 3 - 1 = 2
        append_care_log(stock["id"], "WATER", note="watered")
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        return customer, orderline_id

    def test_warranty_submission_stamps_full_line_subtotal_provisional(self, api):
        """PRD §3.5: "On successful submission, the target OrderLine.refund_status
        flips from NONE to PENDING_REVIEW and the provisional refund amount is
        stamped as WarrantyClaim.refund_amount_cents_provisional using the
        provisional variant of warranty_refund_amount — the full
        OrderLine.line_subtotal_cents, with no care-log deduction, floored."

        Design: Difficulty/dual_variant_calc/warranty_refund_provisional_vs_final_care_log_deductions
        """
        customer, orderline_id = self._setup_delivered_with_one_care_log("bob1@example.com")
        r = api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        )
        claim = validate_success(r, expected_status=201)
        assert claim["refund_amount_cents_provisional"] == 5000

    def test_warranty_approval_stamps_final_with_two_missing_deductions(self, api):
        """PRD §3.5: "the number of missing events is the greater of zero and three
        minus the observed count; the deduction count is that missing-events
        value clamped at a maximum of three; the final refund is the base
        multiplied by one minus 0.20 for each deduction, floored to integer
        cents."
        PRD §3.5: "WarrantyClaim.status moves to APPROVED".

        Design: Difficulty/dual_variant_calc/warranty_refund_provisional_vs_final_care_log_deductions
        """
        customer, orderline_id = self._setup_delivered_with_one_care_log("bob2@example.com")
        submitted = get_success_data(api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        ))
        r = api.approve_warranty_claim(submitted["id"], TEST_USERS["horticulturist_headers"])
        approved = validate_success(r)
        # missing_events = 2 → deductions=2 → 5000 * (1 - 0.4) = 3000
        assert approved["refund_amount_cents_final"] == 3000
        assert approved["status"] == "APPROVED"

    def test_warranty_approval_credits_wallet_with_final_amount(self, api):
        """PRD §3.5: "Customer.wallet_credit_cents is increased by the final
        amount".

        Design: Difficulty/dual_variant_calc/warranty_refund_provisional_vs_final_care_log_deductions
        """
        customer, orderline_id = self._setup_delivered_with_one_care_log("bob3@example.com")
        submitted = get_success_data(api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        ))
        validate_success(api.approve_warranty_claim(submitted["id"], TEST_USERS["horticulturist_headers"]))
        c = get_success_data(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
        assert c["wallet_credit_cents"] == 3000


# -----------------------------------------------------------------------------
# Difficulty Rule 4 (instance 2): Warranty approval depth-2 cascade
# -----------------------------------------------------------------------------

class TestWarrantyApprovalCascade:

    def test_approval_flips_stock_to_shrink_with_warranty_return(self, api):
        """PRD §3.5: "the delivered StockUnit.sale_status flips from SOLD first to
        RETURNED and then to SHRINK with shrink_reason of WARRANTY_RETURN".

        Design: Difficulty/transitive_cascade/warranty_approve_cascade_depth_2_orderline_stock_customer_wallet
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="iris1@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Jake1")
        plant = create_plant(
            name="Peperomia1", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=5000, warranty_days=30,
        )
        stock = intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-05T09:00:00Z", "2026-04-05T11:00:00Z")
        set_clock("2026-04-05T10:00:00Z")
        deliver(d["id"], driver["id"])
        set_clock("2026-04-10T00:00:00Z")
        for et in ("WATER", "LIGHT_CHECK", "PRUNE"):
            append_care_log(stock["id"], et)
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        claim = get_success_data(api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        ))
        validate_success(api.approve_warranty_claim(claim["id"], TEST_USERS["horticulturist_headers"]))

        stock_after = get_success_data(api.get_stock_unit(stock["id"], TEST_USERS["manager_headers"]))
        assert stock_after["sale_status"] == "SHRINK"
        assert stock_after["shrink_reason"] == "WARRANTY_RETURN"

    def test_approval_credits_wallet_by_full_line_subtotal_when_no_missing_care(self, api):
        """PRD §3.5: "The formula guarantees a minimum payout of 40% of the base
        (three deductions) and a maximum payout of 100% (zero missing care
        events)."
        PRD §3.5: "Customer.wallet_credit_cents is increased by the final amount".

        Design: Difficulty/transitive_cascade/warranty_approve_cascade_depth_2_orderline_stock_customer_wallet
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="iris2@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Jake2")
        plant = create_plant(
            name="Peperomia2", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=5000, warranty_days=30,
        )
        stock = intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-05T09:00:00Z", "2026-04-05T11:00:00Z")
        set_clock("2026-04-05T10:00:00Z")
        deliver(d["id"], driver["id"])
        set_clock("2026-04-10T00:00:00Z")
        for et in ("WATER", "LIGHT_CHECK", "PRUNE"):
            append_care_log(stock["id"], et)
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        claim = get_success_data(api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        ))
        approved = get_success_data(api.approve_warranty_claim(claim["id"], TEST_USERS["horticulturist_headers"]))
        assert approved["refund_amount_cents_final"] == 5000

        c = get_success_data(api.get_customer(customer["id"], make_customer_headers(customer["id"])))
        assert c["wallet_credit_cents"] == 5000


# -----------------------------------------------------------------------------
# Difficulty Rule 6: Boundary precision — warranty period
# -----------------------------------------------------------------------------

class TestWarrantyPeriodBoundary:

    def test_claim_at_day_31_rejected_with_warranty_expired(self, api):
        """PRD §3.5: "the elapsed time between the logical clock and the parent
        order's delivery instant, measured in whole days (86400-second buckets,
        floor-inclusive), must not exceed the plant's warranty_days; the
        boundary is inclusive at exactly warranty_days and rejects at
        warranty_days + 1 with ERR_WARRANTY_EXPIRED (HTTP 422)."

        Design: Difficulty/boundary_precision_check/warranty_period_boundary_exact_day_inclusive
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="oli1@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Pat1")
        plant = create_plant(
            name="Calathea1", light_tag="LOW", care_tag="MODERATE",
            weight_class="LIGHT", unit_price_cents=4500, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-05T09:00:00Z", "2026-04-05T11:00:00Z")
        set_clock("2026-04-05T10:00:00Z")
        deliver(d["id"], driver["id"])
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        # Delivered on day 0; advance to day 31 (2026-05-06T10:00Z is 31 whole days after)
        set_clock("2026-05-06T10:00:00Z")
        r = api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_WARRANTY_EXPIRED.value)

    def test_claim_by_stranger_and_expired_returns_warranty_expired(self, api):
        """PRD §2.8: "Business — safety. The warranty period boundary check
        (ERR_WARRANTY_EXPIRED, HTTP 422, on warranty submission) and the
        stock-unit adjust health guard against a forbidden flip out of shrink
        (ERR_STOCK_UNIT_UNHEALTHY, HTTP 422, on stock-unit adjustment)."
        PRD §2.8: "Business — referential. Workshop capacity (ERR_WORKSHOP_FULL),
        order-line stock availability (ERR_STOCK_UNAVAILABLE), and warranty
        ownership (ERR_WARRANTY_NOT_ELIGIBLE) fall here."
        PRD §2.8: "In particular, a compliance-style rejection surfaces before a
        business rule masks it".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_warranty_expired_and_not_owner
        """
        set_clock("2026-04-01T00:00:00Z")
        cust_a = register_customer(email="leo@example.com", delivery_zone="ZONE_A")
        cust_b = register_customer(email="mia@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Ned")
        plant = create_plant(
            name="ZZ", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=4000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(cust_a["id"], [(plant["id"], 1)])
        pay_order(order["id"], cust_a["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z")
        deliver(d["id"], driver["id"])
        orderline_id = get_orderline_id_for_order(order["id"], cust_a["id"])
        set_clock("2026-06-01T00:00:00Z")
        # Customer B submits on Customer A's line, past the warranty window.
        # Both business_safety (expired) and business_referential (not owner) fail;
        # PRD §2.8 pins temporal/safety BEFORE referential.
        r = api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": cust_b["id"], "reason": "MORTALITY"},
            make_customer_headers(cust_b["id"]),
        )
        validate_error(r, ApiErrorId.ERR_WARRANTY_EXPIRED.value)


