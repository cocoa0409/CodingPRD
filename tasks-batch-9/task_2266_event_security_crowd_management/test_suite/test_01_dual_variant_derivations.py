"""Derivations that run twice under two different declared bases.

Two families live here. A risk assessment scores the event once on the expected
attendance at submission and again on the ticketed attendance at approval, and
the two passes must land on different tiers and different staffing matrices. A
density reading gates the event on the instantaneous classification while the
zone has fewer than three observations and on the rolling mean once it has
three, so the very same 4.500 spike restricts one zone and not the other.
"""

from test_helpers import (
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    AssessmentStatus,
    AttendanceBasis,
    CrowdProfile,
    DensityLevel,
    EventStatus,
    GatePosture,
    ProtestLikelihood,
    RiskTier,
    ThreatLevel,
    action,
    assert_decimal,
    assert_density_reading,
    assert_gate,
    assert_risk_assessment,
    assert_three_decimals,
    build_event_world,
    build_zoned_venue_world,
    density_reading_payload,
    event_payload,
    read_event_version,
    risk_assessment_payload,
    set_clock,
    validate_success,
)

HIGH_RISK_INPUTS = dict(
    threat_level_input=ThreatLevel.HIGH,
    protest_likelihood=ProtestLikelihood.LIKELY,
    crowd_profile=CrowdProfile.GENERAL_ADMISSION,
    ingress_door_count=1,
    layout_complexity_score=2,
    history_incident_rate=0,
)


def _submitted_assessment(api: ApiClient):
    """Event for 400 expected patrons in an 8000-seat house, assessment submitted."""
    world = build_event_world(api, expected_attendance=400)
    assessment = validate_success(
        api.create_risk_assessment(
            world.event_id, risk_assessment_payload(**HIGH_RISK_INPUTS), ANALYST_HEADERS
        ),
        expected_status=201,
    )
    world.ra_id = assessment["id"]
    world.assessment = validate_success(
        api.risk_assessment_decision(world.ra_id, action("SUBMIT"), ANALYST_HEADERS)
    )
    return world


def test_submission_scores_the_assessment_on_the_expected_attendance_basis():
    """Submission pins the preliminary basis and derives the whole staffing matrix from it.

    400 expected patrons against a gross capacity of 8000 is a load ratio of
    0.05, so the density pressure contributes 1.50 points on top of 30 for a
    HIGH threat, 15 for a LIKELY protest, 10 for general admission and 6 for a
    layout complexity of 2 — a composite of 62.50, which is tier T3.

    PRD: "On submission the assessment sets `attendance_basis` to `EXPECTED` and `score_basis_attendance` to the event's `expected_attendance`, stamps `submitted_by_user_id` with the acting `X-User-ID`, recomputes the whole derived block (`composite_threat_score`, `risk_tier`, `required_perimeter_guards`, `required_ingress_guards`, `required_floor_guards`, `required_exit_guards`, `required_line_guards`, `required_supervisors`, `required_total_staff`, `required_screening_lanes` and `minimum_staffing_cost_floor_cents`) under the preliminary basis, and increments the assessment's `version`."
    Design: Difficulty/dual_variant_calc/threat_score_preliminary_expected_vs_final_ticketed
    """
    api = ApiClient()
    world = _submitted_assessment(api)
    assessment = world.assessment

    assert_risk_assessment(assessment)
    assert assessment["status"] == AssessmentStatus.SUBMITTED
    assert assessment["attendance_basis"] == AttendanceBasis.EXPECTED
    assert assessment["score_basis_attendance"] == 400
    assert_decimal(assessment["composite_threat_score"], 62.50, "composite_threat_score")
    assert assessment["risk_tier"] == RiskTier.T3
    assert assessment["required_line_guards"] == 4
    assert assessment["required_supervisors"] == 1
    assert assessment["required_total_staff"] == 5
    assert assessment["required_screening_lanes"] == 2
    assert assessment["minimum_staffing_cost_floor_cents"] == 36000


def test_approval_switches_the_basis_to_ticketed_and_re_derives_every_requirement():
    """A box-office figure landing between submit and approve moves score, tier and matrix.

    The same analyst inputs re-scored on 3600 ticketed patrons give a load ratio
    of 0.45 and a density pressure of 13.50, so the composite rises to 74.50 and
    the tier to T4. At six guards per thousand the raw line figure is 21.6,
    which splits into 7 perimeter, 6 ingress, 8 floor and 3 exit guards.

    PRD: "Approval performs a **basis switch**: if the event's `ticketed_attendance` is not null, `attendance_basis` becomes `TICKETED` and `score_basis_attendance` becomes that ticketed figure; if it is still null, both keep the `EXPECTED` basis."
    Design: Difficulty/dual_variant_calc/threat_score_preliminary_expected_vs_final_ticketed
    """
    api = ApiClient()
    world = _submitted_assessment(api)

    validate_success(
        api.update_event(
            world.event_id,
            {
                "expected_event_version": read_event_version(api, world.event_id),
                "ticketed_attendance": 3600,
            },
            DIRECTOR_HEADERS,
        )
    )

    approved = validate_success(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_HEADERS)
    )
    assert approved["status"] == AssessmentStatus.APPROVED
    assert approved["attendance_basis"] == AttendanceBasis.TICKETED
    assert approved["score_basis_attendance"] == 3600
    assert_decimal(approved["composite_threat_score"], 74.50, "composite_threat_score")
    assert approved["risk_tier"] == RiskTier.T4
    assert approved["required_perimeter_guards"] == 7
    assert approved["required_ingress_guards"] == 6
    assert approved["required_floor_guards"] == 8
    assert approved["required_exit_guards"] == 3
    assert approved["required_line_guards"] == 24
    assert approved["required_supervisors"] == 3
    assert approved["required_total_staff"] == 27
    assert approved["required_screening_lanes"] == 9
    assert approved["minimum_staffing_cost_floor_cents"] == 194400

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED


def _density_world(api: ApiClient):
    """Two zones under one planning-stage event, logical clock at 18:10."""
    world = build_zoned_venue_world(api)
    event = validate_success(
        api.create_event(event_payload(world.venue_id), DIRECTOR_HEADERS),
        expected_status=201,
    )
    world.event_id = event["id"]
    set_clock(api, "2026-09-12T18:10:00Z")
    return world


def test_third_reading_in_a_zone_switches_the_gate_onto_the_rolling_mean():
    """Two calm observations average a 4.500 spike down to AMBER, leaving the gate open.

    The concourse is 100 square metres, so 100, 150 and then 450 patrons read
    1.000, 1.500 and 4.500 persons per square metre. The third reading is the
    third for that event-and-zone pair, so the rolling mean of 2.333 gates the
    event even though the instantaneous classification is CRITICAL.

    PRD: "Which of the two gates the event is decided by how much history exists: if the count of readings for this event-and-zone pair, counting the one being created, is three or more, then `effective_level` is `rolling_level`; if it is fewer than three, `effective_level` is `instantaneous_level`."
    Design: Difficulty/dual_variant_calc/density_effective_level_instantaneous_vs_rolling_window
    """
    api = ApiClient()
    world = _density_world(api)

    for observed_at, occupancy in (("2026-09-12T17:50:00Z", 100), ("2026-09-12T17:55:00Z", 150)):
        validate_success(
            api.create_density_reading(
                world.event_id,
                density_reading_payload(world.zi_id, observed_at, occupancy),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )

    spike = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zi_id, "2026-09-12T18:00:00Z", 450),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_density_reading(spike)
    assert_three_decimals(spike["density_persons_per_sqm"], 4.500)
    assert spike["instantaneous_level"] == DensityLevel.CRITICAL
    assert_three_decimals(spike["rolling_mean_persons_per_sqm"], 2.333)
    assert spike["rolling_level"] == DensityLevel.AMBER
    assert spike["effective_level"] == DensityLevel.AMBER
    assert_three_decimals(spike["occupancy_ratio"], 3.000)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.OPEN)


def test_first_reading_in_a_zone_gates_the_event_on_the_instantaneous_level():
    """With no history behind it, a single CRITICAL observation restricts the gate at once.

    The floor zone is 200 square metres, so 900 patrons read exactly 4.500
    persons per square metre. It is the first reading for that pair, so the
    instantaneous CRITICAL classification is the effective one and clause 4 of
    the posture ladder picks it up.

    PRD: "Otherwise, if any density reading for this event has `effective_level` equal to `CRITICAL` and an `observed_at` no earlier than 15 minutes before the logical clock, the posture is `RESTRICTED`."
    Design: Difficulty/dual_variant_calc/density_effective_level_instantaneous_vs_rolling_window
    """
    api = ApiClient()
    world = _density_world(api)

    reading = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zf_id, "2026-09-12T18:05:00Z", 900),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_three_decimals(reading["density_persons_per_sqm"], 4.500)
    assert reading["instantaneous_level"] == DensityLevel.CRITICAL
    assert_three_decimals(reading["rolling_mean_persons_per_sqm"], 4.500)
    assert reading["effective_level"] == DensityLevel.CRITICAL
    assert_three_decimals(reading["occupancy_ratio"], 3.000)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.RESTRICTED)
