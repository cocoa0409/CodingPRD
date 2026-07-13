"""Composite setup helpers for the Head Start & Pre-K Enrollment API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty database before each
test). Setup calls use get_success_data() (lenient) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: Family is entity-backed, so every guardian-owned call
(accept/decline offer) uses make_family_headers(family_id) with the real id.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_family_headers
from .factories import (
    create_program_payload,
    create_cohort_payload,
    create_family_payload,
    create_application_payload,
    create_attendance_payload,
    create_health_screening_payload,
    create_home_visit_payload,
    create_transition_plan_payload,
    create_pir_report_payload,
)

PA = TEST_USERS["program_admin_headers"]
ES = TEST_USERS["enrollment_specialist_headers"]
FSW = TEST_USERS["family_services_worker_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PA))


# ---------------------------------------------------------------------------
# Atomic building blocks
# ---------------------------------------------------------------------------
def create_program(**overrides) -> dict:
    return get_success_data(api_client.create_program(create_program_payload(**overrides), PA))


def create_cohort(program_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_cohort(create_cohort_payload(program_id, **overrides), PA)
    )


def create_family(**overrides) -> dict:
    return get_success_data(api_client.create_family(create_family_payload(**overrides), ES))


def create_application(program_id, cohort_id, family_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_application(
            create_application_payload(program_id, cohort_id, family_id, **overrides), ES
        )
    )


def submit_application(application_id) -> dict:
    return get_success_data(api_client.submit_application(application_id, ES))


def verify_application(application_id, verified_income_cents) -> dict:
    return get_success_data(
        api_client.verify_eligibility(
            application_id, {"verified_income_cents": verified_income_cents}, ES
        )
    )


def waitlist_application(application_id) -> dict:
    return get_success_data(api_client.waitlist_application(application_id, ES))


def run_selection(cohort_id) -> list:
    return get_success_data(api_client.run_selection(cohort_id, PA))


def cohort_version(cohort_id) -> int:
    return get_success_data(api_client.get_cohort(cohort_id, PA))["version"]


def offer_id_for_application(application_id) -> str:
    data = get_success_data(
        api_client.list_offers(ES, params={"application_id": application_id})
    )
    return data[0]["id"]


def accept_offer(offer_id, family_id, version=None) -> dict:
    if version is None:
        # Read the current cohort version through the offer.
        offer = get_success_data(api_client.get_offer(offer_id, ES))
        version = cohort_version(offer["cohort_id"])
    return get_success_data(
        api_client.accept_offer(
            offer_id, {"expected_cohort_version": version}, make_family_headers(family_id)
        )
    )


def enrollment_for_application(application_id) -> dict:
    data = get_success_data(
        api_client.list_enrollments(ES, params={"application_id": application_id})
    )
    return data[0]


# ---------------------------------------------------------------------------
# Attendance helper
# ---------------------------------------------------------------------------
def _date_seq(count, start="2026-03-02"):
    d = datetime.strptime(start, "%Y-%m-%d")
    out = []
    for _ in range(count):
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def record_attendance(enrollment_id, present=0, absent_unexcused=0, absent_excused=0,
                      start="2026-03-02", instructional_day=True):
    """Record `present` PRESENT, then `absent_unexcused` ABSENT_UNEXCUSED, then
    `absent_excused` ABSENT_EXCUSED attendance records on consecutive distinct
    dates, all with the given instructional_day flag."""
    total = present + absent_unexcused + absent_excused
    dates = _date_seq(total, start)
    i = 0
    for _ in range(present):
        get_success_data(api_client.create_attendance_record(
            create_attendance_payload(enrollment_id, dates[i], "PRESENT",
                                      instructional_day=instructional_day), FSW))
        i += 1
    for _ in range(absent_unexcused):
        get_success_data(api_client.create_attendance_record(
            create_attendance_payload(enrollment_id, dates[i], "ABSENT_UNEXCUSED",
                                      instructional_day=instructional_day), FSW))
        i += 1
    for _ in range(absent_excused):
        get_success_data(api_client.create_attendance_record(
            create_attendance_payload(enrollment_id, dates[i], "ABSENT_EXCUSED",
                                      instructional_day=instructional_day), FSW))
        i += 1


# ---------------------------------------------------------------------------
# Health / home-visit / transition helpers
# ---------------------------------------------------------------------------
def add_immunization_screening(enrollment_id, due_date="2026-03-15") -> dict:
    return get_success_data(api_client.create_health_screening(
        create_health_screening_payload(enrollment_id, "IMMUNIZATION", due_date), FSW))


def update_screening(screening_id, status, completed_date=None) -> dict:
    payload = {"status": status}
    if completed_date is not None:
        payload["completed_date"] = completed_date
    return get_success_data(api_client.update_health_screening(screening_id, payload, FSW))


def add_home_visit(enrollment_id, scheduled_date, window_start, window_end) -> dict:
    return get_success_data(api_client.create_home_visit(
        create_home_visit_payload(enrollment_id, scheduled_date, window_start, window_end), FSW))


def add_completed_home_visit(enrollment_id, scheduled_date,
                             window_start="13:00", window_end="14:00") -> dict:
    hv = add_home_visit(enrollment_id, scheduled_date, window_start, window_end)
    return get_success_data(api_client.complete_home_visit(hv["id"], FSW))


def add_transition_plan(enrollment_id, **overrides) -> dict:
    return get_success_data(api_client.create_transition_plan(
        create_transition_plan_payload(enrollment_id, **overrides), FSW))


# ---------------------------------------------------------------------------
# Composite setups
# ---------------------------------------------------------------------------
def setup_program_and_cohort(program_overrides=None, cohort_overrides=None):
    """Active program + one cohort. Returns (program, cohort)."""
    program = create_program(**(program_overrides or {}))
    cohort = create_cohort(program["id"], **(cohort_overrides or {}))
    return program, cohort


def add_waitlisted_applicant(program, cohort, family_overrides=None, app_overrides=None,
                             verified_income_cents=800_000):
    """Create family + application, submit, verify, waitlist. Returns (family, application)."""
    family = create_family(**(family_overrides or {}))
    app = create_application(program["id"], cohort["id"], family["id"], **(app_overrides or {}))
    submit_application(app["id"])
    verify_application(app["id"], verified_income_cents)
    app = waitlist_application(app["id"])
    return family, app


def setup_waitlisted_application(program_overrides=None, cohort_overrides=None,
                                 family_overrides=None, app_overrides=None,
                                 verified_income_cents=800_000):
    """Single ELIGIBLE->WAITLISTED application. Returns bundle dict."""
    program, cohort = setup_program_and_cohort(program_overrides, cohort_overrides)
    family, app = add_waitlisted_applicant(
        program, cohort, family_overrides, app_overrides, verified_income_cents)
    return {"program": program, "cohort": cohort, "family": family, "application": app}


def setup_offered_application(program_overrides=None, cohort_overrides=None,
                             family_overrides=None, app_overrides=None,
                             verified_income_cents=800_000):
    """Single application driven to OFFERED with a PENDING offer. Returns bundle
    dict {program, cohort, family, application, offer}."""
    b = setup_waitlisted_application(program_overrides, cohort_overrides,
                                     family_overrides, app_overrides, verified_income_cents)
    run_selection(b["cohort"]["id"])
    offer_id = offer_id_for_application(b["application"]["id"])
    b["offer"] = get_success_data(api_client.get_offer(offer_id, ES))
    return b


def setup_active_enrollment(program_overrides=None, cohort_overrides=None,
                            family_overrides=None, app_overrides=None,
                            verified_income_cents=800_000):
    """Full chain through an ACTIVE enrollment. Returns bundle dict
    {program, cohort, family, application, offer, enrollment}."""
    b = setup_offered_application(program_overrides, cohort_overrides,
                                  family_overrides, app_overrides, verified_income_cents)
    accept_offer(b["offer"]["id"], b["family"]["id"])
    b["enrollment"] = enrollment_for_application(b["application"]["id"])
    return b


def setup_two_offered_applications(cohort_funded_slots=2):
    """Two eligible waitlisted applications (families B and A) in one cohort; a
    single selection run issues two PENDING offers. Captures the cohort version
    BEFORE any accept. Returns bundle
    {program, cohort, famB, famA, appB, appA, offerB, offerA, version_before}."""
    program, cohort = setup_program_and_cohort(
        cohort_overrides={"funded_slots": cohort_funded_slots})
    famB, appB = add_waitlisted_applicant(
        program, cohort,
        family_overrides={"guardian_name": "B", "household_size": 3,
                          "annual_income_cents": 800_000, "categorical_eligibility": "TANF"},
        app_overrides={"child_first_name": "Bo", "child_last_name": "B",
                       "child_dob": "2022-01-10"},
        verified_income_cents=800_000)
    famA, appA = add_waitlisted_applicant(
        program, cohort,
        family_overrides={"guardian_name": "A", "household_size": 4,
                          "annual_income_cents": 1_400_000, "categorical_eligibility": "SNAP"},
        app_overrides={"child_first_name": "Al", "child_last_name": "A",
                       "child_dob": "2022-02-20"},
        verified_income_cents=1_400_000)
    run_selection(cohort["id"])
    offerB = offer_id_for_application(appB["id"])
    offerA = offer_id_for_application(appA["id"])
    version_before = cohort_version(cohort["id"])
    return {
        "program": program, "cohort": cohort,
        "famB": famB, "famA": famA, "appB": appB, "appA": appA,
        "offerB": offerB, "offerA": offerA, "version_before": version_before,
    }
