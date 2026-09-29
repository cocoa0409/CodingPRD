"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient `get_success_data()` validator so that a
broken setup reports itself as a setup failure rather than as a mysterious
assertion mismatch.

Identity threading: whenever a helper needs to act as a `HomeboundTeacher` or a
`ClassroomTeacher` it builds the headers from the real `Teacher` row's `id`,
because for those two roles `X-User-ID` *is* the teacher's `id` (PRD §2.1).
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_ACTIVATION_INSTANT, CLOCK_CONFIG_INSTANT
from .factories import (
    create_assignment_payload,
    create_case_payload,
    create_certification_payload,
    create_entitlement_rule_payload,
    create_extension_request_payload,
    create_pacing_sync_payload,
    create_safety_review_payload,
    create_session_payload,
    create_sped_service_log_payload,
    create_student_payload,
    create_teacher_payload,
    create_transition_plan_payload,
    log_delivered_payload,
    review_certification_payload,
    set_clock_payload,
    void_session_payload,
)
from .test_users import (
    CM_HEADERS,
    NR_HEADERS,
    PA_HEADERS,
    make_classroom_teacher_headers,
    make_homebound_teacher_headers,
)


# ===========================================================================
# Single-call primitives
# ===========================================================================


def set_clock(to_iso8601: str, headers: dict = None) -> dict:
    """Move the server's logical clock to an absolute UTC instant (PRD §2.4)."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), headers or PA_HEADERS)
    )


def register_student(**overrides) -> dict:
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), PA_HEADERS)
    )


def register_teacher(**overrides) -> dict:
    return get_success_data(
        api_client.create_teacher(create_teacher_payload(**overrides), PA_HEADERS)
    )


def publish_entitlement_rule(**overrides) -> dict:
    return get_success_data(
        api_client.create_entitlement_rule(
            create_entitlement_rule_payload(**overrides), PA_HEADERS
        )
    )


def open_case(student_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_case(
            create_case_payload(student_id, **overrides), headers or CM_HEADERS
        )
    )


def read_case(case_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_case(case_id, headers or CM_HEADERS))


def case_version(case_id: str) -> int:
    return read_case(case_id)["version"]


def read_teacher(teacher_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_teacher(teacher_id, headers or PA_HEADERS))


def read_assignment(assignment_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_assignment(assignment_id, headers or CM_HEADERS)
    )


def read_session(session_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_session(session_id, headers or CM_HEADERS))


def submit_certification(
    case_id: str, expected_case_version: int = None, headers: dict = None, **overrides
) -> dict:
    if expected_case_version is None:
        expected_case_version = case_version(case_id)
    return get_success_data(
        api_client.create_certification(
            create_certification_payload(
                case_id, expected_case_version, **overrides
            ),
            headers or CM_HEADERS,
        )
    )


def review_certification(
    certification_id: str, decision: str = "ACCEPT", headers: dict = None, **overrides
) -> dict:
    return get_success_data(
        api_client.review_certification(
            certification_id,
            review_certification_payload(decision, **overrides),
            headers or NR_HEADERS,
        )
    )


def record_safety_review(case_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_safety_review(
            create_safety_review_payload(case_id, **overrides), headers or CM_HEADERS
        )
    )


def finalize_safety_review(review_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.finalize_safety_review(review_id, headers or CM_HEADERS)
    )


def propose_assignment(
    case_id: str,
    role: str = "PRIMARY",
    teacher_id: str = None,
    headers: dict = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(case_id, role, teacher_id, **overrides),
            headers or CM_HEADERS,
        )
    )


def accept_assignment(assignment_id: str, teacher_id: str) -> dict:
    """Acceptance is the assigned teacher's own act (PRD §3.4)."""
    return get_success_data(
        api_client.accept_assignment(
            assignment_id, make_homebound_teacher_headers(teacher_id)
        )
    )


def activate_case(case_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.activate_case(case_id, headers or PA_HEADERS))


def schedule_session(
    case_id: str, assignment_id: str, headers: dict = None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_session(
            create_session_payload(case_id, assignment_id, **overrides),
            headers or CM_HEADERS,
        )
    )


def log_session_delivered(session_id: str, teacher_id: str, actual_minutes: int) -> dict:
    return get_success_data(
        api_client.log_session(
            session_id,
            log_delivered_payload(actual_minutes),
            make_homebound_teacher_headers(teacher_id),
        )
    )


def log_session(session_id: str, teacher_id: str, payload: dict) -> dict:
    return get_success_data(
        api_client.log_session(
            session_id, payload, make_homebound_teacher_headers(teacher_id)
        )
    )


def verify_session(session_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.verify_session(session_id, headers or PA_HEADERS)
    )


def void_session(session_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.void_session(
            session_id, void_session_payload(**overrides), headers or PA_HEADERS
        )
    )


def open_pacing_sync(
    case_id: str, classroom_teacher_id: str, headers: dict = None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_pacing_sync(
            create_pacing_sync_payload(case_id, classroom_teacher_id, **overrides),
            headers or CM_HEADERS,
        )
    )


def acknowledge_pacing_sync(sync_id: str, classroom_teacher_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_pacing_sync(
            sync_id, make_classroom_teacher_headers(classroom_teacher_id)
        )
    )


def open_sped_service_log(case_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_sped_service_log(
            create_sped_service_log_payload(case_id, **overrides), headers or CM_HEADERS
        )
    )


def open_transition_plan(
    case_id: str, expected_case_version: int = None, headers: dict = None, **overrides
) -> dict:
    if expected_case_version is None:
        expected_case_version = case_version(case_id)
    return get_success_data(
        api_client.create_transition_plan(
            create_transition_plan_payload(
                case_id, expected_case_version, **overrides
            ),
            headers or CM_HEADERS,
        )
    )


def open_extension_request(
    case_id: str,
    certification_id: str,
    expected_case_version: int = None,
    headers: dict = None,
    **overrides,
) -> dict:
    if expected_case_version is None:
        expected_case_version = case_version(case_id)
    return get_success_data(
        api_client.create_extension_request(
            create_extension_request_payload(
                case_id, certification_id, expected_case_version, **overrides
            ),
            headers or CM_HEADERS,
        )
    )


# ===========================================================================
# Listing helpers
# ===========================================================================


def list_data(response) -> list:
    get_success_data(response)
    return response.json()["data"]


def ledger_entries_for_case(case_id: str, headers: dict = None) -> list:
    """Every attendance ledger row of one case, oldest first.

    Only `limit` and `offset` are used, because those are the two query
    parameters the PRD declares for list endpoints; the case is selected
    client-side.
    """
    rows = list_data(
        api_client.list_attendance_entries(headers or PA_HEADERS, params={"limit": 100})
    )
    return [row for row in rows if row["case_id"] == case_id]


def assignments_for_case(case_id: str, headers: dict = None) -> list:
    rows = list_data(
        api_client.list_assignments(headers or CM_HEADERS, params={"limit": 100})
    )
    return [row for row in rows if row["case_id"] == case_id]


def sessions_for_case(case_id: str, headers: dict = None) -> list:
    rows = list_data(
        api_client.list_sessions(headers or CM_HEADERS, params={"limit": 100})
    )
    return [row for row in rows if row["case_id"] == case_id]


def entries_for_session(session_id: str, headers: dict = None) -> list:
    rows = list_data(
        api_client.list_attendance_entries(headers or PA_HEADERS, params={"limit": 100})
    )
    return [row for row in rows if row["session_id"] == session_id]


# ===========================================================================
# Tier 1–2: catalogue + student + teacher scaffolding
# ===========================================================================

DEFAULT_TEACHER = {
    "full_name": "Tara Ng",
    "employee_number": "E-1001",
    "credential_areas": ["MATH", "ELA"],
    "grade_bands": ["MIDDLE", "HIGH"],
    "max_weekly_caseload_minutes": 1200,
}

SECOND_TEACHER = {
    "full_name": "Sam Duro",
    "employee_number": "E-1002",
    "credential_areas": ["SCIENCE"],
    "grade_bands": ["MIDDLE"],
    "max_weekly_caseload_minutes": 1200,
}

CLASSROOM_TEACHER = {
    "full_name": "Lena Ford",
    "employee_number": "E-1004",
    "credential_areas": ["MATH"],
    "grade_bands": ["MIDDLE"],
    "max_weekly_caseload_minutes": 300,
    "home_visit_eligible": False,
}


def setup_catalogue(
    *, clock: str = CLOCK_CONFIG_INSTANT, rules=None
) -> list:
    """Move the clock to a known instant and publish the entitlement catalogue.

    `rules` is a list of override dicts; it defaults to the single
    MIDDLE / IN_HOME rule the rest of the suite leans on.
    """
    set_clock(clock)
    if rules is None:
        rules = [{}]
    return [publish_entitlement_rule(**overrides) for overrides in rules]


# ===========================================================================
# Tier 3: full lifecycle shortcuts
# ===========================================================================


def setup_eligible_case(
    *,
    clock: str = CLOCK_CONFIG_INSTANT,
    rules=None,
    student: dict = None,
    case: dict = None,
    certification: dict = None,
) -> dict:
    """Clock → catalogue → student → case → certification → nurse ACCEPT.

    Returns a bundle: rules, rule (the first one), student, case (re-read after
    acceptance) and certification (the accepted row).
    """
    published = setup_catalogue(clock=clock, rules=rules)
    student_row = register_student(**(student or {}))
    case_row = open_case(student_row["id"], **(case or {}))
    cert = submit_certification(case_row["id"], **(certification or {}))
    accepted = review_certification(cert["id"], "ACCEPT")
    return {
        "rules": published,
        "rule": published[0],
        "student": student_row,
        "case": read_case(case_row["id"]),
        "case_v_draft": case_row["version"],
        "certification": accepted,
    }


def setup_case_with_primary_assignment(
    *,
    clock: str = CLOCK_CONFIG_INSTANT,
    rules=None,
    student: dict = None,
    case: dict = None,
    certification: dict = None,
    teacher: dict = None,
    accept: bool = True,
) -> dict:
    """An ELIGIBLE case with a primary teacher assignment, accepted by default."""
    bundle = setup_eligible_case(
        clock=clock,
        rules=rules,
        student=student,
        case=case,
        certification=certification,
    )
    teacher_row = register_teacher(**{**DEFAULT_TEACHER, **(teacher or {})})
    assignment = propose_assignment(
        bundle["case"]["id"], "PRIMARY", teacher_row["id"]
    )
    if accept:
        assignment = accept_assignment(assignment["id"], teacher_row["id"])
    bundle["teacher"] = read_teacher(teacher_row["id"])
    bundle["primary_assignment"] = assignment
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def setup_active_case(
    *,
    clock: str = CLOCK_CONFIG_INSTANT,
    activation_clock: str = CLOCK_ACTIVATION_INSTANT,
    rules=None,
    student: dict = None,
    case: dict = None,
    certification: dict = None,
    teacher: dict = None,
    safety_review: dict = None,
    include_safety_review: bool = True,
) -> dict:
    """The full path to a case in service.

    Clock → catalogue → student → case → certification accepted → safety review
    finalized → primary assignment accepted → clock advanced → activation.

    Returns a bundle with rule(s), student, teacher, case (post-activation),
    certification, safety_review and primary_assignment.
    """
    bundle = setup_eligible_case(
        clock=clock,
        rules=rules,
        student=student,
        case=case,
        certification=certification,
    )
    case_id = bundle["case"]["id"]

    if include_safety_review:
        review = record_safety_review(case_id, **(safety_review or {}))
        bundle["safety_review"] = finalize_safety_review(review["id"])
    else:
        bundle["safety_review"] = None

    teacher_row = register_teacher(**{**DEFAULT_TEACHER, **(teacher or {})})
    assignment = propose_assignment(case_id, "PRIMARY", teacher_row["id"])
    bundle["primary_assignment"] = accept_assignment(
        assignment["id"], teacher_row["id"]
    )

    set_clock(activation_clock)
    bundle["case"] = activate_case(case_id)
    bundle["teacher"] = read_teacher(teacher_row["id"])
    bundle["case_v_active"] = bundle["case"]["version"]
    return bundle


def add_support_assignment(
    bundle: dict, *, teacher: dict = None, accept: bool = True
) -> dict:
    """Add a SUPPORT assignment to an existing bundle's case.

    Stores the support teacher under `support_teacher` and the assignment under
    `support_assignment`, refreshes `case`, `teacher` and `primary_assignment`.
    """
    teacher_row = register_teacher(**{**SECOND_TEACHER, **(teacher or {})})
    assignment = propose_assignment(bundle["case"]["id"], "SUPPORT", teacher_row["id"])
    if accept:
        assignment = accept_assignment(assignment["id"], teacher_row["id"])
    bundle["support_teacher"] = read_teacher(teacher_row["id"])
    bundle["support_assignment"] = assignment
    bundle["case"] = read_case(bundle["case"]["id"])
    bundle["teacher"] = read_teacher(bundle["teacher"]["id"])
    bundle["primary_assignment"] = read_assignment(bundle["primary_assignment"]["id"])
    return bundle


# ===========================================================================
# Tier 4: accumulation / threshold targeting
# ===========================================================================


def setup_active_case_with_session(
    *,
    session: dict = None,
    **active_kwargs,
) -> dict:
    """An active case carrying one SCHEDULED session (stored as `session`)."""
    bundle = setup_active_case(**active_kwargs)
    bundle["session"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        **(session or {}),
    )
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def setup_delivered_session(
    *,
    session: dict = None,
    actual_minutes: int = 120,
    log_clock: str = "2026-09-07T12:00:00Z",
    **active_kwargs,
) -> dict:
    """An active case with one DELIVERED session and its attendance ledger row."""
    bundle = setup_active_case_with_session(session=session, **active_kwargs)
    set_clock(log_clock)
    bundle["session"] = log_session_delivered(
        bundle["session"]["id"], bundle["teacher"]["id"], actual_minutes
    )
    bundle["case"] = read_case(bundle["case"]["id"])
    bundle["ledger"] = ledger_entries_for_case(bundle["case"]["id"])
    return bundle


def setup_verified_session(
    *,
    verify_clock: str = None,
    verify_headers: dict = None,
    **delivered_kwargs,
) -> dict:
    """An active case with one DELIVERED session that also carries `verified_at`."""
    bundle = setup_delivered_session(**delivered_kwargs)
    if verify_clock:
        set_clock(verify_clock)
    bundle["session"] = verify_session(bundle["session"]["id"], verify_headers)
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def deliver_and_verify(
    bundle: dict,
    *,
    scheduled_start: str,
    scheduled_end: str,
    actual_minutes: int,
    delivery_mode: str = "IN_HOME",
    subject: str = "MATH",
    assignment_id: str = None,
    log_clock: str = None,
    verify: bool = True,
) -> dict:
    """Schedule → log DELIVERED → (optionally) verify one further session.

    Returns the session row. The caller controls the clock ordering through
    `log_clock`; when omitted the clock is left where it is.
    """
    session = schedule_session(
        bundle["case"]["id"],
        assignment_id or bundle["primary_assignment"]["id"],
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        delivery_mode=delivery_mode,
        subject=subject,
    )
    if log_clock:
        set_clock(log_clock)
    session = log_session_delivered(
        session["id"], bundle["teacher"]["id"], actual_minutes
    )
    if verify:
        session = verify_session(session["id"])
    return session


# ===========================================================================
# Tier 5: finalization / terminal state
# ===========================================================================


def setup_case_with_transition_plan(
    *,
    plan: dict = None,
    pacing_syncs: int = 1,
    acknowledge: bool = False,
    coordinate: bool = False,
    classroom_teacher: dict = None,
    **active_kwargs,
) -> dict:
    """An active case moved into `TRANSITION_PLANNED` with coordination rows.

    `pacing_syncs` coordination rows are opened (subjects MATH, ELA, SCIENCE in
    that order) against one classroom teacher of record. When `coordinate` is
    true the plan is sent out for classroom coordination; when `acknowledge` is
    also true every row is acknowledged by its teacher of record.
    """
    bundle = setup_active_case(**active_kwargs)
    ct = register_teacher(**{**CLASSROOM_TEACHER, **(classroom_teacher or {})})
    bundle["classroom_teacher"] = ct

    subjects = ["MATH", "ELA", "SCIENCE"]
    bundle["pacing_syncs"] = [
        open_pacing_sync(
            bundle["case"]["id"],
            ct["id"],
            subject=subjects[index],
            pacing_target_unit=f"Unit {index + 3}",
        )
        for index in range(pacing_syncs)
    ]

    bundle["plan"] = open_transition_plan(bundle["case"]["id"], **(plan or {}))
    if coordinate:
        bundle["plan"] = get_success_data(
            api_client.coordinate_transition_plan(bundle["plan"]["id"], CM_HEADERS)
        )
    if acknowledge:
        for sync in bundle["pacing_syncs"]:
            acknowledge_pacing_sync(sync["id"], ct["id"])
        bundle["plan"] = get_success_data(
            api_client.get_transition_plan(bundle["plan"]["id"], CM_HEADERS)
        )
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def setup_extension_under_review(
    *,
    extension: dict = None,
    **active_kwargs,
) -> dict:
    """An active case with an extension request moved to `UNDER_REVIEW`."""
    bundle = setup_active_case(**active_kwargs)
    request = open_extension_request(
        bundle["case"]["id"], bundle["certification"]["id"], **(extension or {})
    )
    bundle["extension_request"] = get_success_data(
        api_client.start_extension_review(request["id"], PA_HEADERS)
    )
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle
