"""Composite setup helpers.

Each helper builds a precondition chain through PRD-declared endpoints only,
using get_success_data so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion deep inside a test.

Role headers come from TEST_USERS (all roles are opaque-identity per PRD §2.1);
the SoD-sensitive helpers take explicit user ids.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    assign_rating_payload,
    create_assessment_area_payload,
    create_branch_payload,
    create_cd_activity_payload,
    create_demographic_profile_payload,
    create_exam_cycle_payload,
    create_expansion_application_payload,
    create_loan_record_payload,
    create_public_file_payload,
    review_decision_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_analyst_headers,
    make_qualification_reviewer_headers,
)

_OFFICER = TEST_USERS["cra_officer_headers"]
_ANALYST = TEST_USERS["compliance_analyst_headers"]
_REVIEWER = TEST_USERS["qualification_reviewer_headers"]
_EXAMINER = TEST_USERS["bank_examiner_headers"]
_EXECUTIVE = TEST_USERS["bank_executive_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: assessment areas and demographic profiles
# ---------------------------------------------------------------------------

def create_area(**overrides) -> dict:
    """Create an assessment area in DRAFT. Returns the created area."""
    resp = api_client.create_assessment_area(
        create_assessment_area_payload(**overrides), _OFFICER
    )
    return get_success_data(resp)


def create_active_area(**overrides) -> dict:
    """Create an area and move it DRAFT -> ACTIVE. Returns the ACTIVE area."""
    area = create_area(**overrides)
    resp = api_client.activate_assessment_area(area["id"], _OFFICER)
    return get_success_data(resp)


def get_area(area_id: str) -> dict:
    return get_success_data(api_client.get_assessment_area(area_id, _OFFICER))


def add_demographic_profile(area: dict, **overrides) -> Tuple[dict, dict]:
    """Post a demographic profile OCC-guarded on the area's current version.

    Returns (profile, area) with the area re-read after creation (profile
    creation increments the area's version per PRD §3.2).
    """
    payload = create_demographic_profile_payload(
        expected_assessment_area_version=area["version"], **overrides
    )
    profile = get_success_data(
        api_client.create_demographic_profile(area["id"], payload, _OFFICER)
    )
    return profile, get_area(area["id"])


# ---------------------------------------------------------------------------
# Tier 2/3: loan records
# ---------------------------------------------------------------------------

def create_loan(area_id: str, **overrides) -> dict:
    """Record a loan in DRAFT against the given area."""
    resp = api_client.create_loan_record(
        create_loan_record_payload(area_id, **overrides), _ANALYST
    )
    return get_success_data(resp)


def create_confirmed_loan(area_id: str, **overrides) -> dict:
    """Record a loan and move it DRAFT -> CONFIRMED (area must be ACTIVE and
    the loan's tract must belong to the area, per PRD §3.3)."""
    loan = create_loan(area_id, **overrides)
    return get_success_data(api_client.confirm_loan_record(loan["id"], _ANALYST))


def create_reported_loan(area_id: str, **overrides) -> dict:
    """Record a loan and walk it DRAFT -> CONFIRMED -> REPORTED."""
    loan = create_confirmed_loan(area_id, **overrides)
    return get_success_data(api_client.mark_loan_reported(loan["id"], _ANALYST))


# ---------------------------------------------------------------------------
# Tier 2/3: community development activities (SoD-sensitive user ids)
# ---------------------------------------------------------------------------

def create_submitted_activity(area_id: str, submitter_user_id: str = "analyst-1",
                              **overrides) -> dict:
    """Submit a CD activity as the given analyst; status SUBMITTED."""
    resp = api_client.create_cd_activity(
        create_cd_activity_payload(area_id, **overrides),
        make_compliance_analyst_headers(submitter_user_id),
    )
    return get_success_data(resp)


def qualify_activity(activity_id: str, allocation_method: str = "PRO_RATA",
                     reviewer_user_id: str = "reviewer-1") -> dict:
    """Render a QUALIFY decision as a reviewer distinct from the submitter."""
    resp = api_client.review_cd_activity(
        activity_id,
        review_decision_payload("QUALIFY", allocation_method=allocation_method),
        make_qualification_reviewer_headers(reviewer_user_id),
    )
    return get_success_data(resp)


def disqualify_activity(activity_id: str, reason: str = "insufficient documentation",
                        reviewer_user_id: str = "reviewer-1") -> dict:
    """Render a DISQUALIFY decision as a reviewer distinct from the submitter."""
    resp = api_client.review_cd_activity(
        activity_id,
        review_decision_payload("DISQUALIFY", disqualify_reason=reason),
        make_qualification_reviewer_headers(reviewer_user_id),
    )
    return get_success_data(resp)


def get_cd_activity(area_id: str, activity_id: str) -> dict:
    """Re-read a CD activity via the area's activity list (PRD §4 defines no
    single-activity GET, so state checks after a rejected call go through the
    list endpoint)."""
    resp = api_client.list_area_cd_activities(
        area_id, _OFFICER, params={"limit": 100}
    )
    data = get_success_data(resp)
    for item in data:
        if item.get("id") == activity_id:
            return item
    raise AssertionError(f"Setup failed: activity {activity_id} not found in area list")


# ---------------------------------------------------------------------------
# Tier 2/3: branches
# ---------------------------------------------------------------------------

def create_proposed_branch(area_id: str, **overrides) -> dict:
    """Directly create a branch in PROPOSED, untied to any application."""
    resp = api_client.create_branch(create_branch_payload(area_id, **overrides), _EXECUTIVE)
    return get_success_data(resp)


def create_open_branch(area_id: str, **overrides) -> dict:
    """Create a branch and move it PROPOSED -> OPEN."""
    branch = create_proposed_branch(area_id, **overrides)
    return get_success_data(api_client.open_branch(branch["id"], _EXECUTIVE))


def get_branch(branch_id: str) -> dict:
    return get_success_data(api_client.get_branch(branch_id, _OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: the singleton public file
# ---------------------------------------------------------------------------

def create_public_file(bank_name: str = "First Test Bank") -> dict:
    """Create the singleton public file (born INCOMPLETE per PRD §3.6)."""
    resp = api_client.create_public_file(
        create_public_file_payload(bank_name=bank_name), _OFFICER
    )
    return get_success_data(resp)


def create_complete_public_file(bank_name: str = "First Test Bank") -> dict:
    """Create the public file and place the disclosure statement, yielding
    posture COMPLETE (all list flags true, no pending comments)."""
    public_file = create_public_file(bank_name)
    resp = api_client.refresh_public_file_items(
        public_file["id"], {"disclosure_statement": True}, _OFFICER
    )
    return get_success_data(resp)


def get_public_file(file_id: str) -> dict:
    return get_success_data(api_client.get_public_file(file_id, _OFFICER))


# ---------------------------------------------------------------------------
# Tier 3/5: exam lifecycle
# ---------------------------------------------------------------------------

def create_scheduled_exam(window_start: str = "2024-01-01",
                          window_end: str = "2024-12-31",
                          **overrides) -> dict:
    """Schedule an exam in SCHEDULED with the given closed window."""
    resp = api_client.create_exam_cycle(
        create_exam_cycle_payload(
            evaluation_window_start=window_start,
            evaluation_window_end=window_end,
            **overrides,
        ),
        _EXAMINER,
    )
    return get_success_data(resp)


def advance_exam_to_data_collection(exam_id: str) -> dict:
    return get_success_data(api_client.begin_data_collection(exam_id, _EXAMINER))


def advance_exam_to_fieldwork(exam_id: str) -> dict:
    """DATA_COLLECTION -> FIELDWORK. Assumes the public file exists and is
    COMPLETE (PRD §3.7 gate)."""
    return get_success_data(api_client.begin_fieldwork(exam_id, _EXAMINER))


def assign_ratings(exam_id: str, lending: str, investment: str, service: str) -> dict:
    """FIELDWORK -> PRELIMINARY_RATING with the three test ratings."""
    resp = api_client.assign_preliminary_rating(
        exam_id, assign_rating_payload(lending, investment, service), _EXAMINER
    )
    return get_success_data(resp)


def create_exam_at_preliminary_rating(lending: str, investment: str, service: str,
                                      window_start: str = "2024-01-01",
                                      window_end: str = "2024-12-31") -> dict:
    """Full chain SCHEDULED -> ... -> PRELIMINARY_RATING. Assumes a COMPLETE
    public file already exists."""
    exam = create_scheduled_exam(window_start, window_end)
    advance_exam_to_data_collection(exam["id"])
    advance_exam_to_fieldwork(exam["id"])
    return assign_ratings(exam["id"], lending, investment, service)


def create_finalized_exam(lending: str, investment: str, service: str,
                          window_start: str = "2024-01-01",
                          window_end: str = "2024-12-31") -> dict:
    """Full chain through FINALIZED. Assumes a COMPLETE public file exists and
    no other exam's window shares a date with the given window."""
    exam = create_exam_at_preliminary_rating(
        lending, investment, service, window_start, window_end
    )
    return get_success_data(api_client.finalize_exam(exam["id"], _EXAMINER))


def get_exam(exam_id: str) -> dict:
    return get_success_data(api_client.get_exam_cycle(exam_id, _OFFICER))


# ---------------------------------------------------------------------------
# Tier 3: expansion applications
# ---------------------------------------------------------------------------

def create_draft_application(area_id: str, application_type: str = "MERGER",
                             **overrides) -> dict:
    """Draft an expansion application (status DRAFT)."""
    resp = api_client.create_expansion_application(
        create_expansion_application_payload(
            area_id, application_type=application_type, **overrides
        ),
        _EXECUTIVE,
    )
    return get_success_data(resp)


def submit_application(app_id: str) -> dict:
    return get_success_data(api_client.submit_expansion_application(app_id, _EXECUTIVE))


def create_submitted_branch_opening(area_id: str, **overrides) -> Tuple[dict, str]:
    """Draft + submit a BRANCH_OPENING application. Returns (application,
    linked_branch_id) with the staged PROPOSED branch id."""
    overrides.setdefault("branch_code", "BR-STAGED")
    overrides.setdefault("branch_census_tract", "T1")
    overrides.setdefault("branch_tract_income_level", "MODERATE")
    app = create_draft_application(area_id, "BRANCH_OPENING", **overrides)
    submitted = submit_application(app["id"])
    return submitted, submitted["linked_branch_id"]


def get_application(app_id: str) -> dict:
    return get_success_data(api_client.get_expansion_application(app_id, _OFFICER))
