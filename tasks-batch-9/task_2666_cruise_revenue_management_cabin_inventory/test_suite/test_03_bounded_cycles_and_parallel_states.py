"""
Cycles that re-enter an earlier state, and two dimensions moving independently.

Three of the state graphs in this API are not chains. A sailing loops
OPEN_FOR_SALE -> SALES_SUSPENDED -> OPEN_FOR_SALE twice; an upgrade bid loops
SUBMITTED -> COUNTERED -> SUBMITTED twice; and a booking's money dimension walks
its own path while the inventory dimension stands still.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_MAX_COUNTER_ROUNDS_EXCEEDED,
    ERR_SUSPENSION_LIMIT_REACHED,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    make_guest_headers,
)


def test_third_sales_suspension_is_refused_after_two_complete_loops(api):
    """suspension_count is the monotone counter that terminates the loop.

    PRD 3.9: "Suspending requires status OPEN_FOR_SALE - otherwise
    ERR_SAILING_NOT_OPEN - and suspension_count strictly below 2, otherwise
    ERR_SUSPENSION_LIMIT_REACHED." And: "The bound lives on the suspend side: the
    third suspend attempt fails, so at most two full suspend-and-resume loops are
    possible over a sailing's life."

    Design: Difficulty/non_linear_state_machine/sailing_sales_suspension_resume_cycle_bounded_at_two
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    sailing_id = world.sailing["id"]

    fx.suspend_sailing(api, sailing_id, "DEMAND_REVIEW_ROUND_1")
    fx.resume_sailing(api, sailing_id)
    fx.suspend_sailing(api, sailing_id, "DEMAND_REVIEW_ROUND_2")
    fx.resume_sailing(api, sailing_id)

    response = api.suspend_sales(
        sailing_id, {"reason": "DEMAND_REVIEW_ROUND_3"}, REVENUE_MANAGER
    )
    validate_error(response, ERR_SUSPENSION_LIMIT_REACHED, 422)

    sailing = fx.read_sailing(api, sailing_id)
    # The refusal leaves the sailing sitting in the earlier state of the loop.
    assert sailing["status"] == "OPEN_FOR_SALE"
    assert sailing["suspension_count"] == 2
    assert sailing["suspension_reason"] is None


def test_suspension_stores_its_reason_and_resuming_clears_it(api):
    """One traversal of the loop: the reason is stored, then cleared on resume.

    PRD 3.9: "A suspension raises suspension_count by 1, stores the supplied
    reason in suspension_reason, and moves the sailing to SALES_SUSPENDED." And:
    "Resuming requires status SALES_SUSPENDED - otherwise
    ERR_SAILING_NOT_SUSPENDED - clears suspension_reason back to null, and
    returns the sailing to OPEN_FOR_SALE."

    Design: Difficulty/non_linear_state_machine/sailing_sales_suspension_resume_cycle_bounded_at_two
    """
    world = fx.simple_world(api, voyage_code="AUR-2702")
    sailing_id = world.sailing["id"]

    suspended = fx.suspend_sailing(api, sailing_id, "DEMAND_REVIEW_ROUND_1")
    assert suspended["status"] == "SALES_SUSPENDED"
    assert suspended["suspension_count"] == 1
    assert suspended["suspension_reason"] == "DEMAND_REVIEW_ROUND_1"

    resumed = fx.resume_sailing(api, sailing_id)
    assert resumed["status"] == "OPEN_FOR_SALE"
    assert resumed["suspension_reason"] is None
    # The counter is never reset by a resume, which is what bounds the cycle.
    assert resumed["suspension_count"] == 1


def _confirmed_booking_gone_delinquent(api):
    """A CONFIRMED booking whose final payment deadline has passed.

    The booking is written at the default clock (net 438,487, deposit 87,697,
    final payment due 2026-10-27T17:00:00Z), the deposit is paid, the booking is
    confirmed, and the sweep then runs one day past the deadline.
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(
        api,
        world.sailing["id"],
        world.category["id"],
        guest["id"],
        third_berth_guests=1,
    )
    assert booking["deposit_due_cents"] == 87697
    fx.pay(api, booking["id"], "DEPOSIT", 87697)
    fx.confirm(api, booking["id"])
    fx.set_clock(api, "2026-10-28T00:00:00Z")
    fx.run_ops(api, world.sailing["id"])
    world.guest = guest
    world.booking = fx.read_booking(api, booking["id"])
    return world


def test_overdue_final_payment_moves_only_the_money_dimension(api):
    """The sweep marks the booking DELINQUENT while it stays CONFIRMED.

    PRD 3.5: "a booking sitting in DEPOSIT_PAID whose final_payment_due_date now
    lies strictly before the current instant moves DEPOSIT_PAID -> DELINQUENT.
    Both require booking_status to be OPTION or CONFIRMED, both stamp
    delinquent_since with the current instant". PRD 3.5 also states that the two
    dimensions are independent: "Neither dimension drives the other
    automatically".

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_dimensions_evolve_independently
    """
    world = _confirmed_booking_gone_delinquent(api)

    assert world.booking["booking_status"] == "CONFIRMED"
    assert world.booking["payment_status"] == "DELINQUENT"
    assert_instant_equals(
        world.booking["delinquent_since"], "2026-10-28T00:00:00Z", "delinquent_since"
    )
    assert world.booking["amount_paid_cents"] == 87697
    assert world.booking["balance_due_cents"] == 350790


def test_delinquency_cure_re_enters_paid_in_full_leaving_booking_status_alone(api):
    """The money dimension walks four states; the inventory dimension none.

    PRD 3.5: "From DELINQUENT there is a cure: a FINAL_PAYMENT of exactly
    balance_due_cents posted while the current instant is strictly earlier than
    delinquent_since plus 7 days moves the booking DELINQUENT -> PAID_IN_FULL,
    clears delinquent_since, and raises the sailing's paid-in-full counter. On
    this cure path the overdue guard does not apply."

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_dimensions_evolve_independently
    """
    world = _confirmed_booking_gone_delinquent(api)
    booking_id = world.booking["id"]

    validate_success(
        api.post_payment(
            booking_id, f.payment_payload("FINAL_PAYMENT", 350790), RESERVATION_AGENT
        ),
        201,
    )

    booking = fx.read_booking(api, booking_id)
    assert booking["booking_status"] == "CONFIRMED"
    assert booking["payment_status"] == "PAID_IN_FULL"
    assert booking["delinquent_since"] is None
    assert booking["amount_paid_cents"] == 438487
    assert booking["balance_due_cents"] == 0

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["confirmed_bookings_count"] == 1
    assert sailing["paid_in_full_bookings_count"] == 1
    # PRD 3.5: the flag needs twice the paid count to be below the confirmed one.
    assert sailing["final_payment_risk_flag"] is False

    ledger = fx.payment_events(api, booking_id)
    assert [event["kind"] for event in ledger] == ["DEPOSIT", "FINAL_PAYMENT"]
    assert [event["amount_cents"] for event in ledger] == [87697, 350790]


def _bid_at_the_far_edge_of_the_window(api):
    """An IA booking with a bid on OV submitted at exactly 60 days to sail.

    At that instant the IA -> OV floor is 21,000 per guest: the 70,000-cent fare
    gap taken at two fifths (28,000) less the per-guest share of the 14,000-cent
    onboard uplift (7,000).
    """
    world = fx.upgrade_bid_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(
        api, world.sailing["id"], world.ia["id"], guest["id"], occupancy_adults=2
    )
    assert booking["net_ticket_cents"] == 379990
    fx.set_clock(api, "2026-11-11T17:00:00Z")
    bid = fx.submit_bid(api, booking, guest["id"], world.ov["id"], 21000)
    world.guest = guest
    world.booking = booking
    world.bid = bid
    return world


def test_third_bid_counter_is_refused_after_two_negotiation_loops(api):
    """counter_rounds is never reset, so the cycle is bounded from the counter side.

    PRD 3.7: "counter_rounds must be below 2 (otherwise
    ERR_MAX_COUNTER_ROUNDS_EXCEEDED)". And: "counter_rounds is never reset, so at
    most two full negotiation loops are possible on any one bid."

    Design: Difficulty/non_linear_state_machine/upgrade_bid_counter_rebid_cycle_bounded_at_two
    """
    world = _bid_at_the_far_edge_of_the_window(api)
    bid_id = world.bid["id"]
    guest_headers = make_guest_headers(world.guest["id"])

    validate_success(api.counter_bid(bid_id, REVENUE_MANAGER))
    validate_success(
        api.rebid(bid_id, {"bid_amount_per_guest_cents": 21000}, guest_headers)
    )
    validate_success(api.counter_bid(bid_id, REVENUE_MANAGER))
    validate_success(
        api.rebid(bid_id, {"bid_amount_per_guest_cents": 22000}, guest_headers)
    )

    response = api.counter_bid(bid_id, REVENUE_MANAGER)
    validate_error(response, ERR_MAX_COUNTER_ROUNDS_EXCEEDED, 422)

    bid = fx.read_bid(api, bid_id)
    assert bid["status"] == "SUBMITTED"
    assert bid["counter_rounds"] == 2
    assert bid["submitted_days_to_sail"] == 60
    assert bid["min_acceptable_per_guest_cents"] == 21000
    assert bid["countered_min_per_guest_cents"] == 21000
    assert bid["bid_amount_per_guest_cents"] == 22000
    assert bid["guest_count"] == 2
    assert bid["award_amount_cents"] is None


def test_rebid_promotes_the_countered_floor_to_the_binding_one(api):
    """One traversal: the counter publishes a floor, the re-bid makes it binding.

    PRD 3.7: "Countering raises counter_rounds by 1, re-evaluates the floor at
    the current instant and publishes it as countered_min_per_guest_cents". And:
    "A re-bid overwrites bid_amount_per_guest_cents with the supplied value and
    promotes the published floor to binding by copying
    countered_min_per_guest_cents into min_acceptable_per_guest_cents."

    Design: Difficulty/non_linear_state_machine/upgrade_bid_counter_rebid_cycle_bounded_at_two
    """
    world = _bid_at_the_far_edge_of_the_window(api)
    bid_id = world.bid["id"]

    countered = validate_success(api.counter_bid(bid_id, REVENUE_MANAGER))
    assert countered["status"] == "COUNTERED"
    assert countered["counter_rounds"] == 1
    assert countered["countered_min_per_guest_cents"] == 21000

    rebid = validate_success(
        api.rebid(
            bid_id,
            {"bid_amount_per_guest_cents": 21000},
            make_guest_headers(world.guest["id"]),
        )
    )
    assert rebid["status"] == "SUBMITTED"
    assert rebid["bid_amount_per_guest_cents"] == 21000
    assert rebid["min_acceptable_per_guest_cents"] == 21000
    assert rebid["counter_rounds"] == 1
