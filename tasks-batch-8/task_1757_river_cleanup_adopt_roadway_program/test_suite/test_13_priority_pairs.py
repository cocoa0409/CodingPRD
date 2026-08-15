"""Validation-family ordering pairs and the segment day-slot resource rule
(PRD §2.11, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_event,
    create_hazard_payload,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    validate_error,
    validate_success,
)

COORD = make_coordinator_headers()


class TestStateBeatsSafety:
    def test_state_beats_safety_on_event_create(self, api):
        """PRD §2.11: "Every request is checked against a fixed sequence of
        rule families, and a failure surfaces the error of the earliest failing
        family"
        PRD §2.11 family 7: "**Safety rules** — hazard blocks on scheduling,
        minor-guardian and supervisor rules on waivers, and briefing-attendee
        rules (the family of 422 safety errors)."
        PRD §3.3: "the agreement-state guard rejects a non-`ACTIVE` agreement
        with `ERR_AGREEMENT_NOT_ACTIVE`; the safety guard refuses scheduling
        while any hazard report on the agreement's segment is in `REPORTED` or
        `ACKNOWLEDGED`, with `ERR_HAZARD_UNRESOLVED`"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_event_create
        """
        group, segment, agreement = setup_active_agreement()
        validate_success(
            api.suspend_agreement(agreement["id"], {"reason": "audit"}, COORD), 200)
        # Open hazard on the same segment.
        validate_success(api.create_hazard(
            create_hazard_payload(segment["id"],
                                  description="rusted drum",
                                  location_note="MP 5.1 north bank"),
            COORD), 201)

        gl = make_group_leader_headers(group["id"])
        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl)
        # Both state (agreement SUSPENDED, family 6) and safety (open hazard,
        # family 7) fail; the earlier family wins.
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_safety_error_surfaces_once_state_passes(self, api):
        """PRD §3.3: "the safety guard refuses scheduling while any hazard
        report on the agreement's segment is in `REPORTED` or `ACKNOWLEDGED`,
        with `ERR_HAZARD_UNRESOLVED`"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_event_create
        """
        group, segment, agreement = setup_active_agreement()
        validate_success(api.create_hazard(
            create_hazard_payload(segment["id"]), COORD), 201)
        gl = make_group_leader_headers(group["id"])
        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, gl)
        # Agreement is ACTIVE, so the state family passes and the safety
        # violation surfaces.
        validate_error(resp, ApiErrorId.ERR_HAZARD_UNRESOLVED)


class TestTemporalBeatsConstraint:
    def test_temporal_beats_constraint_on_event_create(self, api):
        """PRD §2.11: "Every request is checked against a fixed sequence of
        rule families, and a failure surfaces the error of the earliest failing
        family"
        PRD §2.11 family 8: "**Temporal windows** — scheduling lead time,
        briefing and reporting windows, and the renewal window (the family of
        422 timing errors)."
        PRD §2.11 family 9: "**Business constraints** — segment availability,
        event day-slot uniqueness, measured-weight reconciliation,
        return-quantity caps, one-distribution-per-event,
        one-live-sign-per-agreement, renewal eligibility, and the
        completed-cleanup prerequisite for sign installation."
        PRD §3.3: "the temporal guard requires the `scheduled_date` to be at
        least 14 days after the clock date, rejecting earlier dates with
        `ERR_EVENT_TOO_SOON`; and the day-slot constraint forbids another live
        event — one in `SCHEDULED`, `BRIEFING_DONE`, or `POSTPONED` — on the
        same segment sharing the same `scheduled_date`, rejecting collisions
        with `ERR_EVENT_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_event_create
        """
        group, segment, agreement = setup_active_agreement()
        create_event(agreement["id"], group["id"], scheduled_date="2026-09-10")
        # Advance the clock so 2026-09-10 is only 13 days out.
        set_clock("2026-08-28T09:00:00Z")
        gl = make_group_leader_headers(group["id"])
        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 5}, gl)
        # Both temporal (13 < 14 days, family 8) and day-slot collision
        # (family 9) fail; the earlier family wins.
        validate_error(resp, ApiErrorId.ERR_EVENT_TOO_SOON)

    def test_day_slot_collision_surfaces_once_temporal_passes(self, api):
        """PRD §3.3: "the day-slot constraint forbids another live event — one
        in `SCHEDULED`, `BRIEFING_DONE`, or `POSTPONED` — on the same segment
        sharing the same `scheduled_date`, rejecting collisions with
        `ERR_EVENT_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_event_create
        """
        group, segment, agreement = setup_active_agreement()
        create_event(agreement["id"], group["id"], scheduled_date="2026-09-10")
        gl = make_group_leader_headers(group["id"])
        # Clock is at 2026-08-01, so 2026-09-10 is 40 days out: temporal guard
        # passes; the day-slot collision surfaces.
        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 5}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)


class TestSegmentDaySlot:
    def test_segment_day_slot_half_open_adjacency(self, api):
        """PRD §3.3: "the day-slot constraint forbids another live event — one
        in `SCHEDULED`, `BRIEFING_DONE`, or `POSTPONED` — on the same segment
        sharing the same `scheduled_date`, rejecting collisions with
        `ERR_EVENT_WINDOW_OVERLAP`. The slot rule is per calendar day and
        half-open in effect: events on adjacent days coexist freely."

        Design: Difficulty/resource_temporal_overlap/segment_day_slot_half_open_adjacency
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        ea = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10")

        # Same segment, same calendar date: collision.
        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 4}, gl)
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)

        # Adjacent day: allowed (half-open day slots).
        adj = validate_success(api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-11",
             "expected_volunteers": 4}, gl), 201)
        assert adj["status"] == "SCHEDULED"

        # Cancelling the incumbent frees its slot.
        validate_success(
            api.cancel_event(ea["id"], {"reason": "merged groups"}, gl), 200)
        reb = validate_success(api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 4}, gl), 201)
        assert reb["status"] == "SCHEDULED"

    def test_cancelled_event_releases_day_slot(self, api):
        """PRD §3.3: "the day-slot constraint forbids another live event — one
        in `SCHEDULED`, `BRIEFING_DONE`, or `POSTPONED` — on the same segment
        sharing the same `scheduled_date`, rejecting collisions with
        `ERR_EVENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/segment_day_slot_half_open_adjacency
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        ea = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10")
        validate_success(api.cancel_event(ea["id"], {}, gl), 200)
        # CANCELLED is terminal, so the slot is free again.
        reb = validate_success(api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 4}, gl), 201)
        assert reb["status"] == "SCHEDULED"
