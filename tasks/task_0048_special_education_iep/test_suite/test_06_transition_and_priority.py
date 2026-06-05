"""Transition planning (age gate, adopt-requires-active) and the cross-validation
priority pairs whose precedence the PRD pins explicitly in §2.8 (state before
cross-entity business; FK-existence before structural body validation).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_admin_headers,
    make_case_manager_headers,
    create_goal_payload,
    create_transition_plan_payload,
    set_clock,
    create_student,
    make_eligible_student,
    make_draft_iep_for_eligible_student,
    make_active_iep,
    create_draft_iep,
    create_transition_plan,
    open_amendment_payload,
)

ADMIN = make_admin_headers("adm_1")
CM = make_case_manager_headers("cm_1")


class TestTransitionAdoptRequiresActive:
    def test_adopt_plan_when_iep_amendment_pending_rejected(self, api):
        """PRD §3.9: "Adoption requires the plan to be in `DRAFT` and additionally requires the parent program to currently be `ACTIVE`; if the parent program is not active, adoption is rejected with `ERR_IEP_NOT_ACTIVE` (HTTP 409)."

        A DRAFT plan whose parent IEP has since moved to AMENDMENT_PENDING cannot be
        adopted.

        Design: Difficulty/cross_entity_state_dependency/transition_plan_adopt_requires_iep_active
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep, _plc = make_active_iep(
            student_overrides={"full_name": "Yara Bell", "date_of_birth": "2008-03-01",
                               "grade_level": 11},
        )
        tp = create_transition_plan(iep["id"])
        validate_success(
            api.open_amendment(iep["id"], open_amendment_payload(iep["version"]), CM), 200
        )
        validate_error(
            api.adopt_transition_plan(tp["id"], CM),
            ApiErrorId.ERR_IEP_NOT_ACTIVE.value,
        )

    def test_adopt_plan_while_iep_active_succeeds(self, api):
        """PRD §3.9: "Adopting a transition plan moves it `DRAFT → ADOPTED`, which is terminal and is performed by a `CaseManager`."
        PRD §3.9: "Adoption requires the plan to be in `DRAFT` and additionally requires the parent program to currently be `ACTIVE`"

        While the parent IEP is ACTIVE, a DRAFT plan adopts cleanly to ADOPTED — the
        positive complement of the IEP-not-active guard.

        Design: Difficulty/cross_entity_state_dependency/transition_plan_adopt_requires_iep_active
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep, _plc = make_active_iep(
            student_overrides={"full_name": "Yara Bell2", "date_of_birth": "2008-03-01",
                               "grade_level": 11},
        )
        tp = create_transition_plan(iep["id"])
        adopted = validate_success(api.adopt_transition_plan(tp["id"], CM), 200)
        assert adopted["status"] == "ADOPTED", adopted["status"]


class TestTransitionAgeGate:
    def test_transition_plan_under_16_rejected(self, api):
        """PRD §3.9: "A transition plan may be created only when the student is old enough: the student's age at the current server-clock instant — the number of full years between the student's `date_of_birth` and the server clock — must be at least 16. A younger student is rejected with `ERR_TRANSITION_AGE_NOT_MET` (HTTP 409)."

        A student born 2013-01-01 is 13 at the 2026 clock → rejected.

        Design: Corner/state_machines/transition_plan_age_under_16_returns_age_not_met
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = make_draft_iep_for_eligible_student(
            student_overrides={"full_name": "Cal Webb", "date_of_birth": "2013-01-01",
                               "grade_level": 7},
        )
        validate_error(
            api.create_transition_plan(
                create_transition_plan_payload(
                    iep["id"], postsecondary_goal="College",
                    services_summary="Self-advocacy training",
                ),
                CM,
            ),
            ApiErrorId.ERR_TRANSITION_AGE_NOT_MET.value,
        )


class TestPriorityStateVsConsent:
    def test_activate_draft_without_consent_returns_invalid_state(self, api):
        """PRD §2.8: "Only after a request is structurally sound does the system evaluate state: whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`) ... Finally, the cross-entity business guards — consent status, student eligibility, parent-program status, transition age, and the single-active-program rule — are evaluated."
        PRD §2.8: "a state error is rejected before a cross-entity business error."

        A DRAFT IEP (wrong state for activate) with no GRANTED placement consent fails
        both the state check (pri 30) and the consent check (pri 42); the higher-
        priority ERR_INVALID_STATE is returned.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_consent_on_iep_activate
        """
        set_clock("2026-03-01T09:00:00Z")
        student = make_eligible_student(student_overrides={
            "full_name": "Nia Fox", "date_of_birth": "2014-11-11", "grade_level": 6})
        iep = create_draft_iep(student["id"])  # DRAFT, no PLACEMENT consent at all
        validate_error(
            api.activate_iep(iep["id"], ADMIN),
            ApiErrorId.ERR_INVALID_STATE.value,
        )

    def test_state_outranks_consent_on_activate(self, api):
        """PRD §2.8: "a state error is rejected before a cross-entity business error."

        Re-confirms precedence: when the activate target is in DRAFT (a state from
        which activate is undefined) and its placement consent is also un-granted, the
        state error wins over the consent error.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_consent_on_iep_activate
        """
        set_clock("2026-03-01T09:00:00Z")
        student = make_eligible_student(student_overrides={
            "full_name": "Nia Fox2", "date_of_birth": "2014-11-11", "grade_level": 6})
        iep = create_draft_iep(student["id"])
        validate_error(
            api.activate_iep(iep["id"], ADMIN),
            ApiErrorId.ERR_INVALID_STATE.value,
        )


class TestPriorityFkVsConstraint:
    def test_goal_create_bad_fk_and_missing_field_returns_fk_not_found(self, api):
        """PRD §2.8: "existence of every resource named in the path is checked (`ERR_NOT_FOUND`), followed by the existence of every foreign key referenced in the body (`ERR_FK_NOT_FOUND`). Structural validation of the body comes next: required fields must be present and well-typed ... (`ERR_INVALID_REQUEST`)"

        A POST /goals that both names a non-existent iep_id and omits target_value
        fails the body-FK existence check (pri 11) before the structural check (pri
        20); ERR_FK_NOT_FOUND is returned.

        Design: Difficulty/priority_pair_validation_conflict/fk_referential_vs_constraint_on_goal_create_rejected
        """
        validate_error(
            api.create_goal(
                {"iep_id": "00000000-0000-4000-8000-000000000000",
                 "domain": "READING", "baseline_value": 0},
                CM,
            ),
            ApiErrorId.ERR_FK_NOT_FOUND.value,
        )

    def test_fk_existence_outranks_structural_validation_on_goal(self, api):
        """PRD §2.8: "the existence of every foreign key referenced in the body (`ERR_FK_NOT_FOUND`). Structural validation of the body comes next"

        Re-confirms ordering: a body-FK that does not resolve is reported as
        ERR_FK_NOT_FOUND even though the same body also omits a required field that
        would otherwise yield ERR_INVALID_REQUEST.

        Design: Difficulty/priority_pair_validation_conflict/fk_referential_vs_constraint_on_goal_create_rejected
        """
        validate_error(
            api.create_goal(
                {"iep_id": "00000000-0000-4000-8000-000000000000",
                 "domain": "MATH", "baseline_value": 10},
                CM,
            ),
            ApiErrorId.ERR_FK_NOT_FOUND.value,
        )
