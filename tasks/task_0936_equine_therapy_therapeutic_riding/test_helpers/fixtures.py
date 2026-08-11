"""Composite setup helpers.

Every helper builds its state through declared API endpoints only - the test
harness restarts the server before each test, so nothing is ever pre-seeded.
Setup calls use the lenient `get_success_data` validator so a broken precondition
surfaces as a setup failure rather than as a confusing assertion further down.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_DEFAULT_UTC
from .factories import (
    assessment_payload,
    condition_policy_payload,
    crew_assignment_payload,
    goal_payload,
    grant_payload,
    horse_payload,
    incident_payload,
    instructor_payload,
    medical_release_payload,
    period_report_payload,
    progress_note_payload,
    qualification_payload,
    rider_payload,
    scholarship_award_payload,
    session_payload,
    volunteer_payload,
)
from .test_users import TEST_USERS, make_instructor_headers

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
COORD = TEST_USERS["volunteer_coordinator_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1 - single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str = LOGICAL_CLOCK_DEFAULT_UTC) -> Dict[str, Any]:
    """Move the logical clock. PRD 2.5: only a ProgramAdmin may drive it."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def make_condition_policy(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_condition_policy(condition_policy_payload(**overrides), ADMIN)
    )


def make_horse(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_horse(horse_payload(**overrides), ADMIN))


def make_instructor(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_instructor(instructor_payload(**overrides), ADMIN)
    )


def make_rider(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_rider(rider_payload(**overrides), INTAKE))


def read_rider(rider_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_rider(rider_id, ADMIN))


def rider_version(rider_id: str) -> int:
    return int(read_rider(rider_id)["version"])


def read_session(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_session(session_id, ADMIN))


def session_version(session_id: str) -> int:
    return int(read_session(session_id)["version"])


def file_release(
    rider_id: str, expected_rider_version: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    version = (
        expected_rider_version
        if expected_rider_version is not None
        else rider_version(rider_id)
    )
    return get_success_data(
        api_client.create_medical_release(
            rider_id, medical_release_payload(version, **overrides), INTAKE
        )
    )


def file_assessment(
    rider_id: str,
    instructor_id: str,
    expected_rider_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_rider_version
        if expected_rider_version is not None
        else rider_version(rider_id)
    )
    return get_success_data(
        api_client.create_assessment(
            rider_id,
            assessment_payload(version, **overrides),
            make_instructor_headers(instructor_id),
        )
    )


def activate_rider(rider_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_rider(rider_id, INTAKE))


def make_volunteer(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_volunteer(volunteer_payload(**overrides), COORD)
    )


def make_qualification(volunteer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_qualification(
            volunteer_id, qualification_payload(**overrides), COORD
        )
    )


def sign_off_qualification(qualification_id: str, signed_off_on: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.sign_off_qualification(
            qualification_id, {"signed_off_on": signed_off_on}, COORD
        )
    )


def make_grant(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_grant(grant_payload(**overrides), ADMIN))


def make_scholarship_award(rider_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_scholarship_award(
            rider_id, scholarship_award_payload(**overrides), INTAKE
        )
    )


def make_goal(rider_id: str, instructor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_goal(
            rider_id, goal_payload(**overrides), make_instructor_headers(instructor_id)
        )
    )


def make_period_report(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_period_report(period_report_payload(**overrides), ADMIN)
    )


def finalize_period_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_period_report(report_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2 - qualified volunteers
# ---------------------------------------------------------------------------


def make_qualified_volunteer(
    crew_role: str = "SIDEWALKER",
    full_name: str = "Sam Sidewalker",
    date_of_birth: str = "2000-02-02",
    last_retraining_on: str = "2026-04-01",
    training_hours: Optional[float] = None,
    signed_off_on: str = "2026-04-01",
    sign_off: bool = True,
) -> Dict[str, Any]:
    """Register a volunteer, open a role qualification and sign it off.

    Default training hours meet the role minimum stated in PRD 3.4 - 12 hours to
    lead, 6 to sidewalk, 3 for barn work.
    """
    default_hours = {"LEADER": 12, "SIDEWALKER": 6, "BARN": 3}
    hours = training_hours if training_hours is not None else default_hours[crew_role]
    volunteer = make_volunteer(
        full_name=full_name,
        date_of_birth=date_of_birth,
        last_retraining_on=last_retraining_on,
    )
    qualification = make_qualification(
        volunteer["id"], crew_role=crew_role, training_hours=hours
    )
    if sign_off:
        qualification = sign_off_qualification(qualification["id"], signed_off_on)
    return {
        "volunteer": volunteer,
        "volunteer_id": volunteer["id"],
        "qualification": qualification,
        "qualification_id": qualification["id"],
    }


def make_leader(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "crew_role": "LEADER",
        "full_name": "Lee Leader",
        "date_of_birth": "2000-01-01",
    }
    defaults.update(overrides)
    return make_qualified_volunteer(**defaults)


def make_sidewalker(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "crew_role": "SIDEWALKER",
        "full_name": "Sam Sidewalker",
        "date_of_birth": "2000-02-02",
    }
    defaults.update(overrides)
    return make_qualified_volunteer(**defaults)


# ---------------------------------------------------------------------------
# Tier 3 - session lifecycle shortcuts
# ---------------------------------------------------------------------------


def book_session(
    rider_id: str, horse_id: str, instructor_id: str, acting_instructor_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    caller = acting_instructor_id or instructor_id
    return get_success_data(
        api_client.create_session(
            session_payload(rider_id, horse_id, instructor_id, **overrides),
            make_instructor_headers(caller),
        )
    )


def assign_crew(
    session_id: str,
    volunteer_id: str,
    crew_role: str,
    hold_type: Optional[str] = None,
    expected_session_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Add one crew assignment, refreshing the OCC parent version by default."""
    version = (
        expected_session_version
        if expected_session_version is not None
        else session_version(session_id)
    )
    payload = crew_assignment_payload(volunteer_id, crew_role, version)
    if hold_type is not None:
        payload["hold_type"] = hold_type
    return get_success_data(
        api_client.create_crew_assignment(session_id, payload, COORD)
    )


def confirm_session(session_id: str, instructor_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.confirm_session(session_id, make_instructor_headers(instructor_id))
    )


def complete_session(
    session_id: str,
    instructor_id: str,
    mounted_minutes: int,
    preferred_grant_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"mounted_minutes": mounted_minutes}
    if preferred_grant_id is not None:
        payload["preferred_grant_id"] = preferred_grant_id
    return get_success_data(
        api_client.complete_session(
            session_id, payload, make_instructor_headers(instructor_id)
        )
    )


def cancel_session(
    session_id: str, cancellation_reason: str, instructor_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_session(
            session_id,
            {"cancellation_reason": cancellation_reason},
            make_instructor_headers(instructor_id),
        )
    )


def draft_progress_note(
    session_id: str, instructor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_progress_note(
            session_id,
            progress_note_payload(**overrides),
            make_instructor_headers(instructor_id),
        )
    )


def finalize_progress_note(note_id: str, instructor_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.finalize_progress_note(note_id, make_instructor_headers(instructor_id))
    )


def file_incident(session_id: str, instructor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_incident(
            session_id, incident_payload(**overrides), make_instructor_headers(instructor_id)
        )
    )


# ---------------------------------------------------------------------------
# Read-through helpers
# ---------------------------------------------------------------------------


def charges_for_session(session_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_charges(CLERK, params={"session_id": session_id})
    )


def only_charge_for_session(session_id: str) -> Dict[str, Any]:
    rows = charges_for_session(session_id)
    assert len(rows) == 1, (
        f"Expected exactly one charge for session {session_id}, got {len(rows)}: {rows}"
    )
    return rows[0]


def allocations_for_charge(charge_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_funding_allocations(CLERK, params={"charge_id": charge_id})
    )


def read_charge(charge_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_charge(charge_id, CLERK))


def read_grant(grant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_grant(grant_id, ADMIN))


def read_award(award_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_scholarship_award(award_id, ADMIN))


def read_horse(horse_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_horse(horse_id, ADMIN))


def read_volunteer(volunteer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_volunteer(volunteer_id, COORD))


def read_instructor(instructor_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_instructor(instructor_id, ADMIN))


def read_qualification(qualification_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_qualification(qualification_id, COORD))


def read_goal(goal_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_goal(goal_id, ADMIN))


def read_progress_note(note_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_progress_note(note_id, ADMIN))


def read_incident(incident_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_incident(incident_id, ADMIN))


def read_period_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_period_report(report_id, ADMIN))


def read_release(release_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_medical_release(release_id, ADMIN))


def read_assessment(assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_assessment(assessment_id, ADMIN))


def read_crew_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_crew_assignment(assignment_id, COORD))


# ---------------------------------------------------------------------------
# Tier 4 - the standard centre, and a rider walked to ACTIVE
# ---------------------------------------------------------------------------

DEFAULT_POLICIES = [
    {
        "condition_code": "CP_MILD_ASD",
        "activity_type": "THERAPEUTIC_RIDING",
        "tier": "CLEAR",
        "min_instructor_tier": "REGISTERED",
    }
]
DEFAULT_HORSES = [{"name": "Comet", "body_weight_lb": 1100, "tack_weight_lb": 30}]
DEFAULT_INSTRUCTORS = [
    {
        "full_name": "Ada Reins",
        "certification_level": "MASTER",
        "certification_expires_at": "2028-04-30T00:00:00Z",
    }
]


def setup_centre(
    clock: Optional[str] = LOGICAL_CLOCK_DEFAULT_UTC,
    policies: Optional[List[Dict[str, Any]]] = None,
    horses: Optional[List[Dict[str, Any]]] = None,
    instructors: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Clock + condition policies + horses + instructors, and nothing else."""
    if clock is not None:
        set_clock(clock)
    policy_rows = [
        make_condition_policy(**spec)
        for spec in (DEFAULT_POLICIES if policies is None else policies)
    ]
    horse_rows = [
        make_horse(**spec) for spec in (DEFAULT_HORSES if horses is None else horses)
    ]
    instructor_rows = [
        make_instructor(**spec)
        for spec in (DEFAULT_INSTRUCTORS if instructors is None else instructors)
    ]
    scenario: Dict[str, Any] = {
        "policies": policy_rows,
        "horses": horse_rows,
        "instructors": instructor_rows,
        "horse_ids": [row["id"] for row in horse_rows],
        "instructor_ids": [row["id"] for row in instructor_rows],
    }
    if horse_rows:
        scenario["horse"] = horse_rows[0]
        scenario["horse_id"] = horse_rows[0]["id"]
    if instructor_rows:
        scenario["instructor"] = instructor_rows[0]
        scenario["instructor_id"] = instructor_rows[0]["id"]
        scenario["instructor_headers"] = make_instructor_headers(instructor_rows[0]["id"])
    return scenario


def setup_active_rider(
    clock: Optional[str] = LOGICAL_CLOCK_DEFAULT_UTC,
    policies: Optional[List[Dict[str, Any]]] = None,
    horses: Optional[List[Dict[str, Any]]] = None,
    instructors: Optional[List[Dict[str, Any]]] = None,
    rider: Optional[Dict[str, Any]] = None,
    release: Optional[Dict[str, Any]] = None,
    assessment: Optional[Dict[str, Any]] = None,
    assessing_instructor_index: int = 0,
    file_release_first: bool = True,
    activate: bool = True,
) -> Dict[str, Any]:
    """Walk a rider from registration to ACTIVE on top of `setup_centre`.

    `release=None` files the default 2026-04-01 release; pass `release=False` to
    register a rider with no physician release at all. `assessment=None` files
    the default balance 9 / trunk 9 intake assessment, which lands the rider on
    LEVEL_4; pass `assessment=False` to leave them NEVER_ASSESSED.
    """
    scenario = setup_centre(
        clock=clock, policies=policies, horses=horses, instructors=instructors
    )
    rider_row = make_rider(**(rider or {}))
    scenario["rider"] = rider_row
    scenario["rider_id"] = rider_row["id"]

    assessing_id = scenario["instructor_ids"][assessing_instructor_index]

    if release is not False and file_release_first:
        scenario["release"] = file_release(rider_row["id"], **(release or {}))
        scenario["release_id"] = scenario["release"]["id"]

    if assessment is not False:
        scenario["assessment"] = file_assessment(
            rider_row["id"], assessing_id, **(assessment or {})
        )
        scenario["assessment_id"] = scenario["assessment"]["id"]

    if release is not False and not file_release_first:
        scenario["release"] = file_release(rider_row["id"], **(release or {}))
        scenario["release_id"] = scenario["release"]["id"]

    if activate:
        scenario["rider"] = activate_rider(rider_row["id"])

    return scenario


def setup_level_3_rider(**overrides: Any) -> Dict[str, Any]:
    """An ACTIVE rider assessed balance 6 + trunk 6 = 12, so LEVEL_3.

    PRD 3.1: "A `LEVEL_3` rider needs 1 sidewalker and a leader, using
    `ARM_OVER_THIGH`."
    """
    assessment = {"balance_score": 6, "trunk_control_score": 6}
    assessment.update(overrides.pop("assessment", {}) or {})
    return setup_active_rider(assessment=assessment, **overrides)


def setup_crewed_session(
    scheduled_start: str = "2026-05-11T10:00:00Z",
    duration_minutes: int = 60,
    confirm: bool = True,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """A LEVEL_3 rider's session with a leader and a sidewalker assigned.

    Returns the scenario augmented with `session`, `leader`, `sidewalker`,
    `leader_assignment` and `sidewalker_assignment`.
    """
    scenario = setup_level_3_rider(**scenario_overrides)
    leader = make_leader()
    sidewalker = make_sidewalker()
    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
    )
    leader_assignment = assign_crew(session["id"], leader["volunteer_id"], "LEADER")
    sidewalker_assignment = assign_crew(
        session["id"], sidewalker["volunteer_id"], "SIDEWALKER", hold_type="ARM_OVER_THIGH"
    )
    if confirm:
        session = confirm_session(session["id"], scenario["instructor_id"])
    else:
        session = read_session(session["id"])
    scenario.update(
        {
            "session": session,
            "session_id": session["id"],
            "leader": leader,
            "sidewalker": sidewalker,
            "leader_assignment": leader_assignment,
            "sidewalker_assignment": sidewalker_assignment,
        }
    )
    return scenario


def setup_completed_session(
    mounted_minutes: int = 60,
    scheduled_start: str = "2026-05-11T10:00:00Z",
    duration_minutes: int = 60,
    complete_at_clock: Optional[str] = None,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """A LEVEL_4 rider's session booked, confirmed and completed.

    A LEVEL_4 rider needs no crew at all (PRD 3.4), so the empty crew satisfies
    the requirement and the session confirms with no crew assignments.
    """
    scenario = setup_active_rider(**scenario_overrides)
    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
    )
    confirm_session(session["id"], scenario["instructor_id"])
    if complete_at_clock is not None:
        set_clock(complete_at_clock)
    session = complete_session(
        session["id"], scenario["instructor_id"], mounted_minutes
    )
    scenario.update({"session": session, "session_id": session["id"]})
    return scenario


def setup_charged_session(
    mounted_minutes: int = 45,
    **overrides: Any,
) -> Dict[str, Any]:
    """A completed session plus its charge and that charge's allocation ledger."""
    scenario = setup_completed_session(mounted_minutes=mounted_minutes, **overrides)
    charge = only_charge_for_session(scenario["session_id"])
    scenario["charge"] = charge
    scenario["charge_id"] = charge["id"]
    scenario["allocations"] = allocations_for_charge(charge["id"])
    return scenario


def setup_horse_week_at_240(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Fill the Monday week of 2026-05-11 to exactly 240 committed minutes.

    PRD 3.3: "a week reaches exactly 240 with 150 on Monday and 90 on Tuesday".
    Monday carries a 09:00 booking of 90 minutes and a 10:45 booking of 60
    minutes (a 15-minute rest gap), Tuesday a 09:00 booking of 90 minutes.
    """
    rider_id = scenario["rider_id"]
    horse_id = scenario["horse_id"]
    instructor_id = scenario["instructor_id"]
    monday_first = book_session(
        rider_id,
        horse_id,
        instructor_id,
        scheduled_start="2026-05-11T09:00:00Z",
        duration_minutes=90,
    )
    monday_second = book_session(
        rider_id,
        horse_id,
        instructor_id,
        scheduled_start="2026-05-11T10:45:00Z",
        duration_minutes=60,
    )
    tuesday = book_session(
        rider_id,
        horse_id,
        instructor_id,
        scheduled_start="2026-05-12T09:00:00Z",
        duration_minutes=90,
    )
    scenario.update(
        {
            "monday_first": monday_first,
            "monday_second": monday_second,
            "tuesday": tuesday,
        }
    )
    return scenario

