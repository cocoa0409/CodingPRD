"""Membership discount per-line rounding, blowout-credit coverage, and credit conservation.

Queue A (Difficulty): combinatorial_formula/cf_perline_rounded_discount_then_sum;
                      compensating_invariant/ci_credit_conservation_book_then_cancel.
Queue B (Corner): section `calculations` (credit/discount instances).
"""
import pytest
from test_helpers import (
    validate_success,
    create_membership_plan, create_style_service, create_add_on, create_chair,
    create_stylist, create_member, setup_base_scenario, book_standalone_appointment,
    TEST_USERS,
)

FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["finance_manager_headers"]


# ─── Queue A: per-line-rounded discount then sum ──────────────────────────────

def test_perline_rounded_discount_then_sum_on_service_plus_addon(api):
    """PRD §3.5: "The membership `discount_cents` is computed per line and then summed,
    in that pinned order."
    PRD §3.5: "the service line always discounts, contributing the service's
    `base_price_cents` multiplied by the rate and rounded half-up to a whole cent; each
    attached add-on contributes its `captured_price_cents` multiplied by the rate and
    rounded half-up to a whole cent if the add-on is discount-eligible, and contributes
    zero otherwise."

    PLUS member (0.20): service 5500 -> round(1100) ; eligible add-on 3300 -> round(660);
    discount = 1760. list = 8800. net = 8800 - 1760 = 7040; no credits.

    Design: Difficulty/combinatorial_formula/cf_perline_rounded_discount_then_sum
    """
    plan = create_membership_plan(tier="PLUS", monthly_fee_cents=4900,
                                  included_blowout_credits=0, member_discount_pct=0.20)
    service = create_style_service(name="Premium Blowout", base_price_cents=5500,
                                   base_duration_minutes=45, blowout_credit_cost=1)
    addon = create_add_on(name="Updo", category="UPDO", extra_duration_minutes=30,
                          price_cents=3300, discount_eligible=True)
    chair = create_chair()
    stylist = create_stylist(full_name="Sam Senior")
    member = create_member(full_name="Plus Member", membership_plan_id=plan["id"])

    appt = validate_success(api.create_appointment(
        {"member_id": member["id"], "chair_id": chair["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    # Attaching the add-on re-prices.
    res = api.attach_add_on(appt["id"], {"add_on_id": addon["id"]}, FD)
    validate_success(res, 201)

    repriced = validate_success(api.get_appointment(appt["id"], FD), 200)
    assert repriced["discount_cents"] == 1760
    assert repriced["list_amount_cents"] == 8800
    assert repriced["service_charge_cents"] == 7040


def test_perline_rounding_diverges_from_sum_then_round(api):
    """PRD §3.5: "The `discount_cents` is the sum of those individually rounded line
    discounts — never the rate applied to a combined total — and that distinction matters
    whenever two discount-eligible lines carry half-cent residues."

    Rate 0.15 on two 110-cent lines: round(16.5)=17 per line -> 17+17 = 34 (per line),
    whereas (110+110)*0.15 = 33 (sum then round). The pinned order resolves to 34.

    Design: Difficulty/combinatorial_formula/cf_perline_rounded_discount_then_sum
    """
    plan = create_membership_plan(tier="BASIC", monthly_fee_cents=0,
                                  included_blowout_credits=0, member_discount_pct=0.15)
    service = create_style_service(name="Tiny", base_price_cents=110,
                                   base_duration_minutes=15, blowout_credit_cost=0)
    addon = create_add_on(name="Tiny Braid", category="BRAID", extra_duration_minutes=0,
                          price_cents=110, discount_eligible=True)
    chair = create_chair()
    stylist = create_stylist(full_name="Sam Senior")
    member = create_member(full_name="Basic Member", membership_plan_id=plan["id"])

    appt = validate_success(api.create_appointment(
        {"member_id": member["id"], "chair_id": chair["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    validate_success(api.attach_add_on(appt["id"], {"add_on_id": addon["id"]}, FD), 201)

    repriced = validate_success(api.get_appointment(appt["id"], FD), 200)
    assert repriced["discount_cents"] == 34, \
        f"per-line rounding must give 34, not 33 (sum-then-round); got {repriced['discount_cents']}"


# ─── Queue B: blowout credit coverage of the discounted service line ──────────

def test_credit_applied_covers_discounted_service_line(api):
    """PRD §3.5: "The number of `credits_applied` is the lesser of the member's current
    `blowout_credit_balance` and the service's `blowout_credit_cost`."
    PRD §3.5: "If that applied count reaches the service's `blowout_credit_cost` and the
    cost is greater than zero, the discounted service line is fully covered: the system
    subtracts the discounted service line — the service's `base_price_cents` minus the
    per-line rounded service discount — from the net amount, and the remainder is the
    `service_charge_cents`."

    VIP (0.25, 5 credits), service 6000, cost 1: discount 1500; discounted line 4500
    fully covered -> service_charge 0; credits_applied 1; balance 5 -> 4.

    Design: Corner/calculations/calc_credit_applied_reduces_charge
    """
    plan = create_membership_plan(tier="VIP", monthly_fee_cents=9900,
                                  included_blowout_credits=5, member_discount_pct=0.25)
    service = create_style_service(base_price_cents=6000, base_duration_minutes=45,
                                   blowout_credit_cost=1)
    chair = create_chair()
    stylist = create_stylist(full_name="Sam")
    member = create_member(full_name="VIP", membership_plan_id=plan["id"])

    appt = validate_success(api.create_appointment(
        {"member_id": member["id"], "chair_id": chair["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    assert appt["discount_cents"] == 1500
    assert appt["credits_applied"] == 1
    assert appt["service_charge_cents"] == 0

    member_after = validate_success(api.get_member(member["id"], FD), 200)
    assert member_after["blowout_credit_balance"] == 4


# ─── Queue A: credit conservation under book-then-cancel ──────────────────────

def test_credit_conservation_book_then_cancel(api):
    """PRD §3.9: "Cancellation is compensating: the blowout `credits_applied` are
    refunded back to the member's `blowout_credit_balance` ..."
    PRD §2.6 / §3.2: "where consumption is the sum of `credits_applied` across the
    member's appointments that are not `CANCELLED`."

    VIP member with 5 credits books (consumes 1 -> balance 4) then cancels (refund -> 5).

    Design: Difficulty/compensating_invariant/ci_credit_conservation_book_then_cancel
    """
    plan = create_membership_plan(tier="VIP", monthly_fee_cents=9900,
                                  included_blowout_credits=5, member_discount_pct=0.25)
    scenario = setup_base_scenario(
        service_overrides={"base_price_cents": 6000, "blowout_credit_cost": 1},
        member_overrides={"membership_plan_id": plan["id"]})
    appt = book_standalone_appointment(scenario)
    assert appt["credits_applied"] == 1
    member_mid = validate_success(api.get_member(scenario["member"]["id"], FD), 200)
    assert member_mid["blowout_credit_balance"] == 4

    validate_success(api.cancel_appointment(appt["id"], FD), 200)
    member_after = validate_success(api.get_member(scenario["member"]["id"], FD), 200)
    assert member_after["blowout_credit_balance"] == 5


def test_credit_conservation_with_package_credits_book_then_cancel(api):
    """PRD §3.13: "A purchase is born `ACTIVE`, and it raises the member's
    `blowout_credit_balance` by `credits_purchased` and increments the member's `version`
    by one."
    PRD §3.9: "the blowout `credits_applied` are refunded back to the member's
    `blowout_credit_balance` ..."

    Conservation holds when the credits come from a package (not a membership): a
    non-member buys 3 package credits (balance 3), books consuming 1 (balance 2), then
    cancels (refund -> 3).

    Design: Difficulty/compensating_invariant/ci_credit_conservation_book_then_cancel
    """
    scenario = setup_base_scenario(
        service_overrides={"base_price_cents": 6000, "blowout_credit_cost": 1})
    member_id = scenario["member"]["id"]
    mem = validate_success(api.get_member(member_id, FD), 200)
    validate_success(api.create_package_purchase(
        {"member_id": member_id, "credits_purchased": 3, "price_cents": 12000,
         "expected_member_version": mem["version"]}, FD), 201)
    after_pkg = validate_success(api.get_member(member_id, FD), 200)
    assert after_pkg["blowout_credit_balance"] == 3

    appt = book_standalone_appointment(scenario)
    assert appt["credits_applied"] == 1
    mid = validate_success(api.get_member(member_id, FD), 200)
    assert mid["blowout_credit_balance"] == 2

    validate_success(api.cancel_appointment(appt["id"], FD), 200)
    final = validate_success(api.get_member(member_id, FD), 200)
    assert final["blowout_credit_balance"] == 3
