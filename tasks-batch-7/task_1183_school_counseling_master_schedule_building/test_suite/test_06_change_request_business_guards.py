"""Change-request business guards: capacity, credit ceiling, singleton cap,
quota, cohort cap — and the invariants execution must preserve."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_student_headers,
    setup_change_window_scenario, entry_for, make_change_request,
    claim_change_request, approve_change_request,
    get_enrolled_entries, get_term_version,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSwapPreservesGlobalEnrollmentCount:
    def _setup(self, api):
        students = [{"ref": f"P{i:03d}", "requests": [(0, 1)]} for i in range(1, 11)]
        students += [{"ref": f"Q{i:03d}", "requests": [(1, 1)]} for i in range(1, 6)]
        return setup_change_window_scenario(
            courses=[{"course_code": "SWP-P", "subject_area": "ELECTIVE"},
                     {"course_code": "SWP-Q", "subject_area": "ELECTIVE"}],
            students=students,
            section_specs={0: [{"period": 1, "capacity": 32}],
                           1: [{"period": 2, "capacity": 32}]},
            term_code="2038-FALL", counselor_name="C Seventeen")

    def _approved_swap(self, api, sc):
        counselor = sc["counselor"]
        s_swap = sc["students"][0]
        sec_p, sec_q = sc["sections"][0][0], sc["sections"][1][0]
        entry_p = entry_for(api, s_swap["id"], sec_p["id"])
        req = make_change_request(s_swap["id"], sc["term"]["id"], "SWAP",
                                  drop_entry_id=entry_p["id"], add_section_id=sec_q["id"],
                                  reason="Swap for band practice slot")
        claim_change_request(req["id"], counselor["id"])
        approve_change_request(req["id"], sc["term"]["id"])
        return s_swap, sec_p, sec_q, entry_p, req

    def test_swap_marks_entry_moved_with_target(self, api):
        """PRD §3.5: "An executed `SWAP` does both atomically: the dropped entry
        becomes `MOVED` with `moved_to_section_id` pointing at the replacement
        section, and the replacement `ENROLLED` entry is created in the same
        operation."

        Design: Difficulty/compensating_invariant/swap_preserves_global_enrollment_count
        """
        sc = self._setup(api)
        s_swap, sec_p, sec_q, entry_p, req = self._approved_swap(api, sc)
        get_success_data(api.execute_change_request(req["id"], ADMIN))
        moved = validate_success(api.get_schedule_entry(entry_p["id"], ADMIN), 200)
        assert moved["state"] == "MOVED"
        assert moved["moved_to_section_id"] == sec_q["id"]
        enrolled = get_enrolled_entries(s_swap["id"], sc["term"]["id"])
        assert len(enrolled) == 1, "the student's ENROLLED entry count is invariant at 1"
        assert enrolled[0]["section_id"] == sec_q["id"]
        assert enrolled[0]["origin"] == "CHANGE_REQUEST"

    def test_swap_preserves_section_enrollment_sum(self, api):
        """PRD §3.5: "Source and target sections recompute `enrolled_count`,
        `cohort_counts`, and `under_enrolled`" — the source loses exactly one and
        the target gains exactly one, so the two-section total is conserved.

        Design: Difficulty/compensating_invariant/swap_preserves_global_enrollment_count
        """
        sc = self._setup(api)
        s_swap, sec_p, sec_q, entry_p, req = self._approved_swap(api, sc)
        assert sec_p["enrolled_count"] == 10 and sec_q["enrolled_count"] == 5
        get_success_data(api.execute_change_request(req["id"], ADMIN))
        p_after = validate_success(api.get_section(sec_p["id"], ADMIN), 200)
        q_after = validate_success(api.get_section(sec_q["id"], ADMIN), 200)
        assert p_after["enrolled_count"] == 9
        assert q_after["enrolled_count"] == 6
        assert p_after["enrolled_count"] + q_after["enrolled_count"] == 15, (
            "total ENROLLED seats across the two sections must be unchanged"
        )


class TestSectionFullAtExactCapacity:
    def _setup(self, api):
        # Course A: capacity-3 section at period 2, two fillers occupy 2 seats.
        # Course B: period 1; s_edge and s_third enrolled there.
        students = [{"ref": "F001", "requests": [(0, 1)]},
                    {"ref": "F002", "requests": [(0, 1)]},
                    {"ref": "EDG1", "requests": [(1, 1)]},
                    {"ref": "THD1", "requests": [(1, 1)]}]
        return setup_change_window_scenario(
            courses=[{"course_code": "EDG-A", "subject_area": "ELECTIVE"},
                     {"course_code": "EDG-B", "subject_area": "ELECTIVE"}],
            students=students,
            section_specs={0: [{"period": 2, "capacity": 3}],
                           1: [{"period": 1, "capacity": 32}]},
            term_code="2034-FALL", counselor_name="C Eleven")

    def test_execute_rejects_at_exact_capacity(self, api):
        """PRD §3.5: "Its `enrolled_count` must be strictly below `capacity`, a
        section at exactly capacity refusing the placement (`ERR_SECTION_FULL`,
        HTTP 422)."
        PRD §3.5: "executing an `APPROVED` request — again only while
        `change_window_open` holds — re-validates every business check at
        execution time."

        Design: Difficulty/boundary_precision_check/section_full_at_exact_capacity
        """
        sc = self._setup(api)
        counselor = sc["counselor"]
        s_edge, s_third = sc["students"][2], sc["students"][3]
        sec_edge = sc["sections"][0][0]
        assert sec_edge["enrolled_count"] == 2  # one seat free at approval time
        # s_edge's ADD is approved while a seat is free
        cr_edge = make_change_request(s_edge["id"], sc["term"]["id"], "ADD",
                                      add_section_id=sec_edge["id"],
                                      reason="Add at exact capacity edge")
        claim_change_request(cr_edge["id"], counselor["id"])
        approve_change_request(cr_edge["id"], sc["term"]["id"])
        # another executed change takes the last seat first
        cr_third = make_change_request(s_third["id"], sc["term"]["id"], "ADD",
                                       add_section_id=sec_edge["id"],
                                       reason="Taking the final free seat")
        claim_change_request(cr_third["id"], counselor["id"])
        approve_change_request(cr_third["id"], sc["term"]["id"])
        get_success_data(api.execute_change_request(cr_third["id"], ADMIN))
        full = validate_success(api.get_section(sec_edge["id"], ADMIN), 200)
        assert full["enrolled_count"] == 3 == full["capacity"]
        resp = api.execute_change_request(cr_edge["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SECTION_FULL, 422)

    def test_execute_accepts_one_below_capacity(self, api):
        """PRD §3.5: "Its `enrolled_count` must be strictly below `capacity`" —
        with enrolled_count == capacity - 1 the strict inequality holds and the
        placement proceeds.

        Design: Difficulty/boundary_precision_check/section_full_at_exact_capacity
        """
        sc = self._setup(api)
        counselor = sc["counselor"]
        s_edge = sc["students"][2]
        sec_edge = sc["sections"][0][0]
        assert sec_edge["enrolled_count"] == 2 == sec_edge["capacity"] - 1
        cr_edge = make_change_request(s_edge["id"], sc["term"]["id"], "ADD",
                                      add_section_id=sec_edge["id"],
                                      reason="Add with one seat still free")
        claim_change_request(cr_edge["id"], counselor["id"])
        approve_change_request(cr_edge["id"], sc["term"]["id"])
        done = validate_success(api.execute_change_request(cr_edge["id"], ADMIN), 200)
        assert done["state"] == "EXECUTED"
        after = validate_success(api.get_section(sec_edge["id"], ADMIN), 200)
        assert after["enrolled_count"] == 3


class TestCreditCeiling:
    def test_credit_ceiling_blocks_add(self, api):
        """PRD §3.5: "The student's `planned_credit_load` plus the incoming
        course's `credits` must not exceed the 8.0 credit ceiling
        (`ERR_CREDIT_CEILING_EXCEEDED`, HTTP 422)."
        PRD §3.5: "executing an `APPROVED` request — again only while
        `change_window_open` holds — re-validates every business check at
        execution time."

        Design: Corner/validations/credit_ceiling_blocks_add
        """
        courses = [{"course_code": f"MAX-C{i}", "subject_area": "ELECTIVE"} for i in range(1, 8)]
        courses += [{"course_code": "MAX-X", "subject_area": "ELECTIVE"},
                    {"course_code": "MAX-Y", "subject_area": "ELECTIVE"}]
        students = [{"ref": "MAX1", "grade_level": 12, "earned_credits": 20.0,
                     "requests": [(i, i + 1) for i in range(7)]},
                    {"ref": "F001", "requests": [(7, 1), (8, 2)]}]
        section_specs = {i: [{"period": i + 1, "capacity": 32}] for i in range(7)}
        section_specs[7] = [{"period": 9, "capacity": 32}]
        section_specs[8] = [{"period": 10, "capacity": 32}]
        sc = setup_change_window_scenario(
            courses=courses, students=students, section_specs=section_specs,
            periods_per_day=10, term_code="2057-FALL", counselor_name="C Max")
        counselor = sc["counselor"]
        s_max = sc["students"][0]
        sec_x, sec_y = sc["sections"][7][0], sc["sections"][8][0]
        student_now = get_success_data(api.get_student(s_max["id"], ADMIN))
        assert float(student_now["planned_credit_load"]) == pytest.approx(7.0)
        # Both ADDs are approved while the load is still 7.0 (7.0 + 1.0 <= 8.0)
        cr_x = make_change_request(s_max["id"], sc["term"]["id"], "ADD",
                                   add_section_id=sec_x["id"], reason="Add course X for credit")
        claim_change_request(cr_x["id"], counselor["id"])
        approve_change_request(cr_x["id"], sc["term"]["id"])
        cr_y = make_change_request(s_max["id"], sc["term"]["id"], "ADD",
                                   add_section_id=sec_y["id"], reason="Add course Y for credit")
        claim_change_request(cr_y["id"], counselor["id"])
        approve_change_request(cr_y["id"], sc["term"]["id"])
        # Executing Y lifts the load to exactly 8.0
        get_success_data(api.execute_change_request(cr_y["id"], ADMIN))
        loaded = get_success_data(api.get_student(s_max["id"], ADMIN))
        assert float(loaded["planned_credit_load"]) == pytest.approx(8.0)
        # Executing X now would push 8.0 + 1.0 above the ceiling
        resp = api.execute_change_request(cr_x["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CREDIT_CEILING_EXCEEDED, 422)


class TestSingletonCap:
    def test_singleton_cap_boundary(self, api):
        """PRD §3.5: "When the term's `singleton_section_cap` is non-zero, the
        student's count of `ENROLLED` entries in `singleton` courses after the
        change must not exceed the cap (`ERR_SINGLETON_CAP_EXCEEDED`, HTTP 422)."

        Design: Corner/validations/singleton_cap_boundary
        """
        courses = [{"course_code": f"SG-G{i}", "subject_area": "ELECTIVE", "singleton": True}
                   for i in range(1, 4)]
        students = [{"ref": "SG02", "requests": [(0, 1)]},
                    {"ref": "SG01", "requests": [(0, 1)]},
                    {"ref": "F002", "requests": [(1, 1)]},
                    {"ref": "F003", "requests": [(2, 1)]}]
        section_specs = {0: [{"period": 1, "capacity": 32}],
                         1: [{"period": 2, "capacity": 32}],
                         2: [{"period": 3, "capacity": 32}]}
        sc = setup_change_window_scenario(
            courses=courses, students=students, section_specs=section_specs,
            term_code="2058-FALL", counselor_name="C Sg2", singleton_section_cap=2)
        counselor = sc["counselor"]
        s_sg2, s_sg1 = sc["students"][0], sc["students"][1]
        sec_g2, sec_g3 = sc["sections"][1][0], sc["sections"][2][0]

        def approved_add(student, section):
            req = make_change_request(student["id"], sc["term"]["id"], "ADD",
                                      add_section_id=section["id"],
                                      reason="Adding a singleton course")
            claim_change_request(req["id"], counselor["id"])
            return approve_change_request(req["id"], sc["term"]["id"])

        # Approved while each student still holds only 1 singleton enrollment.
        cr2_g2 = approved_add(s_sg2, sec_g2)
        cr2_g3 = approved_add(s_sg2, sec_g3)
        cr1_g2 = approved_add(s_sg1, sec_g2)
        # 1 -> 2 reaches the cap but does not exceed it: both succeed.
        get_success_data(api.execute_change_request(cr2_g2["id"], ADMIN))
        ok = validate_success(api.execute_change_request(cr1_g2["id"], ADMIN), 200)
        assert ok["state"] == "EXECUTED"
        assert len(get_enrolled_entries(s_sg1["id"], sc["term"]["id"])) == 2
        # 2 -> 3 would exceed cap 2.
        resp = api.execute_change_request(cr2_g3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SINGLETON_CAP_EXCEEDED, 422)


class TestChangeQuota:
    def test_error_change_quota_trigger(self, api):
        """PRD §3.5: "Approval additionally requires the student's count of
        approved-but-not-yet-executed change requests this term to be strictly
        below the term's `change_request_max_per_student` — a student at the
        quota is refused with `ERR_CHANGE_QUOTA_EXCEEDED` (HTTP 422)"

        Design: Corner/errors/error_change_quota_trigger
        """
        courses = [{"course_code": f"Q-Q{i}", "subject_area": "ELECTIVE"} for i in range(1, 5)]
        students = [{"ref": "Q001", "requests": [(0, 1), (1, 2), (2, 3), (3, 4)]}]
        section_specs = {i: [{"period": i + 1, "capacity": 32}] for i in range(4)}
        sc = setup_change_window_scenario(
            courses=courses, students=students, section_specs=section_specs,
            term_code="2066-FALL", counselor_name="C Q", change_request_max_per_student=3)
        counselor = sc["counselor"]
        s_q = sc["students"][0]
        entries = get_enrolled_entries(s_q["id"], sc["term"]["id"])
        assert len(entries) == 4
        approved = []
        for i, entry in enumerate(entries):
            req = make_change_request(s_q["id"], sc["term"]["id"], "DROP",
                                      drop_entry_id=entry["id"],
                                      reason=f"Drop number {i + 1} for quota")
            claim_change_request(req["id"], counselor["id"])
            if i < 3:
                approved.append(approve_change_request(req["id"], sc["term"]["id"]))
            else:
                fourth = req
        resp = api.decide_change_request(fourth["id"], {
            "decision": "APPROVE",
            "expected_term_version": get_term_version(sc["term"]["id"]),
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CHANGE_QUOTA_EXCEEDED, 422)


class TestCohortCap:
    def test_error_cohort_cap_trigger(self, api):
        """PRD §3.5: "adding the student must not push the target section's
        `cohort_counts` entry for the student's `special_program` above half the
        section's `capacity` rounded up to a whole seat whenever the student
        belongs to a special program (`ERR_COHORT_CAP_EXCEEDED`, HTTP 422)."

        Design: Corner/errors/error_cohort_cap_trigger
        """
        students = [{"ref": "IE01", "special_program": "IEP", "requests": [(0, 1)]},
                    {"ref": "IE02", "special_program": "IEP", "requests": [(1, 1)]},
                    {"ref": "IE03", "special_program": "IEP", "requests": [(1, 1)]}]
        sc = setup_change_window_scenario(
            courses=[{"course_code": "COH-C", "subject_area": "ELECTIVE"},
                     {"course_code": "COH-B", "subject_area": "ELECTIVE"}],
            students=students,
            section_specs={0: [{"period": 2, "capacity": 4}],
                           1: [{"period": 1, "capacity": 32}]},
            term_code="2067-FALL", counselor_name="C Coh")
        counselor = sc["counselor"]
        i1, i2, s_coh = sc["students"]
        sec_coh = sc["sections"][0][0]
        assert sec_coh["cohort_counts"]["IEP"] == 1  # only i1 placed at publish

        def approved_add(student):
            req = make_change_request(student["id"], sc["term"]["id"], "ADD",
                                      add_section_id=sec_coh["id"],
                                      reason="Joining the cohort section")
            claim_change_request(req["id"], counselor["id"])
            return approve_change_request(req["id"], sc["term"]["id"])

        # Both ADDs are approved while the cohort holds 1 (1 + 1 <= ceil(0.5*4)).
        cr_i2 = approved_add(i2)
        cr_coh = approved_add(s_coh)
        # i2's execute lifts the cohort to exactly the half-cap boundary (2).
        get_success_data(api.execute_change_request(cr_i2["id"], ADMIN))
        mid = validate_success(api.get_section(sec_coh["id"], ADMIN), 200)
        assert mid["cohort_counts"]["IEP"] == 2
        # s_coh's execute would push the cohort to 3 > 2.
        resp = api.execute_change_request(cr_coh["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_COHORT_CAP_EXCEEDED, 422)


class TestExecuteSideEffects:
    def test_immediate_visibility_of_execute_effects(self, api):
        """PRD §3.5: "An executed `ADD` creates a fresh entry in state `ENROLLED`
        with `origin` `CHANGE_REQUEST` and `epoch_placed` stamped with the term's
        current `rebalance_epoch`."
        PRD §3.5: "the request becomes `EXECUTED` and its `version` increments by
        one."

        Design: Corner/consistency_model/immediate_visibility_of_execute_effects
        """
        sc = setup_change_window_scenario(
            courses=[{"course_code": "IMM-B", "subject_area": "ELECTIVE"},
                     {"course_code": "IMM-X", "subject_area": "ELECTIVE"}],
            students=[{"ref": "IM01", "requests": [(0, 1)]},
                      {"ref": "F001", "requests": [(1, 1)]}],
            section_specs={0: [{"period": 1, "capacity": 32}],
                           1: [{"period": 2, "capacity": 32}]},
            term_code="2074-FALL", counselor_name="C Imm")
        counselor = sc["counselor"]
        s_imm = sc["students"][0]
        sec_imm = sc["sections"][1][0]
        req = make_change_request(s_imm["id"], sc["term"]["id"], "ADD",
                                  add_section_id=sec_imm["id"], reason="Adding second course now")
        claim_change_request(req["id"], counselor["id"])
        approve_change_request(req["id"], sc["term"]["id"])
        done = validate_success(api.execute_change_request(req["id"], ADMIN), 200)
        assert done["state"] == "EXECUTED"
        entries = get_enrolled_entries(s_imm["id"], sc["term"]["id"])
        new_entries = [e for e in entries if e["section_id"] == sec_imm["id"]]
        assert len(new_entries) == 1, "the immediate read must show the new entry"
        assert new_entries[0]["state"] == "ENROLLED"
        assert new_entries[0]["origin"] == "CHANGE_REQUEST"

    def test_derived_counts_reconcile_after_drop(self, api):
        """PRD §3.5: "An executed `DROP` moves the dropped entry `ENROLLED` →
        `DROPPED`."
        PRD §3.5: "Source and target sections recompute `enrolled_count`,
        `cohort_counts`, and `under_enrolled`"
        PRD §3.8: "a section flies the `under_enrolled` flag when its enrollment
        sits below half its `capacity` rounded up to a whole seat"

        Design: Corner/cross_cutting_layers/derived_counts_reconcile_after_drop
        """
        students = [{"ref": "DR01", "special_program": "IEP", "requests": [(0, 1)]},
                    {"ref": "DR02", "special_program": "IEP", "requests": [(0, 1)]}]
        sc = setup_change_window_scenario(
            courses=[{"course_code": "DER-1", "subject_area": "ELECTIVE"}],
            students=students,
            section_specs={0: [{"period": 1, "capacity": 4}]},
            term_code="2072-FALL", counselor_name="C Der")
        counselor = sc["counselor"]
        d1 = sc["students"][0]
        sec_der = sc["sections"][0][0]
        assert sec_der["enrolled_count"] == 2
        entry = entry_for(api, d1["id"], sec_der["id"])
        req = make_change_request(d1["id"], sc["term"]["id"], "DROP",
                                  drop_entry_id=entry["id"], reason="Dropping to fix balance")
        claim_change_request(req["id"], counselor["id"])
        approve_change_request(req["id"], sc["term"]["id"])
        get_success_data(api.execute_change_request(req["id"], ADMIN))
        after = validate_success(api.get_section(sec_der["id"], ADMIN), 200)
        assert after["enrolled_count"] == 1
        assert after["cohort_counts"].get("IEP", 0) == 1
        assert after["under_enrolled"] is True, "1 < ceil(0.5 * 4) == 2 must flip the flag"

    def test_credit_audit_input_set_excludes_dropped(self, api):
        """PRD §3.4: "the student's `planned_credit_load` — the sum of course
        `credits` over the student's `ENROLLED` entries for the term, recomputed
        on every enrollment mutation" — a `DROPPED` entry leaves the input set.

        Design: Corner/calculations/credit_audit_input_set_excludes_dropped
        """
        sc = setup_change_window_scenario(
            courses=[{"course_code": "DRP-1", "subject_area": "ELECTIVE"},
                     {"course_code": "DRP-2", "subject_area": "ELECTIVE"}],
            students=[{"ref": "DP01", "requests": [(0, 1), (1, 2)]}],
            section_specs={0: [{"period": 1, "capacity": 32}],
                           1: [{"period": 2, "capacity": 32}]},
            term_code="2050-FALL", counselor_name="C Drp")
        counselor = sc["counselor"]
        s_drp = sc["students"][0]
        before = get_success_data(api.get_student(s_drp["id"], ADMIN))
        assert float(before["planned_credit_load"]) == pytest.approx(2.0)
        entry = entry_for(api, s_drp["id"], sc["sections"][0][0]["id"])
        req = make_change_request(s_drp["id"], sc["term"]["id"], "DROP",
                                  drop_entry_id=entry["id"], reason="Reducing my course load")
        claim_change_request(req["id"], counselor["id"])
        approve_change_request(req["id"], sc["term"]["id"])
        get_success_data(api.execute_change_request(req["id"], ADMIN))
        after = get_success_data(api.get_student(s_drp["id"], ADMIN))
        assert float(after["planned_credit_load"]) == pytest.approx(1.0), (
            "the dropped entry's credit must leave planned_credit_load"
        )
