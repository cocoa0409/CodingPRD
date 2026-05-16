"""Composite setup helpers — multi-step preambles tests can reuse.

The IEP pipeline is long: district → student → eligibility evaluation
→ request-consent → parent-approve consent → finalize evaluation
ELIGIBLE → create DRAFT IEP → create IEP_IMPLEMENTATION consent →
parent-approve that consent → add at least one goal → optionally add
RELATED_SERVICE consents and propose services → activate IEP →
optionally activate services. Most interesting test claims need the
system at a late-pipeline state.

IDENTITY THREADING — PRD §2.1:

- DistrictAdmin / SchoolPsychologist / SpecialEducationTeacher /
  RelatedServiceProvider are OPAQUE — TEST_USERS shared constants are
  canonical for those roles.

- Parent is OWNERSHIP-GATED. PRD §2.1: "every Parent request
  additionally requires that the value of X-User-ID match the
  parent_user_id recorded on the targeted Student. Mismatch is
  rejected with ERR_PARENT_OWNERSHIP_MISMATCH." Every Parent call
  inside these fixtures threads the student's `parent_user_id`
  through `make_parent_headers(student["parent_user_id"])` — never the
  shared PARENT_FALLBACK_ID.

- PRD §3.2 segregation of duties: "the same opaque identifier may not
  finalize an evaluation on a student for whom it is recorded as
  parent_user_id". Fixtures use distinct ids for the parent and the
  psychologist so this gate is satisfied by default.

Setup calls use `get_success_data` (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    activate_related_service_payload,
    clock_advance_payload,
    close_goal_payload,
    create_consent_payload,
    create_district_payload,
    create_evaluation_payload,
    create_goal_payload,
    create_iep_payload,
    create_progress_report_payload,
    create_related_service_payload,
    create_session_payload,
    create_student_payload,
    create_transition_plan_payload,
    deliver_session_payload,
    finalize_evaluation_payload,
    iso_utc,
    make_objective,
    random_suffix,
    resume_related_service_payload,
)
from .test_users import (
    SCHOOL_PSYCHOLOGIST_ID,
    SCHOOL_PSYCHOLOGIST_ID_ALT,
    TEST_USERS,
    make_parent_headers,
    make_psychologist_headers,
)


# ===========================================================================
# Tier 0: District + clock helpers
# ===========================================================================
def create_district(
    *,
    name: Optional[str] = None,
    state_code: str = "NY",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts — DistrictAdmin only per PRD §3.1.

    PRD §2.7: a newly created district has current_date initialised to
    2025-01-01T00:00:00.000Z.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_district(
        create_district_payload(name=name, state_code=state_code),
        headers,
    )
    return get_success_data(resp)


def advance_clock(
    district_id: str,
    *,
    by_days: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/clock/advance — DistrictAdmin only per
    PRD §2.7.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.advance_clock(
        district_id,
        clock_advance_payload(by_days=by_days),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Student
# ===========================================================================
def create_student(
    district_id: str,
    *,
    external_student_number: Optional[str] = None,
    date_of_birth: str = TEST_DEFAULTS["DEFAULT_DOB"],
    parent_user_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/students — DistrictAdmin only per PRD §3.1.

    Every fixture chain that needs Parent ownership must remember the
    parent_user_id this fixture returns on the Student so the Parent
    headers can be minted via make_parent_headers later.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_student(
        district_id,
        create_student_payload(
            external_student_number=external_student_number,
            date_of_birth=date_of_birth,
            parent_user_id=parent_user_id,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Eligibility evaluation lifecycle
# ===========================================================================
def create_evaluation(
    district_id: str, student_id: str,
    *,
    evaluation_type: str = "INITIAL",
    psychologist_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../eligibility-evaluations — SchoolPsychologist only.

    PRD §3.2: "the server records `requested_at` to the current clock,
    mints `evaluator_user_id` from X-User-ID ... and starts the
    evaluation in REQUESTED."
    """
    headers = psychologist_headers or TEST_USERS["psychologist_headers"]
    resp = api_client.create_eligibility_evaluation(
        district_id, student_id,
        create_evaluation_payload(evaluation_type=evaluation_type),
        headers,
    )
    return get_success_data(resp)


def request_evaluation_consent(
    district_id: str, student_id: str, evaluation_id: str,
    *,
    psychologist_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../eligibility-evaluations/{id}/request-consent.

    PRD §3.2: moves the evaluation to CONSENT_PENDING and
    "simultaneously creates a ParentalConsent with scope=EVALUATION".
    """
    headers = psychologist_headers or TEST_USERS["psychologist_headers"]
    resp = api_client.request_evaluation_consent(
        district_id, student_id, evaluation_id, headers,
    )
    return get_success_data(resp)


def find_pending_consent_for_evaluation(
    district_id: str, student_id: str, evaluation_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Find the auto-created EVALUATION consent for this evaluation by
    listing consents and matching on target_resource_id.

    PRD §3.2 says request-consent auto-creates the consent row but the
    returned envelope is the evaluation, so we list consents to locate
    the new consent id.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.list_consents(
        district_id, student_id, headers,
        params={"scope": "EVALUATION", "status": "PENDING"},
    )
    body = resp.json()
    items = body["data"]
    for c in items:
        if c.get("target_resource_id") == evaluation_id and (
            c.get("status") == "PENDING"
        ):
            return c
    raise AssertionError(
        f"Setup failed: no PENDING EVALUATION consent for "
        f"evaluation_id={evaluation_id}; listed {len(items)} items"
    )


def parent_approve_consent(
    district_id: str, student_id: str, consent_id: str,
    *,
    parent_user_id: str,
) -> Dict[str, Any]:
    """POST .../parental-consents/{id}/approve as the acting Parent.

    Identity threading: PRD §2.1 — Parent is ownership-gated. We mint
    headers via make_parent_headers(student.parent_user_id), which is
    the value recorded on the Student row at creation time.
    """
    resp = api_client.approve_consent(
        district_id, student_id, consent_id,
        make_parent_headers(parent_user_id),
    )
    return get_success_data(resp)


def parent_reject_consent(
    district_id: str, student_id: str, consent_id: str,
    *,
    parent_user_id: str,
) -> Dict[str, Any]:
    resp = api_client.reject_consent(
        district_id, student_id, consent_id,
        make_parent_headers(parent_user_id),
    )
    return get_success_data(resp)


def parent_withdraw_consent(
    district_id: str, student_id: str, consent_id: str,
    *,
    parent_user_id: str,
) -> Dict[str, Any]:
    resp = api_client.withdraw_consent(
        district_id, student_id, consent_id,
        make_parent_headers(parent_user_id),
    )
    return get_success_data(resp)


def finalize_evaluation(
    district_id: str, student_id: str, evaluation_id: str,
    *,
    disability_categories: Optional[List[str]] = None,
    psychologist_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../eligibility-evaluations/{id}/finalize.

    PRD §3.2: empty categories → INELIGIBLE; non-empty → ELIGIBLE.
    The acting psychologist's X-User-ID must equal the evaluation's
    `evaluator_user_id` AND must NOT equal the student's
    parent_user_id (segregation of duties).
    """
    if disability_categories is None:
        disability_categories = ["SLD"]
    headers = psychologist_headers or TEST_USERS["psychologist_headers"]
    resp = api_client.finalize_evaluation(
        district_id, student_id, evaluation_id,
        finalize_evaluation_payload(
            disability_categories=disability_categories,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_eligible_student(
    *,
    district_id: Optional[str] = None,
    parent_user_id: Optional[str] = None,
    date_of_birth: str = TEST_DEFAULTS["DEFAULT_DOB"],
    disability_categories: Optional[List[str]] = None,
    evaluation_type: str = "INITIAL",
    psychologist_id: str = SCHOOL_PSYCHOLOGIST_ID,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a district + student + ELIGIBLE evaluation in one call.

    Returns (district, student, evaluation).

    Identity threading: parent_user_id is intentionally a random id
    distinct from psychologist_id so PRD §3.2 segregation-of-duties is
    satisfied by default.
    """
    if district_id is None:
        district = create_district()
        district_id_val = district["id"]
    else:
        district = {"id": district_id}
        district_id_val = district_id
    if parent_user_id is None:
        parent_user_id = f"parent-{random_suffix(8)}"
    psych_headers = make_psychologist_headers(psychologist_id)
    student = create_student(
        district_id_val,
        date_of_birth=date_of_birth,
        parent_user_id=parent_user_id,
    )
    evaluation = create_evaluation(
        district_id_val, student["id"],
        evaluation_type=evaluation_type,
        psychologist_headers=psych_headers,
    )
    evaluation = request_evaluation_consent(
        district_id_val, student["id"], evaluation["id"],
        psychologist_headers=psych_headers,
    )
    consent = find_pending_consent_for_evaluation(
        district_id_val, student["id"], evaluation["id"],
    )
    parent_approve_consent(
        district_id_val, student["id"], consent["id"],
        parent_user_id=parent_user_id,
    )
    evaluation = finalize_evaluation(
        district_id_val, student["id"], evaluation["id"],
        disability_categories=disability_categories,
        psychologist_headers=psych_headers,
    )
    return district, student, evaluation


# ===========================================================================
# Tier 3: IEP — create DRAFT, add goal, consent, activate
# ===========================================================================
def create_iep(
    district_id: str, student_id: str,
    *,
    meeting_held_at: Optional[str] = None,
    effective_start_date: Optional[str] = None,
    total_instructional_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_INSTRUCTIONAL_MINUTES"
    ],
    total_school_day_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_SCHOOL_DAY_MINUTES"
    ],
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../ieps — SpecialEducationTeacher only per PRD §3.3."""
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.create_iep(
        district_id, student_id,
        create_iep_payload(
            meeting_held_at=meeting_held_at,
            effective_start_date=effective_start_date,
            total_instructional_minutes_per_week=(
                total_instructional_minutes_per_week
            ),
            total_school_day_minutes_per_week=(
                total_school_day_minutes_per_week
            ),
        ),
        headers,
    )
    return get_success_data(resp)


def create_goal_with_single_objective(
    district_id: str, student_id: str, iep_id: str,
    *,
    domain: str = "ACADEMIC",
    description: str = "Demonstrate grade-level reading comprehension.",
    objective_id: Optional[str] = None,
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../goals with a single objective of weight=1.0 — the
    simplest valid goal per PRD §3.3."""
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.create_goal(
        district_id, student_id, iep_id,
        create_goal_payload(
            domain=domain,
            description=description,
            objectives=[make_objective(
                objective_id=objective_id, weight=1.0,
            )],
        ),
        headers,
    )
    return get_success_data(resp)


def create_goal_with_objectives(
    district_id: str, student_id: str, iep_id: str,
    *,
    objectives: List[Dict[str, Any]],
    domain: str = "ACADEMIC",
    description: str = "Multi-objective goal.",
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../goals — generic helper for multi-objective tests."""
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.create_goal(
        district_id, student_id, iep_id,
        create_goal_payload(
            domain=domain,
            description=description,
            objectives=objectives,
        ),
        headers,
    )
    return get_success_data(resp)


def create_iep_implementation_consent_approved(
    district_id: str, student_id: str, iep_id: str,
    *,
    parent_user_id: str,
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create an IEP_IMPLEMENTATION consent then parent-approve it.

    PRD §3.4: SpecialEducationTeacher creates the consent; the Parent
    (whose X-User-ID equals Student.parent_user_id) approves it.
    """
    teacher = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.create_parental_consent(
        district_id, student_id,
        create_consent_payload(
            scope="IEP_IMPLEMENTATION",
            target_resource_type="IEP",
            target_resource_id=iep_id,
        ),
        teacher,
    )
    consent = get_success_data(resp)
    parent_approve_consent(
        district_id, student_id, consent["id"],
        parent_user_id=parent_user_id,
    )
    return consent


def activate_iep(
    district_id: str, student_id: str, iep_id: str,
    *,
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../ieps/{id}/activate.

    PRD §3.3: transitions DRAFT → ACTIVE if all activation
    preconditions are satisfied.
    """
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.activate_iep(
        district_id, student_id, iep_id, headers,
    )
    return get_success_data(resp)


def begin_amendment(
    district_id: str, student_id: str, iep_id: str,
    *,
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    return get_success_data(
        api_client.begin_iep_amendment(
            district_id, student_id, iep_id, headers,
        ),
    )


def finalize_amendment(
    district_id: str, student_id: str, iep_id: str,
    *,
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    return get_success_data(
        api_client.finalize_iep_amendment(
            district_id, student_id, iep_id, headers,
        ),
    )


def setup_active_iep(
    *,
    parent_user_id: Optional[str] = None,
    date_of_birth: str = TEST_DEFAULTS["DEFAULT_DOB"],
    disability_categories: Optional[List[str]] = None,
    total_instructional_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_INSTRUCTIONAL_MINUTES"
    ],
    total_school_day_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_SCHOOL_DAY_MINUTES"
    ],
    effective_start_date: Optional[str] = None,
    meeting_held_at: Optional[str] = None,
    objectives: Optional[List[Dict[str, Any]]] = None,
    district_id: Optional[str] = None,
    psychologist_id: str = SCHOOL_PSYCHOLOGIST_ID,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """End-to-end shortcut: build district + ELIGIBLE student + DRAFT
    IEP with one APPROVED IEP_IMPLEMENTATION consent + at least one
    PROPOSED goal → activate IEP.

    Returns (district, student, evaluation, iep_active, goal).

    The returned `student` has its `parent_user_id` recorded so
    downstream Parent-driven calls can mint headers via
    make_parent_headers(student["parent_user_id"]).
    """
    district, student, evaluation = setup_eligible_student(
        district_id=district_id,
        parent_user_id=parent_user_id,
        date_of_birth=date_of_birth,
        disability_categories=disability_categories,
        psychologist_id=psychologist_id,
    )
    iep = create_iep(
        district["id"], student["id"],
        meeting_held_at=meeting_held_at,
        effective_start_date=effective_start_date,
        total_instructional_minutes_per_week=(
            total_instructional_minutes_per_week
        ),
        total_school_day_minutes_per_week=(
            total_school_day_minutes_per_week
        ),
    )
    if objectives is None:
        goal = create_goal_with_single_objective(
            district["id"], student["id"], iep["id"],
        )
    else:
        goal = create_goal_with_objectives(
            district["id"], student["id"], iep["id"],
            objectives=objectives,
        )
    create_iep_implementation_consent_approved(
        district["id"], student["id"], iep["id"],
        parent_user_id=student["parent_user_id"],
    )
    iep_active = activate_iep(
        district["id"], student["id"], iep["id"],
    )
    return district, student, evaluation, iep_active, goal


# ===========================================================================
# Tier 4: Related services — propose, gate by consent, activate, suspend
# ===========================================================================
def propose_related_service(
    district_id: str, student_id: str, iep_id: str,
    *,
    service_type: str = "OT",
    minutes_per_week: int = 60,
    location_setting: str = "PULL_OUT",
    provider_user_id: Optional[str] = None,
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../related-services — SpecialEducationTeacher only per
    PRD §3.3.
    """
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.create_related_service(
        district_id, student_id, iep_id,
        create_related_service_payload(
            service_type=service_type,
            minutes_per_week=minutes_per_week,
            location_setting=location_setting,
            provider_user_id=provider_user_id,
        ),
        headers,
    )
    return get_success_data(resp)


def create_related_service_consent_approved(
    district_id: str, student_id: str, service_id: str,
    *,
    parent_user_id: str,
    provider_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a RELATED_SERVICE consent, then parent-approve it.

    PRD §3.4: RelatedServiceProvider creates the consent;
    the Parent (whose X-User-ID equals Student.parent_user_id)
    approves it.
    """
    provider = provider_headers or TEST_USERS["provider_headers"]
    resp = api_client.create_parental_consent(
        district_id, student_id,
        create_consent_payload(
            scope="RELATED_SERVICE",
            target_resource_type="RelatedService",
            target_resource_id=service_id,
        ),
        provider,
    )
    consent = get_success_data(resp)
    parent_approve_consent(
        district_id, student_id, consent["id"],
        parent_user_id=parent_user_id,
    )
    return consent


def activate_related_service(
    district_id: str, student_id: str, iep_id: str,
    service_id: str,
    *,
    consent_id: str,
    provider_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PUT .../related-services/{id}/activate.

    PRD §3.6: requires consent in APPROVED status.
    """
    headers = provider_headers or TEST_USERS["provider_headers"]
    resp = api_client.activate_related_service(
        district_id, student_id, iep_id, service_id,
        activate_related_service_payload(consent_id=consent_id),
        headers,
    )
    return get_success_data(resp)


def suspend_related_service(
    district_id: str, student_id: str, iep_id: str,
    service_id: str,
    *,
    provider_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = provider_headers or TEST_USERS["provider_headers"]
    return get_success_data(
        api_client.suspend_related_service(
            district_id, student_id, iep_id, service_id, headers,
        ),
    )


def resume_related_service(
    district_id: str, student_id: str, iep_id: str,
    service_id: str,
    *,
    consent_id: str,
    provider_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = provider_headers or TEST_USERS["provider_headers"]
    return get_success_data(
        api_client.resume_related_service(
            district_id, student_id, iep_id, service_id,
            resume_related_service_payload(consent_id=consent_id),
            headers,
        ),
    )


def setup_active_iep_with_active_service(
    *,
    service_type: str = "OT",
    minutes_per_week: int = 60,
    location_setting: str = "PULL_OUT",
    total_instructional_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_INSTRUCTIONAL_MINUTES"
    ],
    total_school_day_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_SCHOOL_DAY_MINUTES"
    ],
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Build (district, student, IEP, RelatedService, RELATED_SERVICE
    consent) where the service is ACTIVE.

    Returns (district, student, iep_active, service_active, consent).
    """
    district, student, _eval, iep, _goal = setup_active_iep(
        total_instructional_minutes_per_week=(
            total_instructional_minutes_per_week
        ),
        total_school_day_minutes_per_week=(
            total_school_day_minutes_per_week
        ),
    )
    service = propose_related_service(
        district["id"], student["id"], iep["id"],
        service_type=service_type,
        minutes_per_week=minutes_per_week,
        location_setting=location_setting,
    )
    consent = create_related_service_consent_approved(
        district["id"], student["id"], service["id"],
        parent_user_id=student["parent_user_id"],
    )
    service_active = activate_related_service(
        district["id"], student["id"], iep["id"], service["id"],
        consent_id=consent["id"],
    )
    return district, student, iep, service_active, consent


# ===========================================================================
# Tier 5: Service sessions — schedule, deliver, cancel
# ===========================================================================
def create_session(
    district_id: str, student_id: str, iep_id: str, service_id: str,
    *,
    scheduled_start: str,
    scheduled_end: str,
    provider_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = provider_headers or TEST_USERS["provider_headers"]
    resp = api_client.create_session(
        district_id, student_id, iep_id, service_id,
        create_session_payload(
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        headers,
    )
    return get_success_data(resp)


def deliver_session(
    district_id: str, student_id: str, iep_id: str, service_id: str,
    session_id: str,
    *,
    actual_minutes: int,
    provider_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = provider_headers or TEST_USERS["provider_headers"]
    return get_success_data(
        api_client.deliver_session(
            district_id, student_id, iep_id, service_id, session_id,
            deliver_session_payload(actual_minutes=actual_minutes),
            headers,
        ),
    )


def cancel_session(
    district_id: str, student_id: str, iep_id: str, service_id: str,
    session_id: str,
    *,
    provider_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = provider_headers or TEST_USERS["provider_headers"]
    return get_success_data(
        api_client.cancel_session(
            district_id, student_id, iep_id, service_id, session_id,
            headers,
        ),
    )


def schedule_three_25min_sessions_in_past(
    district_id: str, student_id: str, iep_id: str, service_id: str,
) -> List[Dict[str, Any]]:
    """Schedule three SCHEDULED 25-minute ServiceSessions on the given
    service with `scheduled_start <= current_date` and pairwise
    non-overlapping. Used to set up the compensatory-service test
    pinned in PRD §3.6 (three missed 25-minute sessions → 114
    compensatory minutes owed under round-then-sum).

    PRD §3.6 (closed-interval overlap rule): two sessions on the same
    RelatedService whose `scheduled_end` and `scheduled_start` touch
    are rejected. We separate the three sessions by one minute so
    they do not touch.
    """
    sessions: List[Dict[str, Any]] = []
    # All three start well before 2025-01-01 so they are in the past
    # even at the initial clock (PRD §2.7: districts start at
    # 2025-01-01T00:00:00.000Z).
    bases = [
        ("2024-12-01T09:00:00.000Z", "2024-12-01T09:25:00.000Z"),
        ("2024-12-08T09:00:00.000Z", "2024-12-08T09:25:00.000Z"),
        ("2024-12-15T09:00:00.000Z", "2024-12-15T09:25:00.000Z"),
    ]
    for start, end in bases:
        s = create_session(
            district_id, student_id, iep_id, service_id,
            scheduled_start=start, scheduled_end=end,
        )
        sessions.append(s)
    return sessions


# ===========================================================================
# Tier 6: Transition plan
# ===========================================================================
def create_transition_plan(
    district_id: str, student_id: str, iep_id: str,
    *,
    parent_invitation_documented: bool = True,
    student_invitation_documented: bool = True,
    teacher_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.create_transition_plan(
        district_id, student_id, iep_id,
        create_transition_plan_payload(
            parent_invitation_documented=parent_invitation_documented,
            student_invitation_documented=student_invitation_documented,
            **overrides,
        ),
        headers,
    )
    return get_success_data(resp)


def finalize_transition_plan(
    district_id: str, student_id: str, iep_id: str,
    *,
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    return get_success_data(
        api_client.finalize_transition_plan(
            district_id, student_id, iep_id, headers,
        ),
    )


# ===========================================================================
# Tier 7: Progress reports
# ===========================================================================
def create_progress_report(
    district_id: str, student_id: str, iep_id: str, goal_id: str,
    *,
    reporting_period_index: int,
    objective_progress: List[Dict[str, Any]],
    narrative: str = TEST_DEFAULTS["PROGRESS_NARRATIVE"],
    teacher_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../goals/{id}/progress-reports.

    PRD §3.7: required inputs are `reporting_period_index`,
    `objective_progress` (one entry per objective on the parent goal
    — exact set parity), and `narrative` (1..2000 chars).
    """
    headers = teacher_headers or TEST_USERS["teacher_headers"]
    resp = api_client.create_progress_report(
        district_id, student_id, iep_id, goal_id,
        create_progress_report_payload(
            reporting_period_index=reporting_period_index,
            objective_progress=objective_progress,
            narrative=narrative,
        ),
        headers,
    )
    return get_success_data(resp)


def get_goal(
    district_id: str, student_id: str, iep_id: str, goal_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Re-read the goal after a mutation."""
    headers = headers or TEST_USERS["teacher_headers"]
    body = api_client.list_goals(
        district_id, student_id, iep_id, headers,
        params={"limit": 100},
    ).json()
    for g in body["data"]:
        if g["id"] == goal_id:
            return g
    raise AssertionError(f"Setup failed: goal {goal_id} not found")


def get_iep(
    district_id: str, student_id: str, iep_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["teacher_headers"]
    return get_success_data(
        api_client.get_iep(district_id, student_id, iep_id, headers),
    )


def get_student(
    district_id: str, student_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_student(district_id, student_id, headers),
    )


def get_service(
    district_id: str, student_id: str, iep_id: str, service_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["teacher_headers"]
    body = api_client.list_related_services(
        district_id, student_id, iep_id, headers,
        params={"limit": 100},
    ).json()
    for s in body["data"]:
        if s["id"] == service_id:
            return s
    raise AssertionError(f"Setup failed: service {service_id} not found")


def get_evaluation(
    district_id: str, student_id: str, evaluation_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["psychologist_headers"]
    return get_success_data(
        api_client.get_evaluation(
            district_id, student_id, evaluation_id, headers,
        ),
    )


def get_consent(
    district_id: str, student_id: str, consent_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """List consents and locate by id (no by-id read endpoint defined
    in PRD §4)."""
    headers = headers or TEST_USERS["admin_headers"]
    body = api_client.list_consents(
        district_id, student_id, headers, params={"limit": 100},
    ).json()
    for c in body["data"]:
        if c["id"] == consent_id:
            return c
    raise AssertionError(f"Setup failed: consent {consent_id} not found")


def get_lre_summary(
    district_id: str, student_id: str, iep_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["teacher_headers"]
    return get_success_data(
        api_client.get_lre_summary(
            district_id, student_id, iep_id, headers,
        ),
    )


__all__ = [
    "create_district",
    "advance_clock",
    "create_student",
    "create_evaluation",
    "request_evaluation_consent",
    "find_pending_consent_for_evaluation",
    "parent_approve_consent",
    "parent_reject_consent",
    "parent_withdraw_consent",
    "finalize_evaluation",
    "setup_eligible_student",
    "create_iep",
    "create_goal_with_single_objective",
    "create_goal_with_objectives",
    "create_iep_implementation_consent_approved",
    "activate_iep",
    "begin_amendment",
    "finalize_amendment",
    "setup_active_iep",
    "propose_related_service",
    "create_related_service_consent_approved",
    "activate_related_service",
    "suspend_related_service",
    "resume_related_service",
    "setup_active_iep_with_active_service",
    "create_session",
    "deliver_session",
    "cancel_session",
    "schedule_three_25min_sessions_in_past",
    "create_transition_plan",
    "finalize_transition_plan",
    "create_progress_report",
    "get_goal",
    "get_iep",
    "get_student",
    "get_service",
    "get_evaluation",
    "get_consent",
    "get_lre_summary",
]
