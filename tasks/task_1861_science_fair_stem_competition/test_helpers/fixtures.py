"""Composite setup helpers for the Science Fair API test suite.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup step failed"
errors.

Ordering note: judges are always recruited and ACTIVATED while the edition is
in REGISTRATION_CLOSED, because PRD §3.4 permits activation only while the
edition is in SETUP, REGISTRATION_OPEN, or REGISTRATION_CLOSED.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_MAX_JUDGES_PER_PROJECT,
    DEFAULT_MIN_QUORUM_RATIO_PCT,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .factories import (
    award_payload,
    booth_payload,
    category_payload,
    ethics_decision_payload,
    fair_edition_payload,
    inspection_result_payload,
    judge_payload,
    mentor_payload,
    project_payload,
    research_plan_payload,
    scholarship_pool_payload,
    score_sheet_payload,
)
from .test_users import TEST_USERS, make_judge_headers, make_mentor_headers


# --- header shortcuts (opaque roles) ------------------------------------------
def fd_headers():
    return TEST_USERS["fair_director_headers"]


def er_headers():
    return TEST_USERS["ethics_reviewer_headers"]


def ops_headers():
    return TEST_USERS["operations_lead_headers"]


def si_headers():
    return TEST_USERS["safety_inspector_headers"]


# --- granular builders ----------------------------------------------------------
def create_edition(
    name="Test Edition",
    algorithm="Z_SCORE",
    max_judges=DEFAULT_MAX_JUDGES_PER_PROJECT,
    quorum_pct=DEFAULT_MIN_QUORUM_RATIO_PCT,
):
    """Create a fair edition (born SETUP, advancement_freeze false)."""
    resp = api_client.create_fair_edition(
        fair_edition_payload(
            name=name,
            normalization_algorithm=algorithm,
            max_judges_per_project=max_judges,
            min_quorum_ratio_pct=quorum_pct,
        ),
        fd_headers(),
    )
    return get_success_data(resp, 201)


def add_category(edition_id, code="PHYS", name=None, grade_band="SENIOR", slots=1):
    resp = api_client.create_category(
        category_payload(
            edition_id,
            code=code,
            name=name or f"Category {code}",
            grade_band=grade_band,
            advancement_slots=slots,
        ),
        fd_headers(),
    )
    return get_success_data(resp, 201)


def add_mentor(full_name="Mentor A", email=None):
    resp = api_client.create_mentor(mentor_payload(full_name=full_name, email=email), fd_headers())
    return get_success_data(resp, 201)


def open_registration(edition_id):
    return get_success_data(api_client.open_registration(edition_id, fd_headers()))


def register_project(
    edition_id,
    category_id,
    mentor_id,
    title="Project",
    team_size=1,
    human=False,
    animal=False,
):
    """Register a DRAFT project; the acting mentor's identity becomes mentor_id."""
    resp = api_client.create_project(
        project_payload(
            edition_id,
            category_id,
            title=title,
            team_size=team_size,
            involves_human_subjects=human,
            involves_animal_subjects=animal,
        ),
        make_mentor_headers(mentor_id),
    )
    return get_success_data(resp, 201)


def submit_project(project_id, mentor_id):
    return get_success_data(api_client.submit_project(project_id, make_mentor_headers(mentor_id)))


def withdraw_project(project_id, mentor_id):
    return get_success_data(api_client.withdraw_project(project_id, make_mentor_headers(mentor_id)))


def close_registration(edition_id):
    return get_success_data(api_client.close_registration(edition_id, fd_headers()))


def add_active_judge(edition_id, full_name="Judge", max_assignments=9, expertise=None):
    """Recruit a judge and activate them. Caller must ensure the edition is in
    SETUP / REGISTRATION_OPEN / REGISTRATION_CLOSED (PRD §3.4)."""
    judge = get_success_data(
        api_client.create_judge(
            judge_payload(
                edition_id,
                full_name=full_name,
                max_assignments=max_assignments,
                expertise_category_ids=expertise,
            ),
            fd_headers(),
        ),
        201,
    )
    get_success_data(api_client.activate_judge(judge["id"], fd_headers()))
    return get_judge(judge["id"])


def schedule_booth(
    project_id,
    hall="A",
    booth_number=1,
    window_start=DEFAULT_WINDOW_START,
    window_end=DEFAULT_WINDOW_END,
):
    resp = api_client.create_booth_assignment(
        project_id,
        booth_payload(
            hall=hall,
            booth_number=booth_number,
            inspection_window_start=window_start,
            inspection_window_end=window_end,
        ),
        ops_headers(),
    )
    return get_success_data(resp, 201)


def record_inspection(project_id, result="PASS"):
    return get_success_data(
        api_client.record_inspection_result(project_id, inspection_result_payload(result), si_headers())
    )


def begin_judging(edition_id):
    return get_success_data(api_client.begin_judging(edition_id, fd_headers()))


def assign_judge(project_id, judge_id):
    """Explicit-mode assignment by the FairDirector."""
    resp = api_client.create_judging_assignment(project_id, {"judge_id": judge_id}, fd_headers())
    return get_success_data(resp, 201)


def submit_score(assignment_id, judge_id, raw_score):
    """Judge submits a score sheet on their own assignment; returns the sheet."""
    resp = api_client.submit_score_sheet(
        assignment_id, score_sheet_payload(raw_score), make_judge_headers(judge_id)
    )
    return get_success_data(resp, 201)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, fd_headers()))


def get_edition(edition_id):
    return get_success_data(api_client.get_fair_edition(edition_id, fd_headers()))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, fd_headers()))


def get_mentor(mentor_id):
    return get_success_data(api_client.get_mentor(mentor_id, fd_headers()))


def get_judge(judge_id):
    return get_success_data(api_client.get_judge(judge_id, fd_headers()))


def get_plan(plan_id):
    return get_success_data(api_client.get_research_plan(plan_id, fd_headers()))


def get_award(award_id):
    return get_success_data(api_client.get_award(award_id, fd_headers()))


def get_pool(pool_id):
    return get_success_data(api_client.get_scholarship_pool(pool_id, fd_headers()))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_judging_assignment(assignment_id, fd_headers()))


def get_sheet(sheet_id):
    return get_success_data(api_client.get_score_sheet(sheet_id, fd_headers()))


def get_category(category_id):
    return get_success_data(api_client.get_category(category_id, fd_headers()))


def current_edition_version(edition_id):
    return get_edition(edition_id)["version"]


def publish_advancement(edition_id, expected_version=None):
    """Publish advancement, reading the current edition version when not given."""
    version = expected_version if expected_version is not None else current_edition_version(edition_id)
    return get_success_data(
        api_client.publish_advancement(
            edition_id, {"expected_fair_edition_version": version}, fd_headers()
        )
    )


def propose_award(edition_id, project_id, award_type):
    return get_success_data(
        api_client.create_award(award_payload(edition_id, project_id, award_type), fd_headers()), 201
    )


def create_pool(edition_id, total_cents):
    return get_success_data(
        api_client.create_scholarship_pool(
            scholarship_pool_payload(edition_id, total_cents), fd_headers()
        ),
        201,
    )


def finalize_awards(edition_id):
    return get_success_data(api_client.finalize_awards(edition_id, fd_headers()))


# --- Tier 1/2 composites ---------------------------------------------------------

def setup_open_edition(
    name="Edition",
    algorithm="Z_SCORE",
    max_judges=DEFAULT_MAX_JUDGES_PER_PROJECT,
    quorum_pct=DEFAULT_MIN_QUORUM_RATIO_PCT,
    slots=1,
    code="PHYS",
):
    """Edition in REGISTRATION_OPEN with one OPEN category and one mentor.

    Returns dict(edition, category, mentor).
    """
    edition = create_edition(name=name, algorithm=algorithm, max_judges=max_judges, quorum_pct=quorum_pct)
    category = add_category(edition["id"], code=code, slots=slots)
    mentor = add_mentor(full_name=f"{name} Mentor")
    edition = open_registration(edition["id"])
    return {"edition": edition, "category": category, "mentor": mentor}


def setup_registration_closed(
    num_projects=1,
    slots=1,
    algorithm="Z_SCORE",
    max_judges=DEFAULT_MAX_JUDGES_PER_PROJECT,
    quorum_pct=DEFAULT_MIN_QUORUM_RATIO_PCT,
    code="PHYS",
    name="Edition",
    project_titles=None,
):
    """Edition driven REGISTRATION_OPEN -> REGISTRATION_CLOSED with
    num_projects submitted projects (CONFIRMED after the closing sweep).

    Returns dict(edition, category, mentor, projects).
    """
    ctx = setup_open_edition(
        name=name, algorithm=algorithm, max_judges=max_judges, quorum_pct=quorum_pct,
        slots=slots, code=code,
    )
    projects = []
    for i in range(num_projects):
        title = (project_titles or [])[i] if project_titles else f"P{i + 1}"
        project = register_project(
            ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"], title=title
        )
        submit_project(project["id"], ctx["mentor"]["id"])
        projects.append(project)
    edition = close_registration(ctx["edition"]["id"])
    # Re-read after the closing sweep: PRD 3.2 confirms SUBMITTED projects
    # whose ethics_status is APPROVED/NOT_REQUIRED, so the post-sweep readback
    # (CONFIRMED, version bumped by the cascade) is the state callers expect.
    projects = [get_project(p["id"]) for p in projects]
    return {
        "edition": edition,
        "category": ctx["category"],
        "mentor": ctx["mentor"],
        "projects": projects,
    }


def setup_judging(
    num_projects=1,
    slots=1,
    algorithm="Z_SCORE",
    max_judges=DEFAULT_MAX_JUDGES_PER_PROJECT,
    quorum_pct=DEFAULT_MIN_QUORUM_RATIO_PCT,
    judges_spec=None,
    inspection="pass",
    code="PHYS",
    name="Judging Edition",
):
    """Full path to JUDGING: projects CONFIRMED, booths scheduled and (by
    default) inspections PASSED, judges recruited and ACTIVATED while the
    edition is still REGISTRATION_CLOSED, then begin-judging.

    judges_spec: list of dicts {full_name, max_assignments, expertise};
        defaults to two generic ACTIVE judges with max_assignments=9.
        Pass [] for no judges.
    inspection: "pass" | "schedule" | "none" applied to every project.

    Returns dict(edition, category, mentor, projects, judges).
    """
    ctx = setup_registration_closed(
        num_projects=num_projects, slots=slots, algorithm=algorithm,
        max_judges=max_judges, quorum_pct=quorum_pct, code=code, name=name,
    )
    edition_id = ctx["edition"]["id"]

    # Judges first: activation is only legal before the judging phase opens.
    spec = judges_spec if judges_spec is not None else [
        {"full_name": "Judge 1", "max_assignments": 9},
        {"full_name": "Judge 2", "max_assignments": 9},
    ]
    judges = [
        add_active_judge(
            edition_id,
            full_name=j.get("full_name", f"Judge {i + 1}"),
            max_assignments=j.get("max_assignments", 9),
            expertise=j.get("expertise"),
        )
        for i, j in enumerate(spec)
    ]

    if inspection != "none":
        for i, project in enumerate(ctx["projects"]):
            schedule_booth(project["id"], hall="A", booth_number=i + 1)
            if inspection == "pass":
                record_inspection(project["id"], "PASS")

    edition = begin_judging(edition_id)
    return {
        "edition": edition,
        "category": ctx["category"],
        "mentor": ctx["mentor"],
        "projects": ctx["projects"],
        "judges": judges,
    }


def judge_project_fully(project_id, judge_raw_pairs):
    """Assign + submit one sheet per (judge, raw_score) pair. Returns sheets."""
    sheets = []
    for judge, raw in judge_raw_pairs:
        assignment = assign_judge(project_id, judge["id"])
        sheets.append(submit_score(assignment["id"], judge["id"], raw))
    return sheets


def setup_publishable(slots=1, raws=(80, 85), name="Publishable Edition"):
    """Edition in JUDGING with one fully judged project (max_judges=2).

    Returns dict(edition, category, mentor, project, judges, assignments).
    """
    ctx = setup_judging(num_projects=1, slots=slots, name=name)
    project = ctx["projects"][0]
    judges = ctx["judges"]
    assignments = []
    for judge, raw in zip(judges, raws):
        assignment = assign_judge(project["id"], judge["id"])
        submit_score(assignment["id"], judge["id"], raw)
        assignments.append(assignment)
    ctx["project"] = get_project(project["id"])
    ctx["assignments"] = assignments
    return ctx


def setup_partially_judged(name="Partial Edition"):
    """Edition in JUDGING with one CONFIRMED+PASSED project carrying exactly
    one submitted sheet out of the two required (judging_status ASSIGNED)."""
    ctx = setup_judging(
        num_projects=1,
        judges_spec=[{"full_name": "Judge 1", "max_assignments": 9}],
        name=name,
    )
    project = ctx["projects"][0]
    judge = ctx["judges"][0]
    assignment = assign_judge(project["id"], judge["id"])
    submit_score(assignment["id"], judge["id"], 80)
    ctx["project"] = get_project(project["id"])
    ctx["assignment"] = assignment
    return ctx


def setup_project_with_plan(human=True, animal=False, plan_risk="LOW"):
    """REGISTRATION_OPEN edition; a project declaring subjects, a DRAFT
    research plan, and a distinct reviewer mentor (for committee decisions).

    Returns dict(edition, category, mentor, reviewer, project, plan).
    """
    ctx = setup_open_edition(name="Ethics Edition", code="BME")
    reviewer = add_mentor(full_name="Reviewer Mentor")
    project = register_project(
        ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"],
        title="Subjects Study", team_size=2, human=human, animal=animal,
    )
    plan = get_success_data(
        api_client.create_research_plan(
            research_plan_payload(project["id"], plan_text="plan v1", risk_level=plan_risk),
            make_mentor_headers(ctx["mentor"]["id"]),
        ),
        201,
    )
    ctx.update({"reviewer": reviewer, "project": get_project(project["id"]), "plan": plan})
    return ctx


def setup_plan_under_review(human=True, animal=False, plan_risk="LOW"):
    """As setup_project_with_plan, plus plan submitted and UNDER_REVIEW, and
    the parent project itself SUBMITTED (ethics PENDING)."""
    ctx = setup_project_with_plan(human=human, animal=animal, plan_risk=plan_risk)
    mentor_id = ctx["mentor"]["id"]
    get_success_data(api_client.submit_research_plan(ctx["plan"]["id"], make_mentor_headers(mentor_id)))
    submit_project(ctx["project"]["id"], mentor_id)
    get_success_data(api_client.begin_review(ctx["plan"]["id"], er_headers()))
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def record_decision(plan_id, reviewer_mentor_id, decision, rationale=None):
    """Raw ethics-decision call (may succeed or fail); returns the Response."""
    return api_client.record_ethics_decision(
        plan_id,
        ethics_decision_payload(reviewer_mentor_id, decision, rationale=rationale),
        er_headers(),
    )


def drive_revision_loop(ctx):
    """Run the full revision cycle on ctx's plan: SUBMITTED -> UNDER_REVIEW ->
    REQUEST_REVISION -> (plan_text edit) DRAFT -> SUBMITTED -> UNDER_REVIEW ->
    APPROVE. Returns the final plan and project readbacks."""
    mentor_id = ctx["mentor"]["id"]
    reviewer_id = ctx["reviewer"]["id"]
    plan_id = ctx["plan"]["id"]

    get_success_data(api_client.submit_research_plan(plan_id, make_mentor_headers(mentor_id)))
    get_success_data(api_client.begin_review(plan_id, er_headers()))
    get_success_data(
        record_decision(plan_id, reviewer_id, "REQUEST_REVISION", rationale="needs consent form"),
        201,
    )
    get_success_data(
        api_client.update_research_plan(
            plan_id, {"plan_text": "v2 plan with consent"}, make_mentor_headers(mentor_id)
        )
    )
    get_success_data(api_client.submit_research_plan(plan_id, make_mentor_headers(mentor_id)))
    get_success_data(api_client.begin_review(plan_id, er_headers()))
    get_success_data(record_decision(plan_id, reviewer_id, "APPROVE"), 201)
    return get_plan(plan_id), get_project(ctx["project"]["id"])
