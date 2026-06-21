"""Non-linear state machines (promo cycle, visit fork) and transitive cascades
(cancel depth-3, downgrade depth-2).
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_field_technician_headers,
    create_package,
    create_premium_channel,
    create_equipment_model,
    create_rsf_rule,
    create_promotion_offer,
    create_technician,
    create_active_account,
    attach_add_on,
    assign_equipment,
    apply_promotion,
    downgrade,
    get_account,
    account_version,
    set_clock,
    schedule_visit,
    dispatch_visit,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ===========================================================================
# non_linear_state_machine / account_promo_cycle_rolledback_to_promoactive_winback
# ===========================================================================
def test_advance_cycle_rolls_promo_back_to_rolled_back(api):
    """PRD §3.6: "The first is **time-based**: when a `BillingAdmin` advances the billing cycle
    (§3.9) and the new tenure reaches or exceeds the active application's `rollback_at_tenure`,
    the application is rolled back, its `discount_cents_snapshot` contribution drops to 0, the
    recurring charge is recomputed back up to catalog price, and the account `version` increments."

    Design: Difficulty/non_linear_state_machine/account_promo_cycle_rolledback_to_promoactive_winback
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    offer = create_promotion_offer(
        code="WB", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.2, promo_months=1,
        requires_min_rank=2, rollback_protected=True,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    apply_promotion(account["id"], offer["id"])
    advanced = validate_success(api.advance_cycle(account["id"], ADMIN), 200)
    assert advanced["promo_status"] == "ROLLED_BACK"


def test_winback_reapplication_returns_promo_to_promo_active(api):
    """PRD §3.6: "A successful win-back creates a new `PromotionApplication` with `is_winback`
    set to true, moves `promo_status` from `ROLLED_BACK` back to `PROMO_ACTIVE`, recomputes the
    recurring charge, and increments the version."

    Design: Difficulty/non_linear_state_machine/account_promo_cycle_rolledback_to_promoactive_winback
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    offer = create_promotion_offer(
        code="WB", discount_kind="PERCENT_OFF_PACKAGE", percent_off=0.2, promo_months=1,
        requires_min_rank=2, rollback_protected=True,
    )
    account, _ = create_active_account(package, service_state_code="CA")
    apply_promotion(account["id"], offer["id"])
    rolled = validate_success(api.advance_cycle(account["id"], ADMIN), 200)
    assert rolled["promo_status"] == "ROLLED_BACK"

    v2 = account_version(account["id"])
    winback = validate_success(
        api.apply_promotion(
            account["id"], {"promotion_offer_id": offer["id"], "expected_account_version": v2}, CSA
        ),
        201,
    )
    assert winback["status"] == "ACTIVE"
    assert winback["is_winback"] is True
    assert get_account(account["id"])["promo_status"] == "PROMO_ACTIVE"


# ===========================================================================
# non_linear_state_machine / service_visit_branch_completed_vs_noshow
# ===========================================================================
def test_install_completion_waives_truck_roll_fee(api):
    """PRD §3.8: "On completion, an `INSTALL` visit is waived and charges 0, while a `SERVICE`
    visit charges the standard truck-roll fee of 99 dollars (9,900 cents)."

    Design: Difficulty/non_linear_state_machine/service_visit_branch_completed_vs_noshow
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="Tech One", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    visit = schedule_visit(
        account["id"], tech["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", visit_type="INSTALL"
    )
    dispatch_visit(account["id"], visit["id"], tech["id"])
    completed = validate_success(
        api.complete_service_visit(
            account["id"], visit["id"], {"outcome_note": "installed ok"},
            make_field_technician_headers(tech["id"]),
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["truck_roll_fee_cents"] == 0


def test_noshow_charges_full_truck_roll_fee_for_install(api):
    """PRD §3.8: "A no-show, regardless of whether the visit was an `INSTALL` or a `SERVICE`,
    always charges the full standard truck-roll fee of 9,900 cents."

    Design: Difficulty/non_linear_state_machine/service_visit_branch_completed_vs_noshow
    """
    set_clock("2026-06-01T00:00:00Z")
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    tech = create_technician(name="Tech One", home_state_code="CA")
    account, _ = create_active_account(package, service_state_code="CA")
    visit = schedule_visit(
        account["id"], tech["id"], "2026-06-02T13:00:00Z", "2026-06-02T14:00:00Z", visit_type="INSTALL"
    )
    dispatch_visit(account["id"], visit["id"], tech["id"])
    noshow = validate_success(
        api.no_show_service_visit(account["id"], visit["id"], make_field_technician_headers(tech["id"])),
        200,
    )
    assert noshow["status"] == "NO_SHOW"
    assert noshow["truck_roll_fee_cents"] == 9900


# ===========================================================================
# transitive_cascade / cancel_cascade_subscription_addon_equipment_depth3
# ===========================================================================
def test_cancel_cascades_addon_drop_and_equipment_unreturned(api):
    """PRD §3.3: "That subscription termination drops **every** `ACTIVE` add-on subscription
    to `DROPPED` with a `drop_reason` of `CANCELLED`; each such drop recomputes the account's
    recurring charge."
    PRD §3.3: "Every equipment lease still in `ASSIGNED` status that has not been returned
    transitions to `UNRETURNED`, and its `unreturned_charge_cents` is set to the equipment
    model's `replacement_cost_cents` multiplied by the lease `quantity`; the lease's monthly
    contribution is removed from the recurring charge."

    Design: Difficulty/transitive_cascade/cancel_cascade_subscription_addon_equipment_depth3
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    dvr = create_equipment_model(model_code="DVR-4K", kind="DVR", monthly_lease_cents=1000, replacement_cost_cents=30000)
    account, _ = create_active_account(package, service_state_code="CA", contract_term_months=0)
    add_on = attach_add_on(account["id"], premium["id"])
    lease = assign_equipment(account["id"], dvr["id"], quantity=1)

    cancelled = validate_success(api.cancel_account(account["id"], CSA), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    add_on_after = validate_success(api.get_add_on(add_on["id"], CSA), 200)
    assert add_on_after["status"] == "DROPPED"
    assert add_on_after["drop_reason"] == "CANCELLED"

    lease_after = validate_success(api.get_equipment_lease(lease["id"], CSA), 200)
    assert lease_after["status"] == "UNRETURNED"
    assert lease_after["unreturned_charge_cents"] == 30000


def test_cancel_recomputes_monthly_recurring_to_zero(api):
    """PRD §3.3: "The account's `monthly_recurring_cents` is recomputed to 0, since no live
    recurring line items remain."

    Design: Difficulty/transitive_cascade/cancel_cascade_subscription_addon_equipment_depth3
    """
    package = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    dvr = create_equipment_model(model_code="DVR-4K", kind="DVR", monthly_lease_cents=1000, replacement_cost_cents=30000)
    account, _ = create_active_account(package, service_state_code="CA", contract_term_months=0)
    attach_add_on(account["id"], premium["id"])
    assign_equipment(account["id"], dvr["id"], quantity=1)

    cancelled = validate_success(api.cancel_account(account["id"], CSA), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["monthly_recurring_cents"] == 0


# ===========================================================================
# transitive_cascade / downgrade_cascade_incompatible_addon_recompute_depth2
# ===========================================================================
def test_downgrade_drops_incompatible_addon(api):
    """PRD §3.4: "First, every `ACTIVE` add-on subscription whose premium channel has a
    `min_package_rank` greater than the new package's rank is dropped to `DROPPED` with a
    `drop_reason` of `INCOMPATIBLE_DOWNGRADE`, because the lower tier no longer supports it;
    each such incompatible drop recomputes the recurring charge."

    Design: Difficulty/transitive_cascade/downgrade_cascade_incompatible_addon_recompute_depth2
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    plus = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    account, subscription = create_active_account(plus, service_state_code="CA")
    add_on = attach_add_on(account["id"], premium["id"])

    downgrade(account["id"], subscription["id"], basic["id"])

    add_on_after = validate_success(api.get_add_on(add_on["id"], CSA), 200)
    assert add_on_after["status"] == "DROPPED"
    assert add_on_after["drop_reason"] == "INCOMPATIBLE_DOWNGRADE"


def test_downgrade_recomputes_monthly_recurring_to_basic_base(api):
    """PRD §3.7: "The account's `monthly_recurring_cents` is the single derived figure that
    every commercial action recomputes — on subscription activation, downgrade, and upgrade;
    on add-on attach and drop; on equipment assign and return; on promotion apply, rollback,
    and win-back; and on suspend, reactivate, and cancel."

    Design: Difficulty/transitive_cascade/downgrade_cascade_incompatible_addon_recompute_depth2
    """
    basic = create_package(tier_code="BASIC", monthly_fee_cents=3000, rank=1, channel_count=60)
    plus = create_package(tier_code="PLUS", monthly_fee_cents=6000, rank=2)
    premium = create_premium_channel(code="HBOX", kind="PREMIUM", monthly_fee_cents=1500, min_package_rank=2)
    create_rsf_rule(state_code="CA", base_fee_cents=800, premier_surcharge_cents=500)
    account, subscription = create_active_account(plus, service_state_code="CA")
    attach_add_on(account["id"], premium["id"])

    downgrade(account["id"], subscription["id"], basic["id"])
    # BASIC base 3000 + rsf 800 (rank1, no surcharge); add-on dropped -> 3800
    net = get_account(account["id"])["monthly_recurring_cents"]
    assert net == 3800, f"post-downgrade net expected 3800, got {net}"
