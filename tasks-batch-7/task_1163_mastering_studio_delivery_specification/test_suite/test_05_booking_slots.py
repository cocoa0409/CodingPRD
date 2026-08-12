"""Booking gates, session-slot holds, overlap semantics, hold expiry, and OCC
(PRD §3.3, §3.4, §2.5, §2.6, §2.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_logical_clock, make_engineer, make_platform_profile, make_rush_tier_rule,
    make_client, make_project, activate_client, current_client_version,
    book_project, make_held_slot, make_client_headers, create_project_payload,
    create_session_slot_payload, create_credit_adjustment_payload,
    setup_booked_project, TEST_USERS, ApiErrorId,
)

MANAGER = TEST_USERS["manager_headers"]
QA = TEST_USERS["qa_headers"]


class TestBookGatedByClientActive:

    def test_book_rejected_when_client_not_active(self, api):
        """PRD §3.3: "The client must be `ACTIVE` — booking against a suspended or
        prospective client fails with `ERR_ENTITY_NOT_ACTIVE` (HTTP 422)".

        A PROSPECT client's project cannot be booked and stays DRAFT.

        Design: Difficulty/cross_entity_state_dependency/project_book_gated_by_client_active
        """
        set_logical_clock()
        make_engineer()
        profile = make_platform_profile()
        make_rush_tier_rule()
        client = make_client(credit_cents=100000)
        project = make_project(client["id"], profile["id"])
        version = current_client_version(client["id"])

        res = api.book_project(project["id"], {"expected_client_version": version},
                               make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_ENTITY_NOT_ACTIVE, expected_status=422)
        after = validate_success(api.get_project(project["id"], MANAGER), 200)
        assert after["status"] == "DRAFT"

    def test_failed_booking_creates_no_slot_or_assignment(self, api):
        """PRD §2.5: "Every request is evaluated against a fixed guard chain, and
        guards fire in ascending priority: a failure at an earlier step halts
        evaluation and masks every later check." PRD §3.3: "A successful booking
        performs its side effects atomically: a session slot in `BOOKED` status is
        created covering the window from `scheduled_start_at` for
        `scheduled_duration_minutes`; the project's `assigned_engineer_id` is set to
        the selected engineer".

        A booking rejected at the cross-entity guard produces none of the booking
        side effects.

        Design: Difficulty/cross_entity_state_dependency/project_book_gated_by_client_active
        """
        set_logical_clock()
        make_engineer()
        profile = make_platform_profile()
        make_rush_tier_rule()
        client = make_client(credit_cents=100000)
        project = make_project(client["id"], profile["id"])
        version = current_client_version(client["id"])

        api.book_project(project["id"], {"expected_client_version": version},
                         make_client_headers(client["id"]))
        slots, meta = validate_paginated(
            api.list_session_slots(MANAGER, params={"project_id": project["id"]}))
        assert slots == [], "a rejected booking must not create a session slot"
        after = validate_success(api.get_project(project["id"], MANAGER), 200)
        assert after.get("assigned_engineer_id") in (None,), (
            "a rejected booking must not assign an engineer")


class TestSlotConfirmStateVsSafetyPriority:

    def _setup_booked_slot(self, api):
        set_logical_clock()
        engineer = make_engineer()
        client = make_client()
        slot = make_held_slot(engineer["id"])
        validate_success(api.confirm_session_slot(
            slot["id"], make_client_headers(client["id"])), 200)
        return engineer, client, slot

    def test_confirm_booked_slot_with_engineer_on_leave_returns_state_error(self, api):
        """PRD §2.5: "Every request is evaluated against a fixed guard chain, and
        guards fire in ascending priority: a failure at an earlier step halts
        evaluation and masks every later check." PRD §2.5: "Fifth (priority 5), state
        admissibility: the resource's current state must permit the requested
        transition on every action endpoint, failing with `ERR_INVALID_STATE` (HTTP
        409)". PRD §2.5: "Sixth (priority 6), cross-entity activity guards: the
        engineer must be `AVAILABLE` before a session hold is confirmed, and the
        client must be `ACTIVE` before a project is booked — booking and
        hold-confirmation are the two guarded operations — failing with
        `ERR_ENTITY_NOT_ACTIVE` (HTTP 422)."

        With the slot already BOOKED (priority 5 violated) AND the engineer ON_LEAVE
        (priority 6 violated), the earlier guard reports ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_double_book_suspended_client
        """
        engineer, client, slot = self._setup_booked_slot(api)
        validate_success(api.set_engineer_availability(
            engineer["id"], {"availability_status": "ON_LEAVE"}, MANAGER), 200)
        res = api.confirm_session_slot(slot["id"], make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_confirm_booked_slot_returns_state_error_when_engineer_available(self, api):
        """PRD §2.5: "Fifth (priority 5), state admissibility: the resource's current
        state must permit the requested transition on every action endpoint, failing
        with `ERR_INVALID_STATE` (HTTP 409)".

        Isolated state violation: a BOOKED slot cannot be confirmed again even when
        the engineer is AVAILABLE.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_double_book_suspended_client
        """
        engineer, client, slot = self._setup_booked_slot(api)
        res = api.confirm_session_slot(slot["id"], make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestHeldSlotExpiryBoundary:

    def test_confirm_at_exact_expiry_instant_rejected(self, api):
        """PRD §3.4: "It must happen before `held_expires_at`; a confirmation
        attempted at or after the expiry instant is rejected with `ERR_HOLD_EXPIRED`
        (HTTP 410)." PRD §2.6: "When a session slot is created it enters `HELD` and
        the server stamps `held_expires_at` as its creation time plus fifteen
        minutes."

        Slot created at 09:00:00 expires at 09:15:00; confirming at exactly
        09:15:00 is rejected.

        Design: Difficulty/boundary_precision_check/held_slot_expiry_at_exact_second
        """
        set_logical_clock("2026-05-10T09:00:00Z")
        engineer = make_engineer()
        client = make_client()
        slot = make_held_slot(engineer["id"])
        set_logical_clock("2026-05-10T09:15:00Z")
        res = api.confirm_session_slot(slot["id"], make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_HOLD_EXPIRED, expected_status=410)

    def test_confirm_one_second_before_expiry_succeeds(self, api):
        """PRD §3.4: "It must happen before `held_expires_at`; a confirmation
        attempted at or after the expiry instant is rejected with `ERR_HOLD_EXPIRED`
        (HTTP 410)."

        One second before the expiry instant the confirmation succeeds and the slot
        moves HELD → BOOKED.

        Design: Difficulty/boundary_precision_check/held_slot_expiry_at_exact_second
        """
        set_logical_clock("2026-05-10T09:00:00Z")
        engineer = make_engineer()
        client = make_client()
        slot = make_held_slot(engineer["id"])
        set_logical_clock("2026-05-10T09:14:59Z")
        confirmed = validate_success(
            api.confirm_session_slot(slot["id"], make_client_headers(client["id"])), 200)
        assert confirmed["status"] == "BOOKED"


class TestSlotOverlapHalfOpen:

    def test_adjacent_slots_sharing_a_boundary_do_not_conflict(self, api):
        """PRD §2.6: "A requested window conflicts with an existing `BOOKED` or
        `HELD` slot for the same engineer only when the requested start is strictly
        before the existing slot's end and the existing slot's start is strictly
        before the requested end; two slots that merely touch at a boundary — one
        ending at the exact minute the other begins — do not conflict."

        Slot [10:00, 11:00) is BOOKED; a new slot [11:00, 12:00) is accepted in HELD.

        Design: Difficulty/resource_temporal_overlap/session_slot_adjacency_half_open_no_overlap
        """
        set_logical_clock()
        engineer = make_engineer()
        client = make_client()
        slot1 = make_held_slot(engineer["id"])
        validate_success(api.confirm_session_slot(
            slot1["id"], make_client_headers(client["id"])), 200)
        slot2 = validate_success(api.create_session_slot(
            create_session_slot_payload(
                engineer["id"], slot_start_at="2026-05-11T11:00:00Z",
                slot_end_at="2026-05-11T12:00:00Z"), MANAGER), 201)
        assert slot2["status"] == "HELD"

    def test_overlapping_slot_rejected(self, api):
        """PRD §2.6: "A conflict is rejected with `ERR_SLOT_CONFLICT` (HTTP 409)."

        A new slot [10:30, 11:30) overlaps the BOOKED slot [10:00, 11:00).

        Design: Difficulty/resource_temporal_overlap/session_slot_adjacency_half_open_no_overlap
        """
        set_logical_clock()
        engineer = make_engineer()
        client = make_client()
        slot1 = make_held_slot(engineer["id"])
        validate_success(api.confirm_session_slot(
            slot1["id"], make_client_headers(client["id"])), 200)
        res = api.create_session_slot(
            create_session_slot_payload(
                engineer["id"], slot_start_at="2026-05-11T10:30:00Z",
                slot_end_at="2026-05-11T11:30:00Z"), MANAGER)
        validate_error(res, ApiErrorId.ERR_SLOT_CONFLICT, expected_status=409)


class TestBookingBasics:

    def test_project_start_off_30_minute_grid_rejected(self, api):
        """PRD §2.6: "`scheduled_start_at` on a project, and `slot_start_at` and
        `slot_end_at` on a session slot, must each fall on minute :00 or :30 of an
        hour; a timestamp off the grid is rejected with `ERR_INVALID_TIME_BOUNDARY`
        (HTTP 400)."

        Design: Corner/validations/invalid_time_boundary_rejected
        """
        set_logical_clock()
        profile = make_platform_profile()
        client = make_client()
        payload = create_project_payload(
            client["id"], profile["id"],
            scheduled_start_at="2026-05-11T10:15:00Z",
            scheduled_duration_minutes=60, rush_tier="STANDARD")
        res = api.create_project(payload, make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_TIME_BOUNDARY, expected_status=400)

    def test_book_creates_slot_assigns_engineer_and_writes_quote(self, api):
        """PRD §3.3: "A successful booking performs its side effects atomically: a
        session slot in `BOOKED` status is created covering the window from
        `scheduled_start_at` for `scheduled_duration_minutes`; the project's
        `assigned_engineer_id` is set to the selected engineer; the engineer's
        `active_project_count` increments; the provisional pricing variant runs and
        writes `quoted_price_cents`; and both the project's `version` and the
        client's `version` increment."

        Design: Corner/state_machines/side_effect_execution_book_creates_session_slot
        """
        ctx = setup_booked_project()
        project = ctx["project"]
        assert project["status"] == "BOOKED"
        assert project.get("assigned_engineer_id"), (
            "booking must assign an engineer")
        assert project["quoted_price_cents"] > 0, (
            "provisional quote must be written at booking")
        slots, meta = validate_paginated(
            api.list_session_slots(MANAGER, params={"project_id": project["id"]}))
        assert len(slots) == 1
        assert slots[0]["status"] == "BOOKED"
        assert slots[0]["slot_start_at"].startswith("2026-05-11T10:00:00")

    def test_booking_with_stale_client_version_rejected(self, api):
        """PRD §2.9: "A booking request must carry `expected_client_version`, holding
        the client's `version` as the caller last observed it. If the client record's
        current `version` has advanced since that observation — for instance because
        another writer has just suspended the client, which legitimately releases
        held session slots and cancels early-stage projects, leaving the caller's
        view of the client's status stale — the booking is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and no booking side effects occur."

        The captured version is made stale by a credit adjustment that mutates the
        client record before the booking attempt.

        Design: Corner/cross_cutting/occ_stale_version_on_booking
        """
        set_logical_clock()
        make_engineer()
        profile = make_platform_profile()
        make_rush_tier_rule()
        client = make_client(credit_cents=100000)
        project = make_project(client["id"], profile["id"])
        activate_client(client["id"])
        stale_version = current_client_version(client["id"])
        # Any further mutation advances the client version (PRD §2.4).
        validate_success(api.create_credit_adjustment(
            client["id"],
            create_credit_adjustment_payload(amount_cents=1, reason="bump version"),
            MANAGER), 201)
        res = api.book_project(
            project["id"], {"expected_client_version": stale_version},
            make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        after = validate_success(api.get_project(project["id"], MANAGER), 200)
        assert after["status"] == "DRAFT", "no booking side effects may occur"
