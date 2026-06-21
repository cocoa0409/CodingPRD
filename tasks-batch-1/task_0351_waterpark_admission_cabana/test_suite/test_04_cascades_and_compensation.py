"""Depth-3 cascades (rain-out, refund) and compensating invariants on the wallet
and the window capacity pool (PRD §3.3, §3.8)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_guest_headers, TEST_USERS,
    setup_confirmed_admission, setup_rained_out_admission, setup_held_cabana_rental,
    get_window,
)

PM = TEST_USERS["park_manager_headers"]
FC = TEST_USERS["finance_clerk_headers"]
GA = TEST_USERS["gate_agent_headers"]


# ───────────────── Queue A: transitive_cascade ─────────────────

def test_rainout_cascade_window_admission_raincheck(api):
    """PRD §3.8: "every admission on that window in CONFIRMED or FROZEN status moves
    to RAINED_OUT; for each, the window's reserved_count decrement is accounted, and a
    rain-check voucher is issued to that admission's guest when a guest_id is bound"
    PRD §3.8: "After both cascades complete, the window's reserved_count is set to zero"

    Design: Difficulty/transitive_cascade/rainout_cascade_window_admission_raincheck_depth3
    """
    ctx = setup_rained_out_admission(rain_check_value_cents=4000, clock="2026-07-01T08:00:00Z")
    adm = get_success_data(api_client.get_admission(ctx["admission"]["id"], PM))
    assert adm["status"] == "RAINED_OUT", f"admission link-2: expected RAINED_OUT, got {adm['status']}"
    # link 3: exactly one ISSUED rain-check for the guest, value 4000.
    rcs = [r for r in ctx["rain_checks"] if r["guest_id"] == ctx["guest"]["id"]]
    assert len(rcs) == 1, f"expected exactly one rain-check, got {len(rcs)}"
    assert rcs[0]["status"] == "ISSUED"
    assert rcs[0]["value_cents"] == 4000, f"expected value 4000, got {rcs[0]['value_cents']}"
    assert ctx["window"]["reserved_count"] == 0, \
        f"window reserved_count should be 0, got {ctx['window']['reserved_count']}"


def test_rainout_cascade_issues_voucher_with_admission_source_kind(api):
    """PRD §3.8: "a rain-check voucher is issued to that admission's guest when a
    guest_id is bound, with the voucher's source_kind recorded as ADMISSION and its
    source_ref_id pointing at the rained-out admission."
    PRD §3.8: "Each voucher's value_cents is set at issuance from the park's
    rain_check_value_cents, and the voucher opens in ISSUED status."

    Design: Difficulty/transitive_cascade/rainout_cascade_window_admission_raincheck_depth3
    """
    ctx = setup_rained_out_admission(rain_check_value_cents=4000, clock="2026-07-01T08:00:00Z")
    rcs = [r for r in ctx["rain_checks"] if r["guest_id"] == ctx["guest"]["id"]]
    assert len(rcs) == 1
    rc = rcs[0]
    assert rc["source_kind"] == "ADMISSION", f"expected ADMISSION, got {rc['source_kind']}"
    assert rc["source_ref_id"] == ctx["admission"]["id"], "source_ref_id must point at the admission"
    assert rc["status"] == "ISSUED"


def test_refund_cascade_order_admission_window_reserved_count(api):
    """PRD §3.3: "every non-terminal admission under the order moves to CANCELLED, and
    each such admission that had been holding a confirmed window slot decrements that
    window's reserved_count by one"
    PRD §3.3: "Finally the order reaches its joint terminal posture of REFUNDED payment
    and CANCELLED fulfillment"

    Design: Difficulty/transitive_cascade/refund_cascade_order_admission_window_depth3
    """
    ctx = setup_confirmed_admission(clock="2026-07-01T08:00:00Z", party_size=1)
    # reserved_count should be 1 before refund.
    before = get_window(ctx["window"]["id"])
    assert before["reserved_count"] == 1, f"precondition reserved_count 1, got {before['reserved_count']}"
    refunded = get_success_data(api_client.refund_order(ctx["order"]["id"], FC))
    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["fulfillment_status"] == "CANCELLED"
    adm = get_success_data(api_client.get_admission(ctx["admission"]["id"], PM))
    assert adm["status"] == "CANCELLED", f"admission link-2: expected CANCELLED, got {adm['status']}"
    after = get_window(ctx["window"]["id"])
    assert after["reserved_count"] == 0, \
        f"window reserved_count link-3: expected 0, got {after['reserved_count']}"


# ───────────────── Queue A: compensating_invariant ─────────────────

def test_refund_cancels_held_cabana_rental_and_releases_slot(api):
    """PRD §3.3: "every cabana rental under the order in CONFIRMED or HELD status moves
    to CANCELLED, decrementing the relevant window's reserved_count."
    PRD §3.3: "Finally the order reaches its joint terminal posture of REFUNDED payment
    and CANCELLED fulfillment"

    Design: Difficulty/transitive_cascade/refund_cascade_order_admission_window_depth3
    """
    ctx = setup_held_cabana_rental(clock="2026-07-01T08:00:00Z")
    gh = make_guest_headers(ctx["guest"]["id"])
    # Fulfill so the order is PAID/FULFILLED and the rental is CONFIRMED.
    get_success_data(api_client.fulfill_order(ctx["order"]["id"], gh))
    before = get_window(ctx["window"]["id"])
    assert before["reserved_count"] == 1, f"rental holds 1, got {before['reserved_count']}"
    refunded = get_success_data(api_client.refund_order(ctx["order"]["id"], FC))
    assert refunded["payment_status"] == "REFUNDED"
    rental_after = get_success_data(api_client.get_cabana_rental(ctx["rental"]["id"], FC))
    assert rental_after["status"] == "CANCELLED", \
        f"cabana rental link-2: expected CANCELLED, got {rental_after['status']}"
    after = get_window(ctx["window"]["id"])
    assert after["reserved_count"] == 0, \
        f"window reserved_count link-3: expected 0, got {after['reserved_count']}"


def test_refund_credits_total_back_to_wallet(api):
    """PRD §3.3: "A successful refund credits the guest's wallet_credit_cents by the
    order's total_cents, conserving the wallet against the original debit and charge."

    Design: Difficulty/compensating_invariant/refund_conserves_guest_wallet_minus_charge
    """
    ctx = setup_confirmed_admission(clock="2026-07-01T10:00:00Z", party_size=1)
    gh = make_guest_headers(ctx["guest"]["id"])
    order = get_success_data(api_client.get_order(ctx["order"]["id"], gh))
    assert order["total_cents"] == 5000, f"precondition total 5000, got {order['total_cents']}"
    refunded = get_success_data(api_client.refund_order(ctx["order"]["id"], FC))
    assert refunded["payment_status"] == "REFUNDED"
    guest_after = get_success_data(api_client.get_guest(ctx["guest"]["id"], FC))
    # wallet started at 0; pay debited 0; refund credits total 5000 → wallet 5000.
    assert guest_after["wallet_credit_cents"] == 5000, \
        f"wallet should be 5000 after refund, got {guest_after['wallet_credit_cents']}"


def test_refund_wallet_credit_exact_with_party_size_one(api):
    """PRD §3.3: "A successful refund credits the guest's wallet_credit_cents by the
    order's total_cents, conserving the wallet against the original debit and charge."

    Design: Difficulty/compensating_invariant/refund_conserves_guest_wallet_minus_charge
    """
    # Distinct base price → distinct total, still pinned by the same wallet invariant.
    ctx = setup_confirmed_admission(clock="2026-07-01T10:00:00Z", party_size=1,
                                    policy_overrides={"base_price_cents": 7700})
    order = get_success_data(api_client.get_order(ctx["order"]["id"],
                                                  make_guest_headers(ctx["guest"]["id"])))
    assert order["total_cents"] == 7700
    get_success_data(api_client.refund_order(ctx["order"]["id"], FC))
    guest_after = get_success_data(api_client.get_guest(ctx["guest"]["id"], FC))
    assert guest_after["wallet_credit_cents"] == 7700, \
        f"wallet should equal refunded total 7700, got {guest_after['wallet_credit_cents']}"


def test_rainout_settle_conserves_window_capacity_pool(api):
    """PRD §3.8: "After both cascades complete, the window's reserved_count is set to
    zero"
    PRD §3.8: "A FinanceClerk settles an ISSUED voucher, moving it to the terminal
    SETTLED and crediting the holder's wallet_credit_cents by the voucher's value_cents"

    Design: Difficulty/compensating_invariant/rainout_settle_conserves_window_capacity_pool
    """
    ctx = setup_rained_out_admission(rain_check_value_cents=4000, clock="2026-07-01T10:00:00Z")
    # After rain-out, reserved_count is 0.
    assert ctx["window"]["reserved_count"] == 0
    rc = [r for r in ctx["rain_checks"] if r["guest_id"] == ctx["guest"]["id"]][0]
    get_success_data(api_client.settle_rain_check(rc["id"], FC))
    after = get_window(ctx["window"]["id"])
    assert after["reserved_count"] == 0, \
        f"settle must NOT re-consume the pool; reserved_count {after['reserved_count']}"
    guest_after = get_success_data(api_client.get_guest(ctx["guest"]["id"], FC))
    assert guest_after["wallet_credit_cents"] == 4000, \
        f"wallet should be 4000 after settle, got {guest_after['wallet_credit_cents']}"


def test_rainout_settle_credits_wallet_without_reconsuming_pool_distinct_value(api):
    """PRD §3.8: "every cabana rental on that window in CONFIRMED or HELD status moves
    to RAINED_OUT"
    PRD §3.8: "moving it to the terminal SETTLED and crediting the holder's
    wallet_credit_cents by the voucher's value_cents, which is the compensating credit
    that conserves the guest's wallet against forgone gate revenue."

    Design: Difficulty/compensating_invariant/rainout_settle_conserves_window_capacity_pool
    """
    ctx = setup_rained_out_admission(rain_check_value_cents=2500, clock="2026-07-01T10:00:00Z")
    assert ctx["window"]["reserved_count"] == 0
    rc = [r for r in ctx["rain_checks"] if r["guest_id"] == ctx["guest"]["id"]][0]
    get_success_data(api_client.settle_rain_check(rc["id"], FC))
    after = get_window(ctx["window"]["id"])
    assert after["reserved_count"] == 0, \
        f"pool must stay 0 after settle, got {after['reserved_count']}"
    guest_after = get_success_data(api_client.get_guest(ctx["guest"]["id"], FC))
    assert guest_after["wallet_credit_cents"] == 2500, \
        f"wallet should be 2500 after settle, got {guest_after['wallet_credit_cents']}"


# ───────────────── Queue B: cross_cutting_complexity_layers (cascade) ─────────────────

def test_rainout_flips_both_admission_and_cabana_rental(api):
    """PRD §3.8: "every admission on that window in CONFIRMED or FROZEN status moves
    to RAINED_OUT"
    PRD §3.8: "every cabana rental on that window in CONFIRMED or HELD status moves to
    RAINED_OUT, and each issues a rain-check to the order's guest with source_kind of
    CABANA_RENTAL"

    Design: Corner/cross_cutting_complexity_layers/rainout_cascade_partial_to_cabana_and_admission
    """
    # Build: paid order, HELD cabana rental, fulfill → rental CONFIRMED, mint admission,
    # bind, assign; then weather RAINED_OUT; then rain-out the window.
    from test_helpers import create_cabana, create_window, create_policy, create_park, create_guest, create_order
    park = create_park(rain_check_value_cents=4000)
    get_success_data(api_client.set_clock({"to_iso8601": "2026-07-01T10:00:00Z"}, PM))
    create_policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    window = create_window(park["id"], starts_at="2026-07-01T09:00:00Z",
                           ends_at="2026-07-01T20:00:00Z", window_capacity=50)
    cabana = create_cabana(park["id"], label="C-8", tier="STANDARD", daily_rate_cents=9000)
    guest = create_guest()
    gh = make_guest_headers(guest["id"])
    order = create_order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    get_success_data(api_client.pay_order(order["id"], gh))
    fresh = get_window(window["id"])
    rental = get_success_data(api_client.create_cabana_rental(
        {"cabana_id": cabana["id"], "order_id": order["id"], "entry_window_id": window["id"],
         "starts_at": "2026-07-01T10:00:00Z", "ends_at": "2026-07-01T14:00:00Z",
         "expected_entry_window_version": fresh["version"]}, gh))
    get_success_data(api_client.fulfill_order(order["id"], gh))
    adm = get_success_data(api_client.list_order_admissions(order["id"], gh))[0]
    get_success_data(api_client.bind_guest(adm["id"], {"guest_id": guest["id"]}, gh))
    fresh2 = get_window(window["id"])
    get_success_data(api_client.assign_window(
        adm["id"], {"entry_window_id": window["id"],
                    "expected_entry_window_version": fresh2["version"]}, gh))
    get_success_data(api_client.set_park_weather(park["id"], {"weather_status": "RAINED_OUT"}, PM))
    get_success_data(api_client.rain_out_entry_window(window["id"], PM))

    rental_after = get_success_data(api_client.get_cabana_rental(rental["id"], PM))
    adm_after = get_success_data(api_client.get_admission(adm["id"], PM))
    assert rental_after["status"] == "RAINED_OUT"
    assert adm_after["status"] == "RAINED_OUT"
    rcs = get_success_data(api_client.list_rain_checks(PM, params={"park_id": park["id"]}))
    assert len(rcs) == 2, f"expected 2 rain-checks (admission + cabana), got {len(rcs)}"
