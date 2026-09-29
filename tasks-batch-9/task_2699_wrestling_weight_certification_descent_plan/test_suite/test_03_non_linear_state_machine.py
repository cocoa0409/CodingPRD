"""
Branching and cyclic state shapes: the assessment hydration fork and the
descent-plan breach/revision cycle.

Two families of behaviour are exercised here, both of them non-linear.

The first is the fork the requirements put on assessment finalization (§3.3):
a single comparison of the sample's ``urine_specific_gravity`` against the
season's ``hydration_max_specific_gravity`` selects between ``VALIDATED`` and
``HYDRATION_FAILED``, and the two arms have deliberately divergent side-effect
sets — the validated arm computes four certified figures and repoints the
wrestler, while the hydration-failed arm leaves all four null, leaves the
wrestler's certification dimension exactly where it was, and raises a
``HYDRATION_FAIL`` health flag onto the team's severity ledger.  Neither arm
returns to ``DRAFT``: ``HYDRATION_FAILED`` is terminal, so the fork cannot be
re-run.

The second is the loop the requirements put on a descent plan (§3.5, §3.6):
``CERTIFIED → BREACHED → CERTIFIED``.  The season compliance run judges the due
milestones, declares the breach once ``missed_milestone_count`` reaches the
season's ``plan_breach_limit``, and raises a ``PLAN_BREACH`` flag; the coach's
revision then waives the pending schedule, regenerates it from a new start date
with continued week numbering, and returns the plan to ``CERTIFIED`` — without
resetting the missed count that the breach put on the record.
"""

from typing import Any, Dict, List

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_all_null,
    assert_flag_severity_matches_source,
    assert_milestone,
    assert_ordered_by,
    assert_row_count,
    assert_severity_ledger,
    assert_weight_equals,
    expected_lean_body_weight,
    expected_min_eligible_class,
    expected_minimum_certified_weight,
    plus_weeks,
    smallest_class_at_or_above,
)
from test_helpers.constants import (
    ASSESSED_AT,
    ASSESSMENT_HYDRATION_FAILED,
    ASSESSMENT_VALIDATED,
    CANON_BODY_FAT_PCT,
    CANON_MEASURED_WEIGHT_LBS,
    CANON_TARGET_CLASS_LBS,
    CANON_USG_FAIL,
    CANON_USG_PASS,
    DEFAULT_HYDRATION_MAX_SPECIFIC_GRAVITY,
    DEFAULT_MIN_BODY_FAT_PCT_MALE,
    ELIGIBILITY_ELIGIBLE,
    FLAG_HYDRATION_FAIL,
    FLAG_OPEN,
    FLAG_PLAN_BREACH,
    MILESTONE_MISSED,
    MILESTONE_SCHEDULED,
    MILESTONE_WAIVED,
    PLAN_BREACHED,
    PLAN_CERTIFIED,
    SEX_MALE,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEEKLY_STEP_MILESTONE_DATES,
    WEEKLY_STEP_SCHEDULE,
    WEEKLY_STEP_TOTAL_WEEKS,
    WRESTLER_CERTIFIED,
    WRESTLER_PROVISIONAL,
    WRESTLER_UNCERTIFIED,
)
from test_helpers.test_users import STATE_OFFICE, assessor_headers, coach_headers

# The four certified figures the validated arm produces and the hydration-failed
# arm leaves null (§3.3).
CERTIFIED_FIGURE_FIELDS = (
    "lean_body_weight_lbs",
    "minimum_certified_weight_lbs",
    "min_weight_class_lbs",
    "alpha_weight_lbs",
)

# The instant the compliance run is swept at: three of the six weekly milestones
# of a schedule starting 2026-11-02 have come due by this date.
SWEEP_INSTANT = "2026-11-20T00:00:00Z"

# The start date the breached plan is revised onto, strictly after every
# milestone still pending on the plan.
REVISED_START_DATE = "2026-12-14"


def _expected_certified_figures() -> Dict[str, Any]:
    """The figures §3.3 derives for the canonical male measurement.

    The rounding order is pinned by the requirements: the lean weight is rounded
    to one decimal place before it is divided by one minus the body-fat floor.
    """
    lean = expected_lean_body_weight(CANON_MEASURED_WEIGHT_LBS, CANON_BODY_FAT_PCT)
    minimum = expected_minimum_certified_weight(
        CANON_MEASURED_WEIGHT_LBS, CANON_BODY_FAT_PCT, DEFAULT_MIN_BODY_FAT_PCT_MALE
    )
    return {
        "lean_body_weight_lbs": lean,
        "minimum_certified_weight_lbs": minimum,
        "min_weight_class_lbs": smallest_class_at_or_above(minimum),
        "alpha_weight_lbs": CANON_MEASURED_WEIGHT_LBS,
    }


def _milestone_at(rows: List[Dict[str, Any]], week_index: int) -> Dict[str, Any]:
    """The single milestone row carrying ``week_index`` on a plan's schedule."""
    matches = [row for row in rows if row.get("week_index") == week_index]
    assert len(matches) == 1, (
        f"expected exactly one milestone at week_index {week_index}, "
        f"found {len(matches)}"
    )
    return matches[0]


def _flags_of(api, wrestler_id: str, expected_count: int) -> List[Dict[str, Any]]:
    """The wrestler's health flags, asserting how many the listing carries."""
    return assert_row_count(
        api.list_health_flags(STATE_OFFICE, {"wrestler_id": wrestler_id, "limit": 100}),
        expected_count,
        f"health flags of wrestler {wrestler_id}",
    )


def _fork_setup(api) -> Dict[str, Any]:
    """Two draft assessments on two wrestlers, one hydrated and one not.

    Both readings are taken by the same certified assessor on the same UTC
    calendar day, which is inside the assessor's daily capacity of three.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    hydrated = fixtures.create_wrestler(api, scenario.team_id, "Alex Mercer", SEX_MALE, 11)
    dehydrated = fixtures.create_wrestler(api, scenario.team_id, "Blake Ito", SEX_MALE, 12)
    assessment_a = fixtures.create_assessment(
        api,
        hydrated["id"],
        assessor["id"],
        assessed_at=ASSESSED_AT,
        measured_weight_lbs=CANON_MEASURED_WEIGHT_LBS,
        body_fat_pct=CANON_BODY_FAT_PCT,
        urine_specific_gravity=CANON_USG_PASS,
    )
    assessment_b = fixtures.create_assessment(
        api,
        dehydrated["id"],
        assessor["id"],
        assessed_at="2026-11-01T10:00:00Z",
        measured_weight_lbs=165.0,
        body_fat_pct=16.0,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    return {
        "season_id": scenario.season_id,
        "team_id": scenario.team_id,
        "assessor_id": assessor["id"],
        "assessor_auth": assessor_headers(assessor["id"]),
        "wrestler_a": hydrated["id"],
        "wrestler_b": dehydrated["id"],
        "assess_a": assessment_a["id"],
        "assess_b": assessment_b["id"],
    }


# ── The hydration fork on assessment finalization ────────────────────

def test_hydration_fork_validated_arm_produces_every_certified_figure(api):
    """A hydrated reading takes the DRAFT -> VALIDATED arm of the fork.

    Per §3.3 the arm sets ``hydration_passed`` true, computes the lean body
    weight, the minimum certified weight, the minimum weight class and the alpha
    weight, repoints the wrestler's ``source_assessment_id`` and moves the
    certification dimension ``UNCERTIFIED -> PROVISIONAL``.  No health flag
    belongs to this arm.

    Design: Difficulty/non_linear_state_machine/assessment_hydration_fork_divergent_side_effects
    """
    setup = _fork_setup(api)
    expected = _expected_certified_figures()

    finalized = validate_success(
        api.finalize_assessment(setup["assess_a"], setup["assessor_auth"])
    )

    assert finalized["status"] == ASSESSMENT_VALIDATED
    assert finalized["hydration_passed"] is True
    assert_weight_equals(
        finalized["lean_body_weight_lbs"],
        expected["lean_body_weight_lbs"],
        "lean_body_weight_lbs",
    )
    assert_weight_equals(
        finalized["minimum_certified_weight_lbs"],
        expected["minimum_certified_weight_lbs"],
        "minimum_certified_weight_lbs",
    )
    assert finalized["min_weight_class_lbs"] == expected["min_weight_class_lbs"]
    assert_weight_equals(
        finalized["alpha_weight_lbs"],
        expected["alpha_weight_lbs"],
        "alpha_weight_lbs",
    )

    wrestler = fixtures.read_wrestler(api, setup["wrestler_a"])
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert wrestler["source_assessment_id"] == setup["assess_a"]

    # The validated arm raises nothing: the flag ledger is the other arm's work.
    _flags_of(api, setup["wrestler_a"], 0)


def test_hydration_fork_failed_arm_leaves_the_figures_null_and_raises_a_flag(api):
    """A dehydrated reading takes the DRAFT -> HYDRATION_FAILED arm instead.

    Per §3.3 the divergence is total: ``hydration_passed`` is false, all four
    certified figures stay null, the wrestler's certification dimension and
    ``source_assessment_id`` are untouched, and a ``HYDRATION_FAIL`` flag of
    severity 1 opens on the wrestler.  §2.9 then puts that severity on the team's
    ledger, which derives the ``WATCH`` posture.

    Design: Difficulty/non_linear_state_machine/assessment_hydration_fork_divergent_side_effects
    """
    setup = _fork_setup(api)

    # Finalize both arms of the same fork, so the ledger below is attributable.
    validate_success(api.finalize_assessment(setup["assess_a"], setup["assessor_auth"]))
    finalized = validate_success(
        api.finalize_assessment(setup["assess_b"], setup["assessor_auth"])
    )

    assert finalized["status"] == ASSESSMENT_HYDRATION_FAILED
    assert finalized["hydration_passed"] is False
    assert_all_null(finalized, CERTIFIED_FIGURE_FIELDS, "hydration-failed assessment")

    wrestler = fixtures.read_wrestler(api, setup["wrestler_b"])
    assert wrestler["certification_status"] == WRESTLER_UNCERTIFIED
    assert wrestler["source_assessment_id"] is None

    flags = _flags_of(api, setup["wrestler_b"], 1)
    flag = flags[0]
    assert flag["source"] == FLAG_HYDRATION_FAIL
    assert flag["severity"] == 1
    assert_flag_severity_matches_source(flag)
    assert flag["status"] == FLAG_OPEN
    assert flag["weigh_in_id"] is None

    # The hydrated wrestler contributes nothing, so the ledger reads exactly 1.
    _flags_of(api, setup["wrestler_a"], 0)
    assert_severity_ledger(fixtures.read_team(api, setup["team_id"]), 1)


def test_hydration_failed_is_terminal_and_the_fork_cannot_be_re_run(api):
    """``HYDRATION_FAILED`` admits no second finalize.

    §3.3 requires the from-state to be ``DRAFT`` and calls a second finalize of
    the same assessment ``ERR_ASSESSMENT_INVALID_STATE``; a failed hydration
    reading is redone as a new assessment, never rehabilitated in place.  The
    refused call leaves the row and its raised flag exactly as they were.

    Design: Difficulty/non_linear_state_machine/assessment_hydration_fork_divergent_side_effects
    """
    setup = _fork_setup(api)
    validate_success(api.finalize_assessment(setup["assess_b"], setup["assessor_auth"]))

    refused = api.finalize_assessment(setup["assess_b"], setup["assessor_auth"])
    validate_error(refused, api_errors.ERR_ASSESSMENT_INVALID_STATE, 409)

    unchanged = fixtures.read_assessment(api, setup["assess_b"])
    assert unchanged["status"] == ASSESSMENT_HYDRATION_FAILED
    assert unchanged["hydration_passed"] is False
    assert_all_null(unchanged, CERTIFIED_FIGURE_FIELDS, "hydration-failed assessment")
    _flags_of(api, setup["wrestler_b"], 1)


@pytest.mark.parametrize(
    "urine_specific_gravity,expected_status,expected_passed",
    [
        (CANON_USG_PASS, ASSESSMENT_VALIDATED, True),
        (DEFAULT_HYDRATION_MAX_SPECIFIC_GRAVITY, ASSESSMENT_VALIDATED, True),
        (CANON_USG_FAIL, ASSESSMENT_HYDRATION_FAILED, False),
    ],
)
def test_fork_arm_is_selected_purely_by_the_hydration_comparison(
    api, urine_specific_gravity, expected_status, expected_passed
):
    """One comparison picks the arm, and landing on the ceiling passes.

    §3.3 sets ``hydration_passed`` true when the sample's specific gravity is
    less than or equal to the season's ``hydration_max_specific_gravity`` and
    false when it is strictly greater, and §2.6 states that landing exactly on a
    limit is permitted.  The certified figures follow the arm and nothing else.

    Design: Difficulty/non_linear_state_machine/assessment_hydration_fork_divergent_side_effects
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    assessment = fixtures.create_assessment(
        api,
        wrestler["id"],
        assessor["id"],
        urine_specific_gravity=urine_specific_gravity,
    )

    finalized = validate_success(
        api.finalize_assessment(assessment["id"], assessor_headers(assessor["id"]))
    )

    assert finalized["status"] == expected_status
    assert finalized["hydration_passed"] is expected_passed
    if expected_passed:
        expected = _expected_certified_figures()
        assert_weight_equals(
            finalized["minimum_certified_weight_lbs"],
            expected["minimum_certified_weight_lbs"],
            "minimum_certified_weight_lbs",
        )
        assert finalized["min_weight_class_lbs"] == expected["min_weight_class_lbs"]
        assert fixtures.read_wrestler(api, wrestler["id"])["certification_status"] == (
            WRESTLER_PROVISIONAL
        )
    else:
        assert_all_null(finalized, CERTIFIED_FIGURE_FIELDS, "finalized assessment")
        assert fixtures.read_wrestler(api, wrestler["id"])["certification_status"] == (
            WRESTLER_UNCERTIFIED
        )


# ── The descent-plan breach and revision cycle ───────────────────────

def _breached_plan(api) -> fixtures.Scenario:
    """A certified WEEKLY_STEP plan swept into ``BREACHED``.

    The plan starts 2026-11-02 and no weigh-in exists for the wrestler, so once
    the clock stands at 2026-11-20 the three milestones that have come due all
    evaluate as ``MISSED`` — which is at or above the season's
    ``plan_breach_limit`` of two.
    """
    scenario = fixtures.certified_wrestler(api)
    assert scenario.plan["status"] == PLAN_CERTIFIED
    assert scenario.plan["target_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert scenario.plan["total_weeks"] == WEEKLY_STEP_TOTAL_WEEKS
    assert scenario.plan["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT
    fixtures.move_clock(api, SWEEP_INSTANT)
    validate_success(api.run_compliance(scenario.season_id, STATE_OFFICE))
    return scenario


def test_compliance_run_takes_the_certified_plan_to_breached(api):
    """The sweep judges only the due milestones and then declares the breach.

    §3.6 considers a milestone only when its ``effective_date`` is on or before
    the clock date, so the three weeks dated 2026-11-02, 11-09 and 11-16 are
    judged and the three later weeks stay ``SCHEDULED``.  With no candidate
    weigh-in inside any evaluation window each judged milestone becomes
    ``MISSED`` with ``evaluated_recorded_weight_lbs`` still null, and a
    ``missed_milestone_count`` of three reaches the ``plan_breach_limit`` of two,
    which moves the plan ``CERTIFIED -> BREACHED`` and increments
    ``breach_count``.

    Design: Difficulty/non_linear_state_machine/descent_plan_breach_revision_cycle
    """
    scenario = _breached_plan(api)

    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["status"] == PLAN_BREACHED
    assert plan["breach_count"] == 1
    assert plan["missed_milestone_count"] == 3

    rows = fixtures.milestones_of(api, scenario.plan_id)
    assert len(rows) == WEEKLY_STEP_MILESTONE_COUNT
    assert_ordered_by(rows, "week_index", "plan milestones")
    for week_index in (0, 1, 2):
        milestone = _milestone_at(rows, week_index)
        assert milestone["effective_date"] == WEEKLY_STEP_MILESTONE_DATES[week_index]
        assert milestone["status"] == MILESTONE_MISSED
        assert milestone["evaluated_recorded_weight_lbs"] is None
    for week_index in (3, 4, 5):
        milestone = _milestone_at(rows, week_index)
        assert milestone["effective_date"] == WEEKLY_STEP_MILESTONE_DATES[week_index]
        assert milestone["status"] == MILESTONE_SCHEDULED


def test_plan_breach_raises_a_flag_without_moving_the_certification_dimension(api):
    """The breach is the only thing that reaches the wrestler's team.

    §3.6 raises a ``PLAN_BREACH`` flag of severity 3 in ``OPEN`` when a plan
    becomes breached and recomputes the team's ledger and posture; §2.9 derives
    ``WATCH`` from a total of three.  §3.9 leaves the wrestler's certification
    dimension alone — the plan cycle never touches it — and because the team did
    not land on ``PROBATION`` the eligibility dimension is not demoted either.

    Design: Difficulty/non_linear_state_machine/descent_plan_breach_revision_cycle
    """
    scenario = _breached_plan(api)

    flags = _flags_of(api, scenario.wrestler_id, 1)
    flag = flags[0]
    assert flag["source"] == FLAG_PLAN_BREACH
    assert flag["severity"] == 3
    assert_flag_severity_matches_source(flag)
    assert flag["status"] == FLAG_OPEN
    assert flag["weigh_in_id"] is None

    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 3)

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_ELIGIBLE


def test_revision_closes_the_cycle_back_to_certified_with_monotone_counters(api):
    """``BREACHED -> CERTIFIED`` keeps the breach on the record.

    §3.6 returns a revised plan to ``CERTIFIED``, increments ``revision_count``,
    and emphatically does not reset ``missed_milestone_count``; ``breach_count``
    likewise stays where the breach left it.  ``milestone_count`` becomes the
    total number of milestone rows on the plan — the three ``MISSED`` weeks, the
    three waived ones and the six regenerated ones — and the variant's schedule,
    recomputed from the same alpha weight, rate and target, still arrives in five
    weeks.

    Design: Difficulty/non_linear_state_machine/descent_plan_breach_revision_cycle
    """
    scenario = _breached_plan(api)

    revised = validate_success(
        api.revise_descent_plan(
            scenario.plan_id,
            factories.plan_revision_payload(REVISED_START_DATE),
            coach_headers(scenario.team_id),
        )
    )

    assert revised["status"] == PLAN_CERTIFIED
    assert revised["revision_count"] == 1
    assert revised["breach_count"] == 1
    assert revised["missed_milestone_count"] == 3
    assert revised["milestone_count"] == 12
    assert revised["total_weeks"] == WEEKLY_STEP_TOTAL_WEEKS

    # The same figures are readable back through the plan itself.
    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["status"] == PLAN_CERTIFIED
    assert plan["revision_count"] == 1
    assert plan["breach_count"] == 1
    assert plan["missed_milestone_count"] == 3
    assert plan["milestone_count"] == 12


def test_revision_waives_the_pending_weeks_and_continues_the_numbering(api):
    """The delicate part of a revision is what happens to the old schedule.

    §3.6 retains every still-``SCHEDULED`` milestone dated strictly before the
    new ``plan_start_date`` as ``WAIVED`` history, leaves the already-judged rows
    exactly where they are, and numbers the regenerated rows from one greater
    than the highest ``week_index`` still present.  The k-th regenerated row
    therefore carries the new start date advanced by seven days times k together
    with the variant's week-k allowable weight, even though its stored
    ``week_index`` is offset by the continuation.

    Design: Difficulty/non_linear_state_machine/descent_plan_breach_revision_cycle
    """
    scenario = _breached_plan(api)
    minimum_certified = fixtures.read_wrestler(api, scenario.wrestler_id)[
        "minimum_certified_weight_lbs"
    ]

    validate_success(
        api.revise_descent_plan(
            scenario.plan_id,
            factories.plan_revision_payload(REVISED_START_DATE),
            coach_headers(scenario.team_id),
        )
    )

    waived = assert_row_count(
        api.list_plan_milestones(
            scenario.plan_id, STATE_OFFICE, {"status": MILESTONE_WAIVED, "limit": 100}
        ),
        3,
        "waived milestones",
    )
    assert [row["week_index"] for row in waived] == [3, 4, 5]

    missed = assert_row_count(
        api.list_plan_milestones(
            scenario.plan_id, STATE_OFFICE, {"status": MILESTONE_MISSED, "limit": 100}
        ),
        3,
        "missed milestones",
    )
    assert [row["week_index"] for row in missed] == [0, 1, 2]

    rows = fixtures.milestones_of(api, scenario.plan_id)
    assert len(rows) == 12
    assert_ordered_by(rows, "week_index", "plan milestones")

    # Six regenerated rows, numbered from one past the highest retained index.
    for offset, allowable in enumerate(WEEKLY_STEP_SCHEDULE):
        week_index = WEEKLY_STEP_MILESTONE_COUNT + offset
        assert_milestone(
            _milestone_at(rows, week_index),
            week_index=week_index,
            effective_date=plus_weeks(REVISED_START_DATE, offset),
            allowable_weight_lbs=allowable,
            min_eligible_class_lbs=expected_min_eligible_class(
                allowable, minimum_certified
            ),
            status=MILESTONE_SCHEDULED,
            label=f"regenerated milestone at week {week_index}",
        )

    # The two ends of the regenerated run, stated explicitly.
    first_regenerated = _milestone_at(rows, 6)
    assert first_regenerated["effective_date"] == REVISED_START_DATE
    assert_weight_equals(
        first_regenerated["allowable_weight_lbs"],
        WEEKLY_STEP_SCHEDULE[0],
        "week 6 allowable_weight_lbs",
    )
    last_regenerated = _milestone_at(rows, 11)
    assert last_regenerated["effective_date"] == "2027-01-18"
    assert_weight_equals(
        last_regenerated["allowable_weight_lbs"],
        WEEKLY_STEP_SCHEDULE[-1],
        "week 11 allowable_weight_lbs",
    )
