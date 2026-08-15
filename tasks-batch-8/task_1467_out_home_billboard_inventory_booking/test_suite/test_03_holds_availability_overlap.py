"""Holds, the dual availability calendar, overlap and capacity disciplines."""
from datetime import datetime

from test_helpers import (
    CO,
    IM,
    SP,
    ApiErrorId,
    api_client,
    create_advertiser,
    create_campaign,
    create_face_with_permit,
    create_flight_payload,
    create_published_rate_card,
    create_rate_card_payload,
    create_work_order,
    face_version,
    get_success_data,
    hold_flight,
    normalize_calendar,
    set_clock,
    setup_held_flight,
    transition_work_order,
    validate_error,
    validate_success,
)


def _availability(face_id, from_date="2026-08-01", to_date="2026-09-30"):
    resp = api_client.get_face_availability(
        face_id, SP, params={"from_date": from_date, "to_date": to_date})
    return validate_success(resp, 200)


class TestCommittedVsForwardCalendar:

    def test_committed_calendar_excludes_unexpired_held_windows(self):
        """PRD section 3.5: "Planners and inventory managers read the face's
        book through the availability inquiry, which takes `from_date` and
        `to_date` and answers with two calendars clipped to that window:
        `committed_calendar`, the merged union of occupied intervals over
        `BOOKED`, `ART_CLEARED`, `LIVE`, `MISSED`, and `HOLDOVER` flights, and
        `forward_calendar`, the same union with unexpired `HELD` holds added."

        Design: Difficulty/dual_variant_calc/availability_committed_vs_forward_calendar
        """
        bundle = setup_held_flight(
            face_kwargs={"face_code": "F-NYC-002", "illuminated": False,
                         "daily_traffic_count": 50_000,
                         "permit_number": "P-002"},
        )
        avail = _availability(bundle["face"]["id"])
        assert normalize_calendar(avail["committed_calendar"]) == set(), (
            f"committed calendar excludes HELD holds: expected no intervals, "
            f"got {avail['committed_calendar']}"
        )

    def test_forward_calendar_includes_unexpired_held_windows(self):
        """PRD section 3.5: "The two calendars differ precisely on the windows
        covered only by unexpired holds."

        Design: Difficulty/dual_variant_calc/availability_committed_vs_forward_calendar
        """
        bundle = setup_held_flight(
            face_kwargs={"face_code": "F-NYC-002", "illuminated": False,
                         "daily_traffic_count": 50_000,
                         "permit_number": "P-002"},
        )
        avail = _availability(bundle["face"]["id"])
        forward = normalize_calendar(avail["forward_calendar"])
        assert forward == {("2026-08-10", "2026-09-06")}, (
            f"forward calendar includes the unexpired HELD window: "
            f"got {avail['forward_calendar']}"
        )
        committed = normalize_calendar(avail["committed_calendar"])
        assert forward - committed == {("2026-08-10", "2026-09-06")}, (
            "the calendars must differ exactly on the HELD-only window"
        )


class TestStaticChangeoverGap:

    def test_touching_or_adjacent_windows_rejected(self):
        """PRD section 3.5: "On a `STATIC` face, the new window must leave one
        full changeover day against every blocking interval — blocking
        intervals are the inclusive date ranges of flights in `BOOKED`,
        `ART_CLEARED`, `LIVE`, `MISSED`, or `HOLDOVER`, plus unexpired `HELD`
        holds — meaning the new flight either starts at least two days after
        an occupied interval's last day or ends at least two days before an
        occupied interval's first day. A `DIGITAL` face allows next-day
        adjacency: starting the day after an existing booking ends is fine.
        Any breach is `ERR_FACE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/static_face_changeover_gap_exclusion
        """
        bundle = setup_held_flight(campaign_end="2026-10-31")
        face_id, card_id = bundle["face"]["id"], bundle["rate_card"]["id"]
        camp_id = bundle["campaign"]["id"]

        touch = api_client.create_flight(
            create_flight_payload(camp_id, face_id, card_id,
                                  expected_face_version=face_version(face_id),
                                  start_date="2026-09-06", end_date="2026-10-04"),
            SP,
        )
        validate_error(touch, ApiErrorId.ERR_FACE_OVERLAP)

        adjacent = api_client.create_flight(
            create_flight_payload(camp_id, face_id, card_id,
                                  expected_face_version=face_version(face_id),
                                  start_date="2026-09-07", end_date="2026-10-04"),
            SP,
        )
        validate_error(adjacent, ApiErrorId.ERR_FACE_OVERLAP)

    def test_one_full_changeover_day_accepted(self):
        """PRD section 3.5: "On a `STATIC` face, the new window must leave one
        full changeover day against every blocking interval — blocking
        intervals are the inclusive date ranges of flights in `BOOKED`,
        `ART_CLEARED`, `LIVE`, `MISSED`, or `HOLDOVER`, plus unexpired `HELD`
        holds — meaning the new flight either starts at least two days after
        an occupied interval's last day or ends at least two days before an
        occupied interval's first day."

        Design: Difficulty/resource_temporal_overlap/static_face_changeover_gap_exclusion
        """
        bundle = setup_held_flight(campaign_end="2026-10-31")
        face_id, card_id = bundle["face"]["id"], bundle["rate_card"]["id"]
        camp_id = bundle["campaign"]["id"]

        resp = api_client.create_flight(
            create_flight_payload(camp_id, face_id, card_id,
                                  expected_face_version=face_version(face_id),
                                  start_date="2026-09-08", end_date="2026-10-05"),
            SP,
        )
        flight = validate_success(resp, 201)
        assert flight["status"] == "HELD", (
            f"start 2026-09-08 leaves the full changeover day 2026-09-07 "
            f"free after the 2026-09-06 end: expected HELD, "
            f"got {flight['status']}"
        )


class TestLoopSlotCapacity:

    def _digital_setup(self):
        card = create_published_rate_card(display_type="DIGITAL",
                                          base_weekly_cents=400_000)
        face, _permit = create_face_with_permit(
            face_code="F-DIGI-1", display_type="DIGITAL", illuminated=True,
            daily_traffic_count=300_000, loop_slots_total=8,
            permit_number="P-D1",
        )
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], start_date="2026-08-01",
                                   end_date="2026-10-31")
        return card, face, campaign

    def test_loop_filled_to_exact_capacity_allowed(self):
        """PRD section 3.5: "On a `DIGITAL` face, capacity is also enforced:
        summing `loop_slots` over the blocking flights whose windows intersect
        the new window and adding the new `loop_slots` must not exceed
        `loop_slots_total` — a sum exactly equal to the total is allowed, and
        only an excess is rejected with `ERR_LOOP_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/loop_slot_equality_boundary_on_create
        """
        card, face, campaign = self._digital_setup()
        d1 = hold_flight(campaign["id"], face["id"], card["id"],
                         start_date="2026-08-10", end_date="2026-09-06",
                         loop_slots=4)
        assert d1["pinned_weekly_cents"] == 287_500, (
            f"round_half_up(400000 x 1.25 x 1.15 x 4/8) per the pinned "
            f"pricing formula: expected 287500, got {d1['pinned_weekly_cents']}"
        )
        d2 = hold_flight(campaign["id"], face["id"], card["id"],
                         start_date="2026-08-17", end_date="2026-09-13",
                         loop_slots=4)
        assert d2["status"] == "HELD", (
            f"4 + 4 == 8 == loop_slots_total: equality is allowed, "
            f"got status {d2['status']}"
        )

    def test_one_slot_over_capacity_rejected(self):
        """PRD section 3.5: "On a `DIGITAL` face, capacity is also enforced:
        summing `loop_slots` over the blocking flights whose windows intersect
        the new window and adding the new `loop_slots` must not exceed
        `loop_slots_total` — a sum exactly equal to the total is allowed, and
        only an excess is rejected with `ERR_LOOP_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/loop_slot_equality_boundary_on_create
        """
        card, face, campaign = self._digital_setup()
        hold_flight(campaign["id"], face["id"], card["id"],
                    start_date="2026-08-10", end_date="2026-09-06", loop_slots=4)
        hold_flight(campaign["id"], face["id"], card["id"],
                    start_date="2026-08-17", end_date="2026-09-13", loop_slots=4)

        resp = api_client.create_flight(
            create_flight_payload(campaign["id"], face["id"], card["id"],
                                  expected_face_version=face_version(face["id"]),
                                  start_date="2026-08-24", end_date="2026-09-20",
                                  loop_slots=1),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_LOOP_CAPACITY_EXCEEDED)


class TestHoldReleaseInvariant:

    def test_hold_creation_occupies_forward_calendar_only(self):
        """PRD section 3.5: "A new flight is born `HELD`, with `held_until`
        set exactly 72 hours after `created_at`. The hold immediately reserves
        occupancy on the face's forward calendar and increments the face's
        `version` by 1, since the occupancy basis has changed."

        Design: Difficulty/compensating_invariant/hold_release_restores_forward_calendar
        """
        card = create_published_rate_card()
        face, _permit = create_face_with_permit(
            face_code="F-NYC-002", illuminated=False, daily_traffic_count=50_000,
            permit_number="P-002",
        )
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])

        before = _availability(face["id"])
        assert normalize_calendar(before["forward_calendar"]) == set()
        assert normalize_calendar(before["committed_calendar"]) == set()

        hold_flight(campaign["id"], face["id"], card["id"])
        mid = _availability(face["id"])
        assert normalize_calendar(mid["forward_calendar"]) == {
            ("2026-08-10", "2026-09-06")}, (
            f"the HELD hold occupies the forward calendar only: "
            f"got {mid['forward_calendar']}"
        )
        assert normalize_calendar(mid["committed_calendar"]) == set()

    def test_release_restores_occupancy_exactly(self):
        """PRD section 3.5: "If the clock reaches `held_until` before
        confirmation, the sweep moves the flight `HELD` → `EXPIRED` and frees
        the reserved occupancy exactly; a planner may likewise abandon a hold
        voluntarily (the `HELD` → `RELEASED` transition), freeing the same
        occupancy."

        Design: Difficulty/compensating_invariant/hold_release_restores_forward_calendar
        """
        card = create_published_rate_card()
        face, _permit = create_face_with_permit(
            face_code="F-NYC-002", illuminated=False, daily_traffic_count=50_000,
            permit_number="P-002",
        )
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])
        baseline = _availability(face["id"])

        flight = hold_flight(campaign["id"], face["id"], card["id"])
        released = validate_success(
            api_client.update_flight(flight["id"], {"status": "RELEASED"}, SP), 200)
        assert released["status"] == "RELEASED"

        after = _availability(face["id"])
        assert normalize_calendar(after["forward_calendar"]) == \
            normalize_calendar(baseline["forward_calendar"])
        assert normalize_calendar(after["committed_calendar"]) == \
            normalize_calendar(baseline["committed_calendar"])


class TestFacePostureGatesCreation:

    def test_create_rejected_while_face_under_maintenance(self):
        """PRD section 2.7: "Only an `OPEN` face accepts new holds or
        confirmations."
        PRD section 3.5: "...the face must stand at `booking_posture` `OPEN`
        with a current permit in force (otherwise `ERR_FACE_NOT_BOOKABLE`)..."
        PRD section 3.3: "Starting work (the `SCHEDULED` → `IN_PROGRESS`
        transition) stamps `started_at` with the clock and moves the face from
        `AVAILABLE` to `UNDER_MAINTENANCE`, recomputing its posture to
        `RESTRICTED`."

        Design: Difficulty/cross_entity_state_dependency/flight_creation_gated_by_face_posture
        """
        card = create_published_rate_card()
        face, _permit = create_face_with_permit(face_code="F-NYC-001")
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])
        order = create_work_order(face["id"])
        transition_work_order(order["id"], "SCHEDULED",
                              scheduled_start="2026-08-05T06:00:00Z",
                              scheduled_end="2026-08-05T18:00:00Z")
        transition_work_order(order["id"], "IN_PROGRESS")

        mid = validate_success(api_client.get_face(face["id"], SP), 200)
        assert mid["booking_posture"] == "RESTRICTED"

        resp = api_client.create_flight(
            create_flight_payload(campaign["id"], face["id"], card["id"],
                                  expected_face_version=mid["version"]),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_FACE_NOT_BOOKABLE)

    def test_create_succeeds_after_work_completes(self):
        """PRD section 3.3: "Completing work stamps `completed_at`, computes
        `downtime_hours` as the elapsed hours between `started_at` and
        `completed_at` rounded to 2 decimal places, and returns the face from
        `UNDER_MAINTENANCE` to `AVAILABLE` — but only when zero sibling work
        orders on that face remain `IN_PROGRESS`."
        PRD section 2.7: "Only an `OPEN` face accepts new holds or
        confirmations."

        Design: Difficulty/cross_entity_state_dependency/flight_creation_gated_by_face_posture
        """
        card = create_published_rate_card()
        face, _permit = create_face_with_permit(face_code="F-NYC-001")
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])
        order = create_work_order(face["id"])
        transition_work_order(order["id"], "SCHEDULED",
                              scheduled_start="2026-08-05T06:00:00Z",
                              scheduled_end="2026-08-05T18:00:00Z")
        transition_work_order(order["id"], "IN_PROGRESS")
        transition_work_order(order["id"], "COMPLETED")

        after = validate_success(api_client.get_face(face["id"], SP), 200)
        assert after["status"] == "AVAILABLE"
        assert after["booking_posture"] == "OPEN"

        flight = validate_success(api_client.create_flight(
            create_flight_payload(campaign["id"], face["id"], card["id"],
                                  expected_face_version=after["version"]),
            SP,
        ), 201)
        assert flight["status"] == "HELD"


class TestHoldExpiryBoundary:

    def test_hold_expiry_clock_sweep_boundary(self):
        """PRD section 3.5: "A new flight is born `HELD`, with `held_until`
        set exactly 72 hours after `created_at`."
        PRD section 3.5: "If the clock reaches `held_until` before
        confirmation, the sweep moves the flight `HELD` → `EXPIRED` and frees
        the reserved occupancy exactly; a planner may likewise abandon a hold
        voluntarily (the `HELD` → `RELEASED` transition), freeing the same
        occupancy."
        PRD section 2.5: "2. **Hold expiry** — held flights whose deadline has
        passed move from `HELD` to `EXPIRED`, freeing their reserved
        occupancy."

        Design: Corner/state_machines/hold_expiry_clock_sweep_boundary
        """
        bundle = setup_held_flight()
        flight = bundle["flight"]
        created = datetime.fromisoformat(
            flight["created_at"].replace("Z", "+00:00"))
        held_until = datetime.fromisoformat(
            flight["held_until"].replace("Z", "+00:00"))
        assert (held_until - created).total_seconds() == 72 * 3600, (
            f"held_until must be exactly 72 hours after created_at: "
            f"{flight['created_at']} -> {flight['held_until']}"
        )

        set_clock("2026-08-03T23:00:00Z")
        before = validate_success(api_client.get_flight(flight["id"], SP), 200)
        assert before["status"] == "HELD", (
            f"one hour before held_until the hold survives: "
            f"got {before['status']}"
        )

        set_clock("2026-08-04T00:00:00Z")
        after = validate_success(api_client.get_flight(flight["id"], SP), 200)
        assert after["status"] == "EXPIRED", (
            f"at exactly held_until (created 2026-08-01T00:00:00Z + 72h) the "
            f"hold is swept: got {after['status']}"
        )


class TestFlightCreationReferentialGates:

    def test_flight_outside_campaign_window_rejected(self):
        """PRD section 3.4: "Every flight of the campaign must lie inside that
        window — a hold whose dates fall outside is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/flight_outside_campaign_window_rejected
        """
        bundle = setup_held_flight()
        resp = api_client.create_flight(
            create_flight_payload(
                bundle["campaign"]["id"], bundle["face"]["id"],
                bundle["rate_card"]["id"],
                expected_face_version=face_version(bundle["face"]["id"]),
                start_date="2026-10-01", end_date="2026-10-28"),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_flight_create_with_unpublished_card_rejected(self):
        """PRD section 3.5: "The campaign must be in `DRAFT` or `SUBMITTED`
        (otherwise `ERR_CAMPAIGN_NOT_APPROVED`), the rate card must be
        `PUBLISHED` (otherwise `ERR_RATE_CARD_NOT_PUBLISHED`), the face must
        stand at `booking_posture` `OPEN` with a current permit in force
        (otherwise `ERR_FACE_NOT_BOOKABLE`), and the flight's dates must lie
        inside the campaign window."

        Design: Corner/errors/flight_create_with_unpublished_card_rejected
        """
        card = get_success_data(api_client.create_rate_card(
            create_rate_card_payload(), IM))
        assert card["status"] == "DRAFT"
        face, _permit = create_face_with_permit(face_code="F-NYC-001")
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])

        resp = api_client.create_flight(
            create_flight_payload(campaign["id"], face["id"], card["id"],
                                  expected_face_version=face_version(face["id"])),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_CARD_NOT_PUBLISHED)
