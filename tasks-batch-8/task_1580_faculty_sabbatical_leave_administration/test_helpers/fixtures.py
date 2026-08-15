"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
(the server is relaunched before each test) using only PRD-declared endpoints.
Setup calls use get_success_data so failures surface as clear setup errors.

The logical clock starts at 2026-08-01T00:00:00Z (PRD 2.5). Helpers only ever
move the clock forward.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_application_payload,
    create_coverage_plan_payload,
    create_cycle_payload,
    create_department_payload,
    create_faculty_payload,
    create_fellowship_payload,
    create_payment_payload,
    create_review_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_member_headers,
    make_department_chair_headers,
    make_faculty_headers,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]

SAB_START = "2027-01-01T00:00:00Z"
SAB_END = "2027-07-01T00:00:00Z"
SAB_END_2SEM = "2028-01-01T00:00:00Z"
HIRE_72 = "2020-08-01T00:00:00Z"  # one run at the default clock earns 72 months


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def create_department(name="Engineering", pool=160000.00) -> dict:
    return get_success_data(
        api_client.create_department(create_department_payload(name=name, replacement_pool=pool), ADMIN)
    )


def set_department_chair(department_id: str, chair_faculty_id: str) -> dict:
    return get_success_data(
        api_client.update_department(department_id, {"chair_faculty_id": chair_faculty_id}, ADMIN)
    )


def create_faculty(department_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_faculty_member(create_faculty_payload(department_id, **overrides), ADMIN)
    )


def run_accruals() -> dict:
    return get_success_data(api_client.run_accruals({}, ADMIN))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_cycle(award_quota=2, name="AY2027 Sabbaticals", academic_year="2027-2028") -> dict:
    return get_success_data(
        api_client.create_leave_cycle(
            create_cycle_payload(name=name, academic_year=academic_year, award_quota=award_quota),
            PROVOST,
        )
    )


def open_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.open_leave_cycle(cycle_id, PROVOST))


def close_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.close_leave_cycle(cycle_id, PROVOST))


def allocate_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.allocate_leave_cycle(cycle_id, PROVOST))


def create_application(faculty_id: str, **kwargs) -> dict:
    return get_success_data(
        api_client.create_leave_application(
            create_application_payload(**kwargs), make_faculty_headers(faculty_id)
        )
    )


def submit_application(application_id: str, faculty_id: str) -> dict:
    return get_success_data(
        api_client.submit_leave_application(application_id, make_faculty_headers(faculty_id))
    )


def decide_application(application_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_leave_application(application_id, {"decision": decision}, PROVOST)
    )


def create_submitted_review(
    application_id: str, reviewer_id: str, merit=80, curriculum=90, feasibility=70
) -> dict:
    review = get_success_data(
        api_client.create_committee_review(
            create_review_payload(application_id, merit, curriculum, feasibility),
            make_committee_member_headers(reviewer_id),
        )
    )
    return get_success_data(
        api_client.submit_committee_review(review["id"], make_committee_member_headers(reviewer_id))
    )


def get_application(application_id: str) -> dict:
    return get_success_data(api_client.get_leave_application(application_id, ADMIN))


def create_coverage_plan(application_id: str, chair_id: str, courses_to_cover: int,
                         supersedes_plan_id=None) -> dict:
    app = get_application(application_id)
    payload = create_coverage_plan_payload(
        application_id,
        courses_to_cover,
        expected_application_version=app["version"],
        supersedes_plan_id=supersedes_plan_id,
    )
    return get_success_data(
        api_client.create_coverage_plan(payload, make_department_chair_headers(chair_id))
    )


def submit_coverage_plan(plan_id: str, chair_id: str) -> dict:
    return get_success_data(
        api_client.submit_coverage_plan(plan_id, make_department_chair_headers(chair_id))
    )


def approve_coverage_plan(plan_id: str) -> dict:
    return get_success_data(api_client.approve_coverage_plan(plan_id, PROVOST))


def create_approved_plan(application_id: str, chair_id: str, courses_to_cover: int) -> dict:
    plan = create_coverage_plan(application_id, chair_id, courses_to_cover)
    submit_coverage_plan(plan["id"], chair_id)
    return approve_coverage_plan(plan["id"])


def grant_for_application(application_id: str) -> dict:
    grants, _meta = _list(api_client.list_leave_grants(ADMIN, params={"application_id": application_id}))
    assert len(grants) >= 1, f"Setup failed: no grant found for application {application_id}"
    return grants[0]


def _list(response):
    body = response.json()
    assert response.status_code == 200, f"Setup list call failed: {response.text}"
    return body["data"], body["meta"]


def activate_grant_at(grant_id: str, clock_iso: str) -> dict:
    set_clock(clock_iso)
    return get_success_data(api_client.activate_leave_grant(grant_id, ADMIN))


def complete_grant_at(grant_id: str, clock_iso: str) -> dict:
    set_clock(clock_iso)
    return get_success_data(api_client.complete_leave_grant(grant_id, ADMIN))


def separate_faculty(faculty_id: str, separation_date: str) -> dict:
    return get_success_data(
        api_client.separate_faculty_member(faculty_id, {"separation_date": separation_date}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1/2: department + faculty building blocks
# ---------------------------------------------------------------------------

def setup_department_with_chair(pool=160000.00, name="Engineering") -> dict:
    """Department with a chair faculty record wired in. Returns ctx dict."""
    dept = create_department(name=name, pool=pool)
    chair = create_faculty(
        dept["id"], academic_rank="FULL_PROFESSOR", hire_date="2010-01-01T00:00:00Z",
        annual_base_salary=150000.00,
    )
    set_department_chair(dept["id"], chair["id"])
    return {"department": dept, "chair": chair}


def setup_reviewers(count=3, department_name="Humanities") -> list:
    """A second department holding `count` reviewer faculty (cross-department)."""
    dept = create_department(name=department_name, pool=50000.00)
    reviewers = []
    for _ in range(count):
        reviewers.append(
            create_faculty(
                dept["id"], academic_rank="FULL_PROFESSOR",
                hire_date="2012-01-01T00:00:00Z", annual_base_salary=110000.00,
            )
        )
    return reviewers


def setup_faculty_with_credits(department_id: str, months_hire: str = HIRE_72,
                               salary=120000.00, rank="ASSOCIATE_PROFESSOR") -> dict:
    """Faculty hired at `months_hire`; caller must run accruals afterwards.

    With the default clock (2026-08-01) a hire date of 2020-08-01 earns 72
    EARN credits in a single accrual run; 2020-09-01 earns 71.
    """
    return create_faculty(
        department_id, hire_date=months_hire, annual_base_salary=salary, academic_rank=rank
    )


def setup_submitted_sabbatical_application(
    faculty_id: str, cycle_id: str, semesters=1, salary_pct=100,
    start=SAB_START, end=SAB_END,
) -> dict:
    """Create + submit a sabbatical application. Returns the UNDER_REVIEW application."""
    app = create_application(
        faculty_id,
        leave_type="SABBATICAL",
        cycle_id=cycle_id,
        requested_duration_semesters=semesters,
        requested_salary_pct=salary_pct,
        proposed_start_date=start,
        proposed_end_date=end,
    )
    return submit_application(app["id"], faculty_id)


# ---------------------------------------------------------------------------
# Tier 3: full sabbatical award pipeline
# ---------------------------------------------------------------------------

DEFAULT_REVIEW_SCORES = ((80, 90, 70), (90, 85, 95), (70, 60, 80))


def setup_full_award(
    courses_to_cover=5,
    award_quota=1,
    faculty_salary=120000.00,
    faculty_rank="ASSOCIATE_PROFESSOR",
    hire_date=HIRE_72,
    semesters=1,
    salary_pct=100,
    start=SAB_START,
    end=SAB_END,
    review_scores=DEFAULT_REVIEW_SCORES,
    pool=160000.00,
) -> dict:
    """Full sabbatical pipeline: department+chair, applicant with 72 credits,
    three cross-department submitted reviews, approved coverage plan, cycle
    closed and allocated. Returns ctx with department, chair, faculty,
    reviewers, cycle, application, plan, grant (SCHEDULED)."""
    base = setup_department_with_chair(pool=pool)
    dept, chair = base["department"], base["chair"]
    faculty = create_faculty(
        dept["id"], hire_date=hire_date, annual_base_salary=faculty_salary,
        academic_rank=faculty_rank,
    )
    reviewers = setup_reviewers(count=len(review_scores))
    run_accruals()
    cycle = open_cycle(create_cycle(award_quota=award_quota)["id"]) \
        if False else _open_new_cycle(award_quota)
    app = setup_submitted_sabbatical_application(
        faculty["id"], cycle["id"], semesters=semesters, salary_pct=salary_pct,
        start=start, end=end,
    )
    for reviewer, (m, c, f) in zip(reviewers, review_scores):
        create_submitted_review(app["id"], reviewer["id"], m, c, f)
    plan = create_approved_plan(app["id"], chair["id"], courses_to_cover)
    close_cycle(cycle["id"])
    cycle = allocate_cycle(cycle["id"])
    grant = grant_for_application(app["id"])
    return {
        "department": dept,
        "chair": chair,
        "faculty": create_faculty_member_fresh(faculty["id"]),
        "reviewers": reviewers,
        "cycle": cycle,
        "application": get_application(app["id"]),
        "plan": plan,
        "grant": grant,
    }


def _open_new_cycle(award_quota: int, name="AY2027 Sabbaticals",
                    academic_year="2027-2028") -> dict:
    cycle = create_cycle(award_quota=award_quota, name=name, academic_year=academic_year)
    return open_cycle(cycle["id"])


def create_faculty_member_fresh(faculty_id: str) -> dict:
    return get_success_data(api_client.get_faculty_member(faculty_id, ADMIN))


def setup_active_grant(**kwargs) -> dict:
    """Award pipeline + grant activated at its start date (clock moves forward)."""
    ctx = setup_full_award(**kwargs)
    ctx["grant"] = activate_grant_at(ctx["grant"]["id"], ctx["grant"]["start_date"])
    return ctx


def setup_completed_grant(**kwargs) -> dict:
    """Award pipeline + grant activated then completed at its end date."""
    ctx = setup_active_grant(**kwargs)
    ctx["grant"] = complete_grant_at(ctx["grant"]["id"], ctx["grant"]["end_date"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: non-sabbatical (PROFESSIONAL) pipeline — no cycle/reviews/plan
# ---------------------------------------------------------------------------

def setup_professional_grant(
    pool=160000.00, faculty_salary=120000.00, hire_date=HIRE_72,
    start="2027-01-01T00:00:00Z", end="2027-07-01T00:00:00Z",
    leave_type="PROFESSIONAL", salary_pct=None,
) -> dict:
    """Department + faculty + non-sabbatical application approved; grant SCHEDULED."""
    dept = create_department(pool=pool)
    faculty = create_faculty(dept["id"], hire_date=hire_date, annual_base_salary=faculty_salary)
    if salary_pct is None:
        salary_pct = 100 if leave_type == "PROFESSIONAL" else 0
    app = create_application(
        faculty["id"],
        leave_type=leave_type,
        requested_duration_semesters=1,
        requested_salary_pct=salary_pct,
        proposed_start_date=start,
        proposed_end_date=end,
    )
    submit_application(app["id"], faculty["id"])
    app = decide_application(app["id"], "APPROVED")
    grant = grant_for_application(app["id"])
    return {"department": dept, "faculty": faculty, "application": app, "grant": grant}


def setup_breached_repayment(
    completion_clock="2027-07-01T00:00:00Z",
    separation_date="2027-08-01T00:00:00Z",
    **kwargs,
) -> dict:
    """PROFESSIONAL grant activated + completed + faculty separated.

    Breach creates a RepaymentObligation with base = net salary 60000.00
    (no coverage plan on professional leave), fulfilled_months_at_breach 0,
    amount_owed 60000.00. Returns ctx including `repayment`.
    """
    ctx = setup_professional_grant(**kwargs)
    ctx["grant"] = activate_grant_at(ctx["grant"]["id"], "2027-01-01T00:00:00Z")
    ctx["grant"] = complete_grant_at(ctx["grant"]["id"], completion_clock)
    set_clock(separation_date)
    separate_faculty(ctx["faculty"]["id"], separation_date)
    repayments, _meta = _list(
        api_client.list_repayment_obligations(ADMIN, params={"faculty_id": ctx["faculty"]["id"]})
    )
    assert len(repayments) == 1, "Setup failed: expected exactly one repayment obligation"
    ctx["repayment"] = repayments[0]
    return ctx
