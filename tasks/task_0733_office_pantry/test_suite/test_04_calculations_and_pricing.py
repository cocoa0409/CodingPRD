"""Calculation correctness: subscription fee, delivery charges, per-line rounding,
satisfaction variants."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    make_client_admin_headers, make_location_manager_headers,
    TEST_USERS,
    set_clock, create_plan, create_client, create_location, create_product,
    create_par_level, create_preference, create_subscription, activate_subscription,
    get_first_rotation_cycle,
    setup_scheduled_delivery, setup_disputed_delivery,
    close_and_get_invoice, report_all_actuals_and_resolve,
    dispatch_delivery,
)


# ─────────────────────────────────────────────────────────────
# Difficulty rule 1 — dual_variant_calc
# ─────────────────────────────────────────────────────────────

class TestDeliveryProvisionalVsFinalDiverge:
    def test_provisional_reflects_planned_units(self, api):
        """PRD §3.5: "The provisional variant, evaluated at dispatch, walks each DeliveryLine
        for the delivery and computes three per-line quantities from three inputs plus the
        parent location's kind."

        Design: Difficulty/dual_variant_calc/delivery_provisional_vs_final_diverge
        """
        # Two lines: prodA par=10 @ 100 cents, prodB par=5 @ 200 cents. PANTRY (no fee, <100 no disc).
        set_clock("2026-06-01T00:00:00Z")
        plan = create_plan(tier="ST-DV", billing_type="FLAT", flat_fee_cents=5000,
                          volume_discount_threshold_headcount=50)
        client = create_client(name="AcmeCo-DV", headcount=20)
        loc = create_location(client["id"], name="HQ Pantry", kind="PANTRY", capacity_units=100)
        prodA = create_product(sku="A-100-DV", name="Chips", category="SNACK", unit_cost_cents=100)
        prodB = create_product(sku="B-200-DV", name="Bars", category="SNACK", unit_cost_cents=200)
        create_par_level(loc["id"], prodA["id"], 10)
        create_par_level(loc["id"], prodB["id"], 5)
        sub = create_subscription(client["id"], plan["id"], client["version"])
        activate_subscription(sub["id"])
        rc = get_first_rotation_cycle(sub["id"])
        res = api.create_delivery(
            rc["id"],
            {"location_id": loc["id"], "scheduled_at": "2026-06-01T12:00:00Z"},
            TEST_USERS["platform_admin_headers"],
        )
        delv = validate_success(res, expected_status=201)
        dispatched = dispatch_delivery(delv["id"])
        # planned: 10*100 + 5*200 = 1000+1000 = 2000
        assert dispatched["provisional_cents"] == 2000, \
            f"expected provisional_cents=2000, got {dispatched['provisional_cents']}"

    def test_final_after_short_ship_diverges_from_provisional(self, api):
        """PRD §3.5: "The final variant, evaluated at finalize or resolve-dispute, is
        identical in shape but reads actual_units in place of planned_units."
        PRD §3.6: "the credit is the unit shortfall priced at the same snapshotted
        per-unit cost the billing engine uses — no service-fee overlay and no
        bulk-discount overlay applies to the credit."

        Design: Difficulty/dual_variant_calc/delivery_provisional_vs_final_diverge
        """
        set_clock("2026-06-01T00:00:00Z")
        plan = create_plan(tier="ST-DV2", billing_type="FLAT", flat_fee_cents=5000,
                          volume_discount_threshold_headcount=50)
        client = create_client(name="AcmeCo-DV2", headcount=20)
        loc = create_location(client["id"], name="HQ Pantry-DV2", kind="PANTRY", capacity_units=100)
        prodA = create_product(sku="A-100-DV2", name="Chips", category="SNACK", unit_cost_cents=100)
        prodB = create_product(sku="B-200-DV2", name="Bars", category="SNACK", unit_cost_cents=200)
        create_par_level(loc["id"], prodA["id"], 10)
        create_par_level(loc["id"], prodB["id"], 5)
        sub = create_subscription(client["id"], plan["id"], client["version"])
        activate_subscription(sub["id"])
        rc = get_first_rotation_cycle(sub["id"])
        delv_res = api.create_delivery(
            rc["id"],
            {"location_id": loc["id"], "scheduled_at": "2026-06-01T12:00:00Z"},
            TEST_USERS["platform_admin_headers"],
        )
        delv = validate_success(delv_res, expected_status=201)
        # Full lifecycle: dispatch -> confirm -> dispute -> patch actuals -> resolve.
        state = {"delivery": delv, "location": loc}
        from test_helpers import (
            confirm_delivery, dispute_delivery,
        )
        dispatched = dispatch_delivery(delv["id"])
        state["delivery"] = dispatched
        confirm_delivery(delv["id"], loc["id"])
        dispute_delivery(delv["id"], loc["id"], "short-shipped A")
        # Set actuals: line0 (prodA) actual=8, line1 (prodB) actual=5.
        state["delivery"] = dispatched
        state = report_all_actuals_and_resolve(state, [8, 5])
        d = state["delivery"]
        # provisional_cents = 10*100 + 5*200 = 2000
        # final_cents = 8*100 + 5*200 = 800 + 1000 = 1800
        # dispute_credit_cents = (10-8)*100 = 200
        assert d["provisional_cents"] == 2000, f"prov: {d['provisional_cents']}"
        assert d["final_cents"] == 1800, f"final: {d['final_cents']}"
        assert d["dispute_credit_cents"] == 200, f"credit: {d['dispute_credit_cents']}"
        assert d["provisional_cents"] != d["final_cents"], "variants must diverge"


class TestSatisfactionVariantsDiverge:
    def _setup(self):
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(name="SnackCo-SV", headcount=10)
        loc = create_location(client["id"], name="Pantry-A", kind="PANTRY", capacity_units=50)
        prodA = create_product(sku="SKU-A-SV", name="ChipsA", category="SNACK", unit_cost_cents=100)
        prodB = create_product(sku="SKU-B-SV", name="BarsB", category="SNACK", unit_cost_cents=150)
        prodC = create_product(sku="SKU-C-SV", name="OldC", category="SNACK", unit_cost_cents=200)
        create_par_level(loc["id"], prodA["id"], 5)
        # Note: productC is NOT in any ParLevel.
        api_res_a = api_client_local()  # local ref
        # Feedback rows: (A, 5, no swap), (A, 3, swap=B), (C, 1, no swap)
        from test_helpers import api_client, create_feedback_payload
        headers = make_client_admin_headers(client["id"])
        api_client.create_feedback(client["id"], {"product_id": prodA["id"], "rating": 5}, headers)
        api_client.create_feedback(
            client["id"],
            {"product_id": prodA["id"], "rating": 3, "swap_suggestion_product_id": prodB["id"]},
            headers,
        )
        api_client.create_feedback(client["id"], {"product_id": prodC["id"], "rating": 1}, headers)
        return client

    def test_authoritative_variant_excludes_unstocked_product_feedback(self, api):
        """PRD §3.8: "The authoritative variant — the default surface for a public
        satisfaction query — counts only feedback whose product_id currently appears in a
        ParLevel under one of the client's locations, silently excluding stale feedback
        that referred to products long dropped from the assortment."
        PRD §3.8: "a row with a non-null swap_suggestion_product_id counts with weight 2,
        and a row with a null suggestion counts with weight 1."

        Design: Difficulty/dual_variant_calc/client_satisfaction_score_variants_diverge
        """
        client = self._setup()
        res = api.get_client_satisfaction(
            client["id"], TEST_USERS["platform_admin_headers"],
            params={"variant": "authoritative"},
        )
        body = validate_success(res)
        # authoritative excludes productC:
        # numerator = 5*1 + 3*2 = 11 ; denominator = 3 -> 11/3 = 3.6666... -> 3.67 (half-up)
        assert body["score"] == 3.67, f"authoritative score should be 3.67, got {body['score']}"
        assert body["feedback_considered"] == 2, \
            f"authoritative feedback_considered should be 2, got {body['feedback_considered']}"

    def test_provisional_variant_counts_unstocked_product_feedback(self, api):
        """PRD §3.8: "The provisional variant — used for internal audit and churn analysis —
        counts every feedback row ever recorded for the client, including feedback about
        products that are no longer stocked at any of the client's locations."

        Design: Difficulty/dual_variant_calc/client_satisfaction_score_variants_diverge
        """
        client = self._setup()
        res = api.get_client_satisfaction(
            client["id"], TEST_USERS["platform_admin_headers"],
            params={"variant": "provisional"},
        )
        body = validate_success(res)
        # provisional includes productC:
        # numerator = 5*1 + 3*2 + 1*1 = 12 ; denominator = 4 -> 12/4 = 3.00
        assert body["score"] == 3.00, f"provisional score should be 3.00, got {body['score']}"
        assert body["feedback_considered"] == 3, \
            f"provisional feedback_considered should be 3, got {body['feedback_considered']}"


def api_client_local():
    # placeholder to avoid unused-import warnings; not called.
    return None


# ─────────────────────────────────────────────────────────────
# Difficulty rule 2 — combinatorial_formula
# ─────────────────────────────────────────────────────────────

def test_subscription_fee_per_employee_with_volume_discount(api):
    """PRD §3.7: "Under PER_EMPLOYEE billing, the engine first computes the raw per-employee
    amount as per_employee_fee_cents multiplied by headcount. If the client's headcount is
    at least the plan's volume_discount_threshold_headcount (the boundary is inclusive),
    the raw amount is multiplied by one minus volume_discount_pct to yield a discounted
    amount; that discounted amount is then rounded to integer cents using round-half-up."
    PRD §3.7: "The rounded (or unrounded) per-employee amount is then added to
    plan.base_fee_cents to produce subscription_fee_cents."

    Design: Difficulty/combinatorial_formula/subscription_fee_tiered_multi_input
    """
    from test_helpers import setup_active_subscription
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        plan_overrides={
            "tier": "GROWTH-CFA", "billing_type": "PER_EMPLOYEE",
            "base_fee_cents": 5000, "per_employee_fee_cents": 200,
            "volume_discount_threshold_headcount": 50, "volume_discount_pct": 0.10,
        },
        client_overrides={"name": "BigCo-CFA", "headcount": 100},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-15T00:00:00Z")
    inv = state["invoice"]
    # raw_per_employee = 200 * 100 = 20000
    # discounted = 20000 * 0.90 = 18000 (integer; round_half_up of 18000 is 18000)
    # subscription_fee_cents = 5000 + 18000 = 23000
    assert inv["subscription_fee_cents"] == 23000, \
        f"expected subscription_fee_cents=23000, got {inv['subscription_fee_cents']}"
    assert inv["consumption_cents"] == 0, f"expected consumption=0, got {inv['consumption_cents']}"
    assert inv["total_cents"] == 23000, f"expected total=23000, got {inv['total_cents']}"


def test_subscription_fee_total_reconciles_when_no_deliveries(api):
    """PRD §3.7: "consumption_cents is the sum of delivery.final_cents across all
    deliveries under the cycle whose status is FINALIZED."
    PRD §3.7: "total_cents is subscription_fee_cents + consumption_cents - credit_applied_cents."

    Design: Difficulty/combinatorial_formula/subscription_fee_tiered_multi_input
    """
    from test_helpers import setup_active_subscription
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        plan_overrides={
            "tier": "GROWTH-CFB", "billing_type": "PER_EMPLOYEE",
            "base_fee_cents": 5000, "per_employee_fee_cents": 200,
            "volume_discount_threshold_headcount": 50, "volume_discount_pct": 0.10,
        },
        client_overrides={"name": "BigCo-CFB", "headcount": 100},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-15T00:00:00Z")
    inv = state["invoice"]
    # No deliveries were dispatched or finalized in this cycle; consumption must be 0
    # and total must equal (subscription_fee + 0 - credit_applied); no prior credit exists so credit=0.
    assert inv["consumption_cents"] == 0, f"no deliveries -> consumption=0; got {inv['consumption_cents']}"
    assert inv["credit_applied_cents"] == 0, \
        f"no prior credit balance -> credit_applied=0; got {inv['credit_applied_cents']}"
    assert inv["total_cents"] == inv["subscription_fee_cents"], \
        f"total must equal fee when consumption=0 and credit=0; got total={inv['total_cents']}, fee={inv['subscription_fee_cents']}"


def test_micro_market_per_line_rounding_before_summation(api):
    """PRD §2.6: "Per-line rounding first. Whenever a per-line rounded quantity is combined
    into a total (for example, a per-line service fee at a MICRO_MARKET or a per-line bulk
    discount), each line is rounded to integer cents independently using round-half-up,
    then the rounded per-line quantities are summed."
    PRD §3.5: "When the location's kind is MICRO_MARKET, the per-line fee is the raw
    amount multiplied by the line's service_fee_bps_snapshot divided by 10000, then
    rounded to integer cents using round-half-up."

    Design: Difficulty/combinatorial_formula/delivery_provisional_per_line_rounding_order
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="ST-MM", billing_type="FLAT", flat_fee_cents=1000,
                      volume_discount_threshold_headcount=50)
    client = create_client(name="MMCo-MM", headcount=5)
    loc = create_location(client["id"], name="MM-MM", kind="MICRO_MARKET",
                          capacity_units=20, service_fee_bps=750)
    prodX = create_product(sku="X-1-MM", name="X", category="SNACK", unit_cost_cents=100)
    prodY = create_product(sku="Y-1-MM", name="Y", category="SNACK", unit_cost_cents=100)
    create_par_level(loc["id"], prodX["id"], 1)
    create_par_level(loc["id"], prodY["id"], 1)
    sub = create_subscription(client["id"], plan["id"], client["version"])
    activate_subscription(sub["id"])
    rc = get_first_rotation_cycle(sub["id"])
    delv_res = api.create_delivery(
        rc["id"],
        {"location_id": loc["id"], "scheduled_at": "2026-06-01T12:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    delv = validate_success(delv_res, expected_status=201)
    dispatched = dispatch_delivery(delv["id"])
    # Per line: raw=1*100=100, fee=round_half_up(100*0.075)=round_half_up(7.5)=8, disc=0 (planned<100)
    # line_cents = 108 per line; provisional_cents = 216
    # Sum-then-round would give 200*0.075=15 -> 215 (off by 1).
    assert dispatched["provisional_cents"] == 216, \
        f"per-line rounding must give provisional_cents=216, got {dispatched['provisional_cents']}"


def test_pantry_location_charges_no_service_fee(api):
    """PRD §3.5: "The per-line fee amount is zero when the location's kind is PANTRY or
    FRIDGE."
    PRD §3.5: "This isolation of the service fee to micro-markets is deliberate: pantries
    and refrigerators have no operator-attended checkout to fund."

    Design: Difficulty/combinatorial_formula/delivery_provisional_per_line_rounding_order
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="ST-PN", billing_type="FLAT", flat_fee_cents=1000,
                      volume_discount_threshold_headcount=50)
    client = create_client(name="PantryCo-PN", headcount=5)
    # PANTRY with service_fee_bps set high (750) — the fee is a per-location input but only
    # applied at MICRO_MARKET. PANTRY must ignore it.
    loc = create_location(client["id"], name="P-PN", kind="PANTRY",
                          capacity_units=20, service_fee_bps=750)
    prodX = create_product(sku="X-PN", name="X", category="SNACK", unit_cost_cents=100)
    prodY = create_product(sku="Y-PN", name="Y", category="SNACK", unit_cost_cents=100)
    create_par_level(loc["id"], prodX["id"], 1)
    create_par_level(loc["id"], prodY["id"], 1)
    sub = create_subscription(client["id"], plan["id"], client["version"])
    activate_subscription(sub["id"])
    rc = get_first_rotation_cycle(sub["id"])
    delv_res = api.create_delivery(
        rc["id"],
        {"location_id": loc["id"], "scheduled_at": "2026-06-01T12:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    delv = validate_success(delv_res, expected_status=201)
    dispatched = dispatch_delivery(delv["id"])
    # PANTRY: fee_line = 0 for both lines. raw per line = 1*100 = 100; discount = 0 (planned<100).
    # provisional_cents = 200 (no fee applied even though bps is set).
    assert dispatched["provisional_cents"] == 200, \
        f"PANTRY must not apply service_fee_bps; expected 200, got {dispatched['provisional_cents']}"


# ─────────────────────────────────────────────────────────────
# Corner/calculations
# ─────────────────────────────────────────────────────────────

def test_subscription_fee_flat_ignores_headcount(api):
    """PRD §3.7: "Under FLAT billing, subscription_fee_cents equals plan.flat_fee_cents.
    No headcount computation, no volume discount."

    Design: Corner/calculations/subscription_fee_flat_ignores_headcount
    """
    from test_helpers import setup_active_subscription
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        plan_overrides={"tier": "FL-A", "billing_type": "FLAT", "flat_fee_cents": 8888,
                        "volume_discount_threshold_headcount": 10},
        client_overrides={"name": "Big-FL", "headcount": 1000},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
    inv = state["invoice"]
    assert inv["subscription_fee_cents"] == 8888, \
        f"expected flat fee 8888 regardless of headcount, got {inv['subscription_fee_cents']}"
    assert inv["total_cents"] == 8888, \
        f"total should equal fee (no consumption, no credit), got {inv['total_cents']}"


def test_subscription_fee_below_threshold_no_discount(api):
    """PRD §3.7: "If headcount is strictly less than the threshold, no discount is applied
    and the raw per-employee amount is used as-is."

    Design: Corner/calculations/subscription_fee_below_threshold_no_discount
    """
    from test_helpers import setup_active_subscription
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        plan_overrides={
            "tier": "T-49-A", "billing_type": "PER_EMPLOYEE",
            "base_fee_cents": 1000, "per_employee_fee_cents": 200,
            "volume_discount_threshold_headcount": 50, "volume_discount_pct": 0.10,
        },
        client_overrides={"name": "T49-A", "headcount": 49},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
    inv = state["invoice"]
    # raw = 200 * 49 = 9800; no discount (49 < 50); fee = 1000 + 9800 = 10800
    assert inv["subscription_fee_cents"] == 10800, \
        f"below threshold: expected 10800, got {inv['subscription_fee_cents']}"


def test_delivery_bulk_discount_boundary_at_100(api):
    """PRD §3.5: "The per-line bulk discount is zero when the line's planned_units is
    strictly less than 100. When planned_units is at least 100 (the boundary is inclusive),
    the per-line discount is the raw amount multiplied by 0.05, rounded to integer cents
    using round-half-up. This is a five-percent discount on bulky line items."

    Design: Corner/calculations/delivery_charge_bulk_discount_boundary_at_100
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BK-A", billing_type="FLAT", flat_fee_cents=1000,
                      volume_discount_threshold_headcount=10)
    client = create_client(name="BulkCo-BK", headcount=5)
    loc = create_location(client["id"], name="MM-BK", kind="MICRO_MARKET",
                          capacity_units=200, service_fee_bps=500)
    prod = create_product(sku="P-BK-A", name="PB", category="SNACK", unit_cost_cents=50)
    create_par_level(loc["id"], prod["id"], 100)
    sub = create_subscription(client["id"], plan["id"], client["version"])
    activate_subscription(sub["id"])
    rc = get_first_rotation_cycle(sub["id"])
    delv_res = api.create_delivery(
        rc["id"],
        {"location_id": loc["id"], "scheduled_at": "2026-06-02T00:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    delv = validate_success(delv_res, expected_status=201)
    dispatched = dispatch_delivery(delv["id"])
    # raw = 100*50 = 5000; MICRO_MARKET fee = round_half_up(5000*0.05)=250;
    # bulk disc = round_half_up(5000*0.05)=250; line = 5000+250-250 = 5000.
    assert dispatched["provisional_cents"] == 5000, \
        f"boundary planned=100 must apply bulk discount; expected 5000, got {dispatched['provisional_cents']}"
