"""Audit exceptions: the substitution/waiver approval chain — deny/resubmit
cycle, segregation of duties, enrollment-completion gating, approval cascade,
and revocation compensation (PRD §3.5).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    advisor_approve,
    advisor_deny,
    create_waiver_payload,
    declare,
    enroll,
    file_waiver,
    get_student_program,
    get_waiver,
    list_audits,
    make_advisor_headers,
    make_course,
    make_program,
    make_requirement_group,
    make_student,
    make_student_headers,
    registrar_approve,
    run_audit,
    setup_graduation_pipeline,
    validate_error,
    validate_success,
)


def _substitution_scenario(program_code="BS-CYC", enrollment_grade="A",
                           enrollment_term="2024-FA", requester="student"):
    """Program with one ELEC group eligible only for HIST201, a student with a
    PSY101 enrollment (ineligible course code), a declaration, and a SUBMITTED
    SUBSTITUTION waiver mapping the PSY101 enrollment into ELEC."""
    program = make_program(program_code=program_code, name=program_code,
                           min_total_credits=3, min_gpa=2.0,
                           catalog_year_start=2024, catalog_year_end=2028)
    group = make_requirement_group(
        program["id"], group_code="ELEC", required_credits=3, min_grade="D",
        eligible_course_codes=["HIST201"])
    course = make_course(course_code="PSY101", title="Psych", credits=3)
    student = make_student(student_number=f"S-{program_code}", legal_name="Cy Cole")
    enrollment = enroll(student["id"], course["id"], enrollment_term,
                        grade=enrollment_grade)
    sp = declare(student["id"], program["id"], catalog_year=2024)
    if requester == "student":
        waiver = file_waiver(sp["id"], group["id"], "SUBSTITUTION",
                             requester_role="student",
                             requester_student_id=student["id"],
                             enrollment_id=enrollment["id"], reason="advising plan")
    else:
        waiver = file_waiver(sp["id"], group["id"], "SUBSTITUTION",
                             requester_role="advisor", requester_advisor_id="adv-1",
                             enrollment_id=enrollment["id"], reason="advisor initiated")
    return program, group, course, student, enrollment, sp, waiver


class TestWaiverDenyResubmitCycle:
    def test_deny_then_resubmit_preserves_original_requester(self, api, registrar_headers):
        """PRD §3.5: "An `Advisor` or the owning `Student` may resubmit it, which
        moves `DENIED` back to `SUBMITTED` and may optionally change the
        `enrollment_id`, `credit_waiver_amount`, or `reason`; resubmission from
        any other state meets `ERR_WAIVER_INVALID_STATE`. Crucially, resubmission
        preserves the *original* `requested_by_role` and `requested_by_user_id`,
        so the segregation-of-duties anchor survives the rewrite — whoever
        resubmits does not become the requester of record."

        Design: Difficulty/non_linear_state_machine/waiver_deny_resubmit_cycle
        """
        _p, _g, _c, student, _e, _sp, waiver = _substitution_scenario()

        denied = advisor_deny(waiver["id"], advisor_id="adv-2", reason="not justified")
        assert denied["status"] == "DENIED"
        assert denied["decision_reason"] == "not justified"

        # The owning student resubmits; the requester-of-record stays the student
        # (who also filed originally), proving the rewrite does not re-anchor.
        resubmitted = validate_success(api.resubmit_waiver(
            waiver["id"], {"reason": "updated justification"},
            make_student_headers(student["id"])), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["requested_by_role"] == "STUDENT"
        assert resubmitted["requested_by_user_id"] == student["id"]

    def test_full_chain_to_revoked_and_revoked_is_terminal(self, api, registrar_headers):
        """PRD §3.5: "`RegistrarStaff` may revoke an `APPROVED` exception,
        supplying a `reason` that is recorded as the exception's
        `decision_reason`; the exception moves from `APPROVED` to its terminal
        state `REVOKED`."
        PRD §3.5: "First the state check — anything other than `SUBMITTED` is
        rejected with `ERR_WAIVER_INVALID_STATE`."

        Walks SUBMITTED -> DENIED -> SUBMITTED -> ADVISOR_APPROVED -> APPROVED ->
        REVOKED, then proves REVOKED is terminal.

        Design: Difficulty/non_linear_state_machine/waiver_deny_resubmit_cycle
        """
        _p, _g, _c, student, _e, _sp, waiver = _substitution_scenario()
        wid = waiver["id"]

        assert advisor_deny(wid, advisor_id="adv-2")["status"] == "DENIED"
        assert validate_success(api.resubmit_waiver(
            wid, {"reason": "updated justification"},
            make_student_headers(student["id"])), 200)["status"] == "SUBMITTED"
        assert advisor_approve(wid, advisor_id="adv-2")["status"] == "ADVISOR_APPROVED"
        assert registrar_approve(wid)["status"] == "APPROVED"
        revoked = validate_success(api.revoke_waiver(
            wid, {"reason": "entered in error"}, registrar_headers), 200)
        assert revoked["status"] == "REVOKED"

        res = api.advisor_decision(wid, {"decision": "APPROVE"},
                                   make_advisor_headers("adv-2"))
        validate_error(res, ApiErrorId.ERR_WAIVER_INVALID_STATE.value, expected_status=409)


class TestWaiverApprovalCascade:
    def _scenario(self):
        program = make_program(program_code="BS-WC", name="BS WC",
                               min_total_credits=3, min_gpa=2.0,
                               catalog_year_start=2024, catalog_year_end=2028)
        group = make_requirement_group(
            program["id"], group_code="ELEC", required_credits=3, min_grade="D",
            eligible_course_codes=["HIST201"])
        course = make_course(course_code="PSY101", title="Psych", credits=3)
        student = make_student(student_number="S-WC", legal_name="Wes Case")
        enrollment = enroll(student["id"], course["id"], "2024-FA", grade="A")
        sp = declare(student["id"], program["id"], catalog_year=2024)
        pre_audit = run_audit(sp["id"], "FINAL")
        waiver = file_waiver(sp["id"], group["id"], "SUBSTITUTION",
                             requester_role="student",
                             requester_student_id=student["id"],
                             enrollment_id=enrollment["id"], reason="content overlap")
        advisor_approve(waiver["id"], advisor_id="adv-2")
        return sp, waiver, pre_audit

    def test_registrar_approval_recomputes_current_final_audit(self, api, registrar_headers):
        """PRD §3.5: "Approval takes effect immediately: the `CURRENT` audits of
        the declaration are recomputed with the exception applied — substituted
        enrollments flow into their new group, waived amounts shrink the group's
        effective requirement — and `latest_audit_satisfied` refreshes from the
        `CURRENT` `FINAL` audit, incrementing the declaration's `version` when
        the flag changes."

        Pre-approval the FINAL audit is unsatisfied (ELEC 0/3, PSY101 ineligible);
        approval maps PSY101 into ELEC and the recomputed audit is satisfied.

        Design: Difficulty/transitive_cascade/waiver_approval_two_hop_audit_cascade
        """
        sp, waiver, pre_audit = self._scenario()
        assert pre_audit["overall_satisfied"] is False

        approved = registrar_approve(waiver["id"])
        assert approved["status"] == "APPROVED"

        audits, _meta = list_audits(sp["id"], audit_kind="FINAL", status="CURRENT")
        assert audits[0]["overall_satisfied"] is True
        groups = {g["group_code"]: g for g in audits[0]["groups_result"]}
        assert groups["ELEC"]["credits_applied"] == 3
        assert groups["ELEC"]["satisfied"] is True

    def test_approval_flips_latest_audit_satisfied(self, api, registrar_headers):
        """PRD §3.4: "After a `FINAL` audit is created or recomputed, the
        declaration's `latest_audit_satisfied` takes the audit's
        `overall_satisfied`, and the declaration's `version` increments whenever
        that flag changes" — the audit mutation caused by the approval bubbles up
        to the declaration's clearance flag.

        Design: Difficulty/transitive_cascade/waiver_approval_two_hop_audit_cascade
        """
        sp, waiver, pre_audit = self._scenario()
        assert pre_audit["overall_satisfied"] is False
        before = get_student_program(sp["id"])
        assert before["latest_audit_satisfied"] is False

        registrar_approve(waiver["id"])

        after = get_student_program(sp["id"])
        assert after["latest_audit_satisfied"] is True
        assert after["version"] > before["version"]


class TestSubstitutionEnrollmentGate:
    def test_advisor_decision_on_in_progress_enrollment_rejected(self, api, registrar_headers):
        """PRD §3.5: "Finally, for a `SUBSTITUTION`, the referenced enrollment
        must be `COMPLETED`; a substitution built on unfinished coursework is
        rejected with `ERR_ENROLLMENT_NOT_COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/substitution_decision_requires_completed_enrollment
        """
        _p, _g, _c, _s, enrollment, _sp, waiver = _substitution_scenario(
            program_code="BS-EC", enrollment_grade=None, enrollment_term="2026-SP")
        assert enrollment["status"] == "IN_PROGRESS"

        res = api.advisor_decision(waiver["id"], {"decision": "APPROVE"},
                                   make_advisor_headers("adv-9"))
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_COMPLETED.value, expected_status=422)
        assert get_waiver(waiver["id"])["status"] == "SUBMITTED"

    def test_registrar_decision_reexamines_enrollment_completion(self, api, registrar_headers):
        """PRD §3.5: "The state check again comes first (`ERR_WAIVER_INVALID_STATE`
        from any other state), and the completed-enrollment requirement is
        re-examined for substitutions (`ERR_ENROLLMENT_NOT_COMPLETED`) because
        grading may have moved on between the two steps."

        The enrollment is COMPLETED at the advisor step, then retroactively
        withdrawn (grade change to W) before the registrar step.

        Design: Difficulty/cross_entity_state_dependency/substitution_decision_requires_completed_enrollment
        """
        _p, _g, _c, _s, enrollment, _sp, waiver = _substitution_scenario(
            program_code="BS-EC")
        assert enrollment["status"] == "COMPLETED"
        advisor_approve(waiver["id"], advisor_id="adv-2")

        validate_success(api.change_grade(
            enrollment["id"], {"new_grade": "W", "reason": "retroactive withdrawal"},
            registrar_headers), 200)

        res = api.registrar_decision(waiver["id"], {"decision": "APPROVE"}, registrar_headers)
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_COMPLETED.value, expected_status=422)
        assert get_waiver(waiver["id"])["status"] == "ADVISOR_APPROVED"


class TestSegregationOfDutiesPriority:
    def test_self_approval_beats_enrollment_completion_check(self, api, registrar_headers):
        """PRD §3.5: "The guards fire in gatekeeping order. First the state check
        — anything other than `SUBMITTED` is rejected with
        `ERR_WAIVER_INVALID_STATE`. Then segregation of duties: when the original
        `requested_by_role` was `ADVISOR` and the deciding `X-User-ID` equals the
        recorded `requested_by_user_id`, the decision is refused with
        `ERR_SELF_APPROVAL_FORBIDDEN`, so an advisor can never adjudicate a
        request they filed themselves. Finally, for a `SUBSTITUTION`, the
        referenced enrollment must be `COMPLETED`; a substitution built on
        unfinished coursework is rejected with `ERR_ENROLLMENT_NOT_COMPLETED`."

        Here both later guards are violated (requester == decider, enrollment
        IN_PROGRESS); segregation of duties surfaces first.

        Design: Difficulty/priority_pair_validation_conflict/advisor_self_approval_before_referential
        """
        _p, _g, _c, _s, enrollment, _sp, waiver = _substitution_scenario(
            program_code="BS-SD", enrollment_grade=None, enrollment_term="2026-SP",
            requester="advisor")
        assert enrollment["status"] == "IN_PROGRESS"

        res = api.advisor_decision(waiver["id"], {"decision": "APPROVE"},
                                   make_advisor_headers("adv-1"))
        validate_error(res, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value, expected_status=403)

    def test_other_advisor_decision_surfaces_enrollment_check(self, api, registrar_headers):
        """PRD §3.5: "Then segregation of duties: when the original
        `requested_by_role` was `ADVISOR` and the deciding `X-User-ID` equals the
        recorded `requested_by_user_id`, the decision is refused with
        `ERR_SELF_APPROVAL_FORBIDDEN`" — a *different* advisor (adv-2) passes the
        segregation gate on the same advisor-filed request, so the
        completion check is the one that fires, proving the self-approval error
        is specific to the requester's identity. The failed self-approval attempt
        also leaves the exception SUBMITTED.

        Design: Difficulty/priority_pair_validation_conflict/advisor_self_approval_before_referential
        """
        _p, _g, _c, _s, _e, _sp, waiver = _substitution_scenario(
            program_code="BS-SD", enrollment_grade=None, enrollment_term="2026-SP",
            requester="advisor")

        validate_error(
            api.advisor_decision(waiver["id"], {"decision": "APPROVE"},
                                 make_advisor_headers("adv-1")),
            ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value, expected_status=403)
        assert get_waiver(waiver["id"])["status"] == "SUBMITTED"

        res = api.advisor_decision(waiver["id"], {"decision": "APPROVE"},
                                   make_advisor_headers("adv-2"))
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_COMPLETED.value, expected_status=422)


class TestWaiverFloorAndRevocation:
    def test_waiver_floors_effective_requirement_and_revoke_compensates(self, api, registrar_headers):
        """PRD §3.4: "For each requirement group of the target program, the
        **effective requirement** is the group's `required_credits` reduced by
        the sum of `credit_waiver_amount` across `APPROVED` `WAIVER` exceptions
        on that group, never below zero."
        PRD §3.5: "Revocation recomputes the `CURRENT` audits with the exception
        removed, compensating the approval exactly — group credits and
        `outstanding_credits` return to their pre-approval values — and refreshes
        `latest_audit_satisfied` from the `CURRENT` `FINAL` audit."

        A 5-credit waiver against a 3-credit group floors the effective
        requirement at 0 (max(0, 3-5)).

        Design: Corner/state_machines/waiver_amount_floor_zero_and_revoke_compensation
        """
        sc = setup_graduation_pipeline(
            program_overrides={
                "program_code": "BS-WV", "name": "BS WV",
                "min_total_credits": 3, "min_gpa": 1.0,
                "catalog_year_start": 2024, "catalog_year_end": 2028,
            },
            groups=[
                {"group_code": "G", "required_credits": 3, "min_grade": "C",
                 "eligible_course_codes": ["H201"]},
            ],
            student_overrides={"student_number": "S-WV", "legal_name": "Wyn Vee"},
            enrollment_specs=[{"course_code": "PSY101", "term": "2024-FA", "grade": "A"}],
            audit_kinds=("FINAL",),
        )
        assert sc.audits["FINAL"]["overall_satisfied"] is False

        waiver = file_waiver(sc.student_program["id"], sc.groups[0]["id"], "WAIVER",
                             requester_role="advisor", requester_advisor_id="adv-1",
                             credit_waiver_amount=5, reason="prior experience")
        advisor_approve(waiver["id"], advisor_id="adv-2")
        registrar_approve(waiver["id"])

        audits, _ = list_audits(sc.student_program["id"], audit_kind="FINAL", status="CURRENT")
        approved_audit = audits[0]
        groups = {g["group_code"]: g for g in approved_audit["groups_result"]}
        assert groups["G"]["effective_required_credits"] == 0
        assert groups["G"]["satisfied"] is True
        assert approved_audit["overall_satisfied"] is True

        validate_success(api.revoke_waiver(
            waiver["id"], {"reason": "approved in error"}, registrar_headers), 200)

        audits, _ = list_audits(sc.student_program["id"], audit_kind="FINAL", status="CURRENT")
        revoked_audit = audits[0]
        groups = {g["group_code"]: g for g in revoked_audit["groups_result"]}
        assert groups["G"]["effective_required_credits"] == 3
        assert groups["G"]["satisfied"] is False
        assert revoked_audit["overall_satisfied"] is False
