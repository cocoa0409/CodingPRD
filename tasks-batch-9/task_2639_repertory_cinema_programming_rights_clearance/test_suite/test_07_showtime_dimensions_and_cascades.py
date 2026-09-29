"""The screening's three independent status dimensions and the cascades that pull them.

A screening carries a lifecycle `status`, a ticketing `sale_status` and a
technical `playback_status`, and each moves on its own schedule. When a key is
revoked, an event is confirmed or an engagement is withdrawn, the cascade
reaches through the screening into orders, licences and member ledgers.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_screen_block,
    assert_screening_allowance_conserved,
    assert_seat_conservation,
    assert_showtime,
    assert_special_event,
    close_showtime_sales,
    confirm_event,
    mark_showtime_played,
    open_showtime_sales,
    pay_for_order,
    place_showtime,
    plan_event,
    read_booking,
    read_clearance,
    read_event,
    read_kdm,
    read_member,
    read_order,
    read_showtime,
    revoke_kdm,
    sell_seats,
    set_logical_clock,
    setup_key_pending_screening,
    setup_member_at_tier,
    setup_programming_baseline,
    setup_verified_screening,
    verify_booth_playback,
    validate_error,
    withdraw_engagement,
)


class TestThreeIndependentStatusDimensions:
    """Ticketing, technical and lifecycle state advance without waiting on each other."""

    def test_sales_open_and_sell_out_while_playback_is_still_unverified(self):
        """A screening with no key cut yet can be sold to the last seat.

        PRD: "A screening's ticketing dimension, `sale_status`, evolves entirely independently of its technical dimension, `playback_status`."

        Design: Difficulty/non_linear_state_machine/showtime_three_parallel_status_dimensions_evolve_independently
        """
        world = setup_programming_baseline()
        showtime = place_showtime(world, "2026-08-14T12:00:00Z")
        assert showtime["playback_status"] == "UNVERIFIED"

        opened = open_showtime_sales(showtime["id"])
        assert opened["sale_status"] == "ON_SALE"
        assert opened["playback_status"] == "UNVERIFIED"

        sell_seats(showtime["id"], 8, purchaser_email="walkup@example.com")

        sold_out = read_showtime(showtime["id"])
        assert_showtime(sold_out)
        assert sold_out["sale_status"] == "SOLD_OUT"
        assert sold_out["playback_status"] == "UNVERIFIED", (
            "the ticketing dimension never touches the technical one"
        )
        assert sold_out["status"] == "SCHEDULED"

    def test_playback_verifies_while_the_screening_is_still_in_draft(self):
        """The booth can key and test a show the box office has not opened.

        PRD: "A screening whose KDM has not yet been cut may still go on sale, and a screening that has passed its booth test may still be sitting in `DRAFT`."

        Design: Difficulty/non_linear_state_machine/showtime_three_parallel_status_dimensions_evolve_independently
        """
        world = setup_key_pending_screening("2026-08-14T12:00:00Z")
        armed = read_showtime(world["showtime"]["id"])
        assert armed["playback_status"] == "KEY_PENDING"
        assert armed["sale_status"] == "DRAFT"

        verified = verify_booth_playback(world["showtime"]["id"], "PASS")

        assert verified["playback_status"] == "PLAYBACK_VERIFIED"
        assert verified["sale_status"] == "DRAFT", (
            "the technical dimension never opens the box office"
        )
        assert verified["status"] == "SCHEDULED"

    def test_lifecycle_completion_waits_for_both_other_dimensions(
        self, box_office_headers
    ):
        """Completion is refused while sales are open and admitted once they close.

        PRD: "Four conditions must hold, and any failure yields `ERR_SHOWTIME_INVALID_STATE`: the screening's status is `SCHEDULED`, its `sale_status` is `SALES_CLOSED`, its `playback_status` is `PLAYBACK_VERIFIED`, and the logical clock has reached or passed its `end_at`."

        Design: Difficulty/non_linear_state_machine/showtime_three_parallel_status_dimensions_evolve_independently
        """
        world = setup_verified_screening("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]
        open_showtime_sales(showtime_id)
        set_logical_clock("2026-08-14T14:00:00Z")

        validate_error(
            api_client.complete_showtime(showtime_id, box_office_headers),
            ApiErrorId.ERR_SHOWTIME_INVALID_STATE,
        )
        assert read_showtime(showtime_id)["status"] == "SCHEDULED"

        close_showtime_sales(showtime_id)
        completed = mark_showtime_played(showtime_id)

        assert completed["status"] == "COMPLETED"
        assert completed["sale_status"] == "SALES_CLOSED"
        assert completed["playback_status"] == "PLAYBACK_VERIFIED"


def _key_pending_world_with_a_held_order():
    """An on-sale, key-pending screening carrying one RESERVED member hold."""
    world = setup_key_pending_screening("2026-08-14T12:00:00Z")
    open_showtime_sales(world["showtime"]["id"])
    member = setup_member_at_tier("SUPPORTER")
    world["member"] = member
    world["order"] = sell_seats(
        world["showtime"]["id"], 2,
        purchaser_email="ada@example.com", member_id=member["id"],
    )
    world["showtime"] = read_showtime(world["showtime"]["id"])
    return world


class TestKeyRevocationCascade:
    """Revoking the only covering key pulls playback, sales and the held orders."""

    def test_revocation_drops_playback_to_unverified_and_closes_the_box_office(self):
        """With no other key covering it, the screening loses both arming and sales.

        PRD: "**Hop two:** because the key is gone, every screening at that auditorium on that package whose status is `SCHEDULED` and whose `playback_status` is `KEY_PENDING` or `PLAYBACK_VERIFIED`, and for which no *other* `ISSUED` key still provides coverage, falls back to `UNVERIFIED`; and if such a screening's `sale_status` is `ON_SALE` or `SOLD_OUT` it is forced to `SALES_CLOSED`, because a house cannot keep selling a show it can no longer project."

        Design: Difficulty/transitive_cascade/kdm_revoke_pulls_sales_and_refunds_depth_three
        """
        world = _key_pending_world_with_a_held_order()
        assert world["showtime"]["playback_status"] == "KEY_PENDING"
        assert world["showtime"]["sale_status"] == "ON_SALE"

        revoke_kdm(world["key"]["id"], "wrong server certificate")

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["playback_status"] == "UNVERIFIED"
        assert showtime["sale_status"] == "SALES_CLOSED"

    def test_revocation_voids_the_unpaid_hold_and_recomputes_the_seat_rollup(self):
        """The two held seats return to the house at hop three.

        PRD: "**Hop three:** because those screenings' sales have been pulled, their ticket orders in `RESERVED` become `VOID` — unpaid holds are released — and each affected screening's `seats_sold` and `seats_available` are recomputed from the surviving orders."

        Design: Difficulty/transitive_cascade/kdm_revoke_pulls_sales_and_refunds_depth_three
        """
        world = _key_pending_world_with_a_held_order()
        assert world["showtime"]["seats_sold"] == 2

        revoke_kdm(world["key"]["id"], "wrong server certificate")

        order = read_order(world["order"]["id"])
        assert order["status"] == "VOID"
        assert order["refund_destination"] is None, "a released hold is not a refund"

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["seats_sold"] == 0
        assert showtime["seats_available"] == 8
        assert_seat_conservation(showtime, world["venue"])

    def test_revocation_cascade_stops_short_of_the_licence_and_the_package(self):
        """The screening keeps its slot and its allowance; only the key dies.

        PRD: "**Hop one** records the supplied `revoked_reason` and moves the key `ISSUED → REVOKED`."

        Design: Difficulty/transitive_cascade/kdm_revoke_pulls_sales_and_refunds_depth_three
        """
        world = _key_pending_world_with_a_held_order()

        revoke_kdm(world["key"]["id"], "wrong server certificate")

        key = read_kdm(world["key"]["id"])
        assert key["status"] == "REVOKED"
        assert key["revoked_reason"] == "wrong server certificate"

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["status"] == "SCHEDULED", "the screening is not cancelled"

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 1
        assert clearance["screenings_remaining"] == 5
        assert_screening_allowance_conserved(clearance)


def _event_world_with_a_later_paid_screening():
    """A 19:00 screening carrying a planned event, and a 21:30 screening on sale."""
    world = setup_programming_baseline()
    world["first"] = place_showtime(world, "2026-08-10T19:00:00Z")
    world["second"] = place_showtime(world, "2026-08-10T21:30:00Z")
    open_showtime_sales(world["second"]["id"])
    world["member"] = setup_member_at_tier("SUPPORTER")
    order = sell_seats(
        world["second"]["id"], 2,
        purchaser_email="ada@example.com", member_id=world["member"]["id"],
    )
    world["order"] = pay_for_order(order["id"])
    world["event"] = plan_event(
        world["first"]["id"],
        guest_name="R. Marker",
        extra_minutes=30,
        surcharge_cents=500,
        guest_fee_cents=25000,
    )
    return world


class TestSpecialEventDisplacementCascade:
    """Confirming an event grows one block and unwinds everything it now covers."""

    def test_confirmation_extends_the_block_and_prices_the_surcharge(self):
        """Thirty extra minutes push end_at to 21:26 and blocked_until to 21:51.

        PRD: "**Hop one:** the event moves `PLANNED → CONFIRMED`, the screening's `extra_minutes` is set from the event's `extra_minutes` and its `surcharge_cents` from the event's `surcharge_cents`, and both `end_at` and `blocked_until` are recomputed and therefore both move later."

        Design: Difficulty/transitive_cascade/special_event_confirm_displacement_depth_four_cascade
        """
        world = _event_world_with_a_later_paid_screening()
        assert world["event"]["status"] == "PLANNED"
        assert world["first"]["end_at"] == "2026-08-10T20:56:00.000Z"

        confirmed = confirm_event(world["event"]["id"], displace_conflicts=True)

        assert_special_event(confirmed)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["guest_fee_cents"] == 25000

        host = read_showtime(world["first"]["id"])
        assert host["extra_minutes"] == 30
        assert host["surcharge_cents"] == 500
        assert_screen_block(
            host, "2026-08-10T21:26:00.000Z", "2026-08-10T21:51:00.000Z"
        )

    def test_enlarged_block_displaces_the_later_screening(self):
        """The 21:30 show now sits inside the enlarged block and is cancelled.

        PRD: "**Hop two:** because `blocked_until` moved, every other screening at that auditorium whose status is `SCHEDULED` and whose own occupancy interval now intersects the enlarged block becomes `CANCELLED` with `cancel_reason` set to `DISPLACED_BY_SPECIAL_EVENT`, its `sale_status` forced to `SALES_CLOSED`, and its `id` appended to the event's `displaced_showtime_ids`."

        Design: Difficulty/transitive_cascade/special_event_confirm_displacement_depth_four_cascade
        """
        world = _event_world_with_a_later_paid_screening()

        confirmed = confirm_event(world["event"]["id"], displace_conflicts=True)

        assert confirmed["displaced_showtime_ids"] == [world["second"]["id"]]

        displaced = read_showtime(world["second"]["id"])
        assert displaced["status"] == "CANCELLED"
        assert displaced["cancel_reason"] == "DISPLACED_BY_SPECIAL_EVENT"
        assert displaced["sale_status"] == "SALES_CLOSED"

    def test_displacement_refunds_the_paid_order_and_returns_the_allowance(self):
        """The licence takes back the displaced screening and the order is reversed.

        PRD: "**Hop three:** because those screenings are cancelled, their `RESERVED` orders become `VOID` and their `PAID` orders become `REFUNDED`, each displaced screening's licence gets `screenings_used` reduced by one with the licence's `version` incremented, and each displaced screening's engagement gets `scheduled_showtime_count` reduced by one."

        Design: Difficulty/transitive_cascade/special_event_confirm_displacement_depth_four_cascade
        """
        world = _event_world_with_a_later_paid_screening()

        confirm_event(world["event"]["id"], displace_conflicts=True)

        order = read_order(world["order"]["id"])
        assert order["status"] == "REFUNDED"
        assert order["refund_destination"] == "MEMBER_CREDIT"
        assert order["total_cents"] == 2766

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 1
        assert clearance["screenings_remaining"] == 5
        assert_screening_allowance_conserved(clearance)

        booking = read_booking(world["booking"]["id"])
        assert booking["scheduled_showtime_count"] == 1

    def test_displacement_banks_the_refund_as_member_credit(self):
        """The member's credit rises by the whole refunded total at hop four.

        PRD: "**Hop four:** because the paid member orders were refunded to member credit, each affected member's `credit_balance_cents` rises by the refunded `total_cents` and their `comp_tickets_remaining` is restored."

        Design: Difficulty/transitive_cascade/special_event_confirm_displacement_depth_four_cascade
        """
        world = _event_world_with_a_later_paid_screening()

        confirm_event(world["event"]["id"], displace_conflicts=True)

        member = read_member(world["member"]["id"])
        assert member["credit_balance_cents"] == 2766
        assert member["comp_tickets_remaining"] == 2

        host = read_showtime(world["first"]["id"])
        assert host["status"] == "SCHEDULED", "the hosting screening survives"
        assert host["sale_status"] == "DRAFT"
        assert read_event(world["event"]["id"])["status"] == "CONFIRMED"


def _withdrawal_world():
    """One on-sale screening carrying a paid member order and an unpaid walk-up hold."""
    world = setup_programming_baseline()
    world["showtime"] = place_showtime(world, "2026-08-14T12:00:00Z")
    open_showtime_sales(world["showtime"]["id"])
    world["member"] = setup_member_at_tier("SUPPORTER")
    paid = sell_seats(
        world["showtime"]["id"], 3,
        purchaser_email="ada@example.com", member_id=world["member"]["id"],
    )
    world["paid_order"] = pay_for_order(paid["id"])
    world["held_order"] = sell_seats(
        world["showtime"]["id"], 2, purchaser_email="walkup@example.com"
    )
    return world


class TestEngagementWithdrawalCascade:
    """Withdrawing the engagement unwinds licence, calendar, orders and ledgers."""

    def test_withdrawal_revokes_the_attached_licence(self):
        """The engagement dies and takes its cleared licence with it.

        PRD: "**Hop two:** because the engagement is gone, every rights clearance attached to it whose status is `SUBMITTED`, `CHANGES_REQUESTED` or `CLEARED` becomes `REVOKED` with its `revoked_reason` set to `BOOKING_WITHDRAWN`."

        Design: Difficulty/transitive_cascade/booking_withdraw_unwinds_showtimes_orders_and_allowance
        """
        world = _withdrawal_world()

        withdrawn = withdraw_engagement(
            world["booking"]["id"], "DISTRIBUTOR_PULLED"
        )
        assert withdrawn["status"] == "WITHDRAWN"

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["status"] == "REVOKED"
        assert clearance["revoked_reason"] == "BOOKING_WITHDRAWN"

    def test_withdrawal_cancels_the_screening_and_closes_its_box_office(self):
        """The scheduled screening standing on the revoked licence is cancelled.

        PRD: "**Hop three:** because those licences are revoked, every screening standing on them whose status is `SCHEDULED` becomes `CANCELLED` with `cancel_reason` set to `CLEARANCE_REVOKED` and its `sale_status` forced to `SALES_CLOSED`."

        Design: Difficulty/transitive_cascade/booking_withdraw_unwinds_showtimes_orders_and_allowance
        """
        world = _withdrawal_world()

        withdraw_engagement(world["booking"]["id"], "DISTRIBUTOR_PULLED")

        showtime = read_showtime(world["showtime"]["id"])
        assert_showtime(showtime)
        assert showtime["status"] == "CANCELLED"
        assert showtime["sale_status"] == "SALES_CLOSED"

    def test_withdrawal_unwinds_the_orders_the_ledger_and_the_allowance(self):
        """The paid order becomes credit, the hold is released, the licence is emptied.

        PRD: "**Hop four:** because those screenings are cancelled, their ticket orders unwind — orders in `RESERVED` become `VOID`, orders in `PAID` become `REFUNDED` with `refund_destination` set to `MEMBER_CREDIT` when the order carries a `member_id` and `CASH` when it does not, each affected member's `credit_balance_cents` and `comp_tickets_remaining` are restored accordingly, and each affected clearance's `screenings_used` and `screenings_remaining` are recomputed from the surviving screenings."

        Design: Difficulty/transitive_cascade/booking_withdraw_unwinds_showtimes_orders_and_allowance
        """
        world = _withdrawal_world()

        withdraw_engagement(world["booking"]["id"], "DISTRIBUTOR_PULLED")

        paid = read_order(world["paid_order"]["id"])
        assert paid["status"] == "REFUNDED"
        assert paid["refund_destination"] == "MEMBER_CREDIT"
        assert paid["total_cents"] == 4149

        held = read_order(world["held_order"]["id"])
        assert held["status"] == "VOID"
        assert held["refund_destination"] is None, "a walk-up hold earns no credit"

        member = read_member(world["member"]["id"])
        assert member["credit_balance_cents"] == 4149

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 0
        assert clearance["screenings_remaining"] == 6
        assert_screening_allowance_conserved(clearance)

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["seats_sold"] == 0
        assert showtime["seats_available"] == 8
        assert_seat_conservation(showtime, world["venue"])
