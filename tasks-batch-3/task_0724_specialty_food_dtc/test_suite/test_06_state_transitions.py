"""Invalid/terminal transitions, label-hold side effects, referral lifecycle.

Corner queue: state_machines section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_active_sku_with_lot, create_draft_sku, create_quarantine_lot,
    create_customer, create_active_subscription, build_shipped_order,
    setup_customer_with_active_subscription, setup_qualified_referral,
    setup_referrer_and_referred_with_referral,
    make_customer_headers, TEST_USERS, ApiErrorId,
)

INV = TEST_USERS["inventory_manager_headers"]
COMP = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_cancel_delivered_order_rejected(api):
    """PRD §3.5: "An order may be cancelled while it is DRAFT or RESERVED."
    PRD §3.8: "State-illegal subscription transitions are rejected with ERR_INVALID_STATE."
    PRD §3.5: "A shipped order is later marked delivered by an InventoryManager, moving it
    SHIPPED → DELIVERED; DELIVERED is terminal."

    Design: Corner/state_machines/order_cancel_from_delivered_returns_invalid_state
    """
    sku, _ = create_active_sku_with_lot(name="Del Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1000,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_shipped_order(cid, [(sku["id"], 1)])
    validate_success(api.deliver_order(order["id"], INV), 200)
    res = api.cancel_order(order["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_subscription_rejected(api):
    """PRD §3.8: "A subscriber may cancel from either ACTIVE or PAUSED (→ CANCELLED, terminal).
    State-illegal subscription transitions are rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/subscription_cancel_terminal_lockdown
    """
    customer, sku, lot, sub = setup_customer_with_active_subscription(tier="STARTER", cadence_days=14)
    cid = customer["id"]
    validate_success(api.cancel_subscription(sub["id"], make_customer_headers(cid)), 200)
    res = api.cancel_subscription(sub["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_label_hold_reverts_sku_and_autopauses_subscription(api):
    """PRD §3.2: "A ComplianceOfficer may place a label hold on an ACTIVE SKU, moving it
    ACTIVE → LABEL_HOLD; this clears label_approved back to false and auto-pauses every ACTIVE
    subscription whose selected SKU is the held one."

    Design: Corner/state_machines/sku_label_hold_reverts_active_to_label_hold_and_pauses_subscriptions
    """
    customer, sku, lot, sub = setup_customer_with_active_subscription(tier="STARTER", cadence_days=14)
    cid = customer["id"]
    held = validate_success(api.hold_label(sku["id"], COMP), 200)
    assert held["status"] == "LABEL_HOLD"
    assert held["label_approved"] is False
    sub_after = validate_success(api.get_subscription(sub["id"], make_customer_headers(cid)), 200)
    assert sub_after["status"] == "PAUSED"


def test_referral_qualifies_when_referred_first_order_ships(api):
    """PRD §3.1: "When the referred customer's first order reaches the shipped milestone —
    their lifetime_order_count moving from 0 to 1 — the system advances the referral from
    PENDING to QUALIFIED."

    Design: Corner/state_machines/referral_qualifies_when_referred_first_order_ships
    """
    referrer, referred, referral, sku = setup_qualified_referral()
    assert referral["status"] == "QUALIFIED"


def test_recall_quarantine_lot_rejected(api):
    """PRD §3.2: "A ComplianceOfficer may recall a RELEASED lot, moving it RELEASED → RECALLED"
    PRD §3.8: (state machine legality) — recall is only valid from RELEASED; an illegal
    from-state raises ERR_INVALID_STATE per §2.9.

    Design: Corner/state_machines/lot_release_quarantine_only_invalid_from_recalled
    """
    sku = create_draft_sku(name="Q Coffee", category="COFFEE",
                           storage_class="AMBIENT", unit_price_cents=1000)
    lot = create_quarantine_lot(sku["id"], produced_units=5)  # never released
    res = api.recall_lot(lot["id"], COMP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_reward_qualified_referral_credits_referrer(api):
    """PRD §3.1: "A PlatformAdmin then rewards a qualified referral, moving it
    QUALIFIED → REWARDED: this sets the referral's reward_points to 500 and adds those 500
    points to the referrer's loyalty_points_balance."

    Design: Corner/state_machines/referral_reward_credits_referrer_points
    """
    referrer, referred, referral, sku = setup_qualified_referral()
    rewarded = validate_success(api.reward_referral(referral["id"], ADMIN), 200)
    assert rewarded["reward_points"] == 500
    referrer_after = validate_success(api.get_customer(referrer["id"], ADMIN), 200)
    assert referrer_after["loyalty_points_balance"] == 500
