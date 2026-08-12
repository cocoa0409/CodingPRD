"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so every test
starts against an empty database). Setup calls use get_success_data() so
failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_season_payload,
    create_pass_holder_payload,
    create_pass_payload,
    create_admission_payload,
    create_lesson_level_payload,
    create_lesson_session_payload,
    create_enrollment_payload,
    create_lifeguard_payload,
    create_chemistry_log_payload,
    create_lane_allocation_payload,
    create_rental_payload,
    create_incident_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_lifeguard_headers,
    make_passholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


# --- Tier 0: primitives -------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock (PRD §2.6)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER)
    )


def make_facility(**overrides) -> dict:
    """Create a Facility. Returns the facility resource."""
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), MANAGER)
    )


def make_season(facility_id, publish=True, **overrides) -> dict:
    """Create a MembershipSeason; publishes it by default."""
    season = get_success_data(
        api_client.create_season(
            create_season_payload(facility_id, **overrides), MANAGER
        )
    )
    if publish:
        season = get_success_data(api_client.publish_season(season["id"], MANAGER))
    return season


def make_pass_holder(**overrides) -> dict:
    """Register a PassHolder."""
    return get_success_data(
        api_client.create_pass_holder(
            create_pass_holder_payload(**overrides), GATE
        )
    )


def make_lifeguard(**overrides) -> dict:
    """Register a Lifeguard (cert ACTIVE assuming cert_expires_on in future)."""
    return get_success_data(
        api_client.create_lifeguard(create_lifeguard_payload(**overrides), MANAGER)
    )


def make_season_pass(pass_holder_id, season_id) -> dict:
    """Purchase a SeasonPass against a PUBLISHED season."""
    return get_success_data(
        api_client.create_pass(
            create_pass_payload(pass_holder_id, season_id), GATE
        )
    )


def make_lesson_level(**overrides) -> dict:
    return get_success_data(
        api_client.create_lesson_level(
            create_lesson_level_payload(**overrides), MANAGER
        )
    )


def make_chemistry_log(facility_id, lifeguard_id, **overrides) -> dict:
    """Record a ChemistryLog as the given lifeguard (identity-threaded)."""
    return get_success_data(
        api_client.create_chemistry_log(
            facility_id,
            create_chemistry_log_payload(lifeguard_id, **overrides),
            make_lifeguard_headers(lifeguard_id),
        )
    )


def get_facility(facility_id) -> dict:
    return get_success_data(api_client.get_facility(facility_id, MANAGER))


def facility_version(facility_id) -> int:
    return get_facility(facility_id)["version"]


# --- Tier 1: facility + season ------------------------------------------

def setup_facility_with_season(clock="2026-07-01T00:00:00Z",
                               facility_overrides=None,
                               season_overrides=None):
    """Facility + PUBLISHED season, clock advanced. Returns (facility, season)."""
    facility = make_facility(**(facility_overrides or {}))
    season = make_season(facility["id"], **(season_overrides or {}))
    set_clock(clock)
    return get_facility(facility["id"]), season


# --- Tier 2: admissions ---------------------------------------------------

def make_admission(facility_id, pass_holder_id, admission_date, **overrides) -> dict:
    """Issue a DailyAdmission."""
    return get_success_data(
        api_client.create_admission(
            create_admission_payload(
                facility_id, pass_holder_id, admission_date, **overrides
            ),
            GATE,
        )
    )


def setup_admission_entered(clock_date="2026-07-15", enter_time="10:00:00",
                            facility_overrides=None, season_overrides=None,
                            holder_overrides=None):
    """Facility + PUBLISHED season + holder + admission ENTERED at enter_time.

    Returns (facility, season, holder, admission).
    """
    facility, season = setup_facility_with_season(
        clock=f"{clock_date}T09:55:00Z",
        facility_overrides=facility_overrides,
        season_overrides=season_overrides,
    )
    holder = make_pass_holder(**(holder_overrides or {}))
    admission = make_admission(
        facility["id"], holder["id"], f"{clock_date}T00:00:00Z"
    )
    set_clock(f"{clock_date}T{enter_time}Z")
    admission = get_success_data(api_client.enter_admission(admission["id"], GATE))
    return get_facility(facility["id"]), season, holder, admission


# --- Tier 2: lessons ------------------------------------------------------

def setup_scheduled_lesson_session(clock="2026-06-15T00:00:00Z",
                                   facility_overrides=None,
                                   season_overrides=None,
                                   level_overrides=None,
                                   session_overrides=None):
    """Facility + PUBLISHED season + level + SCHEDULED LessonSession.

    Returns (facility, season, level, session). Handles the OCC guard on
    schedule by reading the live facility version.
    """
    facility, season = setup_facility_with_season(
        clock=clock,
        facility_overrides=facility_overrides,
        season_overrides=season_overrides,
    )
    level = make_lesson_level(**(level_overrides or {}))
    session = get_success_data(
        api_client.create_lesson_session(
            create_lesson_session_payload(
                facility["id"], level["id"], season["id"],
                **(session_overrides or {}),
            ),
            MANAGER,
        )
    )
    fv = facility_version(facility["id"])
    session = get_success_data(
        api_client.schedule_lesson_session(
            session["id"], {"expected_facility_version": fv}, MANAGER
        )
    )
    return get_facility(facility["id"]), season, level, session


def make_enrollment(session_id, pass_holder_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(session_id, pass_holder_id, **overrides),
            GATE,
        )
    )


# --- Tier 2: rentals ------------------------------------------------------

def make_rental(facility_id, pass_holder_id, **overrides) -> dict:
    """Create a REQUESTED FacilityRental as the renting patron."""
    holder_id = overrides.get("pass_holder_id", pass_holder_id)
    payload = create_rental_payload(facility_id, pass_holder_id, **overrides)
    return get_success_data(
        api_client.create_rental(payload, make_passholder_headers(holder_id))
    )


def approve_rental(rental_id, facility_id) -> dict:
    """Approve a rental, reading the live facility version for the OCC guard."""
    fv = facility_version(facility_id)
    return get_success_data(
        api_client.approve_rental(
            rental_id, {"expected_facility_version": fv}, MANAGER
        )
    )


def setup_rental_approved(clock="2026-07-01T00:00:00Z",
                          facility_overrides=None,
                          holder_overrides=None,
                          rental_overrides=None):
    """Facility + holder + APPROVED rental. Returns (facility, holder, rental)."""
    facility = make_facility(**(facility_overrides or {"lap_lane_count": 0}))
    holder = make_pass_holder(**(holder_overrides or {}))
    set_clock(clock)
    rental = make_rental(facility["id"], holder["id"], **(rental_overrides or {}))
    rental = approve_rental(rental["id"], facility["id"])
    return get_facility(facility["id"]), holder, rental


# --- Tier 2: incidents ------------------------------------------------------

def setup_submitted_incident(severity="MINOR", clock="2026-06-15T12:00:00Z",
                             incident_type="RULE_VIOLATION",
                             facility_overrides=None):
    """Facility + holder + ACTIVE-cert lifeguard + SUBMITTED IncidentReport.

    Returns (facility, holder, lifeguard, report).
    """
    facility = make_facility(**(facility_overrides or {}))
    holder = make_pass_holder()
    lifeguard = make_lifeguard()
    set_clock(clock)
    report = get_success_data(
        api_client.create_incident_report(
            create_incident_report_payload(
                facility["id"], lifeguard["id"], holder["id"],
                incident_type=incident_type, severity=severity,
                occurred_at=clock,
            ),
            make_lifeguard_headers(lifeguard["id"]),
        )
    )
    report = get_success_data(
        api_client.submit_incident_report(
            report["id"], make_lifeguard_headers(lifeguard["id"])
        )
    )
    return get_facility(facility["id"]), holder, lifeguard, report


# --- Tier 3: closures -------------------------------------------------------

def make_weather_closure(facility_id, started_at) -> dict:
    """Declare a WEATHER closure (manager)."""
    return get_success_data(
        api_client.create_closure(
            facility_id,
            {"closure_reason": "WEATHER", "started_at": started_at},
            MANAGER,
        )
    )


def setup_chemistry_closed_facility(clock="2026-06-15T10:00:00Z"):
    """Facility pushed to CLOSED_CHEMISTRY by a single OUT_OF_RANGE log.

    Returns (facility, lifeguard, chemistry_log).
    """
    facility = make_facility()
    lifeguard = make_lifeguard()
    set_clock(clock)
    log = make_chemistry_log(
        facility["id"], lifeguard["id"],
        recorded_at=clock, free_chlorine_ppm=0.5, ph=7.5,
        combined_chlorine_ppm=0.2,
    )
    return get_facility(facility["id"]), lifeguard, log
