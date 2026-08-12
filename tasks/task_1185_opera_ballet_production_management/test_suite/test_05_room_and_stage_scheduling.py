"""Room half-open overlap semantics vs stage changeover-buffer semantics."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_rehearsal_call,
    assert_stage_slot,
    create_production,
    create_production_in_state,
    create_rehearsal_call,
    create_rehearsal_call_payload,
    create_rehearsal_room,
    create_rehearsal_room_payload,
    create_stage_slot,
    create_stage_slot_payload,
    create_published_call,
    transition_rehearsal_call,
    validate_error,
    validate_success,
)

TD = TEST_USERS["technical_director_headers"]
ANY = TEST_USERS["any_headers"]


class TestRoomOverlap:
    def test_room_back_to_back_allowed_and_overlap_rejected(self, api):
        """PRD §2.8: "Two calls on the same room conflict when each one starts before the other ends; two calls that merely touch — one ending exactly when the other begins — do not conflict, so back-to-back occupation is allowed. Only calls in `DRAFT` or `PUBLISHED` status block a room. The check runs when a rehearsal call is created and is re-run when a call is published; a conflict is rejected with `ERR_ROOM_TIME_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/room_half_open_back_to_back
        """
        production = create_production_in_state("REHEARSAL", title="Giselle",
                                                build_budget_cents=50_000_000)
        room = create_rehearsal_room(name="Studio 1")
        call1 = create_rehearsal_call(production["id"], room["id"],
                                      "2026-06-08T09:00:00Z", "2026-06-08T12:00:00Z")
        assert call1["status"] == "DRAFT"

        # Back-to-back: starts exactly when call1 ends — allowed.
        resp = api.create_rehearsal_call(
            create_rehearsal_call_payload(production["id"], room["id"],
                                          "2026-06-08T12:00:00Z", "2026-06-08T15:00:00Z",
                                          call_type="BLOCKING"),
            TD,
        )
        call2 = validate_success(resp, 201)
        assert_rehearsal_call(call2)
        assert call2["status"] == "DRAFT"

        # 30-minute overlap with call1 (11:30-13:00 vs 09:00-12:00) — rejected.
        resp = api.create_rehearsal_call(
            create_rehearsal_call_payload(production["id"], room["id"],
                                          "2026-06-08T11:30:00Z", "2026-06-08T13:00:00Z",
                                          call_type="STAGING"),
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)

    def test_cancelled_call_does_not_block_room_and_other_rooms_are_independent(self, api):
        """PRD §2.8: "Only calls in `DRAFT` or `PUBLISHED` status block a room."
        PRD §2.8: "**Rehearsal rooms** use strict half-open interval semantics: a call occupies its room from `starts_at` (inclusive) to `ends_at` (exclusive)."

        Design: Difficulty/resource_temporal_overlap/room_half_open_back_to_back
        """
        production = create_production_in_state("REHEARSAL", title="Giselle",
                                                build_budget_cents=50_000_000)
        room1 = create_rehearsal_room(name="Studio 1")
        room2 = create_rehearsal_room(name="Studio 2", capacity=30, hourly_rate_cents=4_000)

        # A different room is an independent resource: same window, no conflict.
        create_published_call(production["id"], room1["id"],
                              "2026-06-08T09:00:00Z", "2026-06-08T12:00:00Z")
        resp = api.create_rehearsal_call(
            create_rehearsal_call_payload(production["id"], room2["id"],
                                          "2026-06-08T09:00:00Z", "2026-06-08T12:00:00Z",
                                          call_type="BLOCKING"),
            TD,
        )
        validate_success(resp, 201)

        # A CANCELLED call drops out of the blocking set.
        call_c = create_published_call(production["id"], room2["id"],
                                       "2026-06-08T14:00:00Z", "2026-06-08T17:00:00Z",
                                       call_type="STAGING")
        transition_rehearsal_call(call_c["id"], "CANCELLED")
        resp = api.create_rehearsal_call(
            create_rehearsal_call_payload(production["id"], room2["id"],
                                          "2026-06-08T15:00:00Z", "2026-06-08T18:00:00Z",
                                          call_type="DRESS"),
            TD,
        )
        validate_success(resp, 201)


class TestCallShape:
    def test_invalid_time_range_rejected(self, api):
        """PRD §2.9: "`ends_at` must be strictly after `starts_at`, and `window_end` strictly after `window_start` — else `ERR_INVALID_TIME_RANGE` (400). This applies to exactly four creation endpoints: `POST /opera/rehearsal-calls`, `POST /opera/stage-slots`, `POST /opera/performances`, and `POST /opera/rental-offers`."

        Design: Corner/validations/invalid_time_range_rejected
        """
        production = create_production_in_state("REHEARSAL", title="Giselle",
                                                build_budget_cents=50_000_000)
        room = create_rehearsal_room(name="Studio 1")
        resp = api.create_rehearsal_call(
            create_rehearsal_call_payload(production["id"], room["id"],
                                          "2026-06-08T12:00:00Z", "2026-06-08T09:00:00Z"),
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_rehearsal_call_double_publish_rejected(self, api):
        """PRD §3.6: "Publishing — `DRAFT` → `PUBLISHED` — is gated twice: the production must be in `REHEARSAL`, else `ERR_PRODUCTION_NOT_IN_REHEARSAL`, and the room-overlap check is re-run against the room's current `DRAFT` and `PUBLISHED` calls, since the calendar may have moved since the draft was made."
        PRD §2.9: "The target entity's current state must permit the requested transition or action. Where the state machine declares a specific code, that code is used ... otherwise the generic `ERR_INVALID_STATE_TRANSITION` (409) is used."

        Design: Corner/state_machines/rehearsal_call_double_publish_rejected
        """
        production = create_production_in_state("REHEARSAL", title="Giselle",
                                                build_budget_cents=50_000_000)
        room = create_rehearsal_room(name="Studio 1")
        call = create_published_call(production["id"], room["id"],
                                     "2026-06-08T09:00:00Z", "2026-06-08T12:00:00Z")
        resp = api.transition_rehearsal_call(call["id"], "PUBLISHED", TD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_rehearsal_call(call["id"], ANY), 200)
        assert after["status"] == "PUBLISHED", "the second publish is not a silent no-op"


class TestImmediateConsistency:
    def test_immediate_read_after_write(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.7: "A `TechnicalDirector` registers rehearsal rooms with a `name`, a `kind` of `STUDIO`, `STAGE`, or `ORCHESTRA_PIT`, a `capacity` greater than zero, and an `hourly_rate_cents`."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        resp = api.create_rehearsal_room(
            create_rehearsal_room_payload(name="Studio 9", kind="ORCHESTRA_PIT",
                                          capacity=80, hourly_rate_cents=9_000),
            TD,
        )
        created = validate_success(resp, 201)
        fetched = validate_success(api.get_rehearsal_room(created["id"], ANY), 200)
        assert fetched["name"] == "Studio 9"
        assert fetched["kind"] == "ORCHESTRA_PIT"
        assert fetched["capacity"] == 80
        assert fetched["hourly_rate_cents"] == 9_000


class TestStageChangeover:
    def test_stage_cross_production_six_hour_gap_passes_one_hour_same_fails(self, api):
        """PRD §2.8: "The required gap is two hours when the existing slot belongs to the same production as the new one (a reset buffer) and six hours when it belongs to a different production (a changeover buffer). A conflict exists when the existing slot starts before the new slot's end plus the required gap, and the new slot starts before the existing slot's end plus the required gap; overlap is therefore always a conflict, while adjacency is allowed only when the gap between the slots is at least the buffer. A gap of exactly the buffer passes. Violations are rejected with `ERR_STAGE_CHANGEOVER_CONFLICT` (HTTP 409)."

        P1 LOAD_OUT 2026-06-10 16:00-20:00. P2 LOAD_IN next day 02:00 (gap exactly
        6h, passes); P1 TECH at 21:00 (gap 1h < 2h reset buffer, rejected).

        Design: Difficulty/resource_temporal_overlap/stage_changeover_buffer_semantics
        """
        prod1 = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        prod2 = create_production(title="Otello", work_type="OPERA",
                                  build_budget_cents=80_000_000)
        slot_out = create_stage_slot(prod1["id"], "2026-06-10T16:00:00Z",
                                     "2026-06-10T20:00:00Z", slot_type="LOAD_OUT")
        assert slot_out["status"] == "PLANNED"

        resp = api.create_stage_slot(
            create_stage_slot_payload(prod2["id"], "2026-06-11T02:00:00Z",
                                      "2026-06-11T06:00:00Z", slot_type="LOAD_IN"),
            TD,
        )
        slot_in = validate_success(resp, 201)
        assert_stage_slot(slot_in)

        resp = api.create_stage_slot(
            create_stage_slot_payload(prod1["id"], "2026-06-10T21:00:00Z",
                                      "2026-06-10T23:00:00Z", slot_type="TECH"),
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_STAGE_CHANGEOVER_CONFLICT)

    def test_stage_same_production_two_hour_gap_passes_five_hour_cross_fails(self, api):
        """PRD §3.7: "Creation runs the changeover check of §2.8 — the two-hour reset buffer between slots of the same production, the six-hour changeover buffer between slots of different productions, with a gap exactly equal to the buffer allowed — rejecting conflicts with `ERR_STAGE_CHANGEOVER_CONFLICT`."

        P1 TECH 16:00-18:00 then P1 LOAD_OUT 20:00-22:00 (gap exactly 2h, passes);
        P2 LOAD_IN next day 03:00-05:00 (gap 5h from the 22:00 end < 6h, rejected).

        Design: Difficulty/resource_temporal_overlap/stage_changeover_buffer_semantics
        """
        prod1 = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        prod2 = create_production(title="Otello", work_type="OPERA",
                                  build_budget_cents=80_000_000)
        create_stage_slot(prod1["id"], "2026-06-10T16:00:00Z", "2026-06-10T18:00:00Z",
                          slot_type="TECH")

        resp = api.create_stage_slot(
            create_stage_slot_payload(prod1["id"], "2026-06-10T20:00:00Z",
                                      "2026-06-10T22:00:00Z", slot_type="LOAD_OUT"),
            TD,
        )
        slot2 = validate_success(resp, 201)
        assert_stage_slot(slot2)

        resp = api.create_stage_slot(
            create_stage_slot_payload(prod2["id"], "2026-06-11T03:00:00Z",
                                      "2026-06-11T05:00:00Z", slot_type="LOAD_IN"),
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_STAGE_CHANGEOVER_CONFLICT)
