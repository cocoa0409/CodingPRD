"""One cancellation, one request cycle: every derived field is already settled."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    OFFICER_HEADERS,
    add_ancillary,
    assert_booking_ledger,
    assert_exposure,
    assert_instant,
    assert_list_meta,
    assert_obligated_ledger,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_segment_state,
    build_world,
    cancel_segment,
    list_obligations,
    read_ancillary,
    read_booking,
    read_exposure,
    read_segment,
)


def _two_legs_and_a_seat_charge(api):
    """90000 over two legs plus a 2000 seat: 92000 collected, nothing obligated."""
    world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])
    world.ancillary = add_ancillary(
        api, world.booking["id"], world.segments[0]["id"], "SEAT_SELECTION", 2000
    )
    return world


class TestCancellationCascadeIsVisibleImmediately:
    def test_the_declaration_response_already_carries_the_whole_first_link(self, api):
        """No follow-up read is needed: the leg, its sibling and the seat all moved.

        PRD §3.3: "**Link one:** the leg moves to `CANCELLED`, its `disruption_type` is set to
        `CANCELLATION`, its `disruption_declared_at_utc` takes the supplied `declared_at_utc`, and
        its `version` advances by 1; if the leg was in `DELAYED`, its `delay_minutes` resets to 0,
        its `revised_arrival_utc` to null and its `is_significant_delay` to false."

        PRD §3.3: "**Link two-a,** caused by link one: every sibling leg of the same booking with
        a `sequence_index` greater than the cancelled leg's and a `status` of `SCHEDULED` becomes
        `DISRUPTED_UNUSED`, processed in ascending `sequence_index` order."

        PRD §3.3: "**Link two-b,** also caused by link one: every ancillary purchase attached to
        the cancelled leg whose `delivery_status` is `PENDING_DELIVERY` becomes `NOT_PROVIDED` with
        `non_provision_reason` set to `SERVICE_CANCELLED`, processed in ascending `created_at`
        order."

        Design: Corner/consistency_model/whole_cancellation_cascade_is_visible_in_the_same_request_cycle
        """
        world = _two_legs_and_a_seat_charge(api)

        declared = cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")

        assert_segment_state(
            declared,
            status="CANCELLED",
            disruption_type="CANCELLATION",
            disruption_declared_at_utc="2026-08-10T10:00:00Z",
        )
        assert_segment_state(
            read_segment(api, world.segments[1]["id"]),
            status="DISRUPTED_UNUSED",
            disruption_type="NONE",
            disruption_declared_at_utc="2026-08-10T10:00:00Z",
        )
        seat = read_ancillary(api, world.ancillary["id"])
        assert seat["delivery_status"] == "NOT_PROVIDED"
        assert seat["non_provision_reason"] == "SERVICE_CANCELLED"

    def test_the_recomputed_ledger_is_final_on_the_very_first_read(self, api):
        """Two obligations, 92000 obligated, and a repeat read that adds nothing.

        PRD §2.11: "When one operation touches several rows, the writes happen in a fixed order,
        siblings are processed in a deterministic order (`sequence_index` ascending for flight
        segments, `created_at` ascending everywhere else), and the parent booking's derived fields
        are recomputed once, at the end, from the rows that exist at that moment — including rows
        written earlier in the same request."

        PRD §3.3: "**Link three-b,** caused by link two-b: one refund obligation on an
        `ANCILLARY` basis in proactive issuance mode at fee face value is minted for each ancillary
        that just became `NOT_PROVIDED`, in the same ascending `created_at` order, each clamped
        against the headroom left by every obligation created earlier in this same request; each
        such ancillary's `refund_obligation_created` becomes true."

        PRD §3.3: "**Link four,** caused by links three-a and three-b: the booking's
        `total_refund_obligated_cents`, `earliest_refund_deadline_utc`, `unused_segment_count` and
        `disruption_posture` (which reaches `REFUND_OBLIGATED`) are recomputed, and the booking's
        `version` advances by exactly 1 for the whole request."

        PRD §2.11: "A booking's `total_refund_obligated_cents` must always equal the sum of
        `amount_cents` over that booking's refund obligations whose settlement axis is anything
        other than voided, summed in `created_at` ascending order."

        Design: Corner/consistency_model/whole_cancellation_cascade_is_visible_in_the_same_request_cycle
        """
        world = _two_legs_and_a_seat_charge(api)

        cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")

        rows, meta = validate_paginated(
            api.list_refund_obligations(OFFICER_HEADERS, booking_id=world.booking["id"])
        )
        assert_list_meta(meta, total_count=2, has_more=False)
        by_basis = {row["basis"]: row for row in rows}
        assert set(by_basis) == {"FARE", "ANCILLARY"}
        assert_obligation_amounts(by_basis["FARE"], amount_cents=90000)
        assert_obligation_amounts(by_basis["ANCILLARY"], amount_cents=2000)
        for row in rows:
            assert row["issuance_mode"] == "PROACTIVE"
            assert_obligation_axes(
                row, election_status="PENDING_ELECTION", settlement_status="UNSETTLED"
            )

        first = read_booking(api, world.booking["id"])
        assert_booking_ledger(
            first,
            collected_total_cents=92000,
            total_refund_obligated_cents=92000,
            disruption_posture="REFUND_OBLIGATED",
            unused_segment_count=2,
            suppressed_obligation_count=0,
        )
        assert_instant(first["earliest_refund_deadline_utc"], "2026-08-17T10:00:00Z")
        assert_obligated_ledger(first, list_obligations(api, world.booking["id"]))
        assert read_ancillary(api, world.ancillary["id"])["refund_obligation_created"] is True

        second = read_booking(api, world.booking["id"])
        assert second["total_refund_obligated_cents"] == first["total_refund_obligated_cents"]
        assert second["disruption_posture"] == first["disruption_posture"]
        assert second["version"] == first["version"], "reads never converge late"

    def test_the_exposure_view_shows_the_headroom_already_exhausted(self, api):
        """The cascade consumed the whole collected total inside one request cycle.

        PRD §3.6: "A read-only exposure view evaluates **both** fare variants against the
        booking's current state without persisting anything, and reports, for the addressed
        `booking_id`: `proactive_full_itinerary_cents`, the value the proactive rule would produce
        right now; `request_based_proration_cents`, the value the request-based rule would produce
        right now; `variant_delta_cents`, the proactive figure minus the request-based figure;
        `obligated_total_cents`, mirroring the booking's `total_refund_obligated_cents`;
        `remaining_headroom_cents`, computed exactly as step two above; `collected_total_cents`;
        `segment_count`; `unused_segment_count`; and `travel_commenced`."

        PRD §3.6: "The money collected on the booking is its `total_fare_cents` plus the sum of
        `amount_cents` over all of its ancillary purchases plus the sum of `fee_cents` over all of
        its checked bags, counting every such row whatever its delivery outcome."

        PRD §3.6: "The money already consumed is the sum of `amount_cents` over the booking's
        obligations whose settlement axis is not voided **and** whose `basis` is not
        `DENIED_BOARDING`, added in ascending `created_at` order; statutory denied-boarding
        compensation is excluded because it compensates a service failure rather than refunding
        money collected."

        Design: Corner/consistency_model/whole_cancellation_cascade_is_visible_in_the_same_request_cycle
        """
        world = _two_legs_and_a_seat_charge(api)

        cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")

        assert_exposure(
            read_exposure(api, world.booking["id"]),
            obligated_total_cents=92000,
            remaining_headroom_cents=0,
            collected_total_cents=92000,
            segment_count=2,
            unused_segment_count=2,
            travel_commenced=False,
        )
