"""Transitive cascades (deem-total-loss depth-3, cancel depth-2), the repair authorization
cap boundary, and the shop-active cross-entity gate on repair acceptance.

Design queue A: transitive_cascade, resource_temporal_overlap (repair cap),
cross_entity_state_dependency (repair accept requires active shop).
Design queue B: validations (repair exceeds auth).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    create_repair_shop,
    create_policyholder,
    create_appraisal,
    create_policy,
    create_scheduled_item,
    bind_policy,
    pay_premium,
    file_claim,
    setup_active_policy_with_item,
    setup_repair_order_assigned,
    setup_repair_order_in_progress,
    make_policyholder_headers,
    make_repair_shop_headers,
)

_UW = TEST_USERS["underwriter_headers"]
_CA = TEST_USERS["claims_adjuster_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Queue A: transitive_cascade — deem_total_loss depth >= 3
# ─────────────────────────────────────────────────────────────────────────

def test_deem_total_loss_cascades_to_item_removal_and_premium_recompute(api):
    """PRD §3.14: "This upgrade reclassifies the claim's loss_type to TOTAL_LOSS, recomputes
    settlement_cents along the full-item-value total-loss path of §3.12, removes the
    referenced scheduled item by transitioning it from SUSPENDED to REMOVED, and recomputes
    the policy's total_insured_value_cents and annual_premium_cents against the reduced item
    set."

    Design: Difficulty/transitive_cascade/deem_total_loss_cascade_depth3
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    create_risk_zone(zip_prefix="200", risk_band="HIGH",
                     rate_per_thousand_cents=200, catastrophe_loaded=True)
    shop = create_repair_shop(name="InNet Jeweler", service_zip="10005", in_network=True)
    ph = create_policyholder(email="dc@x.com", residence_zip="10001")
    appraisal = create_appraisal(ph["id"], appraised_value_cents=3000000,
                                 effective_date_iso="2026-01-10T00:00:00Z")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    ring = create_scheduled_item(policy["id"], description="Ring", category="RING",
                                 location_zip="10001", scheduled_value_cents=1000000)
    create_scheduled_item(policy["id"], description="Watch", category="WATCH",
                          location_zip="20001", scheduled_value_cents=3000000,
                          appraisal_id=appraisal["id"])
    bind_policy(policy["id"])
    pay_premium(policy["id"], ph["id"])

    claim = file_claim(policy["id"], ring["id"], peril="ACCIDENTAL_DAMAGE",
                       loss_type="PARTIAL_DAMAGE", claimed_amount_cents=300000)
    rev = get_success_data(api.start_review_claim(policy["id"], claim["id"], _CA))
    validate_success(api.approve_claim(policy["id"], claim["id"],
                                       {"expected_claim_version": rev["version"]}, _CA), 200)
    validate_success(
        api.assign_repair_order(policy["id"], claim["id"], {"repair_shop_id": shop["id"]}, _CA),
        201)
    validate_success(
        api.accept_repair_order(policy["id"], claim["id"], make_repair_shop_headers(shop["id"])),
        200)

    # Trigger: deem total loss.
    validate_success(
        api.deem_total_loss_repair_order(policy["id"], claim["id"], _CA), 200)

    claim_after = validate_success(api.get_claim(claim["id"], _CA), 200)
    assert claim_after["loss_type"] == "TOTAL_LOSS"
    assert claim_after["status"] == "SETTLED"

    ring_after = validate_success(api.get_scheduled_item(ring["id"], _UW), 200)
    assert ring_after["item_status"] == "REMOVED"

    policy_after = validate_success(api.get_policy(policy["id"], _UW), 200)
    assert policy_after["total_insured_value_cents"] == 3000000
    assert policy_after["annual_premium_cents"] == 12264


def test_deem_total_loss_removes_only_claimed_item(api):
    """PRD §3.14: "removes the referenced scheduled item by transitioning it from SUSPENDED
    to REMOVED, and recomputes the policy's total_insured_value_cents and annual_premium_cents
    against the reduced item set."
    PRD §3.4: "The policy's total_insured_value_cents is the sum of current_value_cents over
    those same ACTIVE-or-SUSPENDED items."

    Design: Difficulty/transitive_cascade/deem_total_loss_cascade_depth3
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    create_risk_zone(zip_prefix="200", risk_band="HIGH",
                     rate_per_thousand_cents=200, catastrophe_loaded=True)
    shop = create_repair_shop(name="InNet2", service_zip="10005", in_network=True)
    ph = create_policyholder(email="dc2@x.com", residence_zip="10001")
    appraisal = create_appraisal(ph["id"], appraised_value_cents=3000000,
                                 effective_date_iso="2026-01-10T00:00:00Z")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    ring = create_scheduled_item(policy["id"], description="Ring", category="RING",
                                 location_zip="10001", scheduled_value_cents=1000000)
    watch = create_scheduled_item(policy["id"], description="Watch", category="WATCH",
                                  location_zip="20001", scheduled_value_cents=3000000,
                                  appraisal_id=appraisal["id"])
    bind_policy(policy["id"])
    pay_premium(policy["id"], ph["id"])

    claim = file_claim(policy["id"], ring["id"], peril="ACCIDENTAL_DAMAGE",
                       loss_type="PARTIAL_DAMAGE", claimed_amount_cents=300000)
    rev = get_success_data(api.start_review_claim(policy["id"], claim["id"], _CA))
    validate_success(api.approve_claim(policy["id"], claim["id"],
                                       {"expected_claim_version": rev["version"]}, _CA), 200)
    validate_success(
        api.assign_repair_order(policy["id"], claim["id"], {"repair_shop_id": shop["id"]}, _CA),
        201)
    validate_success(
        api.accept_repair_order(policy["id"], claim["id"], make_repair_shop_headers(shop["id"])),
        200)
    validate_success(api.deem_total_loss_repair_order(policy["id"], claim["id"], _CA), 200)

    watch_after = validate_success(api.get_scheduled_item(watch["id"], _UW), 200)
    assert watch_after["item_status"] == "ACTIVE"
    policy_after = validate_success(api.get_policy(policy["id"], _UW), 200)
    assert policy_after["total_insured_value_cents"] == 3000000


# ─────────────────────────────────────────────────────────────────────────
# Queue A: transitive_cascade — cancel depth >= 2
# ─────────────────────────────────────────────────────────────────────────

def test_cancel_policy_removes_all_scheduled_items(api):
    """PRD §3.8: "When cancellation proceeds, coverage_status becomes CANCELLED and every
    scheduled item on the policy transitions to item_status REMOVED."

    Design: Difficulty/transitive_cascade/cancel_policy_cascade_depth2
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    ph = create_policyholder(email="cx@x.com", residence_zip="10001")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    it1 = create_scheduled_item(policy["id"], description="Ring 1", category="RING",
                                location_zip="10001", scheduled_value_cents=1000000)
    it2 = create_scheduled_item(policy["id"], description="Ring 2", category="RING",
                                location_zip="10001", scheduled_value_cents=800000)
    bind_policy(policy["id"])
    pay_premium(policy["id"], ph["id"])

    cancelled = validate_success(api.cancel_policy(policy["id"], _UW), 200)
    assert cancelled["coverage_status"] == "CANCELLED"
    assert validate_success(api.get_scheduled_item(it1["id"], _UW), 200)["item_status"] == "REMOVED"
    assert validate_success(api.get_scheduled_item(it2["id"], _UW), 200)["item_status"] == "REMOVED"


def test_cancel_active_policy_transitions_to_cancelled(api):
    """PRD §3.8: "Cancellation is available from QUOTED, BOUND, or ACTIVE, and CANCELLED is
    terminal."
    PRD §3.8: "every scheduled item on the policy transitions to item_status REMOVED."

    Design: Difficulty/transitive_cascade/cancel_policy_cascade_depth2
    """
    ctx = setup_active_policy_with_item()
    cancelled = validate_success(api.cancel_policy(ctx["policy"]["id"], _UW), 200)
    assert cancelled["coverage_status"] == "CANCELLED"
    item = validate_success(api.get_scheduled_item(ctx["item"]["id"], _UW), 200)
    assert item["item_status"] == "REMOVED"


# ─────────────────────────────────────────────────────────────────────────
# Queue A: resource_temporal_overlap — repair cost within authorized cap
# ─────────────────────────────────────────────────────────────────────────

def test_repair_complete_at_exact_authorized_cap_closes(api):
    """PRD §3.14: "The reported cost must not exceed the order's authorized_amount_cents, or
    completion is rejected with ERR_REPAIR_EXCEEDS_AUTH."
    PRD §3.14: "A valid completion moves the order to REPAIRED and then automatically to
    CLOSED, and that closure cascades upward: the parent claim moves from APPROVED to SETTLED,
    and the referenced scheduled item is unlocked from SUSPENDED back to ACTIVE."

    Design: Difficulty/resource_temporal_overlap/repair_cost_within_authorized_cap
    """
    ctx = setup_repair_order_in_progress(shop_in_network=True, claimed_amount_cents=300000)
    pol, claim, shop, item = ctx["policy"], ctx["claim"], ctx["shop"], ctx["item"]
    # authorized cap == settlement 275,000; report exactly 275,000 (inclusive cap).
    assert ctx["repair_order"]["authorized_amount_cents"] == 275000

    completed = validate_success(
        api.complete_repair_order(pol["id"], claim["id"], {"actual_cost_cents": 275000},
                                  make_repair_shop_headers(shop["id"])), 200)
    assert completed["status"] == "CLOSED"

    claim_after = validate_success(api.get_claim(claim["id"], _CA), 200)
    assert claim_after["status"] == "SETTLED"
    item_after = validate_success(api.get_scheduled_item(item["id"], _UW), 200)
    assert item_after["item_status"] == "ACTIVE"


def test_repair_complete_within_cap_settles_claim(api):
    """PRD §3.14: "A valid completion moves the order to REPAIRED and then automatically to
    CLOSED, and that closure cascades upward: the parent claim moves from APPROVED to SETTLED"

    Design: Difficulty/resource_temporal_overlap/repair_cost_within_authorized_cap
    """
    ctx = setup_repair_order_in_progress(shop_in_network=True, claimed_amount_cents=300000)
    pol, claim, shop = ctx["policy"], ctx["claim"], ctx["shop"]
    completed = validate_success(
        api.complete_repair_order(pol["id"], claim["id"], {"actual_cost_cents": 200000},
                                  make_repair_shop_headers(shop["id"])), 200)
    assert completed["status"] == "CLOSED"
    claim_after = validate_success(api.get_claim(claim["id"], _CA), 200)
    assert claim_after["status"] == "SETTLED"


# ─────────────────────────────────────────────────────────────────────────
# Queue A: cross_entity_state_dependency — repair accept requires active shop
# ─────────────────────────────────────────────────────────────────────────

def test_repair_accept_on_suspended_shop_rejected(api):
    """PRD §3.14: "The assigned RepairShop accepts the order, moving it from ASSIGNED to
    IN_PROGRESS; acceptance again requires the shop to be ACTIVE, failing with
    ERR_SHOP_SUSPENDED otherwise."

    Design: Difficulty/cross_entity_state_dependency/repair_accept_requires_shop_active
    """
    ctx = setup_repair_order_assigned(shop_in_network=True, claimed_amount_cents=300000)
    pol, claim, shop = ctx["policy"], ctx["claim"], ctx["shop"]
    validate_success(api.suspend_repair_shop(shop["id"], _UW), 200)

    res = api.accept_repair_order(pol["id"], claim["id"], make_repair_shop_headers(shop["id"]))
    validate_error(res, ApiErrorId.ERR_SHOP_SUSPENDED, 409)


def test_repair_accept_succeeds_on_active_shop(api):
    """PRD §3.14: "The assigned RepairShop accepts the order, moving it from ASSIGNED to
    IN_PROGRESS; acceptance again requires the shop to be ACTIVE, failing with
    ERR_SHOP_SUSPENDED otherwise."

    Design: Difficulty/cross_entity_state_dependency/repair_accept_requires_shop_active
    """
    ctx = setup_repair_order_assigned(shop_in_network=True, claimed_amount_cents=300000)
    pol, claim, shop = ctx["policy"], ctx["claim"], ctx["shop"]
    accepted = validate_success(
        api.accept_repair_order(pol["id"], claim["id"], make_repair_shop_headers(shop["id"])),
        200)
    assert accepted["status"] == "IN_PROGRESS"


# ─────────────────────────────────────────────────────────────────────────
# Queue B: validations — repair exceeds authorized
# ─────────────────────────────────────────────────────────────────────────

def test_repair_complete_one_cent_over_cap_rejected(api):
    """PRD §3.14: "The reported cost must not exceed the order's authorized_amount_cents, or
    completion is rejected with ERR_REPAIR_EXCEEDS_AUTH."

    Design: Corner/validations/repair_complete_exceeds_authorized
    """
    ctx = setup_repair_order_in_progress(shop_in_network=True, claimed_amount_cents=300000)
    pol, claim, shop = ctx["policy"], ctx["claim"], ctx["shop"]
    assert ctx["repair_order"]["authorized_amount_cents"] == 275000
    res = api.complete_repair_order(pol["id"], claim["id"], {"actual_cost_cents": 275001},
                                    make_repair_shop_headers(shop["id"]))
    validate_error(res, ApiErrorId.ERR_REPAIR_EXCEEDS_AUTH, 409)
