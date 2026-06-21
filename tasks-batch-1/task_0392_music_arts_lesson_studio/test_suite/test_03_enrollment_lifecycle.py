"""Enrollment matching, activation preconditions, the parallel status dimensions,
the freeze cascade, optimistic concurrency, and the activation validation precedence.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    create_invoice_payload,
    create_enrollment_payload,
    create_room_payload,
    create_student_payload,
    setup_roster,
    setup_active_enrollment,
    create_enrollment,
    activate_enrollment,
    create_occurrence,
)

ADMIN = TEST_USERS["studio_admin_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine / enrollment_parallel_lifecycle_x_billing
# ===========================================================================
class TestParallelLifecycleAndBilling:
    def test_freeze_leaves_billing_status_billed(self, api):
        """PRD 3.2: "These two status dimensions evolve independently:
        `lifecycle_status` tracks the matching and scheduling life of the enrollment,
        while `billing_status` tracks its invoicing state." PRD 3.2: "A freeze moves the
        enrollment `ACTIVE → FROZEN`".

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_lifecycle_x_billing
        """
        studio, family, student, instructor, room, enr = setup_active_enrollment()
        sid = studio["id"]
        get_success_data(
            api.create_invoice(sid, create_invoice_payload(enr["id"], "2026-01"), BILLING)
        )
        frozen = validate_success(api.freeze_enrollment(sid, enr["id"], ADMIN), 200)
        assert frozen["lifecycle_status"] == "FROZEN"
        assert frozen["billing_status"] == "BILLED"

    def test_invoice_issue_moves_billing_unbilled_to_billed(self, api):
        """PRD 3.3: "At issue the invoice's `status` is `ISSUED`, its `family_id` is
        derived from the enrollment, and the enrollment's `billing_status` moves
        `UNBILLED → BILLED`".

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_lifecycle_x_billing
        """
        studio, family, student, instructor, room, enr = setup_active_enrollment()
        sid = studio["id"]
        assert enr["billing_status"] == "UNBILLED"
        get_success_data(
            api.create_invoice(sid, create_invoice_payload(enr["id"], "2026-01"), BILLING)
        )
        after = validate_success(api.get_enrollment(sid, enr["id"], ADMIN), 200)
        assert after["billing_status"] == "BILLED"
        assert after["lifecycle_status"] == "ACTIVE"


# ===========================================================================
# Difficulty / transitive_cascade / freeze_cascade_occurrence_credit_discount
# ===========================================================================
class TestFreezeCascade:
    def _setup_two_active_with_future_occ(self, api):
        # Family with two ACTIVE enrollments (discount 0.05); e1 has a future occ.
        studio, family, student1, instructor, room1 = setup_roster(
            instructor_overrides={
                "instruments": ["PIANO"],
                "weekly_availability": [{"weekday": 0, "start_min": 540, "end_min": 1080}],
                "hourly_rate_cents": 6000,
            }
        )
        sid = studio["id"]
        student2 = get_success_data(api.create_student(sid, create_student_payload(family["id"]), ADMIN))
        room2 = get_success_data(api.create_room(sid, create_room_payload(room_name="R2", supported_instruments=["PIANO"]), ADMIN))
        e1 = create_enrollment(sid, student1["id"], instructor["id"], room1["id"], instrument="PIANO", weekday=0, start_min=540, duration_min=60)
        e1 = activate_enrollment(sid, e1)
        e2 = create_enrollment(sid, student2["id"], instructor["id"], room2["id"], instrument="PIANO", weekday=0, start_min=660, duration_min=60)
        e2 = activate_enrollment(sid, e2)
        occ = create_occurrence(sid, e1["id"], "2026-01-26T09:00:00.000Z")
        return sid, family, e1, occ

    def test_freeze_cancels_future_occurrence_and_mints_credit(self, api):
        """PRD 3.2: "first, every one of this enrollment's `SCHEDULED` lesson
        occurrences whose `scheduled_start_utc` is at or after the studio clock is moved
        to `CANCELLED_NOTICE`; second, each such cancelled occurrence mints one
        `OUTSTANDING` makeup credit for the enrollment, but only while the enrollment's
        outstanding-credit count remains below `makeup_credit_cap_per_enrollment`".

        Design: Difficulty/transitive_cascade/freeze_cascade_occurrence_credit_discount
        """
        sid, family, e1, occ = self._setup_two_active_with_future_occ(api)
        validate_success(api.freeze_enrollment(sid, e1["id"], ADMIN), 200)
        occ_after = validate_success(api.get_occurrence(sid, occ["id"], ADMIN), 200)
        assert occ_after["status"] == "CANCELLED_NOTICE"
        credits, meta = validate_paginated(
            api.list_makeup_credits(sid, ADMIN, params={"enrollment_id": e1["id"]})
        )
        assert meta["total_count"] == 1
        assert credits[0]["status"] == "OUTSTANDING"

    def test_freeze_drops_family_discount_via_recompute(self, api):
        """PRD 3.2: "third, because a `FROZEN` enrollment no longer counts as active, the
        family's `active_enrollment_count` and `family_discount_pct` are recomputed."
        PRD 3.4: "enrollments that are `FROZEN`, `PENDING_MATCH`, or `CANCELLED` do not
        count."

        Design: Difficulty/transitive_cascade/freeze_cascade_occurrence_credit_discount
        """
        sid, family, e1, occ = self._setup_two_active_with_future_occ(api)
        before = validate_success(api.get_family(sid, family["id"], ADMIN), 200)
        assert before["family_discount_pct"] == pytest.approx(0.05, abs=0.0001)
        validate_success(api.freeze_enrollment(sid, e1["id"], ADMIN), 200)
        after = validate_success(api.get_family(sid, family["id"], ADMIN), 200)
        assert after["active_enrollment_count"] == 1
        assert after["family_discount_pct"] == pytest.approx(0.0, abs=0.0001)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict /
#   state_vs_instructor_overlap_state_wins
# ===========================================================================
class TestStateOutranksInstructorOverlap:
    def _setup_cancelled_b_colliding_with_active_a(self, api):
        studio, family, s1, instructor, r1 = setup_roster(
            instructor_overrides={
                "instruments": ["PIANO"],
                "weekly_availability": [{"weekday": 0, "start_min": 540, "end_min": 720}],
                "hourly_rate_cents": 6000,
            }
        )
        sid = studio["id"]
        s2 = get_success_data(api.create_student(sid, create_student_payload(family["id"]), ADMIN))
        r2 = get_success_data(api.create_room(sid, create_room_payload(room_name="R2", supported_instruments=["PIANO"]), ADMIN))
        eA = create_enrollment(sid, s1["id"], instructor["id"], r1["id"], instrument="PIANO", weekday=0, start_min=540, duration_min=60)
        eA = activate_enrollment(sid, eA)
        eB = create_enrollment(sid, s2["id"], instructor["id"], r2["id"], instrument="PIANO", weekday=0, start_min=540, duration_min=60)
        validate_success(api.cancel_enrollment(sid, eB["id"], ADMIN), 200)
        eB_now = validate_success(api.get_enrollment(sid, eB["id"], ADMIN), 200)
        return sid, eB_now

    def test_activate_cancelled_enrollment_fails_state_not_overlap(self, api):
        """PRD 3.2: "Cancelling an enrollment is a `StudioAdmin` action permitted from
        `PENDING_MATCH`, `ACTIVE`, or `FROZEN` — any state other than `CANCELLED`, else
        `ERR_INVALID_STATE`." PRD 2.6: "This priority chain is global ... which outranks
        state and business checks." The state check (the enrollment is CANCELLED) is the
        first to fail, ahead of the instructor double-booking check.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_instructor_overlap_state_wins
        """
        sid, eB = self._setup_cancelled_b_colliding_with_active_a(api)
        res = api.activate_enrollment(
            sid, eB["id"], {"expected_enrollment_version": eB["version"]}, ADMIN
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_cancelled_enrollment_activation_never_reaches_overlap_branch(self, api):
        """PRD 3.2: "the activation-specific checks apply: family suspension, then the
        instructor-and-instrument capability match, then the room-and-instrument
        capability match, then availability, then instructor double-booking, then room
        double-booking" — but PRD 3.2 also gates activation on the lifecycle state, so a
        CANCELLED enrollment is rejected with `ERR_INVALID_STATE` before any of those.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_instructor_overlap_state_wins
        """
        sid, eB = self._setup_cancelled_b_colliding_with_active_a(api)
        res = api.activate_enrollment(
            sid, eB["id"], {"expected_enrollment_version": eB["version"]}, ADMIN
        )
        body = res.json()
        assert body["data"]["error_id"] == "ERR_INVALID_STATE"
        assert body["data"]["error_id"] != "ERR_INSTRUCTOR_DOUBLE_BOOKED"


# ===========================================================================
# Corner / cross_cutting_complexity_layers / occ_correct_version_then_stale_version_conflict
# ===========================================================================
def test_resume_with_stale_version_rejected(api):
    """PRD 2.7: "Resuming a frozen enrollment likewise requires
    `expected_enrollment_version` to match the enrollment's current `version`; if a
    cancel or a re-freeze has advanced the `version` since the client's last read, the
    resume is rejected with `ERR_STALE_VERSION` (HTTP 412) before the recurring slot is
    re-claimed."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_then_stale_version_conflict
    """
    studio, family, student, instructor, room = setup_roster()
    sid = studio["id"]
    enr = create_enrollment(sid, student["id"], instructor["id"], room["id"])
    v0 = enr["version"]
    activated = validate_success(
        api.activate_enrollment(sid, enr["id"], {"expected_enrollment_version": v0}, ADMIN), 200
    )
    # freeze advances version again; the client still holds the pre-activate v0.
    validate_success(api.freeze_enrollment(sid, enr["id"], ADMIN), 200)
    res = api.resume_enrollment(sid, enr["id"], {"expected_enrollment_version": v0}, ADMIN)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ===========================================================================
# Corner / state_machines / activate_already_active_enrollment_returns_invalid_state
# ===========================================================================
def test_activate_already_active_enrollment_returns_invalid_state(api):
    """PRD 3.2: "Freezing an enrollment is a `StudioAdmin` action permitted only while
    `lifecycle_status` is `ACTIVE`, else `ERR_INVALID_STATE` (HTTP 409)." The activate
    transition (PRD 3.2) runs from `PENDING_MATCH`; a second activate on an already-
    `ACTIVE` enrollment is not a valid transition and fails the state check.

    Design: Corner/state_machines/activate_already_active_enrollment_returns_invalid_state
    """
    studio, family, student, instructor, room, enr = setup_active_enrollment()
    sid = studio["id"]
    res = api.activate_enrollment(
        sid, enr["id"], {"expected_enrollment_version": enr["version"]}, ADMIN
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ===========================================================================
# Corner / state_machines / cancel_terminal_enrollment_returns_invalid_state
# ===========================================================================
def test_cancel_terminal_enrollment_returns_invalid_state(api):
    """PRD 3.2: "Cancelling an enrollment is a `StudioAdmin` action permitted from
    `PENDING_MATCH`, `ACTIVE`, or `FROZEN` — any state other than `CANCELLED`, else
    `ERR_INVALID_STATE`. Cancellation moves `lifecycle_status → CANCELLED` (a terminal
    state)".

    Design: Corner/state_machines/cancel_terminal_enrollment_returns_invalid_state
    """
    studio, family, student, instructor, room = setup_roster()
    sid = studio["id"]
    enr = create_enrollment(sid, student["id"], instructor["id"], room["id"])
    validate_success(api.cancel_enrollment(sid, enr["id"], ADMIN), 200)
    res = api.cancel_enrollment(sid, enr["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ===========================================================================
# Corner / validations / instructor_instrument_mismatch_rejected
# ===========================================================================
def test_instructor_instrument_mismatch_rejected(api):
    """PRD 3.2: "The instructor must be `ACTIVE` and must teach the enrollment's
    `instrument` (the value must appear in the instructor's `instruments`), or the
    result is `ERR_INSTRUCTOR_INSTRUMENT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/instructor_instrument_mismatch_rejected
    """
    studio, family, student, instructor, room = setup_roster(
        instructor_overrides={"instruments": ["PIANO"]},
        room_overrides={"supported_instruments": ["PIANO", "VIOLIN"]},
    )
    sid = studio["id"]
    enr = create_enrollment(sid, student["id"], instructor["id"], room["id"], instrument="VIOLIN")
    res = api.activate_enrollment(
        sid, enr["id"], {"expected_enrollment_version": enr["version"]}, ADMIN
    )
    validate_error(res, "ERR_INSTRUCTOR_INSTRUMENT_MISMATCH", expected_status=422)


# ===========================================================================
# Corner / validations / room_instrument_mismatch_rejected
# ===========================================================================
def test_room_instrument_mismatch_rejected(api):
    """PRD 3.2: "The room's `supported_instruments` must contain the `instrument`, or
    the result is `ERR_ROOM_INSTRUMENT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/room_instrument_mismatch_rejected
    """
    studio, family, student, instructor, room = setup_roster(
        instructor_overrides={"instruments": ["PIANO", "DRUMS"]},
        room_overrides={"supported_instruments": ["PIANO"]},
    )
    sid = studio["id"]
    enr = create_enrollment(sid, student["id"], instructor["id"], room["id"], instrument="DRUMS")
    res = api.activate_enrollment(
        sid, enr["id"], {"expected_enrollment_version": enr["version"]}, ADMIN
    )
    validate_error(res, "ERR_ROOM_INSTRUMENT_MISMATCH", expected_status=422)


# ===========================================================================
# Corner / validations / activate_outside_instructor_availability_rejected
# ===========================================================================
def test_activate_outside_instructor_availability_rejected(api):
    """PRD 3.2: "The recurring weekly window must lie entirely inside one of the
    instructor's `weekly_availability` windows for that `weekday`, or activation fails
    with `ERR_OUTSIDE_AVAILABILITY` (HTTP 409)."

    Design: Corner/validations/activate_outside_instructor_availability_rejected
    """
    studio, family, student, instructor, room = setup_roster(
        instructor_overrides={
            "instruments": ["PIANO"],
            "weekly_availability": [{"weekday": 0, "start_min": 600, "end_min": 720}],
        }
    )
    sid = studio["id"]
    # 08:00-09:00 lies outside the only Monday window 10:00-12:00.
    enr = create_enrollment(sid, student["id"], instructor["id"], room["id"], instrument="PIANO", weekday=0, start_min=480, duration_min=60)
    res = api.activate_enrollment(
        sid, enr["id"], {"expected_enrollment_version": enr["version"]}, ADMIN
    )
    validate_error(res, "ERR_OUTSIDE_AVAILABILITY", expected_status=409)


# ===========================================================================
# Corner / endpoints / filtered_list_enrollments_by_family
# ===========================================================================
def test_filtered_list_enrollments_by_family(api):
    """PRD 4: "enrollments [filtered] by `family_id`, `student_id`, `instructor_id`, and
    `room_id`". PRD 2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/filtered_list_enrollments_by_family
    """
    studio, family, student, instructor, room = setup_roster()
    sid = studio["id"]
    create_enrollment(sid, student["id"], instructor["id"], room["id"])
    res = api.list_enrollments(sid, ADMIN, params={"family_id": family["id"]})
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["total_count"] == 1
