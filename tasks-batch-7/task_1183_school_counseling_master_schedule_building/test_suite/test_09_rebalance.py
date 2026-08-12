"""Mid-year rebalancing: epoch stamping, empty-section consolidation, OCC on
the term, and the epoch guard against double moves."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_admin_headers,
    setup_counselor, setup_term, setup_course, setup_student,
    setup_teacher, setup_room, qualify_teacher,
    make_and_submit_request, drive_term_to_building, list_term_sections,
    get_term_version, schedule_section, setup_change_window_scenario,
    drive_term_to_locked, make_change_request, claim_change_request,
    approve_change_request, get_enrolled_entries,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCompoundRebalanceCycle:
    def _setup(self, api):
        """26 students each take singleton course B (one period-1 section) and
        course C (two sections); C's second-created section sits at period 1 and
        conflicts with B for every student, so it stays empty."""
        courses = [{"course_code": "RB-B", "subject_area": "ELECTIVE", "singleton": True},
                   {"course_code": "RB-C", "subject_area": "ELECTIVE"}]
        students = [{"ref": f"RB{i:02d}", "requests": [(0, 1), (1, 2)]}
                    for i in range(1, 27)]
        sc = setup_change_window_scenario(
            courses=courses, students=students,
            section_specs={0: [{"period": 1, "capacity": 32}],
                           1: [{"period": 2, "capacity": 32},
                               {"period": 1, "capacity": 32}]},
            term_code="2030-FALL", counselor_name="C Six")
        drive_term_to_locked(sc["term"]["id"])
        sc["term"] = get_success_data(api.get_term(sc["term"]["id"], ADMIN))
        sec_live, sec_empty = sc["sections"][1][0], sc["sections"][1][1]
        assert sec_live["enrolled_count"] == 26
        assert sec_empty["enrolled_count"] == 0
        return sc, sec_empty

    def test_rebalance_cancels_empty_published_section(self, api):
        """PRD §3.8: "Any under-enrolled `PUBLISHED` section whose
        `enrolled_count` has fallen to zero is cancelled outright"
        PRD §3.8: "The run increments the term's `rebalance_epoch` by one and
        writes a `RebalanceRun` row whose `epoch` field holds that new value"

        Design: Difficulty/non_linear_state_machine/section_and_term_compound_rebalance_cycle
        """
        sc, sec_empty = self._setup(api)
        run = validate_success(api.create_rebalance_run(
            sc["term"]["id"],
            {"expected_term_version": get_term_version(sc["term"]["id"])}, ADMIN), 201)
        assert run["epoch"] == 1
        term = get_success_data(api.get_term(sc["term"]["id"], ADMIN))
        assert term["rebalance_epoch"] == 1
        cancelled = validate_success(api.get_section(sec_empty["id"], ADMIN), 200)
        assert cancelled["state"] == "CANCELLED", (
            "the parent rebalance run drives the child section to CANCELLED"
        )

    def test_rebalance_run_returns_term_to_locked(self, api):
        """PRD §2.4: "A seventh posture, `REBALANCING`, exists only inside a
        rebalance run: the term leaves `LOCKED` for the duration of the run and
        settles back to `LOCKED` when the run completes, so `REBALANCING` is
        never observable outside the run itself."

        Design: Difficulty/non_linear_state_machine/section_and_term_compound_rebalance_cycle
        """
        sc, _ = self._setup(api)
        assert sc["term"]["posture"] == "LOCKED"
        get_success_data(api.create_rebalance_run(
            sc["term"]["id"],
            {"expected_term_version": get_term_version(sc["term"]["id"])}, ADMIN))
        term = get_success_data(api.get_term(sc["term"]["id"], ADMIN))
        assert term["posture"] == "LOCKED", "REBALANCING is transient within the run"


class TestCancelledSectionTerminalLockdown:
    def _setup(self, api):
        """BUILDING term; a section is scheduled then cancelled while still
        empty, landing it in the terminal CANCELLED state."""
        counselor = setup_counselor(max_caseload=50, full_name="C SixB")
        term = setup_term("2030-SPR")
        course = setup_course("TRM-C", credits=1.0, subject_area="ELECTIVE")
        student = setup_student(counselor["id"], "TB01", grade_level=9)
        make_and_submit_request(student["id"], course["id"], term["id"], 1)
        drive_term_to_building(term["id"])
        teacher = setup_teacher(max_sections=5, full_name="T Term")
        qualify_teacher(teacher["id"], course["id"])
        room = setup_room("TRM-1", capacity=32)
        section = list_term_sections(term["id"])[0]
        schedule_section(section["id"], teacher["id"], room["id"], 1, 32, term["id"])
        cancelled = validate_success(api.cancel_section(section["id"], ADMIN), 200)
        assert cancelled["state"] == "CANCELLED"
        return term, teacher, room, section

    def test_cancelled_section_rejects_patch(self, api):
        """PRD §3.3: "The term must be in `BUILDING` (`ERR_INVALID_TERM_POSTURE`)
        and the section still in `DRAFT` (`ERR_INVALID_STATE`)." A CANCELLED
        section is not in DRAFT, so the scheduling transition rejects it.

        Design: Difficulty/non_linear_state_machine/terminal_lockdown_cancelled_section_rejects_patch
        """
        term, teacher, room, section = self._setup(api)
        resp = api.patch_section(section["id"], {
            "teacher_id": teacher["id"], "room_id": room["id"], "period": 2,
            "capacity": 32, "expected_term_version": get_term_version(term["id"]),
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_cancelled_section_state_unchanged_after_rejected_patch(self, api):
        """PRD §3.3: "A `SCHEDULED` section that proves unnecessary can be
        cancelled while `BUILDING` continues" — cancellation is a one-way
        terminal transition; a rejected PATCH performs no state change.

        Design: Difficulty/non_linear_state_machine/terminal_lockdown_cancelled_section_rejects_patch
        """
        term, teacher, room, section = self._setup(api)
        api.patch_section(section["id"], {
            "teacher_id": teacher["id"], "room_id": room["id"], "period": 2,
            "capacity": 32, "expected_term_version": get_term_version(term["id"]),
        }, ADMIN)
        current = validate_success(api.get_section(section["id"], ADMIN), 200)
        assert current["state"] == "CANCELLED"


class TestOccOnRebalance:
    def test_occ_stale_version_on_rebalance(self, api):
        """PRD §2.7: "On each, if `expected_term_version` does not match the
        term's current `version` — because the term's version has advanced since
        the client last read it, invalidating the client's view of window caps,
        seat tallies, conflict maps, or rebalance epoch — the request is rejected
        with `ERR_STALE_TERM_VERSION` (HTTP 412)."
        PRD §3.8: "The run increments the term's `rebalance_epoch` by one and
        writes a `RebalanceRun` row whose `epoch` field holds that new value"

        Design: Corner/endpoints/occ_stale_version_on_rebalance
        """
        term = setup_term("2063-FALL")
        # Drive to LOCKED with no requests at all (publish preconditions hold
        # vacuously over zero sections).
        get_success_data(api.close_collection(term["id"], ADMIN))
        get_success_data(api.generate_sections(term["id"], ADMIN))
        get_success_data(api.publish_term(term["id"], ADMIN))
        get_success_data(api.open_change_window(term["id"], ADMIN))
        get_success_data(api.close_change_window(term["id"], ADMIN))
        locked = get_success_data(api.get_term(term["id"], ADMIN))
        assert locked["posture"] == "LOCKED"
        v = locked["version"]
        stale = api.create_rebalance_run(term["id"], {"expected_term_version": v - 1}, ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_TERM_VERSION, 412)
        runs = get_success_data(api.list_rebalance_runs(term["id"], ADMIN))
        assert runs == [], "the stale call must create no RebalanceRun"
        ok = validate_success(api.create_rebalance_run(
            term["id"], {"expected_term_version": v}, ADMIN), 201)
        assert ok["epoch"] == 1


class TestRebalanceEpochGuard:
    def test_rebalance_epoch_prevents_double_move(self, api):
        """PRD §3.8: "any student whose `epoch_placed` already equals the term's
        new `rebalance_epoch` is skipped, so no student moves twice in one run."
        PRD §3.8: "creates a replacement `ENROLLED` entry with `origin`
        `REBALANCE` and `epoch_placed` stamped with the new epoch"
        PRD §3.8: "Each donor drains students into its single best receiver
        until the donor reaches `class_size_target` or runs out of movable
        students"

        Design: Corner/cross_cutting_layers/rebalance_epoch_prevents_double_move
        """
        # EP: 12 students, 3 sections (periods 2/3/4), publish balances 4/4/4.
        # F: singleton course holding 4 more students at period 5.
        courses = [{"course_code": "EP-1", "subject_area": "ELECTIVE"},
                   {"course_code": "EP-F", "subject_area": "ELECTIVE", "singleton": True}]
        students = ([{"ref": f"EP{i:02d}", "requests": [(0, 1)]} for i in range(1, 13)]
                    + [{"ref": f"EF{i:02d}", "requests": [(1, 1)]} for i in range(1, 5)])
        sc = setup_change_window_scenario(
            courses=courses, students=students,
            section_specs={0: [{"period": 2, "capacity": 32},
                               {"period": 3, "capacity": 32},
                               {"period": 4, "capacity": 32}],
                           1: [{"period": 5, "capacity": 32}]},
            term_code="2071-FALL", counselor_name="C Ep", class_size_target=4)
        counselor = sc["counselor"]
        term_id = sc["term"]["id"]
        sec_a, sec_b, sec_c = sc["sections"][0]
        assert sec_a["enrolled_count"] == 4 and sec_b["enrolled_count"] == 4

        # Four F-students ADD into sec_a (period 2): A goes 4 -> 8 (over target).
        f_students = sc["students"][12:]
        for stu in f_students:
            req = make_change_request(stu["id"], term_id, "ADD",
                                      add_section_id=sec_a["id"],
                                      reason="Moving into the bigger section")
            claim_change_request(req["id"], counselor["id"])
            approved = approve_change_request(req["id"], term_id)
            get_success_data(api.execute_change_request(approved["id"], ADMIN))

        # Two sec_b students DROP: B goes 4 -> 2 (below target).
        b_entries = get_success_data(api.list_schedule_entries(ADMIN, params={
            "section_id": sec_b["id"], "state": "ENROLLED",
        }))
        for entry in b_entries[:2]:
            stu_id = entry["student_id"]
            req = make_change_request(stu_id, term_id, "DROP",
                                      drop_entry_id=entry["id"],
                                      reason="Leaving to lighten my load")
            claim_change_request(req["id"], counselor["id"])
            approved = approve_change_request(req["id"], term_id)
            get_success_data(api.execute_change_request(approved["id"], ADMIN))

        drive_term_to_locked(term_id)
        run = validate_success(api.create_rebalance_run(
            term_id, {"expected_term_version": get_term_version(term_id)}, ADMIN), 201)
        assert run["epoch"] == 1
        assert run["moves_proposed"] == 4, (
            "donor A drains from 8 to the target 4 into receiver B: exactly 4 moves"
        )
        moved = get_success_data(api.list_schedule_entries(ADMIN, params={
            "term_id": term_id, "state": "MOVED",
        }))
        rebalance_new = [e for e in get_success_data(api.list_schedule_entries(
            ADMIN, params={"term_id": term_id, "state": "ENROLLED",
                           "limit": 100}))
            if e["origin"] == "REBALANCE"]
        assert len(rebalance_new) == 4
        for entry in rebalance_new:
            assert entry["epoch_placed"] == 1, (
                "every entry created by the run must be stamped with the new epoch"
            )
        moved_students = [e["student_id"] for e in moved]
        assert len(moved_students) == len(set(moved_students)), (
            "no student may be the source of more than one MOVED entry in one run"
        )
