"""Session creation guards, scheduling gates, and calendar conflicts
(PRD §2.8, §2.10, §3.5)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    get_facilitator_version,
    get_success_data,
    make_active_group,
    make_bootstrap_reviewer,
    make_certified_facilitator,
    make_course,
    make_facilitator,
    make_program,
    make_room,
    make_session,
    make_scheduled_session,
    NON_EXISTENT_UUID,
    reset_clock,
    schedule_session,
    setup_certified_facilitator,
    setup_program_with_active_group,
    setup_session_scenario,
    validate_error,
    validate_success,
)


class TestSessionCreationGuards:
    def test_end_at_not_after_start_at_rejected(self, api):
        """PRD §3.5: "The end must be strictly later than the start, else
        `ERR_INVALID_TIME_RANGE` (HTTP 422)."

        Design: Corner/validations/session_invalid_time_range_rejected
        """
        env = setup_program_with_active_group(modality="VIRTUAL")
        facilitator = make_facilitator(full_name="F")
        resp = api.create_session(
            env.program["id"], env.group["id"],
            {"start_at": "2026-08-03T11:00:00Z", "end_at": "2026-08-03T10:00:00Z",
             "primary_facilitator_id": facilitator["id"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_cofacilitator_same_as_primary_rejected(self, api):
        """PRD §3.5: "The cofacilitator must differ from the primary, else
        `ERR_COFACILITATOR_SAME_AS_PRIMARY` (HTTP 422)."

        Design: Corner/validations/cofacilitator_same_as_primary_rejected
        """
        env = setup_program_with_active_group(modality="VIRTUAL")
        facilitator = make_facilitator(full_name="F")
        resp = api.create_session(
            env.program["id"], env.group["id"],
            {"start_at": "2026-08-03T10:00:00Z", "end_at": "2026-08-03T11:00:00Z",
             "primary_facilitator_id": facilitator["id"],
             "cofacilitator_id": facilitator["id"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_COFACILITATOR_SAME_AS_PRIMARY)


class TestReferenceVersusTemporalOrdering:
    def test_nonexistent_room_rejected_before_any_overlap_check(self, api):
        """PRD §3.5: "Referenced rooms and facilitators must exist, else
        `ERR_REFERENCE_NOT_FOUND`."
        PRD §2.10: "fifth, existence of every body-referenced foreign key
        (`ERR_REFERENCE_NOT_FOUND`); ... fourteenth, room overlap
        (`ERR_ROOM_OVERLAP`)"

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_schedule_with_bad_room_and_overlap
        """
        env = setup_session_scenario(modality="IN_PERSON")
        resp = api.create_session(
            env.program["id"], env.group["id"],
            {"start_at": "2026-08-02T10:30:00Z", "end_at": "2026-08-02T11:30:00Z",
             "primary_facilitator_id": env.facilitator["id"],
             "room_id": NON_EXISTENT_UUID},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_true_room_overlap_rejected(self, api):
        """PRD §3.5: "The room rule treats each booking of the same room as a
        half-open interval: two sessions conflict unless one of them ends at or
        before the moment the other begins — so back-to-back sessions where one
        ends exactly when the next starts do not conflict — and any true
        overlap is rejected with `ERR_ROOM_OVERLAP` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_schedule_with_bad_room_and_overlap
        """
        env = setup_session_scenario(modality="IN_PERSON")
        second = make_certified_facilitator(env.reviewer["id"], full_name="F2")
        overlapping = make_session(
            env.program["id"], env.group["id"], second["id"],
            start_at="2026-08-02T10:30:00Z", end_at="2026-08-02T11:30:00Z",
            room_id=env.room["id"])
        version = get_facilitator_version(second["id"])
        resp = api.schedule_session(
            env.program["id"], env.group["id"], overlapping["id"],
            {"expected_facilitator_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROOM_OVERLAP)


class TestRoomOverlapHalfOpen:
    def _two_certified_facilitators(self):
        fac = setup_certified_facilitator()
        second = make_certified_facilitator(fac.reviewer["id"], full_name="F2")
        return fac.facilitator, second

    def test_adjacent_sessions_on_same_room_allowed(self, api):
        """PRD §3.5: "The room rule treats each booking of the same room as a
        half-open interval: two sessions conflict unless one of them ends at or
        before the moment the other begins — so back-to-back sessions where one
        ends exactly when the next starts do not conflict — and any true
        overlap is rejected with `ERR_ROOM_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/room_overlap_half_open_allows_adjacent_sessions
        """
        env = setup_program_with_active_group(modality="IN_PERSON")
        f1, f2 = self._two_certified_facilitators()
        make_scheduled_session(
            env.program["id"], env.group["id"], f1["id"],
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
            room_id=env.room["id"])
        # Adjacent at the boundary: existing end 11:00 == new start 11:00.
        adjacent = make_session(
            env.program["id"], env.group["id"], f2["id"],
            start_at="2026-08-02T11:00:00Z", end_at="2026-08-02T12:00:00Z",
            room_id=env.room["id"])
        scheduled = schedule_session(env.program["id"], env.group["id"], adjacent["id"])
        assert scheduled["status"] == "SCHEDULED", (
            "half-open interval semantics must allow back-to-back sessions")

    def test_overlapping_sessions_on_same_room_rejected(self, api):
        """PRD §3.5: "any true overlap is rejected with `ERR_ROOM_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/room_overlap_half_open_allows_adjacent_sessions
        """
        env = setup_program_with_active_group(modality="IN_PERSON")
        f1, f2 = self._two_certified_facilitators()
        make_scheduled_session(
            env.program["id"], env.group["id"], f1["id"],
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
            room_id=env.room["id"])
        overlapping = make_session(
            env.program["id"], env.group["id"], f2["id"],
            start_at="2026-08-02T10:30:00Z", end_at="2026-08-02T11:30:00Z",
            room_id=env.room["id"])
        version = get_facilitator_version(f2["id"])
        resp = api.schedule_session(
            env.program["id"], env.group["id"], overlapping["id"],
            {"expected_facilitator_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROOM_OVERLAP)


class TestFacilitatorBufferRule:
    def _setup_two_rooms(self):
        env = setup_program_with_active_group(modality="IN_PERSON")
        room_b = make_room(name="RB", physical_capacity=10)
        fac = setup_certified_facilitator()
        return env, room_b, fac.facilitator

    def test_twenty_minute_gap_rejected(self, api):
        """PRD §3.5: "The facilitator rule is stricter: a facilitator's
        occupied window extends thirty minutes before their session's start and
        thirty minutes after its end, for any existing session where they serve
        as primary or cofacilitator. A new session conflicts unless the
        existing session's end plus thirty minutes is at or before the new
        session's start, or the new session's end plus thirty minutes is at or
        before the existing session's start; a clash is rejected with
        `ERR_FACILITATOR_BUFFER_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/facilitator_buffer_thirty_min_blocks_20_min_gap
        """
        env, room_b, facilitator = self._setup_two_rooms()
        make_scheduled_session(
            env.program["id"], env.group["id"], facilitator["id"],
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
            room_id=env.room["id"])
        # 20-minute gap < 30-minute buffer: conflict even on a different room.
        too_close = make_session(
            env.program["id"], env.group["id"], facilitator["id"],
            start_at="2026-08-02T11:20:00Z", end_at="2026-08-02T12:20:00Z",
            room_id=room_b["id"])
        version = get_facilitator_version(facilitator["id"])
        resp = api.schedule_session(
            env.program["id"], env.group["id"], too_close["id"],
            {"expected_facilitator_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FACILITATOR_BUFFER_CONFLICT)

    def test_exact_thirty_minute_gap_allowed(self, api):
        """PRD §3.5: "A new session conflicts unless the existing session's end
        plus thirty minutes is at or before the new session's start, or the new
        session's end plus thirty minutes is at or before the existing
        session's start; a clash is rejected with
        `ERR_FACILITATOR_BUFFER_CONFLICT` (HTTP 409). Adjacency alone is not
        sufficient clearance for a facilitator, unlike rooms."

        Design: Difficulty/resource_temporal_overlap/facilitator_buffer_thirty_min_blocks_20_min_gap
        """
        env, room_b, facilitator = self._setup_two_rooms()
        make_scheduled_session(
            env.program["id"], env.group["id"], facilitator["id"],
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
            room_id=env.room["id"])
        # Exactly 30 minutes after the prior end: 11:00 + 30min <= 11:30.
        clear = make_session(
            env.program["id"], env.group["id"], facilitator["id"],
            start_at="2026-08-02T11:30:00Z", end_at="2026-08-02T12:30:00Z",
            room_id=room_b["id"])
        scheduled = schedule_session(env.program["id"], env.group["id"], clear["id"])
        assert scheduled["status"] == "SCHEDULED", (
            "an exact 30-minute gap satisfies 'end plus thirty minutes is at or "
            "before the new session's start'")


class TestScheduleDependsOnFacilitatorLevel:
    def test_level_below_requirement_rejected(self, api):
        """PRD §3.5: "the primary facilitator must be `CERTIFIED`, must hold a
        `level` of at least the group's `required_facilitator_level` (else
        `ERR_FACILITATOR_LEVEL_TOO_LOW`), and must have `supervision_required`
        false (else `ERR_SUPERVISION_REQUIRED`)"
        PRD §3.2: "the raw level is 1 plus the training points plus the
        supervision bonus, and the final `level` clamps that raw value into the
        range 1 to 5 inclusive."

        Design: Difficulty/cross_entity_state_dependency/session_schedule_depends_on_facilitator_certified_and_level
        """
        env = setup_program_with_active_group(
            modality="VIRTUAL", required_facilitator_level=3)
        reviewer, _ = make_bootstrap_reviewer()
        # Level 2: one passing completion on a level_weight-1 course, one
        # rating-4 review (bonus min(2, 1 // 2) = 0) -> level = 1 + 1 + 0 = 2.
        low_course = make_course(code="LVL-100", credit_hours=2, level_weight=1)
        facilitator = make_certified_facilitator(reviewer["id"], course=low_course)
        fetched = validate_success(api.get_facilitator(facilitator["id"], ADMIN))
        assert fetched["level"] == 2
        assert env.group["required_facilitator_level"] == 3

        session = make_session(
            env.program["id"], env.group["id"], facilitator["id"],
            start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:00:00Z")
        version = get_facilitator_version(facilitator["id"])
        resp = api.schedule_session(
            env.program["id"], env.group["id"], session["id"],
            {"expected_facilitator_version": version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FACILITATOR_LEVEL_TOO_LOW)

    def test_level_equal_to_requirement_succeeds(self, api):
        """PRD §3.5: "the primary facilitator must be `CERTIFIED`, must hold a
        `level` of at least the group's `required_facilitator_level`"
        PRD §3.5: "Scheduling moves a session from `DRAFT` to `SCHEDULED`"

        Design: Difficulty/cross_entity_state_dependency/session_schedule_depends_on_facilitator_certified_and_level
        """
        env = setup_program_with_active_group(
            modality="VIRTUAL", required_facilitator_level=2)
        reviewer, _ = make_bootstrap_reviewer()
        low_course = make_course(code="LVL-100", credit_hours=2, level_weight=1)
        facilitator = make_certified_facilitator(reviewer["id"], course=low_course)
        assert validate_success(
            api.get_facilitator(facilitator["id"], ADMIN))["level"] == 2

        session = make_session(
            env.program["id"], env.group["id"], facilitator["id"],
            start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:00:00Z")
        scheduled = schedule_session(env.program["id"], env.group["id"], session["id"])
        assert scheduled["status"] == "SCHEDULED", (
            "level exactly equal to required_facilitator_level satisfies 'at least'")


class TestScheduleOptimisticConcurrency:
    def test_schedule_with_stale_facilitator_version_rejected(self, api):
        """PRD §2.8: "Scheduling a session requires the request to carry
        `expected_facilitator_version`, the `version` of the designated primary
        facilitator as the client last observed it. If the facilitator's
        current `version` has advanced since that read — for example because
        another session was scheduled against the same facilitator, or the
        facilitator was suspended — the schedule request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "A successful schedule ... increments the primary
        facilitator's `version` by 1."

        Design: Corner/endpoints/session_schedule_occ_stale_facilitator_version
        """
        env = setup_program_with_active_group(modality="IN_PERSON")
        room_b = make_room(name="R2", physical_capacity=10)
        fac = setup_certified_facilitator()
        fid = fac.facilitator["id"]
        s1 = make_session(
            env.program["id"], env.group["id"], fid,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
            room_id=env.room["id"])
        s2 = make_session(
            env.program["id"], env.group["id"], fid,
            start_at="2026-08-04T10:00:00Z", end_at="2026-08-04T11:00:00Z",
            room_id=room_b["id"])
        stale_version = get_facilitator_version(fid)
        scheduled = schedule_session(env.program["id"], env.group["id"], s1["id"])
        assert scheduled["status"] == "SCHEDULED"

        resp = api.schedule_session(
            env.program["id"], env.group["id"], s2["id"],
            {"expected_facilitator_version": stale_version}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSessionCancellation:
    def test_cancel_completed_session_rejected(self, api):
        """PRD §3.5: "Cancellation by an admin works from either `DRAFT` or
        `SCHEDULED`."
        PRD §2.10: "A state-transition attempted from a state that does not
        permit it is always reported as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/session_cancel_from_completed_invalid
        """
        env = setup_session_scenario(modality="IN_PERSON")
        reset_clock("2026-08-02T11:30:00Z")
        completed = validate_success(api.complete_session(
            env.program["id"], env.group["id"], env.session["id"], ADMIN))
        assert completed["status"] == "COMPLETED"

        resp = api.cancel_session(env.program["id"], env.group["id"], env.session["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_session(env.program["id"], env.group["id"], env.session["id"], ADMIN))
        assert after["status"] == "COMPLETED"
