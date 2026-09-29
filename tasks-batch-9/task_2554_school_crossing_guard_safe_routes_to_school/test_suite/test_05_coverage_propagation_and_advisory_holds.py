"""Coverage propagation from one absence all the way out to a walking route.

Filing a single absence report walks four links: the assignment opens a gap, the
post falls uncovered, the school recomputes its posture, and a suspended posture
puts the school's published routes on advisory hold. Withdrawing the report runs
every link in reverse.
"""
from test_helpers import validate_success
from test_helpers.assertions import (
    assert_absence_report,
    assert_same_instant,
    assert_school,
    assert_school_coverage_partition,
    assert_walking_route,
)
from test_helpers.factories import route_segment
from test_helpers.fixtures import (
    advance_clock,
    draft_route,
    file_absence,
    read_absence,
    read_assignment,
    read_guard,
    read_post,
    read_route,
    read_school,
    rescind,
    setup_published_route,
    setup_staffed_post,
    add_second_post_and_guard,
)
from test_helpers.test_users import make_school_liaison_headers

ABSENCE_DAY = "2026-09-16"
DUTY_CLOCK = "2026-09-16T01:00:00Z"


def test_filing_one_absence_opens_a_gap_that_suspends_the_school(api):
    """Links one through three of the propagation chain: assignment, post, school.

    PRD: "the parent assignment's `open_absence_count` increments by 1 and its
    `coverage_state` becomes `GAP`; the post's `open_gap_count` increments by 1
    and its `coverage_status` becomes `UNCOVERED`; the school's
    `covered_post_count`, `uncovered_post_count`, `coverage_rate_pct` and
    `coverage_posture` are recomputed".

    Design: Difficulty/transitive_cascade/absence_create_depth4_cascade_to_route_advisory_hold
    """
    scenario = setup_staffed_post()
    setup_published_route(scenario["school"]["id"])
    advance_clock(DUTY_CLOCK)
    assert read_post(scenario["post"]["id"])["coverage_status"] == "COVERED"
    before = read_school(scenario["school"]["id"])
    assert before["coverage_posture"] == "OPEN"
    assert before["coverage_rate_pct"] == 100.00

    report = file_absence(scenario["assignment"]["id"], absence_date=ABSENCE_DAY)

    assert_absence_report(report)
    assert report["status"] == "DISPATCH_PENDING"
    assert report["shift"] == "AM"
    assignment = read_assignment(scenario["assignment"]["id"])
    assert assignment["open_absence_count"] == 1
    assert assignment["coverage_state"] == "GAP"
    post = read_post(scenario["post"]["id"])
    assert post["open_gap_count"] == 1
    assert post["coverage_status"] == "UNCOVERED"
    school = read_school(scenario["school"]["id"])
    assert_school(school)
    assert school["active_post_count"] == 1
    assert school["covered_post_count"] == 0
    assert school["uncovered_post_count"] == 1
    assert school["coverage_rate_pct"] == 0.00
    assert school["coverage_posture"] == "SUSPENDED"


def test_a_suspended_posture_puts_the_published_route_on_advisory_hold(api):
    """Link four reaches a route that holds no reference to the absence at all.

    PRD: "and if the school thereby enters `SUSPENDED`, every `PUBLISHED` walking
    route of that school moves to `ADVISORY_HOLD` with `hold_reason` set to
    `SCHOOL_COVERAGE_SUSPENDED`."

    Design: Difficulty/transitive_cascade/absence_create_depth4_cascade_to_route_advisory_hold
    """
    scenario = setup_staffed_post()
    route = setup_published_route(scenario["school"]["id"])
    advance_clock(DUTY_CLOCK)
    assert read_route(route["id"])["status"] == "PUBLISHED"

    file_absence(scenario["assignment"]["id"], absence_date=ABSENCE_DAY)

    held = read_route(route["id"])
    assert_walking_route(held)
    assert held["status"] == "ADVISORY_HOLD"
    assert held["hold_reason"] == "SCHOOL_COVERAGE_SUSPENDED"
    guard = read_guard(scenario["guard"]["id"])
    assert guard["reliability_score_rolling_90d"] == 99.00
    assert guard["reliability_score_season_to_date"] == 100.00
    assert guard["certification_status"] == "CERTIFIED"
    assert read_assignment(scenario["assignment"]["id"])["status"] == "ACTIVE"


def _school_with_two_staffed_posts():
    scenario = setup_staffed_post()
    second = add_second_post_and_guard(scenario, post_label="Maple SE corner",
                                       guard_name="Tomas Reyes")
    advance_clock(DUTY_CLOCK)
    return scenario, second


def test_the_post_partition_holds_as_two_absences_open(api):
    """Exactly half the posts covered is RESTRICTED, and the partition of active
    posts into covered and uncovered holds at every step.

    PRD: "the partition invariant that `active_post_count` equals
    `covered_post_count` plus `uncovered_post_count` holds at every observable
    instant" ... "A rate of exactly 50.00 is `RESTRICTED`, not `SUSPENDED`."

    Design: Difficulty/compensating_invariant/post_coverage_partition_conserved_across_absence_and_rescind
    """
    scenario, second = _school_with_two_staffed_posts()
    school_id = scenario["school"]["id"]
    first_observation = read_school(school_id)
    assert_school_coverage_partition(first_observation)
    assert first_observation["active_post_count"] == 2
    assert first_observation["covered_post_count"] == 2
    assert first_observation["uncovered_post_count"] == 0
    assert first_observation["coverage_rate_pct"] == 100.00
    assert first_observation["coverage_posture"] == "OPEN"

    file_absence(scenario["assignment"]["id"], absence_date=ABSENCE_DAY)
    second_observation = read_school(school_id)
    assert_school_coverage_partition(second_observation)
    assert second_observation["covered_post_count"] == 1
    assert second_observation["uncovered_post_count"] == 1
    assert second_observation["coverage_rate_pct"] == 50.00
    assert second_observation["coverage_posture"] == "RESTRICTED"
    assert second_observation["coverage_posture"] != "SUSPENDED"

    file_absence(second["assignment"]["id"], absence_date=ABSENCE_DAY,
                 reason="FAMILY")
    third_observation = read_school(school_id)
    assert_school_coverage_partition(third_observation)
    assert third_observation["covered_post_count"] == 0
    assert third_observation["uncovered_post_count"] == 2
    assert third_observation["coverage_rate_pct"] == 0.00
    assert third_observation["coverage_posture"] == "SUSPENDED"
    assert third_observation["active_post_count"] == 2


def test_withdrawing_both_absences_restores_the_partition_exactly(api):
    """Withdrawal is the compensating action, and it puts every counter back.

    PRD: "the school's counters, `coverage_rate_pct` and `coverage_posture` are
    restored to their pre-report values".

    Design: Difficulty/compensating_invariant/post_coverage_partition_conserved_across_absence_and_rescind
    """
    scenario, second = _school_with_two_staffed_posts()
    school_id = scenario["school"]["id"]
    absence_a = file_absence(scenario["assignment"]["id"], absence_date=ABSENCE_DAY)
    absence_b = file_absence(second["assignment"]["id"], absence_date=ABSENCE_DAY,
                             reason="FAMILY")

    rescind(absence_b["id"], reason="Tomas able to work after all.")
    fourth_observation = read_school(school_id)
    assert_school_coverage_partition(fourth_observation)
    assert fourth_observation["covered_post_count"] == 1
    assert fourth_observation["uncovered_post_count"] == 1
    assert fourth_observation["coverage_rate_pct"] == 50.00
    assert fourth_observation["coverage_posture"] == "RESTRICTED"

    rescind(absence_a["id"], reason="Rita cleared for duty.")
    fifth_observation = read_school(school_id)
    assert_school_coverage_partition(fifth_observation)
    assert fifth_observation["covered_post_count"] == 2
    assert fifth_observation["uncovered_post_count"] == 0
    assert fifth_observation["coverage_rate_pct"] == 100.00
    assert fifth_observation["coverage_posture"] == "OPEN"

    for absence_id, reason in ((absence_a["id"], "Rita cleared for duty."),
                              (absence_b["id"], "Tomas able to work after all.")):
        report = read_absence(absence_id)
        assert report["status"] == "RESCINDED"
        assert report["rescind_reason"] == reason
    for assignment_id in (scenario["assignment"]["id"], second["assignment"]["id"]):
        assignment = read_assignment(assignment_id)
        assert assignment["open_absence_count"] == 0
        assert assignment["coverage_state"] == "STAFFED"
    for post_id in (scenario["post"]["id"], second["post"]["id"]):
        assert read_post(post_id)["open_gap_count"] == 0
    for guard_id in (scenario["guard"]["id"], second["guard"]["id"]):
        guard = read_guard(guard_id)
        assert guard["reliability_score_rolling_90d"] == 100.00
        assert guard["certification_status"] == "CERTIFIED"


def test_publishing_while_the_school_is_suspended_lands_on_advisory_hold(api):
    """The posture changes the outcome of a successful publish rather than
    rejecting it.

    PRD: "when the owning school's `coverage_posture` is already `SUSPENDED` at
    the moment of publication, the freshly published route is placed on
    `ADVISORY_HOLD` right away."

    Design: Difficulty/cross_entity_state_dependency/route_publish_outcome_depends_on_school_coverage_posture
    """
    scenario = setup_staffed_post()
    advance_clock(DUTY_CLOCK)
    file_absence(scenario["assignment"]["id"], absence_date=ABSENCE_DAY)
    school_id = scenario["school"]["id"]
    assert read_school(school_id)["coverage_posture"] == "SUSPENDED"
    route = draft_route(school_id, [route_segment(1, "NO_SIDEWALK", 133)])
    assert route["status"] == "DRAFT"

    published = validate_success(api.publish_walking_route(
        route["id"], make_school_liaison_headers(school_id)))

    assert_walking_route(published)
    assert published["status"] == "ADVISORY_HOLD"
    assert published["hold_reason"] == "SCHOOL_COVERAGE_SUSPENDED"
    assert_same_instant(published["published_at"], DUTY_CLOCK,
                        "WalkingRoute.published_at")


def test_withdrawing_the_absence_releases_the_route_without_republishing_it(api):
    """Once the posture leaves SUSPENDED the held route returns to PUBLISHED and
    keeps the publication timestamp it was given.

    PRD: "and every `ADVISORY_HOLD` route of that school returns to `PUBLISHED`
    once the posture leaves `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/route_publish_outcome_depends_on_school_coverage_posture
    """
    scenario = setup_staffed_post()
    advance_clock(DUTY_CLOCK)
    absence = file_absence(scenario["assignment"]["id"], absence_date=ABSENCE_DAY)
    school_id = scenario["school"]["id"]
    route = draft_route(school_id, [route_segment(1, "NO_SIDEWALK", 133)])
    held = validate_success(api.publish_walking_route(
        route["id"], make_school_liaison_headers(school_id)))
    assert held["status"] == "ADVISORY_HOLD"

    rescind(absence["id"], reason="Guard reported fit for duty.")

    assert read_absence(absence["id"])["status"] == "RESCINDED"
    school = read_school(school_id)
    assert school["coverage_posture"] == "OPEN"
    assert school["coverage_rate_pct"] == 100.00
    released = read_route(route["id"])
    assert_walking_route(released)
    assert released["status"] == "PUBLISHED"
    assert released["hold_reason"] is None
    assert_same_instant(released["published_at"], DUTY_CLOCK,
                        "WalkingRoute.published_at")
    assert read_guard(scenario["guard"]["id"])["reliability_score_rolling_90d"] == 100.00
