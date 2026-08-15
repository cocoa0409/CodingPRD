"""Publication slots and scheduling: window spacing, fit checks, OCC tokens,
the reservation counter invariant, cancel guards, and immediate consistency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_staff_to,
    create_slot,
    create_slot_payload,
    get_success_data,
    schedule,
    schedule_payload,
    setup_cleared_story,
    setup_newsroom,
    create_greenlit_story,
    drive_story_to_cleared,
    validate_error,
    validate_success,
)

ND = TEST_USERS["news_director_headers"]


def _cleared(ctx, title, embargo_until=None,
             assignment_window=("2026-08-01T08:00:00Z",
                                "2026-08-01T09:00:00Z")):
    """Greenlit story driven to CLEARED (optionally embargoed)."""
    _pitch, story_id = create_greenlit_story(
        ctx, title=title, deadline_at="2026-08-06T00:00:00Z")
    return drive_story_to_cleared(ctx, story_id, embargo_until=embargo_until,
                                  assignment_window=assignment_window)


class TestSlotWindowGap:
    def test_exact_thirty_minute_gap_conflicts(self, api):
        """PRD §3.5: "The window must be sane — `window_end` strictly after
        `window_start`, else `ERR_INVALID_INTERVAL` — and slots on the same
        channel must respect turnaround: a new slot conflicts with an existing
        `ACTIVE` slot on the same channel unless their windows are separated
        by strictly more than 30 minutes, so an exact 30-minute gap still
        conflicts, as does any overlap or smaller gap, and the violation is
        rejected with `ERR_SLOT_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/slot_window_buffer_gap
        """
        ctx = setup_newsroom()
        create_slot(ctx["desk_headers"], window_start="2026-08-05T18:00:00Z",
                    window_end="2026-08-05T19:00:00Z", capacity=2)
        payload = create_slot_payload(window_start="2026-08-05T19:30:00Z",
                                      window_end="2026-08-05T20:00:00Z")
        resp = api.create_slot(payload, ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_CONFLICT)

    def test_gap_31_minutes_and_other_channel_pass(self, api):
        """PRD §3.5: "The window must be sane — `window_end` strictly after
        `window_start`, else `ERR_INVALID_INTERVAL` — and slots on the same
        channel must respect turnaround: a new slot conflicts with an existing
        `ACTIVE` slot on the same channel unless their windows are separated
        by strictly more than 30 minutes, so an exact 30-minute gap still
        conflicts, as does any overlap or smaller gap, and the violation is
        rejected with `ERR_SLOT_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/slot_window_buffer_gap
        """
        ctx = setup_newsroom()
        create_slot(ctx["desk_headers"], window_start="2026-08-05T18:00:00Z",
                    window_end="2026-08-05T19:00:00Z", capacity=2)
        payload = create_slot_payload(window_start="2026-08-05T19:30:00Z",
                                      window_end="2026-08-05T20:00:00Z")
        validate_error(api.create_slot(payload, ctx["desk_headers"]),
                       ApiErrorId.ERR_SLOT_WINDOW_CONFLICT)

        # 31 minutes of separation is strictly more than 30: allowed.
        ok1 = api.create_slot(
            create_slot_payload(window_start="2026-08-05T19:31:00Z",
                                window_end="2026-08-05T20:00:00Z"),
            ctx["desk_headers"])
        assert validate_success(ok1, 201)["status"] == "ACTIVE"

        # A different channel sharing the wall-clock window is isolated.
        ok2 = api.create_slot(
            create_slot_payload(channel="BROADCAST",
                                window_start="2026-08-05T19:00:00Z",
                                window_end="2026-08-05T20:00:00Z"),
            ctx["desk_headers"])
        assert validate_success(ok2, 201)["channel"] == "BROADCAST"


class TestScheduleFitChecks:
    def test_channel_mismatch_on_schedule(self, api):
        """PRD §3.5: "Three fit checks then apply: the story's `story_type`
        must equal the slot's `channel` — print copy does not go into a
        broadcast window (`ERR_CHANNEL_MISMATCH`, HTTP 422); the story's
        `embargo_until`, when set, must fall no later than the slot's
        `window_end` (`ERR_EMBARGO_BEYOND_SLOT`, HTTP 422); and the slot must
        have room — `reserved_count` below `capacity`, with rejection exactly
        when the count already equals capacity (`ERR_SLOT_CAPACITY_EXCEEDED`,
        HTTP 422)."

        Design: Corner/validations/channel_mismatch_on_schedule
        """
        ctx, story = setup_cleared_story(story_type="BROADCAST",
                                         deadline_at="2026-08-06T00:00:00Z")
        slot = create_slot(ctx["desk_headers"], channel="PRINT")
        resp = api.schedule_story(
            story["id"],
            schedule_payload(slot["id"], story["version"]),
            ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_CHANNEL_MISMATCH)

    def test_embargo_equal_window_end_allowed(self, api):
        """PRD §3.5: "Three fit checks then apply: the story's `story_type`
        must equal the slot's `channel` — print copy does not go into a
        broadcast window (`ERR_CHANNEL_MISMATCH`, HTTP 422); the story's
        `embargo_until`, when set, must fall no later than the slot's
        `window_end` (`ERR_EMBARGO_BEYOND_SLOT`, HTTP 422); and the slot must
        have room — `reserved_count` below `capacity`, with rejection exactly
        when the count already equals capacity (`ERR_SLOT_CAPACITY_EXCEEDED`,
        HTTP 422)."

        Design: Corner/validations/embargo_equal_window_end_allowed
        """
        ctx, story = setup_cleared_story(
            deadline_at="2026-08-06T00:00:00Z", word_count=400,
            embargo_until="2026-08-05T19:00:00Z")
        slot = create_slot(ctx["desk_headers"])
        resp = api.schedule_story(
            story["id"], schedule_payload(slot["id"], story["version"]),
            ctx["desk_headers"])
        scheduled = validate_success(resp)
        assert scheduled["status"] == "SCHEDULED", \
            "embargo_until == window_end is permitted (no later than)"

    def test_schedule_into_full_slot_rejected(self, api):
        """PRD §3.5: "Three fit checks then apply: the story's `story_type`
        must equal the slot's `channel` — print copy does not go into a
        broadcast window (`ERR_CHANNEL_MISMATCH`, HTTP 422); the story's
        `embargo_until`, when set, must fall no later than the slot's
        `window_end` (`ERR_EMBARGO_BEYOND_SLOT`, HTTP 422); and the slot must
        have room — `reserved_count` below `capacity`, with rejection exactly
        when the count already equals capacity (`ERR_SLOT_CAPACITY_EXCEEDED`,
        HTTP 422)."

        Design: Corner/validations/schedule_into_full_slot_rejected
        """
        ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                             legal_reviewer=True)
        sx = _cleared(ctx, "FS X")
        sy = _cleared(ctx, "FS Y",
                      assignment_window=("2026-08-01T09:00:00Z",
                                         "2026-08-01T10:00:00Z"))
        slot = create_slot(ctx["desk_headers"], capacity=1)
        schedule(ctx, sx["id"], slot["id"])

        resp = api.schedule_story(
            sy["id"], schedule_payload(slot["id"], sy["version"]),
            ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)
        slot_after = get_success_data(api.get_slot(slot["id"], ND))
        assert slot_after["reserved_count"] == 1, "the failed schedule held"

class TestTemporalBeatsFiscal:
    def _full_slot_plus_embargoed_story(self, api):
        """Capacity-1 PRINT slot already holding story X; story Y CLEARED
        with embargo_until beyond the slot's window_end."""
        ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                             legal_reviewer=True)
        slot = create_slot(ctx["desk_headers"], capacity=1)
        sx = _cleared(ctx, "FS X")
        schedule(ctx, sx["id"], slot["id"])
        sy = _cleared(ctx, "FS Y",
                      embargo_until="2026-08-06T00:00:00Z",
                      assignment_window=("2026-08-01T09:00:00Z",
                                         "2026-08-01T10:00:00Z"))
        return ctx, slot, sy

    def test_embargo_error_wins_over_capacity_error(self, api):
        """PRD §2.7: "Every write request passes through a single ordered
        validation pipeline, and the first failing check determines the error
        returned."
        PRD §2.7: "12. Temporal sanity — interval ordering on assignments,
        slots, events, and analytics windows (`ERR_INVALID_INTERVAL`,
        HTTP 422), the embargo-versus-slot check at scheduling
        (`ERR_EMBARGO_BEYOND_SLOT`, HTTP 422), and call-in expiry at confirm
        or decline (`ERR_CALL_IN_EXPIRED`, HTTP 409)."
        PRD §2.7: "14. Capacity — the assignment acceptance cap
        (`ERR_ASSIGNMENT_CAP_REACHED`, HTTP 422) and the slot reservation
        capacity (`ERR_SLOT_CAPACITY_EXCEEDED`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_schedule
        """
        ctx, slot, sy = self._full_slot_plus_embargoed_story(api)
        # Both failures are latent: embargo 2026-08-06 lies beyond the slot's
        # window_end 2026-08-05T19:00 AND the slot is full. The temporal
        # check fires first.
        resp = api.schedule_story(
            sy["id"], schedule_payload(slot["id"], sy["version"]),
            ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_EMBARGO_BEYOND_SLOT)

    def test_failed_schedule_leaves_story_and_slot_untouched(self, api):
        """PRD §3.5: "A successful schedule moves the story `CLEARED →
        SCHEDULED`, sets its `slot_id`, raises the slot's `reserved_count` by
        one, and increments the story's `version`. Unscheduling reverses the
        move — `SCHEDULED → CLEARED`, the slot's `reserved_count` drops by
        one, and `slot_id` returns to null."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_schedule
        """
        ctx, slot, sy = self._full_slot_plus_embargoed_story(api)
        resp = api.schedule_story(
            sy["id"], schedule_payload(slot["id"], sy["version"]),
            ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_EMBARGO_BEYOND_SLOT)
        story_after = get_success_data(api.get_story(sy["id"], ND))
        assert story_after["status"] == "CLEARED"
        assert story_after["slot_id"] is None
        slot_after = get_success_data(api.get_slot(slot["id"], ND))
        assert slot_after["reserved_count"] == 1, \
            "the rejected schedule acquired no reservation"


class TestScheduleOcc:
    def test_occ_stale_schedule_after_reschedule(self, api):
        """PRD §2.8: "A schedule request whose `expected_story_version` no
        longer equals the story's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412) — for example because the story was
        edited, or re-scheduled by another desk action, since the token was
        read; the schedule supersedes the desk's prior view of the story."

        Design: Corner/cross_cutting_layers/occ_stale_schedule_after_reschedule
        """
        ctx, story = setup_cleared_story(
            deadline_at="2026-08-06T00:00:00Z")
        slot = create_slot(ctx["desk_headers"], capacity=1)
        stale_token = story["version"]
        schedule(ctx, story["id"], slot["id"],
                 expected_story_version=stale_token)
        get_success_data(
            api.unschedule_story(story["id"], ctx["desk_headers"]))

        # The story is CLEARED again, but the token aged two versions.
        resp = api.schedule_story(
            story["id"], schedule_payload(slot["id"], stale_token),
            ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        slot_after = get_success_data(api.get_slot(slot["id"], ND))
        assert slot_after["reserved_count"] == 0, \
            "the rejected schedule acquired nothing"


class TestUnscheduleAndSlotCancel:
    def test_story_unschedule_from_cleared_rejected(self, api):
        """PRD §3.5: "A successful schedule moves the story `CLEARED →
        SCHEDULED`, sets its `slot_id`, raises the slot's `reserved_count` by
        one, and increments the story's `version`. Unscheduling reverses the
        move — `SCHEDULED → CLEARED`, the slot's `reserved_count` drops by
        one, and `slot_id` returns to null."
        PRD §2.7: "8. From-state legality — the target resource is in a
        from-state of the invoked transition; failures yield
        `ERR_INVALID_STATE` (HTTP 409), except that proposing a correction or
        ingesting analytics against a story that is not published yields
        `ERR_STORY_NOT_PUBLISHED` (HTTP 409)."

        Design: Corner/state_machines/story_unschedule_from_cleared_rejected
        """
        ctx, story = setup_cleared_story()
        assert story["status"] == "CLEARED"
        resp = api.unschedule_story(story["id"], ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_slot_cancel_not_empty(self, api):
        """PRD §3.5: "Finally, a `ManagingEditor` may cancel a slot that is
        still `ACTIVE`, moving it to `CANCELLED` — but only when its
        `reserved_count` is zero; cancelling a slot with reservations
        outstanding is rejected with `ERR_SLOT_NOT_EMPTY` (HTTP 409)."

        Design: Corner/validations/slot_cancel_not_empty
        """
        ctx, story = setup_cleared_story(
            deadline_at="2026-08-06T00:00:00Z")
        add_staff_to(ctx, "managing_editor", "MANAGING_EDITOR",
                     hourly_rate_cents=8000)
        slot = create_slot(ctx["desk_headers"], capacity=1)
        schedule(ctx, story["id"], slot["id"])

        resp = api.cancel_slot(slot["id"], ctx["managing_editor_headers"])
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_EMPTY)

        get_success_data(
            api.unschedule_story(story["id"], ctx["desk_headers"]))
        ok = api.cancel_slot(slot["id"], ctx["managing_editor_headers"])
        assert validate_success(ok)["status"] == "CANCELLED", \
            "cancel succeeds once the reservation is released"


class TestSlotReservationRoundTrip:
    def _story_and_slot(self, api):
        ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                             legal_reviewer=True)
        _pitch, story_id = create_greenlit_story(
            ctx, title="Opera review", desk="FEATURES",
            deadline_at="2026-08-07T00:00:00Z")
        story = drive_story_to_cleared(ctx, story_id, word_count=600)
        slot = create_slot(ctx["desk_headers"],
                           window_start="2026-08-06T18:00:00Z",
                           window_end="2026-08-06T19:00:00Z", capacity=2)
        return ctx, story, slot

    def _reserved(self, api, slot_id):
        return get_success_data(api.get_slot(slot_id, ND))["reserved_count"]

    def test_schedule_unschedule_compensate(self, api):
        """PRD §2.11: "A publication slot's `reserved_count` is the number of
        stories pointing at that slot with status `SCHEDULED`; it rises when a
        story is scheduled into the slot and falls when such a story is
        unscheduled, killed, or bumped out of the slot."
        PRD §3.5: "A successful schedule moves the story `CLEARED →
        SCHEDULED`, sets its `slot_id`, raises the slot's `reserved_count` by
        one, and increments the story's `version`. Unscheduling reverses the
        move — `SCHEDULED → CLEARED`, the slot's `reserved_count` drops by
        one, and `slot_id` returns to null."

        Design: Difficulty/compensating_invariant/slot_reservation_round_trip
        """
        ctx, story, slot = self._story_and_slot(api)
        assert self._reserved(api, slot["id"]) == 0
        schedule(ctx, story["id"], slot["id"])
        assert self._reserved(api, slot["id"]) == 1
        get_success_data(
            api.unschedule_story(story["id"], ctx["desk_headers"]))
        assert self._reserved(api, slot["id"]) == 0, \
            "schedule/unschedule compensate exactly"

    def test_reschedule_then_kill_returns_to_baseline(self, api):
        """PRD §2.11: "A publication slot's `reserved_count` is the number of
        stories pointing at that slot with status `SCHEDULED`; it rises when a
        story is scheduled into the slot and falls when such a story is
        unscheduled, killed, or bumped out of the slot."
        PRD §3.5: "The kill cascades: every assignment on the story still in
        `PROPOSED` or `ACCEPTED` moves to `CANCELLED` with each affected staff
        member's `active_assignment_count` recomputed, and if the story was
        `SCHEDULED` its slot's `reserved_count` drops by one and `slot_id`
        clears."

        Design: Difficulty/compensating_invariant/slot_reservation_round_trip
        """
        ctx, story, slot = self._story_and_slot(api)
        add_staff_to(ctx, "managing_editor", "MANAGING_EDITOR",
                     hourly_rate_cents=8000)
        schedule(ctx, story["id"], slot["id"])
        get_success_data(
            api.unschedule_story(story["id"], ctx["desk_headers"]))
        schedule(ctx, story["id"], slot["id"])
        assert self._reserved(api, slot["id"]) == 1, \
            "re-schedule re-acquires the reservation"

        get_success_data(
            api.kill_story(story["id"], ctx["managing_editor_headers"]))
        assert self._reserved(api, slot["id"]) == 0, \
            "killing a SCHEDULED story releases the reservation"


class TestImmediateConsistency:
    def test_schedule_immediately_visible(self, api):
        """PRD §3.5: "A successful schedule moves the story `CLEARED →
        SCHEDULED`, sets its `slot_id`, raises the slot's `reserved_count` by
        one, and increments the story's `version`. Unscheduling reverses the
        move — `SCHEDULED → CLEARED`, the slot's `reserved_count` drops by
        one, and `slot_id` returns to null."
        PRD §2.11: "A publication slot's `reserved_count` is the number of
        stories pointing at that slot with status `SCHEDULED`; it rises when a
        story is scheduled into the slot and falls when such a story is
        unscheduled, killed, or bumped out of the slot."

        Design: Corner/consistency_model/schedule_immediately_visible
        """
        ctx, story = setup_cleared_story(
            deadline_at="2026-08-06T00:00:00Z")
        slot = create_slot(ctx["desk_headers"], capacity=1)
        resp = api.schedule_story(
            story["id"], schedule_payload(slot["id"], story["version"]),
            ctx["desk_headers"])
        scheduled = validate_success(resp)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["slot_id"] == slot["id"], "in-response wiring"

        slot_after = get_success_data(api.get_slot(slot["id"], ND))
        assert slot_after["reserved_count"] == 1, \
            "the very next read already reports the reservation"
