"""Walking route hazard arithmetic and the three gates that guard publication.

A route's hazard score is frozen at creation by a rounding order the PRD pins
explicitly, and publication then runs a warrant gate, a hazard ceiling and an
ownership check in a declared sequence. These tests pin the arithmetic, the
ceiling's inclusive edge, and which gate speaks first when one segment breaks
two rules at once.
"""
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant, assert_walking_route
from test_helpers.factories import route_segment
from test_helpers.fixtures import (
    create_intersection,
    create_school,
    draft_route,
    read_route,
    read_school,
    setup_warranted_intersection,
)
from test_helpers.test_users import make_school_liaison_headers

# 1.25 * 133 / 100 = 1.6625, which rounds to 1.66 on the segment alone.
THREE_SIDEWALK_GAPS = [
    route_segment(1, "NO_SIDEWALK", 133),
    route_segment(2, "NO_SIDEWALK", 133),
    route_segment(3, "NO_SIDEWALK", 133),
]


def test_per_segment_rounding_is_applied_before_the_segments_are_summed(api):
    """Three 133 ft sidewalk gaps, a 60 ft uncontrolled crossing and a mitigated
    rail crossing sum to 7.08 under the pinned order, not 7.09.

    PRD: "Those already-rounded per-segment values are then summed, and the sum
    is rounded half up to two decimal places to give `hazard_score`."

    Design: Difficulty/combinatorial_formula/route_hazard_rounds_per_segment_before_summing
    """
    scenario = setup_warranted_intersection()

    route = draft_route(
        scenario["school"]["id"],
        THREE_SIDEWALK_GAPS + [
            route_segment(4, "UNCONTROLLED_CROSSING", 60,
                          intersection_id=scenario["intersection"]["id"]),
            route_segment(5, "RAIL_CROSSING", 80, mitigated=True),
        ],
        route_name="North approach via Maple")

    assert_walking_route(route)
    assert route["hazard_score"] == 7.08
    assert route["hazard_score"] != 7.09
    assert route["segment_count"] == 5
    assert route["status"] == "DRAFT"
    assert route["published_at"] is None
    assert route["hold_reason"] is None


def test_a_mitigated_segment_contributes_nothing_yet_is_still_counted(api):
    """The PRD's own worked example lands on 4.98, and dropping the mitigated rail
    crossing changes the segment count without moving the score.

    PRD: "Rounding twice is deliberate: three unmitigated `NO_SIDEWALK` segments
    of 133 feet each contribute 1.6625 raw, which rounds to 1.66 per segment and
    sums to 4.98, whereas summing raw values and rounding once would give 4.99."
    ... "A segment whose `mitigated` is true contributes exactly 0.00 and is still
    traversed, so it does not shift the ordering of the others."

    Design: Difficulty/combinatorial_formula/route_hazard_rounds_per_segment_before_summing
    """
    scenario = setup_warranted_intersection()
    school_id = scenario["school"]["id"]
    crossing = route_segment(4, "UNCONTROLLED_CROSSING", 60,
                             intersection_id=scenario["intersection"]["id"])

    sidewalks_only = draft_route(school_id, THREE_SIDEWALK_GAPS,
                                route_code="RT-WALK")
    with_rail = draft_route(school_id,
                            THREE_SIDEWALK_GAPS + [
                                crossing,
                                route_segment(5, "RAIL_CROSSING", 80,
                                              mitigated=True)],
                            route_code="RT-RAIL")
    without_rail = draft_route(school_id, THREE_SIDEWALK_GAPS + [crossing],
                               route_code="RT-BARE")

    assert sidewalks_only["hazard_score"] == 4.98
    assert sidewalks_only["hazard_score"] != 4.99
    assert sidewalks_only["segment_count"] == 3
    assert with_rail["hazard_score"] == 7.08
    assert without_rail["hazard_score"] == 7.08
    assert with_rail["segment_count"] == 5
    assert without_rail["segment_count"] == 4


def test_a_hazard_score_of_exactly_the_ceiling_publishes(api):
    """A single unmitigated 625 ft rail crossing scores exactly 25.00, and the
    comparison is inclusive.

    PRD: "Second, the hazard ceiling: `hazard_score` must be at most 25.00, and
    equality publishes; above it the refusal is `ERR_ROUTE_HAZARD_SCORE_EXCEEDED`
    (HTTP 422)." ... "On successful publication the route moves `DRAFT →
    PUBLISHED` and `published_at` is stamped from the logical clock."

    Design: Difficulty/boundary_precision_check/route_hazard_score_exactly_at_publish_ceiling_publishes
    """
    school = create_school()
    assert read_school(school["id"])["coverage_posture"] == "OPEN"
    route = draft_route(school["id"], [route_segment(1, "RAIL_CROSSING", 625)],
                        route_code="RT-CEILING")
    assert route["hazard_score"] == 25.00

    published = validate_success(api.publish_walking_route(
        route["id"], make_school_liaison_headers(school["id"])))

    assert_walking_route(published)
    assert published["status"] == "PUBLISHED"
    assert_same_instant(published["published_at"], "2026-08-01T00:00:00Z",
                        "WalkingRoute.published_at")
    assert published["hold_reason"] is None
    assert published["hazard_score"] == 25.00
    assert published["version"] == route["version"] + 1


def test_a_hazard_score_just_over_the_ceiling_is_refused(api):
    """700 ft of the same hazard scores 28.00 and the publish attempt is rejected
    with the route left untouched in DRAFT.

    PRD: "Each hazard type carries a weight per hundred feet: `NO_SIDEWALK` 1.25,
    `UNCONTROLLED_CROSSING` 3.50, `HIGH_SPEED_ARTERIAL` 2.75, `RAIL_CROSSING`
    4.00, `DRIVEWAY_CONFLICT` 0.85 and `POOR_LIGHTING` 0.60."

    Design: Difficulty/boundary_precision_check/route_hazard_score_exactly_at_publish_ceiling_publishes
    """
    school = create_school()
    route = draft_route(school["id"], [route_segment(1, "RAIL_CROSSING", 700)],
                        route_code="RT-OVER")
    assert route["hazard_score"] == 28.00

    response = api.publish_walking_route(
        route["id"], make_school_liaison_headers(school["id"]))

    validate_error(response, ApiErrorId.ERR_ROUTE_HAZARD_SCORE_EXCEEDED.value, 422)
    after = read_route(route["id"])
    assert after["status"] == "DRAFT"
    assert after["published_at"] is None
    assert after["version"] == route["version"]


def _route_citing_another_schools_intersection(other_intersection_id: str):
    """A DRAFT route owned by Maple Grove whose first segment is an unmitigated
    uncontrolled crossing at an intersection belonging to a different school."""
    school = create_school()
    route = draft_route(
        school["id"],
        [route_segment(1, "UNCONTROLLED_CROSSING", 60,
                       intersection_id=other_intersection_id),
         route_segment(2, "NO_SIDEWALK", 133)],
        route_code="RT-SHARED")
    return school, route


def test_the_warrant_gate_answers_before_the_ownership_check(api):
    """One segment breaks two publish rules at once — an unstudied crossing that
    also belongs to another school — and the safety gate wins.

    PRD: "Because this third gate sits after the first, a route with both faults
    reports the warrant failure, not the ownership failure."

    Design: Difficulty/priority_pair_validation_conflict/unwarranted_crossing_beats_out_of_district_segment_at_publish
    """
    other_school = create_school(name="Birch Hollow Elementary")
    other_intersection = create_intersection(other_school["id"],
                                             cross_streets="Birch St & 4th Ave")
    assert other_intersection["warrant_status"] == "NOT_STUDIED"
    school, route = _route_citing_another_schools_intersection(
        other_intersection["id"])
    assert route["status"] == "DRAFT"
    assert route["hazard_score"] == 3.76

    response = api.publish_walking_route(
        route["id"], make_school_liaison_headers(school["id"]))

    error = validate_error(
        response, ApiErrorId.ERR_ROUTE_CROSSING_NOT_WARRANTED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_ROUTE_SEGMENT_SCHOOL_MISMATCH.value
    assert error["error_id"] != ApiErrorId.ERR_ROUTE_HAZARD_SCORE_EXCEEDED.value
    after = read_route(route["id"])
    assert after["status"] == "DRAFT"
    assert after["published_at"] is None
    assert after["version"] == route["version"]


def test_the_ownership_check_surfaces_once_the_crossing_is_warranted(api):
    """With the warrant gate satisfied the identical publish attempt finally
    reports the ownership fault, which is what makes the ordering observable.

    PRD: "Third and last, the ownership consistency check that was deliberately
    skipped at draft time: every non-null `intersection_id` in `segments` must
    reference an intersection whose `school_id` equals the route's `school_id`, or
    the refusal is `ERR_ROUTE_SEGMENT_SCHOOL_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/unwarranted_crossing_beats_out_of_district_segment_at_publish
    """
    other = setup_warranted_intersection(name="Birch Hollow Elementary",
                                         cross_streets="Birch St & 4th Ave")
    assert other["intersection"]["warrant_status"] == "WARRANTED"
    school, route = _route_citing_another_schools_intersection(
        other["intersection"]["id"])
    assert route["hazard_score"] == 3.76

    response = api.publish_walking_route(
        route["id"], make_school_liaison_headers(school["id"]))

    error = validate_error(
        response, ApiErrorId.ERR_ROUTE_SEGMENT_SCHOOL_MISMATCH.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_ROUTE_CROSSING_NOT_WARRANTED.value
    after = read_route(route["id"])
    assert after["status"] == "DRAFT"
    assert after["published_at"] is None
