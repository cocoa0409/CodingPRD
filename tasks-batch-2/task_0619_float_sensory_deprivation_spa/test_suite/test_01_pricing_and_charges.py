"""Pricing: provisional charge at creation, final charge at completion, and their
divergence for couples bookings."""
from test_helpers import (
    validate_success,
    setup_completed_single_credit_booking,
    create_plan, create_member, create_active_membership, create_tank, create_booking,
    set_clock, api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


def test_final_charge_90min_single_member_discount(api):
    """PRD §3.6: "start from the plan's `retail_float_cents`; if the realized session is 90
    minutes, multiply by the ninety-minute multiplier of 1.4 and round to the nearest cent;
    if the booking is couples, double the base and then add the couples surcharge of fifteen
    hundred cents; and if the booking carries an `ACTIVE` membership, multiply by one minus
    the plan's `member_discount_pct` and round to the nearest cent."

    Design: Difficulty/combinatorial_formula/comb_a_final_charge_nested_branches
    """
    # SOLO retail 5000, discount 0.20, 90-min single CREDIT:
    # round(5000*1.4)=7000; single (no double); round(7000*0.80)=5600.
    ctx = setup_completed_single_credit_booking(retail=5000, discount=0.20, session_minutes=90)
    booking = ctx["booking"]
    assert booking["final_charge_cents"] == 5600, (
        f"expected final 5600, got {booking['final_charge_cents']}"
    )


def test_final_charge_90min_single_member_credits_consumed(api):
    """PRD §3.6: "the credits required are 1 for a solo booking and 2 for a couples booking".
    PRD §3.6: "On a successful credit check-in the platform appends a `CONSUME` ledger entry
    whose `delta` is the negative of the credits required, records that count in
    `credits_consumed`, and recomputes the membership's `credit_balance`."

    Design: Difficulty/combinatorial_formula/comb_a_final_charge_nested_branches
    """
    ctx = setup_completed_single_credit_booking(retail=5000, discount=0.20, session_minutes=90)
    assert ctx["booking"]["credits_consumed"] == 1


def test_provisional_charge_single_60min_member_discount(api):
    """PRD §3.5: "start from the plan's `retail_float_cents` as the base; if the booked
    session is 90 minutes, multiply the base by the ninety-minute multiplier of 1.4 and round
    to the nearest cent; if the booking is couples, double the base; and finally, if the
    booking carries a membership whose status is `ACTIVE`, multiply by one minus the plan's
    `member_discount_pct` and round to the nearest cent".

    Design: Corner/calculations/provisional_charge_single_60_member_discount
    """
    # SOLO retail 5000, discount 0.20, single 60-min member booking:
    # base 5000; no 90-min mult; no double; round(5000*0.80)=4000.
    set_clock("2026-04-10T00:00:00Z")
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=5000, member_discount_pct=0.20)
    member = create_member()
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE")
    booking = create_booking(member["id"], tank["id"], 60, "2026-05-01T10:00:00Z",
                             "CREDIT", membership_id=ship["id"])
    assert booking["provisional_charge_cents"] == 4000, (
        f"expected provisional 4000, got {booking['provisional_charge_cents']}"
    )
