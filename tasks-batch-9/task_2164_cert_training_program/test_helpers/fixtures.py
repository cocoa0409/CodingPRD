"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database.  Helpers use the lenient
success reader so that a broken precondition surfaces as a setup failure rather
than as a confusing assertion inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_activation_payload,
    create_class_session_payload,
    create_cohort_payload,
    create_curriculum_module_payload,
    create_equipment_asset_payload,
    create_exercise_participation_payload,
    create_exercise_payload,
    create_facility_payload,
    create_instructor_payload,
    create_module_completion_payload,
    create_program_payload,
    create_trainee_payload,
)
from .test_users import (
    COORD_ISSUER,
    COORD_REVIEWER,
    TEST_USERS,
    make_coordinator_headers,
    make_evaluator_headers,
    make_instructor_headers,
    make_trainee_headers,
)

COORD = TEST_USERS["coordinator_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
EMERGENCY = TEST_USERS["emergency_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
REVIEWER = TEST_USERS["reviewer_coordinator_headers"]
ISSUER = TEST_USERS["issuer_coordinator_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(iso8601: str) -> str:
    data = get_success_data(api_client.set_clock({"to_iso8601": iso8601}, COORD))
    return data["current_utc"]


# ---------------------------------------------------------------------------
# Tier 1 - primitive creators
# ---------------------------------------------------------------------------

def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), COORD)
    )


def create_module(**overrides) -> dict:
    return get_success_data(
        api_client.create_curriculum_module(
            create_curriculum_module_payload(**overrides), COORD
        )
    )


def create_facility(**overrides) -> dict:
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), COORD)
    )


def create_instructor(**overrides) -> dict:
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(**overrides), COORD)
    )


def create_cohort(program_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_cohort(create_cohort_payload(program_id, **overrides), COORD)
    )


def create_trainee(program_id, cohort_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_trainee(
            create_trainee_payload(program_id, cohort_id, **overrides), COORD
        )
    )


def create_session(cohort_id, module_id, facility_id, instructor_id, starts_at) -> dict:
    return get_success_data(
        api_client.create_class_session(
            create_class_session_payload(
                cohort_id, module_id, facility_id, instructor_id, starts_at
            ),
            COORD,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 - the shared program setup used by nearly every scenario
# ---------------------------------------------------------------------------

def setup_program_and_curriculum(
    budget_cents=None,
    seat_capacity=None,
    facility_capacity=None,
    instructor_max_hours=None,
    window_start=None,
    window_end=None,
    cohort_code="C-2026A",
    instructor_cert_expiry=None,
) -> dict:
    """Program, a three-module core curriculum, one room, two instructors, one cohort.

    CERT-101 is 2.5 contact hours and needs no demonstration.
    CERT-102 is 2.5 contact hours, needs a demonstration and requires CERT-101.
    CERT-103 is 5.0 contact hours, needs a demonstration, is refresher eligible
    and requires CERT-102.  The three together are worth 10.0 core hours.
    """
    ctx = {}
    ctx["program"] = create_program(
        equipment_budget_cents=(
            TEST_DEFAULTS["PROGRAM_BUDGET_CENTS"] if budget_cents is None else budget_cents
        )
    )
    ctx["m101"] = create_module(
        module_code="CERT-101", title="Disaster Preparedness", contact_hours=2.5,
        sequence_index=1, is_core=True, requires_skills_demo=False,
        refresher_eligible=False,
    )
    ctx["m102"] = create_module(
        module_code="CERT-102", title="Fire Safety", contact_hours=2.5,
        sequence_index=2, is_core=True, requires_skills_demo=True,
        refresher_eligible=False, prerequisite_module_id=ctx["m101"]["id"],
    )
    ctx["m103"] = create_module(
        module_code="CERT-103", title="Disaster Medical", contact_hours=5.0,
        sequence_index=3, is_core=True, requires_skills_demo=True,
        refresher_eligible=True, prerequisite_module_id=ctx["m102"]["id"],
    )
    ctx["facility"] = create_facility(
        name="Riverside EOC", room_code="EOC-A",
        capacity_seats=(
            TEST_DEFAULTS["FACILITY_CAPACITY"] if facility_capacity is None
            else facility_capacity
        ),
    )
    cert_expiry = instructor_cert_expiry or TEST_DEFAULTS["INSTRUCTOR_CERT_EXPIRY"]
    max_hours = (
        TEST_DEFAULTS["INSTRUCTOR_MAX_DAILY_HOURS"] if instructor_max_hours is None
        else instructor_max_hours
    )
    ctx["instructor1"] = create_instructor(
        full_name="Ines Ruiz", certification_expires_on=cert_expiry,
        max_daily_contact_hours=max_hours,
    )
    ctx["instructor2"] = create_instructor(
        full_name="Evan Ko", certification_expires_on=cert_expiry,
        max_daily_contact_hours=max_hours,
    )
    ctx["cohort"] = create_cohort(
        ctx["program"]["id"],
        cohort_code=cohort_code,
        seat_capacity=(
            TEST_DEFAULTS["SEAT_CAPACITY"] if seat_capacity is None else seat_capacity
        ),
        session_window_start=window_start or TEST_DEFAULTS["COHORT_WINDOW_START"],
        session_window_end=window_end or TEST_DEFAULTS["COHORT_WINDOW_END"],
    )
    ctx["trainees"] = {}
    ctx["completions"] = {}
    ctx["assets"] = {}
    return ctx


def schedule_core_sessions(ctx, instructor_key="instructor1", facility_key="facility"):
    """One session per core module, on three consecutive days inside the window."""
    instructor_id = ctx[instructor_key]["id"]
    facility_id = ctx[facility_key]["id"]
    cohort_id = ctx["cohort"]["id"]
    ctx["session_a"] = create_session(
        cohort_id, ctx["m101"]["id"], facility_id, instructor_id, "2026-08-03T09:00:00Z"
    )
    ctx["session_b"] = create_session(
        cohort_id, ctx["m102"]["id"], facility_id, instructor_id, "2026-08-04T09:00:00Z"
    )
    ctx["session_c"] = create_session(
        cohort_id, ctx["m103"]["id"], facility_id, instructor_id, "2026-08-05T09:00:00Z"
    )
    return ctx


def add_trainee(ctx, key="tara", full_name="Tara Nolan", email=None,
                deployment_hold=False, enroll=True):
    email = email or f"{key}@riverside.example"
    trainee = create_trainee(
        ctx["program"]["id"], ctx["cohort"]["id"], full_name=full_name,
        email=email, deployment_hold=deployment_hold,
    )
    if enroll:
        trainee = get_success_data(
            api_client.trainee_enrollment(trainee["id"], {"action": "ENROLL"}, COORD)
        )
    ctx["trainees"][key] = trainee
    return trainee


def advance_cohort(ctx, to_status, headers=None):
    ctx["cohort"] = get_success_data(
        api_client.advance_cohort(
            ctx["cohort"]["id"], {"to_status": to_status}, headers or COORD
        )
    )
    return ctx["cohort"]


def open_cohort_for_teaching(ctx):
    """RECRUITING -> SCHEDULED -> IN_SESSION with the clock at its startup default."""
    advance_cohort(ctx, "SCHEDULED")
    advance_cohort(ctx, "IN_SESSION")
    return ctx["cohort"]


def deliver_session(ctx, session_key, at=None, instructor_key="instructor1"):
    if at:
        set_clock(at)
    session = ctx[session_key]
    ctx[session_key] = get_success_data(
        api_client.deliver_class_session(
            session["id"], make_instructor_headers(ctx[instructor_key]["id"])
        )
    )
    return ctx[session_key]


def record_completion(ctx, trainee_key, session_key, attendance_minutes,
                      instructor_key="instructor1", store_as=None):
    completion = get_success_data(
        api_client.create_module_completion(
            create_module_completion_payload(
                ctx["trainees"][trainee_key]["id"], ctx[session_key]["id"],
                attendance_minutes,
            ),
            make_instructor_headers(ctx[instructor_key]["id"]),
        )
    )
    ctx["completions"][store_as or f"{trainee_key}_{session_key}"] = completion
    return completion


def sign_demo(ctx, completion, outcome, demo_score, evaluator_key="instructor2"):
    return get_success_data(
        api_client.sign_skills_demo(
            completion["id"], {"outcome": outcome, "demo_score": demo_score},
            make_evaluator_headers(ctx[evaluator_key]["id"]),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3 - lifecycle shortcuts
# ---------------------------------------------------------------------------

DEFAULT_TRAINEES = (("tara", "Tara Nolan"),)
DEFAULT_DEMO_SCORES = {"tara": (88, 92), "dev": (85, 90)}


def setup_passed_core_trainees(trainees=DEFAULT_TRAINEES, demo_scores=None,
                               sign_c=True, record_c=True,
                               final_at="2026-08-05T15:00:00Z",
                               applicants=(), extra_enrolled=(), **program_opts):
    """Every named trainee holds a PASSED completion on all three core modules.

    The third completion is left awaiting its demonstration when sign_c is False.
    Anyone named in `applicants` is recorded against the cohort but left at APPLIED,
    and anyone named in `extra_enrolled` is enrolled but earns no completions.
    """
    demo_scores = demo_scores or DEFAULT_DEMO_SCORES
    ctx = setup_program_and_curriculum(**program_opts)
    schedule_core_sessions(ctx)
    for key, name in trainees:
        add_trainee(ctx, key=key, full_name=name)
    for key, name in extra_enrolled:
        add_trainee(ctx, key=key, full_name=name)
    for key, name in applicants:
        add_trainee(ctx, key=key, full_name=name, enroll=False)
    open_cohort_for_teaching(ctx)

    deliver_session(ctx, "session_a", at="2026-08-03T12:00:00Z")
    for key, _ in trainees:
        record_completion(ctx, key, "session_a", 150, store_as=f"{key}_a")

    deliver_session(ctx, "session_b", at="2026-08-04T12:00:00Z")
    for key, _ in trainees:
        completion = record_completion(ctx, key, "session_b", 150, store_as=f"{key}_b")
        ctx["completions"][f"{key}_b"] = sign_demo(
            ctx, completion, "PASS", demo_scores[key][0]
        )

    deliver_session(ctx, "session_c", at=final_at)
    if record_c:
        for key, _ in trainees:
            completion = record_completion(ctx, key, "session_c", 300,
                                           store_as=f"{key}_c")
            if sign_c:
                ctx["completions"][f"{key}_c"] = sign_demo(
                    ctx, completion, "PASS", demo_scores[key][1]
                )
    return ctx


def setup_graduated_trainees(trainees=DEFAULT_TRAINEES, reviewer_user_id=COORD_REVIEWER,
                             **kwargs):
    """Cohort moved into graduation review by `reviewer_user_id`, then each trainee graduated."""
    ctx = setup_passed_core_trainees(trainees=trainees, **kwargs)
    reviewer_headers = make_coordinator_headers(reviewer_user_id)
    advance_cohort(ctx, "GRADUATION_REVIEW", headers=reviewer_headers)
    ctx["reviewer_user_id"] = reviewer_user_id
    for key, _ in trainees:
        ctx["trainees"][key] = get_success_data(
            api_client.trainee_enrollment(
                ctx["trainees"][key]["id"], {"action": "GRADUATE"}, reviewer_headers
            )
        )
    return ctx


def mint_credential(ctx, trainee_key, issuer_user_id=COORD_ISSUER, at=None):
    if at:
        set_clock(at)
    credential = get_success_data(
        api_client.create_credential(
            {"trainee_id": ctx["trainees"][trainee_key]["id"]},
            make_coordinator_headers(issuer_user_id),
        )
    )
    ctx.setdefault("credentials", {})[trainee_key] = credential
    return credential


def setup_credentialed_trainees(trainees=DEFAULT_TRAINEES,
                                mint_at="2026-08-05T16:00:00Z",
                                issuer_user_id=COORD_ISSUER, **kwargs):
    """Graduated trainees each holding a freshly minted ACTIVE credential.

    `mint_at` moves the logical clock before the first mint, so the credential's
    term window opens strictly after every module pass recorded during setup.
    """
    ctx = setup_graduated_trainees(trainees=trainees, **kwargs)
    if mint_at:
        set_clock(mint_at)
    for key, _ in trainees:
        mint_credential(ctx, key, issuer_user_id=issuer_user_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 - equipment
# ---------------------------------------------------------------------------

def add_asset(ctx, key, asset_tag, kit_type="BACKPACK_STANDARD", unit_value_cents=17700):
    asset = get_success_data(
        api_client.create_equipment_asset(
            create_equipment_asset_payload(
                ctx["program"]["id"], asset_tag=asset_tag, kit_type=kit_type,
                unit_value_cents=unit_value_cents,
            ),
            LOGISTICS,
        )
    )
    ctx["assets"][key] = asset
    return asset


def current_program_version(ctx) -> int:
    program = get_success_data(api_client.get_program(ctx["program"]["id"], LOGISTICS))
    ctx["program"] = program
    return program["version"]


def issue_kit(ctx, trainee_key, kit_type="BACKPACK_STANDARD", store_as=None):
    """Read the program version, then issue - the concurrency token must be fresh."""
    version = current_program_version(ctx)
    issuance = get_success_data(
        api_client.create_equipment_issuance(
            {
                "trainee_id": ctx["trainees"][trainee_key]["id"],
                "kit_type": kit_type,
                "expected_program_version": version,
            },
            LOGISTICS,
        )
    )
    ctx.setdefault("issuances", {})[store_as or f"{trainee_key}_{kit_type}"] = issuance
    return issuance


# ---------------------------------------------------------------------------
# Tier 4 - exercises
# ---------------------------------------------------------------------------

def create_exercise(ctx, key, title="Drill 1", exercise_type="FUNCTIONAL",
                    starts_at="2026-09-01T08:00:00Z", ends_at="2026-09-01T12:00:00Z",
                    base_credit_hours=4.0):
    exercise = get_success_data(
        api_client.create_exercise(
            create_exercise_payload(
                ctx["program"]["id"], title=title, exercise_type=exercise_type,
                starts_at=starts_at, ends_at=ends_at, base_credit_hours=base_credit_hours,
            ),
            EMERGENCY,
        )
    )
    ctx.setdefault("exercises", {})[key] = exercise
    return exercise


def register_participation(ctx, exercise_key, trainee_key, role_played="LOGISTICS",
                           store_as=None):
    participation = get_success_data(
        api_client.create_exercise_participation(
            create_exercise_participation_payload(
                ctx["exercises"][exercise_key]["id"],
                ctx["trainees"][trainee_key]["id"],
                role_played,
            ),
            EMERGENCY,
        )
    )
    ctx.setdefault("participations", {})[
        store_as or f"{exercise_key}_{trainee_key}"
    ] = participation
    return participation


def advance_exercise(ctx, exercise_key, to_status, headers=None, aar_summary=None):
    payload = {"to_status": to_status}
    if aar_summary is not None:
        payload["aar_summary"] = aar_summary
    ctx["exercises"][exercise_key] = get_success_data(
        api_client.advance_exercise(
            ctx["exercises"][exercise_key]["id"], payload, headers or EMERGENCY
        )
    )
    return ctx["exercises"][exercise_key]


def run_exercise_to_credit(ctx, exercise_key, accept_at):
    """PLANNED -> RUNNING -> COMPLETED -> AAR_SUBMITTED -> AAR_ACCEPTED.

    Acceptance is the coordinator's act; every earlier advance is the manager's.
    """
    exercise = ctx["exercises"][exercise_key]
    set_clock(exercise["starts_at"])
    advance_exercise(ctx, exercise_key, "RUNNING")
    set_clock(exercise["ends_at"])
    advance_exercise(ctx, exercise_key, "COMPLETED")
    advance_exercise(ctx, exercise_key, "AAR_SUBMITTED",
                     aar_summary=TEST_DEFAULTS["AAR_SUMMARY"])
    set_clock(accept_at)
    advance_exercise(ctx, exercise_key, "AAR_ACCEPTED", headers=COORD)
    return ctx["exercises"][exercise_key]


def credit_refresher_hours(ctx, trainee_key, base_credit_hours, role_played="LOGISTICS",
                           key="drill", title="Drill 1",
                           starts_at="2026-09-01T08:00:00Z",
                           ends_at="2026-09-01T12:00:00Z",
                           accept_at="2026-09-01T14:00:00Z"):
    """Run one exercise end to end so the trainee banks refresher hours in the term."""
    create_exercise(ctx, key, title=title, starts_at=starts_at, ends_at=ends_at,
                    base_credit_hours=base_credit_hours)
    register_participation(ctx, key, trainee_key, role_played=role_played,
                           store_as=f"{key}_{trainee_key}")
    run_exercise_to_credit(ctx, key, accept_at)
    return ctx["exercises"][key]


# ---------------------------------------------------------------------------
# Tier 5 - activations and the call-out roster
# ---------------------------------------------------------------------------

def create_activation(ctx, key="act1", incident_number="INC-2026-001",
                      severity="ROUTINE", requested_responders=1,
                      requesting_agency="County OES"):
    activation = get_success_data(
        api_client.create_activation(
            create_activation_payload(
                ctx["program"]["id"], incident_number=incident_number,
                severity=severity, requested_responders=requested_responders,
                requesting_agency=requesting_agency,
            ),
            EMERGENCY,
        )
    )
    ctx.setdefault("activations", {})[key] = activation
    return activation


def build_roster(ctx, key="act1", at=None):
    if at:
        set_clock(at)
    ctx["activations"][key] = get_success_data(
        api_client.build_roster(ctx["activations"][key]["id"], EMERGENCY)
    )
    return ctx["activations"][key]


def roster_assignments_for(ctx, key="act1"):
    body = api_client.list_roster_assignments(
        AUDITOR, {"activation_id": ctx["activations"][key]["id"], "limit": 100}
    ).json()
    return body["data"]


def setup_rostered_activation(trainees=DEFAULT_TRAINEES, severity="ROUTINE",
                              requested_responders=1,
                              mint_at="2026-08-05T15:00:00Z",
                              roster_at="2026-08-05T15:00:00Z", **kwargs):
    """Credentialed trainees plus one activation whose roster has been built."""
    ctx = setup_credentialed_trainees(trainees=trainees, mint_at=mint_at, **kwargs)
    create_activation(ctx, severity=severity, requested_responders=requested_responders)
    build_roster(ctx, at=roster_at)
    ctx["assignments"] = {}
    for row in roster_assignments_for(ctx):
        for key, _ in trainees:
            if row["trainee_id"] == ctx["trainees"][key]["id"]:
                ctx["assignments"][key] = row
    return ctx


def respond_to_call_out(ctx, trainee_key, response="ACCEPT"):
    assignment = ctx["assignments"][trainee_key]
    updated = get_success_data(
        api_client.respond_roster_assignment(
            assignment["id"], {"response": response},
            make_trainee_headers(ctx["trainees"][trainee_key]["id"]),
        )
    )
    ctx["assignments"][trainee_key] = updated
    return updated


def advance_activation(ctx, to_status, key="act1"):
    ctx["activations"][key] = get_success_data(
        api_client.advance_activation(
            ctx["activations"][key]["id"], {"to_status": to_status}, EMERGENCY
        )
    )
    return ctx["activations"][key]


# ---------------------------------------------------------------------------
# Reader helpers
# ---------------------------------------------------------------------------

def read_program(ctx):
    return get_success_data(api_client.get_program(ctx["program"]["id"], AUDITOR))


def read_cohort(ctx):
    return get_success_data(api_client.get_cohort(ctx["cohort"]["id"], AUDITOR))


def read_trainee(ctx, trainee_key):
    return get_success_data(
        api_client.get_trainee(ctx["trainees"][trainee_key]["id"], AUDITOR)
    )


def read_completion(ctx, completion_key):
    return get_success_data(
        api_client.get_module_completion(
            ctx["completions"][completion_key]["id"], AUDITOR
        )
    )


def read_credential(ctx, trainee_key):
    return get_success_data(
        api_client.get_credential(ctx["credentials"][trainee_key]["id"], AUDITOR)
    )


def read_session(ctx, session_key):
    return get_success_data(
        api_client.get_class_session(ctx[session_key]["id"], AUDITOR)
    )


def read_asset(ctx, asset_key):
    return get_success_data(
        api_client.get_equipment_asset(ctx["assets"][asset_key]["id"], AUDITOR)
    )


def read_issuance(ctx, issuance):
    issuance_id = issuance["id"] if isinstance(issuance, dict) else issuance
    return get_success_data(api_client.get_equipment_issuance(issuance_id, AUDITOR))


def read_activation(ctx, key="act1"):
    return get_success_data(
        api_client.get_activation(ctx["activations"][key]["id"], AUDITOR)
    )


def read_assignment(ctx, assignment):
    assignment_id = assignment["id"] if isinstance(assignment, dict) else assignment
    return get_success_data(api_client.get_roster_assignment(assignment_id, AUDITOR))


def read_participation(ctx, participation):
    participation_id = (
        participation["id"] if isinstance(participation, dict) else participation
    )
    return get_success_data(
        api_client.get_exercise_participation(participation_id, AUDITOR)
    )


def read_exercise(ctx, exercise_key):
    return get_success_data(
        api_client.get_exercise(ctx["exercises"][exercise_key]["id"], AUDITOR)
    )


def read_module(ctx, module_key):
    return get_success_data(
        api_client.get_curriculum_module(ctx[module_key]["id"], AUDITOR)
    )


# ---------------------------------------------------------------------------
# Attendance-focused shortcuts
# ---------------------------------------------------------------------------

def setup_session_a_delivered(trainee_key="tara", deliver=True,
                              at="2026-08-03T12:00:00Z", **program_opts):
    """Cohort teaching, one enrolled trainee, and the CERT-101 session delivered."""
    ctx = setup_program_and_curriculum(**program_opts)
    schedule_core_sessions(ctx)
    add_trainee(ctx, key=trainee_key, full_name="Tara Nolan")
    open_cohort_for_teaching(ctx)
    set_clock(at)
    if deliver:
        deliver_session(ctx, "session_a")
    return ctx


def setup_pending_skills_demo(trainee_key="tara", **program_opts):
    """CERT-101 passed on attendance alone; CERT-102 recorded and awaiting a signature."""
    ctx = setup_session_a_delivered(trainee_key=trainee_key, **program_opts)
    record_completion(ctx, trainee_key, "session_a", 150, store_as=f"{trainee_key}_a")
    deliver_session(ctx, "session_b", at="2026-08-04T12:00:00Z")
    record_completion(ctx, trainee_key, "session_b", 150, store_as=f"{trainee_key}_b")
    return ctx
