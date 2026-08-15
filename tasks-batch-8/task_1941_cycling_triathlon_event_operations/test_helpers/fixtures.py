"""Composite setup helpers.

The runner re-launches the API server before every test, so each test starts
against an empty database; every fixture below builds its preconditions from
scratch using only PRD-declared endpoints. All helpers use get_success_data
(lenient) so a setup failure surfaces as a clear "Setup step failed" error.

Standard timeline used throughout:
  event start      2026-10-15T08:00:00Z
  closure window   2026-10-15T06:00:00Z .. 2026-10-15T12:00:00Z
  check-in clock   2026-10-14T10:00:00Z (before start, after confirm deadline
                   is irrelevant — check-in only requires clock < start_date)
  race-start clock 2026-10-15T08:00:00Z
Standard chip stream (provisional total 6390 = 900+60+3600+30+1800):
  SWIM 08:15:00, T1 08:16:00, BIKE 09:16:00, T2 09:16:30, FINISH 09:46:30
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_aid_station_payload,
    create_athlete_payload,
    create_event_payload,
    create_permit_payload,
    create_registration_payload,
    create_road_segment_payload,
    create_safety_assessment_payload,
    create_timing_record_payload,
    create_volunteer_assignment_payload,
    create_wave_payload,
)
from .test_users import (
    TEST_USERS,
    make_athlete_headers,
    make_referee_headers,
)

RD = TEST_USERS["race_director_headers"]
PC = TEST_USERS["permit_coordinator_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]
TIMER = TEST_USERS["timer_headers"]

# Standard five-leg chip stream for a full finish.
STANDARD_SPLITS = [
    ("SWIM", "2026-10-15T08:15:00Z"),
    ("T1", "2026-10-15T08:16:00Z"),
    ("BIKE", "2026-10-15T09:16:00Z"),
    ("T2", "2026-10-15T09:16:30Z"),
    ("FINISH", "2026-10-15T09:46:30Z"),
]
STANDARD_PROVISIONAL_TOTAL = 6390  # 900 + 60 + 3600 + 30 + 1800


# ---------------------------------------------------------------------------
# Tier 1: event skeleton / posture progression
# ---------------------------------------------------------------------------

def create_event(**overrides):
    """Create a bare event (DRAFT). Returns the Event dict."""
    return get_success_data(api_client.create_event(create_event_payload(**overrides), RD))


def create_event_with_approved_segment(**event_overrides):
    """Event + one road segment whose permit is SUBMITTED then APPROVED with a
    window fully covering the segment closure. Returns (event, segment, permit)."""
    event = create_event(**event_overrides)
    segment = get_success_data(
        api_client.create_road_segment(event["id"], create_road_segment_payload(), PC))
    permit = get_success_data(
        api_client.create_permit(segment["id"], create_permit_payload(), PC))
    get_success_data(api_client.submit_permit(permit["id"], PC))
    permit = get_success_data(api_client.approve_permit(permit["id"], PC))
    return event, segment, permit


def create_permitted_event(**event_overrides):
    """Event advanced DRAFT -> PERMITTED (permitting gate satisfied)."""
    event, segment, permit = create_event_with_approved_segment(**event_overrides)
    event = get_success_data(api_client.advance_event(event["id"], RD))
    return event


def make_station_ready(event_id, required_volunteers=1, required_water_units=100,
                       location_km=10.0):
    """Create an aid station, confirm enough volunteers, and allocate water so
    the station reports READY. Returns the station dict."""
    station = get_success_data(api_client.create_aid_station(
        event_id,
        create_aid_station_payload(
            location_km=location_km,
            required_volunteers=required_volunteers,
            required_water_units=required_water_units),
        RD))
    for i in range(required_volunteers):
        assignment = get_success_data(api_client.create_volunteer_assignment(
            station["id"],
            create_volunteer_assignment_payload(volunteer_id=f"vol-{i + 1}"),
            VC))
        get_success_data(api_client.confirm_volunteer_assignment(assignment["id"], VC))
    get_success_data(api_client.allocate_water(event_id, RD))
    return get_success_data(api_client.get_aid_station(station["id"], RD))


def create_published_event(num_waves=1, wave_overrides=None, make_station=True,
                           **event_overrides):
    """Event advanced DRAFT -> PERMITTED -> PUBLISHED with `num_waves` OPEN
    waves and (optionally) one READY aid station.

    Returns dict(event=..., waves=[...], station=... or None).
    """
    event = create_permitted_event(**event_overrides)
    waves = []
    overrides_list = wave_overrides or [{} for _ in range(num_waves)]
    for i in range(num_waves):
        ov = dict(overrides_list[i]) if i < len(overrides_list) else {}
        ov.setdefault("label", f"W{i + 1}")
        waves.append(get_success_data(
            api_client.create_wave(event["id"], create_wave_payload(**ov), RD)))
    station = make_station_ready(event["id"]) if make_station else None
    event = get_success_data(api_client.advance_event(event["id"], RD))
    assert event["posture"] == "PUBLISHED", f"setup: event not PUBLISHED: {event}"
    return {"event": event, "waves": waves, "station": station}


# ---------------------------------------------------------------------------
# Tier 2: athletes and registrations inside an event
# ---------------------------------------------------------------------------

def create_athlete(event_id, **overrides):
    return get_success_data(
        api_client.create_athlete(event_id, create_athlete_payload(**overrides), RD))


def create_paid_registration(event_id, **overrides):
    """Athlete + registration + pay. Returns (athlete, registration).

    The registration is created and paid by the athlete themselves
    (ownership-threaded headers)."""
    athlete_fields = {k: v for k, v in overrides.items()
                      if k in ("full_name", "birth_date", "license_number")}
    athlete = create_athlete(event_id, **athlete_fields)
    reg_fields = {k: v for k, v in overrides.items()
                  if k in ("division", "entry_fee_cents")}
    athlete_headers = make_athlete_headers(athlete["id"])
    registration = get_success_data(api_client.create_registration(
        event_id,
        create_registration_payload(athlete_id=athlete["id"], **reg_fields),
        athlete_headers))
    registration = get_success_data(
        api_client.pay_registration(registration["id"], athlete_headers))
    return athlete, registration


def create_confirmed_registration(event_id, **overrides):
    """Athlete + PAID + confirm through the wave selector.
    Returns (athlete, registration)."""
    athlete, registration = create_paid_registration(event_id, **overrides)
    registration = get_success_data(
        api_client.confirm_registration(registration["id"], RD))
    return athlete, registration


# ---------------------------------------------------------------------------
# Tier 3: racing lifecycle (bike check-in, race start, timing, finish)
# ---------------------------------------------------------------------------

def check_in_bike(registration, athlete, bib_code="BIB-1",
                  clock="2026-10-14T10:00:00Z"):
    """Move the logical clock to check-in time and rack the bike.
    Returns the BikeCheck dict."""
    get_success_data(api_client.set_clock(clock, RD))
    return get_success_data(api_client.check_in_bike(
        registration["id"], bib_code, make_athlete_headers(athlete["id"])))


def record_and_validate_splits(registration_id, splits=None):
    """Record + validate each (discipline, recorded_at) pair in order.
    Returns the list of TimingRecord dicts."""
    records = []
    for discipline, recorded_at in (splits or STANDARD_SPLITS):
        record = get_success_data(api_client.create_timing_record(
            registration_id,
            create_timing_record_payload(discipline=discipline,
                                         recorded_at=recorded_at),
            TIMER))
        records.append(get_success_data(
            api_client.validate_timing_record(record["id"], TIMER)))
    return records


def setup_live_race(has_swim=True, num_athletes=1, wave_overrides=None,
                    bib_prefix="BIB", **event_overrides):
    """Full build to LIVE with `num_athletes` registrations RACKED -> RACING.

    Steps: published event (one wave unless overridden) -> athletes paid and
    confirmed -> swim decision SWIM_ON (has_swim only) -> bike check-in for
    each athlete at 2026-10-14T10:00:00Z -> clock to start -> event start.

    Returns dict(event=..., waves=[...], station=...,
                 athletes=[...], registrations=[...], bike_checks=[...]).
    """
    ctx = create_published_event(wave_overrides=wave_overrides,
                                 has_swim=has_swim, **event_overrides)
    event_id = ctx["event"]["id"]
    reg_division = "AGE_GROUP"
    if wave_overrides and wave_overrides[0].get("division"):
        reg_division = wave_overrides[0]["division"]
    athletes, registrations, bike_checks = [], [], []
    for i in range(num_athletes):
        athlete, registration = create_confirmed_registration(
            event_id,
            full_name=f"Athlete {i + 1}",
            birth_date="1990-01-01",
            license_number=f"USAT-{i + 1}",
            division=reg_division,
        )
        athletes.append(athlete)
        registrations.append(registration)
    if has_swim:
        get_success_data(api_client.create_safety_assessment(
            event_id, create_safety_assessment_payload(), RD))
    for i, (athlete, registration) in enumerate(zip(athletes, registrations)):
        bike_checks.append(check_in_bike(registration, athlete,
                                         bib_code=f"{bib_prefix}-{i + 1}"))
    get_success_data(api_client.set_clock("2026-10-15T08:00:00Z", RD))
    ctx["event"] = get_success_data(api_client.start_event(event_id, RD))
    ctx["athletes"] = athletes
    ctx["registrations"] = [
        get_success_data(api_client.get_registration(r["id"], RD))
        for r in registrations
    ]
    ctx["bike_checks"] = bike_checks
    return ctx


def setup_finished_race(has_swim=True, splits=None, **event_overrides):
    """LIVE race with one athlete FINISHED (all five splits validated).
    Returns the setup_live_race context plus 'records'."""
    ctx = setup_live_race(has_swim=has_swim, num_athletes=1, **event_overrides)
    registration = ctx["registrations"][0]
    ctx["records"] = record_and_validate_splits(registration["id"], splits)
    ctx["registrations"][0] = get_success_data(
        api_client.get_registration(registration["id"], RD))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: officiating (penalties, appeals)
# ---------------------------------------------------------------------------

def assess_penalty(registration_id, kind="DRAFTING", referee_id="ref-1",
                   notes=None):
    """Assess a penalty as the given referee. Returns the Penalty dict."""
    payload = {"kind": kind}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_penalty(
        registration_id, payload, make_referee_headers(referee_id)))


def file_appeal(penalty_id, athlete, grounds="appeal grounds"):
    """File an appeal as the penalized athlete. Returns the Appeal dict."""
    return get_success_data(api_client.create_appeal(
        penalty_id, {"grounds": grounds}, make_athlete_headers(athlete["id"])))


def file_appeal_under_review(penalty_id, athlete, reviewer_id="ref-2",
                             grounds="appeal grounds"):
    """Appeal FILED then moved UNDER_REVIEW by the given referee."""
    appeal = file_appeal(penalty_id, athlete, grounds)
    return get_success_data(api_client.begin_review_appeal(
        appeal["id"], make_referee_headers(reviewer_id)))


def get_result_of(registration_id):
    """The single Result of a registration (created at bike check-in)."""
    results = get_success_data(api_client.get_registration_results(registration_id, RD))
    assert isinstance(results, list) and len(results) == 1, (
        f"setup: expected exactly one result for {registration_id}, got {results}")
    return results[0]


def setup_finalized_event(**event_overrides):
    """Full lifecycle through FINALIZED: one athlete FINISHED, event finalized.
    Returns the setup_finished_race context with refreshed event."""
    ctx = setup_finished_race(**event_overrides)
    ctx["event"] = get_success_data(
        api_client.finalize_event(ctx["event"]["id"], RD))
    return ctx
