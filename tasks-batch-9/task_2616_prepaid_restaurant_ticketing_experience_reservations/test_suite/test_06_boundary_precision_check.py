"""
Five edges probed from both sides: the forfeiture ladder's 72-hour row, the
scarcity step's 8000-basis-point threshold, the dietary note's 1-based cover
index, the kitchen line's prep-minute capacity, and the instant the release
window opens.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import make_guest_headers, make_restaurant_headers

# Every scenario below seats on the same Saturday. Saturday is the strongest
# day-of-week factor at 12500 basis points and the demand tier is HIGH at
# 12000, so the combined factor is 15000 and a 12000-cent cover lists at 18000.
SEATING_START = "2026-09-12T22:00:00Z"
SEATING_END = "2026-09-13T02:00:00Z"
SETUP_CLOCK = "2026-09-01T00:00:00Z"

# "Subtract the logical clock from the service's seating_start_utc and divide by
# 3600 seconds": exactly 72.000 hours, then one minute later at 71.983 hours.
CANCEL_AT_72H = "2026-09-09T22:00:00Z"
CANCEL_AT_71H59M = "2026-09-09T22:01:00Z"

# seating_start_utc less release_lead_minutes of 180, and one minute earlier.
RELEASE_WINDOW_OPENS = "2026-09-12T19:00:00Z"
ONE_MINUTE_BEFORE_WINDOW = "2026-09-12T18:59:00Z"


def _ladder_world(api, guests=1):
    """A published Saturday HIGH service whose package runs the STANDARD ladder
    against the deposit, with one deposit-paid CONFIRMED party of 2 per guest.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name=f"Aurum Edge {F.unique_suffix()}",
        service_charge_bp=725,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        kitchen_prep_minutes_per_cover=12,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest_rows = FX.create_guests(api, guests)
    reservations = [
        FX.confirmed_reservation(api, ticket_class["id"], guest["id"], party_size=2)
        for guest in guest_rows
    ]
    return {
        "restaurant": restaurant,
        "service": service,
        "ticket_class": ticket_class,
        "guests": guest_rows,
        "reservations": reservations,
        "manager": make_restaurant_headers(restaurant["id"]),
    }


class TestForfeitureLadderSeventyTwoHourRow:
    """One minute of clock across the 72-hour row is the whole difference
    between a full refund and a half-deposit forfeiture."""

    def test_cancelling_at_exactly_seventy_two_hours_refunds_the_whole_deposit(
        self, api
    ):
        """The exact band edge takes the cheaper row, so nothing is retained.

        "The same reservation cancelled at exactly 72.0 hours on `STANDARD`
        takes the 0-basis-point band, a 0-cent fee, 0 retention and an
        11583-cent refund, leaving it `REFUNDED`."

        Design: Difficulty/boundary_precision_check/forfeiture_ladder_exact_72_hour_band_edge
        """
        world = _ladder_world(api, guests=1)
        guest = world["guests"][0]
        reservation = world["reservations"][0]
        headers = make_guest_headers(guest["id"])

        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=36000,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=11583,
        )

        FX.set_clock(api, CANCEL_AT_72H)
        FX.cancel(api, reservation["id"], guest["id"])

        settled = FX.read_reservation(api, reservation["id"], headers)
        assert settled["forfeited_cents"] == 0
        assert settled["refunded_cents"] == 11583
        A.assert_payment_status(settled, "REFUNDED")
        A.assert_fulfillment_status(settled, "CANCELLED")
        assert settled["cancel_settlement_basis"] == "DEPOSIT_BASIS"
        A.assert_settled_ledger_identity(settled)

        rows = FX.ledger_rows(api, reservation["id"], headers)
        cancel_rows = [row for row in rows if row["memo_code"] == "GUEST_CANCEL"]
        assert [row["kind"] for row in cancel_rows] == ["REFUND"]
        assert cancel_rows[0]["amount_cents"] == 11583
        assert not [row for row in rows if row["kind"] == "FORFEITURE"]
        for row in rows:
            A.assert_ledger_row_shape(row)
            A.assert_signed_amount(row)
        A.assert_signed_sum_matches(settled, rows)

    def test_cancelling_one_minute_past_the_edge_drops_to_the_five_thousand_band(
        self, api
    ):
        """A minute inside the edge lands on the 5000-basis-point row.

        "This value is compared as an exact decimal and is never truncated or
        rounded to whole hours: 71.9 hours is inside the 24-hour band of the
        `STANDARD` ladder, not on the 72-hour edge."

        "Under `DEPOSIT_BASIS` the raw forfeiture is 5792 cents, the fee 500
        cents, the retention 6292 cents and the refund 5291 cents, leaving the
        money dimension `PARTIALLY_REFUNDED`."

        Design: Difficulty/boundary_precision_check/forfeiture_ladder_exact_72_hour_band_edge
        """
        world = _ladder_world(api, guests=1)
        guest = world["guests"][0]
        reservation = world["reservations"][0]
        headers = make_guest_headers(guest["id"])

        FX.set_clock(api, CANCEL_AT_71H59M)
        FX.cancel(api, reservation["id"], guest["id"])

        settled = FX.read_reservation(api, reservation["id"], headers)
        assert settled["forfeited_cents"] == 6292
        assert settled["refunded_cents"] == 5291
        A.assert_payment_status(settled, "PARTIALLY_REFUNDED")
        A.assert_fulfillment_status(settled, "CANCELLED")
        assert settled["cancel_settlement_basis"] == "DEPOSIT_BASIS"
        A.assert_settled_ledger_identity(settled)

        # 5000 basis points of an 11583-cent deposit is 5792 cents after the
        # half-up rounding, and a raw forfeiture of 9999 cents or less carries a
        # 500-cent rebooking fee.
        expected = C.settle_cancellation(
            amount_paid_cents=11583,
            deposit_due_cents=11583,
            grand_total_cents=38610,
            schedule_code="STANDARD",
            basis_code="DEPOSIT_BASIS",
            hours_to_service=71.983,
        )
        assert expected["band_bp"] == 5000
        assert expected["raw_forfeiture_cents"] == 5792
        assert expected["rebook_fee_cents"] == 500
        assert settled["forfeited_cents"] == expected["forfeited_cents"]
        assert settled["refunded_cents"] == expected["refunded_cents"]

        rows = FX.ledger_rows(api, reservation["id"], headers)
        cancel_rows = [row for row in rows if row["memo_code"] == "GUEST_CANCEL"]
        by_kind = {row["kind"]: row for row in cancel_rows}
        assert sorted(by_kind) == ["FORFEITURE", "REFUND"]
        assert by_kind["FORFEITURE"]["amount_cents"] == 6292
        assert by_kind["REFUND"]["amount_cents"] == 5291
        A.assert_signed_sum_matches(settled, rows)


def _scarcity_world(api):
    """A published Saturday HIGH service carrying one 25-seat class with 19 of
    its seats already held, plus a spare guest to buy the twentieth.

    Nineteen of twenty-five floors to 7600 basis points and twenty floors to
    exactly 8000, so the two adjacent observable sell-through figures sit on
    either side of the high scarcity threshold.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name=f"Aurum Scarcity {F.unique_suffix()}",
        service_charge_bp=725,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        release_discount_bp=1500,
        kitchen_prep_minutes_per_cover=12,
        min_party_size=1,
        max_party_size=8,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=25,
        demand_tier="HIGH",
        kitchen_prep_capacity_minutes=900,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=25,
        min_party_size=1,
        max_party_size=8,
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    holders = FX.create_guests(api, 3)
    for guest, covers in zip(holders, (8, 8, 3)):
        FX.hold_seats(api, ticket_class["id"], guest["id"], party_size=covers)
    buyer = FX.create_guest(api)
    return {
        "restaurant": restaurant,
        "service": service,
        "ticket_class": ticket_class,
        "holders": holders,
        "buyer": buyer,
        "manager": make_restaurant_headers(restaurant["id"]),
    }


class TestScarcityStepEightyPercentThreshold:
    """7600 basis points and 8000 basis points are adjacent observable
    sell-through figures on a 25-seat class, and they price differently."""

    def test_nineteen_of_twenty_five_held_takes_the_eight_hundred_point_step(
        self, api
    ):
        """Just short of the threshold, the middle step applies.

        "Where it has not reached 8000 but has reached 5000, the step is 800
        basis points."

        Design: Difficulty/boundary_precision_check/scarcity_step_exact_8000_sell_through_edge
        """
        world = _scarcity_world(api)
        buyer_headers = make_guest_headers(world["buyer"]["id"])

        quoted = validate_success(
            api.price_quote(world["ticket_class"]["id"], buyer_headers)
        )
        A.assert_seat_pool(
            quoted, sold=0, held=19, released=0, available=6, status="OPEN"
        )
        assert quoted["sell_through_bp"] == 7600
        assert quoted["list_price_per_cover_cents"] == 19440
        assert quoted["release_price_per_cover_cents"] == 16524

        # 18000 cents of scarcity-free list price carried through the 800-point
        # step, and the release discount taken off that scarcity-adjusted figure.
        assert C.scarcity_step_bp(7600) == 800
        assert C.list_price_per_cover(12000, "SAT", "HIGH", 7600) == 19440
        assert C.release_price_per_cover(19440, 1500) == 16524

    def test_the_twentieth_seat_reaches_exactly_eight_thousand_and_steps_up(
        self, api
    ):
        """At exactly 8000 basis points the high step of 1500 applies instead.

        "Where that figure has reached 8000 basis points — eighty percent of the
        allocation committed, holds included — the scarcity step is 1500 basis
        points."

        "First, the only inputs are the class's own `seats_sold` and
        `seats_held`, read **before** the current write credits its own seats — a
        reservation never prices itself into a higher scarcity step."

        Design: Difficulty/boundary_precision_check/scarcity_step_exact_8000_sell_through_edge
        """
        world = _scarcity_world(api)
        buyer = world["buyer"]
        buyer_headers = make_guest_headers(buyer["id"])

        twentieth = FX.hold_seats(
            api, world["ticket_class"]["id"], buyer["id"], party_size=1
        )
        # The twentieth seat is priced from the pool as it stood at 19 held.
        assert twentieth["price_locked_per_cover_cents"] == 19440
        assert twentieth["ticket_subtotal_cents"] == 19440

        quoted = validate_success(
            api.price_quote(world["ticket_class"]["id"], buyer_headers)
        )
        A.assert_seat_pool(
            quoted, sold=0, held=20, released=0, available=5, status="OPEN"
        )
        assert quoted["sell_through_bp"] == 8000
        assert quoted["list_price_per_cover_cents"] == 20700
        assert quoted["release_price_per_cover_cents"] == 17595

        assert C.scarcity_step_bp(8000) == 1500
        assert C.list_price_per_cover(12000, "SAT", "HIGH", 8000) == 20700
        assert C.release_price_per_cover(20700, 1500) == 17595


class TestDietaryNoteGuestIndexRange:
    """The cover index is an inclusive 1-to-party_size range, so index 2 is the
    last valid cover of a party of two and index 3 is the first invalid one."""

    def test_the_last_cover_of_the_party_is_a_valid_guest_index(self, api):
        """A party of two accepts a note against cover 2.

        "The index must be at least 1 and at most the reservation's
        `party_size`, or the capture is refused with
        `ERR_GUEST_INDEX_OUT_OF_RANGE`."

        "Each note carries a derived `prep_minutes` read straight off its
        severity: an `INFO` note costs the kitchen nothing, an `ALLERGY` note
        costs 6 minutes, and an `ANAPHYLAXIS` note costs 15."

        Design: Difficulty/boundary_precision_check/dietary_note_guest_index_upper_bound
        """
        world = _ladder_world(api, guests=1)
        guest = world["guests"][0]
        reservation = world["reservations"][0]
        headers = make_guest_headers(guest["id"])

        note = validate_success(
            api.create_dietary_note(
                reservation["id"],
                F.dietary_note_payload(
                    guest_index=2,
                    restriction_code="GLUTEN",
                    severity="ALLERGY",
                    note_text="celiac",
                ),
                headers,
            ),
            201,
        )
        A.assert_common_fields(note)
        assert note["guest_index"] == 2
        assert note["prep_minutes"] == 6
        assert note["ack_status"] == "PENDING"
        assert note["amend_count"] == 0
        assert note["reject_reason_code"] is None
        assert note["acked_by_user_id"] is None

        listed = validate_success(
            api.list_reservation_dietary_notes(reservation["id"], headers)
        )
        assert len(listed) == 1
        assert listed[0]["id"] == note["id"]

        # A baseline of 2 covers at 12 minutes each plus the note's 6 minutes.
        updated = FX.read_reservation(api, reservation["id"], headers)
        assert updated["prep_minutes_total"] == 30
        assert C.prep_minutes_total(2, 12, severities=("ALLERGY",)) == 30

    def test_one_cover_past_the_party_is_out_of_range(self, api):
        """Cover 3 does not exist in a party of two and is refused.

        "`guest_index` is at least 1 and at most the reservation's `party_size`,
        on dietary-note capture — otherwise `ERR_GUEST_INDEX_OUT_OF_RANGE`."

        Design: Difficulty/boundary_precision_check/dietary_note_guest_index_upper_bound
        """
        world = _ladder_world(api, guests=1)
        guest = world["guests"][0]
        reservation = world["reservations"][0]
        headers = make_guest_headers(guest["id"])

        response = api.create_dietary_note(
            reservation["id"],
            F.dietary_note_payload(
                guest_index=3,
                restriction_code="GLUTEN",
                severity="ALLERGY",
                note_text="third cover",
            ),
            headers,
        )
        validate_error(response, E.ERR_GUEST_INDEX_OUT_OF_RANGE, 422)

        # The refused capture wrote nothing at all.
        listed = validate_success(
            api.list_reservation_dietary_notes(reservation["id"], headers)
        )
        assert listed == []
        unchanged = FX.read_reservation(api, reservation["id"], headers)
        assert unchanged["prep_minutes_total"] == 24

    def test_covers_are_counted_from_one_so_index_zero_is_refused(self, api):
        """Cover 1 is the first cover, and there is no cover 0.

        "A `Guest` records a note against a reservation by naming the
        `guest_index` — which cover in the party the note applies to, counted
        from 1 — together with a `restriction_code`, a clinical `severity`, and
        optional free-text `note_text` for the kitchen that defaults to the
        empty string and may run to 500 characters."

        Design: Difficulty/boundary_precision_check/dietary_note_guest_index_upper_bound
        """
        world = _ladder_world(api, guests=1)
        guest = world["guests"][0]
        reservation = world["reservations"][0]
        headers = make_guest_headers(guest["id"])

        first = validate_success(
            api.create_dietary_note(
                reservation["id"],
                F.dietary_note_payload(
                    guest_index=1,
                    restriction_code="GLUTEN",
                    severity="ALLERGY",
                    note_text="first cover",
                ),
                headers,
            ),
            201,
        )
        assert first["guest_index"] == 1

        zeroth = api.create_dietary_note(
            reservation["id"],
            F.dietary_note_payload(
                guest_index=0,
                restriction_code="GLUTEN",
                severity="ALLERGY",
                note_text="zeroth cover",
            ),
            headers,
        )
        validate_error_is_one_of(
            zeroth, [E.ERR_GUEST_INDEX_OUT_OF_RANGE, E.ERR_VALIDATION]
        )
        assert zeroth.status_code in (400, 422)

        listed = validate_success(
            api.list_reservation_dietary_notes(reservation["id"], headers)
        )
        assert len(listed) == 1


def _prep_line_world(api):
    """A published Saturday HIGH service whose kitchen line is rationed at 48
    prep minutes, with three tables and three CONFIRMED parties of 2.

    Each party carries a prep_minutes_total of 24 — two covers at 12 minutes
    each, no dietary notes and no add-on lines — so two parties fill the line
    exactly and a third overshoots it.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name=f"Aurum Line {F.unique_suffix()}",
        service_charge_bp=725,
        prep_lead_minutes=45,
        refund_scrutiny_threshold_cents=300000,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        kitchen_prep_minutes_per_cover=12,
    )
    tables = [
        FX.create_table(
            api,
            restaurant["id"],
            table_code=f"L{index}-{F.unique_suffix()}",
            seats_min=2,
            seats_max=4,
            turn_buffer_minutes=15,
        )
        for index in (1, 2, 3)
    ]
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
        kitchen_prep_capacity_minutes=48,
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest_rows = FX.create_guests(api, 3)
    reservations = [
        FX.confirmed_reservation(api, ticket_class["id"], guest["id"], party_size=2)
        for guest in guest_rows
    ]
    return {
        "restaurant": restaurant,
        "service": service,
        "tables": tables,
        "guests": guest_rows,
        "reservations": reservations,
        "manager": make_restaurant_headers(restaurant["id"]),
    }


class TestKitchenPrepLoadAgainstCapacity:
    """The prep window is closed at both ends, so windows that merely touch are
    aggregated — and the capacity comparison is strictly greater than."""

    def test_two_touching_windows_summing_to_exactly_capacity_are_accepted(
        self, api
    ):
        """A load of exactly 48 against a capacity of 48 assigns cleanly.

        "If the resulting aggregate is **strictly greater** than the service's
        `kitchen_prep_capacity_minutes`, the assignment is refused with
        `ERR_KITCHEN_PREP_OVERSUBSCRIBED`; a load exactly equal to capacity is
        accepted."

        "The candidate's prep window runs from the proposed `seat_from_utc` less
        the restaurant's `prep_lead_minutes` up to and including that
        `seat_from_utc`."

        Design: Difficulty/boundary_precision_check/kitchen_prep_load_exactly_equals_capacity
        """
        world = _prep_line_world(api)
        tables = world["tables"]
        reservations = world["reservations"]
        for reservation in reservations:
            assert reservation["prep_minutes_total"] == 24
        assert C.prep_minutes_total(2, 12) == 24

        # The first window runs [21:15, 22:00] and carries 24 minutes alone.
        first = validate_success(
            api.assign_table(
                reservations[0]["id"],
                F.assign_table_payload(tables[0]["id"], "2026-09-12T22:00:00Z"),
                world["manager"],
            )
        )
        assert first["assigned_table_id"] == tables[0]["id"]
        assert first["prep_minutes_total"] == 24

        # The second window runs [22:00, 22:45] and touches the first at exactly
        # 22:00, so the aggregate over the pair is 48 against a capacity of 48.
        second = validate_success(
            api.assign_table(
                reservations[1]["id"],
                F.assign_table_payload(tables[1]["id"], "2026-09-12T22:45:00Z"),
                world["manager"],
            )
        )
        assert second["assigned_table_id"] == tables[1]["id"]
        A.assert_instant_equals(second["seat_from_utc"], "2026-09-12T22:45:00Z", "seat_from_utc")
        assert second["prep_minutes_total"] == 24
        A.assert_fulfillment_status(second, "CONFIRMED")

    def test_a_third_touching_window_past_capacity_is_refused(self, api):
        """The window that lifts the same aggregate to 72 is refused.

        "The aggregate kitchen prep load across touching prep windows stays
        inside the service's capacity, on table assignment — otherwise
        `ERR_KITCHEN_PREP_OVERSUBSCRIBED`."

        Design: Difficulty/boundary_precision_check/kitchen_prep_load_exactly_equals_capacity
        """
        world = _prep_line_world(api)
        tables = world["tables"]
        reservations = world["reservations"]
        guest_headers = make_guest_headers(world["guests"][2]["id"])

        FX.assign_table(
            api,
            world["restaurant"]["id"],
            reservations[0]["id"],
            tables[0]["id"],
            "2026-09-12T22:00:00Z",
        )
        FX.assign_table(
            api,
            world["restaurant"]["id"],
            reservations[1]["id"],
            tables[1]["id"],
            "2026-09-12T22:45:00Z",
        )

        # A window of [21:45, 22:30] touches both accepted windows, so the
        # aggregate is three parties at 24 minutes each.
        response = api.assign_table(
            reservations[2]["id"],
            F.assign_table_payload(tables[2]["id"], "2026-09-12T22:30:00Z"),
            world["manager"],
        )
        validate_error(response, E.ERR_KITCHEN_PREP_OVERSUBSCRIBED, 422)

        refused = FX.read_reservation(api, reservations[2]["id"], guest_headers)
        assert refused["assigned_table_id"] is None
        assert refused["seat_from_utc"] is None
        assert refused["prep_minutes_total"] == 24
        A.assert_fulfillment_status(refused, "CONFIRMED")


def _release_window_world(api):
    """A published Saturday HIGH service whose release window opens exactly 180
    minutes before seating, carrying one wholly unsold 2-seat class.

    The whole allocation is releasable: unsold_release_bp is 10000, so the
    release pass takes both seats. No waitlist entry exists, so the promotion
    pass has nothing to do and the released pool survives the run intact.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        name=f"Aurum Window {F.unique_suffix()}",
        service_charge_bp=725,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        release_discount_bp=1500,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START,
        seating_end_utc=SEATING_END,
        turn_time_minutes=150,
        seats_capacity=2,
        demand_tier="HIGH",
        unsold_release_bp=10000,
        release_lead_minutes=180,
    )
    ticket_class = FX.create_ticket_class(
        api,
        restaurant["id"],
        service["id"],
        package["id"],
        seats_allocated=2,
        min_party_size=1,
        max_party_size=2,
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    return {
        "restaurant": restaurant,
        "service": service,
        "ticket_class": ticket_class,
        "manager": make_restaurant_headers(restaurant["id"]),
    }


class TestReleaseWindowLeadInstant:
    """The window opens at seating less the lead, and that instant counts."""

    def test_one_minute_before_the_lead_instant_the_run_is_refused(self, api):
        """Firing at 18:59 against a 19:00 window changes nothing.

        "It is legal only while the service is `PUBLISHED` and only once the
        logical clock has reached the service's `seating_start_utc` less its
        `release_lead_minutes`; firing earlier is refused with
        `ERR_RELEASE_WINDOW_NOT_OPEN`."

        Design: Difficulty/boundary_precision_check/release_window_opens_at_exact_lead_instant
        """
        world = _release_window_world(api)
        FX.set_clock(api, ONE_MINUTE_BEFORE_WINDOW)

        response = api.release_run(world["service"]["id"], world["manager"])
        validate_error(response, E.ERR_RELEASE_WINDOW_NOT_OPEN, 422)

        service = FX.read_service(api, world["service"]["id"], world["manager"])
        assert service["status"] == "PUBLISHED"
        assert service["release_run_count"] == 0
        assert service["seats_released_total"] == 0
        assert service["last_release_released_count"] == 0
        assert service["last_release_promoted_count"] == 0

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class"]["id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=0, available=2, status="OPEN"
        )

    def test_at_the_lead_instant_the_run_releases_the_whole_unsold_pool(self, api):
        """One minute later, at exactly 19:00, both seats move to the released pool.

        "For each, it computes the number of seats to release as the floor of
        that class's `seats_available` multiplied by the service's
        `unsold_release_bp`, divided by 10000 — a partial seat is never released
        — debits that count from `seats_available`, credits it to
        `seats_released`, adds it to the run's release total, and re-evaluates
        the class against the precedence ladder."

        Design: Difficulty/boundary_precision_check/release_window_opens_at_exact_lead_instant
        """
        world = _release_window_world(api)
        FX.set_clock(api, RELEASE_WINDOW_OPENS)

        run = FX.run_release(api, world["restaurant"]["id"], world["service"]["id"])
        assert run["release_run_count"] == 1
        assert run["seats_released_total"] == 2
        assert run["last_release_released_count"] == 2
        # No entry is waiting, so the promotion pass promotes nobody and the
        # released seats stay released.
        assert run["last_release_promoted_count"] == 0
        assert C.release_seat_count(2, 10000) == 2

        ticket_class = FX.read_ticket_class(
            api, world["ticket_class"]["id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=0, released=2, available=0, status="RELEASED"
        )
        # Saturday against the HIGH tier prices a cover at 18000, and the
        # package's 1500-point release discount takes it to 15300.
        assert ticket_class["list_price_per_cover_cents"] == 18000
        assert ticket_class["release_price_per_cover_cents"] == 15300
