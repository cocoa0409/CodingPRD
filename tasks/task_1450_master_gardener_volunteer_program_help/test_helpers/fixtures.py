"""Composite setup helpers for multi-step PRD workflows.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the server is restarted before each test, so nothing carries
over). Setup calls use get_success_data so failures surface as clear
"Setup failed" assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (create_application_payload, create_ce_entry_payload,
                        create_credit_entry_payload, create_cycle_payload,
                        create_enrollment_payload, create_inquiry_payload,
                        create_project_payload,
                        create_rotation_assignment_payload,
                        create_shift_payload, create_signup_payload,
                        create_specialist_payload, decide_application_payload,
                        progress_payload, score_application_payload,
                        set_clock_payload, triage_payload)
from .test_users import (TEST_USERS, make_specialist_headers,
                         make_volunteer_headers)

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: cycle setup
# ---------------------------------------------------------------------------

def create_cycle(**overrides):
    """Create a DRAFT program cycle. Returns the cycle dict."""
    resp = api_client.create_cycle(create_cycle_payload(**overrides), COORD)
    return get_success_data(resp)


def create_and_open_cycle(**overrides):
    """Create a cycle and open it. Returns the OPEN cycle dict."""
    cycle = create_cycle(**overrides)
    resp = api_client.open_cycle(cycle["id"], COORD)
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock. Returns the reported current_utc."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), COORD)
    return get_success_data(resp)["current_utc"]


# ---------------------------------------------------------------------------
# Tier 2: admissions -> volunteer
# ---------------------------------------------------------------------------

def create_application(cycle_id, **overrides):
    resp = api_client.create_application(
        create_application_payload(cycle_id, **overrides), COORD)
    return get_success_data(resp)


def score_application(application_id, **overrides):
    resp = api_client.score_application(
        application_id, score_application_payload(**overrides), COORD)
    return get_success_data(resp)


def decide_application(application_id, decision="ACCEPT"):
    resp = api_client.decide_application(
        application_id, decide_application_payload(decision), COORD)
    return get_success_data(resp)


def create_accepted_volunteer(cycle_id, **app_overrides):
    """Create + score + ACCEPT an application. Returns the Volunteer."""
    app = create_application(cycle_id, **app_overrides)
    score_application(app["id"])
    decide_application(app["id"], "ACCEPT")
    resp = api_client.list_volunteers(
        COORD, params={"application_id": app["id"]})
    vols = get_success_data(resp)
    assert vols, "Setup failed: accepted application produced no volunteer"
    return vols[0]


# ---------------------------------------------------------------------------
# Tier 3: training -> ACTIVE volunteer (+ PENDING recertification record)
# ---------------------------------------------------------------------------

def create_active_volunteer(cycle_id, modules_completed=None,
                            quiz_average=85.0, **app_overrides):
    """Accepted applicant walked through training to ACTIVE.

    Returns the ACTIVE Volunteer dict. Also provisions the PENDING
    recertification record for the cycle (per the activation cascade).
    """
    vol = create_accepted_volunteer(cycle_id, **app_overrides)
    resp = api_client.create_enrollment(
        create_enrollment_payload(cycle_id, vol["id"]), COORD)
    enr = get_success_data(resp)
    mods = modules_completed if modules_completed is not None else 5
    resp = api_client.record_progress(
        enr["id"], progress_payload(mods, quiz_average), COORD)
    get_success_data(resp)
    resp = api_client.complete_enrollment(enr["id"], COORD)
    get_success_data(resp)
    resp = api_client.get_volunteer(vol["id"], COORD)
    return get_success_data(resp)


def get_record_for(volunteer_id, cycle_id):
    """Fetch the RecertificationRecord for a (volunteer, cycle) pair."""
    resp = api_client.list_recertification_records(
        COORD, params={"volunteer_id": volunteer_id, "cycle_id": cycle_id})
    recs = get_success_data(resp)
    assert recs, ("Setup failed: no recertification record for "
                  f"({volunteer_id}, {cycle_id})")
    return recs[0]


def setup_cycle_with_active_volunteer(cycle_overrides=None, **app_overrides):
    """OPEN cycle + one ACTIVE volunteer + PENDING record.

    Returns (cycle, volunteer, record).
    """
    cycle = create_and_open_cycle(**(cycle_overrides or {}))
    vol = create_active_volunteer(cycle["id"], **app_overrides)
    rec = get_record_for(vol["id"], cycle["id"])
    return cycle, vol, rec


def setup_cycle_with_two_active_volunteers(cycle_overrides=None):
    """OPEN cycle + two ACTIVE volunteers + their PENDING records.

    Returns (cycle, vol1, vol2, rec1, rec2).
    """
    cycle = create_and_open_cycle(**(cycle_overrides or {}))
    vol1 = create_active_volunteer(cycle["id"], applicant_name="Alice Arbor",
                                   email="alice@example.org",
                                   county="Harford", prior_gardening_years=7)
    vol2 = create_active_volunteer(cycle["id"], applicant_name="Bob Birch",
                                   email="bob@example.org", county="Cecil",
                                   prior_gardening_years=3)
    rec1 = get_record_for(vol1["id"], cycle["id"])
    rec2 = get_record_for(vol2["id"], cycle["id"])
    return cycle, vol1, vol2, rec1, rec2


# ---------------------------------------------------------------------------
# Tier 4: credit entries
# ---------------------------------------------------------------------------

def log_service_entry(volunteer_id, cycle_id, hours, activity_date,
                      activity_type="OTHER", **extra):
    """Volunteer self-logs a SERVICE entry (identity-threaded headers)."""
    payload = create_credit_entry_payload(
        cycle_id, activity_type=activity_type, activity_date=activity_date,
        hours=hours, **extra)
    resp = api_client.create_credit_entry(
        volunteer_id, payload, make_volunteer_headers(volunteer_id))
    return get_success_data(resp)


def log_ce_entry(volunteer_id, cycle_id, hours, activity_date="2026-09-01",
                 **extra):
    payload = create_ce_entry_payload(cycle_id, activity_date=activity_date,
                                      hours=hours, **extra)
    resp = api_client.create_credit_entry(
        volunteer_id, payload, make_volunteer_headers(volunteer_id))
    return get_success_data(resp)


def approve_entry(entry_id):
    resp = api_client.approve_credit_entry(entry_id, COORD)
    return get_success_data(resp)


def reject_entry(entry_id, reason="unverifiable"):
    resp = api_client.reject_credit_entry(entry_id, {"reason": reason}, COORD)
    return get_success_data(resp)


def log_and_approve_service_entry(volunteer_id, cycle_id, hours,
                                  activity_date, activity_type="OTHER",
                                  **extra):
    entry = log_service_entry(volunteer_id, cycle_id, hours, activity_date,
                              activity_type=activity_type, **extra)
    return approve_entry(entry["id"])


# ---------------------------------------------------------------------------
# Tier 2/3: specialists
# ---------------------------------------------------------------------------

def create_specialist(**overrides):
    resp = api_client.create_specialist(create_specialist_payload(**overrides),
                                        COORD)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: shifts and signups
# ---------------------------------------------------------------------------

def create_shift(cycle_id, **overrides):
    resp = api_client.create_shift(create_shift_payload(cycle_id, **overrides),
                                   COORD)
    return get_success_data(resp)


def sign_up(shift_id, volunteer_id):
    resp = api_client.create_signup(shift_id, create_signup_payload(
        volunteer_id), make_volunteer_headers(volunteer_id))
    return get_success_data(resp)


def complete_shift_and_signup(shift_id, signup_id):
    """Mark shift COMPLETED (assumes clock already past end_time) then mark
    the signup COMPLETED, returning the signup with completed_entry_id."""
    resp = api_client.complete_shift(shift_id, COORD)
    get_success_data(resp)
    resp = api_client.complete_signup(signup_id, COORD)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: inquiries and referrals
# ---------------------------------------------------------------------------

def log_inquiry(shift_id, volunteer_id, **overrides):
    resp = api_client.create_inquiry(
        shift_id, create_inquiry_payload(volunteer_id, **overrides),
        make_volunteer_headers(volunteer_id))
    return get_success_data(resp)


def triage_inquiry(inquiry_id, category="PEST"):
    resp = api_client.triage_inquiry(inquiry_id, triage_payload(category),
                                     COORD)
    return get_success_data(resp)


def create_referral(inquiry_id, **payload_overrides):
    resp = api_client.create_referral(inquiry_id, payload_overrides, COORD)
    return get_success_data(resp)


def setup_staffed_help_desk_shift(cycle_id, volunteer_id,
                                  start_time="2026-08-05T09:00:00Z",
                                  end_time="2026-08-05T12:00:00Z",
                                  location="Desk A", kind="HELP_DESK",
                                  capacity=2, clock_in_window=None):
    """Help-desk shift with the volunteer SIGNED_UP; optionally park the
    clock inside the shift window so inquiries are loggable.

    Returns the shift dict.
    """
    shift = create_shift(cycle_id, kind=kind, location=location,
                         start_time=start_time, end_time=end_time,
                         capacity=capacity)
    sign_up(shift["id"], volunteer_id)
    if clock_in_window:
        set_clock(clock_in_window)
    return shift


def setup_triaged_inquiry(cycle_id, volunteer_id, category="PEST",
                          clock_in_window="2026-08-05T10:00:00Z", **inq_kw):
    """Staffed shift + LOGGED inquiry + TRIAGED. Returns (shift, inquiry)."""
    shift = setup_staffed_help_desk_shift(
        cycle_id, volunteer_id, clock_in_window=clock_in_window)
    inq = log_inquiry(shift["id"], volunteer_id, **inq_kw)
    triage_inquiry(inq["id"], category)
    resp = api_client.get_inquiry(inq["id"], COORD)
    return shift, get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: community projects
# ---------------------------------------------------------------------------

def create_project(cycle_id, organizer_volunteer_id, **overrides):
    resp = api_client.create_project(
        create_project_payload(cycle_id, organizer_volunteer_id, **overrides),
        make_volunteer_headers(organizer_volunteer_id))
    return get_success_data(resp)


def submit_project(project_id, organizer_volunteer_id):
    resp = api_client.submit_project(
        project_id, make_volunteer_headers(organizer_volunteer_id))
    return get_success_data(resp)


def approve_project(project_id, coordinator_headers=None):
    resp = api_client.approve_project(
        project_id, coordinator_headers or COORD)
    return get_success_data(resp)


def create_approved_project(cycle_id, organizer_volunteer_id,
                            approver_headers=None, **overrides):
    """Project walked DRAFT -> UNDER_REVIEW -> APPROVED. Returns the project."""
    proj = create_project(cycle_id, organizer_volunteer_id, **overrides)
    submit_project(proj["id"], organizer_volunteer_id)
    return approve_project(proj["id"], approver_headers)


# ---------------------------------------------------------------------------
# Tier 3: rotation assignments
# ---------------------------------------------------------------------------

def create_rotation_assignment(bed_code, volunteer_id, week_start):
    resp = api_client.create_rotation_assignment(
        create_rotation_assignment_payload(bed_code, volunteer_id,
                                           week_start), COORD)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: cycle close / terminal state
# ---------------------------------------------------------------------------

def move_cycle_to_recertification(cycle_id, clock="2026-11-02T00:00:00Z"):
    set_clock(clock)
    resp = api_client.begin_recertification(cycle_id, COORD)
    return get_success_data(resp)


def close_cycle(cycle_id):
    resp = api_client.close_cycle(cycle_id, COORD)
    return get_success_data(resp)


def setup_cycle_closed_with_shortfall_volunteer():
    """Full lifecycle: cycle with an ACTIVE volunteer holding zero approved
    hours, closed -> volunteer INACTIVE with consecutive_shortfall_cycles 1.

    Returns (cycle, volunteer).
    """
    cycle, vol, _rec = setup_cycle_with_active_volunteer()
    move_cycle_to_recertification(cycle["id"])
    close_cycle(cycle["id"])
    resp = api_client.get_volunteer(vol["id"], COORD)
    return cycle, get_success_data(resp)


def specialist_headers_for(specialist_id):
    return make_specialist_headers(specialist_id)
