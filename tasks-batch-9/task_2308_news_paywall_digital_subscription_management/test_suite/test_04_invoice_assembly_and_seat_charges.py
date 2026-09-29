"""The pinned invoice waterfall: per-seat rounding, the discount tier, then credits."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    assert_hold_credit_bookkeeping,
    assert_invoice_waterfall,
    assert_seat_capacity_conserved,
    create_active_institutional_plan,
    create_active_print_plan,
    create_hold,
    create_registered_reader,
    invite_seat,
    invoice_for_cycle,
    list_holds,
    make_group_admin_headers,
    make_reader_headers,
    open_subscription,
    present_save_offer,
    read_cancellation_request,
    read_group,
    read_hold,
    read_seat,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    start_cancellation,
    validate_success,
)
from test_helpers import factories as f


def _arrange_three_claimed_seats_spanning_eight_days_of_the_second_cycle():
    """A capacity-three group whose three ACTIVE seats each occupy eight cycle days."""
    set_clock_date("2026-09-01")
    plan = create_active_institutional_plan(
        name="Institution Seats",
        intro_price_cents=5000,
        intro_cycles=1,
        standard_price_cents=5000,
        standard_from_cycle=2,
        cycle_days=30,
        per_seat_price_cents=400,
    )
    group = validate_success(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan["id"],
                seat_capacity=3,
                name="Univ Library",
                admin_email="libadmin@univ.edu",
                allowed_email_domain="univ.edu",
            ),
            OPS_AGENT_HEADERS,
        ),
        201,
    )
    admin_headers = make_group_admin_headers(group["id"])
    funding_reader = create_registered_reader("libadmin@univ.edu")
    subscription = open_subscription(funding_reader["id"], plan["id"], group["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 5000)

    seats = []
    for local in ("seat_a", "seat_b", "seat_c"):
        seat_reader = create_registered_reader(f"{local}@univ.edu")
        seat = invite_seat(
            group["id"],
            seat_reader["id"],
            "2026-10-05",
            "2026-10-13",
            admin_headers=admin_headers,
        )
        claimed = validate_success(
            api_client.activate_seat(seat["id"], make_reader_headers(seat_reader["id"])),
            200,
        )
        seats.append(claimed)

    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    return {
        "plan": plan,
        "group": group,
        "subscription": read_subscription(subscription["id"]),
        "seats": seats,
        "invoice": invoice_for_cycle(subscription["id"], 2),
    }


def test_each_seat_line_is_rounded_before_the_seat_charge_is_summed():
    """Eight days at 400 over 30 rounds to 107 per seat, so the sum is 321 not 320.

    PRD: "That seat's line is the plan's `per_seat_price_cents` multiplied by the active days, divided by the plan's `cycle_days`, rounded half up to whole cents."
    PRD: "`seat_line_cents` is the sum of those per-line figures, and the sum is never re-rounded — the pinned order described in §2.6."
    PRD: "The subtotal is `base_line_cents` plus `seat_line_cents`."

    Design: Difficulty/combinatorial_formula/seat_charge_rounds_per_line_then_sums
    """
    state = _arrange_three_claimed_seats_spanning_eight_days_of_the_second_cycle()

    invoice = state["invoice"]
    assert state["subscription"]["cycle_index"] == 2
    assert invoice["cycle_index"] == 2
    assert invoice["base_line_cents"] == 5000
    assert invoice["seat_line_cents"] == 321
    assert invoice["seat_line_cents"] != 320
    assert invoice["total_cents"] == 5321
    assert_invoice_waterfall(invoice)


def test_the_three_billed_seats_stay_active_and_saturate_the_group_capacity():
    """All three seats overlap, so peak concurrency fills the capacity-three group.

    PRD: "The seats that participate are those on the subscription's group account whose `status` is `ACTIVE` or `RECLAIMED`, whose `starts_on` is strictly before the cycle end, and whose `ends_on` is either null or strictly after the cycle start; `INVITED` and `EXPIRED` seats are never billed."
    PRD: "The group's derived counters use the **same** peak-occupancy measure, computed over the `INVITED` and `ACTIVE` seats only with the candidate excluded: `seats_assigned_count` is that peak, and `seats_available_count` is `seat_capacity` less `seats_assigned_count`, floored at zero."

    Design: Difficulty/combinatorial_formula/seat_charge_rounds_per_line_then_sums
    """
    state = _arrange_three_claimed_seats_spanning_eight_days_of_the_second_cycle()

    for seat in state["seats"]:
        assert read_seat(seat["id"])["status"] == "ACTIVE"
    group = read_group(state["group"]["id"])
    assert group["seats_assigned_count"] == 3
    assert group["seats_available_count"] == 0
    assert_seat_capacity_conserved(group)


def _arrange_accepted_discount_and_completed_vacation_credit_at_cycle_two():
    """A 20 percent retention discount and a 450-cent hold credit meeting one invoice."""
    set_clock_date("2026-09-01")
    plan = create_active_print_plan(
        name="Print + Digital",
        intro_price_cents=999,
        intro_cycles=1,
        standard_price_cents=1899,
        standard_from_cycle=2,
        cycle_days=30,
        print_component_cents=900,
        print_deliveries_per_cycle=4,
        print_delivery_days=["SUN"],
    )
    reader = create_registered_reader("pinned@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 999)

    hold = create_hold(
        subscription["id"],
        "VACATION_DELIVERY",
        "2026-09-06",
        "2026-09-13",
        reader_headers,
    )
    request = start_cancellation(subscription["id"], "PRICE", reader_headers)
    offer = present_save_offer(
        request["id"], "RETENTION_DISCOUNT", discount_pct=0.20, duration_cycles=3
    )
    validate_success(
        api_client.decide_save_offer(offer["id"], "ACCEPTED", reader_headers), 200
    )

    set_clock_date("2026-09-10")
    run_billing("HOLDS_ONLY")
    set_clock_date("2026-09-14")
    run_billing("HOLDS_ONLY")
    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    return {
        "plan": plan,
        "reader": reader,
        "reader_headers": reader_headers,
        "subscription": read_subscription(subscription["id"]),
        "hold": read_hold(hold["id"]),
        "request": read_cancellation_request(request["id"]),
        "invoice": invoice_for_cycle(subscription["id"], 2),
    }


def test_vacation_hold_credit_is_frozen_at_two_delivery_days_and_completes_before_billing():
    """A Sunday-only plan credits 09-06 and 09-13 at 225 each, and the hold completes.

    PRD: "For the two print types, the daily print rate is the plan's `print_component_cents` divided by its `print_deliveries_per_cycle`, rounded half up to whole cents **once**; `delivery_days_credited` is the number of dates in the closed interval from `start_date` through `end_date` inclusive whose weekday code appears in the plan's `print_delivery_days`; and `credit_cents` is that rounded daily rate multiplied by `delivery_days_credited`, with no further rounding."
    PRD: "The same pass retires holds that have run their course: an `ACTIVE` hold whose `end_date` is strictly before the clock date becomes `COMPLETED`, is reported in `holds_completed`, and its credit stays inside `pending_credit_cents` until a BILLING pass sweeps it onto an invoice."

    Design: Difficulty/combinatorial_formula/invoice_total_pins_discount_tier_before_credits
    """
    state = _arrange_accepted_discount_and_completed_vacation_credit_at_cycle_two()

    hold = state["hold"]
    assert hold["delivery_days_credited"] == 2
    assert hold["credit_cents"] == 450
    assert hold["status"] == "COMPLETED"


def test_discount_tier_is_keyed_on_the_pre_credit_subtotal_and_takes_the_high_value_uplift():
    """1899 clears the 1500 threshold, so 0.20 becomes 0.30 and the line is 570.

    PRD: "The discount fraction starts as the subscription's `retention_discount_pct` when `retention_discount_cycles_remaining` is at least 1, and 0 otherwise. When that fraction is greater than zero **and** the subtotal is at least 1500 cents — fifteen dollars, the high-value threshold — the fraction is upgraded by ten percentage points, then capped at the forty-percent save-offer ceiling: the fraction becomes the lesser of the uplifted fraction and 0.40."
    PRD: "`discount_line_cents` is the subtotal multiplied by that fraction, rounded half up to whole cents."
    PRD: "Every invoice, whether the cycle-1 invoice created at subscription time or a later invoice created by the BILLING pass, is assembled by the same waterfall, and the evaluation order is pinned because the discount tier is keyed on the pre-credit subtotal — credits reduce what the reader pays but can never change the discount percentage."

    Design: Difficulty/combinatorial_formula/invoice_total_pins_discount_tier_before_credits
    """
    state = _arrange_accepted_discount_and_completed_vacation_credit_at_cycle_two()

    invoice = state["invoice"]
    assert invoice["base_line_cents"] == 1899
    assert invoice["seat_line_cents"] == 0
    assert invoice["discount_line_cents"] == 570
    assert invoice["credit_line_cents"] == 450
    assert invoice["total_cents"] == 879
    assert invoice["status"] == "OPEN"
    assert_invoice_waterfall(invoice)


def test_swept_credit_moves_from_pending_to_lifetime_and_burns_one_discount_cycle():
    """The sweep stamps the billed cycle on the hold and the discount counter drops to two.

    PRD: "Every hold swept in step 6 has its `credit_applied` set to true and its `credit_applied_cycle_index` set to the cycle this invoice bills, which is also what moves that money out of `pending_credit_cents` and into `lifetime_credit_cents`. When the discount fraction was greater than zero, `retention_discount_cycles_remaining` is decremented by one."
    PRD: "Accepting takes the retention branch. The offer becomes `ACCEPTED` with `decided_on` at the clock date, the request moves `SAVE_OFFER_PRESENTED → SAVE_OFFER_ACCEPTED`, and `retained` becomes true."

    Design: Difficulty/combinatorial_formula/invoice_total_pins_discount_tier_before_credits
    """
    state = _arrange_accepted_discount_and_completed_vacation_credit_at_cycle_two()

    hold = state["hold"]
    assert hold["credit_applied"] is True
    assert hold["credit_applied_cycle_index"] == 2
    subscription = state["subscription"]
    assert subscription["pending_credit_cents"] == 0
    assert subscription["lifetime_credit_cents"] == 450
    assert subscription["retention_discount_cycles_remaining"] == 2
    assert subscription["lifecycle_status"] == "ACTIVE"
    assert state["request"]["status"] == "SAVE_OFFER_ACCEPTED"
    assert_hold_credit_bookkeeping(subscription, list_holds(subscription["id"]))
