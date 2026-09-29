"""Windows competing for one street, one crew or one block of parking."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_area,
    assert_money,
    assert_project_scope,
    assert_scenario_funding,
)
from test_helpers.constants import (
    AREA_MAPLE,
    ELM_TOTAL,
    FUNDING_STANDARD,
    MAPLE_TOTAL,
    OAK_TOTAL,
    OBS_CS75,
    OBS_MILL,
    SEG_ELM,
    SEG_MAPLE,
    SEG_OAK,
)
from test_helpers.factories import (
    award_payload,
    project_segment_payload,
    schedule_notice_payload,
)
from test_helpers.test_users import ENGINEER, OFFICER_AWARDER

THREE_STREETS = [(SEG_MAPLE, OBS_MILL), (SEG_OAK, OBS_CS75), (SEG_ELM, OBS_CS75)]

# 11817655 committed by project A plus 1711091 by project C.
COMMITTED_AFTER_A_AND_C = 13528746
UNCOMMITTED_AFTER_A_AND_C = 6471254


def _second_program_over_the_same_block(api):
    """Project A holds [2026-09-01, 2026-09-15) on Maple St; project B holds nothing."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.draft_project(api, ctx, fixtures.MAPLE_LINE, project_name="Maple St phase 1")
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    assert ctx["lines"]["Maple St"]["work_window_start"].startswith("2026-09-01T00:00:00")
    assert ctx["lines"]["Maple St"]["work_window_end"].startswith("2026-09-15T00:00:00")
    assert fixtures.read_candidate(api, fixtures.candidate_for(ctx, "Maple St")["id"])[
        "candidate_status"
    ] == "CONSUMED"

    later = fixtures.open_survey(api, survey_year=2027)
    observation = fixtures.file_observation(api, later["id"], segment_id, OBS_MILL)
    fixtures.accept_observation(api, observation["id"])
    fixtures.seal_survey(api, later["id"])
    candidate_b = fixtures.generate_candidates(api, later["id"])[0]

    scenario_b = fixtures.create_scenario(
        api, later["id"], scenario_name="FY28 program", funding_cents=FUNDING_STANDARD
    )
    fixtures.run_scenario(api, scenario_b["id"])
    fixtures.adopt_scenario(api, scenario_b["id"])
    project_b = fixtures.create_project(
        api,
        scenario_b["id"],
        "Z1",
        project_name="Maple St phase 2",
        planned_start_date="2026-09-01T00:00:00Z",
        planned_end_date="2026-09-30T00:00:00Z",
    )
    return segment_id, candidate_b, project_b, ctx["lines"]["Maple St"]


def test_a_work_window_overlapping_a_sibling_line_is_rejected(api):
    """Half-open occupancy: 2026-09-14 still falls inside a window ending 09-15.

    PRD: "Finally the line's occupancy window is checked against every other
    non-removed line on the same segment as a **half-open interval** running from
    `work_window_start` up to but not including `work_window_end`: overlapping
    windows are rejected with `ERR_SEGMENT_WINDOW_CONFLICT`, while windows that
    merely touch — one line ending at exactly the instant the next begins — are
    allowed."

    Design: Difficulty/resource_temporal_overlap/segment_work_windows_half_open_touching_allowed_overlap_rejected
    """
    segment_id, candidate_b, project_b, _line_a = _second_program_over_the_same_block(api)

    validate_error(
        api.create_project_segment(
            project_segment_payload(
                project_b["id"],
                segment_id,
                candidate_b["id"],
                project_b["version"],
                "2026-09-14T00:00:00Z",
                "2026-09-20T00:00:00Z",
            ),
            ENGINEER,
        ),
        ApiErrorId.SEGMENT_WINDOW_CONFLICT,
        409,
    )

    refused = fixtures.read_project(api, project_b["id"])
    assert refused["segment_count"] == 0
    assert refused["planned_area_sy"] == 0.0
    assert fixtures.read_segment(api, segment_id)["active_project_count"] == 1


def test_a_work_window_that_merely_touches_the_sibling_is_accepted(api):
    """Starting on the exact instant the sibling ends collides on nothing.

    PRD: "The parent project increments `segment_count`, adds the line's
    `line_area_sy` to `planned_area_sy`, recomputes its estimate and increments its
    `version`; the referenced segment increments `active_project_count`."

    The accepted call reuses the very `expected_project_version` the rejected call
    supplied, which proves the refusal never advanced the project's version.

    Design: Difficulty/resource_temporal_overlap/segment_work_windows_half_open_touching_allowed_overlap_rejected
    """
    segment_id, candidate_b, project_b, _line_a = _second_program_over_the_same_block(api)
    validate_error(
        api.create_project_segment(
            project_segment_payload(
                project_b["id"],
                segment_id,
                candidate_b["id"],
                project_b["version"],
                "2026-09-14T00:00:00Z",
                "2026-09-20T00:00:00Z",
            ),
            ENGINEER,
        ),
        ApiErrorId.SEGMENT_WINDOW_CONFLICT,
        409,
    )

    line = validate_success(
        api.create_project_segment(
            project_segment_payload(
                project_b["id"],
                segment_id,
                candidate_b["id"],
                project_b["version"],
                "2026-09-15T00:00:00Z",
                "2026-09-20T00:00:00Z",
            ),
            ENGINEER,
        ),
        201,
    )

    assert line["work_window_start"].startswith("2026-09-15T00:00:00")
    assert line["work_state"] == "PLANNED"
    assert_project_scope(fixtures.read_project(api, project_b["id"]), 1, AREA_MAPLE)
    assert fixtures.read_segment(api, segment_id)["active_project_count"] == 2


def _one_crew_and_three_bundles(api):
    """A single-crew firm holding Maple St, with Oak St and Elm St out for bid."""
    ctx = fixtures.adopted_program(api, THREE_STREETS, max_concurrent_projects=1)
    projects = {}
    for street, zone, name, start, end in (
        ("Maple St", "Z1", "Maple St resurfacing", "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z"),
        ("Oak St", "Z1", "Oak St crack seal", "2026-09-30T00:00:00Z", "2026-10-31T00:00:00Z"),
        ("Elm St", "Z3", "Elm St crack seal", "2026-10-01T00:00:00Z", "2026-10-30T00:00:00Z"),
    ):
        project = fixtures.create_project(
            api,
            ctx["scenario"]["id"],
            zone,
            project_name=name,
            planned_start_date=start,
            planned_end_date=end,
        )
        fixtures.add_line(
            api,
            project["id"],
            fixtures.segment_for(ctx, street)["id"],
            fixtures.candidate_for(ctx, street)["id"],
            start,
            end,
        )
        fixtures.advance(api, project["id"], "START_COORDINATION")
        for row in fixtures.list_coordinations(api, project["id"]):
            fixtures.respond_coordination(
                api, row["id"], "CLEAR", response_note="no facilities in conflict"
            )
        projects[street] = fixtures.advance(api, project["id"], "BID_READY")

    awarded = validate_success(
        api.award_project(
            projects["Maple St"]["id"],
            award_payload(ctx["contractor"]["id"], MAPLE_TOTAL),
            OFFICER_AWARDER,
        )
    )
    assert awarded["delivery_status"] == "AWARDED"
    assert ctx["contractor"]["max_concurrent_projects"] == 1
    return ctx, projects


def test_capacity_counts_a_project_touching_the_held_window_at_one_instant(api):
    """Crew capacity reads the planned dates as a closed interval, unlike a line.

    PRD: "Crew capacity must hold: count the contractor's projects whose
    `delivery_status` is `AWARDED` or `IN_CONSTRUCTION` and whose **closed**
    interval from `planned_start_date` through `planned_end_date` intersects the
    target project's closed interval — touching endpoints *do* count as an
    intersection — and if awarding this project would leave the firm holding more
    overlapping projects than its `max_concurrent_projects`, report
    `ERR_CONTRACTOR_CAPACITY_EXCEEDED`."

    The Oak St bundle runs 2026-09-30 to 2026-10-31 and shares exactly one instant
    with the held 2026-09-01 to 2026-09-30 window, while 5289971 cents sits well
    inside the 8182345 the scenario still has uncommitted.

    Design: Difficulty/resource_temporal_overlap/contractor_capacity_closed_interval_touching_endpoints_conflict
    """
    ctx, projects = _one_crew_and_three_bundles(api)
    assert_money(projects["Oak St"]["project_total_estimate_cents"], OAK_TOTAL)

    validate_error(
        api.award_project(
            projects["Oak St"]["id"],
            award_payload(ctx["contractor"]["id"], OAK_TOTAL),
            OFFICER_AWARDER,
        ),
        ApiErrorId.CONTRACTOR_CAPACITY_EXCEEDED,
        409,
    )

    refused = fixtures.read_project(api, projects["Oak St"]["id"])
    assert refused["delivery_status"] == "BID_READY"
    assert refused["award_amount_cents"] is None
    assert refused["contractor_id"] is None


def test_capacity_clears_for_a_project_starting_one_day_after_the_held_window(api):
    """The same firm, the same instant, one day of separation — and the award lands.

    PRD: "A successful award sets `contractor_id` and `award_amount_cents` on the
    project, adds the awarded amount to the scenario's `committed_cents`, recomputes
    the scenario's `uncommitted_cents` as `funding_cents` less `committed_cents`, and
    increments the scenario's `version` by 1."

    Elm St runs 2026-10-01 to 2026-10-30, one day clear of the held window, and its
    1711091-cent award lifts committed money to 13528746.

    Design: Difficulty/resource_temporal_overlap/contractor_capacity_closed_interval_touching_endpoints_conflict
    """
    ctx, projects = _one_crew_and_three_bundles(api)
    assert_money(projects["Elm St"]["project_total_estimate_cents"], ELM_TOTAL)
    validate_error(
        api.award_project(
            projects["Oak St"]["id"],
            award_payload(ctx["contractor"]["id"], OAK_TOTAL),
            OFFICER_AWARDER,
        ),
        ApiErrorId.CONTRACTOR_CAPACITY_EXCEEDED,
        409,
    )

    awarded = validate_success(
        api.award_project(
            projects["Elm St"]["id"],
            award_payload(ctx["contractor"]["id"], ELM_TOTAL),
            OFFICER_AWARDER,
        )
    )
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])

    assert awarded["delivery_status"] == "AWARDED"
    assert_money(awarded["award_amount_cents"], ELM_TOTAL)
    assert_scenario_funding(
        scenario, FUNDING_STANDARD, COMMITTED_AFTER_A_AND_C, UNCOMMITTED_AFTER_A_AND_C
    )


def _delivered_sibling_notice_on_one_block(api):
    """Project A's notice is out for 2026-09-01..2026-09-15; project B's is pending."""
    segment_id, candidate_b, project_b, line_a = _second_program_over_the_same_block(api)
    fixtures.schedule_notice(api, line_a["id"], "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")
    delivered = fixtures.deliver_notice(api, line_a["id"])
    assert delivered["notice_state"] == "DELIVERED"

    line_b = fixtures.add_line(
        api,
        project_b["id"],
        segment_id,
        candidate_b["id"],
        "2026-10-01T00:00:00Z",
        "2026-10-20T00:00:00Z",
    )
    assert line_b["notice_state"] == "PENDING"
    return delivered, line_b


def test_a_notice_window_touching_the_buffered_sibling_window_is_rejected(api):
    """The 24-hour buffers meet on a single instant, and a closed interval collides.

    PRD: "The window, expanded by a 24-hour buffer on each side and compared as a
    **closed** interval, must not overlap the notice window of any other
    non-removed line on the same segment whose `notice_state` is `SCHEDULED` or
    `DELIVERED`; an overlap reports `ERR_NOTICE_WINDOW_CONFLICT`."

    The PRD buffers the window being scheduled, not the sibling's stored window:
    buffering 2026-09-16T00:00:00Z back by a day reaches 2026-09-15T00:00:00Z, which
    is precisely where the sibling's window ends, so the closed intervals touch.

    Design: Difficulty/resource_temporal_overlap/notice_window_buffered_closed_interval_conflict_on_same_segment
    """
    delivered, line_b = _delivered_sibling_notice_on_one_block(api)

    validate_error(
        api.notice(
            line_b["id"],
            schedule_notice_payload("2026-09-16T00:00:00Z", "2026-09-20T00:00:00Z"),
            ENGINEER,
        ),
        ApiErrorId.NOTICE_WINDOW_CONFLICT,
        409,
    )

    refused = fixtures.read_line(api, line_b["id"])
    assert refused["notice_state"] == "PENDING"
    assert refused["parking_restriction_start"] is None
    assert refused["driveway_access_plan"] is None
    assert delivered["parking_restriction_start"].startswith("2026-09-01T00:00:00")


def test_one_second_of_separation_clears_the_buffered_notice_conflict(api):
    """A single second past the shared instant and the same window is publishable.

    PRD: "`SCHEDULE` moves `notice_state` from `PENDING` to `SCHEDULED` and
    publishes the restriction: the engineer supplies `parking_restriction_start` and
    `parking_restriction_end` for the no-parking window, and a
    `driveway_access_plan` of `MAINTAINED` when driveways stay usable throughout,
    `LIMITED_NIGHTLY` when access is restored each night, or `BLOCKED_WITH_ALT` when
    access is blocked and an alternative is arranged."

    PRD: "A first schedule leaves `notice_round` at 1."

    Design: Difficulty/resource_temporal_overlap/notice_window_buffered_closed_interval_conflict_on_same_segment
    """
    delivered, line_b = _delivered_sibling_notice_on_one_block(api)
    validate_error(
        api.notice(
            line_b["id"],
            schedule_notice_payload("2026-09-16T00:00:00Z", "2026-09-20T00:00:00Z"),
            ENGINEER,
        ),
        ApiErrorId.NOTICE_WINDOW_CONFLICT,
        409,
    )

    scheduled = validate_success(
        api.notice(
            line_b["id"],
            schedule_notice_payload(
                "2026-09-16T00:00:01Z", "2026-09-20T00:00:00Z", "LIMITED_NIGHTLY"
            ),
            ENGINEER,
        )
    )

    assert scheduled["notice_state"] == "SCHEDULED"
    assert scheduled["parking_restriction_start"].startswith("2026-09-16T00:00:01")
    assert scheduled["driveway_access_plan"] == "LIMITED_NIGHTLY"
    assert scheduled["notice_round"] == 1
    sibling = fixtures.read_line(api, delivered["id"])
    assert sibling["parking_restriction_start"].startswith("2026-09-01T00:00:00")
    assert sibling["notice_state"] == "DELIVERED"
    assert_area(scheduled["line_area_sy"], AREA_MAPLE)
