"""Credit projection vs final audit, recovery priority scoring, recovery
placement gating, and change-execute cascades into credit standing."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_counselor_headers, make_student_headers,
    setup_counselor, setup_term, setup_course, setup_student,
    setup_teacher, setup_room, qualify_teacher,
    make_and_submit_request, drive_term_to_building, list_term_sections,
    get_term_version, schedule_section, setup_change_window_scenario,
    drive_term_to_locked, entry_for, make_change_request, claim_change_request,
    approve_change_request,
)

ADMIN = TEST_USERS["admin_headers"]


def _publish_projection_scenario(api):
    """s_main (grade 11, earned 10.0) holds 6 submitted primaries. ART sits at
    period 1 and PE at period 2, colliding with s_main's ENG (period 1) and MAT
    (period 2) placements, so ART/PE go UNPLACED deterministically regardless of
    cross-student processing order."""
    counselor = setup_counselor(max_caseload=100, full_name="C Two")
    term = setup_term("2027-FALL")
    k = {}
    k["eng"] = setup_course("ENG-101", credits=1.0, subject_area="ENGLISH", title="English 9")
    k["mat"] = setup_course("MAT-101", credits=1.0, subject_area="MATH", title="Math 9")
    k["sci"] = setup_course("SCI-101", credits=1.0, subject_area="SCIENCE", title="Sci 9")
    k["soc"] = setup_course("SOC-101", credits=1.0, subject_area="SOCIAL_STUDIES", title="Soc 9")
    k["art"] = setup_course("ART-101", credits=1.0, subject_area="ARTS", title="Art")
    k["pe"] = setup_course("PE-101", credits=1.0, subject_area="PE_HEALTH", title="PE")
    s_main = setup_student(counselor["id"], "M001", grade_level=11, earned_credits=10.0)
    f1 = setup_student(counselor["id"], "F001", grade_level=11, earned_credits=10.0)
    f2 = setup_student(counselor["id"], "F002", grade_level=11, earned_credits=10.0)
    make_and_submit_request(f1["id"], k["art"]["id"], term["id"], 1)
    make_and_submit_request(f2["id"], k["pe"]["id"], term["id"], 1)
    reqs = {}
    for rank, key in enumerate(["eng", "mat", "sci", "soc", "art", "pe"], start=1):
        reqs[key] = make_and_submit_request(s_main["id"], k[key]["id"], term["id"], rank)
    return counselor, term, k, s_main, f1, f2, reqs


def _complete_to_publish(api, term, k):
    drive_term_to_building(term["id"])
    t_a = setup_teacher(max_sections=10, full_name="T Main")
    t_b = setup_teacher(max_sections=10, full_name="T Aux")
    for key in ("eng", "mat", "sci", "soc"):
        qualify_teacher(t_a["id"], k[key]["id"])
    for key in ("art", "pe"):
        qualify_teacher(t_b["id"], k[key]["id"])
    r1 = setup_room("A-1", capacity=32)
    r2 = setup_room("A-2", capacity=32)
    periods = {"eng": 1, "mat": 2, "sci": 3, "soc": 4, "art": 1, "pe": 2}
    staff = {"eng": (t_a, r1), "mat": (t_a, r1), "sci": (t_a, r1), "soc": (t_a, r1),
             "art": (t_b, r2), "pe": (t_b, r2)}
    sections = list_term_sections(term["id"])
    for key, course in k.items():
        sec = next(s for s in sections if s["course_id"] == course["id"])
        teacher, room = staff[key]
        schedule_section(sec["id"], teacher["id"], room["id"], periods[key], 32, term["id"])
    get_success_data(api.publish_term(term["id"], ADMIN))


class TestCreditProjectionVsFinalAudit:
    def test_provisional_projection_counts_submitted_requests(self, api):
        """PRD §3.7: "While the term is still `COLLECTING`, a provisional
        credit-projection read replaces `planned_credit_load` with the requested
        credits of the student's `SUBMITTED` primary requests — alternates
        excluded"

        Design: Difficulty/dual_variant_calc/credit_projection_vs_final_audit
        """
        _, term, _, s_main, _, _, _ = _publish_projection_scenario(api)
        data = validate_success(api.get_student_credit_projection(s_main["id"], ADMIN), 200)
        assert float(data["projected_credits"]) == pytest.approx(16.0), (
            f"10.0 earned + 6.0 requested = 16.0, got {data['projected_credits']}"
        )
        assert float(data["required_credits"]) == pytest.approx(18.0)
        assert float(data["deficiency_credits"]) == pytest.approx(2.0)

    def test_final_audit_counts_only_enrolled_entries(self, api):
        """PRD §3.7: "The final-audit variant is what gets written to
        `CreditAudit` rows at publication and at recovery placement, counting
        only `ENROLLED` entries, so unplaced requests contribute zero"
        PRD §3.4: "only when the primary and every such alternate have failed
        does the request become `UNPLACED`, with no entry created."

        Design: Difficulty/dual_variant_calc/credit_projection_vs_final_audit
        """
        _, term, k, s_main, _, _, reqs = _publish_projection_scenario(api)
        _complete_to_publish(api, term, k)
        audit = validate_success(api.get_student_credit_audit(s_main["id"], ADMIN), 200)
        assert float(audit["projected_credits"]) == pytest.approx(14.0), (
            f"10.0 earned + 4.0 enrolled = 14.0, got {audit['projected_credits']}"
        )
        assert float(audit["deficiency_credits"]) == pytest.approx(4.0)
        student = get_success_data(api.get_student(s_main["id"], ADMIN))
        assert float(student["planned_credit_load"]) == pytest.approx(4.0)
        assert student["credit_deficient"] is True
        for key in ("art", "pe"):
            current = validate_success(api.get_course_request(reqs[key]["id"], ADMIN), 200)
            assert current["state"] == "UNPLACED", (
                f"{key} sits on a colliding period and must be UNPLACED"
            )


class TestRecoveryPriorityScoring:
    def _setup(self, api):
        courses = ([{"course_code": f"RP-M{i}", "subject_area": "MATH"} for i in range(1, 5)]
                   + [{"course_code": "RP-SCI", "subject_area": "SCIENCE"}]
                   + [{"course_code": "ENG-401", "subject_area": "ENGLISH"}])
        students = [{"ref": "HI01", "grade_level": 12, "earned_credits": 15.5,
                     "requests": [(0, 1), (1, 2), (2, 3), (3, 4)]},
                    {"ref": "LO01", "grade_level": 9, "earned_credits": 4.0,
                     "requests": [(4, 1)]}]
        section_specs = {0: [{"period": 1, "capacity": 32}],
                         1: [{"period": 2, "capacity": 32}],
                         2: [{"period": 3, "capacity": 32}],
                         3: [{"period": 4, "capacity": 32}],
                         4: [{"period": 5, "capacity": 32}]}
        sc = setup_change_window_scenario(
            courses=courses, students=students, section_specs=section_specs,
            term_code="2028-FALL", counselor_name="C Three")
        drive_term_to_locked(sc["term"]["id"])
        return sc

    def test_recovery_priority_grade12_english_flag(self, api):
        """PRD §3.7: "it carries a computed `priority_score`: ten points per
        credit of `deficiency_credits`, plus two points per high-school year
        underway (`grade_level` minus 8), plus three points when `ENGLISH` is
        among the deficient subjects and another three when `MATH` is — all drawn
        from the student's latest audit for the term"

        Design: Difficulty/combinatorial_formula/recovery_priority_four_input_scoring
        """
        sc = self._setup(api)
        counselor = sc["counselor"]
        s_hi = sc["students"][0]
        target = sc["courses"][5]
        resp = api.create_recovery_placement({
            "student_id": s_hi["id"], "term_id": sc["term"]["id"],
            "target_course_id": target["id"],
        }, make_counselor_headers(counselor["id"]))
        data = validate_success(resp, 201)
        # audit: projected 15.5 + 4.0 = 19.5, required 22.0, deficiency 2.5;
        # MATH enrolled 4.0 meets the 4-year bar, ENGLISH 0 does not.
        assert float(data["priority_score"]) == pytest.approx(36.0), (
            f"10*2.5 + 2*(12-8) + 3*1 + 3*0 = 36.0, got {data['priority_score']}"
        )

    def test_recovery_priority_grade9_dual_flags(self, api):
        """PRD §3.7: "it carries a computed `priority_score`: ten points per
        credit of `deficiency_credits`, plus two points per high-school year
        underway (`grade_level` minus 8), plus three points when `ENGLISH` is
        among the deficient subjects and another three when `MATH` is"

        Design: Difficulty/combinatorial_formula/recovery_priority_four_input_scoring
        """
        sc = self._setup(api)
        counselor = sc["counselor"]
        s_hi, s_lo = sc["students"][0], sc["students"][1]
        target = sc["courses"][5]
        rp_hi = validate_success(api.create_recovery_placement({
            "student_id": s_hi["id"], "term_id": sc["term"]["id"],
            "target_course_id": target["id"],
        }, make_counselor_headers(counselor["id"])), 201)
        rp_lo = validate_success(api.create_recovery_placement({
            "student_id": s_lo["id"], "term_id": sc["term"]["id"],
            "target_course_id": target["id"],
        }, make_counselor_headers(counselor["id"])), 201)
        # audit: projected 4.0 + 1.0 = 5.0, required 6.0, deficiency 1.0;
        # ENGLISH 0 < 1.0 and MATH 0 < 1.0 are both deficient.
        assert float(rp_lo["priority_score"]) == pytest.approx(18.0), (
            f"10*1.0 + 2*(9-8) + 3*1 + 3*1 = 18.0, got {rp_lo['priority_score']}"
        )
        assert float(rp_hi["priority_score"]) != float(rp_lo["priority_score"])


class TestChangeExecuteCascadeToAudit:
    def _setup(self, api):
        courses = [{"course_code": f"CD-C{i}", "subject_area": "ELECTIVE"} for i in range(1, 5)]
        students = [{"ref": "CD01", "grade_level": 12, "earned_credits": 18.0,
                     "requests": [(0, 1), (1, 2), (2, 3), (3, 4)]}]
        section_specs = {i: [{"period": i + 1, "capacity": 32}] for i in range(4)}
        sc = setup_change_window_scenario(
            courses=courses, students=students, section_specs=section_specs,
            term_code="2031-FALL", counselor_name="C Eight")
        counselor = sc["counselor"]
        s_cd = sc["students"][0]
        entry_x = entry_for(api, s_cd["id"], sc["sections"][0][0]["id"])
        crd = make_change_request(s_cd["id"], sc["term"]["id"], "DROP",
                                  drop_entry_id=entry_x["id"],
                                  reason="Dropping to reduce load now")
        claim_change_request(crd["id"], counselor["id"])
        approve_change_request(crd["id"], sc["term"]["id"])
        return sc, s_cd, entry_x, crd

    def test_execute_drop_flips_entry_and_load(self, api):
        """PRD §3.5: "An executed `DROP` moves the dropped entry `ENROLLED` →
        `DROPPED`."
        PRD §3.4: "the student's `planned_credit_load` — the sum of course
        `credits` over the student's `ENROLLED` entries for the term, recomputed
        on every enrollment mutation"

        Design: Difficulty/transitive_cascade/change_execute_cascade_to_audit_and_deficiency_flag
        """
        sc, s_cd, entry_x, crd = self._setup(api)
        before = get_success_data(api.get_student(s_cd["id"], ADMIN))
        assert float(before["planned_credit_load"]) == pytest.approx(4.0)
        get_success_data(api.execute_change_request(crd["id"], ADMIN))
        entry_now = validate_success(api.get_schedule_entry(entry_x["id"], ADMIN), 200)
        assert entry_now["state"] == "DROPPED"
        after = get_success_data(api.get_student(s_cd["id"], ADMIN))
        assert float(after["planned_credit_load"]) == pytest.approx(3.0)

    def test_execute_drop_cascades_to_audit_deficiency(self, api):
        """PRD §3.7: "`deficiency_credits` is the shortfall — the greater of
        zero and the difference between required and projected"
        PRD §3.7: "The student's `credit_deficient` flag simply reflects the
        latest audit: true exactly when that audit's `deficiency_credits` is
        positive"
        PRD §4: "Read the student's latest CreditAudit for a term, recomputed on
        read"

        Design: Difficulty/transitive_cascade/change_execute_cascade_to_audit_and_deficiency_flag
        """
        sc, s_cd, entry_x, crd = self._setup(api)
        publish_audit = validate_success(
            api.get_student_credit_audit(s_cd["id"], ADMIN), 200)
        assert float(publish_audit["deficiency_credits"]) == pytest.approx(0.0)
        get_success_data(api.execute_change_request(crd["id"], ADMIN))
        audit = validate_success(api.get_student_credit_audit(s_cd["id"], ADMIN), 200)
        assert float(audit["deficiency_credits"]) == pytest.approx(1.0), (
            f"22.0 - (18.0 + 3.0) = 1.0, got {audit['deficiency_credits']}"
        )
        student = get_success_data(api.get_student(s_cd["id"], ADMIN))
        assert student["credit_deficient"] is True


class TestRecoveryPlaceGatedBySectionState:
    def _setup(self, api):
        """ENG-099's only section sits at period 1, colliding with s_rec's
        period-1 AAA placement, so it stays empty through publish; a rebalance
        run then cancels it."""
        courses = [{"course_code": "REC-AAA", "subject_area": "ELECTIVE"},
                   {"course_code": "ENG-099", "subject_area": "ENGLISH"}]
        students = [{"ref": "REC1", "grade_level": 12, "earned_credits": 16.0,
                     "requests": [(0, 1), (1, 2)]}]
        section_specs = {0: [{"period": 1, "capacity": 32}],
                         1: [{"period": 1, "capacity": 32}]}
        sc = setup_change_window_scenario(
            courses=courses, students=students, section_specs=section_specs,
            term_code="2036-FALL", counselor_name="C Fourteen")
        drive_term_to_locked(sc["term"]["id"])
        eng_section = sc["sections"][1][0]
        assert eng_section["enrolled_count"] == 0
        version = get_term_version(sc["term"]["id"])
        run = get_success_data(api.create_rebalance_run(
            sc["term"]["id"], {"expected_term_version": version}, ADMIN))
        cancelled = get_success_data(api.get_section(eng_section["id"], ADMIN))
        assert cancelled["state"] == "CANCELLED"
        return sc

    def test_recovery_place_rejected_when_all_sections_cancelled(self, api):
        """PRD §3.7: "The recovery selector — the placement selector of §3.4 run
        for the target course — must return a section, or the placement fails
        with `ERR_RECOVERY_NO_SECTION` (HTTP 422)"
        PRD §3.4: "only sections in state `PUBLISHED` qualify" (the CANCELLED
        section drops out of the candidate set).

        Design: Difficulty/cross_entity_state_dependency/recovery_place_gated_by_section_state
        """
        sc = self._setup(api)
        counselor = sc["counselor"]
        s_rec = sc["students"][0]
        eng = sc["courses"][1]
        rp = validate_success(api.create_recovery_placement({
            "student_id": s_rec["id"], "term_id": sc["term"]["id"],
            "target_course_id": eng["id"],
        }, make_counselor_headers(counselor["id"])), 201)
        resp = api.place_recovery_placement(rp["id"], make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_RECOVERY_NO_SECTION, 422)

    def test_recovery_placement_remains_pending_after_rejection(self, api):
        """PRD §3.7: "The placement is born `PENDING` with its `section_id` null
        until placed" — a rejected place attempt performs no state transition.

        Design: Difficulty/cross_entity_state_dependency/recovery_place_gated_by_section_state
        """
        sc = self._setup(api)
        counselor = sc["counselor"]
        s_rec = sc["students"][0]
        eng = sc["courses"][1]
        rp = validate_success(api.create_recovery_placement({
            "student_id": s_rec["id"], "term_id": sc["term"]["id"],
            "target_course_id": eng["id"],
        }, make_counselor_headers(counselor["id"])), 201)
        api.place_recovery_placement(rp["id"], make_counselor_headers(counselor["id"]))
        current = validate_success(api.get_recovery_placement(rp["id"], ADMIN), 200)
        assert current["state"] == "PENDING"
        assert current["section_id"] is None


class TestRecoveryTerminalLockdown:
    def test_terminal_placement_lockdown(self, api):
        """PRD §3.7: "Placing the student is the counselor's move, valid from
        `PENDING`..." and "waiving settles the placement as `WAIVED`" — a WAIVED
        placement is no longer in the legal from-state for place.
        PRD §2.8: "then from-state legality on the target entity
        (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/terminal_placement_lockdown
        """
        courses = [{"course_code": "TRM-1", "subject_area": "ENGLISH"}]
        students = [{"ref": "TRM1", "grade_level": 12, "earned_credits": 10.0,
                     "requests": [(0, 1)]}]
        sc = setup_change_window_scenario(
            courses=courses, students=students,
            section_specs={0: [{"period": 1, "capacity": 32}]},
            term_code="2045-FALL", counselor_name="C Term", open_window=False)
        counselor = sc["counselor"]
        s_t = sc["students"][0]
        course = sc["courses"][0]
        rp = validate_success(api.create_recovery_placement({
            "student_id": s_t["id"], "term_id": sc["term"]["id"],
            "target_course_id": course["id"],
        }, make_counselor_headers(counselor["id"])), 201)
        assert rp["state"] == "PENDING"
        waived = validate_success(api.waive_recovery_placement(
            rp["id"], {"waiver_reason": "IEP team waives recovery this term"}, ADMIN), 200)
        assert waived["state"] == "WAIVED"
        resp = api.place_recovery_placement(rp["id"], make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
