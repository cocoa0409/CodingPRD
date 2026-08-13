"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so each helper builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() so failures
surface as clear "Setup failed" errors.

Identity threading: after creating a StaffMember, every ownership- or
segregation-gated call uses make_*_headers(staff["id"]) — never the shared
TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    consent_response_payload,
    create_accommodation_payload,
    create_grievance_payload,
    create_plan_payload,
    create_referral_payload,
    create_review_payload,
    create_school_payload,
    create_staff_member_payload,
    create_student_payload,
    create_testing_request_payload,
    create_training_record_payload,
    determine_evaluation_payload,
)
from .test_users import (
    TEST_USERS,
    make_coordinator_headers,
    make_parent_headers,
    make_teacher_headers,
)


def _setup_fail(step: str, response) -> AssertionError:
    return AssertionError(f"Setup failed at {step}: {response.status_code} {response.text}")


def _ok(step: str, response):
    data = get_success_data(response)
    if response.status_code >= 400:
        raise _setup_fail(step, response)
    return data


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.5)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["director_headers"])
    if resp.status_code >= 400:
        raise _setup_fail("set_clock", resp)
    return get_success_data(resp)


def create_school(**overrides) -> dict:
    resp = api_client.create_school(create_school_payload(**overrides), TEST_USERS["director_headers"])
    if resp.status_code >= 400:
        raise _setup_fail("create_school", resp)
    return get_success_data(resp)


def create_staff(school_id: str, staff_role: str, trained_at: str = None, **overrides) -> dict:
    """Register a staff member; when trained_at is given, also record a training
    completion so current_training_status becomes TRAINED_CURRENT (PRD §3.1)."""
    resp = api_client.create_staff_member(
        create_staff_member_payload(school_id, staff_role, **overrides),
        TEST_USERS["director_headers"],
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_staff", resp)
    staff = get_success_data(resp)
    if trained_at is not None:
        train_staff(staff["id"], trained_at)
        staff = get_success_data(api_client.get_staff_member(staff["id"], TEST_USERS["director_headers"]))
    return staff


def train_staff(staff_id: str, trained_at: str, **overrides) -> dict:
    resp = api_client.create_training_record(
        create_training_record_payload(staff_id, trained_at, **overrides),
        TEST_USERS["director_headers"],
    )
    if resp.status_code >= 400:
        raise _setup_fail("train_staff", resp)
    return get_success_data(resp)


def create_student_for(school_id: str, coordinator_id: str, **overrides) -> dict:
    resp = api_client.create_student(
        create_student_payload(school_id, **overrides),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_student", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: referral / evaluation progression
# ---------------------------------------------------------------------------

def submit_referral(student_id: str, submitted_by_staff_id: str, role: str = "Teacher", **overrides) -> dict:
    """Submit a referral; submitted_by_staff_id is stamped from X-User-ID (PRD §3.2)."""
    if role == "Teacher":
        headers = make_teacher_headers(submitted_by_staff_id)
    else:
        headers = make_coordinator_headers(submitted_by_staff_id)
    resp = api_client.create_referral(create_referral_payload(student_id, **overrides), headers)
    if resp.status_code >= 400:
        raise _setup_fail("submit_referral", resp)
    return get_success_data(resp)


def start_referral_review(referral_id: str, coordinator_id: str) -> dict:
    resp = api_client.start_referral_review(referral_id, make_coordinator_headers(coordinator_id))
    if resp.status_code >= 400:
        raise _setup_fail("start_referral_review", resp)
    return get_success_data(resp)


def initiate_evaluation(referral_id: str, coordinator_id: str, supersedes_evaluation_id: str = None) -> dict:
    payload = {}
    if supersedes_evaluation_id is not None:
        payload["supersedes_evaluation_id"] = supersedes_evaluation_id
    resp = api_client.initiate_evaluation(referral_id, payload, make_coordinator_headers(coordinator_id))
    if resp.status_code >= 400:
        raise _setup_fail("initiate_evaluation", resp)
    return get_success_data(resp)


def drive_evaluation_to_consent_received(evaluation_id: str, coordinator_id: str, parent_ref: str = "parent-1") -> dict:
    """request-consent then record-consent(granted) — evaluation lands in CONSENT_RECEIVED."""
    resp = api_client.request_evaluation_consent(evaluation_id, make_coordinator_headers(coordinator_id))
    if resp.status_code >= 400:
        raise _setup_fail("request_evaluation_consent", resp)
    resp = api_client.record_evaluation_consent(
        evaluation_id,
        consent_response_payload(granted=True, responded_by_parent_ref=parent_ref),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("record_evaluation_consent", resp)
    return get_success_data(resp)


def start_evaluation_now(evaluation_id: str, coordinator_id: str) -> dict:
    resp = api_client.start_evaluation(evaluation_id, make_coordinator_headers(coordinator_id))
    if resp.status_code >= 400:
        raise _setup_fail("start_evaluation", resp)
    return get_success_data(resp)


def determine_evaluation(evaluation_id: str, coordinator_id: str, **overrides) -> dict:
    resp = api_client.determine_evaluation(
        evaluation_id,
        determine_evaluation_payload(**overrides),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("determine_evaluation", resp)
    return get_success_data(resp)


def pipeline_to_determination(student_id: str, referral: dict, coordinator_id: str, **determine_overrides) -> dict:
    """UNDER_REVIEW referral -> initiated -> consent granted -> started -> determined."""
    start_referral_review(referral["id"], coordinator_id)
    evaluation = initiate_evaluation(referral["id"], coordinator_id)
    drive_evaluation_to_consent_received(evaluation["id"], coordinator_id)
    start_evaluation_now(evaluation["id"], coordinator_id)
    return determine_evaluation(evaluation["id"], coordinator_id, **determine_overrides)


# ---------------------------------------------------------------------------
# Tier 2: plan drafting and activation
# ---------------------------------------------------------------------------

def get_student_version(student_id: str, coordinator_id: str) -> int:
    student = get_success_data(api_client.get_student(student_id, make_coordinator_headers(coordinator_id)))
    return student["version"]


def get_plan_version(plan_id: str, coordinator_id: str) -> int:
    plan = get_success_data(api_client.get_plan(plan_id, make_coordinator_headers(coordinator_id)))
    return plan["version"]


def create_draft_plan(student_id: str, evaluation_id: str, coordinator_id: str) -> dict:
    """POST /plans is OCC-guarded on the student's version (PRD §2.7); read it first."""
    student_version = get_student_version(student_id, coordinator_id)
    resp = api_client.create_plan(
        create_plan_payload(student_id, evaluation_id, student_version),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_draft_plan", resp)
    return get_success_data(resp)


def add_accommodation(plan_id: str, coordinator_id: str, **overrides) -> dict:
    resp = api_client.create_accommodation(
        create_accommodation_payload(plan_id, **overrides),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("add_accommodation", resp)
    return get_success_data(resp)


def submit_plan(plan_id: str, coordinator_id: str) -> dict:
    """submit-for-consent is OCC-guarded on the plan's version (PRD §2.7); read it first."""
    plan_version = get_plan_version(plan_id, coordinator_id)
    resp = api_client.submit_plan_for_consent(
        plan_id,
        {"expected_plan_version": plan_version},
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("submit_plan", resp)
    return get_success_data(resp)


def grant_plan_parent_consent(plan_id: str, coordinator_id: str, parent_ref: str = "parent-1") -> dict:
    resp = api_client.record_plan_parent_consent(
        plan_id,
        consent_response_payload(granted=True, responded_by_parent_ref=parent_ref),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("grant_plan_parent_consent", resp)
    return get_success_data(resp)


def acknowledge_all_pending_acks(plan_id: str, coordinator_id: str):
    """Acknowledge every PENDING row on the plan as the named teacher.

    Ownership is checked against X-User-ID == row.staff_id (PRD §2.9), so each
    row is answered with make_teacher_headers(row["staff_id"]).
    """
    co_headers = make_coordinator_headers(coordinator_id)
    acks = get_success_data(
        api_client.list_teacher_acks(co_headers, params={"plan_id": plan_id, "ack_status": "PENDING"})
    )
    for ack in acks:
        resp = api_client.acknowledge_teacher_ack(ack["id"], make_teacher_headers(ack["staff_id"]))
        if resp.status_code >= 400:
            raise _setup_fail(f"acknowledge_teacher_ack({ack['id']})", resp)


def activate_plan(plan_id: str, coordinator_id: str) -> dict:
    """submit-for-consent -> parent grant -> all teachers acknowledge -> ACTIVE."""
    submit_plan(plan_id, coordinator_id)
    grant_plan_parent_consent(plan_id, coordinator_id)
    acknowledge_all_pending_acks(plan_id, coordinator_id)
    return get_success_data(api_client.get_plan(plan_id, make_coordinator_headers(coordinator_id)))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle — school + staff + student + ELIGIBLE evaluation +
#         DRAFT plan + one accommodation + ACTIVE plan
# ---------------------------------------------------------------------------

def setup_school_with_staff(
    school_name="Lincoln High",
    clock_initial="2025-12-15T00:00:00Z",
    num_teachers=1,
    include_director=False,
    train_all=True,
    trained_at=None,
) -> dict:
    """School + coordinator + teachers (+ optional district-director staff).

    By default every staff member is trained (trained_at defaults to the day
    after clock_initial) so training coverage is 100% and no training gap leaks
    into posture-sensitive assertions (PRD §2.10/§3.1).
    """
    set_clock(clock_initial)
    school = create_school(school_name=school_name)
    trained_at = trained_at or "2025-12-16T00:00:00Z"
    train_at = trained_at if train_all else None
    coordinator = create_staff(school["id"], "COORDINATOR", trained_at=train_at,
                               staff_external_ref="CO-1", full_name="Coordinator One")
    teachers = []
    for i in range(num_teachers):
        teachers.append(create_staff(
            school["id"], "TEACHER", trained_at=train_at,
            staff_external_ref=f"T-{i + 1}", full_name=f"Teacher {i + 1}",
        ))
    director = None
    if include_director:
        director = create_staff(school["id"], "DISTRICT_DIRECTOR", trained_at=train_at,
                                staff_external_ref="DIR-1", full_name="Director One")
    return {
        "school": school,
        "coordinator": coordinator,
        "teachers": teachers,
        "teacher": teachers[0] if teachers else None,
        "director": director,
    }


def setup_active_plan(
    school_name="Lincoln High",
    clock_initial="2025-12-15T00:00:00Z",
    activate_at="2026-01-01T00:00:00Z",
    applies_to_testing=False,
    accommodation_type="EXTENDED_TIME",
    include_director=False,
    referral_submitter="teacher",
    train_all=True,
    trained_at=None,
) -> dict:
    """Full pipeline: school -> staff -> student -> referral -> ELIGIBLE
    determination -> DRAFT plan -> one accommodation -> consent -> acks ->
    ACTIVE plan (plan_effective_date stamped at `activate_at`).

    The referral is submitted by the first teacher by default so the
    coordinator's determination satisfies segregation of duties (PRD §2.9).
    """
    ctx = setup_school_with_staff(
        school_name=school_name,
        clock_initial=clock_initial,
        num_teachers=1,
        include_director=include_director,
        train_all=train_all,
        trained_at=trained_at,
    )
    co = ctx["coordinator"]
    teacher = ctx["teacher"]
    student = create_student_for(ctx["school"]["id"], co["id"])
    if referral_submitter == "teacher":
        referral = submit_referral(student["id"], teacher["id"], role="Teacher")
    else:
        referral = submit_referral(student["id"], co["id"], role="Section504Coordinator")
    evaluation = pipeline_to_determination(student["id"], referral, co["id"])
    plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
    accommodation = add_accommodation(
        plan["id"], co["id"],
        accommodation_type=accommodation_type,
        applies_to_testing=applies_to_testing,
    )
    if activate_at is not None:
        set_clock(activate_at)
    plan = activate_plan(plan["id"], co["id"])
    ctx.update({
        "student": get_success_data(api_client.get_student(student["id"], make_coordinator_headers(co["id"]))),
        "referral": referral,
        "evaluation": evaluation,
        "plan": plan,
        "accommodation": accommodation,
    })
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: reviews / testing requests / logs / grievances on top of a plan
# ---------------------------------------------------------------------------

def schedule_review(plan_id: str, coordinator_id: str, scheduled_for: str, review_type: str = "ANNUAL") -> dict:
    resp = api_client.create_review(
        create_review_payload(plan_id, scheduled_for, review_type=review_type),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("schedule_review", resp)
    return get_success_data(resp)


def start_review_now(review_id: str, coordinator_id: str) -> dict:
    resp = api_client.start_review(review_id, make_coordinator_headers(coordinator_id))
    if resp.status_code >= 400:
        raise _setup_fail("start_review", resp)
    return get_success_data(resp)


def complete_review(review_id: str, coordinator_id: str, outcome: str) -> dict:
    resp = api_client.complete_review(review_id, {"outcome": outcome}, make_coordinator_headers(coordinator_id))
    if resp.status_code >= 400:
        raise _setup_fail("complete_review", resp)
    return get_success_data(resp)


def create_testing_request(plan_id: str, accommodation_id: str, coordinator_id: str, test_date: str, **overrides) -> dict:
    resp = api_client.create_testing_request(
        create_testing_request_payload(plan_id, accommodation_id, test_date, **overrides),
        make_coordinator_headers(coordinator_id),
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_testing_request", resp)
    return get_success_data(resp)


def log_implementation(plan_id: str, accommodation_id: str, log_date: str, staff_id: str,
                       was_implemented_as_planned=True, role="Teacher", **overrides) -> dict:
    from .factories import create_implementation_log_payload
    headers = make_teacher_headers(staff_id) if role == "Teacher" else make_coordinator_headers(staff_id)
    resp = api_client.create_implementation_log(
        create_implementation_log_payload(
            plan_id, accommodation_id, log_date,
            was_implemented_as_planned=was_implemented_as_planned, **overrides,
        ),
        headers,
    )
    if resp.status_code >= 400:
        raise _setup_fail("log_implementation", resp)
    return get_success_data(resp)


def suspend_plan_with_low_compliance(ctx: dict) -> dict:
    """File one deviation log (trailing pct -> 0.0 < 60) then suspend (PRD §3.5).

    The log's `log_date` must fall inside the trailing 30-day window
    [clock - 30 days, clock] at suspend time (PRD §3.5: "the inclusive window
    from 30 days before the current clock instant through the instant
    itself"). The fixture clock still sits at the plan's activation instant,
    so the log is dated at `plan_effective_date` — dating it later than the
    clock would place it outside the window and leave the ratio at 100.
    """
    co = ctx["coordinator"]
    plan = ctx["plan"]
    log_date = plan.get("plan_effective_date") or "2026-01-01T00:00:00Z"
    log_implementation(
        plan["id"], ctx["accommodation"]["id"], log_date,
        ctx["teacher"]["id"], was_implemented_as_planned=False,
        deviation_notes="Sub forgot extended time",
    )
    resp = api_client.suspend_plan(plan["id"], {"justification": "low compliance"}, make_coordinator_headers(co["id"]))
    if resp.status_code >= 400:
        raise _setup_fail("suspend_plan", resp)
    return get_success_data(resp)


def file_grievance(student_id: str, parent_ref: str = "parent-1", **overrides) -> dict:
    resp = api_client.create_grievance(
        create_grievance_payload(student_id, filed_by_parent_ref=parent_ref, **overrides),
        make_parent_headers(parent_ref),
    )
    if resp.status_code >= 400:
        raise _setup_fail("file_grievance", resp)
    return get_success_data(resp)


def get_school_posture_snapshot(school_id: str, coordinator_id: str = None) -> dict:
    """GET /schools/{id}/compliance-summary as coordinator (or bootstrap director)."""
    headers = make_coordinator_headers(coordinator_id) if coordinator_id else TEST_USERS["director_headers"]
    resp = api_client.get_school_compliance_summary(school_id, headers)
    if resp.status_code >= 400:
        raise _setup_fail("get_school_compliance_summary", resp)
    return get_success_data(resp)
