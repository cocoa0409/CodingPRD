"""Composite setup helpers for multi-step test prerequisites.

Setup steps use get_success_data() (lenient validator) so a broken precondition
fails with a clear "Setup step failed" message rather than a confusing
assertion error deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    book_session_payload,
    create_case_payload,
    create_consultant_payload,
    create_course_payload,
    create_plan_payload,
    create_refund_request_payload,
    deny_refund_payload,
    enroll_payload,
    purchase_package_payload,
    register_family_payload,
    respond_message_payload,
    review_log_payload,
    review_questionnaire_payload,
    send_message_payload,
    set_clock_payload,
    submit_log_payload,
    submit_questionnaire_payload,
)
from .test_users import TEST_USERS, make_consultant_headers, make_parent_headers

ADMIN = TEST_USERS["practice_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

DEFAULT_BIRTH_DATE = "2026-05-01"  # 3 whole months at the default clock -> NEWBORN
INFANT_BIRTH_DATE = "2026-03-15"  # 4 whole months at the default clock -> INFANT


# ─── Tier 0: single-entity creation ────────────────────


def create_consultant(max_active_cases=5, full_name="Dana Sleep", certification_no="CERT-000"):
    """Create a Consultant as PracticeAdmin. Returns the consultant."""
    res = api_client.create_consultant(
        create_consultant_payload(
            full_name=full_name,
            certification_no=certification_no,
            max_active_cases=max_active_cases,
        ),
        ADMIN,
    )
    return get_success_data(res)


def register_family(full_name="Fam Z", email="z@x.com"):
    """Self-register a ClientFamily as Anonymous. Returns the family."""
    res = api_client.register_family(
        register_family_payload(full_name=full_name, email=email), ANON
    )
    return get_success_data(res)


def open_case(
    family,
    consultant,
    child_birth_date=DEFAULT_BIRTH_DATE,
    delivery_mode="ONE_ON_ONE",
    guarantee_goal_night_wakings=2,
    as_admin=False,
):
    """Open a ClientCase for the family. Returns the case (INTAKE)."""
    headers = ADMIN if as_admin else make_parent_headers(family["id"])
    res = api_client.create_case(
        create_case_payload(
            family["id"],
            consultant["id"],
            child_birth_date=child_birth_date,
            delivery_mode=delivery_mode,
            guarantee_goal_night_wakings=guarantee_goal_night_wakings,
        ),
        headers,
    )
    return get_success_data(res)


# ─── Fresh reads ────────────────────────────────────────


def get_case(case_id, headers=None):
    return get_success_data(api_client.get_case(case_id, headers or ADMIN))


def get_package(package_id, headers=None):
    return get_success_data(api_client.get_package(package_id, headers or ADMIN))


def get_consultant(consultant_id, headers=None):
    return get_success_data(api_client.get_consultant(consultant_id, headers or ADMIN))


def get_family(family_id, headers=None):
    return get_success_data(api_client.get_family(family_id, headers or ADMIN))


def get_course(course_id, headers=None):
    return get_success_data(api_client.get_course(course_id, headers or ADMIN))


# ─── Tier 1: state progression steps ───────────────────


def submit_questionnaire(case, family, answers=None):
    """Parent submits the intake questionnaire. Returns the questionnaire (SUBMITTED)."""
    res = api_client.submit_questionnaire(
        case["id"],
        submit_questionnaire_payload(answers),
        make_parent_headers(family["id"]),
    )
    return get_success_data(res)


def review_case_questionnaire(questionnaire_id, consultant, adjustment_points=0, review_note=None):
    """Assigned consultant reviews the questionnaire. Returns it (REVIEWED)."""
    payload = review_questionnaire_payload(adjustment_points)
    if review_note is not None:
        payload["review_note"] = review_note
    res = api_client.review_questionnaire(
        questionnaire_id, payload, make_consultant_headers(consultant["id"])
    )
    return get_success_data(res)


def create_plan_for_case(
    case_id,
    consultant,
    method="GENTLE_NO_CRY",
    target_night_wake_count=2,
    target_longest_stretch_minutes=240,
    notes=None,
):
    """Create a plan with the case's current version (fetched fresh). Returns the plan."""
    current = get_case(case_id)
    payload = create_plan_payload(
        current["version"],
        method=method,
        target_night_wake_count=target_night_wake_count,
        target_longest_stretch_minutes=target_longest_stretch_minutes,
    )
    if notes is not None:
        payload["notes"] = notes
    res = api_client.create_plan(
        case_id, payload, make_consultant_headers(consultant["id"])
    )
    return get_success_data(res)


def resume_plan(plan_id, consultant):
    res = api_client.resume_plan(plan_id, make_consultant_headers(consultant["id"]))
    return get_success_data(res)


def purchase_package_for_case(
    case_id,
    family,
    tier="BASIC",
    kind="INITIAL",
    starts_on="2026-08-01",
    apply_credit_cents=None,
    as_admin=False,
):
    """Purchase a support package for the case. Returns the package."""
    overrides = {"tier": tier, "kind": kind, "starts_on": starts_on}
    if apply_credit_cents is not None:
        overrides["apply_credit_cents"] = apply_credit_cents
    headers = ADMIN if as_admin else make_parent_headers(family["id"])
    res = api_client.purchase_package(case_id, purchase_package_payload(**overrides), headers)
    return get_success_data(res)


def set_logical_clock(to_iso8601):
    """Advance the logical clock as PracticeAdmin. Returns the clock response data."""
    res = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return get_success_data(res)


def submit_log_for_case(
    case_id,
    family,
    log_date,
    night_wake_count=3,
    longest_stretch_minutes=120,
    nap_count=2,
    nap_total_minutes=130,
    notes=None,
):
    """Parent submits a nightly log. Returns the log (PENDING_REVIEW)."""
    payload = submit_log_payload(
        log_date,
        night_wake_count=night_wake_count,
        longest_stretch_minutes=longest_stretch_minutes,
        nap_count=nap_count,
        nap_total_minutes=nap_total_minutes,
    )
    if notes is not None:
        payload["notes"] = notes
    res = api_client.submit_log(case_id, payload, make_parent_headers(family["id"]))
    return get_success_data(res)


def review_log_entry(log_id, consultant, outcome="ON_TRACK", review_note=None):
    """Assigned consultant reviews a log. Returns the reviewed log."""
    payload = review_log_payload(outcome)
    if review_note is not None:
        payload["review_note"] = review_note
    res = api_client.review_log(log_id, payload, make_consultant_headers(consultant["id"]))
    return get_success_data(res)


def book_session_for_case(
    case_id,
    package_id,
    actor_headers,
    session_type="REGRESSION",
    scheduled_start="2026-08-10T10:00:00Z",
    scheduled_end="2026-08-10T11:00:00Z",
):
    """Book a session carrying the package's current version (fetched fresh).
    Returns the session (SCHEDULED)."""
    pkg = get_package(package_id)
    res = api_client.book_session(
        case_id,
        book_session_payload(
            pkg["version"],
            session_type=session_type,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        actor_headers,
    )
    return get_success_data(res)


def complete_session(session_id, consultant):
    res = api_client.complete_session(session_id, make_consultant_headers(consultant["id"]))
    return get_success_data(res)


def cancel_session(session_id, headers):
    res = api_client.cancel_session(session_id, headers)
    return get_success_data(res)


def send_case_message(case_id, family, body="quick question"):
    """Parent sends a support message. Returns the message (AWAITING_RESPONSE)."""
    res = api_client.send_message(
        case_id, send_message_payload(body), make_parent_headers(family["id"])
    )
    return get_success_data(res)


def respond_to_message(message_id, consultant, response_body="answer"):
    res = api_client.respond_message(
        message_id,
        respond_message_payload(response_body),
        make_consultant_headers(consultant["id"]),
    )
    return get_success_data(res)


def request_refund(case_id, family, refund_type="COOLING_OFF", reason=None):
    payload = create_refund_request_payload(refund_type)
    if reason is not None:
        payload["reason"] = reason
    res = api_client.create_refund_request(
        case_id, payload, make_parent_headers(family["id"])
    )
    return get_success_data(res)


def approve_refund(refund_id):
    return get_success_data(api_client.approve_refund(refund_id, ADMIN))


def deny_refund(refund_id, denial_reason="not eligible"):
    return get_success_data(api_client.deny_refund(refund_id, deny_refund_payload(denial_reason), ADMIN))


def pay_refund(refund_id):
    return get_success_data(api_client.pay_refund(refund_id, ADMIN))


def complete_case(case_id, consultant):
    res = api_client.complete_case(case_id, make_consultant_headers(consultant["id"]))
    return get_success_data(res)


def create_course(consultant, title="Newborn Sleep 101", starts_on="2026-09-01", capacity=2, price_cents=19900):
    res = api_client.create_course(
        create_course_payload(
            consultant["id"], title=title, starts_on=starts_on, capacity=capacity, price_cents=price_cents
        ),
        ADMIN,
    )
    return get_success_data(res)


def enroll_case(course_id, case_id, family):
    res = api_client.enroll(course_id, enroll_payload(case_id), make_parent_headers(family["id"]))
    return get_success_data(res)


# ─── Tier 2/3: composite journey bundles ───────────────


def setup_case_in_planning(
    child_birth_date=DEFAULT_BIRTH_DATE,
    delivery_mode="ONE_ON_ONE",
    max_active_cases=5,
    answers=None,
    guarantee_goal_night_wakings=2,
    adjustment_points=0,
):
    """Consultant + family + case walked INTAKE -> ASSESSMENT -> PLANNING.

    Returns {"consultant", "family", "case", "questionnaire"} with `case` fresh
    (PLANNING)."""
    consultant = create_consultant(max_active_cases=max_active_cases)
    family = register_family()
    case = open_case(
        family,
        consultant,
        child_birth_date=child_birth_date,
        delivery_mode=delivery_mode,
        guarantee_goal_night_wakings=guarantee_goal_night_wakings,
    )
    questionnaire = submit_questionnaire(case, family, answers)
    review_case_questionnaire(questionnaire["id"], consultant, adjustment_points=adjustment_points)
    case = get_case(case["id"])
    return {
        "consultant": consultant,
        "family": family,
        "case": case,
        "questionnaire": questionnaire,
    }


def setup_case_in_active_support(
    child_birth_date=DEFAULT_BIRTH_DATE,
    delivery_mode="ONE_ON_ONE",
    max_active_cases=5,
    method="GENTLE_NO_CRY",
    answers=None,
    guarantee_goal_night_wakings=2,
):
    """Bundle from setup_case_in_planning plus a first ACTIVE plan (case in
    ACTIVE_SUPPORT). Returns bundle with "plan" and fresh "case"."""
    bundle = setup_case_in_planning(
        child_birth_date=child_birth_date,
        delivery_mode=delivery_mode,
        max_active_cases=max_active_cases,
        answers=answers,
        guarantee_goal_night_wakings=guarantee_goal_night_wakings,
    )
    plan = create_plan_for_case(bundle["case"]["id"], bundle["consultant"], method=method)
    bundle["plan"] = plan
    bundle["case"] = get_case(bundle["case"]["id"])
    return bundle


def setup_case_with_package(
    tier="BASIC",
    starts_on="2026-08-01",
    child_birth_date=DEFAULT_BIRTH_DATE,
    max_active_cases=5,
    method="GENTLE_NO_CRY",
    guarantee_goal_night_wakings=2,
    kind="INITIAL",
):
    """Case in ACTIVE_SUPPORT with a purchased package. Returns bundle with
    "package" (ACTIVE)."""
    bundle = setup_case_in_active_support(
        child_birth_date=child_birth_date,
        max_active_cases=max_active_cases,
        method=method,
        guarantee_goal_night_wakings=guarantee_goal_night_wakings,
    )
    package = purchase_package_for_case(
        bundle["case"]["id"], bundle["family"], tier=tier, kind=kind, starts_on=starts_on
    )
    bundle["package"] = package
    return bundle


def setup_completed_case(
    child_birth_date=DEFAULT_BIRTH_DATE,
    max_active_cases=5,
    package_tier="BASIC",
    package_starts_on="2026-08-01",
    expiry_clock="2026-08-15T00:00:00Z",
):
    """Full journey to COMPLETED: case ACTIVE_SUPPORT + package purchased, then the
    clock advances past the package's coverage (ACTIVE -> EXPIRED) and the assigned
    consultant completes the case. Returns bundle with fresh "case" (COMPLETED)."""
    bundle = setup_case_with_package(
        tier=package_tier,
        starts_on=package_starts_on,
        child_birth_date=child_birth_date,
        max_active_cases=max_active_cases,
    )
    set_logical_clock(expiry_clock)
    case = complete_case(bundle["case"]["id"], bundle["consultant"])
    bundle["case"] = case
    bundle["package"] = get_package(bundle["package"]["id"])
    return bundle


def setup_repeat_family_with_planning_case(child_birth_date=DEFAULT_BIRTH_DATE):
    """A repeat client family (one COMPLETED case) plus a second case of the same
    family walked to PLANNING. Returns {"consultant", "family", "case1", "case2"}
    with case2 fresh (PLANNING)."""
    consultant = create_consultant(max_active_cases=5)
    family = register_family()
    case1 = open_case(family, consultant, child_birth_date=child_birth_date)
    q1 = submit_questionnaire(case1, family)
    review_case_questionnaire(q1["id"], consultant)
    create_plan_for_case(case1["id"], consultant)
    purchase_package_for_case(case1["id"], family, tier="BASIC", starts_on="2026-08-01")
    set_logical_clock("2026-08-15T00:00:00Z")
    case1 = complete_case(case1["id"], consultant)

    case2 = open_case(family, consultant, child_birth_date=child_birth_date)
    q2 = submit_questionnaire(case2, family)
    review_case_questionnaire(q2["id"], consultant)
    case2 = get_case(case2["id"])
    return {"consultant": consultant, "family": family, "case1": case1, "case2": case2}


# ─── Tier 4: accumulation / threshold targeting ────────


def setup_guarantee_case(
    reviewed_log_count,
    goal=2,
    wake_count_for_date=None,
    child_birth_date=DEFAULT_BIRTH_DATE,
    max_active_cases=5,
):
    """Case ACTIVE_SUPPORT with an EXPIRED BASIC package ([2026-08-01, 2026-08-14])
    and `reviewed_log_count` logs for 2026-08-01 onward, each reviewed ON_TRACK.

    `wake_count_for_date`: optional callable (day_index 0-based -> night_wake_count);
    defaults to 5 (above the default goal, i.e. a miss) for every log.
    Returns bundle with "package" (EXPIRED) and "log_ids". Clock ends at 2026-08-15.
    """
    bundle = setup_case_with_package(
        tier="BASIC",
        starts_on="2026-08-01",
        child_birth_date=child_birth_date,
        max_active_cases=max_active_cases,
        guarantee_goal_night_wakings=goal,
    )
    set_logical_clock("2026-08-15T00:00:00Z")
    log_ids = []
    for i in range(reviewed_log_count):
        day = i + 1
        log_date = f"2026-08-{day:02d}"
        wakes = wake_count_for_date(i) if wake_count_for_date else 5
        log = submit_log_for_case(
            bundle["case"]["id"],
            bundle["family"],
            log_date,
            night_wake_count=wakes,
            longest_stretch_minutes=100,
            nap_count=2,
            nap_total_minutes=120,
        )
        review_log_entry(log["id"], bundle["consultant"], outcome="ON_TRACK")
        log_ids.append(log["id"])
    bundle["package"] = get_package(bundle["package"]["id"])
    bundle["log_ids"] = log_ids
    return bundle


def setup_course_with_cases(
    num_cases,
    capacity=1,
    starts_on="2026-09-01",
    title="Infant Sleep Basics",
    price_cents=14900,
):
    """Group course plus `num_cases` GROUP_COURSE cases of one family (no
    enrollments yet). Returns {"consultant", "family", "course", "cases"}."""
    consultant = create_consultant(max_active_cases=5)
    family = register_family()
    course = create_course(
        consultant, title=title, starts_on=starts_on, capacity=capacity, price_cents=price_cents
    )
    cases = [
        open_case(family, consultant, delivery_mode="GROUP_COURSE") for _ in range(num_cases)
    ]
    return {"consultant": consultant, "family": family, "course": course, "cases": cases}
