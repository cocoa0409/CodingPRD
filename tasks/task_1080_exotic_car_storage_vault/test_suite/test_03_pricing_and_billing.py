"""Pricing and billing calculations: storage fee cap, dual-variant proration,
service-order cost, per-line tax rounding, money invariants, battery alert
(PRD §2.6, §3.4, §3.9)."""
from test_helpers import (
    validate_success, TEST_USERS,
)
from test_helpers import fixtures as fx

VM = TEST_USERS["vault_manager_headers"]
CT = TEST_USERS["concierge_tech_headers"]
BA = TEST_USERS["billing_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / storage_proration_full_month_vs_prorated
# ---------------------------------------------------------------------------
def test_storage_invoice_full_month_charges_whole_rate(api):
    """PRD §3.9: "Under `FULL_MONTH` — the recurring bill while the agreement is
    still `IN_STORAGE` or `CHECKED_OUT` — the storage line is simply the agreement's
    snapshot `monthly_rate_cents`, the whole monthly rate regardless of days."
    PRD §3.9: "Add a climate surcharge that depends on the unit's class: a `CLIMATE`
    unit adds 5,000 cents".

    Design: Difficulty/dual_variant_calc/storage_proration_full_month_vs_prorated
    """
    ctx = fx.setup_stored_agreement(api, unit_class="CLIMATE", monthly_rate_cents=40000,
                                    membership_tier="GOLD")
    assert ctx["agreement"]["monthly_rate_cents"] == 40500
    inv = validate_success(api.generate_invoice(
        {"member_id": ctx["member_id"], "agreement_id": ctx["agreement_id"],
         "period_start_at": "2026-06-01T00:00:00Z", "period_end_at": "2026-07-01T00:00:00Z",
         "proration_mode": "FULL_MONTH"}, BA), 201)
    assert inv["subtotal_cents"] == 40500
    assert inv["total_cents"] == 43740


def test_storage_invoice_prorated_charges_days_over_thirty(api):
    """PRD §3.9: "Under `PRORATED` — the final bill after the agreement has closed and
    `days_stored` is known — the storage line is the snapshot monthly rate multiplied
    by the number of days stored capped at 30 (that is, the smaller of `days_stored`
    and 30), divided by 30, rounded half up to whole cents."
    PRD §3.3: "`days_stored` is computed as the whole number of days from `move_in_at`
    to `actual_move_out_at`, rounded down (floored) to a whole day".

    Design: Difficulty/dual_variant_calc/storage_proration_full_month_vs_prorated
    """
    ctx = fx.setup_stored_agreement(api, unit_class="CLIMATE", monthly_rate_cents=40000,
                                    membership_tier="GOLD")
    api.set_clock("2026-06-13T00:00:00Z", VM)
    closed = validate_success(api.terminate(ctx["agreement_id"], VM))
    assert closed["days_stored"] == 12
    inv = validate_success(api.generate_invoice(
        {"member_id": ctx["member_id"], "agreement_id": ctx["agreement_id"],
         "period_start_at": "2026-06-01T00:00:00Z", "period_end_at": "2026-07-01T00:00:00Z",
         "proration_mode": "PRORATED"}, BA), 201)
    assert inv["subtotal_cents"] == 16200
    assert inv["total_cents"] == 17496


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / service_order_estimate_vs_final_cost
# ---------------------------------------------------------------------------
def test_service_order_estimate_excludes_parts_at_approve(api):
    """PRD §3.9: "At approval, the provisional `estimated_cost_cents` is the base
    charge plus `estimated_labor_hours` multiplied by 12,000 cents per hour, rounded
    half up to whole cents — parts are excluded."
    PRD §3.9: "The base charge by `service_type` is: `DETAIL` 15,000 cents".

    Design: Difficulty/dual_variant_calc/service_order_estimate_vs_final_cost
    """
    ctx = fx.setup_approved_service_order(api, service_type="DETAIL", estimated_labor_hours=2.0)
    assert ctx["service_order"]["estimated_cost_cents"] == 39000


def test_service_order_final_cost_uses_actual_hours_and_parts(api):
    """PRD §3.9: "At completion, the final `final_cost_cents` is the base charge plus
    `actual_labor_hours` multiplied by 12,000 cents per hour, plus `parts_cents`,
    rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/service_order_estimate_vs_final_cost
    """
    ctx = fx.setup_in_progress_service_order(api, service_type="DETAIL",
                                             estimated_labor_hours=2.0)
    sid = ctx["service_order_id"]
    done = validate_success(api.complete_service_order(
        sid, {"actual_labor_hours": 2.5, "parts_cents": 8000}, CT))
    assert done["final_cost_cents"] == 53000
    assert done["estimated_cost_cents"] == 39000
    assert done["final_cost_cents"] != done["estimated_cost_cents"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / storage_fee_discount_cap_nonlinear
# ---------------------------------------------------------------------------
def test_storage_fee_platinum_showcase_discount_capped(api):
    """PRD §3.9: "Multiply the gross rate by the member's `tier_discount_pct` to get
    the raw discount, then cap the discount at a maximum of 20,000 cents — the applied
    discount is the smaller of the raw discount and 20,000 cents."
    PRD §3.9: "a `SHOWCASE` unit adds 12,000 cents".

    Design: Difficulty/combinatorial_formula/storage_fee_discount_cap_nonlinear
    """
    ctx = fx.setup_pending_agreement(api, unit_class="SHOWCASE", monthly_rate_cents=200000,
                                     membership_tier="PLATINUM", document=False)
    # gross 212000, raw discount 42400 clamped to 20000 -> 192000 (not uncapped 169600)
    assert ctx["agreement"]["monthly_rate_cents"] == 192000
    assert ctx["agreement"]["monthly_rate_cents"] != 169600


def test_storage_fee_silver_showcase_discount_uncapped(api):
    """PRD §3.9: "Start from the unit's base `monthly_rate_cents`. Add a climate
    surcharge that depends on the unit's class ... a `SHOWCASE` unit adds 12,000
    cents ... Multiply the gross rate by the member's `tier_discount_pct` to get the
    raw discount, then cap the discount at a maximum of 20,000 cents".

    Design: Difficulty/combinatorial_formula/storage_fee_discount_cap_nonlinear
    """
    ctx = fx.setup_pending_agreement(api, unit_class="SHOWCASE", monthly_rate_cents=200000,
                                     membership_tier="SILVER", document=False)
    # gross 212000, raw discount 0.05*212000 = 10600 (< 20000, not capped) -> 201400
    assert ctx["agreement"]["monthly_rate_cents"] == 201400


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / invoice_per_line_tax_rounding_order
# ---------------------------------------------------------------------------
def _setup_two_line_3130_invoice(api):
    ctx = fx.setup_stored_agreement(api, unit_class="STANDARD", monthly_rate_cents=3130,
                                    membership_tier="BRONZE")
    so = validate_success(api.create_service_order(
        {"agreement_id": ctx["agreement_id"], "service_type": "START_ENGINE",
         "estimated_labor_hours": 0}, VM), 201)
    validate_success(api.approve_service_order(so["id"], {"scheduled_at": "2026-06-02T09:00:00Z"}, VM))
    validate_success(api.start_service_order(so["id"], CT))
    validate_success(api.complete_service_order(so["id"], {"actual_labor_hours": 0, "parts_cents": 130}, CT))
    inv = validate_success(api.generate_invoice(
        {"member_id": ctx["member_id"], "agreement_id": ctx["agreement_id"],
         "period_start_at": "2026-06-01T00:00:00Z", "period_end_at": "2026-07-01T00:00:00Z",
         "proration_mode": "FULL_MONTH"}, BA), 201)
    return inv


def test_invoice_subtotal_and_total_two_lines(api):
    """PRD §3.9: "The `subtotal_cents` is the sum of all line amounts. The `tax_cents`
    is computed per line — each line's amount multiplied by the tax rate of 8 percent
    (0.08) and rounded half up to whole cents — and then those per-line tax figures
    are summed ... The `total_cents` is `subtotal_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/invoice_per_line_tax_rounding_order
    """
    inv = _setup_two_line_3130_invoice(api)
    assert inv["subtotal_cents"] == 6260
    assert inv["tax_cents"] == 500
    assert inv["total_cents"] == 6760


def test_invoice_per_line_tax_diverges_from_sum_then_round(api):
    """PRD §2.6: "For each line item, the line's tax is the line amount multiplied by
    the tax rate, rounded half up to whole cents; the invoice `tax_cents` is the sum
    of these per-line rounded tax figures. This is deliberately **not** the tax rate
    applied once to the invoice subtotal".

    Design: Difficulty/combinatorial_formula/invoice_per_line_tax_rounding_order
    """
    inv = _setup_two_line_3130_invoice(api)
    # per-line: round(3130*0.08)=250 twice -> 500; sum-then-round: round(6260*0.08)=501
    assert inv["tax_cents"] == 500
    assert inv["tax_cents"] != 501
    kinds = sorted((li["kind"], li["amount_cents"]) for li in inv["line_items"])
    assert ("SERVICE", 3130) in kinds
    assert ("STORAGE", 3130) in kinds


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / member_balance_conserved_on_issue_then_void
# ---------------------------------------------------------------------------
def test_issue_invoice_raises_charged_and_balance(api):
    """PRD §3.9: "A billing administrator **issues** a `DRAFT` invoice, advancing
    `DRAFT → ISSUED`; issuing sets `due_at` to 15 days after the issue moment ... and
    recomputes the member's `charged_cents`."
    PRD §3.9: "`account_balance_cents` is `charged_cents` minus `paid_cents`".

    Design: Difficulty/compensating_invariant/member_balance_conserved_on_issue_then_void
    """
    ctx = fx.setup_draft_invoice(api, monthly_rate_cents=50000, membership_tier="BRONZE")
    assert ctx["invoice"]["total_cents"] == 54000
    before = validate_success(api.get_member(ctx["member_id"], BA))
    assert before["charged_cents"] == 0 and before["account_balance_cents"] == 0
    validate_success(api.issue_invoice(ctx["invoice_id"], BA))
    after = validate_success(api.get_member(ctx["member_id"], BA))
    assert after["charged_cents"] == 54000
    assert after["account_balance_cents"] == 54000


def test_void_after_issue_restores_pre_issue_balance(api):
    """PRD §3.9: "A billing administrator **voids** an invoice from `DRAFT` or
    `ISSUED`, moving it to `VOID`; if it was `ISSUED`, voiding recomputes
    `charged_cents` to restore the member's pre-issue balance."

    Design: Difficulty/compensating_invariant/member_balance_conserved_on_issue_then_void
    """
    ctx = fx.setup_draft_invoice(api, monthly_rate_cents=50000, membership_tier="BRONZE")
    validate_success(api.issue_invoice(ctx["invoice_id"], BA))
    validate_success(api.void_invoice(ctx["invoice_id"], BA))
    after = validate_success(api.get_member(ctx["member_id"], BA))
    assert after["charged_cents"] == 0
    assert after["account_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: calculations / monitoring_low_battery_alert_threshold
# ---------------------------------------------------------------------------
def test_monitoring_low_battery_alert_below_threshold(api):
    """PRD §3.4: "Recording sets `last_battery_voltage` to that value and recomputes
    `low_battery_alert`, which becomes true when the most recent reading is below the
    minimum healthy battery voltage of 12.4 volts and false when the reading is at or
    above that threshold."

    Design: Corner/calculations/monitoring_low_battery_alert_threshold
    """
    ctx = fx.setup_stored_agreement(api, unit_class="CLIMATE", monthly_rate_cents=40000)
    mon = validate_success(api.create_monitoring(
        ctx["agreement_id"], {"monitor_type": "BATTERY_TENDER", "monthly_fee_cents": 5000}, CT), 201)
    updated = validate_success(api.record_reading(mon["id"], {"battery_voltage": 12.3}, CT))
    assert updated["last_battery_voltage"] == 12.3
    assert updated["low_battery_alert"] is True
