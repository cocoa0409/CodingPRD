"""Composite setup helpers for the curriculum approval workflow tests.

The harness restarts the API server before every individual test, so each
test starts against an empty database; these helpers rebuild multi-step
preconditions through the public API. Setup calls use the lenient
get_success_data validator so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.

Identity threading: DepartmentChair is entity-backed by Department, so every
chair call is built with make_chair_headers(<Department.id>). Proposer calls
reuse the creating user id string (proposer_id is compared by raw equality).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_PROPOSER_ID
from .factories import (
    TERM_2026FA,
    TERM_2027FA,
    TERM_2027SP,
    TERM_2027SU,
    create_course_change_proposal_payload,
    create_course_payload,
    create_cross_listing_payload,
    create_deactivation_proposal_payload,
    create_department_payload,
    create_edition_payload,
    create_new_course_proposal_payload,
    create_teach_out_plan_payload,
    create_term_payload,
)
from .test_users import (
    make_chair_headers,
    make_committee_headers,
    make_proposer_headers,
    make_registrar_headers,
    make_senate_headers,
)

# Clock instant just past the canonical fall term's proposal freeze
# (2026-10-01T00:00:00Z), used to lock a term for activation.
CLOCK_AFTER_2026FA_PROPOSAL_FREEZE = "2026-10-02T00:00:00Z"
# Clock instant past every 2026-2027 term freeze (latest catalog freeze in
# that year is 2027-07-01T00:00:00Z), used to freeze a full academic year.
CLOCK_AFTER_AY2026_CATALOG_FREEZES = "2027-07-02T00:00:00Z"


# -------------------------------------------------------------------------
# Tier 1: single-resource creation
# -------------------------------------------------------------------------

def create_department(dept_name="Computer Science", subject_codes=None,
                      college="Engineering") -> dict:
    """Registrar registers a department. Returns the created Department."""
    payload = create_department_payload(
        dept_name=dept_name,
        subject_codes=subject_codes if subject_codes is not None else ["CS"],
        college=college,
    )
    return get_success_data(
        api_client.create_department(payload, make_registrar_headers()), 201)


def create_term(frame=None, **overrides) -> dict:
    """Registrar creates a term. Defaults to the canonical 2026FA frame."""
    base = dict(TERM_2026FA if frame is None else frame)
    base.update(overrides)
    return get_success_data(
        api_client.create_term(create_term_payload(**base),
                               make_registrar_headers()), 201)


def create_term_2027sp(**overrides) -> dict:
    return create_term(TERM_2027SP, **overrides)


def create_term_2027su(**overrides) -> dict:
    return create_term(TERM_2027SU, **overrides)


def create_term_2027fa(**overrides) -> dict:
    return create_term(TERM_2027FA, **overrides)


def import_course(department_id, term_id, subject_code="CS",
                  course_number="301", **overrides) -> dict:
    """Registrar imports a catalog course directly into ACTIVE status."""
    payload = create_course_payload(
        department_id, term_id,
        subject_code=subject_code, course_number=course_number, **overrides)
    return get_success_data(
        api_client.create_course(payload, make_registrar_headers()), 201)


def create_edition(**overrides) -> dict:
    """Registrar creates a DRAFT catalog edition."""
    return get_success_data(
        api_client.create_edition(create_edition_payload(**overrides),
                                  make_registrar_headers()), 201)


# -------------------------------------------------------------------------
# Tier 2: proposal drafting and the committee gauntlet
# -------------------------------------------------------------------------

def create_new_course_proposal(department_id, requested_term_id,
                               course_number, proposer_id=DEFAULT_PROPOSER_ID,
                               **overrides) -> dict:
    """FacultyProposer drafts a NEW_COURSE proposal (status DRAFT)."""
    payload = create_new_course_proposal_payload(
        department_id, requested_term_id, course_number, **overrides)
    return get_success_data(
        api_client.create_proposal(payload, make_proposer_headers(proposer_id)),
        201)


def create_course_change_proposal(department_id, requested_term_id,
                                  target_course_id,
                                  proposer_id=DEFAULT_PROPOSER_ID,
                                  **overrides) -> dict:
    """FacultyProposer drafts a COURSE_CHANGE proposal (status DRAFT)."""
    payload = create_course_change_proposal_payload(
        department_id, requested_term_id, target_course_id, **overrides)
    return get_success_data(
        api_client.create_proposal(payload, make_proposer_headers(proposer_id)),
        201)


def create_deactivation_proposal(department_id, requested_term_id,
                                 target_course_id, declared_remaining_cohorts,
                                 proposer_id=DEFAULT_PROPOSER_ID,
                                 **overrides) -> dict:
    """FacultyProposer drafts a DEACTIVATION proposal (status DRAFT)."""
    payload = create_deactivation_proposal_payload(
        department_id, requested_term_id, target_course_id,
        declared_remaining_cohorts, **overrides)
    return get_success_data(
        api_client.create_proposal(payload, make_proposer_headers(proposer_id)),
        201)


def submit_proposal(proposal_id, proposer_id=DEFAULT_PROPOSER_ID) -> dict:
    """Author submits: DRAFT|RETURNED -> DEPT_REVIEW."""
    return get_success_data(
        api_client.submit_proposal(proposal_id,
                                   make_proposer_headers(proposer_id)))


def create_submitted_new_course_proposal(department_id, requested_term_id,
                                         course_number,
                                         proposer_id=DEFAULT_PROPOSER_ID,
                                         **overrides) -> dict:
    """Draft + submit a NEW_COURSE proposal. Returns it in DEPT_REVIEW."""
    proposal = create_new_course_proposal(
        department_id, requested_term_id, course_number,
        proposer_id=proposer_id, **overrides)
    return submit_proposal(proposal["id"], proposer_id)


def post_decision(proposal_id, action, headers, **extra) -> dict:
    """Record a committee/registrar decision; returns the updated proposal."""
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.post_decision(proposal_id, payload,
                                                     headers))


def advance_through_committee(proposal_id, department_id) -> dict:
    """Walk DEPT_REVIEW -> COMMITTEE_REVIEW -> SENATE_REVIEW ->
    REGISTRAR_REVIEW. Returns the proposal in REGISTRAR_REVIEW (the senate
    approval response, carrying the recomputed final score)."""
    post_decision(proposal_id, "APPROVE", make_chair_headers(department_id))
    post_decision(proposal_id, "APPROVE", make_committee_headers())
    return post_decision(proposal_id, "APPROVE", make_senate_headers())


def registrar_approve(proposal_id, effective_term_id) -> dict:
    """Registrar APPROVE with effective_term_id: REGISTRAR_REVIEW -> APPROVED."""
    return post_decision(proposal_id, "APPROVE", make_registrar_headers(),
                         effective_term_id=effective_term_id)


def notify_accreditor(proposal_id) -> dict:
    """Registrar NOTIFY self-loop on REGISTRAR_REVIEW."""
    return post_decision(proposal_id, "NOTIFY", make_registrar_headers())


def reassign_effective_term(proposal_id, effective_term_id) -> dict:
    """Registrar REASSIGN_TERM self-loop on APPROVED."""
    return post_decision(proposal_id, "REASSIGN_TERM",
                         make_registrar_headers(),
                         effective_term_id=effective_term_id)


def fully_approve_proposal(proposal_id, department_id,
                           effective_term_id) -> dict:
    """Committee gauntlet + registrar approval. Returns the APPROVED proposal."""
    advance_through_committee(proposal_id, department_id)
    return registrar_approve(proposal_id, effective_term_id)


# -------------------------------------------------------------------------
# Tier 3: term freezing and full activation lifecycle
# -------------------------------------------------------------------------

def set_clock(to_iso8601) -> dict:
    return get_success_data(
        api_client.set_clock(to_iso8601, make_registrar_headers()))


def freeze_term_proposals(term_id,
                          clock_at=CLOCK_AFTER_2026FA_PROPOSAL_FREEZE) -> dict:
    """Advance the logical clock past proposal_freeze_at and freeze the
    term's proposal window (OPEN_FOR_PROPOSALS -> PROPOSAL_FROZEN)."""
    set_clock(clock_at)
    return get_success_data(
        api_client.freeze_proposals(term_id, make_registrar_headers()))


def create_and_activate_new_course(department_id, requested_term_id,
                                   course_number, effective_term_id=None,
                                   proposer_id=DEFAULT_PROPOSER_ID,
                                   freeze_clock=CLOCK_AFTER_2026FA_PROPOSAL_FREEZE,
                                   **overrides):
    """Full NEW_COURSE lifecycle: draft -> submit -> committee -> registrar
    approval -> term frozen -> activate. Returns (proposal, course); the
    materialized course is looked up by its subject code and number."""
    proposal = create_submitted_new_course_proposal(
        department_id, requested_term_id, course_number,
        proposer_id=proposer_id, **overrides)
    effective_term_id = effective_term_id or requested_term_id
    fully_approve_proposal(proposal["id"], department_id, effective_term_id)
    freeze_term_proposals(effective_term_id, clock_at=freeze_clock)
    activated = get_success_data(
        api_client.activate_proposal(proposal["id"], make_registrar_headers()))
    courses_resp = api_client.list_courses(
        make_registrar_headers(),
        params={"subject_code": "CS", "course_number": course_number})
    courses = get_success_data(courses_resp)
    course = courses[0]
    return activated, course


# -------------------------------------------------------------------------
# Tier 4: teach-out planning for deactivations
# -------------------------------------------------------------------------

def create_teach_out_plan(proposal_id, enrolled_cohort_count, cohort_sizes,
                          last_enrolled_term_id,
                          proposer_id=DEFAULT_PROPOSER_ID) -> dict:
    """Author creates the DRAFT teach-out plan for a DEACTIVATION proposal."""
    payload = create_teach_out_plan_payload(
        enrolled_cohort_count, cohort_sizes, last_enrolled_term_id)
    return get_success_data(
        api_client.create_teach_out_plan(proposal_id, payload,
                                         make_proposer_headers(proposer_id)),
        201)


def create_and_commit_teach_out_plan(proposal_id, department_id,
                                     enrolled_cohort_count, cohort_sizes,
                                     last_enrolled_term_id,
                                     proposer_id=DEFAULT_PROPOSER_ID) -> dict:
    """Create the plan and have the sponsoring department's chair commit it."""
    plan = create_teach_out_plan(proposal_id, enrolled_cohort_count,
                                 cohort_sizes, last_enrolled_term_id,
                                 proposer_id=proposer_id)
    return get_success_data(
        api_client.commit_teach_out_plan(plan["id"],
                                         make_chair_headers(department_id)))


def setup_approved_deactivation_with_committed_plan(
        declared_remaining_cohorts=1, cohort_sizes=None,
        requested_term_frame=TERM_2027SP):
    """Department + two terms + ACTIVE course + DEACTIVATION proposal with a
    COMMITTED teach-out plan, advanced through the gauntlet, notified, and
    registrar-approved with the (frozen-ready) fall term as effective term.
    The fall term is left OPEN_FOR_PROPOSALS; callers freeze it before
    activation. Returns a dict of every piece."""
    if cohort_sizes is None:
        cohort_sizes = [7]
    dept = create_department()
    t1 = create_term()
    t2 = create_term(requested_term_frame)
    course = import_course(dept["id"], t1["id"])
    proposal = create_deactivation_proposal(
        dept["id"], t2["id"], course["id"], declared_remaining_cohorts)
    plan = create_and_commit_teach_out_plan(
        proposal["id"], dept["id"], declared_remaining_cohorts, cohort_sizes,
        t1["id"])
    submit_proposal(proposal["id"])
    advance_through_committee(proposal["id"], dept["id"])
    if declared_remaining_cohorts > 0:
        # Final score 30 + 20 teach-out factor = 50 crosses the notification
        # threshold, so the registrar must record the notification first.
        notify_accreditor(proposal["id"])
    approved = registrar_approve(proposal["id"], t1["id"])
    return {
        "dept": dept, "t1": t1, "t2": t2, "course": course,
        "proposal": approved, "plan": plan,
    }


# -------------------------------------------------------------------------
# Tier 5: cross-listing setups
# -------------------------------------------------------------------------

def setup_cross_listing_pair():
    """Two departments (CS home, MATH partner), one term, and one ACTIVE
    course per department. Returns a dict with depts, term, and courses."""
    dept_cs = create_department()
    dept_math = create_department(dept_name="Mathematics",
                                  subject_codes=["MATH"], college="Sciences")
    term = create_term()
    home_course = import_course(dept_cs["id"], term["id"], course_number="301",
                                title="Home Course")
    partner_course = import_course(dept_math["id"], term["id"],
                                   subject_code="MATH", course_number="210",
                                   title="Partner Course")
    return {"dept_home": dept_cs, "dept_partner": dept_math, "term": term,
            "home_course": home_course, "partner_course": partner_course}


def create_pending_cross_listing(home_course_id, partner_course_id,
                                 home_department_id) -> dict:
    """Home-department chair requests the cross-listing (status PENDING)."""
    payload = create_cross_listing_payload(home_course_id, partner_course_id)
    return get_success_data(
        api_client.create_cross_listing(payload,
                                        make_chair_headers(home_department_id)),
        201)


# -------------------------------------------------------------------------
# Read-side conveniences
# -------------------------------------------------------------------------

def get_proposal(proposal_id) -> dict:
    return get_success_data(
        api_client.get_proposal(proposal_id, make_registrar_headers()))


def get_term(term_id) -> dict:
    return get_success_data(
        api_client.get_term(term_id, make_registrar_headers()))


def get_course(course_id) -> dict:
    return get_success_data(
        api_client.get_course(course_id, make_registrar_headers()))


def list_decision_records(proposal_id) -> list:
    data = get_success_data(
        api_client.list_decisions(proposal_id, make_registrar_headers()))
    return data
