"""Pricing engine: dual-variant statement totals, per-line rounding order,
gross-then-discount evaluation order, and conserved monthly-recurring invariants.

All money is integer cents.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    create_package,
    create_premium_channel,
    create_equipment_model,
    create_rsf_rule,
    create_promotion_offer,
    create_active_account,
    create_prospect_account,
    activate_first_subscription,
    attach_add_on,
    assign_equipment,
    apply_promotion,
    get_account,
    account_version,
    issue_statement,
    api_client,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ===========================================================================
# dual_variant_calc / statement_full_vs_prorated_diverge
# ===========================================================================
def _seed_tx_account_all_items():
    """PLUS 5000c + SHOWX add-on 1505c + BOX lease 1000c, TX rsf 800c. Returns account id."""
    package = create_package(tier_code="PLUS", monthly_fee_cents=5000, rank=2)
    premium = create_premium_channel(code="SHOWX", kind="PREMIUM", monthly_fee_cents=1505, min_package_rank=2)
    equip = create_equipment_model(model_code="BOX-HD", kind="BOX", monthly_lease_cents=1000, replacement_cost_cents=30000)
    create_rsf_rule(state_code="TX", base_fee_cents=800, premier_surcharge_cents=500)
    account, _ = create_active_account(package, service_state_code="TX")
    attach_add_on(account["id"], premium["id"])
    assign_equipment(account["id"], equip["id"], quantity=1)
    return account["id"]


def test_full_cycle_statement_bills_all_line_items_at_catalog(api):
    """PRD §3.10: "In the **`FULL_CYCLE`** variant, each recurring line is billed at
    its full catalog value and `active_days`/`days_in_cycle` are ignored: `package_charge_cents`
    is the package amount, `addon_charge_cents` is the add-on amount, `equipment_charge_cents`
    is the equipment amount (including the one-time unreturned charge), `regional_sports_fee_cents`
    is the regional sports fee, and `promo_discount_cents` is the discount computed over the
    package plus add-on plus recurring-equipment plus regional-sports-fee base."

    Design: Difficulty/dual_variant_calc/statement_full_vs_prorated_diverge
    """
    account_id = _seed_tx_account_all_items()
    stmt = validate_success(
        api.issue_billing_statement(
            account_id, {"cycle_index": 0, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
        ),
        201,
    )
    # 5000 + 1505 + 1000 + 800 = 8305
    assert stmt["total_cents"] == 8305, f"FULL_CYCLE total expected 8305, got {stmt['total_cents']}"


def test_prorated_statement_diverges_from_full_cycle(api):
    """PRD §3.10: "For the same inputs this per-line prorated rounding deliberately yields
    a different total than the full-cycle variant."

    Design: Difficulty/dual_variant_calc/statement_full_vs_prorated_diverge
    """
    account_id = _seed_tx_account_all_items()
    full = validate_success(
        api.issue_billing_statement(
            account_id, {"cycle_index": 0, "proration_mode": "FULL_CYCLE", "days_in_cycle": 30}, ADMIN
        ),
        201,
    )
    prorated = validate_success(
        api.issue_billing_statement(
            account_id,
            {"cycle_index": 1, "proration_mode": "PRORATED", "days_in_cycle": 30, "active_days": 10},
            ADMIN,
        ),
        201,
    )
    # 1667 + 502 + 333 + 267 = 2769
    assert prorated["total_cents"] == 2769, f"PRORATED total expected 2769, got {prorated['total_cents']}"
    assert full["total_cents"] == 8305
    assert prorated["total_cents"] != full["total_cents"]


# ===========================================================================
# dual_variant_calc / promo_percent_vs_equipment_waiver_diverge
# ===========================================================================
def test_percent_off_package_discount_applies_to_package_only(api):
    """PRD §3.7: "For `PERCENT_OFF_PACKAGE`, the discount is the package base multiplied
    by the offer's `percent_off` fraction, rounded half up to whole cents. This applies to
    the package fee **only** — the add-on, equipment, and regional-sports-fee portions are
    untouched."

    Design: Difficulty/dual_variant_calc/promo_percent_vs_equipment_waiver_diverge
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    dvr = create_equipment_model(model_code="DVR-4K", kind="DVR", monthly_lease_cents=1000, replacement_cost_cents=30000)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    offer = create_promotion_offer(
        code="PCT25", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.25,
        promo_months=12, requires_min_rank=2, rollback_protected=False,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    attach_add_on(account["id"], premium["id"])
    assign_equipment(account["id"], dvr["id"], quantity=1)
    apply_promotion(account["id"], offer["id"])
    # gross = 6000 + 1500 + 1000 + 800 = 9300 ; discount = 25% of 6000 = 1500 ; net = 7800
    net = get_account(account["id"])["monthly_recurring_cents"]
    assert net == 7800, f"PERCENT_OFF_PACKAGE net expected 7800, got {net}"


def test_equipment_waiver_discount_equals_assigned_lease_sum(api):
    """PRD §3.7: "For `EQUIPMENT_WAIVER`, the discount equals the full sum of `monthly_lease_cents`
    across all `ASSIGNED` equipment leases, waiving the entire equipment portion."

    Design: Difficulty/dual_variant_calc/promo_percent_vs_equipment_waiver_diverge
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    dvr = create_equipment_model(model_code="DVR-4K", kind="DVR", monthly_lease_cents=1000, replacement_cost_cents=30000)
    box = create_equipment_model(model_code="BOX-HD", kind="BOX", monthly_lease_cents=500, replacement_cost_cents=20000)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    offer = create_promotion_offer(
        code="WAIVEQ", discount_kind="EQUIPMENT_WAIVER", percent_off=0, flat_off_cents=0,
        promo_months=12, requires_min_rank=2, rollback_protected=False,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    attach_add_on(account["id"], premium["id"])
    assign_equipment(account["id"], dvr["id"], quantity=2)   # 2000c
    assign_equipment(account["id"], box["id"], quantity=1)   # 500c -> lease sum 2500c
    apply_promotion(account["id"], offer["id"])
    # gross = 6000 + 1500 + 2500 + 800 = 10800 ; discount = 2500 (full lease) ; net = 8300
    net = get_account(account["id"])["monthly_recurring_cents"]
    assert net == 8300, f"EQUIPMENT_WAIVER net expected 8300, got {net}"


# ===========================================================================
# combinatorial_formula / statement_round_per_line_then_sum_order
# ===========================================================================
def test_prorated_statement_rounds_each_line_before_summing(api):
    """PRD §3.10: "**Each recurring line item is scaled by that factor and rounded half up
    to whole cents independently, before any summing** — never summed first and prorated after.
    Thus `package_charge_cents` is the package amount times the factor rounded half up;
    `addon_charge_cents` is the add-on amount times the factor rounded half up; the recurring
    portion of equipment is the recurring equipment amount times the factor rounded half up;
    `regional_sports_fee_cents` is the regional sports fee times the factor rounded half up;
    and `promo_discount_cents` is the discount computed over the **prorated** recurring base,
    rounded half up."

    Design: Difficulty/combinatorial_formula/statement_round_per_line_then_sum_order
    """
    account_id = _seed_tx_account_all_items()
    stmt = validate_success(
        api.issue_billing_statement(
            account_id,
            {"cycle_index": 0, "proration_mode": "PRORATED", "days_in_cycle": 30, "active_days": 10},
            ADMIN,
        ),
        201,
    )
    # factor 10/30: package round(5000/3)=1667 ; addon round(1505/3)=502
    assert stmt["package_charge_cents"] == 1667, f"package_charge expected 1667, got {stmt['package_charge_cents']}"
    assert stmt["addon_charge_cents"] == 502, f"addon_charge expected 502, got {stmt['addon_charge_cents']}"


def test_prorated_statement_total_uses_per_line_rounding(api):
    """PRD §3.10: "**Each recurring line item is scaled by that factor and rounded half up
    to whole cents independently, before any summing** — never summed first and prorated after."

    Design: Difficulty/combinatorial_formula/statement_round_per_line_then_sum_order
    """
    account_id = _seed_tx_account_all_items()
    stmt = validate_success(
        api.issue_billing_statement(
            account_id,
            {"cycle_index": 0, "proration_mode": "PRORATED", "days_in_cycle": 30, "active_days": 10},
            ADMIN,
        ),
        201,
    )
    # 1667 + 502 + 333 + 267 = 2769 (per-line) ; sum-then-prorate would give 2768
    assert stmt["total_cents"] == 2769, f"PRORATED per-line total expected 2769, got {stmt['total_cents']}"


# ===========================================================================
# combinatorial_formula / monthly_recurring_eval_order_gross_then_discount
# ===========================================================================
def test_flat_off_total_caps_discount_at_gross_floor_zero(api):
    """PRD §3.7: "For `FLAT_OFF_TOTAL`, the discount is the offer's `flat_off_cents`, but
    capped at the gross so that the net can never go below 0 — that is, the smaller of
    `flat_off_cents` and the gross."

    Design: Difficulty/combinatorial_formula/monthly_recurring_eval_order_gross_then_discount
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    offer = create_promotion_offer(
        code="BIGFLAT", discount_kind="FLAT_OFF_TOTAL", percent_off=0, flat_off_cents=9000,
        promo_months=6, requires_min_rank=2, rollback_protected=False,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    apply_promotion(account["id"], offer["id"])
    # gross = 6000 + 800 = 6800 ; flat 9000 capped at 6800 ; net = max(0, 6800-6800) = 0
    net = get_account(account["id"])["monthly_recurring_cents"]
    assert net == 0, f"FLAT_OFF_TOTAL net floored expected 0, got {net}"


def test_recurring_charge_never_negative_under_large_flat_off(api):
    """PRD §3.7: "The recurring charge is the gross minus the discount, but never less than 0
    (a negative result is clamped to 0)."

    Design: Difficulty/combinatorial_formula/monthly_recurring_eval_order_gross_then_discount
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    offer = create_promotion_offer(
        code="HUGEFLAT", discount_kind="FLAT_OFF_TOTAL", percent_off=0, flat_off_cents=9000,
        promo_months=6, requires_min_rank=2, rollback_protected=False,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    apply_promotion(account["id"], offer["id"])
    net = get_account(account["id"])["monthly_recurring_cents"]
    assert net >= 0, f"recurring charge must be clamped to >= 0, got {net}"
    assert net == 0


# ===========================================================================
# compensating_invariant / addon_attach_then_drop_conserves_monthly_recurring
# ===========================================================================
def test_addon_attach_then_drop_restores_monthly_recurring(api):
    """PRD §3.5: "An add-on may be **dropped** by user request — again by a `CustomerServiceAgent`
    or the owning `Subscriber` — which transitions it to `DROPPED` with a `drop_reason` of `USER`,
    recomputes the recurring charge, and increments the account `version`."

    Design: Difficulty/compensating_invariant/addon_attach_then_drop_conserves_monthly_recurring
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    account, _ = create_active_account(package, service_state_code="CA")
    net_before = get_account(account["id"])["monthly_recurring_cents"]
    assert net_before == 6800, f"pre-attach net expected 6800, got {net_before}"

    add_on = attach_add_on(account["id"], premium["id"])
    validate_success(api.drop_add_on(account["id"], add_on["id"], CSA), 200)

    net_after = get_account(account["id"])["monthly_recurring_cents"]
    assert net_after == 6800, f"post-drop net expected 6800, got {net_after}"
    assert net_after == net_before


def test_addon_drop_sets_user_drop_reason(api):
    """PRD §3.5: "An add-on may be **dropped** by user request ... which transitions it to
    `DROPPED` with a `drop_reason` of `USER`, recomputes the recurring charge, and increments
    the account `version`."

    Design: Difficulty/compensating_invariant/addon_attach_then_drop_conserves_monthly_recurring
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    account, _ = create_active_account(package, service_state_code="CA")
    add_on = attach_add_on(account["id"], premium["id"])
    dropped = validate_success(api.drop_add_on(account["id"], add_on["id"], CSA), 200)
    assert dropped["status"] == "DROPPED"
    assert dropped["drop_reason"] == "USER"


# ===========================================================================
# compensating_invariant / equipment_assign_then_return_conserves_monthly_recurring
# ===========================================================================
def test_equipment_assign_then_return_restores_monthly_recurring(api):
    """PRD §3.5: "A lease may be **returned** by a `CustomerServiceAgent` or a `FieldTechnician`,
    transitioning `ASSIGNED → RETURNED`; on return the lease's monthly contribution is removed
    from the recurring charge, `unreturned_charge_cents` stays 0, and the account `version`
    increments."

    Design: Difficulty/compensating_invariant/equipment_assign_then_return_conserves_monthly_recurring
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    dvr = create_equipment_model(model_code="DVR-4K", kind="DVR", monthly_lease_cents=1000, replacement_cost_cents=30000)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    account, _ = create_active_account(package, service_state_code="CA")
    net_before = get_account(account["id"])["monthly_recurring_cents"]
    assert net_before == 6800, f"pre-assign net expected 6800, got {net_before}"

    lease = assign_equipment(account["id"], dvr["id"], quantity=1)
    returned = validate_success(api.return_equipment_lease(account["id"], lease["id"], CSA), 200)
    assert returned["status"] == "RETURNED"

    net_after = get_account(account["id"])["monthly_recurring_cents"]
    assert net_after == 6800, f"post-return net expected 6800, got {net_after}"
    assert net_after == net_before


def test_equipment_return_keeps_unreturned_charge_zero(api):
    """PRD §3.5: "A lease may be **returned** by a `CustomerServiceAgent` or a `FieldTechnician`,
    transitioning `ASSIGNED → RETURNED`; on return the lease's monthly contribution is removed
    from the recurring charge, `unreturned_charge_cents` stays 0, and the account `version`
    increments."

    Design: Difficulty/compensating_invariant/equipment_assign_then_return_conserves_monthly_recurring
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    dvr = create_equipment_model(model_code="DVR-4K", kind="DVR", monthly_lease_cents=1000, replacement_cost_cents=30000)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    account, _ = create_active_account(package, service_state_code="CA")
    lease = assign_equipment(account["id"], dvr["id"], quantity=1)
    returned = validate_success(api.return_equipment_lease(account["id"], lease["id"], CSA), 200)
    assert returned["status"] == "RETURNED"
    assert returned["unreturned_charge_cents"] == 0
