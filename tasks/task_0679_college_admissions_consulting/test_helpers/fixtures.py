"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty database before
every test). Fixtures use get_success_data() (lenient) internally so setup
failures surface as clear "Setup failed" errors.

Identity threading: Counselor and Student are entity_backed roles, so every
ownership-gated call uses make_counselor_headers(counselor_id) /
make_student_headers(student_id) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_counselor_headers, make_student_headers, make_admin_headers
from . import factories as f


# --------------------------------------------------------------------------
# Tier 0: primitives
# --------------------------------------------------------------------------
def create_counselor(**overrides):
    """Create a Counselor (as PlatformAdmin). Returns the counselor dict."""
    resp = api_client.create_counselor(f.create_counselor_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_student(counselor_id, **overrides):
    """Create a Student owned by counselor_id. Returns the student dict."""
    resp = api_client.create_student(
        f.create_student_payload(counselor_id, **overrides),
        make_counselor_headers(counselor_id),
    )
    return get_success_data(resp)


def add_activity(counselor_id, student_id, **overrides):
    resp = api_client.create_activity(
        f.create_activity_payload(student_id, **overrides),
        make_counselor_headers(counselor_id),
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(f.set_clock_payload(to_iso8601), make_admin_headers())
    return resp


# --------------------------------------------------------------------------
# Tier 1: state progression — onboarded students
# --------------------------------------------------------------------------
def setup_counselor_and_student(student_overrides=None, counselor_overrides=None):
    """Create a Counselor and a PROSPECT Student owned by them.
    Returns (counselor, student)."""
    counselor = create_counselor(**(counselor_overrides or {}))
    student = create_student(counselor["id"], **(student_overrides or {}))
    return counselor, student


def setup_onboarded_student(student_overrides=None, counselor_overrides=None,
                            activity_overrides=None):
    """Create counselor + student, add one activity, transition to ONBOARDED.
    Returns (counselor, student) where student is the post-onboarding snapshot
    (carrying the recomputed profile_strength and the bumped version)."""
    counselor, student = setup_counselor_and_student(student_overrides, counselor_overrides)
    add_activity(counselor["id"], student["id"], **(activity_overrides or {}))
    resp = api_client.transition_student(
        student["id"], {"to_status": "ONBOARDED"}, make_counselor_headers(counselor["id"])
    )
    onboarded = get_success_data(resp)
    return counselor, onboarded


# --------------------------------------------------------------------------
# Tier 2 / 3: active contracts
# --------------------------------------------------------------------------
def setup_active_contract(billing_model="HOURLY", contract_overrides=None,
                          student_overrides=None, counselor_overrides=None,
                          activity_overrides=None):
    """Onboard a student then create + activate a contract.
    Returns (counselor, student, contract) where student/contract are the
    post-activation snapshots. The contract is ACTIVE."""
    counselor, student = setup_onboarded_student(student_overrides, counselor_overrides,
                                                 activity_overrides)
    ch = make_counselor_headers(counselor["id"])
    contract_resp = api_client.create_contract(
        f.create_contract_payload(student["id"], billing_model, **(contract_overrides or {})), ch
    )
    contract = get_success_data(contract_resp)
    act_resp = api_client.activate_contract(
        contract["id"], {"expected_student_version": student["version"]}, ch
    )
    active_contract = get_success_data(act_resp)
    # Re-fetch student to capture the bubbled-up version.
    student = get_success_data(api_client.get_student(student["id"], ch))
    return counselor, student, active_contract


# --------------------------------------------------------------------------
# Tier 2: school list + application progression
# --------------------------------------------------------------------------
def select_school(counselor_id, student, school_overrides=None):
    """Create a CANDIDATE school for `student`, select it (OCC-guarded), and
    return (item, new_student_version). `student` must carry a current version."""
    ch = make_counselor_headers(counselor_id)
    item = get_success_data(
        api_client.create_school_list_item(
            f.create_school_list_item_payload(student["id"], **(school_overrides or {})), ch
        )
    )
    sel = get_success_data(
        api_client.select_school_list_item(
            item["id"], {"expected_student_version": student["version"]}, ch
        )
    )
    new_version = student["version"] + 1
    return sel, new_version


def setup_application(counselor_id, student, round="RD", deadline_utc="2027-01-01T00:00:00Z",
                      school_overrides=None):
    """Onboarded student -> select one school -> create one Application.
    Returns (application, school_item, student_version_after_select)."""
    ch = make_counselor_headers(counselor_id)
    item, version_after_select = select_school(counselor_id, student, school_overrides)
    app = get_success_data(
        api_client.create_application(
            f.create_application_payload(student["id"], item["id"], round, deadline_utc=deadline_utc),
            ch,
        )
    )
    return app, item, version_after_select


def setup_application_in_progress(round="RD", deadline_utc="2027-01-01T00:00:00Z",
                                  student_overrides=None, counselor_overrides=None):
    """Onboarded student with a SELECTED school and an Application in
    prep_status IN_PROGRESS (start-prep called).
    Returns (counselor, student, application)."""
    counselor, student = setup_onboarded_student(student_overrides, counselor_overrides)
    ch = make_counselor_headers(counselor["id"])
    app, _item, _v = setup_application(counselor["id"], student, round, deadline_utc)
    app = get_success_data(api_client.start_prep_application(app["id"], ch))
    return counselor, student, app


def setup_application_ready(round="RD", deadline_utc="2027-01-01T00:00:00Z",
                            student_overrides=None, counselor_overrides=None):
    """Onboarded student, SELECTED school, Application IN_PROGRESS with no open
    tasks, then mark-ready -> prep_status READY.
    Returns (counselor, student, application)."""
    counselor, student, app = setup_application_in_progress(
        round, deadline_utc, student_overrides, counselor_overrides
    )
    ch = make_counselor_headers(counselor["id"])
    app = get_success_data(api_client.mark_ready_application(app["id"], ch))
    return counselor, student, app


def setup_application_submitted(round="RD", deadline_utc="2027-01-01T00:00:00Z",
                                submit_clock="2026-12-01T00:00:00Z",
                                student_overrides=None, counselor_overrides=None):
    """Application taken all the way to prep_status SUBMITTED (clock advanced to
    submit_clock, which must be before deadline). Leaves the clock at submit_clock.
    Returns (counselor, student, application)."""
    counselor, student, app = setup_application_ready(
        round, deadline_utc, student_overrides, counselor_overrides
    )
    ch = make_counselor_headers(counselor["id"])
    set_clock(submit_clock)
    app = get_success_data(api_client.submit_application(app["id"], ch))
    return counselor, student, app


def setup_application_admitted(round="RD", deadline_utc="2027-01-01T00:00:00Z",
                               submit_clock="2026-12-01T00:00:00Z",
                               student_overrides=None, counselor_overrides=None):
    """Application SUBMITTED then decision recorded ADMITTED.
    Returns (counselor, student, application)."""
    counselor, student, app = setup_application_submitted(
        round, deadline_utc, submit_clock, student_overrides, counselor_overrides
    )
    ch = make_counselor_headers(counselor["id"])
    app = get_success_data(api_client.record_decision(app["id"], {"decision": "ADMITTED"}, ch))
    return counselor, student, app


# --------------------------------------------------------------------------
# Tier 3: essays
# --------------------------------------------------------------------------
def create_essay(student_id, student_role_id=None, **overrides):
    """Create an essay as the Student (default) — returns the essay dict."""
    acting = student_role_id or student_id
    resp = api_client.create_essay(
        f.create_essay_payload(student_id, **overrides), make_student_headers(acting)
    )
    return get_success_data(resp)


def setup_essay_drafting(student_overrides=None, counselor_overrides=None, essay_overrides=None):
    """Onboarded-not-required: counselor + student + a DRAFTING essay.
    Returns (counselor, student, essay)."""
    counselor, student = setup_counselor_and_student(student_overrides, counselor_overrides)
    essay = create_essay(student["id"], **(essay_overrides or {}))
    return counselor, student, essay


def setup_essay_in_review(word_count=500, body="v1",
                          student_overrides=None, counselor_overrides=None, essay_overrides=None):
    """DRAFTING essay with one submitted version -> IN_REVIEW (revision_round still 0).
    Returns (counselor, student, essay)."""
    counselor, student, essay = setup_essay_drafting(
        student_overrides, counselor_overrides, essay_overrides
    )
    resp = api_client.submit_essay_version(
        essay["id"], f.submit_essay_version_payload(word_count, body),
        make_student_headers(student["id"]),
    )
    essay = get_success_data(resp)
    return counselor, student, essay


def setup_essay_after_one_revision_cycle(word_count=500, body="v1",
                                         student_overrides=None, counselor_overrides=None,
                                         essay_overrides=None):
    """Essay that has completed one full review cycle and is back in DRAFTING
    with revision_round == 1: submit-version -> request-revision -> resume-drafting.
    Returns (counselor, student, essay)."""
    counselor, student, essay = setup_essay_in_review(
        word_count, body, student_overrides, counselor_overrides, essay_overrides
    )
    ch = make_counselor_headers(counselor["id"])
    sh = make_student_headers(student["id"])
    get_success_data(api_client.request_revision_essay(essay["id"], ch))
    essay = get_success_data(api_client.resume_drafting_essay(essay["id"], sh))
    return counselor, student, essay
