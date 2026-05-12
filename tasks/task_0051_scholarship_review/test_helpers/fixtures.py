"""Composite setup helpers for the Scholarship Review test suite.

Most interesting test claims require the system to be in a specific
state reached through 5-15 API calls. These helpers encapsulate those
preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):

- SchoolAdmin / DeptOfficer / FinanceOfficer / Student carry OPAQUE
  X-User-IDs. The server records them in audit and approval-tracking
  fields ('the plan's dept_approver_id is set to the requesting
  DeptOfficer's X-User-ID') but does NOT match them against any entity's
  id. SOD / executor-mismatch checks compare X-User-IDs across requests,
  so tests must use distinct X-User-IDs for distinct principals.

- Reviewer is ENTITY-BACKED ('For Reviewer, X-User-ID is the id of the
  acting Reviewer entity in the reviewer pool'). Score-submit ownership
  uses Reviewer.id directly, so every Reviewer-role call MUST use
  make_reviewer_headers(reviewer['id']).

- Student ownership: PRD §2.1 'A Student principal's X-User-ID is, by
  convention, stamped onto every Application they create as the
  student_id'. Distinct students need distinct X-User-IDs so the literal
  comparison can distinguish them.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    DEFAULT_GPA_X100,
    DEFAULT_GRADE,
    DEFAULT_MAJOR,
    DEFAULT_REVIEWER_DEPT,
    DEFAULT_STUDENT_DEPT,
)
from .factories import (
    approve_disbursement_plan_payload,
    assign_reviewers_payload,
    clock_payload,
    correct_application_payload,
    create_application_payload,
    create_disbursement_plan_payload,
    create_objection_payload,
    create_quota_allocation_payload,
    create_reviewer_payload,
    create_scholarship_payload,
    dept_review_payload,
    rule_objection_payload,
    scholarship_state_payload,
    submit_score_payload,
    unique_code,
    unique_suffix,
)
from .test_users import (
    TEST_USERS,
    make_dept_officer_headers,
    make_finance_officer_headers,
    make_reviewer_headers,
    make_student_headers,
)


ADMIN = TEST_USERS["school_admin_headers"]


# ===========================================================================
# Clock helpers
# ===========================================================================
def advance_clock(iso: str,
                  headers: Optional[Dict[str, str]] = None) -> None:
    """PRD §2.10: 'an admin-only test-driving capability allows a
    SchoolAdmin to set the system's logical "now" to a supplied ISO 8601
    datetime via the to field of the clock-advance endpoint.'"""
    get_success_data(
        api_client.advance_clock(clock_payload(iso), headers or ADMIN)
    )


def run_sweep(headers: Optional[Dict[str, str]] = None) -> None:
    """PRD §2.10: sweep runs all pending auto-transitions."""
    get_success_data(api_client.run_sweep(headers or ADMIN))


# ===========================================================================
# Scholarship and quota slice creation
# ===========================================================================
def create_scholarship(**overrides: Any) -> Dict[str, Any]:
    """Create a Scholarship in DRAFT state."""
    payload = create_scholarship_payload(**overrides)
    return get_success_data(api_client.create_scholarship(payload, ADMIN))


def create_quota_allocation(scholarship_id: str,
                            **overrides: Any) -> Dict[str, Any]:
    payload = create_quota_allocation_payload(**overrides)
    return get_success_data(
        api_client.create_quota_allocation(scholarship_id, payload, ADMIN)
    )


def transition_scholarship(scholarship_id: str,
                           to_status: str,
                           headers: Optional[Dict[str, str]] = None,
                           ) -> Dict[str, Any]:
    """Force scholarship state transition (lenient — get_success_data)."""
    return get_success_data(
        api_client.transition_scholarship(
            scholarship_id,
            scholarship_state_payload(to_status),
            headers or ADMIN,
        )
    )


def create_scholarship_with_quota(
    *,
    total_quota: int = 1,
    department_code: str = DEFAULT_STUDENT_DEPT,
    grade: int = DEFAULT_GRADE,
    special_group: Optional[str] = None,
    initial_slots: Optional[int] = None,
    **scholarship_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a DRAFT Scholarship + one matching QuotaAllocation whose
    initial_slots equals total_quota. PRD §3.2: 'the sum of initial_slots
    across all QuotaAllocation rows for this scholarship must equal
    exactly the scholarship's total_quota'."""
    scholarship = create_scholarship(
        total_quota=total_quota, **scholarship_overrides
    )
    slots = initial_slots if initial_slots is not None else total_quota
    slice_payload_kwargs = {
        "department_code": department_code,
        "grade": grade,
        "initial_slots": slots,
    }
    if special_group is not None:
        slice_payload_kwargs["special_group"] = special_group
    quota = create_quota_allocation(
        scholarship["id"], **slice_payload_kwargs
    )
    return scholarship, quota


# ===========================================================================
# Reviewer pool helpers
# ===========================================================================
def create_reviewer(*, department_code: str = DEFAULT_REVIEWER_DEPT,
                    family_relation_student_ids: Optional[List[str]] = None,
                    **overrides: Any) -> Dict[str, Any]:
    payload = create_reviewer_payload(
        department_code=department_code,
        family_relation_student_ids=family_relation_student_ids,
        **overrides,
    )
    return get_success_data(api_client.create_reviewer(payload, ADMIN))


def create_reviewer_set(n: int = 3, *,
                        department_code: str = DEFAULT_REVIEWER_DEPT,
                        ) -> List[Dict[str, Any]]:
    return [create_reviewer(department_code=department_code)
            for _ in range(n)]


# ===========================================================================
# Application creation + state walks
# ===========================================================================
def new_student_id(prefix: str = "student") -> str:
    """Stable opaque Student X-User-ID. Each call returns a unique id."""
    return f"{prefix}-{unique_suffix()}"


def create_application(scholarship_id: str,
                       *,
                       student_id: Optional[str] = None,
                       student_headers: Optional[Dict[str, str]] = None,
                       **overrides: Any,
                       ) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Create an Application via Student headers. PRD §3.3: 'the server
    records the requester's X-User-ID as the application's student_id.'
    Returns (application_dict, headers_used).
    """
    if student_headers is None:
        sid = student_id or new_student_id()
        student_headers = make_student_headers(sid)
    payload = create_application_payload(**overrides)
    app = get_success_data(
        api_client.create_application(
            scholarship_id, payload, student_headers
        )
    )
    return app, student_headers


def submit_application(scholarship_id: str,
                       application_id: str,
                       headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_application(
            scholarship_id, application_id, headers,
        )
    )


# ===========================================================================
# Open the application window (advances clock to start of window)
# ===========================================================================
def open_scholarship(scholarship: Dict[str, Any]) -> Dict[str, Any]:
    """Advance clock to application_window_start, then transition the
    scholarship DRAFT->OPEN. PRD §3.2 preconditions: rubric sums to 100,
    sum(initial_slots) == total_quota, now() >= application_window_start.
    """
    advance_clock(scholarship["application_window_start"])
    return transition_scholarship(scholarship["id"], "OPEN")


def close_and_review(scholarship: Dict[str, Any]) -> Dict[str, Any]:
    """Advance clock to application_window_end and move OPEN->REVIEWING.
    PRD §3.3: 'a transition from OPEN to REVIEWING triggered by an admin
    call also requires that the logical "now" be at least
    application_window_end.'"""
    advance_clock(scholarship["application_window_end"])
    return transition_scholarship(scholarship["id"], "REVIEWING")


def announce_scholarship(scholarship_id: str) -> Dict[str, Any]:
    return transition_scholarship(scholarship_id, "ANNOUNCED")


def finalize_scholarship(scholarship: Dict[str, Any]) -> Dict[str, Any]:
    """Advance clock to announcement_window_end, then ANNOUNCED->FINALIZED.
    PRD §3.9: 'the logical "now" must be at least announcement_window_end'.
    """
    advance_clock(scholarship["announcement_window_end"])
    return transition_scholarship(scholarship["id"], "FINALIZED")


# ===========================================================================
# Dept review helpers
# ===========================================================================
def dept_review_pass(scholarship_id: str,
                     application_id: str,
                     *,
                     dept_code: str = DEFAULT_STUDENT_DEPT,
                     uploaded_materials: Optional[List[str]] = None,
                     officer_id: Optional[str] = None,
                     ) -> Dict[str, Any]:
    """PRD §3.4 PASS path: each uploaded_materials entry authenticated."""
    officer = make_dept_officer_headers(
        officer_id or f"dept-officer-{dept_code}-{unique_suffix()}"
    )
    flags = {m: True for m in (uploaded_materials or ["TRANSCRIPT"])}
    payload = dept_review_payload(
        decision="PASS", comment="ok", is_authentic_flags=flags,
    )
    return get_success_data(
        api_client.dept_review_application(
            scholarship_id, application_id, payload, officer,
        )
    )


def dept_review_reject(scholarship_id: str,
                       application_id: str,
                       *,
                       dept_code: str = DEFAULT_STUDENT_DEPT,
                       comment: str = "Materials look suspicious",
                       officer_id: Optional[str] = None,
                       ) -> Dict[str, Any]:
    officer = make_dept_officer_headers(
        officer_id or f"dept-officer-{dept_code}-{unique_suffix()}"
    )
    payload = dept_review_payload(decision="REJECT", comment=comment)
    return get_success_data(
        api_client.dept_review_application(
            scholarship_id, application_id, payload, officer,
        )
    )


# ===========================================================================
# Reviewer assignment + scoring
# ===========================================================================
def assign_three_reviewers(scholarship_id: str,
                           application_id: str,
                           reviewers: List[Dict[str, Any]],
                           ) -> Dict[str, Any]:
    assert len(reviewers) == 3, "PRD §3.5 requires exactly 3 reviewer_ids"
    payload = assign_reviewers_payload(
        reviewer_ids=[r["id"] for r in reviewers]
    )
    return get_success_data(
        api_client.assign_reviewers(
            scholarship_id, application_id, payload, ADMIN,
        )
    )


def submit_score(scholarship_id: str,
                 application_id: str,
                 reviewer: Dict[str, Any],
                 criterion_scores: Dict[str, int],
                 *,
                 comment: Optional[str] = None,
                 ) -> Dict[str, Any]:
    """Submit a score using the reviewer's entity-backed X-User-ID."""
    payload = submit_score_payload(
        criterion_scores=criterion_scores, comment=comment,
    )
    headers = make_reviewer_headers(reviewer["id"])
    return get_success_data(
        api_client.submit_score(
            scholarship_id, application_id, payload, headers,
        )
    )


def submit_three_scores(scholarship_id: str,
                        application_id: str,
                        reviewers: List[Dict[str, Any]],
                        criterion_scores_list: List[Dict[str, int]],
                        ) -> List[Dict[str, Any]]:
    """Submit one score per reviewer. PRD §3.6: 'the instant the third
    Score row is recorded for an application, the system automatically
    advances the application from UNDER_REVIEW to REVIEW_COMPLETE'."""
    assert len(reviewers) == 3 and len(criterion_scores_list) == 3
    out: List[Dict[str, Any]] = []
    for r, cs in zip(reviewers, criterion_scores_list):
        out.append(submit_score(scholarship_id, application_id, r, cs))
    return out


# ===========================================================================
# Full application lifecycle shortcuts
# ===========================================================================
def create_open_scholarship(
    *,
    category: str = "MERIT",
    rubric_weights: Optional[Dict[str, int]] = None,
    required_materials: Optional[List[str]] = None,
    department_code: str = DEFAULT_STUDENT_DEPT,
    grade: int = DEFAULT_GRADE,
    total_quota: int = 1,
    application_window_start: str = "2026-06-01T00:00:00Z",
    application_window_end: str = "2026-06-30T00:00:00Z",
    announcement_window_end: str = "2026-07-15T00:00:00Z",
    gpa_threshold_x100: int = 300,
    outlier_z_threshold_x100: Optional[int] = None,
    eligible_majors: Optional[List[str]] = None,
    eligible_grades: Optional[List[int]] = None,
    family_income_ceiling_cents: Optional[int] = None,
    per_award_amount_cents: int = 1_000_000,
    **extra_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create Scholarship + matching QuotaAllocation + open it.
    Returns (scholarship, quota)."""
    scholarship, quota = create_scholarship_with_quota(
        category=category,
        rubric_weights=rubric_weights or {"core": 100},
        required_materials=(
            required_materials if required_materials is not None
            else ["TRANSCRIPT"]
        ),
        department_code=department_code,
        grade=grade,
        total_quota=total_quota,
        application_window_start=application_window_start,
        application_window_end=application_window_end,
        announcement_window_end=announcement_window_end,
        gpa_threshold_x100=gpa_threshold_x100,
        outlier_z_threshold_x100=outlier_z_threshold_x100,
        eligible_majors=eligible_majors,
        eligible_grades=eligible_grades,
        family_income_ceiling_cents=family_income_ceiling_cents,
        per_award_amount_cents=per_award_amount_cents,
        **extra_overrides,
    )
    open_scholarship(scholarship)
    # Refresh.
    scholarship = get_success_data(
        api_client.get_scholarship(scholarship["id"], ADMIN)
    )
    return scholarship, quota


def create_submitted_application(
    scholarship: Dict[str, Any],
    *,
    student_id: Optional[str] = None,
    student_department_code: str = DEFAULT_STUDENT_DEPT,
    student_grade: int = DEFAULT_GRADE,
    student_major: str = DEFAULT_MAJOR,
    student_gpa_x100: int = DEFAULT_GPA_X100,
    student_family_income_cents: Optional[int] = None,
    student_special_group: Optional[str] = None,
    uploaded_materials: Optional[List[str]] = None,
    advisor_recommendation_id: Optional[str] = None,
    student_advisor_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Create + submit an application. Returns (application, student_headers).
    Scholarship must be OPEN and 'now' inside its window.
    """
    sid = student_id or new_student_id()
    headers = make_student_headers(sid)

    overrides: Dict[str, Any] = dict(
        student_department_code=student_department_code,
        student_grade=student_grade,
        student_major=student_major,
        student_gpa_x100=student_gpa_x100,
        uploaded_materials=(
            uploaded_materials
            if uploaded_materials is not None
            else list(scholarship["required_materials"]) or ["TRANSCRIPT"]
        ),
    )
    if student_family_income_cents is not None:
        overrides["student_family_income_cents"] = (
            student_family_income_cents
        )
    if student_special_group is not None:
        overrides["student_special_group"] = student_special_group
    if advisor_recommendation_id is not None:
        overrides["advisor_recommendation_id"] = advisor_recommendation_id
    if student_advisor_id is not None:
        overrides["student_advisor_id"] = student_advisor_id

    app, _ = create_application(
        scholarship["id"],
        student_headers=headers,
        **overrides,
    )
    app = submit_application(scholarship["id"], app["id"], headers)
    return app, headers


def setup_application_under_review(
    *,
    rubric_weights: Optional[Dict[str, int]] = None,
    required_materials: Optional[List[str]] = None,
    outlier_z_threshold_x100: Optional[int] = None,
    student_department_code: str = "STU-DEPT",
    reviewer_department_code: str = "REV-DEPT",
    **scholarship_overrides: Any,
) -> Dict[str, Any]:
    """Full preamble: open scholarship + create submitted application +
    REVIEWING + dept-review PASS + assign 3 reviewers -> UNDER_REVIEW.
    Returns dict with:
       scholarship, quota, application, student_headers, reviewers,
       admin_headers.
    """
    materials = required_materials or ["TRANSCRIPT"]
    scholarship, quota = create_open_scholarship(
        rubric_weights=rubric_weights or {"core": 100},
        required_materials=materials,
        department_code=student_department_code,
        outlier_z_threshold_x100=outlier_z_threshold_x100,
        **scholarship_overrides,
    )
    app, student_headers = create_submitted_application(
        scholarship,
        student_department_code=student_department_code,
        uploaded_materials=list(materials),
    )
    close_and_review(scholarship)
    dept_review_pass(
        scholarship["id"], app["id"],
        dept_code=student_department_code,
        uploaded_materials=list(materials),
    )
    reviewers = create_reviewer_set(
        3, department_code=reviewer_department_code,
    )
    assign_three_reviewers(scholarship["id"], app["id"], reviewers)
    # Refresh application
    app = get_success_data(
        api_client.get_application(
            scholarship["id"], app["id"], ADMIN,
        )
    )
    return {
        "scholarship": scholarship,
        "quota": quota,
        "application": app,
        "student_headers": student_headers,
        "reviewers": reviewers,
    }


def setup_review_complete(
    criterion_scores_list: Optional[List[Dict[str, int]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build an application all the way to REVIEW_COMPLETE with the given
    three scores. Returns the dict from setup_application_under_review
    augmented with `scores` (list of 3 dicts)."""
    state = setup_application_under_review(**kwargs)
    if criterion_scores_list is None:
        # Default uniform scores (no outliers).
        rubric = state["scholarship"]["rubric_weights"]
        # If 'core' weight is 100, each criterion_scores={core: 50}
        # gives raw_total_x100 = 50*100 = 5000.
        criterion_scores_list = [
            {k: 50 for k in rubric.keys()}
            for _ in range(3)
        ]
    scores = submit_three_scores(
        state["scholarship"]["id"], state["application"]["id"],
        state["reviewers"], criterion_scores_list,
    )
    state["scores"] = scores
    # Refresh application — should now be REVIEW_COMPLETE.
    state["application"] = get_success_data(
        api_client.get_application(
            state["scholarship"]["id"],
            state["application"]["id"],
            ADMIN,
        )
    )
    return state


def setup_announced_with_one_awarded(
    *,
    score_per_criterion: int = 80,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Reach ANNOUNCED with one AWARDED application (the only candidate).
    Returns state dict with announced flag and refreshed application/quota.
    """
    rubric = kwargs.get("rubric_weights") or {"core": 100}
    state = setup_review_complete(
        criterion_scores_list=[
            {k: score_per_criterion for k in rubric.keys()}
            for _ in range(3)
        ],
        rubric_weights=rubric,
        **kwargs,
    )
    announce_scholarship(state["scholarship"]["id"])
    state["application"] = get_success_data(
        api_client.get_application(
            state["scholarship"]["id"],
            state["application"]["id"],
            ADMIN,
        )
    )
    return state


def setup_finalized_with_one_awarded(**kwargs: Any) -> Dict[str, Any]:
    state = setup_announced_with_one_awarded(**kwargs)
    finalize_scholarship(state["scholarship"])
    state["application"] = get_success_data(
        api_client.get_application(
            state["scholarship"]["id"],
            state["application"]["id"],
            ADMIN,
        )
    )
    state["scholarship"] = get_success_data(
        api_client.get_scholarship(
            state["scholarship"]["id"], ADMIN,
        )
    )
    return state


# ===========================================================================
# DisbursementPlan helpers
# ===========================================================================
DEPT_OFFICER_ID_1 = "dept-officer-001"
DEPT_OFFICER_ID_2 = "dept-officer-002"
FINANCE_OFFICER_ID_1 = "finance-officer-001"
FINANCE_OFFICER_ID_2 = "finance-officer-002"


def dept_officer_headers(officer_id: str = DEPT_OFFICER_ID_1):
    return make_dept_officer_headers(officer_id)


def finance_officer_headers(officer_id: str = FINANCE_OFFICER_ID_1):
    return make_finance_officer_headers(officer_id)


def create_disbursement_plan(scholarship_id: str,
                             *,
                             payment_channel: str = "BANK",
                             officer_id: str = FINANCE_OFFICER_ID_1,
                             ) -> Dict[str, Any]:
    payload = create_disbursement_plan_payload(
        payment_channel=payment_channel
    )
    return get_success_data(
        api_client.create_disbursement_plan(
            scholarship_id, payload, finance_officer_headers(officer_id),
        )
    )


def approve_plan_dept(scholarship_id: str,
                      plan_id: str,
                      *,
                      officer_id: str = DEPT_OFFICER_ID_1,
                      ) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_disbursement_plan(
            scholarship_id, plan_id,
            approve_disbursement_plan_payload(level="DEPT"),
            dept_officer_headers(officer_id),
        )
    )


def approve_plan_finance(scholarship_id: str,
                         plan_id: str,
                         *,
                         officer_id: str = FINANCE_OFFICER_ID_1,
                         ) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_disbursement_plan(
            scholarship_id, plan_id,
            approve_disbursement_plan_payload(level="FINANCE"),
            finance_officer_headers(officer_id),
        )
    )


def revert_plan_dept(scholarship_id: str,
                     plan_id: str,
                     *,
                     officer_id: str = DEPT_OFFICER_ID_1,
                     ) -> Dict[str, Any]:
    return get_success_data(
        api_client.revert_disbursement_plan(
            scholarship_id, plan_id,
            dept_officer_headers(officer_id),
        )
    )


def execute_plan(scholarship_id: str,
                 plan_id: str,
                 *,
                 officer_id: str = FINANCE_OFFICER_ID_1,
                 ) -> Dict[str, Any]:
    return get_success_data(
        api_client.execute_disbursement_plan(
            scholarship_id, plan_id,
            finance_officer_headers(officer_id),
        )
    )


def setup_executed_plan(
    *,
    per_award_amount_cents: int = 1_000_000,
    payment_channel: str = "BANK",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Reach a DisbursementPlan in EXECUTED state for one AWARDED
    application. Returns state dict with `plan` added.
    """
    state = setup_finalized_with_one_awarded(
        per_award_amount_cents=per_award_amount_cents,
        **kwargs,
    )
    plan = create_disbursement_plan(
        state["scholarship"]["id"],
        payment_channel=payment_channel,
    )
    plan = approve_plan_dept(state["scholarship"]["id"], plan["id"])
    plan = approve_plan_finance(state["scholarship"]["id"], plan["id"])
    plan = execute_plan(state["scholarship"]["id"], plan["id"])
    state["plan"] = plan
    state["scholarship"] = get_success_data(
        api_client.get_scholarship(state["scholarship"]["id"], ADMIN)
    )
    return state


def setup_dept_approved_plan(
    *,
    per_award_amount_cents: int = 1_000_000,
    payment_channel: str = "BANK",
    dept_officer_id: str = DEPT_OFFICER_ID_1,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Reach a DisbursementPlan in DEPT_APPROVED state."""
    state = setup_finalized_with_one_awarded(
        per_award_amount_cents=per_award_amount_cents,
        **kwargs,
    )
    plan = create_disbursement_plan(
        state["scholarship"]["id"],
        payment_channel=payment_channel,
    )
    plan = approve_plan_dept(
        state["scholarship"]["id"], plan["id"],
        officer_id=dept_officer_id,
    )
    state["plan"] = plan
    state["dept_officer_id"] = dept_officer_id
    return state


# ===========================================================================
# Objection helpers
# ===========================================================================
def create_objection(scholarship_id: str,
                     application_id: str,
                     *,
                     objector_student_id: Optional[str] = None,
                     reason_code: str = "MATERIAL_FALSE",
                     description: str = "Issue raised",
                     ) -> Dict[str, Any]:
    """Submit an objection. PRD §3.9 requires the scholarship to be
    ANNOUNCED and now < announcement_window_end."""
    sid = objector_student_id or new_student_id("objector")
    headers = make_student_headers(sid)
    payload = create_objection_payload(
        application_id=application_id,
        objector_student_id=sid,
        reason_code=reason_code,
        description=description,
    )
    return get_success_data(
        api_client.create_objection(scholarship_id, payload, headers)
    )


def rule_objection(scholarship_id: str,
                   objection_id: str,
                   *,
                   decision: str,
                   ruling_comment: str = "Ruling",
                   ) -> Dict[str, Any]:
    payload = rule_objection_payload(
        decision=decision, ruling_comment=ruling_comment,
    )
    return get_success_data(
        api_client.rule_objection(
            scholarship_id, objection_id, payload, ADMIN,
        )
    )


# ===========================================================================
# Difficulty-design composite fixtures
# ===========================================================================
def setup_announced_with_winner_and_runnerup(
    *,
    rubric_weights: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Reach ANNOUNCED with quota slice current_slots=1, two
    REVIEW_COMPLETE applications: A (winner, score 9000) and B
    (runner-up, score 7000). A is AWARDED, B is NOT_AWARDED.

    Used for objection-uphold cascade and quota-conservation invariant
    tests.
    """
    rubric = rubric_weights or {"core": 100}
    student_dept = "DEPT-CASCADE"
    reviewer_dept = "REV-CASCADE"
    # Scholarship has total_quota=1, one slice with initial_slots=1.
    scholarship, quota = create_open_scholarship(
        rubric_weights=rubric,
        required_materials=["TRANSCRIPT"],
        department_code=student_dept,
        total_quota=1,
        per_award_amount_cents=1_000_000,
    )
    # Two applications in same slice (same dept/grade/special_group).
    app_a, headers_a = create_submitted_application(
        scholarship,
        student_department_code=student_dept,
        student_grade=DEFAULT_GRADE,
        uploaded_materials=["TRANSCRIPT"],
    )
    app_b, headers_b = create_submitted_application(
        scholarship,
        student_department_code=student_dept,
        student_grade=DEFAULT_GRADE,
        uploaded_materials=["TRANSCRIPT"],
    )
    close_and_review(scholarship)
    # Pass both at dept-review.
    dept_review_pass(
        scholarship["id"], app_a["id"],
        dept_code=student_dept, uploaded_materials=["TRANSCRIPT"],
    )
    dept_review_pass(
        scholarship["id"], app_b["id"],
        dept_code=student_dept, uploaded_materials=["TRANSCRIPT"],
    )
    reviewers = create_reviewer_set(3, department_code=reviewer_dept)
    assign_three_reviewers(scholarship["id"], app_a["id"], reviewers)
    assign_three_reviewers(scholarship["id"], app_b["id"], reviewers)
    # A: raw_total_x100 == 90*100 == 9000 per score (with rubric=core:100)
    # B: raw_total_x100 == 70*100 == 7000
    a_scores = [{k: 90 for k in rubric.keys()} for _ in range(3)]
    b_scores = [{k: 70 for k in rubric.keys()} for _ in range(3)]
    submit_three_scores(
        scholarship["id"], app_a["id"], reviewers, a_scores,
    )
    submit_three_scores(
        scholarship["id"], app_b["id"], reviewers, b_scores,
    )
    announce_scholarship(scholarship["id"])
    # Refresh.
    app_a = get_success_data(
        api_client.get_application(scholarship["id"], app_a["id"], ADMIN)
    )
    app_b = get_success_data(
        api_client.get_application(scholarship["id"], app_b["id"], ADMIN)
    )
    quota = list_quota_slices(scholarship["id"])[0]
    return {
        "scholarship": scholarship,
        "quota": quota,
        "winner": app_a,
        "runner_up": app_b,
        "winner_headers": headers_a,
        "runner_up_headers": headers_b,
        "reviewers": reviewers,
    }


def list_quota_slices(scholarship_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api_client.list_quota_allocations(scholarship_id, ADMIN)
    )
    return data


def list_audit(headers: Optional[Dict[str, str]] = None,
               **params: Any) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api_client.list_audit_events(headers or ADMIN, params=params)
    )
    return data


def list_external_sync(headers: Optional[Dict[str, str]] = None,
                       **params: Any) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api_client.list_external_sync_events(
            headers or ADMIN, params=params,
        )
    )
    return data


# ===========================================================================
# Time helper
# ===========================================================================
def iso_at(year: int, month: int, day: int, hour: int = 0,
           minute: int = 0, second: int = 0) -> str:
    """Build an ISO 8601 UTC timestamp with millisecond precision."""
    return (datetime(year, month, day, hour, minute, second,
                     tzinfo=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.000Z"))


__all__ = [
    "ADMIN",
    "DEPT_OFFICER_ID_1",
    "DEPT_OFFICER_ID_2",
    "FINANCE_OFFICER_ID_1",
    "FINANCE_OFFICER_ID_2",
    "advance_clock",
    "run_sweep",
    "create_scholarship",
    "create_quota_allocation",
    "transition_scholarship",
    "create_scholarship_with_quota",
    "create_reviewer",
    "create_reviewer_set",
    "new_student_id",
    "create_application",
    "submit_application",
    "open_scholarship",
    "close_and_review",
    "announce_scholarship",
    "finalize_scholarship",
    "dept_review_pass",
    "dept_review_reject",
    "assign_three_reviewers",
    "submit_score",
    "submit_three_scores",
    "create_open_scholarship",
    "create_submitted_application",
    "setup_application_under_review",
    "setup_review_complete",
    "setup_announced_with_one_awarded",
    "setup_finalized_with_one_awarded",
    "dept_officer_headers",
    "finance_officer_headers",
    "create_disbursement_plan",
    "approve_plan_dept",
    "approve_plan_finance",
    "revert_plan_dept",
    "execute_plan",
    "setup_executed_plan",
    "setup_dept_approved_plan",
    "create_objection",
    "rule_objection",
    "setup_announced_with_winner_and_runnerup",
    "list_quota_slices",
    "list_audit",
    "list_external_sync",
    "iso_at",
]
