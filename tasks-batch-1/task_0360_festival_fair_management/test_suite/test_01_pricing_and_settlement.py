"""Booth-fee pricing, settlement aggregation, and cash-out money math.

Difficulty queue (A): dual_variant_calc, combinatorial_formula, and the wallet-
liability compensating invariant — all driven by PRD-stated pricing constants.
"""
import pytest
from test_helpers import (
    api_client, validate_success, assert_vendor_application, assert_wallet_txn,
    create_vendor_payload, create_vendor_application_payload, topup_payload,
    spend_payload,
    create_festival_with_zone_and_stage, create_zone, create_stage, open_sales,
    go_live, create_on_sale_festival, setup_application_under_review,
    setup_approved_application, approve_application, pay_fee, confirm_application,
    create_vendor, submit_application, sell_ticket, issue_wristband,
    activate_wristband, topup, setup_active_wristband,
    TEST_USERS, make_vendor_headers,
)

_DIRECTOR = TEST_USERS["director_headers"]
_BOXOFFICE = TEST_USERS["boxoffice_headers"]
_VENDOR_MANAGER = TEST_USERS["vendor_manager_headers"]


# ─── dual_variant_calc / booth_fee_tiered_vs_cashout_aggregation_diverge ───

def test_booth_fee_food_zone_a_three_day_with_power(api):
    """PRD §3.8: "The base is the per-day tier rate for the application's `booth_tier`
    multiplied by its `day_count`, where the tier rate is 150.00 for `STANDARD`,
    300.00 for `PREMIUM`, and 450.00 for `FOOD`. A surcharge is the base multiplied
    by the zone-code surcharge fraction, which is 0.20 for zone code `A`, 0.10 for
    zone code `B`, and 0.00 for zone code `C`. The location fee is the base plus the
    surcharge, rounded to two decimal places — this first component is rounded before
    anything is added to it. If `power_addon` is requested, a power fee is the daily
    power rate of 40.00 multiplied by `day_count`, rounded to two decimal places; if
    no power is requested the power fee is 0.00. The final `booth_fee` is the location
    fee plus the power fee, rounded to two decimal places."

    FOOD/zone-A/3-day/power: base 450*3=1350, surcharge 1350*0.20=270, location 1620,
    power 40*3=120 -> booth_fee 1740.00. Tiered-pricing variant over a vendor booth.

    Design: Difficulty/dual_variant_calc/booth_fee_tiered_vs_cashout_aggregation_diverge
    """
    festival, zone, stage = create_festival_with_zone_and_stage(zone_code="A",
                                                                zone_slot_capacity=2)
    open_sales(festival["id"])
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_application_under_review(festival["id"], zone, booth_tier="FOOD",
                                                 day_count=3, power_addon=True,
                                                 vendor_name="Tacos Co")
    res = api.approve_application(app["id"], {"expected_zone_version": zone["version"]},
                                  _VENDOR_MANAGER)
    approved = validate_success(res, 200)
    assert_vendor_application(approved)
    assert approved["status"] == "APPROVED"
    assert approved["booth_fee"] == 1740.00, f"expected 1740.00, got {approved['booth_fee']}"


def test_cashout_aggregation_diverges_from_booth_pricing(api):
    """PRD §3.6: "The cash-out computes a fee as the pre-cash-out `balance` multiplied
    by the festival's `wristband_cashout_pct`, rounded to two decimal places, and a
    refund equal to the pre-cash-out balance minus that fee, again rounded to two
    decimal places. It writes two wallet transactions — one of `kind` `CASHOUT` and
    one of `kind` `CASHOUT_FEE` — sets the `balance` to 0."

    The wallet cash-out aggregation (balance minus 3% fee) is an entirely different
    money algorithm from the vendor booth tiered pricing: a 100.00 wallet yields
    fee 3.00 and refund 97.00.

    Design: Difficulty/dual_variant_calc/booth_fee_tiered_vs_cashout_aggregation_diverge
    """
    festival, zone, stage = create_on_sale_festival(wristband_cashout_pct=0.03)
    ticket, wristband = setup_active_wristband(festival, balance=100.00, rfid_uid="RF-CASH-1")
    go_live(festival["id"])
    res = api.cashout_wristband(wristband["id"], _BOXOFFICE)
    closed = validate_success(res, 200)
    assert closed["lifecycle_status"] == "CLOSED"
    assert closed["balance"] == 0

    txns = validate_success(api.list_wristband_wallet_txns(wristband["id"], _BOXOFFICE), 200)
    cashout = [t for t in txns if t["kind"] == "CASHOUT"]
    cashout_fee = [t for t in txns if t["kind"] == "CASHOUT_FEE"]
    assert len(cashout) == 1 and len(cashout_fee) == 1
    assert_wallet_txn(cashout[0])
    assert cashout[0]["amount"] == 97.00, f"expected 97.00 refund, got {cashout[0]['amount']}"
    assert cashout_fee[0]["amount"] == 3.00, f"expected 3.00 fee, got {cashout_fee[0]['amount']}"


# ─── combinatorial_formula / booth_fee_mode_a_nonlinear_three_inputs ───

def test_booth_fee_premium_zone_b_two_day_no_power(api):
    """PRD §3.8: "The base is the per-day tier rate for the application's `booth_tier`
    multiplied by its `day_count`, where the tier rate is 150.00 for `STANDARD`,
    300.00 for `PREMIUM`, and 450.00 for `FOOD`. A surcharge is the base multiplied
    by the zone-code surcharge fraction, which is 0.20 for zone code `A`, 0.10 for
    zone code `B`, and 0.00 for zone code `C`."

    PREMIUM/zone-B/2-day/no-power: base 300*2=600, surcharge 600*0.10=60, location 660,
    power 0 -> booth_fee 660.00. Non-linear tier-rate x zone-surcharge interaction.

    Design: Difficulty/combinatorial_formula/booth_fee_mode_a_nonlinear_three_inputs
    """
    festival, zone, stage = create_festival_with_zone_and_stage(zone_code="B",
                                                                zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_application_under_review(festival["id"], zone, booth_tier="PREMIUM",
                                                 day_count=2, power_addon=False,
                                                 vendor_name="Crafts Co")
    res = api.approve_application(app["id"], {"expected_zone_version": zone["version"]},
                                  _VENDOR_MANAGER)
    approved = validate_success(res, 200)
    assert approved["booth_fee"] == 660.00, f"expected 660.00, got {approved['booth_fee']}"


def test_booth_fee_power_term_is_conditional(api):
    """PRD §3.8: "If `power_addon` is requested, a power fee is the daily power rate
    of 40.00 multiplied by `day_count`, rounded to two decimal places; if no power is
    requested the power fee is 0.00. The final `booth_fee` is the location fee plus
    the power fee, rounded to two decimal places."

    Same PREMIUM/zone-B/2-day but WITH power: location 660 + power 40*2=80 -> 740.00,
    confirming the conditional power term adds exactly POWER_DAILY*day_count.

    Design: Difficulty/combinatorial_formula/booth_fee_mode_a_nonlinear_three_inputs
    """
    festival, zone, stage = create_festival_with_zone_and_stage(zone_code="B",
                                                                zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_application_under_review(festival["id"], zone, booth_tier="PREMIUM",
                                                 day_count=2, power_addon=True,
                                                 vendor_name="Crafts Pw")
    res = api.approve_application(app["id"], {"expected_zone_version": zone["version"]},
                                  _VENDOR_MANAGER)
    approved = validate_success(res, 200)
    assert approved["booth_fee"] == 740.00, f"expected 740.00, got {approved['booth_fee']}"


# ─── combinatorial_formula / settlement_mode_b_sum_then_round_not_per_line ───

def _setup_settled_single_day_booth(api, spend_amounts, commission_pct=0.08):
    """Build a CLOSED 1-day festival with a CONFIRMED STANDARD/zone-C booth and the
    given SPEND amounts credited to that booth, then settle. Returns (vendor, app)."""
    festival, zone, stage = create_festival_with_zone_and_stage(
        start_date="2026-08-01", end_date="2026-08-01", zone_code="C", zone_slot_capacity=1,
        max_reentries=1, vendor_commission_pct=commission_pct)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_approved_application(festival["id"], zone, booth_tier="STANDARD",
                                             day_count=1, power_addon=False,
                                             vendor_name="Drinks Co")
    pay_fee(app["id"], vendor["id"], 180.00)
    confirm_application(app["id"], vendor["id"])
    open_sales(festival["id"])
    ticket = sell_ticket(festival["id"], ticket_type="GA", day_count=1)
    wristband = issue_wristband(festival["id"], "RF-SETTLE-1")
    activate_wristband(wristband["id"], ticket["id"])
    topup(wristband["id"], 1.00)
    go_live(festival["id"])
    for amt in spend_amounts:
        validate_success(api.spend_wristband(
            wristband["id"], spend_payload(amt, zone["id"]), _BOXOFFICE), 201)
    validate_success(api.close_festival(festival["id"], _DIRECTOR), 200)
    validate_success(api.settle_application(app["id"], _DIRECTOR), 200)
    vendor_after = validate_success(api.get_vendor(vendor["id"], _DIRECTOR), 200)
    return vendor_after, app


def test_settlement_sums_then_rounds_not_per_line(api):
    """PRD §3.9: "First the gross is the sum of the `amount` of every `SPEND` wallet
    transaction whose `vendor_application_id` is this application, with that sum taken
    across all such transactions and then rounded to two decimal places — the rounding
    is applied once to the summed total, never per line. The commission is the gross
    multiplied by the festival's `vendor_commission_pct`, rounded to two decimal places
    and applied to the summed gross. The net is the gross minus the commission, rounded
    to two decimal places."

    Three SPEND of 0.31: gross sum 0.93, commission round2(0.93*0.08)=0.07, net 0.86.
    Per-line rounding (round2(0.31*0.08)=0.02 x3=0.06) would diverge to 0.87; the
    pinned sum-then-round payout is 0.86.

    Design: Difficulty/combinatorial_formula/settlement_mode_b_sum_then_round_not_per_line
    """
    vendor_after, app = _setup_settled_single_day_booth(api, [0.31, 0.31, 0.31])
    assert vendor_after["payout_total"] == 0.86, (
        f"expected payout_total 0.86 (sum-then-round), got {vendor_after['payout_total']}")


def test_settlement_outstanding_fee_zero_when_paid_in_full(api):
    """PRD §3.9: "The outstanding fee is the larger of zero and the application's
    `booth_fee` minus its `fee_paid`. The final payout is the net minus the
    outstanding, rounded to two decimal places, and it is credited to the vendor's
    `payout_total`."

    A STANDARD/zone-C/1-day booth_fee is 150.00 and the vendor paid 180.00, so
    outstanding is max(0, 150-180)=0 and the payout equals net with no deduction.

    Design: Difficulty/combinatorial_formula/settlement_mode_b_sum_then_round_not_per_line
    """
    # gross 1.00, commission round2(0.08)=0.08, net 0.92, outstanding 0 -> payout 0.92.
    vendor_after, app = _setup_settled_single_day_booth(api, [1.00])
    assert vendor_after["payout_total"] == 0.92, (
        f"expected payout_total 0.92, got {vendor_after['payout_total']}")


# ─── compensating_invariant / wallet_liability_conserved_topup_then_cashout ───

def test_wallet_liability_zeroed_after_topup_then_cashout(api):
    """PRD §2.8: "A festival tracks `total_wallet_liability`, the running sum of the
    `balance` across every wristband whose `lifecycle_status` is `ACTIVE`. Topping up
    a wallet increases this total, spending at a booth decreases it, cashing out
    removes the cashed-out balance, and freezing or unfreezing a wristband removes or
    re-includes its balance respectively, because a frozen wristband is no longer in
    the `ACTIVE` set."

    Top-up 100.00 sets liability 100.00; cash-out removes the cashed-out balance,
    leaving total_wallet_liability at 0.00 with no drift, and the wristband CLOSED.

    Design: Difficulty/compensating_invariant/wallet_liability_conserved_topup_then_cashout
    """
    from test_helpers import setup_live_festival_with_active_wristband
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        balance=100.00, rfid_uid="RF-WI-1", wristband_cashout_pct=0.03)
    res = api.cashout_wristband(wristband["id"], _BOXOFFICE)
    closed = validate_success(res, 200)
    assert closed["balance"] == 0
    assert closed["lifecycle_status"] == "CLOSED"
    festival_after = validate_success(api.get_festival(festival["id"], _DIRECTOR), 200)
    assert festival_after["total_wallet_liability"] == 0.00, (
        f"expected total_wallet_liability 0.00, got {festival_after['total_wallet_liability']}")


def test_topup_sets_wallet_liability_before_cashout(api):
    """PRD §2.8: "A festival tracks `total_wallet_liability`, the running sum of the
    `balance` across every wristband whose `lifecycle_status` is `ACTIVE`. Topping up
    a wallet increases this total."

    Before the compensating cash-out, the lone topped-up ACTIVE wristband's 100.00
    balance is exactly reflected in the festival's total_wallet_liability.

    Design: Difficulty/compensating_invariant/wallet_liability_conserved_topup_then_cashout
    """
    from test_helpers import setup_live_festival_with_active_wristband
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        balance=100.00, rfid_uid="RF-WI-2", wristband_cashout_pct=0.03)
    festival_now = validate_success(api.get_festival(festival["id"], _DIRECTOR), 200)
    assert festival_now["total_wallet_liability"] == 100.00, (
        f"expected total_wallet_liability 100.00, got {festival_now['total_wallet_liability']}")
