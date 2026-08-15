"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before each test) and uses get_success_data()
so a broken setup surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_DEFAULT, SCHOOL_YEAR_DEFAULT, TEST_DEFAULTS
from .factories import (
    create_appointment_payload,
    create_clinic_session_payload,
    create_compliance_notice_payload,
    create_exemption_request_payload,
    create_immunization_record_payload,
    create_outbreak_event_payload,
    create_student_payload,
    create_vaccine_requirement_payload,
    deny_exemption_payload,
    district_rollup_payload,
    generate_snapshot_payload,
    rescind_notice_payload,
    resubmit_exemption_payload,
    seed_registry_dose_payload,
    set_clock_payload,
    void_record_payload,
)
from .test_users import TEST_USERS, make_nurse_headers, make_officer_headers

CLERK = TEST_USERS["clerk_headers"]
NURSE = TEST_USERS["nurse_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER_2 = TEST_USERS["officer_2_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ─── Tier 1: atomic creators ────────────────────────────────────────────────


def create_mmr_requirement(
    doses_required=TEST_DEFAULTS["DOSES_REQUIRED"],
    min_interval_days=TEST_DEFAULTS["MIN_INTERVAL_DAYS"],
    min_age_months=TEST_DEFAULTS["MIN_AGE_MONTHS"],
    applies_to_grades=None,
    vaccine_code="MMR",
    school_year=SCHOOL_YEAR_DEFAULT,
):
    """Configure a vaccine requirement (DistrictHealthOfficer). Returns it."""
    res = api_client.create_vaccine_requirement(
        create_vaccine_requirement_payload(
            vaccine_code=vaccine_code,
            applies_to_grades=list(applies_to_grades or ["K"]),
            doses_required=doses_required,
            min_interval_days=min_interval_days,
            min_age_months=min_age_months,
            school_year=school_year,
        ),
        OFFICER,
    )
    return get_success_data(res)


def create_student(
    school_code,
    legal_name="Test Student",
    grade="K",
    date_of_birth=TEST_DEFAULTS["DATE_OF_BIRTH"],
    enrollment_date=TEST_DEFAULTS["ENROLLMENT_DATE"],
):
    """Register a student (HealthClerk). Returns the created student."""
    res = api_client.create_student(
        create_student_payload(
            legal_name=legal_name,
            date_of_birth=date_of_birth,
            grade=grade,
            school_code=school_code,
            enrollment_date=enrollment_date,
        ),
        CLERK,
    )
    return get_success_data(res)


def get_student(student_id):
    return get_success_data(api_client.get_student(student_id, CLERK))


def set_logical_clock(to_iso8601):
    """Advance the logical clock (DistrictHealthOfficer)."""
    res = api_client.set_current_utc(set_clock_payload(to_iso8601), OFFICER)
    return get_success_data(res)


def run_sweep():
    """Run the compliance sweep checkpoint (DistrictHealthOfficer)."""
    res = api_client.run_compliance_sweep(OFFICER)
    return get_success_data(res)


def get_compliance(student_id):
    """Read the per-requirement compliance view for a student."""
    res = api_client.get_student_compliance(student_id, NURSE)
    return get_success_data(res)


def list_notices(student_id):
    """Return (notices, meta) for a student."""
    res = api_client.list_compliance_notices(student_id, OFFICER)
    return validate_paginated(res)


def list_student_records(student_id):
    """Return (records, meta) for a student."""
    res = api_client.list_immunization_records(student_id, NURSE)
    return validate_paginated(res)


def list_exemptions(student_id):
    """Return (exemption requests, meta) for a student."""
    res = api_client.list_exemption_requests(student_id, OFFICER)
    return validate_paginated(res)


# ─── Tier 2: dose flows ─────────────────────────────────────────────────────


def add_manual_dose(
    student_id,
    student_version,
    vaccine_code="MMR",
    dose_number=1,
    administered_date="2026-08-05T00:00:00Z",
):
    """Record a MANUAL dose (HealthClerk, OCC-guarded). Returns the record."""
    res = api_client.create_immunization_record(
        student_id,
        create_immunization_record_payload(
            student_version,
            vaccine_code=vaccine_code,
            dose_number=dose_number,
            administered_date=administered_date,
        ),
        CLERK,
    )
    return get_success_data(res)


def verify_record(record_id):
    """Verify a pending record (SchoolNurse). Returns the verified record."""
    res = api_client.verify_immunization_record(record_id, NURSE)
    return get_success_data(res)


def add_verified_dose(
    student_id,
    vaccine_code="MMR",
    dose_number=1,
    administered_date="2026-08-05T00:00:00Z",
):
    """Record + verify a MANUAL dose. Returns the VERIFIED record."""
    student = get_student(student_id)
    record = add_manual_dose(
        student_id,
        student["version"],
        vaccine_code=vaccine_code,
        dose_number=dose_number,
        administered_date=administered_date,
    )
    return verify_record(record["id"])


# ─── Tier 3: exemption flows ────────────────────────────────────────────────


def submit_exemption(
    student_id,
    vaccine_code="MMR",
    exemption_type="MEDICAL",
    document_ref="doc://exm-1",
    submitter_headers=None,
):
    """Submit an exemption request; defaults to SchoolNurse nurse-1."""
    res = api_client.create_exemption_request(
        student_id,
        create_exemption_request_payload(
            vaccine_code=vaccine_code,
            exemption_type=exemption_type,
            document_ref=document_ref,
        ),
        submitter_headers or NURSE,
    )
    return get_success_data(res)


def review_exemption(exemption_id, officer_headers=None):
    """Move a request SUBMITTED -> UNDER_REVIEW (DistrictHealthOfficer)."""
    res = api_client.start_exemption_review(exemption_id, officer_headers or OFFICER)
    return get_success_data(res)


def approve_exemption(exemption_id, officer_headers=None):
    """Move a request UNDER_REVIEW -> APPROVED (DistrictHealthOfficer)."""
    res = api_client.approve_exemption(exemption_id, officer_headers or OFFICER)
    return get_success_data(res)


def deny_exemption(exemption_id, denial_reason="missing physician signature",
                   officer_headers=None):
    """Move a request UNDER_REVIEW -> DENIED (DistrictHealthOfficer)."""
    res = api_client.deny_exemption(
        exemption_id, deny_exemption_payload(denial_reason=denial_reason),
        officer_headers or OFFICER,
    )
    return get_success_data(res)


def create_approved_exemption(student_id, vaccine_code="MMR",
                              submitter_headers=None, reviewer_headers=None):
    """Submit (nurse-1) -> start-review (officer-1) -> approve (officer-1)."""
    exemption = submit_exemption(
        student_id, vaccine_code=vaccine_code, submitter_headers=submitter_headers
    )
    review_exemption(exemption["id"], officer_headers=reviewer_headers)
    return approve_exemption(exemption["id"], officer_headers=reviewer_headers)


def create_student_with_approved_exemption(school_code, vaccine_code="MMR",
                                           requirement=True):
    """Requirement (optional) + student + APPROVED exemption. Returns (student, exemption)."""
    if requirement:
        create_mmr_requirement(vaccine_code=vaccine_code)
    student = create_student(school_code)
    exemption = create_approved_exemption(student["id"], vaccine_code=vaccine_code)
    return get_student(student["id"]), exemption


def create_denied_exemption(school_code, vaccine_code="MMR", requirement=True):
    """Requirement (optional) + student + exemption driven SUBMITTED -> UNDER_REVIEW -> DENIED."""
    if requirement:
        create_mmr_requirement(vaccine_code=vaccine_code)
    student = create_student(school_code)
    exemption = submit_exemption(student["id"], vaccine_code=vaccine_code)
    review_exemption(exemption["id"])
    denied = deny_exemption(exemption["id"])
    return student, denied


# ─── Tier 4: clinic session / appointment flows ─────────────────────────────


def create_open_session(school_code="SCH-C1",
                        session_date=TEST_DEFAULTS["SESSION_DATE"],
                        duration_minutes=120, capacity=5):
    """Create a session (SchoolNurse) and open it. Returns the OPEN session."""
    res = api_client.create_clinic_session(
        create_clinic_session_payload(
            school_code=school_code,
            session_date=session_date,
            duration_minutes=duration_minutes,
            capacity=capacity,
        ),
        NURSE,
    )
    session = get_success_data(res)
    res = api_client.open_clinic_session(session["id"], NURSE)
    return get_success_data(res)


def get_session(session_id):
    return get_success_data(api_client.get_clinic_session(session_id, NURSE))


def book_appointment(session_id, student_id, vaccine_code="MMR",
                     start_time="2026-09-01T10:00:00Z",
                     end_time="2026-09-01T10:30:00Z"):
    """Book an appointment (HealthClerk), refreshing the session OCC version."""
    session = get_session(session_id)
    res = api_client.book_appointment(
        session_id,
        create_appointment_payload(
            student_id,
            session["version"],
            vaccine_code=vaccine_code,
            start_time=start_time,
            end_time=end_time,
        ),
        CLERK,
    )
    return get_success_data(res)


def cancel_appointment(appointment_id):
    res = api_client.cancel_appointment(appointment_id, CLERK)
    return get_success_data(res)


def complete_appointment(appointment_id):
    res = api_client.complete_appointment(appointment_id, NURSE)
    return get_success_data(res)


# ─── Tier 5: outbreak flows ─────────────────────────────────────────────────


def declare_outbreak(school_code, vaccine_code="MMR"):
    res = api_client.create_outbreak_event(
        create_outbreak_event_payload(school_code=school_code, vaccine_code=vaccine_code),
        OFFICER,
    )
    return get_success_data(res)


def lift_outbreak(outbreak_id):
    res = api_client.lift_outbreak_event(outbreak_id, OFFICER)
    return get_success_data(res)


# ─── Tier 6: registry / snapshot flows ──────────────────────────────────────


def seed_registry_dose(student_id, vaccine_code="MMR", dose_number=2,
                       administered_date="2026-08-06T00:00:00Z"):
    res = api_client.seed_registry_dose(
        seed_registry_dose_payload(
            student_id,
            vaccine_code=vaccine_code,
            dose_number=dose_number,
            administered_date=administered_date,
        ),
        COORDINATOR,
    )
    return get_success_data(res)


def run_registry_sync(school_code):
    res = api_client.create_registry_sync_run({"school_code": school_code}, COORDINATOR)
    return get_success_data(res)


def generate_snapshot(school_code, grade="K",
                      census_date=TEST_DEFAULTS["CENSUS_DATE"],
                      rate_variant="CENSUS_DATE",
                      school_year=SCHOOL_YEAR_DEFAULT):
    res = api_client.generate_compliance_snapshot(
        generate_snapshot_payload(
            school_year=school_year,
            school_code=school_code,
            grade=grade,
            census_date=census_date,
            rate_variant=rate_variant,
        ),
        COORDINATOR,
    )
    return get_success_data(res)


def district_rollup(school_year=SCHOOL_YEAR_DEFAULT, grade="K"):
    res = api_client.district_rollup(
        district_rollup_payload(school_year=school_year, grade=grade), OFFICER
    )
    return get_success_data(res)


# ─── Tier 7: composite compliance scenarios ─────────────────────────────────


def create_deficient_student(school_code="SCH-D"):
    """Requirement MMR/K/1 dose + student with no doses. Returns the student."""
    create_mmr_requirement(doses_required=1)
    return create_student(school_code)


def setup_student_non_compliant_with_notice(school_code="SCH-NC",
                                            clock="2026-09-01T00:00:00Z"):
    """Deficient student swept once past the provisional deadline.

    Returns (student_after, notice, sweep_data) with the student NON_COMPLIANT
    and one INITIAL_NONCOMPLIANCE notice in ISSUED.
    """
    student = create_deficient_student(school_code)
    set_logical_clock(clock)
    sweep = run_sweep()
    notices, _ = list_notices(student["id"])
    return get_student(student["id"]), notices[0], sweep


def setup_student_excluded_via_sweep(school_code="SCH-EXC",
                                     first_clock="2026-09-01T00:00:00Z",
                                     second_clock="2026-09-15T00:00:00Z"):
    """Deficient student swept past deadline, then swept at the exclusion date.

    Returns (student_after, notice) with the student EXCLUDED and the notice
    EXCLUSION_EFFECTIVE.
    """
    student = create_deficient_student(school_code)
    set_logical_clock(first_clock)
    run_sweep()
    set_logical_clock(second_clock)
    run_sweep()
    notices, _ = list_notices(student["id"])
    return get_student(student["id"]), notices[0]


def setup_two_student_roster(school_code="SCH-R2"):
    """One deficient student (first) and one compliant student (second)."""
    create_mmr_requirement(doses_required=1)
    deficient = create_student(school_code, legal_name="Roster Deficient")
    compliant = create_student(school_code, legal_name="Roster Compliant")
    add_verified_dose(compliant["id"])
    return get_student(deficient["id"]), get_student(compliant["id"])


def setup_manual_plus_registry_student(school_code="SCH-REG",
                                       registry_administered_date="2026-08-06T00:00:00Z"):
    """Two-dose MMR requirement; student with one VERIFIED MANUAL dose plus one
    seeded registry dose that a sync run then imports. Returns (student, run)."""
    create_mmr_requirement(doses_required=2, min_interval_days=28)
    student = create_student(school_code)
    add_verified_dose(student["id"], dose_number=1,
                      administered_date="2026-08-05T00:00:00Z")
    seed_registry_dose(student["id"], dose_number=2,
                       administered_date=registry_administered_date)
    run = run_registry_sync(school_code)
    return get_student(student["id"]), run


def setup_census_variant_school(school_code="SCH-R"):
    """Three grade-K students: one compliant, one non-compliant, one withdrawn."""
    create_mmr_requirement(doses_required=1)
    compliant = create_student(school_code, legal_name="Case Compliant")
    add_verified_dose(compliant["id"])
    non_compliant = create_student(school_code, legal_name="Case Noncompliant")
    withdrawn = create_student(school_code, legal_name="Case Withdrawn")
    api_client.withdraw_student(withdrawn["id"], CLERK)
    return {
        "compliant": get_student(compliant["id"]),
        "non_compliant": get_student(non_compliant["id"]),
        "withdrawn": get_student(withdrawn["id"]),
    }


def setup_rollup_scenario():
    """SCH-A with 2 compliant of 3; SCH-B with 1 compliant of 6 (grade K)."""
    create_mmr_requirement(doses_required=1)

    def _populate(school_code, n_compliant, n_total):
        for i in range(n_total):
            student = create_student(school_code, legal_name=f"{school_code} Stu {i}")
            if i < n_compliant:
                add_verified_dose(student["id"])

    _populate("SCH-A", 2, 3)
    _populate("SCH-B", 1, 6)


def setup_two_sessions_one_booked(school_1="SCH-S1", school_2="SCH-S2"):
    """Student A plus session 1 (OPEN, A booked 10:00-10:30) and session 2
    (left SCHEDULED, different school so the 7-day spacing rule is silent)."""
    student = create_student("SCH-Y", legal_name="Pat Why")
    session_1 = create_open_session(
        school_1, session_date="2026-09-01T09:00:00Z", duration_minutes=180
    )
    book_appointment(session_1["id"], student["id"],
                     start_time="2026-09-01T10:00:00Z",
                     end_time="2026-09-01T10:30:00Z")
    res = api_client.create_clinic_session(
        create_clinic_session_payload(
            school_code=school_2,
            session_date="2026-09-01T09:00:00Z",
            duration_minutes=180,
            capacity=5,
        ),
        NURSE,
    )
    session_2 = get_success_data(res)
    return student, get_session(session_1["id"]), session_2
