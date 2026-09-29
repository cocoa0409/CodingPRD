"""Cascades measured link by link: whole-itinerary cancellation and a late bag."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    OFFICER_HEADERS,
    OPS_HEADERS,
    add_ancillary,
    add_checked_bag,
    assert_booking_ledger,
    assert_exposure,
    assert_hours,
    assert_instant,
    assert_obligation_deadlines,
    assert_segment_state,
    build_world,
    cancel_segment,
    create_booking,
    create_passenger,
    create_policy_profile,
    factories as f,
    list_obligations,
    obligations_with_meta,
    read_ancillary,
    read_bag,
    read_booking,
    read_exposure,
    read_segment,
    set_clock,
    sole_obligation,
)

# ─── Whole-itinerary cancellation ─────────────────────


def _cancelled_middle_leg(api):
    """Three legs and two extras on the middle one; the middle leg is cancelled."""
    set_clock(api, "2026-08-10T18:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "cascade@example.com", "Cass Cade")
    booking = create_booking(
        api, passenger["id"], profile["id"], "CAS001", 100000, "CREDIT_CARD"
    )
    legs = [
        (1, "ZQ101", "LAX", "DEN", "2026-08-12T14:00:00Z", "2026-08-12T17:00:00Z", 20000),
        (2, "ZQ202", "DEN", "ORD", "2026-08-12T18:30:00Z", "2026-08-12T21:00:00Z", 40000),
        (3, "ZQ303", "ORD", "BOS", "2026-08-13T13:00:00Z", "2026-08-13T16:00:00Z", 40000),
    ]
    segments = []
    for index, number, origin, destination, departure, arrival, fare in legs:
        segments.append(
            validate_success(
                api.create_flight_segment(
                    booking["id"],
                    f.flight_segment_payload(
                        sequence_index=index,
                        flight_number=number,
                        origin_iata=origin,
                        destination_iata=destination,
                        scheduled_departure_utc=departure,
                        scheduled_arrival_utc=arrival,
                        segment_fare_cents=fare,
                    ),
                    OPS_HEADERS,
                ),
                201,
            )
        )
    seat = add_ancillary(api, booking["id"], segments[1]["id"], "SEAT_SELECTION", 4500)
    entertainment = add_ancillary(
        api, booking["id"], segments[1]["id"], "ENTERTAINMENT", 1900
    )
    cancel_segment(api, segments[1]["id"], "2026-08-10T18:00:00Z")
    return booking, segments, seat, entertainment


class TestSegmentCancellationCascade:
    def test_downstream_siblings_and_attached_extras_follow_the_cancelled_leg(self, api):
        """Only the later sibling is dragged along, and only the middle leg's extras.

        PRD §3.2: "**Link two-a,** caused by link one: every sibling leg of the same
        booking with a `sequence_index` greater than the cancelled leg's and a `status`
        of `SCHEDULED` becomes `DISRUPTED_UNUSED`, processed in ascending
        `sequence_index` order."

        PRD §3.2: "Each such sibling keeps its `disruption_type` at `NONE` but copies
        `disruption_declared_at_utc` from the cancelled leg, so that an obligation
        naming a downstream sibling still has a well-defined clock start."

        Design: Difficulty/transitive_cascade/segment_cancellation_depth_four_cascade
        """
        _, segments, seat, entertainment = _cancelled_middle_leg(api)

        assert_segment_state(
            read_segment(api, segments[1]["id"]),
            status="CANCELLED",
            disruption_type="CANCELLATION",
            disruption_declared_at_utc="2026-08-10T18:00:00Z",
        )
        assert_segment_state(
            read_segment(api, segments[2]["id"]),
            status="DISRUPTED_UNUSED",
            disruption_type="NONE",
            disruption_declared_at_utc="2026-08-10T18:00:00Z",
        )
        assert_segment_state(read_segment(api, segments[0]["id"]), status="SCHEDULED")

        for purchase_id in (seat["id"], entertainment["id"]):
            purchase = read_ancillary(api, purchase_id)
            assert purchase["delivery_status"] == "NOT_PROVIDED"
            assert purchase["non_provision_reason"] == "SERVICE_CANCELLED"

    def test_the_cascade_mints_one_fare_obligation_and_one_per_extra(self, api):
        """A single fare row for the whole itinerary, then a face-value row per extra.

        PRD §3.2: "**Link three-a,** caused by link one: one refund obligation on a
        `FARE` basis in proactive issuance mode, naming the cancelled leg, is minted per
        the proactive full-itinerary valuation and clamped to the booking's remaining
        headroom; if the clamp yields zero the obligation is skipped and the booking's
        `suppressed_obligation_count` increases by 1 instead."

        PRD §3.2: "**Link three-b,** caused by link two-b: one refund obligation on an
        `ANCILLARY` basis in proactive issuance mode at fee face value is minted for
        each ancillary that just became `NOT_PROVIDED`, in the same ascending
        `created_at` order, each clamped against the headroom left by every obligation
        created earlier in this same request; each such ancillary's
        `refund_obligation_created` becomes true."

        Design: Difficulty/transitive_cascade/segment_cancellation_depth_four_cascade
        """
        booking, segments, seat, entertainment = _cancelled_middle_leg(api)

        fare = sole_obligation(api, booking["id"], basis="FARE")
        assert fare["amount_cents"] == 100000
        assert fare["issuance_mode"] == "PROACTIVE"
        assert fare["variant_applied"] == "PROACTIVE_FULL_ITINERARY"
        assert fare["flight_segment_id"] == segments[1]["id"]

        rows, meta = obligations_with_meta(api, booking["id"], basis="ANCILLARY")
        assert meta["total_count"] == 2
        assert sorted(row["amount_cents"] for row in rows) == [1900, 4500]
        assert {row["variant_applied"] for row in rows} == {"FEE_FACE_VALUE"}
        for purchase_id in (seat["id"], entertainment["id"]):
            assert read_ancillary(api, purchase_id)["refund_obligation_created"] is True

    def test_the_booking_ledger_absorbs_every_link_in_one_version_bump(self, api):
        """All 106400 collected cents become obligated and the headroom drops to zero.

        PRD §3.2: "**Link four,** caused by links three-a and three-b: the booking's
        `total_refund_obligated_cents`, `earliest_refund_deadline_utc`,
        `unused_segment_count` and `disruption_posture` (which reaches
        `REFUND_OBLIGATED`) are recomputed, and the booking's `version` advances by
        exactly 1 for the whole request."

        Design: Difficulty/transitive_cascade/segment_cancellation_depth_four_cascade
        """
        booking, _, _, _ = _cancelled_middle_leg(api)

        stored = read_booking(api, booking["id"])
        assert_booking_ledger(
            stored,
            collected_total_cents=106400,
            total_refund_obligated_cents=106400,
            unused_segment_count=3,
            disruption_posture="REFUND_OBLIGATED",
            suppressed_obligation_count=0,
        )
        assert_instant(stored["earliest_refund_deadline_utc"], "2026-08-17T18:00:00Z")
        assert_exposure(read_exposure(api, booking["id"]), remaining_headroom_cents=0)


# ─── Late bag delivery ────────────────────────────────


def _late_bag(api):
    """A bag delivered exactly twelve hours after its contractual delivery moment."""
    set_clock(api, "2026-08-11T09:00:00Z")
    world = build_world(
        api,
        total_fare_cents=50000,
        segment_fares=[50000],
        record_locator="BAG001",
        email="bag@example.com",
    )
    bag = add_checked_bag(
        api,
        world.booking["id"],
        tag_number="ZQ00990010",
        fee_cents=3500,
        checked_at_utc="2026-08-10T12:30:00Z",
        scheduled_delivery_utc="2026-08-10T21:00:00Z",
    )
    validate_success(
        api.resolve_checked_bag(
            bag["id"], f.bag_delivered_payload("2026-08-11T09:00:00Z"), OFFICER_HEADERS
        )
    )
    return world, bag


class TestLateBagDeliveryCascade:
    def test_a_bag_exactly_twelve_hours_late_is_late_and_owes_its_fee(self, api):
        """The at-or-above comparison catches the bag that lands on the threshold.

        PRD §3.3: "The comparison is at-or-above, so a bag delivered exactly 12.00 hours
        late on a default domestic itinerary is late."

        PRD §3.3: "**Link one:** the bag moves `IN_TRANSIT → DELIVERED_LATE`,
        `delivered_at_utc` and `delivery_delay_hours` are stored, and the bag's
        `version` advances by 1."

        Design: Difficulty/transitive_cascade/late_bag_delivery_depth_three_cascade
        """
        world, bag = _late_bag(api)

        stored = read_bag(api, bag["id"], world.booking["id"])

        assert_hours(stored["delivery_delay_hours"], 12.00, "delivery_delay_hours")
        assert stored["status"] == "DELIVERED_LATE"
        assert stored["fee_refund_obligated"] is True
        assert_segment_state(read_segment(api, world.segments[0]["id"]), status="SCHEDULED")

    def test_the_fee_obligation_runs_its_deadline_from_the_delivery_instant(self, api):
        """3500 cents at face value, due seven days after the bag actually arrived.

        PRD §3.3: "**Link two,** caused by link one: one refund obligation on a
        `BAGGAGE_FEE` basis in proactive issuance mode at fee face value is minted, its
        gross entitlement being exactly the bag's `fee_cents`, clamped to the booking's
        remaining headroom, with the obligation's clock start taken from
        `delivered_at_utc`; the bag's `fee_refund_obligated` becomes true."

        PRD §3.3: "**Link three,** caused by link two: the booking's
        `total_refund_obligated_cents`, `earliest_refund_deadline_utc` and
        `disruption_posture` — which reaches `REFUND_OBLIGATED` — are recomputed and the
        booking's `version` advances by 1."

        Design: Difficulty/transitive_cascade/late_bag_delivery_depth_three_cascade
        """
        world, bag = _late_bag(api)

        rows = list_obligations(api, world.booking["id"], basis="BAGGAGE_FEE")
        assert len(rows) == 1
        obligation = rows[0]
        assert obligation["amount_cents"] == 3500
        assert obligation["variant_applied"] == "FEE_FACE_VALUE"
        assert obligation["issuance_mode"] == "PROACTIVE"
        assert obligation["checked_bag_id"] == bag["id"]
        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-11T09:00:00Z",
            deadline_utc="2026-08-18T09:00:00Z",
        )

        stored = read_booking(api, world.booking["id"])
        assert_booking_ledger(
            stored,
            collected_total_cents=53500,
            total_refund_obligated_cents=3500,
            disruption_posture="REFUND_OBLIGATED",
        )
        assert_instant(stored["earliest_refund_deadline_utc"], "2026-08-18T09:00:00Z")
