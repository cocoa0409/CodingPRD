"""Quoted order-date pricing versus invoiced ship-date pricing, and the two
delinquency-scoring variants reported side by side by the credit summary."""
from test_helpers import (
    CREDIT_MANAGER,
    add_line,
    add_price_file_line,
    allocate_order,
    api_client,
    approve_credit,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_certification,
    make_inventory,
    make_part,
    make_price_file,
    make_pricing_tier,
    open_will_call_order,
    pay_order,
    publish_price_file,
    read_claim,
    read_line,
    read_order,
    read_part,
    read_return_authorization,
    receive_return,
    record_oem_outcome,
    request_return,
    decide_return,
    make_claim,
    submit_claim,
    set_clock,
    fulfill_order,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _order_shipped_after_a_price_rise():
    """A will-call order for three pumps is allocated at the quoted price, then
    a price file raises the catalog price before the order is handed over."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    part = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, part, on_hand_units=10, reorder_point=2)

    order = open_will_call_order(account, branch, purchase_order_ref="PO-1001")
    line = add_line(order, part, quantity=3)
    approve_credit(order, decision_note="within limit")
    allocate_order(order, branch)

    price_file = make_price_file(20260801, effective_at="2026-08-01T00:00:00Z")
    add_price_file_line(price_file, part, 15999)
    publish_price_file(price_file["id"])

    return {
        "branch": branch, "part": part, "account": account,
        "order": order, "line": line,
    }


def _account_with_aged_and_recent_penalties():
    """One denied claim 203 days old, one credited no-longer-needed return 198
    days old, and one denied claim 31 days old, observed at 2026-08-01."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    pump = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    motor = make_part(
        part_number="W10-MOTOR", oem_code="WHIRLPOOL", description="Drive motor",
        category="MECHANICAL", list_price_cents=128000, weight_grams=9000,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )

    set_clock("2026-01-10T00:00:00Z")
    cert = make_certification(
        account, technician_name="Dana Ruiz", oem_code="WHIRLPOOL",
        cert_level="SEALED_SYSTEM",
        training_completed_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    make_inventory(branch, pump, on_hand_units=10, reorder_point=2)
    make_inventory(branch, motor, on_hand_units=10, reorder_point=2)

    order_j = open_will_call_order(account, branch, purchase_order_ref="PO-J")
    line_j1 = add_line(order_j, pump, quantity=1)
    line_j2 = add_line(order_j, motor, quantity=1)
    approve_credit(order_j)
    allocate_order(order_j, branch)
    fulfill_order(order_j, branch, tracking_ref="WILLCALL-J")
    pay_order(order_j, 112799, payment_reference="ACH-J")

    set_clock("2026-01-15T00:00:00Z")
    ra_j1 = request_return(account, line_j1, 1, "NO_LONGER_NEEDED", branch)
    decide_return(ra_j1["id"], "APPROVE")
    receive_return(ra_j1["id"], branch)

    claim_j = make_claim(
        account, line_j2, defect_code="BEARING_NOISE",
        appliance_model_number="WRF535SWHZ",
    )
    submit_claim(claim_j["id"], oem_reference="WP-J-001")
    record_oem_outcome(claim_j["id"], "DENIED", oem_note="wear item")

    set_clock("2026-07-01T00:00:00Z")
    order_k = open_will_call_order(account, branch, purchase_order_ref="PO-K")
    line_k1 = add_line(order_k, pump, quantity=1)
    approve_credit(order_k)
    allocate_order(order_k, branch)
    fulfill_order(order_k, branch, tracking_ref="WILLCALL-K")
    pay_order(order_k, 10399, payment_reference="ACH-K")

    claim_k = make_claim(
        account, line_k1, defect_code="SEIZED_PUMP",
        appliance_model_number="WRF535SWHZ",
    )
    submit_claim(claim_k["id"], oem_reference="WP-K-001")
    record_oem_outcome(claim_k["id"], "DENIED", oem_note="no defect found")

    set_clock("2026-08-01T00:00:00Z")
    return {
        "account": account, "cert": cert,
        "ra_j1": ra_j1, "claim_j": claim_j, "claim_k": claim_k,
    }


# ---------------------------------------------------------------------------
# Order-date basis versus ship-date basis
# ---------------------------------------------------------------------------

class TestQuotedVersusInvoicedLinePricing:

    def test_quoted_line_price_is_untouched_by_a_price_file_published_before_shipment(self):
        """PRD §3.4: "Multiply the part's `list_price_cents` by one minus the
        effective discount and round the result half up to a whole cent; that is
        the line's `unit_price_cents`."
        PRD §3.4: "A later price-file publication changes the catalog but never
        rewrites an existing line's `unit_price_cents` or `extended_price_cents`,
        and a later tier reassignment never reprices an existing line either."
        PRD §3.6: "A `WILL_CALL` order never carries freight at all: its
        `freight_cents` is zero, full stop, because the customer collects."

        Design: Difficulty/dual_variant_calc/order_pricing_quoted_at_order_date_vs_invoiced_at_ship_date
        """
        world = _order_shipped_after_a_price_rise()

        response = api_client.fulfill_part_order(
            world["order"]["id"],
            {"tracking_ref": "WILLCALL-1001"},
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_success(response, 200)

        part = read_part(world["part"]["id"])
        assert part["list_price_cents"] == 15999, (
            "the published price file must have moved the catalog list price"
        )

        line = read_line(world["line"]["id"])
        assert line["unit_price_cents"] == 10399, (
            f"Expected the quoted unit price 10399 to survive the publication, "
            f"got {line['unit_price_cents']}"
        )
        assert line["extended_price_cents"] == 31197

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 31197
        assert order["freight_cents"] == 0
        assert order["total_cents"] == 31197

    def test_ship_date_repricing_writes_the_invoiced_fields_and_the_price_variance(self):
        """PRD §3.6: "Every `ALLOCATED` line moves `ALLOCATED → SHIPPED` and is
        repriced on the **`SHIP_DATE` basis**: the same discount arithmetic as
        §3.4 runs again, but reading the resolved part's **current**
        `list_price_cents` and the account's **current** pricing tier, and writing
        the result into `invoiced_unit_price_cents` rather than
        `unit_price_cents`."
        PRD §3.6: "The order recomputes `core_deposit_total_cents` and
        `freight_cents`, then locks `invoiced_total_cents` as the ship-date
        subtotal plus `core_deposit_total_cents` plus `freight_cents`, and records
        `price_variance_cents` as `invoiced_total_cents` minus `total_cents` —
        zero for as long as `invoiced_total_cents` is null."
        PRD §3.6: "The order's `pricing_basis` flips from `ORDER_DATE` to
        `SHIP_DATE`."

        Design: Difficulty/dual_variant_calc/order_pricing_quoted_at_order_date_vs_invoiced_at_ship_date
        """
        world = _order_shipped_after_a_price_rise()
        fulfill_order(world["order"], world["branch"], tracking_ref="WILLCALL-1001")

        line = read_line(world["line"]["id"])
        assert line["invoiced_unit_price_cents"] == 12799, (
            f"Expected ship-date unit price 12799, got "
            f"{line['invoiced_unit_price_cents']}"
        )

        order = read_order(world["order"]["id"])
        assert order["invoiced_total_cents"] == 38397, (
            f"Expected invoiced_total_cents 38397, got "
            f"{order['invoiced_total_cents']}"
        )
        assert order["price_variance_cents"] == 7200, (
            f"Expected price_variance_cents 7200, got {order['price_variance_cents']}"
        )
        assert order["pricing_basis"] == "SHIP_DATE"
        assert order["settlement_status"] == "INVOICED"


# ---------------------------------------------------------------------------
# Rolling-window versus lifetime delinquency scoring
# ---------------------------------------------------------------------------

class TestRollingVersusLifetimeDelinquency:

    def test_credit_summary_reports_diverging_rolling_and_lifetime_scores(self):
        """PRD §3.5: "**Delinquency scoring** starts every account at a base of
        80 points and adjusts from there. Fifteen points are deducted for each
        overdue invoice, twenty for each denied warranty claim, and eight for each
        credited no-longer-needed return. A bonus of five points is added for each
        currently effective technician certification, but that bonus is capped at
        fifteen points no matter how many certifications the account holds."
        PRD §3.5: "The **rolling** variant counts a penalty row only when its
        anchor timestamp falls within 180 days of the logical clock: the anchor is
        `fulfilled_at` for an overdue invoice, `submitted_at` for a denied claim,
        and `received_at` for a no-longer-needed return."
        PRD §3.5: "The **lifetime** variant applies no window filter at all and
        counts every qualifying row regardless of age, which means that on
        identical data it yields a score less than or equal to the rolling variant
        whenever any penalty row predates the window."

        Design: Difficulty/dual_variant_calc/delinquency_score_rolling_window_vs_lifetime_divergence
        """
        world = _account_with_aged_and_recent_penalties()

        response = api_client.get_credit_summary(
            world["account"]["id"], CREDIT_MANAGER
        )
        summary = validate_success(response, 200)

        assert summary["delinquency_score_rolling"] == 65, (
            f"Expected rolling score 65 (80 - 20 for the one in-window denied "
            f"claim + 5 cert bonus), got {summary['delinquency_score_rolling']}"
        )
        assert summary["delinquency_score_lifetime"] == 37, (
            f"Expected lifetime score 37 (80 - 20 - 20 - 8 + 5), got "
            f"{summary['delinquency_score_lifetime']}"
        )
        assert read_claim(world["claim_j"]["id"])["claim_status"] == "OEM_DENIED"
        assert read_claim(world["claim_k"]["id"])["claim_status"] == "OEM_DENIED"

    def test_credit_summary_exposure_is_floored_at_zero_once_everything_is_paid(self):
        """PRD §3.5: "Subtract the credits from the open exposure — from the
        aggregate, never from individual orders — and floor the result at zero, so
        an over-credited account reads exactly 0 rather than a negative number."
        PRD §3.9: "Multiply it by `gross_return_cents` and round half up to a
        whole cent to get `restocking_fee_cents`, then take `credit_amount_cents`
        as `gross_return_cents` minus `restocking_fee_cents` — an exact integer
        remainder, so fee plus credit always reconstitutes the gross exactly."

        Design: Difficulty/dual_variant_calc/delinquency_score_rolling_window_vs_lifetime_divergence
        """
        world = _account_with_aged_and_recent_penalties()

        response = api_client.get_credit_summary(
            world["account"]["id"], CREDIT_MANAGER
        )
        summary = validate_success(response, 200)

        assert summary["credit_used_cents"] == 0, (
            f"Expected exposure floored at 0, got {summary['credit_used_cents']}"
        )
        assert summary["core_liability_cents"] == 0
        assert summary["effective_cert_count"] == 1
        assert summary["open_order_count"] == 0

        ra = read_return_authorization(world["ra_j1"]["id"])
        assert ra["restocking_fee_cents"] == 1040, (
            f"Expected restocking_fee_cents 1040, got {ra['restocking_fee_cents']}"
        )
        assert ra["credit_amount_cents"] == 9359, (
            f"Expected credit_amount_cents 9359, got {ra['credit_amount_cents']}"
        )
