"""No-show cascade (queue A), training-session corners, shift overlap/duration/
check-in corners (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_volunteer, create_shift_payload, create_training_session_payload,
    set_clock, TEST_USERS, make_volunteer_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestNoshowStrikeCascade:
    def _four_shift_volunteer(self):
        v = make_volunteer(full_name="V NS", email="vn@x.org")
        ids = []
        for day in ("2026-08-02", "2026-08-03", "2026-08-04", "2026-08-20"):
            s = validate_success(
                api_client.create_shift(
                    create_shift_payload(
                        v["id"], shift_role="FLOOR",
                        scheduled_start=f"{day}T09:00:00Z",
                        scheduled_end=f"{day}T10:00:00Z",
                    ),
                    COORD,
                ),
                expected_status=201,
            )
            ids.append(s["id"])
        set_clock("2026-08-10T00:00:00Z")
        return v, ids

    def test_sweep_marks_past_due_shifts_no_show(self):
        """PRD §2.10: "marks past-due scheduled shifts as no-shows once the
        clock is at least 30 minutes past a shift's scheduled end (feeding the
        no-show strike cascade)" and "The checkpoint reports four counts in its
        response: `participants_expired`, `shifts_marked_no_show`,
        `sessions_marked_no_show`, and `memberships_expired`."

        Design: Difficulty/transitive_cascade/noshow_strike_suspends_and_cancels
        """
        v, ids = self._four_shift_volunteer()
        sweep = validate_success(api_client.run_sweep(COORD))
        assert sweep["shifts_marked_no_show"] == 3
        assert sweep["participants_expired"] == 0
        assert sweep["sessions_marked_no_show"] == 0
        assert sweep["memberships_expired"] == 0
        for sid in ids[:3]:
            sh = validate_success(api_client.get_shift(sid, COORD))
            assert sh["status"] == "NO_SHOW"

    def test_third_strike_suspends_and_cancels_remaining(self):
        """PRD §3.5: "When the count reaches 3 — the third strike suspends — the
        volunteer's `engagement_status` flips to `SUSPENDED` and every remaining
        `SCHEDULED` shift of that volunteer is cancelled."

        Design: Difficulty/transitive_cascade/noshow_strike_suspends_and_cancels
        """
        v, ids = self._four_shift_volunteer()
        validate_success(api_client.run_sweep(COORD))
        v_after = validate_success(api_client.get_volunteer(v["id"], COORD))
        assert v_after["no_show_count"] == 3
        assert v_after["engagement_status"] == "SUSPENDED"
        future = validate_success(api_client.get_shift(ids[3], COORD))
        assert future["status"] == "CANCELLED"


class TestTrainingCorners:
    def test_training_cancel_drops_attendances(self):
        """PRD §3.5: "Cancelling a scheduled session instead drops every
        enrolled attendance to `DROPPED` and bumps the session's `version`."
        and PRD §2.7: "`ERR_INVALID_STATE` when no more specific code applies".

        Design: Corner/state_machines/training_cancel_drops_attendances
        """
        v = make_volunteer(full_name="V T", email="vt@x.org")
        s = validate_success(
            api_client.create_training_session(
                create_training_session_payload(
                    topic="Derailleur 101",
                    scheduled_start="2026-08-02T10:00:00Z",
                    scheduled_end="2026-08-02T11:00:00Z",
                    credit_hours=4, capacity=5,
                ),
                COORD,
            ),
            expected_status=201,
        )
        a = validate_success(
            api_client.enroll_in_session(s["id"], {"volunteer_id": v["id"]}, COORD),
            expected_status=201,
        )
        cancelled = validate_success(api_client.cancel_training_session(s["id"], COORD))
        assert cancelled["status"] == "CANCELLED"
        a_after = validate_success(api_client.get_attendance(a["id"], COORD))
        assert a_after["status"] == "DROPPED"
        r = api_client.complete_training_session(
            s["id"], {"marks": [{"attendance_id": a["id"], "outcome": "ATTENDED"}]}, COORD
        )
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        v_after = validate_success(api_client.get_volunteer(v["id"], COORD))
        assert v_after["training_hours"] == 0

    def test_duplicate_enrollment_and_capacity(self):
        """PRD §3.5: "one attendance row per (session, volunteer) pair — a
        second enrollment of the same volunteer in the same session is rejected
        with `ERR_ALREADY_ENROLLED` — and only while `enrolled_count` remains
        below `capacity`; an enrollment into a full session is rejected with
        `ERR_TRAINING_FULL`."

        Design: Corner/validations/duplicate_enrollment_and_capacity
        """
        v1 = make_volunteer(full_name="V 1", email="v1@x.org")
        v2 = make_volunteer(full_name="V 2", email="v2@x.org")
        s = validate_success(
            api_client.create_training_session(
                create_training_session_payload(
                    topic="Wheel true", level="ADVANCED",
                    scheduled_start="2026-08-02T10:00:00Z",
                    scheduled_end="2026-08-02T11:00:00Z",
                    credit_hours=2, capacity=1,
                ),
                COORD,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.enroll_in_session(s["id"], {"volunteer_id": v1["id"]}, COORD),
            expected_status=201,
        )
        r_dup = api_client.enroll_in_session(s["id"], {"volunteer_id": v1["id"]}, COORD)
        validate_error(r_dup, ApiErrorId.ERR_ALREADY_ENROLLED)
        r_full = api_client.enroll_in_session(s["id"], {"volunteer_id": v2["id"]}, COORD)
        validate_error(r_full, ApiErrorId.ERR_TRAINING_FULL)
        s_after = validate_success(api_client.get_training_session(s["id"], COORD))
        assert s_after["enrolled_count"] == 1

    def test_marks_incomplete_on_session_complete(self):
        """PRD §3.5: "the completion must mark every enrolled attendance exactly
        once, each as `ATTENDED` or `NO_SHOW`, via the `marks` payload; missing
        or duplicate marks are rejected with
        `ERR_ATTENDANCE_MARKS_INCOMPLETE`."

        Design: Corner/validations/marks_incomplete_on_session_complete
        """
        v1 = make_volunteer(full_name="V 1", email="v1@x.org")
        v2 = make_volunteer(full_name="V 2", email="v2@x.org")
        s = validate_success(
            api_client.create_training_session(
                create_training_session_payload(
                    topic="Brakes", scheduled_start="2026-08-02T10:00:00Z",
                    scheduled_end="2026-08-02T11:00:00Z", credit_hours=3,
                    capacity=5,
                ),
                COORD,
            ),
            expected_status=201,
        )
        a1 = validate_success(
            api_client.enroll_in_session(s["id"], {"volunteer_id": v1["id"]}, COORD),
            expected_status=201,
        )
        a2 = validate_success(
            api_client.enroll_in_session(s["id"], {"volunteer_id": v2["id"]}, COORD),
            expected_status=201,
        )
        set_clock("2026-08-07T00:00:00Z")
        r = api_client.complete_training_session(
            s["id"], {"marks": [{"attendance_id": a1["id"], "outcome": "ATTENDED"}]},
            COORD,
        )
        validate_error(r, ApiErrorId.ERR_ATTENDANCE_MARKS_INCOMPLETE)
        s_after = validate_success(api_client.get_training_session(s["id"], COORD))
        assert s_after["status"] == "SCHEDULED"
        a1_after = validate_success(api_client.get_attendance(a1["id"], COORD))
        a2_after = validate_success(api_client.get_attendance(a2["id"], COORD))
        assert a1_after["status"] == "ENROLLED"
        assert a2_after["status"] == "ENROLLED"

    def test_session_complete_before_end_returns_session_not_ended(self):
        """PRD §3.5: "A coordinator may complete a session only once the logical
        clock has reached its `scheduled_end` — completing early is rejected
        with `ERR_SESSION_NOT_ENDED`".

        Design: Corner/validations/session_complete_before_end_returns_session_not_ended
        """
        v = make_volunteer(full_name="V NE", email="vne@x.org")
        s = validate_success(
            api_client.create_training_session(
                create_training_session_payload(
                    topic="Early", scheduled_start="2026-08-02T10:00:00Z",
                    scheduled_end="2026-08-02T11:00:00Z", credit_hours=2,
                    capacity=5,
                ),
                COORD,
            ),
            expected_status=201,
        )
        a1 = validate_success(
            api_client.enroll_in_session(s["id"], {"volunteer_id": v["id"]}, COORD),
            expected_status=201,
        )
        # clock still at default 2026-08-01
        r = api_client.complete_training_session(
            s["id"], {"marks": [{"attendance_id": a1["id"], "outcome": "ATTENDED"}]},
            COORD,
        )
        validate_error(r, ApiErrorId.ERR_SESSION_NOT_ENDED)
        s_after = validate_success(api_client.get_training_session(s["id"], COORD))
        assert s_after["status"] == "SCHEDULED"
        v_after = validate_success(api_client.get_volunteer(v["id"], COORD))
        assert v_after["training_hours"] == 0


class TestShiftOverlap:
    def test_shift_overlap_half_open_adjacency(self):
        """PRD §3.6: "Overlap is policed per volunteer under half-open interval
        semantics: the new shift's span must not intersect any existing
        `SCHEDULED` or `CHECKED_IN` shift of the same volunteer, but two shifts
        that merely touch — one ending exactly when the other begins — are
        allowed. An intersecting booking is rejected with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_adjacency
        """
        v = make_volunteer(full_name="V O", email="vo@x.org")
        validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], scheduled_start="2026-08-10T09:00:00Z",
                    scheduled_end="2026-08-10T12:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        r = api_client.create_shift(
            create_shift_payload(
                v["id"], shift_role="INTAKE",
                scheduled_start="2026-08-10T11:00:00Z",
                scheduled_end="2026-08-10T13:00:00Z",
            ),
            COORD,
        )
        validate_error(r, ApiErrorId.ERR_SHIFT_OVERLAP)
        ok = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], shift_role="INTAKE",
                    scheduled_start="2026-08-10T12:00:00Z",
                    scheduled_end="2026-08-10T15:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        assert ok["status"] == "SCHEDULED"

    def test_shift_overlap_checked_in_blocks_but_cancelled_frees(self):
        """PRD §3.6: "Overlap is policed per volunteer under half-open interval
        semantics: the new shift's span must not intersect any existing
        `SCHEDULED` or `CHECKED_IN` shift of the same volunteer, but two shifts
        that merely touch — one ending exactly when the other begins — are
        allowed. An intersecting booking is rejected with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_adjacency
        """
        v = make_volunteer(full_name="V O2", email="vo2@x.org")
        base = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], scheduled_start="2026-08-10T09:00:00Z",
                    scheduled_end="2026-08-10T12:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        # fully-contained 10:00-11:00 overlaps the SCHEDULED 09:00-12:00
        r = api_client.create_shift(
            create_shift_payload(
                v["id"], shift_role="INTAKE",
                scheduled_start="2026-08-10T10:00:00Z",
                scheduled_end="2026-08-10T11:00:00Z",
            ),
            COORD,
        )
        validate_error(r, ApiErrorId.ERR_SHIFT_OVERLAP)
        # after cancelling the original, the same span is free
        validate_success(api_client.cancel_shift(base["id"], COORD))
        ok = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], shift_role="INTAKE",
                    scheduled_start="2026-08-10T10:00:00Z",
                    scheduled_end="2026-08-10T11:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        assert ok["status"] == "SCHEDULED"

    def test_shift_duration_bounds(self):
        """PRD §3.6: "The shift's duration must fall between 30 and 480 minutes
        inclusive, else `ERR_SHIFT_DURATION_INVALID`".

        Design: Corner/validations/shift_duration_bounds
        """
        v = make_volunteer(full_name="V D", email="vd@x.org")
        r20 = api_client.create_shift(
            create_shift_payload(
                v["id"], shift_role="FLOOR",
                scheduled_start="2026-08-10T09:00:00Z",
                scheduled_end="2026-08-10T09:20:00Z",
            ),
            COORD,
        )
        validate_error(r20, ApiErrorId.ERR_SHIFT_DURATION_INVALID)
        r481 = api_client.create_shift(
            create_shift_payload(
                v["id"], shift_role="FLOOR",
                scheduled_start="2026-08-11T09:00:00Z",
                scheduled_end="2026-08-11T17:01:00Z",
            ),
            COORD,
        )
        validate_error(r481, ApiErrorId.ERR_SHIFT_DURATION_INVALID)
        ok30 = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], shift_role="FLOOR",
                    scheduled_start="2026-08-12T09:00:00Z",
                    scheduled_end="2026-08-12T09:30:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        assert ok30["status"] == "SCHEDULED"
        ok480 = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], shift_role="FLOOR",
                    scheduled_start="2026-08-13T09:00:00Z",
                    scheduled_end="2026-08-13T17:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        assert ok480["status"] == "SCHEDULED"

    def test_shift_checkin_window_and_credit(self):
        """PRD §3.6: "the logical clock must fall within the check-in window —
        from 15 minutes before `scheduled_start` through `scheduled_end` — else
        `ERR_CHECKIN_WINDOW_CLOSED`." and "Completion stamps `credited_minutes`
        as the scheduled duration in whole minutes, capped at 480 — a shift
        scheduled longer than eight hours still credits exactly 480 — and adds
        those minutes to the volunteer's `shift_minutes`."

        Design: Corner/state_machines/shift_checkin_window_and_credit
        """
        v = make_volunteer(full_name="V CK", email="vck@x.org")
        sh = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], scheduled_start="2026-08-10T10:00:00Z",
                    scheduled_end="2026-08-10T12:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        set_clock("2026-08-10T09:44:00Z")
        r = api_client.check_in_shift(sh["id"], make_volunteer_headers(v["id"]))
        validate_error(r, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)
        set_clock("2026-08-10T09:45:00Z")
        checked = validate_success(
            api_client.check_in_shift(sh["id"], make_volunteer_headers(v["id"]))
        )
        assert checked["status"] == "CHECKED_IN"
        done = validate_success(api_client.complete_shift(sh["id"], COORD))
        assert done["status"] == "COMPLETED"
        assert done["credited_minutes"] == 120
        v_after = validate_success(api_client.get_volunteer(v["id"], COORD))
        assert v_after["shift_minutes"] == 120

    def test_volunteer_checkin_other_shift_rejected(self):
        """PRD §3.6: "Check-in belongs to the owning volunteer alone: the
        caller's `X-User-ID` must equal the shift's `volunteer_id`, else
        `ERR_NOT_YOUR_SHIFT`."

        Design: Corner/rbac/volunteer_checkin_other_shift_rejected
        """
        va = make_volunteer(full_name="V A", email="va@x.org")
        vb = make_volunteer(full_name="V B", email="vb@x.org")
        sh = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    vb["id"], scheduled_start="2026-08-10T10:00:00Z",
                    scheduled_end="2026-08-10T12:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        set_clock("2026-08-10T10:00:00Z")
        r = api_client.check_in_shift(sh["id"], make_volunteer_headers(va["id"]))
        validate_error(r, ApiErrorId.ERR_NOT_YOUR_SHIFT)
        sh_after = validate_success(api_client.get_shift(sh["id"], COORD))
        assert sh_after["status"] == "SCHEDULED"
