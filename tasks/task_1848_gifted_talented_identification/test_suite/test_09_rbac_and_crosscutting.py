"""RBAC gates, request-context headers, FK reachability, derived-field
reconciliation."""
from test_helpers import (
    CLOCK_TODAY,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    accept_placement,
    api_client,
    create_case,
    create_site,
    create_student,
    enter_measure,
    get_student,
    offer_placement,
    set_clock,
    setup_active_placement,
    setup_cycle_in_state,
    setup_honored_student,
    create_sped_plan,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_placement,
    make_committee_member_headers,
    make_parent_guardian_headers,
    make_referring_educator_headers,
)

GC = TEST_USERS["gifted_coordinator_headers"]


class TestAuthHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or empty, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."
        PRD §2.5: "Checks run in this priority order: 1. Header presence
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). 2. Role permission
        ... 4. Path-parameter existence, validated left-to-right
        (`ERR_NOT_FOUND`)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        # Even against a non-existent resource id, header presence (priority
        # 1) precedes existence (priority 4).
        resp = api.get_student(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


class TestRoleGates:
    def test_educator_cannot_create_cycle_returns_unauthorized(self, api):
        """PRD §4: "POST /gifted/screening-cycles — Create a screening cycle
        ... GiftedCoordinator".
        PRD §2.1: "If the named role is not permitted to call the endpoint —
        including the `review_kind`-conditional role rules described in §3 —
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/educator_cannot_create_cycle_returns_unauthorized
        """
        resp = api.create_screening_cycle(
            {"name": "Fall ES", "school_year": "2026-2027",
             "grade_band": "ELEMENTARY", "screening_open_on": "2026-08-15",
             "screening_close_on": "2026-12-15",
             "referral_close_on": "2026-09-30"},
            make_referring_educator_headers("edu-9"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_member_cannot_finalize_scoring_returns_unauthorized(self, api):
        """PRD §2.5: "2. Role permission for the endpoint, including
        `review_kind`-conditional roles (`ERR_INSUFFICIENT_PERMISSIONS`)."
        PRD §2.5: "4. Path-parameter existence, validated left-to-right
        (`ERR_NOT_FOUND`)."

        Design: Corner/rbac/member_cannot_finalize_scoring_returns_unauthorized
        """
        # The role check (priority 2) precedes existence (priority 4), so a
        # bogus case id still surfaces 403 rather than 404.
        resp = api.finalize_scoring(
            NON_EXISTENT_UUID, make_committee_member_headers("cm-9"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_coordinator_cannot_cast_vote_returns_unauthorized(self, api):
        """PRD §3.5: "Voting is the `CommitteeMember` role's exclusive act:
        the member supplies a `verdict` of `QUALIFY`, `DENY`, or `ABSTAIN`".
        PRD §2.1: "If the named role is not permitted to call the endpoint —
        including the `review_kind`-conditional role rules described in §3 —
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/coordinator_cannot_cast_vote_returns_unauthorized
        """
        resp = api.cast_vote(NON_EXISTENT_UUID, {"verdict": "QUALIFY"}, GC)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_parent_cannot_open_band_review_returns_unauthorized(self, api):
        """PRD §3.5: "A `BAND_REVIEW` may be opened only by a
        `GiftedCoordinator`".
        PRD §2.1: "If the named role is not permitted to call the endpoint —
        including the `review_kind`-conditional role rules described in §3 —
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/parent_cannot_open_band_review_returns_unauthorized
        """
        resp = api.create_committee_review(
            NON_EXISTENT_UUID,
            {"review_kind": "BAND_REVIEW", "grounds": "x"},
            make_parent_guardian_headers("guard-9"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestFkReverseReachability:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD §3.1: "A `SpecialEdCoordinator` registers a `SpedPlan` for a
        student by supplying a `plan_type` of `IEP` or `PLAN_504` and a
        `started_on` date; the record's `student_id` comes from the path."
        PRD §3.4: "each row's `case_id` comes from the path of the request,
        and the body carries a `measure_type` of `ABILITY`, `ACHIEVEMENT`,
        `RATING_SCALE`, or `PORTFOLIO`".

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        create_sped_plan(student["id"], plan_type="IEP",
                         started_on="2026-01-15")
        cycle, _ = setup_cycle_in_state("OPEN")
        case = create_case(student["id"], cycle["id"],
                           pathway="UNIVERSAL_SCREEN")
        enter_measure(case["id"], "ABILITY", 90)

        plans = validate_success(api.list_sped_plans(student["id"], GC), 200)
        assert len(plans) == 1
        assert plans[0]["plan_type"] == "IEP"
        assert plans[0]["student_id"] == student["id"]

        cases, meta = validate_paginated(
            api.list_cases(GC, params={"student_id": student["id"]}))
        assert meta["total_count"] == 1
        assert cases[0]["id"] == case["id"]

        scores = validate_success(api.list_measure_scores(case["id"], GC), 200)
        assert len(scores) == 1
        assert scores[0]["measure_type"] == "ABILITY"
        assert float(scores[0]["percentile"]) == 90


class TestGiftedStatusReconciliation:
    def test_gifted_status_reconciles_across_lifecycle(self, api):
        """PRD §3.1: "The student's `gifted_status` starts at
        `NOT_IDENTIFIED` and is only ever flipped by the workflows in §3.3,
        §3.4, and §3.6."
        PRD §3.3: "the student's `gifted_status` flips to `IDENTIFIED` in the
        same atomic create."
        PRD §3.6: "Either way the exit stamps `end_on` as today, flips the
        student's `gifted_status` to `EXITED`".

        Design: Corner/cross_cutting_layers/gifted_status_reconciles_across_lifecycle
        """
        ctx = setup_honored_student()  # clock at 2026-08-20, case honored
        stu_id = ctx["student"]["id"]
        # Enrollment state (captured before honoring): the create response in
        # the fixture already carried the initial status; re-derive it from
        # the fresh student read pattern — enroll a second student to observe
        # the pristine default without a case.
        other = create_student(ctx["site"]["id"], student_number="ST-2",
                               legal_name="Stu Two", grade_level=3,
                               primary_guardian_user_id="guard-2")
        assert other["gifted_status"] == "NOT_IDENTIFIED"

        assert get_student(stu_id)["gifted_status"] == "IDENTIFIED", (
            "transfer honoring flips gifted_status in the same request")

        placement = offer_placement(ctx["case"]["id"], ctx["site"]["id"],
                                    "PULL_OUT")
        accept_placement(placement["id"],
                         ctx["student"]["primary_guardian_user_id"])
        assert get_student(stu_id)["gifted_status"] == "IDENTIFIED"

        withdraw_placement(placement["id"])
        assert get_student(stu_id)["gifted_status"] == "EXITED", (
            "withdrawal flips gifted_status to EXITED in the same request")
