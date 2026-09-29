"""Derived figures: supervision tiers, engagement, streaks, attainment and outing escorts.

Every test drives the live API over real HTTP. The server is restarted before
each test, so the database starts empty and the logical clock reads exactly
2026-08-01T00:00:00Z; all state below is built through declared endpoints.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId


def test_supervision_tier_takes_the_worse_of_two_axes(api, director, therapist):
    """A resident's supervision tier is the worse of the cognition and function bands,
    so an INTACT resident who is WHEELCHAIR_DEPENDENT lands in TIER_2 while a
    SEVERE_IMPAIRMENT resident who walks independently lands in TIER_3.

    PRD §2.7: "the tier number is the larger of the cognition band and the function band"

    Design: Corner/calculations/supervision_tier_takes_the_worse_of_two_axes
    """
    mobility_driven = fx.create_resident(
        api,
        full_name="Mobility Driven",
        room_number="401A",
        admission_date="2026-07-18",
    )
    cognition_driven = fx.create_resident(
        api,
        full_name="Cognition Driven",
        room_number="401B",
        admission_date="2026-07-18",
    )

    mobility_response = api.create_assessment(
        mobility_driven["id"],
        f.assessment_payload(
            cognitive_level="INTACT",
            functional_mobility="WHEELCHAIR_DEPENDENT",
            interest_domains=["CREATIVE"],
            preferred_group_size="SMALL",
            effective_date="2026-07-18",
        ),
        therapist,
    )
    validate_success(mobility_response, 201)

    cognition_response = api.create_assessment(
        cognition_driven["id"],
        f.assessment_payload(
            cognitive_level="SEVERE_IMPAIRMENT",
            functional_mobility="INDEPENDENT",
            interest_domains=["SPIRITUAL"],
            preferred_group_size="SOLO",
            effective_date="2026-07-18",
        ),
        therapist,
    )
    validate_success(cognition_response, 201)

    mobility_row = fx.read_resident(api, mobility_driven["id"], headers=director)
    cognition_row = fx.read_resident(api, cognition_driven["id"], headers=director)

    assert mobility_row["supervision_tier"] == "TIER_2", (
        "The function band for WHEELCHAIR_DEPENDENT is 2 and beats the cognition "
        f"band 1 for INTACT, got {mobility_row['supervision_tier']!r}"
    )
    assert cognition_row["supervision_tier"] == "TIER_3", (
        "The cognition band for SEVERE_IMPAIRMENT is 3 and beats the function "
        f"band 1 for INDEPENDENT, got {cognition_row['supervision_tier']!r}"
    )
    assert mobility_row["cognitive_level"] == "INTACT"
    assert mobility_row["functional_mobility"] == "WHEELCHAIR_DEPENDENT"


def test_supervision_tier_governing_assessment_is_latest_effective_date(
    api, director, therapist
):
    """The governing assessment is elected by effective_date, not by filing order, so a
    backdated clinical record filed last leaves the tier and the mirrored interests on
    the newer row while the loser is retained and merely labelled superseded.

    PRD §2.7: "rank them by `effective_date` descending and break ties by `created_at` descending"

    Design: Corner/calculations/supervision_tier_governing_assessment_is_latest_effective_date
    """
    resident = fx.create_resident(
        api, full_name="Backdated Bea", room_number="402A", admission_date="2026-07-19"
    )
    newer = fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-25",
    )

    backdated_response = api.create_assessment(
        resident["id"],
        f.assessment_payload(
            cognitive_level="SEVERE_IMPAIRMENT",
            functional_mobility="BEDBOUND",
            interest_domains=["SPIRITUAL"],
            preferred_group_size="SOLO",
            effective_date="2026-07-20",
        ),
        therapist,
    )
    older = validate_success(backdated_response, 201)

    row = fx.read_resident(api, resident["id"], headers=director)
    assert row["supervision_tier"] == "TIER_1", (
        "The 2026-07-25 assessment still governs, so the tier stays TIER_1, got "
        f"{row['supervision_tier']!r}"
    )
    assert row["functional_mobility"] == "INDEPENDENT"
    assert row["interest_domains"] == ["SOCIAL"]

    rows, meta = validate_paginated(
        api.list_assessments(therapist, {"resident_id": resident["id"]})
    )
    assert meta["total_count"] == 2, "The loser of the ranking is retained, not deleted"
    assert {entry["id"] for entry in rows} == {newer["id"], older["id"]}
    assert rows[0]["id"] == newer["id"], "Element zero is the governing assessment"
    assert rows[0]["superseded"] is False
    assert rows[1]["superseded"] is True


def test_engagement_index_rounds_half_up_to_three_decimals(api, director, therapist, aide):
    """A documented refusal stays in the engagement window worth zero points, so one
    PASSIVE_OBSERVER attendance among three documented rows reads 0.083 — the trap is
    0.25, which would wrongly drop both refusals out of the denominator.

    PRD §3.6: "divide by four times the number of records in the window, and round half up to three decimal places"

    Design: Corner/calculations/engagement_index_rounds_half_up_to_three_decimals
    """
    resident = fx.create_resident(
        api, full_name="Precision Pearl", room_number="403A", admission_date="2026-07-20"
    )
    fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-20",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Precision Social",
            "domain": "SOCIAL",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Precision Room", "capacity": 10, "buffer_minutes": 0},
    )
    sessions = fx.hourly_sessions(
        api,
        program["id"],
        room["id"],
        [
            "2026-08-03T09:00:00Z",
            "2026-08-03T10:00:00Z",
            "2026-08-03T11:00:00Z",
        ],
    )
    records = [fx.enroll(api, s["id"], resident["id"], headers=aide) for s in sessions]

    fx.advance_clock(api, "2026-08-03T11:00:00Z")
    for session in sessions:
        fx.start_session(api, session["id"], headers=aide)

    fx.document_attendance(
        api, records[0]["id"], engagement_level="PASSIVE_OBSERVER", headers=aide
    )
    fx.document_refusal(api, records[1]["id"], refusal_reason="FATIGUE", headers=aide)

    response = api.document_participation(
        records[2]["id"], f.refusal_payload(refusal_reason="MOOD"), aide
    )
    validate_success(response, 200)

    row = fx.read_resident(api, resident["id"], headers=director)
    assert row["engagement_index"] == 0.083, (
        "One PASSIVE_OBSERVER point over four times three window members rounds half "
        f"up to 0.083, got {row['engagement_index']!r}"
    )
    assert row["refusal_streak"] == 2, (
        "The two newest rows are refusals and the third is an attendance, got "
        f"{row['refusal_streak']!r}"
    )
    assert row["absence_count"] == 0


def test_refusal_streak_absent_record_interrupts_the_run(api, director, therapist, aide):
    """The refusal streak is the leading run in session-time order, so an absence
    documented last but sitting between two refusals in the calendar cuts the run to
    exactly one — a total refusal count would wrongly read two.

    PRD §3.6: "count one for each consecutive `REFUSED` row and stop at the first row that is anything else"

    Design: Corner/calculations/refusal_streak_absent_record_interrupts_the_run
    """
    resident = fx.create_resident(
        api, full_name="Streak Stanley", room_number="404A", admission_date="2026-07-21"
    )
    fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["COGNITIVE"],
        preferred_group_size="SMALL",
        effective_date="2026-07-21",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Streak Trivia",
            "domain": "COGNITIVE",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Streak Room", "capacity": 10, "buffer_minutes": 0},
    )
    sessions = fx.hourly_sessions(
        api,
        program["id"],
        room["id"],
        [
            "2026-08-04T09:00:00Z",
            "2026-08-04T10:00:00Z",
            "2026-08-04T11:00:00Z",
        ],
    )
    records = [fx.enroll(api, s["id"], resident["id"], headers=aide) for s in sessions]

    fx.advance_clock(api, "2026-08-04T11:00:00Z")
    for session in sessions:
        fx.start_session(api, session["id"], headers=aide)

    # Documented deliberately out of chronological order: newest slot first.
    fx.document_refusal(api, records[2]["id"], refusal_reason="MOOD", headers=aide)
    fx.document_refusal(api, records[0]["id"], refusal_reason="FATIGUE", headers=aide)

    response = api.document_participation(records[1]["id"], f.absence_payload(), aide)
    validate_success(response, 200)

    middle = fx.read_record(api, records[1]["id"], headers=aide)
    assert middle["status"] == "ABSENT"
    assert middle["engagement_level"] is None
    assert middle["refusal_reason"] is None

    row = fx.read_resident(api, resident["id"], headers=director)
    assert row["refusal_streak"] == 1, (
        "The 10:00 absence interrupts the newest-first walk after one refusal, got "
        f"{row['refusal_streak']!r}"
    )
    assert row["absence_count"] == 1
    assert row["engagement_index"] == 0.0, (
        "Only the two refusals enter the window and each scores zero, got "
        f"{row['engagement_index']!r}"
    )


def test_outing_tier3_escort_floor_overrides_the_ratio(api, director, therapist):
    """A single TIER_3 rider weighs 3.0 units, which the ratio alone would cover with one
    escort, but the TIER_3 floor lifts the requirement to two escorts — the floor is a
    maximum applied after the ratio, not a replacement for it.

    PRD §3.8: "`required_escorts` is the larger of that base figure and a floor of 2"

    Design: Corner/calculations/outing_tier3_escort_floor_overrides_the_ratio
    """
    resident = fx.create_resident(
        api, full_name="Floor Fiona", room_number="405A", admission_date="2026-07-22"
    )
    fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="SEVERE_IMPAIRMENT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="SOLO",
        effective_date="2026-07-22",
    )
    program = fx.create_program(
        api,
        name="Floor Outing Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=8,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 11",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Botanic Garden",
        departure_at="2026-08-27T09:00:00Z",
        return_at="2026-08-27T12:00:00Z",
        escort_count=1,
    )
    assert outing["required_escorts"] == 0, "The empty manifest requires no escort"
    assert outing["weighted_supervision_load"] == 0.0

    response = api.create_outing_consent(
        outing["id"],
        f.consent_payload(
            resident["id"],
            responsible_party_name="Floor Family",
            responsible_party_relation="GUARDIAN",
        ),
        director,
    )
    consent = validate_success(response, 201)
    assert consent["status"] == "REQUESTED"

    row = fx.read_outing(api, outing["id"], headers=director)
    assert row["manifest_count"] == 1, "A REQUESTED consent already counts"
    assert row["weighted_supervision_load"] == 3.0, (
        "One TIER_3 rider weighs 3.0 units of supervision load, got "
        f"{row['weighted_supervision_load']!r}"
    )
    assert row["required_escorts"] == 2, (
        "The TIER_3 floor of 2 beats the ceiling of 3.0 divided by 4, got "
        f"{row['required_escorts']!r}"
    )


def test_outing_seat_station_conversion_cap_rejected(api, director, therapist):
    """Spare tie-down stations flip into forward-facing seats only twice, so a bus with
    four idle stations and one free forward seat cannot carry three ambulatory riders
    plus an escort: the booking is refused even though five positions sit empty.

    PRD §3.8: "the number actually converted is the smaller of that surplus and a hard cap of 2 conversions"

    Design: Corner/calculations/outing_seat_station_conversion_cap_rejected
    """
    riders = []
    for full_name, room_number in (
        ("Seat Rider A", "406A"),
        ("Seat Rider B", "406B"),
        ("Seat Rider C", "406C"),
    ):
        rider = fx.create_resident(
            api,
            full_name=full_name,
            room_number=room_number,
            admission_date="2026-07-23",
        )
        fx.file_assessment(
            api,
            rider["id"],
            headers=therapist,
            cognitive_level="INTACT",
            functional_mobility="INDEPENDENT",
            interest_domains=["SOCIAL"],
            preferred_group_size="LARGE",
            effective_date="2026-07-23",
        )
        riders.append(rider)

    program = fx.create_program(
        api,
        name="Seat Cap Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=12,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Lift Van 12",
        ambulatory_seats=1,
        wheelchair_stations=4,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Lakeside Cafe",
        departure_at="2026-08-28T09:00:00Z",
        return_at="2026-08-28T12:00:00Z",
        escort_count=1,
    )
    for rider, relation in zip(riders, ("SPOUSE", "ADULT_CHILD", "GUARDIAN")):
        fx.add_rider(
            api,
            outing["id"],
            rider["id"],
            headers=director,
            responsible_party_relation=relation,
        )

    observed_version = fx.vehicle_version(api, vehicle["id"])
    response = api.book_transport(
        outing["id"], {"expected_vehicle_version": observed_version}, director
    )
    validate_error(response, ApiErrorId.VEHICLE_CAPACITY_EXCEEDED.value, 409)

    outing_row = fx.read_outing(api, outing["id"], headers=director)
    assert outing_row["logistics_status"] == "PLANNING"

    vehicle_row = fx.read_vehicle(api, vehicle["id"], headers=director)
    assert vehicle_row["reserved_ambulatory_seats"] == 0
    assert vehicle_row["reserved_wheelchair_stations"] == 0
    assert vehicle_row["version"] == observed_version, (
        "A rejected booking reserves nothing and advances no version"
    )


def test_plan_attainment_caps_each_domain_before_averaging(api, director, therapist, aide):
    """Over-delivering one domain cannot subsidise an untouched one: SOCIAL targeted once
    and attended twice contributes a single whole unit, PHYSICAL targeted twice with
    nothing delivered contributes zero, and the plan reads 50.0 rather than 100.0.

    PRD §3.3: "cap each domain's ratio first, then average, then round exactly once at the end"

    Design: Corner/calculations/plan_attainment_caps_each_domain_before_averaging
    """
    resident = fx.create_resident(
        api, full_name="Cap Carla", room_number="407A", admission_date="2026-07-24"
    )
    assessment = fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL", "PHYSICAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-24",
    )
    plan = fx.active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=1, physical=2),
        cycle_start_at="2026-08-01T00:00:00Z",
    )
    assert plan["target_total_sessions"] == 3, (
        "target_total_sessions is the arithmetic sum of the five targets, got "
        f"{plan['target_total_sessions']!r}"
    )

    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Cap Social Hour",
            "domain": "SOCIAL",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Cap Room", "capacity": 10, "buffer_minutes": 0},
    )
    sessions = fx.hourly_sessions(
        api,
        program["id"],
        room["id"],
        ["2026-08-04T09:00:00Z", "2026-08-04T10:00:00Z"],
    )
    records = [fx.enroll(api, s["id"], resident["id"], headers=aide) for s in sessions]

    fx.advance_clock(api, "2026-08-04T10:00:00Z")
    for session in sessions:
        fx.start_session(api, session["id"], headers=aide)

    fx.document_attendance(api, records[0]["id"], engagement_level="ACTIVE", headers=aide)
    response = api.document_participation(
        records[1]["id"], f.attendance_payload(engagement_level="ACTIVE"), aide
    )
    validate_success(response, 200)

    row = fx.read_plan(api, plan["id"], headers=therapist)
    assert row["credited_attainment_pct"] == 50.0, (
        "One capped SOCIAL unit and a zero PHYSICAL unit average to 50.0, got "
        f"{row['credited_attainment_pct']!r}"
    )
    assert row["offered_attainment_pct"] == 50.0
    assert row["status"] == "ACTIVE"
    assert row["review_reason"] == "NONE"


def test_plan_attainment_excludes_sessions_outside_the_cycle_window(
    api, director, therapist, aide
):
    """The 28-day measurement window is half-open, so a session starting exactly at the
    window's closing instant scores the plan nothing while one an hour earlier scores
    the domain in full — and the resident's engagement index counts both regardless.

    PRD §2.5: "runs from `cycle_start_at` inclusive to the instant 28 days later, exclusive"

    Design: Corner/calculations/plan_attainment_excludes_sessions_outside_the_cycle_window
    """
    resident = fx.create_resident(
        api, full_name="Window Wilma", room_number="408A", admission_date="2026-07-25"
    )
    assessment = fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-25",
    )
    plan = fx.active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=1),
        cycle_start_at="2026-08-01T00:00:00Z",
    )

    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Window Social",
            "domain": "SOCIAL",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Window Room", "capacity": 10, "buffer_minutes": 0},
    )
    inside = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-28T23:00:00Z",
        ends_at="2026-08-28T23:45:00Z",
    )
    outside = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-29T00:00:00Z",
        ends_at="2026-08-29T00:45:00Z",
    )
    inside_record = fx.enroll(api, inside["id"], resident["id"], headers=aide)
    outside_record = fx.enroll(api, outside["id"], resident["id"], headers=aide)

    fx.advance_clock(api, "2026-08-29T00:30:00Z")
    fx.start_session(api, inside["id"], headers=aide)
    fx.start_session(api, outside["id"], headers=aide)

    fx.document_attendance(
        api, outside_record["id"], engagement_level="ACTIVE", headers=aide
    )
    mid_row = fx.read_plan(api, plan["id"], headers=therapist)
    assert mid_row["credited_attainment_pct"] == 0.0, (
        "The 2026-08-29T00:00:00Z session sits on the exclusive edge of the window, got "
        f"{mid_row['credited_attainment_pct']!r}"
    )

    response = api.document_participation(
        inside_record["id"], f.attendance_payload(engagement_level="ACTIVE"), aide
    )
    validate_success(response, 200)

    row = fx.read_plan(api, plan["id"], headers=therapist)
    assert row["credited_attainment_pct"] == 100.0, (
        "The 2026-08-28T23:00:00Z session is inside the window and fills the only "
        f"scored domain, got {row['credited_attainment_pct']!r}"
    )
    assert row["offered_attainment_pct"] == 100.0

    resident_row = fx.read_resident(api, resident["id"], headers=director)
    assert resident_row["engagement_index"] == 0.75, (
        "Both ACTIVE attendances enter the engagement window regardless of the plan "
        f"cycle, giving six points over eight, got {resident_row['engagement_index']!r}"
    )
