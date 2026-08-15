"""Coverage plan lifecycle: state gates, chair duties, supersede chain, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application,
    create_coverage_plan,
    create_coverage_plan_payload,
    create_cycle,
    create_department,
    create_faculty,
    create_review_payload,
    create_submitted_review,
    get_application,
    get_success_data,
    make_committee_member_headers,
    make_department_chair_headers,
    make_faculty_headers,
    open_cycle,
    run_accruals,
    set_department_chair,
    setup_department_with_chair,
    setup_reviewers,
    setup_submitted_sabbatical_application,
    submit_application,
    submit_coverage_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestPlanStateGates:
    def test_plan_state_gates_rejected(self, api):
        """PRD 3.5: "Approving moves `SUBMITTED` → `APPROVED`; the plan must be
        `SUBMITTED` (`ERR_INVALID_PLAN_STATE`)"
        PRD 3.5: "The provost's office may instead send a submitted plan back —
        `SUBMITTED` → `REVISION_REQUESTED`, requiring the `SUBMITTED`
        from-state and incrementing `version`"
        PRD 3.5: "the plan must be `DRAFT` (`ERR_INVALID_PLAN_STATE`)"

        Design: Corner/state_machines/plan_state_gates_rejected
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])
        plan = create_coverage_plan(app["id"], chair["id"], 3)

        approve_draft = api.approve_coverage_plan(plan["id"], PROVOST)
        validate_error(approve_draft, ApiErrorId.ERR_INVALID_PLAN_STATE)

        revise_draft = api.request_plan_revision(plan["id"], PROVOST)
        validate_error(revise_draft, ApiErrorId.ERR_INVALID_PLAN_STATE)

        submitted = validate_success(
            api.submit_coverage_plan(plan["id"], make_department_chair_headers(chair["id"]))
        )
        assert submitted["status"] == "SUBMITTED"

        resubmit = api.submit_coverage_plan(
            plan["id"], make_department_chair_headers(chair["id"])
        )
        validate_error(resubmit, ApiErrorId.ERR_INVALID_PLAN_STATE)


class TestChairDuties:
    def test_chair_mismatch_and_self_plan_segregation(self, api):
        """PRD 3.5: "the plan's creator may not be the applicant themselves
        (`ERR_SEGREGATION_OF_DUTIES`), and a chair may file only for the
        department they chair (`ERR_CHAIR_DEPARTMENT_MISMATCH`)."

        Design: Corner/validations/chair_mismatch_and_self_plan_segregation
        """
        d1 = create_department(name="Engineering")
        d2 = create_department(name="Humanities", pool=50000.00)
        ch1 = create_faculty(
            d1["id"], academic_rank="FULL_PROFESSOR",
            hire_date="2010-01-01T00:00:00Z", annual_base_salary=150000.00,
        )
        ch2 = create_faculty(
            d2["id"], academic_rank="FULL_PROFESSOR",
            hire_date="2020-08-01T00:00:00Z", annual_base_salary=140000.00,
        )
        set_department_chair(d1["id"], ch1["id"])
        set_department_chair(d2["id"], ch2["id"])
        faculty = create_faculty(d2["id"])
        run_accruals()
        cycle = open_cycle(create_cycle(award_quota=3)["id"])
        app_f = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])
        app_c = setup_submitted_sabbatical_application(ch2["id"], cycle["id"])

        # CH1 chairs D1 but the application belongs to D2.
        app_f_version = get_application(app_f["id"])["version"]
        wrong_dept = api.create_coverage_plan(
            create_coverage_plan_payload(app_f["id"], 2, app_f_version),
            make_department_chair_headers(ch1["id"]),
        )
        validate_error(wrong_dept, ApiErrorId.ERR_CHAIR_DEPARTMENT_MISMATCH)

        # CH2 chairs D2 but IS the applicant of app_c.
        app_c_version = get_application(app_c["id"])["version"]
        self_plan = api.create_coverage_plan(
            create_coverage_plan_payload(app_c["id"], 2, app_c_version),
            make_department_chair_headers(ch2["id"]),
        )
        validate_error(self_plan, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestSupersedeChain:
    def test_coverage_plan_supersede_chain(self, api):
        """PRD 3.5: "If the application already has a non-terminal plan — the
        plan named by `supersedes_plan_id` when given, otherwise the current
        one — and that plan sits in `DRAFT`, `SUBMITTED`, or
        `REVISION_REQUESTED`, it becomes `SUPERSEDED`; the application's
        `current_coverage_plan_id` re-points to the new draft and the
        application's `version` increments by one. When the superseded plan was
        the application's current plan and funding stood at
        `COVERAGE_SUBMITTED`, the application's `funding_status` falls back to
        `NONE`."
        PRD 3.5: "The plan's `provisional_cost` is computed at creation as the
        number of courses multiplied by 8,000.00 USD per course."

        Design: Corner/endpoints/coverage_plan_supersede_chain
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])

        plan1 = create_coverage_plan(app["id"], chair["id"], 3)
        submit_coverage_plan(plan1["id"], chair["id"])

        app_v = get_application(app["id"])["version"]
        plan2 = validate_success(
            api.create_coverage_plan(
                create_coverage_plan_payload(
                    app["id"], 4, app_v, supersedes_plan_id=plan1["id"]
                ),
                make_department_chair_headers(chair["id"]),
            ),
            expected_status=201,
        )
        assert plan2["provisional_cost"] == pytest.approx(32000.00, abs=0.005)

        plan1_after = validate_success(api.get_coverage_plan(plan1["id"], ADMIN))
        assert plan1_after["status"] == "SUPERSEDED"

        chained, _ = validate_paginated(
            api.list_coverage_plans(ADMIN, params={"supersedes_plan_id": plan1["id"]})
        )
        assert [p["id"] for p in chained] == [plan2["id"]]

        app_after = get_application(app["id"])
        assert app_after["current_coverage_plan_id"] == plan2["id"]
        assert app_after["funding_status"] == "NONE"


class TestCoveragePlanOcc:
    def test_occ_coverage_create_stale_application_version(self, api):
        """PRD 2.8: "Creating a coverage plan requires the request to carry
        `expected_application_version`, holding the `version` of the target
        leave application as the caller last observed it. If the application's
        current `version` has advanced past that value — for example because
        another writer filed a superseding plan, which itself mutates the
        application — the creation is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_coverage_create_stale_application_version
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])

        stale_version = get_application(app["id"])["version"]
        plan1 = validate_success(
            api.create_coverage_plan(
                create_coverage_plan_payload(app["id"], 3, stale_version),
                make_department_chair_headers(chair["id"]),
            ),
            expected_status=201,
        )
        assert plan1["status"] == "DRAFT"

        stale = api.create_coverage_plan(
            create_coverage_plan_payload(app["id"], 4, stale_version),
            make_department_chair_headers(chair["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        plans, _ = validate_paginated(
            api.list_coverage_plans(ADMIN, params={"application_id": app["id"]})
        )
        assert len(plans) == 1


class TestFilteredListReverseReachability:
    def test_filtered_list_reverse_reachability(self, api):
        """PRD 3.3: "Applications can be listed filtered by
        `applicant_faculty_id`, `cycle_id`, `status`, or `leave_type`."
        PRD 3.4: "Reviews can be listed filtered by `application_id`,
        `reviewer_faculty_id`, or `status`."
        PRD 3.5: "plans are listed filtered by `application_id`"

        Design: Corner/endpoints/filtered_list_reverse_reachability
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        fa = create_faculty(dept["id"])
        fb = create_faculty(
            dept["id"], academic_rank="ASSISTANT_PROFESSOR", annual_base_salary=100000.00
        )
        reviewers = setup_reviewers(count=1)
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app_a = setup_submitted_sabbatical_application(fa["id"], cycle["id"])
        app_b = setup_submitted_sabbatical_application(fb["id"], cycle["id"])
        review = get_success_data(
            api.create_committee_review(
                create_review_payload(app_a["id"], 80, 90, 70),
                make_committee_member_headers(reviewers[0]["id"]),
            )
        )
        plan_a = create_coverage_plan(app_a["id"], chair["id"], 3)

        apps, _ = validate_paginated(
            api.list_leave_applications(
                ADMIN, params={"applicant_faculty_id": fa["id"], "cycle_id": cycle["id"]}
            )
        )
        assert [a["id"] for a in apps] == [app_a["id"]]

        reviews_a, _ = validate_paginated(
            api.list_committee_reviews(ADMIN, params={"application_id": app_a["id"]})
        )
        assert [r["id"] for r in reviews_a] == [review["id"]]

        reviews_b, _ = validate_paginated(
            api.list_committee_reviews(ADMIN, params={"application_id": app_b["id"]})
        )
        assert reviews_b == []

        plans_a, _ = validate_paginated(
            api.list_coverage_plans(ADMIN, params={"application_id": app_a["id"]})
        )
        assert [p["id"] for p in plans_a] == [plan_a["id"]]
