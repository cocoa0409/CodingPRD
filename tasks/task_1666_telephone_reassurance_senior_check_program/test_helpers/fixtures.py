"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
begins against an empty database and the default logical clock
2026-08-01T00:00:00Z). Setup calls use the lenient get_success_data so a
broken precondition surfaces as a clear "Setup failed" error.

Identity threading: after creating a VolunteerCaller, every ownership-gated
call (agreement signing, call logging) uses make_volunteer_headers(v["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AGREEMENT_VALID_UNTIL,
    MON_0803,
    REQUIRED_TRAINING_MODULES,
    TRAINING_VALID_UNTIL,
)
from .factories import (
    create_availability_window_payload,
    create_call_assignment_payload,
    create_call_log_payload,
    create_call_schedule_payload,
    create_confidentiality_agreement_payload,
    create_emergency_contact_payload,
    create_participant_payload,
    create_program_payload,
    create_training_record_payload,
    create_volunteer_payload,
)
from .test_users import TEST_USERS, make_coordinator_headers, make_volunteer_headers

COORD = TEST_USERS["coordinator_headers"]
INTAKE = TEST_USERS["intake_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
RESPONDER = TEST_USERS["responder_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + program
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, headers=None):
    """Advance the logical clock (PRD §2.4). Returns {current_utc}."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, headers or COORD))


def create_program(**overrides):
    """Create the program (PRD §3.1). Returns the Program."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), COORD))


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, COORD))


def daily_closeout(program_id):
    """Run the daily closeout epoch (PRD §3.9). Returns the touched-id arrays."""
    return get_success_data(api_client.daily_closeout(program_id, COORD))


# ---------------------------------------------------------------------------
# Tier 1: participant lifecycle
# ---------------------------------------------------------------------------

def create_applicant(**overrides):
    """Create a participant application (status APPLICANT)."""
    return get_success_data(api_client.create_participant(create_participant_payload(**overrides), INTAKE))


def add_emergency_contact(participant_id, **overrides):
    """Add an emergency contact to a participant (starts ACTIVE)."""
    return get_success_data(
        api_client.create_emergency_contact(participant_id, create_emergency_contact_payload(**overrides), INTAKE)
    )


def submit_for_review(participant_id):
    """APPLICANT -> UNDER_REVIEW; computes the intake acuity (PRD §3.2)."""
    return get_success_data(api_client.submit_review(participant_id, INTAKE))


def approve_participant(participant_id):
    """UNDER_REVIEW -> ENROLLED or WAITLISTED (capacity branch, PRD §3.2).
    Returns the Participant in whichever branch state resulted."""
    return get_success_data(api_client.approve_participant(participant_id, INTAKE))


def _intake_score(p: dict) -> int:
    """The intake acuity score formula (PRD §3.2), used only to pre-decide
    whether the approval needs a 24h-capable contact (HIGH/CRITICAL gate)."""
    age = {"AGE_65_74": 0, "AGE_75_84": 10, "AGE_85_PLUS": 20}[p["age_band"]]
    alone = 25 if p.get("lives_alone") else 0
    mobility = {"NONE": 0, "LIMITED": 10, "SEVERE": 20}[p["mobility"]]
    cog = 20 if p.get("cognitive_concern") else 0
    chronic = min(3, p.get("chronic_conditions_count", 0)) * 5
    hosp = 10 if p.get("recent_hospitalization") else 0
    bereave = 5 if p.get("recent_bereavement") else 0
    return min(100, age + alone + mobility + cog + chronic + hosp + bereave)


def enroll_participant(participant_overrides=None, contact_overrides=None):
    """Create + contact + submit-review + approve; requires the program to
    have free capacity. Returns the ENROLLED participant."""
    p_over = dict(participant_overrides or {})
    participant = create_applicant(**p_over)
    c_over = {"accepts_24h": True} if _intake_score({**create_participant_payload(), **p_over}) >= 60 else {}
    c_over.update(contact_overrides or {})
    add_emergency_contact(participant["id"], **c_over)
    submit_for_review(participant["id"])
    enrolled = approve_participant(participant["id"])
    assert enrolled["status"] == "ENROLLED", (
        f"Setup failed: expected ENROLLED, got {enrolled['status']} "
        "(capacity or safety gate unexpectedly blocked the enrollment)"
    )
    return enrolled


def waitlist_applicant(participant_overrides=None, contact_overrides=None):
    """Create + contact + submit-review + approve against a full program;
    returns (WAITLISTED participant, its WAITING WaitlistEntry)."""
    p_over = dict(participant_overrides or {})
    participant = create_applicant(**p_over)
    c_over = {"accepts_24h": True} if _intake_score({**create_participant_payload(), **p_over}) >= 60 else {}
    c_over.update(contact_overrides or {})
    add_emergency_contact(participant["id"], **c_over)
    submit_for_review(participant["id"])
    waitlisted = approve_participant(participant["id"])
    assert waitlisted["status"] == "WAITLISTED", (
        f"Setup failed: expected WAITLISTED, got {waitlisted['status']}"
    )
    entries, _meta = _list_entries(participant["id"])
    assert len(entries) == 1, "Setup failed: expected exactly one waitlist entry"
    return waitlisted, entries[0]


def _list_entries(participant_id):
    resp = api_client.list_participant_waitlist_entries(participant_id, INTAKE)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data, resp.json().get("meta", {})
    return data.get("items", data), resp.json().get("meta", {})


def get_waitlist_entry_of(participant_id):
    """Fetch the participant's single waitlist entry."""
    entries, _ = _list_entries(participant_id)
    assert entries, "Setup failed: participant has no waitlist entry"
    return entries[0]


# ---------------------------------------------------------------------------
# Tier 1: volunteer lifecycle
# ---------------------------------------------------------------------------

def create_volunteer(**overrides):
    """Register a volunteer (status APPLICANT, tier SILVER)."""
    return get_success_data(api_client.create_volunteer(create_volunteer_payload(**overrides), COORD))


def create_certified_volunteer(weekdays=("MON",), volunteer_overrides=None,
                               policy_version="v2026.1",
                               training_valid_until=TRAINING_VALID_UNTIL,
                               availability_window=("08:00", "17:00"),
                               effective_from="2026-08-01"):
    """Full roster path (PRD §3.4): register -> begin-training -> three
    required training records -> volunteer signs own agreement -> certify ->
    availability windows. Returns the ACTIVE volunteer."""
    v = create_volunteer(**(volunteer_overrides or {}))
    get_success_data(api_client.begin_training(v["id"], COORD))
    for module in REQUIRED_TRAINING_MODULES:
        get_success_data(api_client.create_training_record(
            v["id"],
            create_training_record_payload(module=module, valid_until=training_valid_until),
            COORD,
        ))
    get_success_data(api_client.sign_confidentiality_agreement(
        v["id"],
        create_confidentiality_agreement_payload(policy_version=policy_version,
                                                 valid_until=AGREEMENT_VALID_UNTIL),
        make_volunteer_headers(v["id"]),
    ))
    certified = get_success_data(api_client.certify_volunteer(v["id"], COORD))
    assert certified["status"] == "ACTIVE", (
        f"Setup failed: expected ACTIVE after certify, got {certified['status']}"
    )
    for weekday in weekdays:
        get_success_data(api_client.create_availability_window(
            v["id"],
            create_availability_window_payload(weekday=weekday,
                                               window_start=availability_window[0],
                                               window_end=availability_window[1],
                                               effective_from=effective_from),
            COORD,
        ))
    return get_success_data(api_client.get_volunteer(v["id"], COORD))


# ---------------------------------------------------------------------------
# Tier 2: schedules + assignments + logs
# ---------------------------------------------------------------------------

def add_call_schedule(participant_id, weekday="MON", window_start="09:00", window_end="11:00"):
    return get_success_data(api_client.create_call_schedule(
        participant_id,
        create_call_schedule_payload(weekday=weekday, window_start=window_start, window_end=window_end),
        COORD,
    ))


def create_assignment(participant_id, volunteer_id=None, scheduled_date=MON_0803,
                      window_start="09:00", window_end="09:30", source=None):
    """Create a call assignment (201). Returns the SCHEDULED assignment."""
    payload = create_call_assignment_payload(
        participant_id=participant_id, scheduled_date=scheduled_date,
        window_start=window_start, window_end=window_end,
    )
    if volunteer_id is not None:
        payload["volunteer_id"] = volunteer_id
    if source is not None:
        payload["source"] = source
    return get_success_data(api_client.create_call_assignment(payload, COORD))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_call_assignment(assignment_id, COORD))


def log_call(assignment_id, volunteer_id, called_at, outcome, **extra):
    """The assigned volunteer records the call outcome on their own
    assignment (ownership-gated, PRD §2.1)."""
    payload = create_call_log_payload(called_at=called_at, outcome=outcome, **extra)
    return get_success_data(
        api_client.create_call_log(assignment_id, payload, make_volunteer_headers(volunteer_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: composite environments
# ---------------------------------------------------------------------------

def setup_enrolled_participant(schedules=(("MON", "09:00", "11:00"),),
                               participant_overrides=None,
                               contact_overrides=None,
                               program_overrides=None):
    """Program + one ENROLLED participant + the given ACTIVE schedules.
    Returns (program, participant)."""
    program = create_program(**(program_overrides or {}))
    participant = enroll_participant(participant_overrides, contact_overrides)
    for weekday, start, end in schedules:
        add_call_schedule(participant["id"], weekday=weekday, window_start=start, window_end=end)
    return program, participant


def setup_calling_environment(schedules=(("MON", "09:00", "11:00"),),
                              volunteer_weekdays=("MON",),
                              participant_overrides=None,
                              contact_overrides=None,
                              program_overrides=None,
                              volunteer_overrides=None,
                              policy_version="v2026.1"):
    """Program + ENROLLED participant with schedules + one certified volunteer
    with availability. Returns (program, participant, volunteer)."""
    program = create_program(**(program_overrides or {}))
    participant = enroll_participant(participant_overrides, contact_overrides)
    for weekday, start, end in schedules:
        add_call_schedule(participant["id"], weekday=weekday, window_start=start, window_end=end)
    volunteer = create_certified_volunteer(
        weekdays=volunteer_weekdays,
        volunteer_overrides=volunteer_overrides,
        policy_version=program.get("current_policy_version", policy_version),
    )
    return program, participant, volunteer


# ---------------------------------------------------------------------------
# Tier 3: escalations
# ---------------------------------------------------------------------------

def open_escalation(participant_id, trigger_type="MANUAL", opener_user_id="coord-1", note=None):
    """Open an escalation by hand (OCC-guarded, PRD §2.7/§3.7): reads the
    participant's current version and anchors the create to it. The opener is
    a ProgramCoordinator with the given opaque user id."""
    participant = get_success_data(api_client.get_participant(participant_id, COORD))
    payload = {
        "participant_id": participant_id,
        "trigger_type": trigger_type,
        "expected_participant_version": participant["version"],
    }
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.create_escalation(payload, make_coordinator_headers(opener_user_id))
    )


def get_escalation(escalation_id):
    return get_success_data(api_client.get_escalation(escalation_id, COORD))


def get_open_escalation_id(participant_id):
    participant = get_success_data(api_client.get_participant(participant_id, COORD))
    assert participant.get("open_escalation_id"), (
        "Setup failed: participant has no open escalation"
    )
    return participant["open_escalation_id"]


def list_welfare_checks_of(escalation_id):
    data = get_success_data(api_client.list_escalation_welfare_checks(escalation_id, COORD))
    return data if isinstance(data, list) else data.get("items", data)


# ---------------------------------------------------------------------------
# Tier 3: waitlist promotion
# ---------------------------------------------------------------------------

def run_promotion(program_id):
    """Run one promotion epoch at the program's current version (PRD §3.3).
    Returns {epoch, offers_created, offered_entry_ids, gross_free_after}."""
    program = get_success_data(api_client.get_program(program_id, INTAKE))
    return get_success_data(
        api_client.run_promotion(program_id, {"expected_program_version": program["version"]}, INTAKE)
    )


# ---------------------------------------------------------------------------
# Tier 3: referrals / surveys / reports
# ---------------------------------------------------------------------------

def create_submitted_referral(participant_id, service_type="MEALS", priority="STANDARD",
                              source_call_log_id=None):
    """DRAFT -> SUBMITTED referral (stamps submitted_at and sla_due_at)."""
    payload = {"participant_id": participant_id, "service_type": service_type, "priority": priority}
    if source_call_log_id is not None:
        payload["source_call_log_id"] = source_call_log_id
    referral = get_success_data(api_client.create_service_referral(payload, COORD))
    return get_success_data(api_client.submit_service_referral(referral["id"], COORD))


def issue_survey(participant_id, period_month="2026-08"):
    return get_success_data(
        api_client.issue_satisfaction_survey(participant_id, {"period_month": period_month}, INTAKE)
    )
