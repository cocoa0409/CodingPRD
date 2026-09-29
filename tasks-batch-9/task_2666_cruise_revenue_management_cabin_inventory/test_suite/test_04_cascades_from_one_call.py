"""
Single calls whose effects propagate through four or five entities.

PRD 2.8: "This API keeps derived state consistent immediately, inside the request
that caused the change - there is no deferred reconciliation."
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    GROUP_SALES_AGENT_2,
    PORT_OPS_COORDINATOR,
    REVENUE_MANAGER,
    assert_instant_equals,
    fixtures as fx,
)

FLAT_FARE_145K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 145000,
    "third_berth_fare_cents": 50000,
    "fourth_berth_fare_cents": 40000,
}

FLAT_FARE_150K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 150000,
    "third_berth_fare_cents": 50000,
    "fourth_berth_fare_cents": 40000,
}


def _sailing_exactly_on_the_alert_floor(api):
    """A 4-berth / 5-night voyage sitting exactly on the 20,000-cent alert floor.

    One 2-adult OV booking contributes 290,000 of ticket revenue and 110,000 of
    projected onboard spend over 20 available lower-berth days.
    """
    ocean_view = fx.make_category(
        api,
        code="OV",
        tier_rank=2,
        max_occupancy=4,
        onboard_spend_lower_per_night_cents=11000,
        onboard_spend_upper_per_night_cents=7000,
    )
    world = fx.simple_world(
        api,
        voyage_code="PRT-2701",
        embark_date="2027-03-01T16:00:00Z",
        nights=5,
        total_lower_berths=4,
        category=ocean_view,
        physical_cabins=2,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_145K,
    )
    world.pair = fx.guest_with_booking(api, world)
    world.change = fx.make_itinerary_change(
        api,
        world.sailing["id"],
        kind="PORT_CANCELLED",
        affected_port_code="GRC",
        compensation_policy="OBC_PLUS_REFUND_PCT",
    )
    return world


def test_draft_itinerary_change_grants_nothing_before_publication(api):
    """A DRAFT change freezes its parameters but moves no money.

    PRD 3.8: "The change is created in DRAFT with published_at null and
    affected_bookings_count, total_obc_granted_cents, and
    total_refund_granted_cents all 0. Nothing is granted to anybody while the
    change sits in DRAFT." PRD 3.8 also fixes the two parameters at creation:
    "obc_per_guest_cents is 5,000 cents (50.00 in whole currency units) under
    OBC_PLUS_REFUND_PCT" and refund_pct "is 0.05 for the two port-level kinds".

    Design: Difficulty/transitive_cascade/itinerary_publish_cascades_to_sailing_revenue_alert
    """
    world = _sailing_exactly_on_the_alert_floor(api)

    change = fx.read_itinerary_change(api, world.change["id"])
    assert change["status"] == "DRAFT"
    assert change["published_at"] is None
    assert change["obc_per_guest_cents"] == 5000
    assert change["refund_pct"] == 0.05
    assert change["affected_bookings_count"] == 0
    assert change["total_obc_granted_cents"] == 0
    assert change["total_refund_granted_cents"] == 0

    booking = fx.read_booking(api, world.pair.booking["id"])
    assert booking["itinerary_compensation_obc_cents"] == 0
    assert booking["itinerary_refund_cents"] == 0
    assert booking["projected_onboard_net_cents"] == 110000
    assert booking["balance_due_cents"] == 290000

    sailing = fx.read_sailing(api, world.sailing["id"])
    # 400,000 of revenue over 20 available lower-berth days is exactly the floor.
    assert sailing["ralbd_net_cents"] == 20000
    assert sailing["revenue_alert"] is False


def test_publishing_a_port_cancellation_flips_the_sailing_revenue_alert(api):
    """One publish walks change -> booking -> onboard projection -> sailing -> alert.

    PRD 3.8: "Its itinerary_compensation_obc_cents is increased by
    obc_per_guest_cents multiplied by the booking's guest_count, and its
    itinerary_refund_cents is increased by net_ticket_cents multiplied by
    refund_pct, rounded half up per booking." And: "At the sailing level,
    projected_onboard_revenue_cents and compensation_liability_cents are
    recomputed, then ralbd_gross_cents and ralbd_net_cents, and then
    revenue_alert from the refreshed net figure."

    Design: Difficulty/transitive_cascade/itinerary_publish_cascades_to_sailing_revenue_alert
    """
    world = _sailing_exactly_on_the_alert_floor(api)

    published = validate_success(
        api.publish_itinerary_change(world.change["id"], PORT_OPS_COORDINATOR)
    )

    assert published["status"] == "PUBLISHED"
    assert_instant_equals(
        published["published_at"], "2026-08-01T00:00:00Z", "published_at"
    )
    assert published["obc_per_guest_cents"] == 5000
    assert published["refund_pct"] == 0.05
    assert published["affected_bookings_count"] == 1
    assert published["total_obc_granted_cents"] == 10000
    assert published["total_refund_granted_cents"] == 14500

    booking = fx.read_booking(api, world.pair.booking["id"])
    assert booking["itinerary_compensation_obc_cents"] == 10000
    assert booking["itinerary_refund_cents"] == 14500
    assert booking["projected_onboard_gross_cents"] == 110000
    # PRD 3.8: onboard credit is spend the guest no longer makes.
    assert booking["projected_onboard_net_cents"] == 100000
    assert booking["balance_due_cents"] == 275500
    # PRD 3.8: compensation is a credit, never a repricing of the ticket.
    assert booking["net_ticket_cents"] == 290000

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["projected_onboard_revenue_cents"] == 100000
    assert sailing["compensation_liability_cents"] == 24500
    assert sailing["ralbd_gross_cents"] == 18275
    assert sailing["ralbd_net_cents"] == 18275
    assert sailing["revenue_alert"] is True


def _fenced_sailing_with_two_waitlisted_bookings(api):
    """A 2-cabin IA allotment fully fenced by one block, with two guests queued.

    Both cabins are held, so available_cabins is 0 and each sale lands
    WAITLISTED. The clock is left standing on the block's review date.
    """
    world = fx.simple_world(
        api,
        voyage_code="WLT-2701",
        nights=4,
        total_lower_berths=20,
        physical_cabins=2,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_150K,
    )
    world.block = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        cabins_held=2,
        review_date="2026-08-15T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    world.queue = fx.waitlisted_bookings(api, world, 2)
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    return world


def test_group_review_release_reprices_the_whole_sailing(api):
    """One review walks block -> allotment -> booking -> sailing occupancy and RALBD.

    PRD 3.3: "under FULL_RELEASE the released quantity is that entire remainder,
    and under ATTRITION_50 it is the remainder multiplied by one half and rounded
    down to a whole cabin." And: "Because available_cabins has risen above zero,
    the waitlist queue for that allotment is then worked, and finally the
    sailing's occupancy chain ... and revenue chain ... are recomputed."

    Design: Difficulty/transitive_cascade/group_review_release_promotes_waitlist_and_reprices_sailing
    """
    world = _fenced_sailing_with_two_waitlisted_bookings(api)

    reviewed = validate_success(
        api.review_group_block(world.block["id"], GROUP_SALES_AGENT_2)
    )

    assert reviewed["status"] == "PARTIALLY_RELEASED"
    assert reviewed["cabins_held"] == 1
    assert reviewed["released_cabins_total"] == 1
    assert reviewed["review_count"] == 1

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["group_held_cabins"] == 1
    assert inventory["released_cabins_total"] == 1
    assert inventory["booked_cabins"] == 1
    assert inventory["waitlisted_bookings_count"] == 1
    assert inventory["available_cabins"] == 0

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["lower_berths_sold"] == 2
    assert sailing["occupancy_pct"] == 10.00
    assert sailing["inventory_posture"] == "OPEN"
    assert sailing["gross_ticket_revenue_cents"] == 300000
    assert sailing["projected_onboard_revenue_cents"] == 72000
    assert sailing["available_lower_berth_days_gross"] == 80
    assert sailing["available_lower_berth_days_net"] == 72
    assert sailing["ralbd_gross_cents"] == 4650
    assert sailing["ralbd_net_cents"] == 5167


def test_the_freed_cabin_goes_to_the_earliest_queued_booking_unrepriced(api):
    """First-come first-served, and the promoted fare is the pinned one.

    PRD 3.3: "Eligible bookings are ranked by created_at ascending first - the
    queue is first-come, first-served". And: "Promotion off the waitlist is
    deliberately not a repricing event. The promoted booking keeps its
    net_ticket_cents, its fare_rule_id, and its pinned_fare_rule_version exactly
    as they were pinned at creation - the fare survives the wait. What does
    change is the money clock: deposit_due_date is reset to the current instant
    plus the sailing's deposit_due_days_after_booking days".

    Design: Difficulty/transitive_cascade/group_review_release_promotes_waitlist_and_reprices_sailing
    """
    world = _fenced_sailing_with_two_waitlisted_bookings(api)
    first, second = world.queue

    fx.read_block(api, world.block["id"])
    validate_success(api.review_group_block(world.block["id"], GROUP_SALES_AGENT_2))

    promoted = fx.read_booking(api, first.booking["id"])
    assert promoted["booking_status"] == "OPTION"
    assert promoted["net_ticket_cents"] == 300000
    assert promoted["fare_rule_id"] == world.fare_rule["id"]
    assert_instant_equals(
        promoted["deposit_due_date"], "2026-08-22T00:00:00Z", "deposit_due_date"
    )

    still_queued = fx.read_booking(api, second.booking["id"])
    assert still_queued["booking_status"] == "WAITLISTED"

    summary = validate_success(
        api.revenue_summary(world.sailing["id"], REVENUE_MANAGER)
    )
    assert summary["lower_berths_sold"] == 2
