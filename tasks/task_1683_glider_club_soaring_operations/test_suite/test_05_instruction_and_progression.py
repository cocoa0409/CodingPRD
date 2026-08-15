"""Student progression: signoff ownership and gates, the rework cycle,
badge-level recomputation, and the solo-eligibility recency window."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_student_progress,
    complete_flight,
    create_aircraft,
    create_availability,
    create_member,
    create_progress,
    create_tier,
    create_tow_slot,
    get_member,
    get_progress,
    make_instructor_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _setup_student_pair(tier_code="STUP", kind="BADGE_A"):
    """A student-tier member plus an instructor and a PENDING record."""
    tier = create_tier(tier_code=tier_code, monthly_dues_cents=0, student_tier=True)
    student = create_member(tier["id"], full_name="Student Pilot")
    instructor = create_member(tier["id"], full_name="CFI-G", is_instructor=True)
    record = create_progress(student["id"], instructor["id"], kind)
    return student, instructor, record


class TestReworkCycle:
    def test_return_for_rework_clears_signoff(self, api):
        """PRD §3.7: "A `ClubAdmin` who finds the paperwork wanting may instead
        return a `SIGNED_OFF` record for rework, moving it back to `PENDING`
        and clearing `signed_off_at` to null — the loop may repeat."
        PRD §3.7: "A successful signoff moves the record to `SIGNED_OFF`,
        snapshots the student's current dual-hour total into
        `dual_hours_at_signoff`, and stamps `signed_off_at`."

        Design: Difficulty/non_linear_state_machine/student_progress_rework_cycle
        """
        _, instructor, record = _setup_student_pair()
        resp = api.signoff_progress(record["id"], make_instructor_headers(instructor["id"]))
        signed = validate_success(resp, 200)
        assert signed["status"] == "SIGNED_OFF"
        assert signed["signed_off_at"] is not None

        resp = api.return_for_rework(record["id"], ADMIN)
        reworked = validate_success(resp, 200)
        assert reworked["status"] == "PENDING"
        assert reworked["signed_off_at"] is None, (
            "the rework edge clears the signoff stamp"
        )

    def test_rework_loop_completes_to_verified(self, api):
        """PRD §3.7: "A `ClubAdmin` who finds the paperwork wanting may instead
        return a `SIGNED_OFF` record for rework, moving it back to `PENDING`
        and clearing `signed_off_at` to null — the loop may repeat."
        PRD §3.7: "Verifying any badge kind recomputes the student's
        `badge_level` as the highest-ranked badge among their `VERIFIED`
        records, ranked `BADGE_A` below `BADGE_B` below `BADGE_C` below
        `BADGE_BRONZE` below `BADGE_SILVER` and surfacing as `A`, `B`, `C`,
        `BRONZE`, or `SILVER`".

        Design: Difficulty/non_linear_state_machine/student_progress_rework_cycle
        """
        student, instructor, record = _setup_student_pair()
        api.signoff_progress(record["id"], make_instructor_headers(instructor["id"]))
        api.return_for_rework(record["id"], ADMIN)
        resp = api.signoff_progress(record["id"], make_instructor_headers(instructor["id"]))
        resigned = validate_success(resp, 200)
        assert resigned["status"] == "SIGNED_OFF"
        assert resigned["signed_off_at"] is not None, "the second signoff re-stamps"

        resp = api.verify_progress(record["id"], ADMIN)
        verified = validate_success(resp, 200)
        assert_student_progress(verified)
        assert verified["status"] == "VERIFIED"
        assert get_member(student["id"])["badge_level"] == "A"


class TestSoloSignoffMemberGate:
    def _setup_suspended_student(self, api):
        tier = create_tier(tier_code="STU2", monthly_dues_cents=0, student_tier=True)
        student = create_member(tier["id"], full_name="Solo Student")
        instructor = create_member(tier["id"], full_name="Solo CFI", is_instructor=True)
        record = create_progress(student["id"], instructor["id"], "SOLO_SIGNOFF")
        resp = api.suspend_member(student["id"], ADMIN)
        validate_success(resp, 200)
        return student, instructor, record

    def test_solo_signoff_with_suspended_student_rejected(self, api):
        """PRD §3.7: "A `SOLO_SIGNOFF` adds the club's safety gate before it
        can be signed: the student must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`),
        their accumulated dual instruction — the sum of `flight_minutes`
        converted to hours across all of the student's `RECONCILED` flights
        that carried an instructor — must total at least 10.0 hours, and at
        least one of those dual flights must have a `takeoff_at` within the
        trailing 90 days."

        Design: Difficulty/cross_entity_state_dependency/solo_signoff_gated_by_member_status
        """
        _, instructor, record = self._setup_suspended_student(api)
        resp = api.signoff_progress(record["id"], make_instructor_headers(instructor["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

    def test_rejected_signoff_leaves_record_pending(self, api):
        """PRD §3.7: "Signoff belongs to the endorsing instructor alone: the
        acting instructor must be the record's `instructor_id`, or the attempt
        fails with `ERR_NOT_ENDORSING_INSTRUCTOR` (HTTP 403), and the record
        must still be `PENDING`, else `ERR_PROGRESS_NOT_PENDING`."
        PRD §2.11: "member-side standing — pilot, instructor, or crew must be
        `ACTIVE` for flight-side operations, a paying member must not be
        `RESIGNED`, a student must be `ACTIVE` at solo signoff
        (`ERR_MEMBER_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/solo_signoff_gated_by_member_status
        """
        student, instructor, record = self._setup_suspended_student(api)
        resp = api.signoff_progress(record["id"], make_instructor_headers(instructor["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        after = get_progress(record["id"])
        assert after["status"] == "PENDING"
        assert after["signed_off_at"] is None
        assert get_member(student["id"])["status"] == "SUSPENDED"


class TestVerifyAndBadges:
    def test_verify_requires_signed_off_state(self, api):
        """PRD §3.7: "A record must be `SIGNED_OFF` to verify — otherwise
        `ERR_PROGRESS_NOT_SIGNED_OFF`".

        Design: Corner/state_machines/verify_requires_signed_off_state
        """
        _, _, record = _setup_student_pair("SPV", "BADGE_B")
        resp = api.verify_progress(record["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRESS_NOT_SIGNED_OFF)
        assert get_progress(record["id"])["status"] == "PENDING"

    def test_badge_level_is_highest_verified(self, api):
        """PRD §3.7: "Verifying any badge kind recomputes the student's
        `badge_level` as the highest-ranked badge among their `VERIFIED`
        records, ranked `BADGE_A` below `BADGE_B` below `BADGE_C` below
        `BADGE_BRONZE` below `BADGE_SILVER` and surfacing as `A`, `B`, `C`,
        `BRONZE`, or `SILVER`; with no verified badges the level stays
        `NONE`."

        Design: Corner/calculations/badge_level_recompute_highest_verified
        """
        tier = create_tier(tier_code="BDG", monthly_dues_cents=0, student_tier=True)
        student = create_member(tier["id"], full_name="Badge Student")
        instructor = create_member(tier["id"], full_name="Badge CFI", is_instructor=True)

        for kind in ("BADGE_A", "BADGE_C"):
            record = create_progress(student["id"], instructor["id"], kind)
            api.signoff_progress(record["id"], make_instructor_headers(instructor["id"]))
            api.verify_progress(record["id"], ADMIN)
        # A merely-PENDING BADGE_SILVER is outside the VERIFIED input set.
        create_progress(student["id"], instructor["id"], "BADGE_SILVER")

        member = get_member(student["id"])
        assert member["badge_level"] == "C", (
            "highest VERIFIED badge wins; the PENDING BADGE_SILVER does not count"
        )


class TestSoloEligibilityRecency:
    def test_stale_dual_hours_fail_recency_window(self, api):
        """PRD §3.7: "their accumulated dual instruction — the sum of
        `flight_minutes` converted to hours across all of the student's
        `RECONCILED` flights that carried an instructor — must total at least
        10.0 hours, and at least one of those dual flights must have a
        `takeoff_at` within the trailing 90 days. Failing the hours or the
        recency leg rejects the signoff with `ERR_SOLO_ELIGIBILITY_FAILED`
        (HTTP 422)."

        Design: Corner/calculations/solo_eligibility_recency_window
        """
        tier = create_tier(
            tier_code="REC", monthly_dues_cents=0, included_tows_per_month=99,
            student_tier=True,
        )
        student = create_member(tier["id"], full_name="Recency Student")
        instructor = create_member(tier["id"], full_name="Recency CFI", is_instructor=True)
        tow_pilot = create_member(tier["id"], full_name="Recency Tow", is_tow_pilot=True)
        glider = create_aircraft("N009G", "GLIDER", "2027-01-01T00:00:00Z")
        tow_plane = create_aircraft("N010T", "TOW_PLANE", "2027-01-01T00:00:00Z")
        slot = create_tow_slot(
            tow_plane["id"], tow_pilot["id"],
            "2026-05-01T08:00:00Z", "2026-05-01T20:00:00Z", 10,
        )
        create_availability(
            instructor["id"], "2026-05-01T08:00:00Z", "2026-05-01T20:00:00Z"
        )
        # Three dual sorties totalling 770 minutes (12.83 h >= 10.0), all with
        # takeoffs on 2026-05-01.
        sorties = [
            ("2026-05-01T08:30:00Z", "2026-05-01T10:30:00Z",
             "2026-05-01T09:00:00Z", "2026-05-01T13:10:00Z", "2026-05-01T08:30:00Z"),
            ("2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z",
             "2026-05-01T14:00:00Z", "2026-05-01T18:10:00Z", "2026-05-01T13:50:00Z"),
            ("2026-05-01T18:30:00Z", "2026-05-01T20:00:00Z",
             "2026-05-01T18:30:00Z", "2026-05-01T23:00:00Z", "2026-05-01T18:20:00Z"),
        ]
        for res_start, res_end, takeoff, landed, clock in sorties:
            set_clock(clock)
            complete_flight(
                student["id"], glider["id"], slot["id"],
                res_start, res_end, takeoff, landed,
                instructor_id=instructor["id"],
                reconcile_officer_id=tow_pilot["id"],
            )
        # Jump past the 90-day recency window: 2026-08-30 is 121 days later.
        set_clock("2026-08-30T10:00:00Z")
        record = create_progress(student["id"], instructor["id"], "SOLO_SIGNOFF")
        resp = api.signoff_progress(record["id"], make_instructor_headers(instructor["id"]))
        validate_error(resp, ApiErrorId.ERR_SOLO_ELIGIBILITY_FAILED)
        assert get_progress(record["id"])["status"] == "PENDING"


class TestSignoffOwnership:
    def test_instructor_cannot_signoff_others_record(self, api):
        """PRD §3.7: "Signoff belongs to the endorsing instructor alone: the
        acting instructor must be the record's `instructor_id`, or the attempt
        fails with `ERR_NOT_ENDORSING_INSTRUCTOR` (HTTP 403)".

        Design: Corner/rbac/instructor_cannot_signoff_others_record
        """
        tier = create_tier(tier_code="RB2", monthly_dues_cents=0, student_tier=True)
        student = create_member(tier["id"], full_name="RB Student")
        cfi_a = create_member(tier["id"], full_name="CFI Alpha", is_instructor=True)
        cfi_b = create_member(tier["id"], full_name="CFI Beta", is_instructor=True)
        record = create_progress(student["id"], cfi_a["id"], "BADGE_A")

        resp = api.signoff_progress(record["id"], make_instructor_headers(cfi_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ENDORSING_INSTRUCTOR)
        assert get_progress(record["id"])["status"] == "PENDING"
