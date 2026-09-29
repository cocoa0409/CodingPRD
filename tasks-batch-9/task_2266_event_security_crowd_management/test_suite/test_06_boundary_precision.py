"""Inputs chosen so a derived figure lands exactly on a declared threshold.

Every case here is a pair: one input sitting precisely on the boundary and one a
single unit of the retained precision below it. A three-patron change in
attendance moves a score from 50.00 to 49.99 and the whole roster with it; one
extra body in a zone moves a density from 3.999 to 4.000 and freezes the
posture; and one post is the difference between a plan that cannot be published
and one that can.
"""

from test_helpers import (
    ANALYST_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    CrowdProfile,
    DensityLevel,
    GatePosture,
    PlanStatus,
    PostStatus,
    PostType,
    ProtestLikelihood,
    ReadinessPosture,
    RiskTier,
    ThreatLevel,
    World,
    action,
    assert_coverage,
    assert_decimal,
    assert_gate,
    assert_three_decimals,
    build_plan_world,
    build_venue_world,
    density_reading_payload,
    event_payload,
    post_payload,
    risk_assessment_payload,
    set_clock,
    validate_error,
    validate_success,
    zone_payload,
)

BOUNDARY_INPUTS = dict(
    threat_level_input=ThreatLevel.ELEVATED,
    protest_likelihood=ProtestLikelihood.POSSIBLE,
    crowd_profile=CrowdProfile.FAMILY,
    ingress_door_count=1,
    layout_complexity_score=3,
    history_incident_rate=0,
)

DENSITY_CLOCK = "2026-09-12T18:10:00Z"


def _scored(api: ApiClient, expected_attendance: int) -> dict:
    """Score one assessment for the given attendance in a 9000-seat single-door house."""
    world = build_venue_world(api, gross_capacity=9000, door_count=1)
    event = validate_success(
        api.create_event(
            event_payload(
                world.venue_id,
                expected_attendance=expected_attendance,
                vip_present=True,
                alcohol_served=False,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assessment = validate_success(
        api.create_risk_assessment(
            event["id"], risk_assessment_payload(**BOUNDARY_INPUTS), ANALYST_HEADERS
        ),
        expected_status=201,
    )
    return validate_success(
        api.risk_assessment_decision(assessment["id"], action("SUBMIT"), ANALYST_HEADERS)
    )


def test_a_composite_score_of_exactly_fifty_lands_in_the_upper_tier():
    """3000 patrons in a 9000-seat house score exactly 50.00 and buy T3.

    18 points for an ELEVATED picture, 6 for a possible protest, 2 for a family
    crowd, 9 for a layout complexity of 3 and 5 for the protectee detail come to
    40, and a load ratio of one third contributes exactly 10.00 of density
    pressure. The threshold is inclusive at the bottom, so 50.00 is T3.

    PRD: "A score of exactly 50.00 is `T3`, and 49.99 is `T2`."
    Design: Difficulty/boundary_precision_check/risk_tier_boundary_score_exactly_fifty
    """
    api = ApiClient()
    assessment = _scored(api, 3000)

    assert_decimal(assessment["composite_threat_score"], 50.00, "composite_threat_score")
    assert assessment["risk_tier"] == RiskTier.T3
    assert assessment["required_perimeter_guards"] == 4
    assert assessment["required_ingress_guards"] == 3
    assert assessment["required_floor_guards"] == 5
    assert assessment["required_exit_guards"] == 2
    assert assessment["required_line_guards"] == 14
    assert assessment["required_supervisors"] == 2
    assert assessment["required_total_staff"] == 16
    assert assessment["required_screening_lanes"] == 8
    assert assessment["minimum_staffing_cost_floor_cents"] == 115200


def test_one_hundredth_of_a_point_below_the_threshold_drops_the_whole_matrix():
    """Three fewer patrons score 49.99, and the roster falls from 16 staff to 10.

    2997 of 9000 gives a density pressure of 9.99 rather than 10.00, so the
    composite lands one hundredth below the cut and the tier ratio drops from
    4.0 guards per thousand to 2.5. The exit requirement collapses to the venue's
    one-guard-per-door floor, while both screening streams still need 8 lanes.

    PRD: "The **line-guard matrix** starts from a raw line-guard figure: the basis attendance divided by 1000, multiplied by the tier's guard ratio, which is 1.5 guards per thousand for `T1`, 2.5 for `T2`, 4.0 for `T3` and 6.0 for `T4`."
    Design: Difficulty/boundary_precision_check/risk_tier_boundary_score_exactly_fifty
    """
    api = ApiClient()
    assessment = _scored(api, 2997)

    assert_decimal(assessment["composite_threat_score"], 49.99, "composite_threat_score")
    assert assessment["risk_tier"] == RiskTier.T2
    assert assessment["required_perimeter_guards"] == 3
    assert assessment["required_ingress_guards"] == 2
    assert assessment["required_floor_guards"] == 3
    assert assessment["required_exit_guards"] == 1
    assert assessment["required_line_guards"] == 9
    assert assessment["required_supervisors"] == 1
    assert assessment["required_total_staff"] == 10
    assert assessment["required_screening_lanes"] == 8
    assert assessment["minimum_staffing_cost_floor_cents"] == 72000


def _four_zone_world(api: ApiClient) -> World:
    """Two 500 sqm zones and two 1000 sqm zones under one event, clock at 18:10."""
    world = build_venue_world(api)
    for code, area, posted, exits in (
        ("ZS", 500, 600, 8),
        ("ZS2", 500, 600, 8),
        ("ZB", 1000, 1500, 15),
        ("ZB2", 1000, 1500, 15),
    ):
        zone = validate_success(
            api.create_zone(
                world.venue_id,
                zone_payload(
                    zone_code=code,
                    floor_area_sqm=area,
                    posted_capacity=posted,
                    exit_units=exits,
                ),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        setattr(world, code.lower() + "_id", zone["id"])
        assert zone["max_safe_occupancy"] == posted
    event = validate_success(
        api.create_event(event_payload(world.venue_id), DIRECTOR_HEADERS), expected_status=201
    )
    world.event_id = event["id"]
    set_clock(api, DENSITY_CLOCK)
    return world


def test_two_persons_per_square_metre_is_amber_and_a_thousandth_less_is_green():
    """999 patrons in 500 square metres read GREEN; the thousandth body reads AMBER.

    The band edges are inclusive at the bottom, so 1.998 persons per square metre
    stays GREEN while exactly 2.000 crosses into AMBER. Each is the first reading
    for its own zone, so the instantaneous classification is the effective one.

    PRD: "Classification uses inclusive-at-the-bottom thresholds: a density of 4.000 persons per square metre or more is `CRITICAL`; otherwise 3.200 or more is `RED`; otherwise 2.000 or more is `AMBER`; otherwise `GREEN`."
    Design: Difficulty/boundary_precision_check/density_critical_threshold_exactly_four_persons_per_sqm
    """
    api = ApiClient()
    world = _four_zone_world(api)

    below = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zs2_id, "2026-09-12T18:00:00Z", 999),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_three_decimals(below["density_persons_per_sqm"], 1.998)
    assert below["instantaneous_level"] == DensityLevel.GREEN
    assert below["effective_level"] == DensityLevel.GREEN
    assert_three_decimals(below["occupancy_ratio"], 1.665)

    at = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zs_id, "2026-09-12T18:02:00Z", 1000),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_three_decimals(at["density_persons_per_sqm"], 2.000)
    assert at["instantaneous_level"] == DensityLevel.AMBER
    assert at["effective_level"] == DensityLevel.AMBER
    assert_three_decimals(at["occupancy_ratio"], 1.667)


def test_exactly_four_persons_per_square_metre_is_critical_and_restricts_the_gate():
    """3999 patrons in 1000 square metres leave the gate open; 4000 restrict it.

    3.999 persons per square metre is RED, which the posture ladder does not act
    on, so the event stays OPEN. One more body reads exactly 4.000, which is
    CRITICAL, and because the observation is four minutes old against an 18:10
    clock the ladder restricts the gate.

    PRD: "Exactly 4.000 is `CRITICAL` and 3.999 is `RED`."
    Design: Difficulty/boundary_precision_check/density_critical_threshold_exactly_four_persons_per_sqm
    """
    api = ApiClient()
    world = _four_zone_world(api)

    below = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zb2_id, "2026-09-12T18:04:00Z", 3999),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_three_decimals(below["density_persons_per_sqm"], 3.999)
    assert below["instantaneous_level"] == DensityLevel.RED
    assert below["effective_level"] == DensityLevel.RED
    assert_three_decimals(below["occupancy_ratio"], 2.666)
    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.OPEN)

    at = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zb_id, "2026-09-12T18:06:00Z", 4000),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_three_decimals(at["density_persons_per_sqm"], 4.000)
    assert at["instantaneous_level"] == DensityLevel.CRITICAL
    assert at["effective_level"] == DensityLevel.CRITICAL
    assert_three_decimals(at["occupancy_ratio"], 2.667)
    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.RESTRICTED)


def test_publishing_a_plan_with_no_posts_at_all_is_refused():
    """An empty post collection is the boundary case of the non-empty plan rule.

    The plan's budget clears the assessed floor and its assessment is approved,
    so nothing but the missing posts stands in the way. The refusal leaves the
    plan in DRAFT with nothing pinned.

    PRD: "**Non-empty plan** — a publish or an activate requires at least one post on the plan whose `status` is not `CLOSED`, else `ERR_PLAN_HAS_NO_POSTS` (422)."
    Design: Difficulty/boundary_precision_check/publish_with_empty_post_collection
    """
    api = ApiClient()
    world = build_plan_world(api)

    response = api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.PLAN_HAS_NO_POSTS)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.DRAFT
    assert plan["pinned_risk_assessment_version"] is None


def test_one_post_is_enough_to_take_the_same_plan_over_the_line():
    """Adding a single five-slot post turns the same refusal into a publish.

    The one post carries the whole assessed requirement of five staff, so the
    plan is sized correctly and pins the approved assessment at version 3. No
    guard has been booked yet, so coverage is zero and the posture is BLOCKED.

    PRD: "On success the plan becomes `PUBLISHED`, pins `pinned_risk_assessment_version` to the assessment's current `version` so the plan is permanently sized against that snapshot, recomputes the coverage and posture block, and increments `version`."
    Design: Difficulty/boundary_precision_check/publish_with_empty_post_collection
    """
    api = ApiClient()
    world = build_plan_world(api)
    validate_error(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS),
        ApiErrorId.PLAN_HAS_NO_POSTS,
    )

    post = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "P1", PostType.PERIMETER, required_guard_count=5),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )

    published = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )
    assert published["status"] == PlanStatus.PUBLISHED
    assert published["pinned_risk_assessment_version"] == 3
    assert_coverage(published, 5, 0, 0.00, ReadinessPosture.BLOCKED)

    stored_post = validate_success(api.get_post(post["id"], COORDINATOR_HEADERS))
    assert stored_post["status"] == PostStatus.OPEN
