"""Student plans, course enrollments, and pathway gating.

PRD §3.2 (plans), §3.3 (enrollments), §2.7 (optimistic concurrency on plan
creation).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId, activate_plan, add_completed_enrollment,
    add_enrollment, assert_enrollment, assert_pct, create_active_plan,
    create_advisor, create_pathway, create_plan, create_student,
    create_student_payload, enroll_and_complete, get_plan, get_student,
    make_advisor_headers, setup_student_with_active_plan, validate_error,
    validate_success,
)

ADMIN = TEST_USERS["district_admin_headers"]


class TestPlanEditGating:
    def test_plan_patch_active_plan_returns_409(self, api):
        """PRD §3.2: "Editing a plan is permitted only while it is `DRAFT` or
        `REVISING`". PRD §2.6: "The entity sits in a from-state for the requested
        transition, and terminal lockdown holds. Failures yield
        `ERR_INVALID_STATE`".

        Design: Corner/entities/plan_patch_active_plan_returns_409
        """
        ctx = setup_student_with_active_plan()
        resp = api.patch_plan(
            ctx["plan"]["id"],
            {"interest_inventory": [{"interest_code": "ART", "score": 4}]},
            make_advisor_headers(ctx["advisor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_plan_revise_patch_reactivate_cycle(self, api):
        """PRD §3.2: "An `ACTIVE` plan may be sent into `REVISING` by its
        advisor to open a revision loop". PRD §3.2: "When `pathway_id`
        changes, the server first recomputes `counts_toward_pathway` across
        the student's enrollments and then re-derives the alignment and
        readiness figures, incrementing the plan's `version`."

        Design: Corner/state_machines/plan_revise_patch_reactivate_cycle
        """
        advisor = create_advisor(max_caseload=10)
        pw1 = create_pathway(pathway_code="GEN1", required_course_codes=["C1"])
        pw2 = create_pathway(pathway_code="GEN2", required_course_codes=["C2"])
        student = create_student(student_ref="RV1", advisor_id=advisor["id"])
        plan = create_active_plan(student, pw1["id"], advisor["id"])
        enrollment = add_completed_enrollment(student["id"], plan["id"],
                                              advisor["id"], "C1", 4, "A")

        revise = api.revise_plan(plan["id"],
                                 make_advisor_headers(advisor["id"]))
        assert validate_success(revise)["status"] == "REVISING"

        patched = api.patch_plan(plan["id"], {"pathway_id": pw2["id"]},
                                 make_advisor_headers(advisor["id"]))
        validate_success(patched)
        enr = validate_success(api.get_enrollment(enrollment["id"],
                                                  make_advisor_headers(
                                                      advisor["id"])))
        assert_enrollment(enr)
        assert enr["counts_toward_pathway"] is False, (
            "C1 is not in GEN2's required course codes"
        )

        reactivated = api.activate_plan(plan["id"],
                                        make_advisor_headers(advisor["id"]))
        assert validate_success(reactivated)["status"] == "ACTIVE"
        final = validate_success(api.get_plan(plan["id"],
                                              make_advisor_headers(
                                                  advisor["id"])))
        assert_pct(final["alignment_official_pct"], 0.0)


class TestEnrollmentLifecycle:
    def test_enrollment_completed_terminal_lockdown_returns_409(self, api):
        """PRD §3.3: "`COMPLETED` is terminal; nothing leaves it." PRD §2.6: "The entity sits in a
        from-state for the requested transition, and terminal lockdown
        holds. Failures yield `ERR_INVALID_STATE`".

        Design: Corner/state_machines/enrollment_completed_terminal_lockdown_returns_409
        """
        ctx = setup_student_with_active_plan()
        advisor_id = ctx["advisor"]["id"]
        enr = add_enrollment(ctx["student"]["id"], ctx["plan"]["id"],
                             advisor_id, "X1", 2)
        enroll_and_complete(enr["id"], advisor_id, "A")

        resp = api.transition_enrollment(enr["id"], {"to_status": "ENROLLED"},
                                         make_advisor_headers(advisor_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_enrollment(enr["id"], ADMIN))
        assert after["status"] == "COMPLETED"
        assert after["grade"] == "A"

    def test_derived_fields_reconcile_on_replan_loop(self, api):
        """PRD §3.2: "The provisional variant — stored as
        `alignment_provisional_pct` and used by the forward-looking advising
        view — counts `PLANNED`, `ENROLLED`, and `COMPLETED` enrollments as
        covering". PRD §3.3: "a `DROPPED` or `FAILED` enrollment may be
        returned to `PLANNED`, again gated on the owning plan being `ACTIVE`
        with `ERR_PLAN_NOT_ACTIVE` on violation, and each such move recomputes
        the plan's derived fields."

        Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_on_replan_loop
        """
        advisor = create_advisor(max_caseload=10)
        pathway = create_pathway(pathway_code="ONE",
                                 required_course_codes=["C1"])
        student = create_student(student_ref="DR1", advisor_id=advisor["id"])
        plan = create_active_plan(student, pathway["id"], advisor["id"])
        enr = add_enrollment(student["id"], plan["id"], advisor["id"],
                             "C1", 4)
        headers = make_advisor_headers(advisor["id"])

        api.transition_enrollment(enr["id"], {"to_status": "ENROLLED"},
                                  headers)
        while_enrolled = validate_success(api.get_plan(plan["id"], headers))
        assert_pct(while_enrolled["alignment_provisional_pct"], 100.0)

        api.transition_enrollment(enr["id"], {"to_status": "DROPPED"}, headers)
        while_dropped = validate_success(api.get_plan(plan["id"], headers))
        assert_pct(while_dropped["alignment_provisional_pct"], 0.0)

        api.transition_enrollment(enr["id"], {"to_status": "PLANNED"}, headers)
        replanned = validate_success(api.get_plan(plan["id"], headers))
        assert_pct(replanned["alignment_provisional_pct"], 100.0)


class TestPlanAndEnrollmentCreationGates:
    def test_enrollment_create_against_draft_plan_returns_409(self, api):
        """PRD §3.3: "The named plan must belong to the student and must be
        the student's `ACTIVE` plan at creation time; adding against a plan in
        any other status is rejected with `ERR_PLAN_NOT_ACTIVE`."

        Design: Corner/validations/enrollment_create_against_draft_plan_returns_409
        """
        advisor = create_advisor(max_caseload=10)
        pathway = create_pathway(pathway_code="GPN")
        student = create_student(student_ref="PN1", advisor_id=advisor["id"])
        plan = create_plan(student, pathway["id"], advisor["id"])
        assert plan["status"] == "DRAFT"

        resp = api.create_enrollment(
            student["id"],
            {"plan_id": plan["id"], "course_code": "X1",
             "term": "2026-SPRING", "credits": 2},
            make_advisor_headers(advisor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

    def test_retired_pathway_plan_create_returns_409(self, api):
        """PRD §3.2: "Retirement is prospective only: plans already targeting
        the pathway keep their snapshot, but any attempt to create a plan
        against, activate a plan on, or repoint a plan to a `RETIRED` pathway
        is rejected with `ERR_PATHWAY_NOT_ACTIVE`." PRD §2.4: "The `version`
        is an integer that starts at 1 when the resource is created and
        increments by exactly 1 on every mutation of that resource."

        Design: Corner/validations/retired_pathway_plan_create_returns_409
        """
        advisor = create_advisor(max_caseload=10)
        pathway = create_pathway(pathway_code="OLD")
        validate_success(api.patch_pathway(pathway["id"],
                                           {"status": "RETIRED"}, ADMIN))
        student = create_student(student_ref="RT1", advisor_id=advisor["id"])

        resp = api.create_plan(
            student["id"],
            {"pathway_id": pathway["id"],
             "expected_student_version": student["version"]},
            make_advisor_headers(advisor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PATHWAY_NOT_ACTIVE)
        assert get_student(student["id"])["version"] == student["version"], (
            "a rejected create is not a mutation and must not bump version"
        )

    def test_plan_create_for_withdrawn_student_returns_409(self, api):
        """PRD §3.2: "The student must be `ENROLLED` (else
        `ERR_STUDENT_NOT_ENROLLED`), the pathway must be `ACTIVE`, and the
        request must carry the OCC field `expected_student_version` per
        §2.7."

        Design: Corner/validations/plan_create_for_withdrawn_student_returns_409
        """
        advisor = create_advisor(max_caseload=10)
        pathway = create_pathway(pathway_code="GWS")
        student = create_student(student_ref="WS1", advisor_id=advisor["id"])
        validate_success(api.withdraw_student(student["id"],
                                              {"reason": "WITHDRAWN"}, ADMIN))
        fresh = get_student(student["id"])

        resp = api.create_plan(
            student["id"],
            {"pathway_id": pathway["id"],
             "expected_student_version": fresh["version"]},
            make_advisor_headers(advisor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ENROLLED)

    def test_stale_plan_create_returns_412(self, api):
        """PRD §2.7: "If the student's current `version` has advanced past
        that value — for instance because another plan was just created
        against the same student, which legitimately succeeds under product
        semantics — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the writer must re-read the student before retrying."

        Design: Corner/validations/stale_plan_create_returns_412
        """
        advisor = create_advisor(max_caseload=10)
        pathway = create_pathway(pathway_code="GOC")
        student = create_student(student_ref="OC1", advisor_id=advisor["id"])
        observed_version = student["version"]
        create_plan(student, pathway["id"], advisor["id"])

        resp = api.create_plan(
            student["id"],
            {"pathway_id": pathway["id"],
             "expected_student_version": observed_version},
            make_advisor_headers(advisor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        plans = validate_success(api.list_student_plans(student["id"], ADMIN))
        assert len(plans) == 1, "the stale create must not add a second plan"

    def test_duplicate_pathway_code_returns_409(self, api):
        """PRD §3.2: "A `DistrictAdmin` creates one with a unique
        `pathway_code` (such as STEM or HEALTH; collisions yield
        `ERR_DUPLICATE_CODE`)".

        Design: Corner/validations/duplicate_pathway_code_returns_409
        """
        create_pathway(pathway_code="STEM", name="STEM")
        resp = api.create_pathway(
            {"pathway_code": "STEM", "name": "STEM Again",
             "required_course_codes": []},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)


class TestActivePlanCardinality:
    """Difficulty instance: supersede keeps exactly one ACTIVE plan."""

    def _setup_two_plans(self):
        advisor = create_advisor(max_caseload=50)
        pathway = create_pathway(pathway_code="GENK")
        student = create_student(student_ref="K001", advisor_id=advisor["id"])
        plan1 = create_active_plan(student, pathway["id"], advisor["id"])
        plan2 = create_plan(student, pathway["id"], advisor["id"])
        activated2 = activate_plan(plan2["id"], advisor["id"])
        return advisor, pathway, student, plan1, activated2

    def test_supersede_transitions(self, api):
        """PRD §3.2: "Activation supersedes: any other `ACTIVE` plan belonging
        to the same student moves to `SUPERSEDED`, which is terminal."

        Design: Difficulty/compensating_invariant/active_plan_cardinality_conserved_on_supersede
        """
        advisor, pathway, student, plan1, plan2 = self._setup_two_plans()
        headers = make_advisor_headers(advisor["id"])
        p1_after = validate_success(api.get_plan(plan1["id"], headers))
        p2_after = validate_success(api.get_plan(plan2["id"], headers))
        assert p1_after["status"] == "SUPERSEDED"
        assert p2_after["status"] == "ACTIVE"

    def test_exactly_one_active_plan_conserved(self, api):
        """PRD §3.2: "Activation supersedes: any other `ACTIVE` plan belonging
        to the same student moves to `SUPERSEDED`, which is terminal."

        Design: Difficulty/compensating_invariant/active_plan_cardinality_conserved_on_supersede
        """
        advisor, pathway, student, plan1, plan2 = self._setup_two_plans()
        plans = validate_success(
            api.list_student_plans(student["id"],
                                   make_advisor_headers(advisor["id"])))
        active = [p for p in plans if p["status"] == "ACTIVE"]
        assert len(active) == 1, (
            f"expected exactly one ACTIVE plan, got {[p['id'] for p in active]}"
        )
        assert active[0]["id"] == plan2["id"]
