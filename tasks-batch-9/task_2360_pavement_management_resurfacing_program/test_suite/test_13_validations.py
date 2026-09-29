"""Uniqueness, referential, temporal, roster, aggregate and conditional gates."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_area,
    assert_index,
    assert_line_states,
    assert_money,
    assert_pay_factor,
    assert_project_estimate,
    assert_project_scope,
    assert_project_states,
    assert_scenario_funding,
    assert_scenario_totals,
)
from test_helpers.constants import (
    AREA_MAPLE,
    AREA_OAK,
    CRACK_SEAL,
    DEFAULT_CLOCK,
    ELM_CANDIDATE_COST,
    FUNDING_STANDARD,
    MAPLE_BUNDLE_BASE,
    MAPLE_CANDIDATE_COST,
    MAPLE_CONTINGENCY,
    MAPLE_TOTAL,
    MILL_AND_OVERLAY,
    OAK_LINE_COST,
    OBS_CS75,
    OBS_CS75_INDEX,
    OBS_MILL,
    SEG_ELM,
    SEG_MAPLE,
)
from test_helpers.factories import (
    acceptance_decision_payload,
    advance_payload,
    allocation_payload,
    award_payload,
    cut_permit_payload,
    observation_payload,
    project_payload,
    project_segment_payload,
    respond_payload,
    schedule_notice_payload,
    triage_payload,
)
from test_helpers.test_users import (
    COORDINATOR,
    ENGINEER,
    INSPECTOR,
    INSPECTOR_DECIDER,
    INSPECTOR_DECIDER_USER_ID,
    OFFICER,
    OFFICER_AWARDER,
)

# ----------------------------------------------------------------------
# Pinned literals
# ----------------------------------------------------------------------
SURVEY_YEAR_2027 = 2027

# One line holding the whole month, so the duplicate retry can repeat it verbatim.
MAPLE_FULL_MONTH_LINE = [("Maple St", "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")]
MAPLE_FIRST_HALF_LINE = [("Maple St", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")]
MAPLE_AND_OAK_LINES = [
    ("Maple St", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z"),
    ("Oak St", "2026-09-16T00:00:00Z", "2026-09-30T00:00:00Z"),
]
SECOND_HALF_START = "2026-09-16T00:00:00Z"
SECOND_HALF_END = "2026-09-30T00:00:00Z"

# A window that cannot collide with project A's first-half occupancy.
DISJOINT_WINDOW_START = "2026-09-20T00:00:00Z"
DISJOINT_WINDOW_END = "2026-09-30T00:00:00Z"

# Maple St (10,743,323) plus Elm St (1,487,905) both fit inside 20,000,000.
MAPLE_ELM_FUNDED = 12231228
# Maple St (10,743,323) plus Oak St (4,599,975).
MAPLE_OAK_FUNDED = 15343298

# The scenario is created while the clock reads 2026-08-01, so that is its
# analysis_date, and July is entirely behind it.
ANALYSIS_DATE = "2026-08-01T00:00:00"
BACKDATED_START = "2026-07-01T00:00:00Z"
BACKDATED_END = "2026-07-31T00:00:00Z"
ON_ANALYSIS_DATE_START = "2026-08-01T00:00:00Z"
ON_ANALYSIS_DATE_END = "2026-08-31T00:00:00Z"

# WATER's dig window against a 2026-09-01 paving start.
UTILITY_WORK_START = "2026-08-20T00:00:00Z"
UTILITY_WORK_LATE_END = "2026-09-05T00:00:00Z"
UTILITY_WORK_ON_TIME_END = "2026-09-01T00:00:00Z"
CONFLICT_NOTE = "16-inch main sits under the crown"
SCHEDULE_NOTE = "crew available late August"

# Cut permit applications.
CUT_AREA_SQFT = 200.0
ROSTERLESS_CUT_START = "2026-08-10T00:00:00Z"
ROSTERLESS_CUT_END = "2026-08-12T00:00:00Z"
CONSTRUCTION_CUT_START = "2026-09-10T00:00:00Z"
CONSTRUCTION_CUT_END = "2026-09-12T00:00:00Z"

# A funding envelope far below the single candidate the survey produced.
TINY_FUNDING = 1000000

# density 94.0 -> 0.98, IRI 120.0 -> 0.97, 1.80 in against a 2.00 in design -> 0.96.
FAIL_DENSITY_PCT = 94.0
FAIL_IRI = 120.0
FAIL_THICKNESS_IN = 1.80
FAIL_PAY_FACTOR = 0.9126
PASS_ATTEMPT_NOTE = "field engineer wants to accept as-is"
FAIL_NOTE = "cores confirm the computed failure"

OAK_COMPLAINT_NOTE = "sunken patch outside 812 Oak St"

# 11,817,655 +/- 10 percent is [10,635,890, 12,999,421].
LOW_BID = 10000000
IN_BAND_BID = 10700000

# 2026-08-01T00:00:00Z plus exactly 72 hours.
NOTICE_BOUNDARY_START = "2026-08-04T00:00:00Z"
NOTICE_BOUNDARY_END = "2026-08-18T00:00:00Z"
NOTICE_ONE_SECOND_SHORT_START = "2026-08-03T23:59:59Z"
NOTICE_ONE_SECOND_SHORT_END = "2026-08-17T00:00:00Z"
ACCESS_MAINTAINED = "MAINTAINED"

MAPLE_AND_ELM = [(SEG_MAPLE, OBS_MILL), (SEG_ELM, OBS_CS75)]


def _observation_total(api):
    _rows, meta = validate_paginated(api.list_observations(ENGINEER, {"limit": 100}))
    return meta["total_count"]


def _line_total_for_project(api, project_id):
    _rows, meta = validate_paginated(
        api.list_project_segments(ENGINEER, {"project_id": project_id, "limit": 100})
    )
    return meta["total_count"]


# ----------------------------------------------------------------------
# Uniqueness: the pair, not the part
# ----------------------------------------------------------------------


def test_a_second_reading_of_the_same_street_on_the_same_survey_is_refused(api):
    """The duplicate key is the survey-and-segment pair, so different numbers do not help.

    PRD: "Filing an observation against a survey that is not `OPEN` is rejected with
    `ERR_SURVEY_NOT_OPEN`, and a second observation for the same survey-and-segment
    pair is rejected with `ERR_DUPLICATE_OBSERVATION`."

    PRD: "A survey's `observation_count` counts every distress observation on it in any
    quality-control state, while `accepted_observation_count` counts only those
    accepted."

    The retry reports rutting 0.875 instead of 0.55, so it is a genuinely different
    measurement of the same block; only the pair is what the constraint reads.

    Design: Corner/validations/second_observation_on_the_same_survey_and_segment_rejected
    """
    ctx = fixtures.open_survey_with_observations(api, fixtures.MAPLE_ONLY)
    survey_id = ctx["survey"]["id"]
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]

    validate_error(
        api.create_observation(
            observation_payload(survey_id, segment_id, OBS_CS75), ENGINEER
        ),
        ApiErrorId.DUPLICATE_OBSERVATION,
        409,
    )

    survey = validate_success(api.get_survey(survey_id, ENGINEER))
    assert survey["survey_status"] == "OPEN"
    assert survey["observation_count"] == 1
    assert survey["accepted_observation_count"] == 1
    assert _observation_total(api) == 1


def test_the_same_reading_is_accepted_on_a_second_open_survey_year(api):
    """Pair-scoped means one street may be measured once per campaign, not once ever.

    PRD: "Filing an observation against a survey that is not `OPEN` is rejected with
    `ERR_SURVEY_NOT_OPEN`, and a second observation for the same survey-and-segment
    pair is rejected with `ERR_DUPLICATE_OBSERVATION`."

    PRD: "Finally `measured_condition_index` is 100 less the `deduct_total`, clamped
    into the range 0.0 through 100.0 and rounded to one decimal place."

    A per-segment unique index would refuse this filing; a per-pair one accepts it and
    the network then holds two readings of Maple St.

    Design: Corner/validations/second_observation_on_the_same_survey_and_segment_rejected
    """
    ctx = fixtures.open_survey_with_observations(api, fixtures.MAPLE_ONLY)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]

    next_year = fixtures.open_survey(api, survey_year=SURVEY_YEAR_2027)
    assert next_year["survey_status"] == "OPEN"
    assert next_year["observation_count"] == 0

    filed = validate_success(
        api.create_observation(
            observation_payload(next_year["id"], segment_id, OBS_CS75), ENGINEER
        ),
        201,
    )
    assert_index(filed["measured_condition_index"], OBS_CS75_INDEX)
    assert filed["survey_id"] == next_year["id"]
    assert filed["segment_id"] == segment_id

    assert _observation_total(api) == 2
    assert (
        validate_success(api.get_survey(ctx["survey"]["id"], ENGINEER))[
            "observation_count"
        ]
        == 1
    )
    assert validate_success(api.get_survey(next_year["id"], ENGINEER))["observation_count"] == 1


def test_reposting_an_identical_line_body_is_refused_as_a_duplicate_pair(api):
    """The pair clause is declared first, so it is the clause that reports.

    PRD: "Two uniqueness rules follow: at most one non-removed line per
    project-and-segment pair, else `ERR_DUPLICATE_PROJECT_SEGMENT`, and at most one
    non-removed line per candidate anywhere in the system, else
    `ERR_CANDIDATE_ALREADY_PROGRAMMED`."

    PRD: "When a request violates several rules at once, exactly one error is reported,
    and which one is fully determined."

    PRD: "The parent project increments `segment_count`, adds the line's `line_area_sy`
    to `planned_area_sy`, recomputes its estimate and increments its `version`; the
    referenced segment increments `active_project_count`."

    The retry carries the project's refreshed version, so the stale-read guard cannot
    be what rejects it, and the bundle arithmetic must not double.

    Design: Corner/validations/duplicate_line_for_the_same_project_and_segment_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.draft_project(api, ctx, MAPLE_FULL_MONTH_LINE)
    project_id = ctx["project"]["id"]
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    candidate_id = fixtures.candidate_for(ctx, "Maple St")["id"]

    validate_error(
        api.create_project_segment(
            project_segment_payload(
                project_id,
                segment_id,
                candidate_id,
                fixtures.project_version(api, project_id),
                "2026-09-01T00:00:00Z",
                "2026-09-30T00:00:00Z",
            ),
            ENGINEER,
        ),
        ApiErrorId.DUPLICATE_PROJECT_SEGMENT,
        409,
    )

    project = fixtures.read_project(api, project_id)
    assert_project_scope(project, 1, AREA_MAPLE)
    assert_project_estimate(project, MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL)
    assert _line_total_for_project(api, project_id) == 1
    assert fixtures.read_segment(api, segment_id)["active_project_count"] == 1


def test_one_funded_candidate_cannot_be_delivered_by_two_projects(api):
    """A new pair and a disjoint window still cannot buy the same work twice.

    PRD: "Two uniqueness rules follow: at most one non-removed line per
    project-and-segment pair, else `ERR_DUPLICATE_PROJECT_SEGMENT`, and at most one
    non-removed line per candidate anywhere in the system, else
    `ERR_CANDIDATE_ALREADY_PROGRAMMED`."

    PRD: "Finally the line's occupancy window is checked against every other
    non-removed line on the same segment as a **half-open interval** running from
    `work_window_start` up to but not including `work_window_end`: overlapping windows
    are rejected with `ERR_SEGMENT_WINDOW_CONFLICT`, while windows that merely touch —
    one line ending at exactly the instant the next begins — are allowed."

    PRD: "The candidate moves from `RECOMMENDED` or `OVERRIDDEN` to `CONSUMED` and is
    locked against override while consumed."

    PRD: "A new project has `delivery_status` `DRAFT` and `quality_status`
    `NOT_STARTED`, with `contractor_id` null, `award_amount_cents` null, `accepted_at`,
    `substantial_completion_at` and `accepting_inspector_user_id` all null, `days_late`
    zero, and every money field and counter at zero."

    Design: Corner/validations/same_candidate_placed_into_a_second_project_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.draft_project(api, ctx, MAPLE_FIRST_HALF_LINE, project_name="Package A")
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    candidate_id = fixtures.candidate_for(ctx, "Maple St")["id"]

    package_b = fixtures.create_project(
        api, ctx["scenario"]["id"], "Z1", project_name="Package B"
    )
    assert_project_scope(package_b, 0, 0.0)

    validate_error(
        api.create_project_segment(
            project_segment_payload(
                package_b["id"],
                segment_id,
                candidate_id,
                package_b["version"],
                DISJOINT_WINDOW_START,
                DISJOINT_WINDOW_END,
            ),
            ENGINEER,
        ),
        ApiErrorId.CANDIDATE_ALREADY_PROGRAMMED,
        409,
    )

    after_b = fixtures.read_project(api, package_b["id"])
    assert_project_scope(after_b, 0, 0.0)
    assert_project_estimate(after_b, 0, 0, 0, 0)
    assert fixtures.read_candidate(api, candidate_id)["candidate_status"] == "CONSUMED"
    assert fixtures.read_segment(api, segment_id)["active_project_count"] == 1


# ----------------------------------------------------------------------
# Referential rules: zone, candidate-to-segment
# ----------------------------------------------------------------------


def test_a_funded_candidate_outside_the_bundles_zone_cannot_join_it(api):
    """Geographic bundling is a hard rule, not a preference.

    PRD: "The segment's `geo_zone` must equal the project's `geo_zone`, because a
    bundle is a geographic package and may not reach outside its zone, else
    `ERR_SEGMENT_ZONE_MISMATCH`."

    PRD: "The candidate must belong to the survey behind the project's scenario and
    must hold a `FUNDED` allocation in that scenario, else `ERR_CANDIDATE_NOT_FUNDED`."

    PRD: "The candidate moves from `RECOMMENDED` or `OVERRIDDEN` to `CONSUMED` and is
    locked against override while consumed."

    Elm St's candidate is funded in the very same adopted scenario and names its own
    segment, so zone is the only clause it fails.

    Design: Corner/validations/line_whose_segment_sits_in_another_geo_zone_rejected
    """
    ctx = fixtures.adopted_program(api, MAPLE_AND_ELM)
    assert_scenario_totals(ctx["scenario"], 2, MAPLE_ELM_FUNDED, 0)
    ctx = fixtures.draft_project(api, ctx, MAPLE_FIRST_HALF_LINE)
    project_id = ctx["project"]["id"]

    elm_segment = fixtures.segment_for(ctx, "Elm St")
    elm_candidate = fixtures.candidate_for(ctx, "Elm St")
    assert elm_segment["geo_zone"] == "Z3"
    assert_money(elm_candidate["estimated_cost_cents"], ELM_CANDIDATE_COST)

    validate_error(
        api.create_project_segment(
            project_segment_payload(
                project_id,
                elm_segment["id"],
                elm_candidate["id"],
                fixtures.project_version(api, project_id),
                SECOND_HALF_START,
                SECOND_HALF_END,
            ),
            ENGINEER,
        ),
        ApiErrorId.SEGMENT_ZONE_MISMATCH,
        422,
    )

    project = fixtures.read_project(api, project_id)
    assert project["geo_zone"] == "Z1"
    assert_project_scope(project, 1, AREA_MAPLE)
    assert_project_estimate(project, MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL)
    assert fixtures.read_candidate(api, elm_candidate["id"])["candidate_status"] == "RECOMMENDED"
    assert fixtures.read_segment(api, elm_segment["id"])["active_project_count"] == 0
    assert _line_total_for_project(api, project_id) == 1


def test_a_line_naming_one_street_with_another_streets_candidate_is_refused(api):
    """Crossing the pair would price one block's overlay onto another block.

    PRD: "The candidate must reference the same segment as the line, else
    `ERR_CANDIDATE_SEGMENT_MISMATCH`."

    PRD: "Creation copies `treatment_type` from the candidate and `line_area_sy` from
    the segment's `area_sy`, computes the line's `line_cost_cents`, and starts the line
    at `work_state` `PLANNED`, `notice_state` `PENDING` and `notice_round` 1, with
    `parking_restriction_start`, `parking_restriction_end`, `driveway_access_plan`,
    `notice_delivered_at` and `pay_factor` all null and `test_count` zero."

    Both rows are individually legal — same zone, same survey, both funded — so only
    the pairing is at fault, and the corrected line proves it.

    Design: Corner/validations/line_whose_candidate_belongs_to_another_segment_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    assert_scenario_totals(ctx["scenario"], 2, MAPLE_OAK_FUNDED, 0)
    project = fixtures.create_project(api, ctx["scenario"]["id"], "Z1")

    oak_segment = fixtures.segment_for(ctx, "Oak St")
    oak_candidate = fixtures.candidate_for(ctx, "Oak St")
    maple_candidate = fixtures.candidate_for(ctx, "Maple St")
    assert maple_candidate["treatment_type"] == MILL_AND_OVERLAY
    assert oak_candidate["treatment_type"] == CRACK_SEAL

    validate_error(
        api.create_project_segment(
            project_segment_payload(
                project["id"],
                oak_segment["id"],
                maple_candidate["id"],
                project["version"],
            ),
            ENGINEER,
        ),
        ApiErrorId.CANDIDATE_SEGMENT_MISMATCH,
        422,
    )

    after = fixtures.read_project(api, project["id"])
    assert_project_scope(after, 0, 0.0)
    assert_project_estimate(after, 0, 0, 0, 0)
    assert fixtures.read_candidate(api, maple_candidate["id"])["candidate_status"] == "RECOMMENDED"
    assert fixtures.read_candidate(api, oak_candidate["id"])["candidate_status"] == "RECOMMENDED"

    corrected = fixtures.add_line(
        api, project["id"], oak_segment["id"], oak_candidate["id"]
    )
    assert_area(corrected["line_area_sy"], AREA_OAK)
    assert corrected["treatment_type"] == CRACK_SEAL
    assert_line_states(corrected, "PLANNED", "PENDING")


# ----------------------------------------------------------------------
# Temporal rules: the analysis date and the paving start
# ----------------------------------------------------------------------


def test_a_project_window_entirely_before_the_analysis_date_is_refused(api):
    """You cannot pave in a month the funding analysis never looked at.

    PRD: "The planned start must be on or after the scenario's `analysis_date` and the
    planned end strictly after the planned start; a start earlier than the analysis
    date reports `ERR_PROJECT_WINDOW_BEFORE_ANALYSIS_DATE`."

    PRD: "Creation stamps `analysis_date` with the logical clock — every age
    computation inside this scenario is measured from that instant, not from the clock
    as it stands later — and sets `scenario_status` to `DRAFT`, with all money and
    projection outputs at zero or null until the first run."

    The July window is perfectly ordered, so shape is not the defect.

    Design: Corner/validations/project_starting_before_the_scenario_analysis_date_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    scenario_id = ctx["scenario"]["id"]
    assert ctx["scenario"]["analysis_date"].startswith(ANALYSIS_DATE)

    validate_error(
        api.create_project(
            project_payload(
                scenario_id,
                "Z1",
                project_name="Backdated package",
                planned_start_date=BACKDATED_START,
                planned_end_date=BACKDATED_END,
            ),
            ENGINEER,
        ),
        ApiErrorId.PROJECT_WINDOW_BEFORE_ANALYSIS_DATE,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_projects(ENGINEER, {"scenario_id": scenario_id, "limit": 100})
    )
    assert meta["total_count"] == 0


def test_a_project_starting_exactly_on_the_analysis_date_is_accepted(api):
    """A start on the analysis date itself satisfies the on-or-after comparison.

    PRD: "The planned start must be on or after the scenario's `analysis_date` and the
    planned end strictly after the planned start; a start earlier than the analysis
    date reports `ERR_PROJECT_WINDOW_BEFORE_ANALYSIS_DATE`."

    PRD: "A new project has `delivery_status` `DRAFT` and `quality_status`
    `NOT_STARTED`, with `contractor_id` null, `award_amount_cents` null, `accepted_at`,
    `substantial_completion_at` and `accepting_inspector_user_id` all null, `days_late`
    zero, and every money field and counter at zero."

    Design: Corner/validations/project_starting_before_the_scenario_analysis_date_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    scenario_id = ctx["scenario"]["id"]

    created = validate_success(
        api.create_project(
            project_payload(
                scenario_id,
                "Z1",
                project_name="Boundary package",
                planned_start_date=ON_ANALYSIS_DATE_START,
                planned_end_date=ON_ANALYSIS_DATE_END,
            ),
            ENGINEER,
        ),
        201,
    )
    assert created["planned_start_date"].startswith(ANALYSIS_DATE)
    assert_project_states(created, "DRAFT", "NOT_STARTED")
    assert created["contractor_id"] is None
    assert created["award_amount_cents"] is None
    assert_project_scope(created, 0, 0.0)
    assert_project_estimate(created, 0, 0, 0, 0)


def test_utility_work_finishing_after_the_paver_arrives_is_refused(api):
    """Utilities dig before the paver, so the dig window may not outlast the start.

    PRD: "From `CONFLICT_DECLARED`, a `response` of `SCHEDULE_WORK` moves the row to
    `WORK_SCHEDULED` and records the utility's `planned_work_start` and
    `planned_work_end`; it requires the row to be in `CONFLICT_DECLARED`, else
    `ERR_COORDINATION_NOT_IN_CONFLICT`, requires both instants to be supplied with the
    end strictly after the start, else `ERR_INVALID_REQUEST`, and requires the planned
    work to finish on or before the project's `planned_start_date`, because utilities
    dig before the paver and never after — a window ending later reports
    `ERR_UTILITY_WORK_AFTER_PAVING`."

    PRD: "A `response` of `CONFLICT` moves the row to `CONFLICT_DECLARED` and records
    the note, leaving `clearance_outstanding_count` unchanged because the clearance is
    still outstanding."

    Design: Corner/validations/utility_work_scheduled_to_finish_after_paving_starts_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx, MAPLE_FIRST_HALF_LINE)
    water = fixtures.coordination_for(ctx, "WATER")
    declared = fixtures.respond_coordination(
        api, water["id"], "CONFLICT", response_note=CONFLICT_NOTE
    )
    assert declared["coordination_status"] == "CONFLICT_DECLARED"

    validate_error(
        api.respond_coordination(
            water["id"],
            respond_payload(
                "SCHEDULE_WORK",
                response_note=SCHEDULE_NOTE,
                planned_work_start=UTILITY_WORK_START,
                planned_work_end=UTILITY_WORK_LATE_END,
            ),
            COORDINATOR,
        ),
        ApiErrorId.UTILITY_WORK_AFTER_PAVING,
        422,
    )

    row = validate_success(api.get_coordination(water["id"], COORDINATOR))
    assert row["coordination_status"] == "CONFLICT_DECLARED"
    assert row["planned_work_start"] is None
    assert row["planned_work_end"] is None
    assert row["round_count"] == 1
    project = fixtures.read_project(api, ctx["project"]["id"])
    assert project["clearance_outstanding_count"] == 4
    assert_project_states(project, "COORDINATING", "NOT_STARTED")


def test_utility_work_ending_exactly_at_the_paving_start_is_accepted(api):
    """The on-or-before bound includes the paving start instant itself.

    PRD: "From `CONFLICT_DECLARED`, a `response` of `SCHEDULE_WORK` moves the row to
    `WORK_SCHEDULED` and records the utility's `planned_work_start` and
    `planned_work_end`; it requires the row to be in `CONFLICT_DECLARED`, else
    `ERR_COORDINATION_NOT_IN_CONFLICT`, requires both instants to be supplied with the
    end strictly after the start, else `ERR_INVALID_REQUEST`, and requires the planned
    work to finish on or before the project's `planned_start_date`, because utilities
    dig before the paver and never after — a window ending later reports
    `ERR_UTILITY_WORK_AFTER_PAVING`."

    Design: Corner/validations/utility_work_scheduled_to_finish_after_paving_starts_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx, MAPLE_FIRST_HALF_LINE)
    assert ctx["project"]["planned_start_date"].startswith("2026-09-01T00:00:00")
    water = fixtures.coordination_for(ctx, "WATER")
    fixtures.respond_coordination(api, water["id"], "CONFLICT", response_note=CONFLICT_NOTE)

    scheduled = fixtures.respond_coordination(
        api,
        water["id"],
        "SCHEDULE_WORK",
        response_note=SCHEDULE_NOTE,
        planned_work_start=UTILITY_WORK_START,
        planned_work_end=UTILITY_WORK_ON_TIME_END,
    )
    assert scheduled["coordination_status"] == "WORK_SCHEDULED"
    assert scheduled["planned_work_start"].startswith("2026-08-20T00:00:00")
    assert scheduled["planned_work_end"].startswith("2026-09-01T00:00:00")
    assert scheduled["round_count"] == 1
    assert fixtures.read_project(api, ctx["project"]["id"])["clearance_outstanding_count"] == 4


# ----------------------------------------------------------------------
# Roster and worker safety on cut permits
# ----------------------------------------------------------------------


def test_a_cut_permit_is_refused_while_the_coordination_roster_is_empty(api):
    """The roster is whatever coordination has produced so far, and nothing has.

    PRD: "Then the roster check: the `applicant_utility` must appear on the city's
    coordination roster, meaning some utility coordination row somewhere in the system
    carries the same utility value, else `ERR_UTILITY_NOT_ON_COORDINATION_ROSTER`."

    PRD: "Permits may be listed and filtered by `segment_id`, `permit_status` and
    `applicant_utility`."

    The segment, the window and the area are all valid, so membership is the only
    failing clause and no PENDING row may be left behind.

    Design: Corner/validations/cut_permit_from_a_utility_absent_from_the_roster_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    segment = fixtures.create_segment(api, SEG_MAPLE)
    assert segment["moratorium_until"] is None
    assert segment["active_project_count"] == 0

    _rows, roster_meta = validate_paginated(
        api.list_coordinations(
            COORDINATOR, {"utility": "FRANCHISE_TELECOM", "limit": 100}
        )
    )
    assert roster_meta["total_count"] == 0

    validate_error(
        api.create_cut_permit(
            cut_permit_payload(
                segment["id"],
                applicant_utility="FRANCHISE_TELECOM",
                requested_start=ROSTERLESS_CUT_START,
                requested_end=ROSTERLESS_CUT_END,
                cut_area_sqft=CUT_AREA_SQFT,
            ),
            COORDINATOR,
        ),
        ApiErrorId.UTILITY_NOT_ON_COORDINATION_ROSTER,
        422,
    )

    _permits, meta = validate_paginated(
        api.list_cut_permits(COORDINATOR, {"segment_id": segment["id"], "limit": 100})
    )
    assert meta["total_count"] == 0


def test_a_cut_permit_over_live_construction_is_refused_before_any_fee_is_computed(api):
    """Worker safety outranks the roster, the moratorium and the fee alike.

    PRD: "Worker safety comes first: a permit may not be created for a segment carrying
    an active construction line — any line on that segment whose `work_state` is
    `IN_PROGRESS` or `REMEDIATION_REQUIRED` — and that rejection,
    `ERR_CUT_BLOCKED_ACTIVE_CONSTRUCTION`, outranks every roster, moratorium and fee
    consideration."

    WATER is on the roster and `moratorium_until` is still null, so live work is the
    only thing that can be refusing this application.

    Design: Corner/validations/cut_permit_on_a_segment_under_active_construction_rejected
    """
    ctx = fixtures.maple_in_construction(api)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    line = fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])
    assert_line_states(line, "IN_PROGRESS", "DELIVERED")
    assert fixtures.read_segment(api, segment_id)["moratorium_until"] is None

    validate_error(
        api.create_cut_permit(
            cut_permit_payload(
                segment_id,
                applicant_utility="WATER",
                requested_start=CONSTRUCTION_CUT_START,
                requested_end=CONSTRUCTION_CUT_END,
                cut_area_sqft=CUT_AREA_SQFT,
            ),
            COORDINATOR,
        ),
        ApiErrorId.CUT_BLOCKED_ACTIVE_CONSTRUCTION,
        409,
    )

    _permits, meta = validate_paginated(
        api.list_cut_permits(COORDINATOR, {"segment_id": segment_id, "limit": 100})
    )
    assert meta["total_count"] == 0


def test_an_emergency_cut_over_live_construction_is_refused_identically(api):
    """The worker-safety rule carries no emergency exception.

    PRD: "Worker safety comes first: a permit may not be created for a segment carrying
    an active construction line — any line on that segment whose `work_state` is
    `IN_PROGRESS` or `REMEDIATION_REQUIRED` — and that rejection,
    `ERR_CUT_BLOCKED_ACTIVE_CONSTRUCTION`, outranks every roster, moratorium and fee
    consideration."

    Design: Corner/validations/cut_permit_on_a_segment_under_active_construction_rejected
    """
    ctx = fixtures.maple_in_construction(api)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]

    validate_error(
        api.create_cut_permit(
            cut_permit_payload(
                segment_id,
                applicant_utility="WATER",
                requested_start=CONSTRUCTION_CUT_START,
                requested_end=CONSTRUCTION_CUT_END,
                cut_area_sqft=CUT_AREA_SQFT,
                emergency=True,
            ),
            COORDINATOR,
        ),
        ApiErrorId.CUT_BLOCKED_ACTIVE_CONSTRUCTION,
        409,
    )

    _permits, meta = validate_paginated(
        api.list_cut_permits(COORDINATOR, {"segment_id": segment_id, "limit": 100})
    )
    assert meta["total_count"] == 0


# ----------------------------------------------------------------------
# The aggregate funding envelope
# ----------------------------------------------------------------------


def test_a_manual_allocation_beyond_the_funding_envelope_is_refused(api):
    """A hand-added row is measured against the same envelope the waterfall respects.

    PRD: "And the addition must not push `funded_cost_cents` above `funding_cents`,
    else `ERR_ALLOCATION_EXCEEDS_FUNDING`."

    PRD: "Manual adds require the scenario to be `DRAFT` or `COMPUTED`, since an
    `ADOPTED` or `SUPERSEDED` scenario is frozen and reports `ERR_SCENARIO_FROZEN`."

    PRD: "The manual row is created with `source` `MANUAL_ADD`, `allocation_status`
    `FUNDED`, `allocated_cents` equal to the candidate's `estimated_cost_cents`, and a
    `rank` one greater than the highest existing rank on the scenario; the parent then
    recomputes `allocation_count`, `funded_cost_cents` and `uncommitted_cents`, and its
    `version` increments."

    The scenario is DRAFT and the version is the one the create response published, so
    neither the frozen check nor the stale-read guard can be what fires.

    Design: Corner/validations/manual_allocation_pushing_funded_cost_past_the_funding_rejected
    """
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_ONLY)
    candidate = fixtures.candidate_for(ctx, "Maple St")
    assert_money(candidate["estimated_cost_cents"], MAPLE_CANDIDATE_COST)

    scenario = fixtures.create_scenario(
        api, ctx["survey"]["id"], funding_cents=TINY_FUNDING
    )
    assert scenario["scenario_status"] == "DRAFT"
    before_version = scenario["version"]

    validate_error(
        api.create_allocation(
            allocation_payload(scenario["id"], candidate["id"], before_version), OFFICER
        ),
        ApiErrorId.ALLOCATION_EXCEEDS_FUNDING,
        422,
    )

    after = fixtures.read_scenario(api, scenario["id"])
    assert after["scenario_status"] == "DRAFT"
    assert_scenario_totals(after, 0, 0, 0)
    # The refusal leaves the funding envelope and the committed total untouched.
    # `uncommitted_cents` is not asserted here: PRD 3.4 puts "all money and
    # projection outputs at zero or null until the first run" on a fresh DRAFT
    # scenario, so its value before the first run is not pinned by the PRD.
    assert_money(after["funding_cents"], TINY_FUNDING, "funding_cents")
    assert_money(after["committed_cents"], 0, "committed_cents")
    assert after["version"] == before_version

    _rows, meta = validate_paginated(
        api.list_allocations(OFFICER, {"scenario_id": scenario["id"], "limit": 100})
    )
    assert meta["total_count"] == 0


# ----------------------------------------------------------------------
# The conditional pass path on acceptance tests
# ----------------------------------------------------------------------


def test_a_pass_decision_on_a_computed_failure_is_refused_and_scores_nothing(api):
    """The pay-factor arithmetic binds the pass path and only the pass path.

    PRD: "The pay-factor arithmetic is binding on the pass path only: deciding `PASS`
    on a test whose `computed_outcome` is `FAIL` reports
    `ERR_TEST_DECISION_CONFLICTS_COMPUTED`, while `FAIL` and `RETEST` remain available
    regardless of the computed outcome."

    PRD: "Every test starts with `test_status` `SUBMITTED`, `decided_by_user_id` null
    and `decision_note` null, and each submission increments the line's `test_count`."

    PRD: "A `PASS` decision moves the test to `PASSED`, records `decided_by_user_id`
    and `decision_note`, moves the line's `work_state` from `IN_PROGRESS` to
    `WORK_COMPLETE` provided the decided test carries the highest `test_round` on that
    line, and copies the test's `computed_pay_factor` onto the line's `pay_factor`."

    PRD: "A new firm starts at `standing` `GOOD_STANDING` with
    `interim_performance_score` 100.0, `final_performance_score` null, and
    `passed_test_count`, `failed_test_count`, `remediation_event_count`,
    `days_late_total` and `accepted_project_count` all zero."

    The witness and the decider are different inspectors, so segregation of duties
    cannot mask the conflict, and the follow-up FAIL shows the asymmetry.

    Design: Corner/validations/pass_decision_on_a_computed_fail_test_rejected
    """
    ctx = fixtures.maple_in_construction(api)
    line_id = ctx["lines"]["Maple St"]["id"]
    submitted = fixtures.submit_test(
        api,
        line_id,
        core_density_pct=FAIL_DENSITY_PCT,
        iri_in_per_mi=FAIL_IRI,
        thickness_in=FAIL_THICKNESS_IN,
    )
    assert_pay_factor(submitted, FAIL_PAY_FACTOR, "FAIL")
    assert submitted["test_status"] == "SUBMITTED"

    validate_error(
        api.decide_acceptance_test(
            submitted["id"],
            acceptance_decision_payload("PASS", PASS_ATTEMPT_NOTE),
            INSPECTOR_DECIDER,
        ),
        ApiErrorId.TEST_DECISION_CONFLICTS_COMPUTED,
        422,
    )

    test_row = validate_success(api.get_acceptance_test(submitted["id"], INSPECTOR))
    assert test_row["test_status"] == "SUBMITTED"
    assert test_row["decided_by_user_id"] is None
    assert test_row["decision_note"] is None
    assert_pay_factor(test_row, FAIL_PAY_FACTOR, "FAIL")

    line = fixtures.read_line(api, line_id)
    assert_line_states(line, "IN_PROGRESS", "DELIVERED")
    assert line["pay_factor"] is None
    assert line["test_count"] == 1
    assert_project_states(
        fixtures.read_project(api, ctx["project"]["id"]), "IN_CONSTRUCTION", "TESTING"
    )

    scorecard = validate_success(
        api.get_contractor_scorecard(ctx["contractor"]["id"], ENGINEER)
    )
    assert scorecard["passed_test_count"] == 0
    assert scorecard["failed_test_count"] == 0
    assert scorecard["interim_performance_score"] == 100.0

    decided = fixtures.decide_test(api, submitted["id"], "FAIL", FAIL_NOTE)
    assert decided["test_status"] == "FAILED"
    assert decided["decided_by_user_id"] == INSPECTOR_DECIDER_USER_ID


# ----------------------------------------------------------------------
# Deferral eligibility
# ----------------------------------------------------------------------


def test_a_complaint_cannot_be_deferred_to_a_project_that_misses_its_street(api):
    """Eligibility is not just state and zone: the bundle must reach the block.

    PRD: "The deferral target must be eligible: a project whose `delivery_status` is
    anything other than `ACCEPTED` and which contains a non-removed line on this
    request's `segment_id`; anything else reports `ERR_TARGET_PROJECT_NOT_ELIGIBLE`."

    PRD: "Triage requires the request to still be `NEW`, else
    `ERR_SERVICE_REQUEST_NOT_NEW`, and — per §2.11 — never changes the segment's
    `open_service_request_count`."

    PRD: "A `disposition` of `DEFER_TO_CAPITAL` moves `request_status` from `NEW` to
    `DEFERRED_TO_CAPITAL`, stamps `triaged_at`, and sets `capital_project_id` to the
    supplied `target_project_id`, attaching the complaint to a resurfacing project so
    that it closes automatically when the street is rebuilt rather than being closed by
    a patch crew."

    Adding the missing line and re-triaging then succeeds, so neither the project's
    zone nor its delivery state was ever the problem.

    Design: Corner/validations/triage_deferring_to_a_project_without_the_segment_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, MAPLE_FIRST_HALF_LINE)
    project_id = ctx["project"]["id"]
    oak_segment = fixtures.segment_for(ctx, "Oak St")

    request = fixtures.file_service_request(
        api, oak_segment["id"], location_note=OAK_COMPLAINT_NOTE
    )
    assert request["request_status"] == "NEW"
    assert fixtures.read_segment(api, oak_segment["id"])["open_service_request_count"] == 1

    validate_error(
        api.triage_service_request(
            request["id"], triage_payload("DEFER_TO_CAPITAL", project_id), ENGINEER
        ),
        ApiErrorId.TARGET_PROJECT_NOT_ELIGIBLE,
        422,
    )

    unchanged = validate_success(api.get_service_request(request["id"], ENGINEER))
    assert unchanged["request_status"] == "NEW"
    assert unchanged["capital_project_id"] is None
    assert unchanged["triaged_at"] is None
    assert fixtures.read_segment(api, oak_segment["id"])["open_service_request_count"] == 1

    fixtures.add_line(
        api,
        project_id,
        oak_segment["id"],
        fixtures.candidate_for(ctx, "Oak St")["id"],
        SECOND_HALF_START,
        SECOND_HALF_END,
    )
    deferred = fixtures.triage_service_request(
        api, request["id"], "DEFER_TO_CAPITAL", project_id
    )
    assert deferred["request_status"] == "DEFERRED_TO_CAPITAL"
    assert deferred["capital_project_id"] == project_id
    assert deferred["triaged_at"] is not None
    assert fixtures.read_segment(api, oak_segment["id"])["open_service_request_count"] == 1


# ----------------------------------------------------------------------
# The award tolerance band
# ----------------------------------------------------------------------


def test_a_bid_far_below_the_estimate_is_refused_even_though_funding_allows_it(api):
    """The tolerance is two-sided and measured against the estimate, not the funding.

    PRD: "Then the two fiscal tests: `award_amount_cents` must not exceed the
    scenario's `uncommitted_cents`, else `ERR_SCENARIO_FUNDS_EXCEEDED`, and it must lie
    within 10 percent of the project's `project_total_estimate_cents` in either
    direction, else `ERR_AWARD_OUTSIDE_ESTIMATE_TOLERANCE`."

    PRD: "A successful award sets `contractor_id` and `award_amount_cents` on the
    project, adds the awarded amount to the scenario's `committed_cents`, recomputes
    the scenario's `uncommitted_cents` as `funding_cents` less `committed_cents`, and
    increments the scenario's `version` by 1."

    10,000,000 sits comfortably inside 20,000,000 of funding, so the funds test stays
    silent and only the deviation from 11,817,655 can be reporting.

    Design: Corner/validations/award_below_the_estimate_tolerance_band_rejected
    """
    ctx = fixtures.maple_bid_ready(api)
    project_id = ctx["project"]["id"]
    assert_project_estimate(
        ctx["project"], MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL
    )

    validate_error(
        api.award_project(
            project_id, award_payload(ctx["contractor"]["id"], LOW_BID), OFFICER_AWARDER
        ),
        ApiErrorId.AWARD_OUTSIDE_ESTIMATE_TOLERANCE,
        422,
    )

    project = fixtures.read_project(api, project_id)
    assert_project_states(project, "BID_READY", "NOT_STARTED")
    assert project["award_amount_cents"] is None
    assert project["contractor_id"] is None
    assert_scenario_funding(
        fixtures.read_scenario(api, ctx["scenario"]["id"]),
        FUNDING_STANDARD,
        0,
        FUNDING_STANDARD,
    )


def test_a_bid_inside_the_tolerance_band_is_accepted_and_commits_the_funding(api):
    """It is the deviation and not the absolute amount that the band measures.

    PRD: "Then the two fiscal tests: `award_amount_cents` must not exceed the
    scenario's `uncommitted_cents`, else `ERR_SCENARIO_FUNDS_EXCEEDED`, and it must lie
    within 10 percent of the project's `project_total_estimate_cents` in either
    direction, else `ERR_AWARD_OUTSIDE_ESTIMATE_TOLERANCE`."

    PRD: "A successful award sets `contractor_id` and `award_amount_cents` on the
    project, adds the awarded amount to the scenario's `committed_cents`, recomputes
    the scenario's `uncommitted_cents` as `funding_cents` less `committed_cents`, and
    increments the scenario's `version` by 1."

    Design: Corner/validations/award_below_the_estimate_tolerance_band_rejected
    """
    ctx = fixtures.maple_bid_ready(api)
    awarded = fixtures.award(
        api, ctx["project"]["id"], ctx["contractor"]["id"], IN_BAND_BID
    )
    assert_project_states(awarded, "AWARDED", "NOT_STARTED")
    assert_money(awarded["award_amount_cents"], IN_BAND_BID)
    assert awarded["contractor_id"] == ctx["contractor"]["id"]

    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])
    assert_scenario_funding(
        scenario, FUNDING_STANDARD, IN_BAND_BID, FUNDING_STANDARD - IN_BAND_BID
    )
    assert scenario["version"] > ctx["scenario"]["version"]


# ----------------------------------------------------------------------
# Two readiness rules guard BID_READY; this isolates the emptiness one
# ----------------------------------------------------------------------


def test_an_empty_but_fully_cleared_bundle_cannot_go_out_for_bid(api):
    """With every clearance in hand, emptiness is the only remaining objection.

    PRD: "It requires the project to be in `COORDINATING`, else
    `ERR_PROJECT_NOT_COORDINATING`; it requires at least one non-removed line, else
    `ERR_PROJECT_HAS_NO_SEGMENTS`; and it requires `clearance_outstanding_count` to
    have reached zero, meaning every utility row on the project is either `CLEARED` or
    `CLEARED_AFTER_WORK`, else `ERR_UTILITY_CLEARANCE_PENDING`."

    PRD: "Both adding and removing lines require the project's `delivery_status` to be
    `DRAFT` or `COORDINATING`; once the bundle has moved beyond coordination its scope
    is fixed and both operations report `ERR_PROJECT_SCOPE_LOCKED`."

    PRD: "The freed candidate returns to the pool, and which state it returns to
    depends on its history: a candidate with a null `override_reason` returns to
    `RECOMMENDED`, while a candidate carrying an `override_reason` returns to
    `OVERRIDDEN` with its override intact."

    The bundle is emptied while still coordinating, all four utilities then clear, and
    re-adding the line makes the very same advance succeed.

    Design: Corner/validations/bid_ready_on_an_empty_but_fully_cleared_project_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx, MAPLE_FIRST_HALF_LINE)
    project_id = ctx["project"]["id"]
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    candidate_id = fixtures.candidate_for(ctx, "Maple St")["id"]

    removed = validate_success(
        api.delete_project_segment(ctx["lines"]["Maple St"]["id"], ENGINEER)
    )
    assert removed["work_state"] == "REMOVED"
    assert fixtures.read_candidate(api, candidate_id)["candidate_status"] == "RECOMMENDED"

    ctx = fixtures.clear_all_coordinations(api, ctx)
    emptied = ctx["project"]
    assert emptied["clearance_outstanding_count"] == 0
    assert_project_scope(emptied, 0, 0.0)

    validate_error(
        api.advance_project(project_id, advance_payload("BID_READY"), ENGINEER),
        ApiErrorId.PROJECT_HAS_NO_SEGMENTS,
        422,
    )

    still_coordinating = fixtures.read_project(api, project_id)
    assert_project_states(still_coordinating, "COORDINATING", "NOT_STARTED")
    assert still_coordinating["clearance_outstanding_count"] == 0
    assert_project_scope(still_coordinating, 0, 0.0)

    fixtures.add_line(api, project_id, segment_id, candidate_id)
    priced = fixtures.advance(api, project_id, "BID_READY")
    assert_project_states(priced, "BID_READY", "NOT_STARTED")
    assert_project_scope(priced, 1, AREA_MAPLE)
    assert_project_estimate(priced, MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL)


# ----------------------------------------------------------------------
# The 72-hour notice runway, at the instant itself
# ----------------------------------------------------------------------


def test_a_notice_window_exactly_seventy_two_hours_out_is_accepted(api):
    """The lead-time comparison admits the boundary, so 72 hours exactly is enough.

    PRD: "The parking window must begin at least 72 hours after the logical clock
    stands at scheduling time; a shorter runway reports
    `ERR_NOTICE_LEAD_TIME_TOO_SHORT`, and per §2.10 that lead-time test runs *before*
    the overlap test."

    PRD: "`SCHEDULE` moves `notice_state` from `PENDING` to `SCHEDULED` and publishes
    the restriction: the engineer supplies `parking_restriction_start` and
    `parking_restriction_end` for the no-parking window, and a `driveway_access_plan`
    of `MAINTAINED` when driveways stay usable throughout, `LIMITED_NIGHTLY` when
    access is restored each night, or `BLOCKED_WITH_ALT` when access is blocked and an
    alternative is arranged."

    PRD: "A first schedule leaves `notice_round` at 1."

    The clock reads 2026-08-01T00:00:00Z, so 2026-08-04T00:00:00Z is the boundary
    instant itself.

    Design: Corner/validations/notice_scheduled_at_exactly_the_lead_time_boundary_succeeds
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, MAPLE_AND_OAK_LINES)
    maple_line = ctx["lines"]["Maple St"]
    assert_line_states(maple_line, "PLANNED", "PENDING")

    scheduled = validate_success(
        api.notice(
            maple_line["id"],
            schedule_notice_payload(
                NOTICE_BOUNDARY_START, NOTICE_BOUNDARY_END, ACCESS_MAINTAINED
            ),
            ENGINEER,
        )
    )
    assert_line_states(scheduled, "PLANNED", "SCHEDULED")
    assert scheduled["parking_restriction_start"].startswith("2026-08-04T00:00:00")
    assert scheduled["parking_restriction_end"].startswith("2026-08-18T00:00:00")
    assert scheduled["driveway_access_plan"] == ACCESS_MAINTAINED
    assert scheduled["notice_round"] == 1
    assert scheduled["notice_delivered_at"] is None


def test_a_notice_window_one_second_short_of_the_runway_is_refused(api):
    """One second inside the runway is inside the runway.

    PRD: "The parking window must begin at least 72 hours after the logical clock
    stands at scheduling time; a shorter runway reports
    `ERR_NOTICE_LEAD_TIME_TOO_SHORT`, and per §2.10 that lead-time test runs *before*
    the overlap test."

    PRD: "Creation copies `treatment_type` from the candidate and `line_area_sy` from
    the segment's `area_sy`, computes the line's `line_cost_cents`, and starts the line
    at `work_state` `PLANNED`, `notice_state` `PENDING` and `notice_round` 1, with
    `parking_restriction_start`, `parking_restriction_end`, `driveway_access_plan`,
    `notice_delivered_at` and `pay_factor` all null and `test_count` zero."

    The refused line sits on a different segment from the scheduled one, so the
    buffered-overlap rule cannot fire on it either way.

    Design: Corner/validations/notice_scheduled_at_exactly_the_lead_time_boundary_succeeds
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, MAPLE_AND_OAK_LINES)
    fixtures.schedule_notice(
        api,
        ctx["lines"]["Maple St"]["id"],
        NOTICE_BOUNDARY_START,
        NOTICE_BOUNDARY_END,
        ACCESS_MAINTAINED,
    )
    oak_line = ctx["lines"]["Oak St"]
    assert oak_line["segment_id"] != ctx["lines"]["Maple St"]["segment_id"]

    validate_error(
        api.notice(
            oak_line["id"],
            schedule_notice_payload(
                NOTICE_ONE_SECOND_SHORT_START,
                NOTICE_ONE_SECOND_SHORT_END,
                ACCESS_MAINTAINED,
            ),
            ENGINEER,
        ),
        ApiErrorId.NOTICE_LEAD_TIME_TOO_SHORT,
        422,
    )

    after = fixtures.read_line(api, oak_line["id"])
    assert_line_states(after, "PLANNED", "PENDING")
    assert after["parking_restriction_start"] is None
    assert after["parking_restriction_end"] is None
    assert after["driveway_access_plan"] is None
    assert_money(after["line_cost_cents"], OAK_LINE_COST)
