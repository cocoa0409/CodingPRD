"""Composite setup helpers for the DSMES API.

Every test runs against a freshly restarted, empty database, so these helpers
build all preconditions from scratch using only PRD-declared endpoints. They use
get_success_data() (lenient) internally so setup failures surface as clear
"Setup failed" errors.

The central helper is setup_active_enrollment(), which walks the referral →
assessment → enrollment → activation pipeline and returns a context dict with
every id plus role headers. The Dietitian is entity-backed, so ctx["diet"]
carries make_dietitian_headers(dietitian_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_dietitian_headers
from . import factories as f
from .constants import CLOCK_DEFAULT_UTC


COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------
def set_logical_clock(api, iso=CLOCK_DEFAULT_UTC):
    return get_success_data(api.set_clock({"to_iso8601": iso}, COORD))


def make_program(api, **overrides):
    return get_success_data(api.create_program(f.create_program_payload(**overrides), COORD))


def make_curriculum(api, **overrides):
    return get_success_data(api.create_curriculum(f.create_curriculum_payload(**overrides), COORD))


def make_patient(api, **overrides):
    return get_success_data(api.create_patient(f.create_patient_payload(**overrides), COORD))


def make_dietitian(api, **overrides):
    return get_success_data(api.create_dietitian(f.create_dietitian_payload(**overrides), COORD))


def make_referral(api, program_id, patient_id, **overrides):
    return get_success_data(
        api.create_referral(f.create_referral_payload(program_id, patient_id, **overrides), COORD)
    )


def assess_referral(api, referral_id, dietitian_id, assessed_a1c=8.0):
    return get_success_data(
        api.assess_referral(referral_id, {"assessed_a1c": assessed_a1c}, make_dietitian_headers(dietitian_id))
    )


def make_enrollment(api, referral_id, curriculum_id, **overrides):
    return get_success_data(
        api.create_enrollment(f.create_enrollment_payload(referral_id, curriculum_id, **overrides), COORD)
    )


def activate_enrollment(api, enrollment_id):
    return get_success_data(api.activate_enrollment(enrollment_id, COORD))


def add_active_enrollment(api, ctx, **patient_overrides):
    """Create a second ACTIVE enrollment that shares ctx's program, curriculum,
    and dietitian (a distinct patient). Returns the activated enrollment dict.

    Useful when a scenario needs two patients competing for the same group
    class or benefit pool.
    """
    patient = make_patient(api, **patient_overrides)
    referral = make_referral(api, ctx["program_id"], patient["id"])
    assess_referral(api, referral["id"], ctx["dietitian_id"], assessed_a1c=8.0)
    enrollment = make_enrollment(api, referral["id"], ctx["curriculum_id"])
    activated = activate_enrollment(api, enrollment["id"])
    activated["patient_id"] = patient["id"]
    return activated


def current_enrollment_version(api, enrollment_id):
    return get_success_data(api.get_enrollment(enrollment_id, COORD))["version"]


def current_group_class_version(api, group_class_id):
    return get_success_data(api.get_group_class(group_class_id, COORD))["version"]


def get_enrollment(api, enrollment_id):
    return get_success_data(api.get_enrollment(enrollment_id, COORD))


def get_session(api, session_id):
    return get_success_data(api.get_session(session_id, COORD))


def get_group_class(api, group_class_id):
    return get_success_data(api.get_group_class(group_class_id, COORD))


def get_care_plan(api, care_plan_id):
    return get_success_data(api.get_care_plan(care_plan_id, COORD))


def get_device(api, device_id):
    return get_success_data(api.get_device_enrollment(device_id, COORD))


# ---------------------------------------------------------------------------
# Pipeline composite
# ---------------------------------------------------------------------------
def setup_active_enrollment(
    api,
    *,
    required_hours=10.0,
    curriculum_focus="TYPE_2",
    patient_type="TYPE_2",
    baseline_a1c=8.0,
    payer="MEDICARE",
    module_count=8,
    program_overrides=None,
    credential="RD",
    set_clock=True,
    assess=True,
    create_enrollment=True,
    activate=True,
):
    """Walk program → curriculum → patient → dietitian → referral → (assess) →
    (enrollment) → (activate).

    Returns a context dict:
        coord, billing, diet (headers), dietitian_id,
        program_id, curriculum_id, patient_id, referral_id,
        enrollment_id (when created), enrollment_version (current, when created).

    Flags let callers stop early to reach PENDING enrollment, RECEIVED referral,
    or a LAPSED program (via program_overrides).
    """
    if set_clock:
        set_logical_clock(api)

    program = make_program(api, **(program_overrides or {}))
    curriculum = make_curriculum(
        api, diabetes_type_focus=curriculum_focus, required_hours=required_hours, module_count=module_count
    )
    patient = make_patient(api, diabetes_type=patient_type, baseline_a1c=baseline_a1c, payer=payer)
    dietitian = make_dietitian(api, credential=credential)
    referral = make_referral(api, program["id"], patient["id"])

    ctx = {
        "coord": COORD,
        "billing": BILLING,
        "diet": make_dietitian_headers(dietitian["id"]),
        "dietitian_id": dietitian["id"],
        "program_id": program["id"],
        "curriculum_id": curriculum["id"],
        "patient_id": patient["id"],
        "referral_id": referral["id"],
        "program": program,
        "curriculum": curriculum,
        "patient": patient,
    }

    if assess:
        assess_referral(api, referral["id"], dietitian["id"], assessed_a1c=baseline_a1c)

    if create_enrollment and assess:
        enrollment = make_enrollment(api, referral["id"], curriculum["id"])
        ctx["enrollment_id"] = enrollment["id"]
        if activate:
            activated = activate_enrollment(api, enrollment["id"])
            ctx["enrollment_version"] = activated["version"]
        else:
            ctx["enrollment_version"] = enrollment["version"]

    return ctx


# ---------------------------------------------------------------------------
# Session action helpers
# ---------------------------------------------------------------------------
def schedule_individual_session(api, ctx, scheduled_start, scheduled_end,
                                *, expected_version=None, is_telehealth=None,
                                dietitian_id=None):
    """Schedule an individual session against ctx's active enrollment.

    Returns the raw Response so tests can assert either success or error. When
    expected_version is None it is auto-fetched from the enrollment's current
    version (the happy path). Pass a stale value explicitly for OCC tests.
    """
    if expected_version is None:
        expected_version = current_enrollment_version(api, ctx["enrollment_id"])
    payload = f.create_session_payload(
        ctx["enrollment_id"],
        dietitian_id or ctx["dietitian_id"],
        scheduled_start,
        scheduled_end,
        expected_version,
    )
    if is_telehealth is not None:
        payload["is_telehealth"] = is_telehealth
    return api.create_session(payload, ctx["diet"])


def schedule_individual_session_ok(api, ctx, scheduled_start, scheduled_end,
                                   *, expected_version=None, is_telehealth=None):
    return get_success_data(
        schedule_individual_session(
            api, ctx, scheduled_start, scheduled_end,
            expected_version=expected_version, is_telehealth=is_telehealth,
        )
    )


def check_in(api, ctx, session_id):
    return get_success_data(api.check_in_session(session_id, ctx["diet"]))


def complete(api, ctx, session_id, actual_minutes):
    """Check in then complete a session. Returns the completed session data."""
    check_in(api, ctx, session_id)
    return get_success_data(api.complete_session(session_id, {"actual_minutes": actual_minutes}, ctx["diet"]))


def no_show(api, ctx, session_id):
    return get_success_data(api.no_show_session(session_id, ctx["diet"]))


def cancel(api, ctx, session_id, cancel_reason=None):
    payload = {"cancel_reason": cancel_reason} if cancel_reason is not None else {}
    return get_success_data(api.cancel_session(session_id, payload, ctx["diet"]))


def schedule_n_sessions(api, ctx, n, base_day="2026-05-13", duration_minutes=30):
    """Schedule n non-overlapping individual sessions (each duration_minutes,
    one per hour starting 09:00). Returns the list of session dicts."""
    sessions = []
    for i in range(n):
        hour = 9 + i
        start = f"{base_day}T{hour:02d}:00:00Z"
        end_minute = 0 + duration_minutes
        end_hour = hour + end_minute // 60
        end_minute = end_minute % 60
        end = f"{base_day}T{end_hour:02d}:{end_minute:02d}:00Z"
        sessions.append(schedule_individual_session_ok(api, ctx, start, end))
    return sessions


def suspend_via_no_shows(api, ctx, total_sessions=3, strikes=3, base_day="2026-05-13"):
    """Schedule total_sessions 30-min sessions, then no-show the first `strikes`
    of them. The 3rd no-show suspends the enrollment; any still-SCHEDULED
    session beyond `strikes` is cascade-cancelled. Returns the session list."""
    sessions = schedule_n_sessions(api, ctx, total_sessions, base_day=base_day)
    for i in range(strikes):
        no_show(api, ctx, sessions[i]["id"])
    return sessions


# ---------------------------------------------------------------------------
# Group class / seat helpers
# ---------------------------------------------------------------------------
def make_group_class(api, ctx, *, room_id="ROOM-1", scheduled_start="2026-05-20T13:00:00Z",
                     scheduled_end="2026-05-20T14:00:00Z", capacity=5, topic="Nutrition Basics",
                     dietitian_id=None):
    payload = f.create_group_class_payload(
        ctx["curriculum_id"], dietitian_id or ctx["dietitian_id"],
        scheduled_start, scheduled_end, room_id=room_id, capacity=capacity, topic=topic,
    )
    return api.create_group_class(payload, COORD)


def make_group_class_ok(api, ctx, **kwargs):
    return get_success_data(make_group_class(api, ctx, **kwargs))


def reserve_seat(api, ctx, group_class_id, enrollment_id, *, expected_group_class_version=None):
    if expected_group_class_version is None:
        expected_group_class_version = current_group_class_version(api, group_class_id)
    payload = f.reserve_seat_payload(enrollment_id, expected_group_class_version)
    return api.reserve_group_seat(group_class_id, payload, ctx["diet"])


def reserve_seat_ok(api, ctx, group_class_id, enrollment_id, *, expected_group_class_version=None):
    return get_success_data(
        reserve_seat(api, ctx, group_class_id, enrollment_id,
                     expected_group_class_version=expected_group_class_version)
    )


# ---------------------------------------------------------------------------
# Device helpers
# ---------------------------------------------------------------------------
def make_device(api, ctx, *, device_type="CGM"):
    return get_success_data(
        api.create_device_enrollment(
            f.create_device_enrollment_payload(ctx["enrollment_id"], device_type=device_type), COORD
        )
    )


def activate_device(api, ctx, device_id):
    return get_success_data(api.activate_device(device_id, ctx["diet"]))


def make_active_device(api, ctx, *, device_type="CGM"):
    device = make_device(api, ctx, device_type=device_type)
    return activate_device(api, ctx, device["id"])


def ingest_reading(api, ctx, device_id, glucose_mgdl, measured_at):
    return api.ingest_reading(device_id, f.create_reading_payload(glucose_mgdl, measured_at), ctx["diet"])


# ---------------------------------------------------------------------------
# Care plan helpers
# ---------------------------------------------------------------------------
def make_care_plan(api, ctx, *, goal_description="Lower A1c below target", target_a1c=7.0):
    return get_success_data(
        api.create_care_plan(
            f.create_care_plan_payload(ctx["enrollment_id"], goal_description=goal_description, target_a1c=target_a1c),
            ctx["diet"],
        )
    )
