"""Dorm/room/assignment lifecycle, occupancy counters, roommate matching, OCC."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_dorm, assert_room, assert_dorm_assignment,
    create_dorm_assignment_payload,
    make_student_headers,
    make_dorm, make_room, make_term, make_active_term, make_parent,
    make_student, make_domestic_student, get_student,
    propose_assignment, confirm_assignment, setup_confirmed_residency,
)


def _setup_dorm_with_confirmed_and_proposed():
    """Dorm with one 2-bed room; student A CONFIRMED, student B PROPOSED."""
    dorm = make_dorm(name="Winslow House")
    room = make_room(dorm["id"], room_number="W-101", beds=2)
    term = make_active_term()
    stu_a = make_domestic_student(grade=10, gender="MALE", legal_name="Stu A")
    stu_b = make_domestic_student(grade=10, gender="FEMALE", legal_name="Stu B")
    asg_a = propose_assignment(stu_a["id"], room["id"], term["id"])
    confirm_assignment(asg_a["id"])
    asg_b = propose_assignment(stu_b["id"], room["id"], term["id"])
    return dorm, room, term, stu_a, stu_b, asg_a, asg_b


class TestOccupancyDualVariants:
    def test_occupancy_physical_vs_projected(self, api, admin_headers):
        """PRD §3.1: "`occupancy_physical` counts `CONFIRMED` assignments in the
        dorm's rooms; `occupancy_projected` adds the `PROPOSED` ones on top of
        physical, so it reads strictly higher whenever proposals are pending".

        Design: Difficulty/dual_variant_calc/bed_utilization_physical_vs_projected
        """
        dorm, room, term, stu_a, stu_b, asg_a, asg_b = \
            _setup_dorm_with_confirmed_and_proposed()
        fetched = validate_success(api.get_dorm(dorm["id"], admin_headers), 200)
        assert_dorm(fetched)
        assert fetched["occupancy_physical"] == 1
        assert fetched["occupancy_projected"] == 2

    def test_beds_total_and_beds_available_with_pending_proposal(self, api, admin_headers):
        """PRD §3.1: "the dorm-level `beds_total` sums `beds` across all its rooms"
        and "`beds_available` is `beds_total` minus `occupancy_physical`".

        Design: Difficulty/dual_variant_calc/bed_utilization_physical_vs_projected
        """
        dorm, room, term, stu_a, stu_b, asg_a, asg_b = \
            _setup_dorm_with_confirmed_and_proposed()
        fetched = validate_success(api.get_dorm(dorm["id"], admin_headers), 200)
        assert fetched["beds_total"] == 2
        assert fetched["beds_available"] == 1


def _setup_linked_roommates():
    """Two students CONFIRMED as linked roommates in a 2-bed room; ACTIVE term.

    Questionnaire A (5,4,5,3), B (2,4,1,3) -> compatibility 32 (PRD §3.3).
    """
    from test_helpers import api_client, TEST_USERS
    dorm = make_dorm(name="Lowell House")
    room = make_room(dorm["id"], room_number="L-201", beds=2)
    term = make_active_term()
    stu_a = make_domestic_student(grade=11, gender="MALE", legal_name="Stu J",
                                  sleep_schedule=5, cleanliness=4,
                                  noise_tolerance=5, guests_comfort=3)
    stu_b = make_domestic_student(grade=11, gender="MALE", legal_name="Stu K",
                                  sleep_schedule=2, cleanliness=4,
                                  noise_tolerance=1, guests_comfort=3)
    asg_a = propose_assignment(stu_a["id"], room["id"], term["id"])
    asg_b = propose_assignment(stu_b["id"], room["id"], term["id"])
    get_success_data(api_client.link_roommate(asg_a["id"], asg_b["id"],
                                              TEST_USERS["admin_headers"]))
    confirm_assignment(asg_a["id"])
    confirm_assignment(asg_b["id"])
    return dorm, room, term, stu_a, stu_b, asg_a, asg_b


class TestTermCloseCascade:
    def test_term_close_ends_assignments_and_stamps_checkout(self, api, admin_headers):
        """PRD §3.1: "Closing the active term is the year's big cascade. Every
        `CONFIRMED` assignment in that term moves to `ENDED` with `check_out_at`
        stamped to the current logical instant; every `PROPOSED` assignment moves
        to `SUPERSEDED`."
        PRD §3.3: "The compatibility score starts from 100 and subtracts weighted
        questionnaire distances: twelve points per unit of difference in
        `sleep_schedule`, eight per unit of difference in `cleanliness`, eight per
        unit of difference in `noise_tolerance`, and four per unit of difference
        in `guests_comfort`; the result floors at 0."

        Design: Difficulty/transitive_cascade/term_close_cascades_assignment_roommate_room
        """
        dorm, room, term, stu_a, stu_b, asg_a, asg_b = _setup_linked_roommates()
        pre = validate_success(api.get_dorm_assignment(asg_a["id"], admin_headers), 200)
        assert pre["compatibility_score"] == 32, \
            "100 - 12*|5-2| - 8*|4-4| - 8*|5-1| - 4*|3-3| = 32"
        assert pre["roommate_assignment_id"] == asg_b["id"]

        validate_success(api.close_term(term["id"], admin_headers), 200)

        a = validate_success(api.get_dorm_assignment(asg_a["id"], admin_headers), 200)
        b = validate_success(api.get_dorm_assignment(asg_b["id"], admin_headers), 200)
        assert a["status"] == "ENDED" and a["check_out_at"] is not None
        assert b["status"] == "ENDED" and b["check_out_at"] is not None

    def test_term_close_clears_roommate_links_and_refreshes_room(self, api, admin_headers):
        """PRD §3.1: "Each ended assignment clears the mutual roommate link — the
        partner assignment's `roommate_assignment_id` and `compatibility_score`
        both reset to null. Each affected room recomputes `beds_assigned` and
        `beds_available`, and a `FULL` room whose confirmed count drops below its
        capacity flips itself back to `AVAILABLE`."

        Design: Difficulty/transitive_cascade/term_close_cascades_assignment_roommate_room
        """
        dorm, room, term, stu_a, stu_b, asg_a, asg_b = _setup_linked_roommates()
        room_mid = validate_success(api.get_room(room["id"], admin_headers), 200)
        assert room_mid["status"] == "FULL"

        validate_success(api.close_term(term["id"], admin_headers), 200)

        a = validate_success(api.get_dorm_assignment(asg_a["id"], admin_headers), 200)
        b = validate_success(api.get_dorm_assignment(asg_b["id"], admin_headers), 200)
        assert a["roommate_assignment_id"] is None and a["compatibility_score"] is None
        assert b["roommate_assignment_id"] is None and b["compatibility_score"] is None

        room_after = validate_success(api.get_room(room["id"], admin_headers), 200)
        assert room_after["beds_assigned"] == 0
        assert room_after["status"] == "AVAILABLE"


class TestRoommateMatching:
    def test_questionnaire_patch_recomputes_compatibility_on_both_sides(self, api, admin_headers):
        """PRD §3.2: "Updating a student's `grade` or any questionnaire field is
        an administrator action that recomputes downstream values: a `grade`
        change refreshes `weekend_leave_allowance`, and any questionnaire change
        recomputes the `compatibility_score` stored on both sides of a linked
        assignment pair."

        Design: Corner/entities/questionnaire_patch_recomputes_compatibility
        """
        dorm, room, term, stu_a, stu_b, asg_a, asg_b = _setup_linked_roommates()
        pre = validate_success(api.get_dorm_assignment(asg_a["id"], admin_headers), 200)
        assert pre["compatibility_score"] == 32

        validate_success(api.patch_student(stu_a["id"], {"sleep_schedule": 2},
                                           admin_headers), 200)

        a = validate_success(api.get_dorm_assignment(asg_a["id"], admin_headers), 200)
        b = validate_success(api.get_dorm_assignment(asg_b["id"], admin_headers), 200)
        # 100 - 12*|2-2| - 8*|4-4| - 8*|5-1| - 4*|3-3| = 68
        assert a["compatibility_score"] == 68
        assert b["compatibility_score"] == 68

    def test_self_roommate_rejected(self, api, admin_headers):
        """PRD §3.3: "the link target must belong to a different student
        (`ERR_SELF_ROOMMATE`)".

        Design: Corner/validations/self_roommate_rejected
        """
        dorm = make_dorm()
        room = make_room(dorm["id"], beds=2)
        term = make_active_term()
        student = make_domestic_student(grade=10, gender="MALE", legal_name="Stu F")
        asg = propose_assignment(student["id"], room["id"], term["id"])

        res = api.link_roommate(asg["id"], asg["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_SELF_ROOMMATE)

    def test_roommate_in_other_room_rejected(self, api, admin_headers):
        """PRD §3.3: "must sit in the same room and same term, and must be
        `PROPOSED` or `CONFIRMED` (`ERR_ROOMMATE_NOT_IN_ROOM`)".

        Design: Corner/validations/roommate_other_room_rejected
        """
        dorm = make_dorm()
        room1 = make_room(dorm["id"], room_number="W-101", beds=2)
        room2 = make_room(dorm["id"], room_number="W-102", beds=2)
        term = make_active_term()
        stu_a = make_domestic_student(grade=10, gender="MALE", legal_name="Stu G")
        stu_b = make_domestic_student(grade=10, gender="MALE", legal_name="Stu H")
        asg_a = propose_assignment(stu_a["id"], room1["id"], term["id"])
        asg_b = propose_assignment(stu_b["id"], room2["id"], term["id"])

        res = api.link_roommate(asg_a["id"], asg_b["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_ROOMMATE_NOT_IN_ROOM)


class TestConfirmGates:
    def test_gender_mismatch_confirm_rejected(self, api, admin_headers):
        """PRD §3.3: "the dorm's `gender_policy` must accept the student's gender,
        where `ANY` accepts everyone, `MALE_ONLY` accepts `MALE`, and
        `FEMALE_ONLY` accepts `FEMALE` (`ERR_DORM_GENDER_MISMATCH`)".

        Design: Corner/validations/gender_mismatch_confirm_rejected
        """
        dorm = make_dorm(name="Cutter House", gender_policy="FEMALE_ONLY")
        room = make_room(dorm["id"], room_number="C-101", beds=2)
        term = make_active_term()
        stu_m = make_domestic_student(grade=10, gender="MALE", legal_name="Stu M")
        stu_f = make_domestic_student(grade=10, gender="FEMALE", legal_name="Stu F")
        asg_m = propose_assignment(stu_m["id"], room["id"], term["id"])
        asg_f = propose_assignment(stu_f["id"], room["id"], term["id"])

        res = api.confirm_dorm_assignment(asg_m["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_DORM_GENDER_MISMATCH)

        ok = validate_success(api.confirm_dorm_assignment(asg_f["id"], admin_headers), 200)
        assert ok["status"] == "CONFIRMED"

    def test_room_full_second_confirm_rejected(self, api, admin_headers):
        """PRD §3.3: "must have at least one bed free — a `FULL` room fails only
        the fiscal bed check with `ERR_ROOM_FULL`".
        PRD §3.1: "a confirm that raises `beds_assigned` to equal `beds` flips the
        room from `AVAILABLE` to `FULL`".

        Design: Corner/validations/room_full_second_confirm_rejected
        """
        dorm = make_dorm()
        room = make_room(dorm["id"], room_number="W-103", beds=1)
        term = make_active_term()
        stu_a = make_domestic_student(grade=10, gender="MALE", legal_name="Stu M")
        stu_b = make_domestic_student(grade=10, gender="FEMALE", legal_name="Stu N")
        asg_a = propose_assignment(stu_a["id"], room["id"], term["id"])
        confirm_assignment(asg_a["id"])
        asg_b = propose_assignment(stu_b["id"], room["id"], term["id"])

        res = api.confirm_dorm_assignment(asg_b["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_ROOM_FULL)

        room_after = validate_success(api.get_room(room["id"], admin_headers), 200)
        assert room_after["status"] == "FULL"
        assert room_after["beds_available"] == 0

    def test_dorm_closed_for_break_blocks_confirm(self, api, admin_headers):
        """PRD §3.1: "A closed-for-break dorm refuses new assignment confirmations
        and refuses ordinary sign-ins — the exception being students holding an
        `APPROVED` or `CHECKED_IN` break-housing request — while night checks
        remain allowed; violations surface as `ERR_DORM_CLOSED`."
        PRD §3.1: "When a break period is `ACTIVE`, an administrator may close a
        dorm for break, moving its posture to `CLOSED_FOR_BREAK`".

        Design: Corner/validations/dorm_closed_blocks_confirm
        """
        from test_helpers import make_break_period, set_clock
        dorm = make_dorm()
        room = make_room(dorm["id"], room_number="W-101", beds=2)
        term = make_active_term()
        student = make_domestic_student(grade=10, gender="MALE", legal_name="Stu V")
        asg = propose_assignment(student["id"], room["id"], term["id"])
        make_break_period()
        set_clock("2026-11-25T00:00:00Z")  # sweeps the break to ACTIVE
        validate_success(api.close_dorm_for_break(dorm["id"], admin_headers), 200)

        res = api.confirm_dorm_assignment(asg["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_DORM_CLOSED)


class TestRoomAndEnrollmentGuards:
    def test_block_occupied_room_rejected(self, api, admin_headers):
        """PRD §3.1: "An administrator may block an empty room for maintenance —
        attempting to block a room with any occupant is rejected with
        `ERR_ROOM_OCCUPIED` — and unblock it later."

        Design: Corner/state_machines/room_block_occupied_returns_room_occupied
        """
        ctx = setup_confirmed_residency(grade=10, with_dorm_parent=False)
        res = api.block_room(ctx["room"]["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_ROOM_OCCUPIED)

    def test_graduate_with_confirmed_assignment_rejected(self, api, admin_headers):
        """PRD §3.2: "Graduation requires that the student hold no `CONFIRMED`
        assignment in the active term — the residence must be ended first, for
        example by term close — otherwise `ERR_ACTIVE_ASSIGNMENT_EXISTS`."

        Design: Corner/validations/graduate_with_confirmed_assignment_rejected
        """
        ctx = setup_confirmed_residency(grade=12, gender="FEMALE",
                                        with_dorm_parent=False)
        res = api.set_student_enrollment(ctx["student"]["id"], "GRADUATED", admin_headers)
        validate_error(res, ApiErrorId.ERR_ACTIVE_ASSIGNMENT_EXISTS)

        validate_success(api.end_dorm_assignment(ctx["assignment"]["id"], admin_headers), 200)
        ok = validate_success(
            api.set_student_enrollment(ctx["student"]["id"], "GRADUATED", admin_headers), 200)
        assert ok["enrollment_status"] == "GRADUATED"

    def test_second_term_activation_rejected(self, api, admin_headers):
        """PRD §3.1: "Activating a term moves it to `ACTIVE` and is refused with
        `ERR_ACTIVE_TERM_EXISTS` while any other term is already `ACTIVE` — the
        school runs exactly one term at a time."

        Design: Corner/validations/second_term_activation_rejected
        """
        term_a = make_active_term(name="FALL_2026", starts_on="2026-08-24",
                                  ends_on="2026-12-18")
        term_b = make_term(name="SPRING_2027", starts_on="2027-01-11",
                           ends_on="2027-05-28")
        res = api.activate_term(term_b["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_ACTIVE_TERM_EXISTS)


class TestOptimisticConcurrency:
    def test_assignment_create_with_stale_student_version_rejected(self, api, admin_headers):
        """PRD §2.7: "Creating a dorm assignment requires `expected_student_version`,
        matching the target student's current `version`." and "a mismatch with the
        parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/assignment_create_stale_student_version_occ
        """
        dorm = make_dorm()
        room = make_room(dorm["id"], room_number="W-101", beds=2)
        term = make_active_term()
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="MALE",
                               legal_name="Stu AI")
        payload = create_dorm_assignment_payload(
            student["id"], room["id"], term["id"], student["version"])
        asg_a = validate_success(api.create_dorm_assignment(payload, admin_headers), 201)
        assert_dorm_assignment(asg_a)

        # Same stale version again -> rejected.
        res = api.create_dorm_assignment(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_assignment_create_with_fresh_version_supersedes_prior_proposal(self, api, admin_headers):
        """PRD §3.3: "Creating a new assignment for a student who already has a
        `PROPOSED` assignment in the same term supersedes the old one — the
        earlier proposal moves to `SUPERSEDED` and any roommate link it held is
        cleared on the partner."
        PRD §2.7: "Creating a dorm assignment requires `expected_student_version`,
        matching the target student's current `version`."

        Design: Corner/cross_cutting/assignment_create_stale_student_version_occ
        """
        dorm = make_dorm()
        room = make_room(dorm["id"], room_number="W-101", beds=2)
        term = make_active_term()
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="MALE",
                               legal_name="Stu AI")
        asg_a = propose_assignment(student["id"], room["id"], term["id"])

        fresh = get_student(student["id"])
        payload = create_dorm_assignment_payload(
            student["id"], room["id"], term["id"], fresh["version"])
        asg_b = validate_success(api.create_dorm_assignment(payload, admin_headers), 201)
        assert asg_b["status"] == "PROPOSED"

        old = validate_success(api.get_dorm_assignment(asg_a["id"], admin_headers), 200)
        assert old["status"] == "SUPERSEDED"


class TestImmediateConsistency:
    def test_confirm_then_room_read_immediately_consistent(self, api, admin_headers):
        """PRD §3.3: "A successful confirm stamps `check_in_at` to the current
        logical instant, increments the room's `beds_assigned`, and flips the room
        to `FULL` when the count reaches capacity."

        Design: Corner/consistency/confirm_then_room_read_immediately_consistent
        """
        dorm = make_dorm()
        room = make_room(dorm["id"], room_number="W-103", beds=1)
        term = make_active_term()
        student = make_domestic_student(grade=11, gender="MALE", legal_name="Stu AJ")
        asg = propose_assignment(student["id"], room["id"], term["id"])

        confirmed = validate_success(api.confirm_dorm_assignment(asg["id"], admin_headers), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["check_in_at"] is not None

        room_after = validate_success(api.get_room(room["id"], admin_headers), 200)
        assert_room(room_after)
        assert room_after["beds_assigned"] == 1
        assert room_after["status"] == "FULL"
