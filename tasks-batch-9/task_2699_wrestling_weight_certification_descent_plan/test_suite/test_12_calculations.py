"""
The derived-figure arithmetic of the certification regime.

Every formula the requirements pin is exercised here through the declared
endpoints: the two-stage minimum-certified-weight computation of §3.3 with its
sex-selected body-fat floor and its pinned rounding order, the audit discrepancy
scoring of §3.9 with its minimum-sample-count gate, the half-open milestone
evaluation window of §3.6, the three-key seed ranking expression of §3.8, the
severity-ledger aggregation and posture bands of §2.9, the four-step eligibility
floor of §3.7 with its hard-floor clamp, and the capped consecutive-day weigh-in
allowance of §3.8.

Weights, allowances and body-fat percentages are carried to one decimal place
rounded half up (§2.6); audit discrepancy figures are the sole two-decimal
exception.  Every reading is sent as a JSON number.  The server is restarted
before each test, so the database starts empty and the logical clock starts at
its default instant.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ERR_CLASS_BELOW_CERTIFIED_MINIMUM
from test_helpers.assertions import (
    assert_flag_severity_matches_source,
    assert_severity_ledger,
    assert_weight_equals,
    expected_consecutive_day_allowance,
    expected_lowest_eligible_class,
    expected_seed_integrity_sum,
    expected_weigh_in_result,
)
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    ASSESSMENT_HYDRATION_FAILED,
    ASSESSMENT_VALIDATED,
    ASSESSOR_CERTIFIED,
    AUDIT_INCONCLUSIVE,
    AUDIT_PASS,
    AUDIT_TYPE_ASSESSOR_SAMPLE,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_MIN_WEIGHT_CLASS_LBS,
    CANON_TARGET_CLASS_LBS,
    DEFAULT_MAX_CONSECUTIVE_DAY_ALLOWANCE_LBS,
    ELIGIBILITY_INELIGIBLE,
    ENTRY_SEEDED,
    ENTRY_WEIGHED_IN,
    EVENT_SEEDED,
    EVENT_TYPE_DUAL,
    EVENT_TYPE_TOURNAMENT,
    FLAG_HYDRATION_FAIL,
    FLAG_OPEN,
    MILESTONE_MET,
    MILESTONE_MISSED,
    MILESTONE_SCHEDULED,
    OUTCOME_BLOCKED_CLASS_BELOW_MINIMUM,
    OUTCOME_CLEARED,
    PLAN_CERTIFIED,
    PLAN_START_DATE,
    SCORING_SAMPLE_MEAN,
    SCORING_WORST_CASE,
    SEX_FEMALE,
    SEX_MALE,
    TEAM_CLEAR,
    TEAM_PROBATION,
    TEAM_WATCH,
    WEIGH_IN_FAIL,
    WEIGH_IN_PASS,
    WEIGH_IN_PASS_WITH_ALLOWANCE,
    WRESTLER_PROVISIONAL,
    WRESTLER_UNCERTIFIED,
)
from test_helpers.test_users import STATE_OFFICE, assessor_headers


# ── Local helpers ────────────────────────────────────────────────────

def _open_program(api, **season_overrides):
    """An open season carrying one team and one certified assessor."""
    scenario = fixtures.open_season_with_team(api, **season_overrides)
    assessor = fixtures.create_certified_assessor(api)
    scenario.update(assessor=assessor, assessor_id=assessor["id"])
    return scenario


def _finalize(api, assessment_id, assessor_id):
    """Finalize one assessment and return the mutated row."""
    return validate_success(
        api.finalize_assessment(assessment_id, assessor_headers(assessor_id))
    )


def _milestones(api, plan_id):
    """The plan's milestone rows, in week-index ascending order."""
    rows, _meta = validate_paginated(
        api.list_plan_milestones(plan_id, STATE_OFFICE, {"limit": 100})
    )
    return rows


def _certify_at_target_class(api, scenario, full_name, assessed_at):
    """Roster, assess and certify one wrestler onto a plan to the target class."""
    wrestler = fixtures.create_wrestler(api, scenario.team_id, full_name)
    assessment = fixtures.create_validated_assessment(
        api, wrestler["id"], scenario.assessor_id, assessed_at=assessed_at
    )
    fixtures.create_certified_plan(
        api,
        wrestler["id"],
        scenario.team_id,
        assessment["id"],
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
    )
    return wrestler["id"]


# A measured weight of 150.0 pounds read three ways, straddling the class
# boundary from all three sides.  Each row is
# (name, assessed_at, body_fat_pct, lean weight, minimum, minimum class).
_BOUNDARY_READINGS = [
    ("Exact Boundary", "2026-11-01T09:00:00Z", 7.0, 139.5, 150.0, 150),
    ("Below Floor", "2026-11-01T09:30:00Z", 6.0, 141.0, 151.6, 157),
    ("Above Floor", "2026-11-01T10:00:00Z", 8.0, 138.0, 148.4, 150),
]

_BOUNDARY_MEASURED_WEIGHT_LBS = 150.0


# ── The minimum certified weight at the class boundary ───────────────

def test_minimum_certified_weight_selects_the_class_it_lands_on(api):
    """An inclusive comparison certifies into the class the minimum equals.

    Three wrestlers read at the identical 150.0 pounds diverge only on body-fat
    percentage.  Per §3.3 the lean weight is the measurement times one minus the
    fat fraction rounded to one decimal, the minimum is that already-rounded lean
    weight divided by one minus the 7.0 percent male floor, and the minimum class
    is the smallest ladder member greater than or equal to it — so a minimum of
    exactly 150.0 certifies into class 150 rather than stepping up to 157 (§2.6).

    Design: Corner/calculations/minimum_certified_weight_at_and_around_class_boundary
    """
    scenario = _open_program(api)

    for name, assessed_at, body_fat_pct, lean, minimum, min_class in _BOUNDARY_READINGS:
        wrestler = fixtures.create_wrestler(api, scenario.team_id, name)
        draft = fixtures.create_assessment(
            api,
            wrestler["id"],
            scenario.assessor_id,
            assessed_at=assessed_at,
            measured_weight_lbs=_BOUNDARY_MEASURED_WEIGHT_LBS,
            body_fat_pct=body_fat_pct,
        )
        finalized = _finalize(api, draft["id"], scenario.assessor_id)

        assert_weight_equals(
            finalized["lean_body_weight_lbs"], lean, f"{name} lean_body_weight_lbs"
        )
        assert_weight_equals(
            finalized["minimum_certified_weight_lbs"],
            minimum,
            f"{name} minimum_certified_weight_lbs",
        )
        assert finalized["min_weight_class_lbs"] == min_class, (
            f"{name}: a minimum of {minimum} selects class {min_class}, "
            f"got {finalized['min_weight_class_lbs']!r}"
        )


def test_boundary_readings_keep_the_measurement_as_the_descent_baseline(api):
    """The measured weight is carried through untouched and only certification moves.

    Per §3.3 ``alpha_weight_lbs`` is the assessment's ``measured_weight_lbs``
    unchanged, the validated arm moves the wrestler's certification dimension
    ``UNCERTIFIED -> PROVISIONAL``, and the eligibility dimension is deliberately
    left exactly as it was — which for a freshly rostered wrestler is
    ``INELIGIBLE`` (§3.1).

    Design: Corner/calculations/minimum_certified_weight_at_and_around_class_boundary
    """
    scenario = _open_program(api)

    for name, assessed_at, body_fat_pct, _lean, _minimum, _class in _BOUNDARY_READINGS:
        wrestler = fixtures.create_wrestler(api, scenario.team_id, name)
        draft = fixtures.create_assessment(
            api,
            wrestler["id"],
            scenario.assessor_id,
            assessed_at=assessed_at,
            measured_weight_lbs=_BOUNDARY_MEASURED_WEIGHT_LBS,
            body_fat_pct=body_fat_pct,
        )
        finalized = _finalize(api, draft["id"], scenario.assessor_id)

        assert finalized["status"] == ASSESSMENT_VALIDATED, (
            f"{name}: a hydrated reading validates, got {finalized['status']!r}"
        )
        assert_weight_equals(
            finalized["alpha_weight_lbs"],
            _BOUNDARY_MEASURED_WEIGHT_LBS,
            f"{name} alpha_weight_lbs",
        )

        stored = fixtures.read_wrestler(api, wrestler["id"])
        assert stored["certification_status"] == WRESTLER_PROVISIONAL, (
            f"{name}: expected certification_status PROVISIONAL, "
            f"got {stored['certification_status']!r}"
        )
        assert stored["eligibility_status"] == ELIGIBILITY_INELIGIBLE, (
            f"{name}: the eligibility dimension does not move on validation, "
            f"got {stored['eligibility_status']!r}"
        )


# ── The sex-selected body-fat floor ──────────────────────────────────

def test_body_fat_floor_is_taken_from_the_wrestlers_own_sex_column(api):
    """Identical measurements diverge purely on the sex-selected floor constant.

    Per §3.3 the floor is ``min_body_fat_pct_female`` (12.0 by default) when the
    wrestler is ``F`` and ``min_body_fat_pct_male`` (7.0) when the wrestler is
    ``M``.  A 130.0 pound reading at 12.0 percent body fat gives the same
    114.4 pound lean weight either way, but 114.4 divided by 0.88 is 130.0 and
    selects class 132, while 114.4 divided by 0.93 is 123.0107 — 123.0 at one
    decimal place — and selects class 126.

    Design: Corner/calculations/minimum_certified_weight_uses_sex_specific_floor_constant
    """
    scenario = _open_program(api)

    female = fixtures.create_wrestler(
        api, scenario.team_id, "Rae Feldman", sex=SEX_FEMALE, grade=10
    )
    male = fixtures.create_wrestler(
        api, scenario.team_id, "Ray Feldman", sex=SEX_MALE, grade=10
    )

    female_draft = fixtures.create_assessment(
        api,
        female["id"],
        scenario.assessor_id,
        assessed_at="2026-11-01T09:00:00Z",
        measured_weight_lbs=130.0,
        body_fat_pct=12.0,
        urine_specific_gravity=1.018,
    )
    female_final = _finalize(api, female_draft["id"], scenario.assessor_id)

    male_draft = fixtures.create_assessment(
        api,
        male["id"],
        scenario.assessor_id,
        assessed_at="2026-11-01T09:30:00Z",
        measured_weight_lbs=130.0,
        body_fat_pct=12.0,
        urine_specific_gravity=1.018,
    )
    male_final = _finalize(api, male_draft["id"], scenario.assessor_id)

    # The lean-weight step reads no floor constant at all, so it is identical.
    assert_weight_equals(
        female_final["lean_body_weight_lbs"], 114.4, "female lean_body_weight_lbs"
    )
    assert_weight_equals(
        male_final["lean_body_weight_lbs"], 114.4, "male lean_body_weight_lbs"
    )

    assert_weight_equals(
        female_final["minimum_certified_weight_lbs"],
        130.0,
        "female minimum_certified_weight_lbs",
    )
    assert female_final["min_weight_class_lbs"] == 132, (
        "a 130.0 minimum selects class 132, got "
        f"{female_final['min_weight_class_lbs']!r}"
    )

    assert_weight_equals(
        male_final["minimum_certified_weight_lbs"],
        123.0,
        "male minimum_certified_weight_lbs",
    )
    assert male_final["min_weight_class_lbs"] == 126, (
        "a 123.0 minimum selects class 126, got "
        f"{male_final['min_weight_class_lbs']!r}"
    )


# ── The pinned two-stage rounding order ──────────────────────────────

def test_lean_weight_is_rounded_before_it_enters_the_division(api):
    """The already-rounded lean weight is what the division consumes.

    Per §3.3 and §2.6 an intermediate value the specification says is rounded must
    be rounded before it is used as an input to the next step.  A 121.0 pound
    reading at 13.1 percent body fat gives 105.149 pounds of lean mass, rounded to
    105.1; 105.1 divided by 0.93 is 113.0107, so the minimum is 113.0 and the
    minimum class is 113.  Carrying the unrounded 105.149 into the division would
    give 113.1 and would exclude class 113 in favour of 120 — a full class apart.

    Design: Corner/calculations/minimum_certified_weight_double_rounding_order_precision
    """
    scenario = _open_program(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id, "Casey Lin", grade=9)

    draft = fixtures.create_assessment(
        api,
        wrestler["id"],
        scenario.assessor_id,
        assessed_at="2026-11-01T09:00:00Z",
        measured_weight_lbs=121.0,
        body_fat_pct=13.1,
        urine_specific_gravity=1.019,
    )
    finalized = _finalize(api, draft["id"], scenario.assessor_id)

    assert_weight_equals(
        finalized["lean_body_weight_lbs"], 105.1, "lean_body_weight_lbs"
    )
    assert_weight_equals(
        finalized["minimum_certified_weight_lbs"],
        113.0,
        "minimum_certified_weight_lbs",
    )
    assert finalized["min_weight_class_lbs"] == 113, (
        "the two-stage rounding lands the minimum on 113.0 and selects class 113, "
        f"got {finalized['min_weight_class_lbs']!r}"
    )


def test_the_wrestler_echoes_the_double_rounded_certified_figures(api):
    """The wrestler's own certified figures are recomputed from the validated row.

    Per §3.3 the wrestler's ``alpha_weight_lbs``, ``body_fat_pct``,
    ``minimum_certified_weight_lbs`` and ``min_weight_class_lbs`` are recomputed
    from the newly validated assessment, and ``source_assessment_id`` is repointed
    at it.

    Design: Corner/calculations/minimum_certified_weight_double_rounding_order_precision
    """
    scenario = _open_program(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id, "Casey Lin", grade=9)

    draft = fixtures.create_assessment(
        api,
        wrestler["id"],
        scenario.assessor_id,
        assessed_at="2026-11-01T09:00:00Z",
        measured_weight_lbs=121.0,
        body_fat_pct=13.1,
        urine_specific_gravity=1.019,
    )
    finalized = _finalize(api, draft["id"], scenario.assessor_id)

    stored = fixtures.read_wrestler(api, wrestler["id"])
    assert stored["source_assessment_id"] == finalized["id"], (
        "the wrestler's source_assessment_id is repointed at the validated row, "
        f"got {stored['source_assessment_id']!r}"
    )
    assert_weight_equals(
        stored["minimum_certified_weight_lbs"],
        113.0,
        "wrestler minimum_certified_weight_lbs",
    )
    assert stored["min_weight_class_lbs"] == 113, (
        f"wrestler min_weight_class_lbs: expected 113, "
        f"got {stored['min_weight_class_lbs']!r}"
    )
    assert_weight_equals(stored["alpha_weight_lbs"], 121.0, "wrestler alpha_weight_lbs")
    assert_weight_equals(stored["body_fat_pct"], 13.1, "wrestler body_fat_pct")


# ── Audit scoring and the minimum sample count ───────────────────────

def _three_draft_assessments(api, scenario, wrestler_id):
    """Three draft assessments by the same assessor, stamped the same UTC day."""
    readings = [
        ("2026-11-01T09:00:00Z", 159.6, 14.0),
        ("2026-11-01T09:30:00Z", 158.0, 12.0),
        ("2026-11-01T10:00:00Z", 157.0, 10.0),
    ]
    return [
        fixtures.create_assessment(
            api,
            wrestler_id,
            scenario.assessor_id,
            assessed_at=assessed_at,
            measured_weight_lbs=measured,
            body_fat_pct=body_fat_pct,
        )
        for assessed_at, measured, body_fat_pct in readings
    ]


def test_an_undersized_sample_set_is_never_scored_at_all(api):
    """Two samples are filtered out of scoring instead of being scored on partial data.

    Per §3.9, when ``sample_count`` is strictly less than the season's
    ``audit_min_sample_count`` — three by default — the audit is unscoreable: the
    ``outcome`` becomes ``INCONCLUSIVE`` and ``discrepancy_score`` stays null.  The
    two deviations here are 3.00 and 4.00, both far above the inclusive 2.0 percent
    failure threshold, and neither is ever looked at.  An ``INCONCLUSIVE`` outcome
    triggers no cascade whatsoever, so the assessor keeps their credential.

    Design: Corner/calculations/audit_scoring_input_set_filtered_by_min_sample_count
    """
    scenario = _open_program(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    drafts = _three_draft_assessments(api, scenario, wrestler["id"])

    audit = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_WORST_CASE,
        "2026-11-01",
        assessor_id=scenario.assessor_id,
        samples=factories.audit_samples(
            [(drafts[0]["id"], 17.0), (drafts[1]["id"], 16.0)]
        ),
    )
    assert audit["sample_count"] == 2, (
        f"sample_count is the length of samples, got {audit['sample_count']!r}"
    )

    finalized = validate_success(api.finalize_audit(audit["id"], STATE_OFFICE))
    assert finalized["outcome"] == AUDIT_INCONCLUSIVE, (
        "a sample set below audit_min_sample_count is unscoreable, got "
        f"{finalized['outcome']!r}"
    )
    assert finalized["discrepancy_score"] is None, (
        "discrepancy_score stays null on an unscoreable audit, got "
        f"{finalized['discrepancy_score']!r}"
    )
    assert finalized["voided_assessment_count"] == 0, (
        "no assessment is voided without a FAIL outcome, got "
        f"{finalized['voided_assessment_count']!r}"
    )

    assessor = fixtures.read_assessor(api, scenario.assessor_id)
    assert assessor["status"] == ASSESSOR_CERTIFIED, (
        f"the assessor keeps their credential, got {assessor['status']!r}"
    )
    assert assessor["last_audit_outcome"] == AUDIT_INCONCLUSIVE, (
        "last_audit_outcome reports the verdict of the latest finalized audit, got "
        f"{assessor['last_audit_outcome']!r}"
    )
    assert assessor["voided_assessment_count"] == 0, (
        "no hop of the failure cascade ran, got "
        f"{assessor['voided_assessment_count']!r}"
    )


def test_a_scoreable_sample_set_is_averaged_and_supersedes_the_prior_verdict(api):
    """Three samples are scored, and the latest finalized audit owns the verdict.

    Per §3.9 the ``SAMPLE_MEAN`` variant takes the sum of the per-sample
    deviations divided by ``sample_count``, rounded half up to two decimal places:
    deviations of 0.50, 0.70 and 0.90 sum to 2.10 and average to 0.70, which is
    below the 2.0 percent threshold and therefore ``PASS``.  Per §3.2
    ``last_audit_outcome`` reports the most recently created finalized audit in
    ``created_at`` descending order, so the ``PASS`` supersedes the earlier
    ``INCONCLUSIVE``, and auditing never mutates the sampled assessments.

    Design: Corner/calculations/audit_scoring_input_set_filtered_by_min_sample_count
    """
    scenario = _open_program(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    drafts = _three_draft_assessments(api, scenario, wrestler["id"])

    undersized = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_WORST_CASE,
        "2026-11-01",
        assessor_id=scenario.assessor_id,
        samples=factories.audit_samples(
            [(drafts[0]["id"], 17.0), (drafts[1]["id"], 16.0)]
        ),
    )
    fixtures.finalize_audit(api, undersized["id"])

    scoreable = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_SAMPLE_MEAN,
        "2026-11-01",
        assessor_id=scenario.assessor_id,
        samples=factories.audit_samples(
            [
                (drafts[0]["id"], 14.5),
                (drafts[1]["id"], 12.7),
                (drafts[2]["id"], 10.9),
            ]
        ),
    )
    assert scoreable["sample_count"] == 3, (
        f"sample_count is the length of samples, got {scoreable['sample_count']!r}"
    )

    finalized = validate_success(api.finalize_audit(scoreable["id"], STATE_OFFICE))
    assert finalized["discrepancy_score"] == 0.70, (
        "the mean of 0.50, 0.70 and 0.90 is 0.70 at two decimal places, got "
        f"{finalized['discrepancy_score']!r}"
    )
    assert finalized["outcome"] == AUDIT_PASS, (
        "0.70 is below the 2.0 percent failure threshold, got "
        f"{finalized['outcome']!r}"
    )

    assessor = fixtures.read_assessor(api, scenario.assessor_id)
    assert assessor["status"] == ASSESSOR_CERTIFIED, (
        f"a PASS leaves the credential in force, got {assessor['status']!r}"
    )
    assert assessor["last_audit_outcome"] == AUDIT_PASS, (
        "the latest finalized audit owns last_audit_outcome, got "
        f"{assessor['last_audit_outcome']!r}"
    )

    _rows, meta = validate_paginated(
        api.list_assessments(
            STATE_OFFICE,
            {
                "assessor_id": scenario.assessor_id,
                "status": ASSESSMENT_DRAFT,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 3, (
        "scoring an audit never mutates the sampled assessments, got "
        f"{meta['total_count']!r} still in DRAFT"
    )


# ── The half-open milestone evaluation window ────────────────────────

def _plan_with_two_duals(api):
    """A certified weekly-step plan plus two single-day duals around week 1."""
    scenario = fixtures.certified_wrestler(api)
    early = fixtures.create_event(
        api, scenario.season_id, "Early Dual", "2026-11-04", EVENT_TYPE_DUAL
    )
    late = fixtures.create_event(
        api, scenario.season_id, "Late Dual", "2026-11-12", EVENT_TYPE_DUAL
    )
    early_entry = fixtures.create_entry(
        api, early["id"], scenario.wrestler_id, scenario.team_id, 165,
        season_win_count=1,
    )
    late_entry = fixtures.create_entry(
        api, late["id"], scenario.wrestler_id, scenario.team_id, 165,
        season_win_count=2,
    )
    scenario.update(
        early_event_id=early["id"],
        late_event_id=late["id"],
        early_entry_id=early_entry["id"],
        late_entry_id=late_entry["id"],
    )
    return scenario


def _weigh_in_on(api, event_id, entry_id, clock, recorded_weight_lbs):
    """Move the clock onto the event's weigh-in day and record one reading."""
    fixtures.move_clock(api, clock)
    fixtures.open_weigh_ins(api, event_id)
    return fixtures.record_weigh_in(api, event_id, entry_id, 0, recorded_weight_lbs)


def test_a_weigh_in_one_day_past_the_window_cannot_meet_the_milestone(api):
    """The three-day grace window closes at its upper bound rather than including it.

    Per §3.6 a milestone's evaluation window opens at midnight UTC on its
    ``effective_date`` and closes at midnight UTC three days later, so a reading
    taken at the instant the window opens counts and one taken at the instant it
    closes does not.  Week 0 opens on 2026-11-02, and the 2026-11-04 reading of
    158.0 pounds sits inside ``[2026-11-02, 2026-11-05)`` and is at or under the
    159.6 allowable, so week 0 is met with that number recorded.  Week 1 opens on
    2026-11-09 and closes on 2026-11-12, so the 2026-11-12 reading is not a
    candidate at all: week 1 is missed with no evaluated weight, even though its
    157.0 pounds would have satisfied week 1's 157.2 allowable had the upper bound
    been inclusive.

    Design: Corner/calculations/milestone_evaluation_half_open_grace_window_chronology
    """
    scenario = _plan_with_two_duals(api)

    early = _weigh_in_on(
        api, scenario.early_event_id, scenario.early_entry_id,
        "2026-11-04T08:00:00Z", 158.0,
    )
    late = _weigh_in_on(
        api, scenario.late_event_id, scenario.late_entry_id,
        "2026-11-12T08:00:00Z", 157.0,
    )
    assert early["result"] == WEIGH_IN_PASS, (
        "158.0 is under the class-165 limit outright, got "
        f"{early['result']!r}"
    )
    assert late["result"] == WEIGH_IN_PASS, (
        "157.0 is under the class-165 limit outright, got "
        f"{late['result']!r}"
    )
    assert early["below_minimum"] is False and late["below_minimum"] is False, (
        "147.6 is the certified floor, so neither reading is below it: got "
        f"{early['below_minimum']!r} and {late['below_minimum']!r}"
    )

    fixtures.move_clock(api, "2026-11-13T12:00:00Z")
    fixtures.run_compliance(api, scenario.season_id)

    milestones = _milestones(api, scenario.plan_id)
    week0, week1 = milestones[0], milestones[1]

    assert week0["status"] == MILESTONE_MET, (
        "the 2026-11-04 reading is inside week 0's window, got "
        f"{week0['status']!r}"
    )
    assert_weight_equals(
        week0["evaluated_recorded_weight_lbs"], 158.0, "week 0 evaluated weight"
    )
    assert week1["status"] == MILESTONE_MISSED, (
        "the 2026-11-12 reading is past week 1's window, got "
        f"{week1['status']!r}"
    )
    assert week1["evaluated_recorded_weight_lbs"] is None, (
        "no candidate exists for week 1, so its evaluated weight stays null; the "
        "157.0 reading must not be silently credited to it, got "
        f"{week1['evaluated_recorded_weight_lbs']!r}"
    )
    assert_weight_equals(
        week1["allowable_weight_lbs"], 157.2, "week 1 allowable_weight_lbs"
    )


def test_future_milestones_are_skipped_rather_than_defaulted_to_missed(api):
    """Only milestones already due are judged, and one miss is not yet a breach.

    Per §3.6 the sweep considers only milestones whose ``effective_date`` is on or
    before the current logical clock date; a milestone still in the future is
    skipped and stays scheduled rather than being treated as a failure.  With the
    clock at 2026-11-13 that leaves weeks 2 through 5 — 11-16, 11-23, 11-30 and
    12-07 — untouched, and a single missed milestone is below the breach limit of
    two, so the plan stays certified and no breach flag is raised.

    Design: Corner/calculations/milestone_evaluation_half_open_grace_window_chronology
    """
    scenario = _plan_with_two_duals(api)

    _weigh_in_on(
        api, scenario.early_event_id, scenario.early_entry_id,
        "2026-11-04T08:00:00Z", 158.0,
    )
    _weigh_in_on(
        api, scenario.late_event_id, scenario.late_entry_id,
        "2026-11-12T08:00:00Z", 157.0,
    )

    fixtures.move_clock(api, "2026-11-13T12:00:00Z")
    fixtures.run_compliance(api, scenario.season_id)

    milestones = _milestones(api, scenario.plan_id)
    assert len(milestones) == 6, (
        f"the weekly-step schedule generates six milestones, got {len(milestones)}"
    )
    for milestone in milestones[2:]:
        assert milestone["status"] == MILESTONE_SCHEDULED, (
            f"week {milestone['week_index']} falls on "
            f"{milestone['effective_date']}, after the run date, so it is skipped: "
            f"got {milestone['status']!r}"
        )
        assert milestone["evaluated_recorded_weight_lbs"] is None, (
            f"week {milestone['week_index']} was never judged, got "
            f"{milestone['evaluated_recorded_weight_lbs']!r}"
        )

    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["missed_milestone_count"] == 1, (
        "exactly one milestone was missed, got "
        f"{plan['missed_milestone_count']!r}"
    )
    assert plan["status"] == PLAN_CERTIFIED, (
        "one miss is below the breach limit of two, got "
        f"{plan['status']!r}"
    )
    assert plan["breach_count"] == 0, (
        f"no breach was declared, got {plan['breach_count']!r}"
    )

    team = fixtures.read_team(api, scenario.team_id)
    assert team["open_flag_severity_total"] == 0, (
        "no breach flag was raised, so the ledger stays empty, got "
        f"{team['open_flag_severity_total']!r}"
    )
    assert team["compliance_status"] == TEAM_CLEAR, (
        f"an empty ledger reads CLEAR, got {team['compliance_status']!r}"
    )


# ── The three-key seeding ranking expression ─────────────────────────

def _seeded_qualifier(api):
    """Three certified wrestlers weighed in for one class-150 bracket.

    Creation order is A, B, C; wins are 5, 3, 5 and the day's readings are 150.0,
    149.0 and 149.5, so wins and weight disagree about who should lead.
    """
    scenario = _open_program(api)
    wrestler_a = _certify_at_target_class(
        api, scenario, "Alex Mercer", "2026-11-01T09:00:00Z"
    )
    wrestler_b = _certify_at_target_class(
        api, scenario, "Blake Nolan", "2026-11-01T09:20:00Z"
    )
    wrestler_c = _certify_at_target_class(
        api, scenario, "Cory Diaz", "2026-11-01T09:40:00Z"
    )

    event = fixtures.create_event(
        api, scenario.season_id, "State Qualifier", "2026-12-12", EVENT_TYPE_TOURNAMENT
    )
    entries = {}
    for key, wrestler_id, wins in (
        ("a", wrestler_a, 5),
        ("b", wrestler_b, 3),
        ("c", wrestler_c, 5),
    ):
        entries[key] = fixtures.create_entry(
            api,
            event["id"],
            wrestler_id,
            scenario.team_id,
            CANON_TARGET_CLASS_LBS,
            season_win_count=wins,
        )["id"]

    fixtures.move_clock(api, "2026-12-12T07:00:00Z")
    fixtures.open_weigh_ins(api, event["id"])
    for key, recorded in (("a", 150.0), ("b", 149.0), ("c", 149.5)):
        fixtures.record_weigh_in(api, event["id"], entries[key], 0, recorded)
    fixtures.close_weigh_ins(api, event["id"])

    scenario.update(event_id=event["id"], entries=entries)
    return scenario


def test_wins_outrank_weight_and_weight_breaks_the_tie_between_equals(api):
    """The ranking keys are applied in the declared order, not blended.

    Per §3.8 the entries of a class are ranked by ``season_win_count`` descending,
    then by ``latest_effective_weight_lbs`` ascending with nulls sorting last, then
    by ``created_at`` ascending, and the row identifier is never consulted.  C ties
    A on five wins and takes seed 1 on the lighter 149.5 pound reading; B, created
    second and lightest of the three at 149.0, is nevertheless seeded last because
    its three wins lose on the first key.  Creation order A, B, C therefore yields
    seeds C, A, B.

    Design: Corner/calculations/seed_assignment_ranking_expression_and_tiebreak_order
    """
    scenario = _seeded_qualifier(api)
    fixtures.seed_event(api, scenario.event_id)

    seeds = {
        key: fixtures.read_entry(api, entry_id)["seed_number"]
        for key, entry_id in scenario.entries.items()
    }
    assert seeds["c"] == 1, (
        "C ties A on wins and wins the weight tiebreak at 149.5 against 150.0, got "
        f"{seeds['c']!r}"
    )
    assert seeds["a"] == 2, (
        f"A follows C on the same five wins, got {seeds['a']!r}"
    )
    assert seeds["b"] == 3, (
        "B's three wins put it last despite the lightest reading of 149.0, which is "
        f"what proves wins are applied before weight: got {seeds['b']!r}"
    )


def test_seeding_locks_the_bracket_and_conserves_the_integrity_sum(api):
    """One occupied class of three yields a contiguous run and the conserved sum.

    Per §3.8 every admitted entry moves to ``SEEDED`` with a seed number counting
    from 1 within its class, the initial run sets ``bracket_locked`` true and
    ``reseed_required`` false, and both counters are refreshed.  A single occupied
    class holding three entries contributes three times four over two, which is 6.

    Design: Corner/calculations/seed_assignment_ranking_expression_and_tiebreak_order
    """
    scenario = _seeded_qualifier(api)
    event = fixtures.seed_event(api, scenario.event_id)

    assert event["status"] == EVENT_SEEDED, (
        f"the event lands in SEEDED, got {event['status']!r}"
    )
    assert event["seeded_entry_count"] == 3, (
        f"all three weighed-in entries are admitted, got "
        f"{event['seeded_entry_count']!r}"
    )
    expected_sum = expected_seed_integrity_sum([3])
    assert event["seed_integrity_sum"] == expected_sum == 6, (
        "the conserved sum over one class of three is 6, got "
        f"{event['seed_integrity_sum']!r}"
    )
    assert event["bracket_locked"] is True, (
        f"the initial run locks the bracket, got {event['bracket_locked']!r}"
    )
    assert event["reseed_required"] is False, (
        f"a freshly seeded bracket needs no reseed, got {event['reseed_required']!r}"
    )

    for key, entry_id in scenario.entries.items():
        entry = fixtures.read_entry(api, entry_id)
        assert entry["status"] == ENTRY_SEEDED, (
            f"entry {key} is admitted and seeded, got {entry['status']!r}"
        )


# ── The severity ledger and its posture bands ────────────────────────

# Five hydration failures on one wrestler, spread across two calendar days so
# that no assessor exceeds the daily capacity of three.  Each row is
# (clock, assessed_at, measured weight, specific gravity).
_HYDRATION_FAILURES = [
    ("2026-11-01T12:00:00Z", "2026-11-01T09:00:00Z", 159.6, 1.031),
    ("2026-11-01T12:00:00Z", "2026-11-01T09:30:00Z", 159.4, 1.032),
    ("2026-11-01T12:00:00Z", "2026-11-01T10:00:00Z", 159.2, 1.033),
    ("2026-11-02T12:00:00Z", "2026-11-02T09:00:00Z", 159.0, 1.034),
    ("2026-11-02T12:00:00Z", "2026-11-02T09:30:00Z", 158.8, 1.035),
]


def _fail_hydration(api, scenario, wrestler_id, reading):
    """Finalize one over-hydrated reading, taking the hydration-failure arm."""
    clock, assessed_at, measured_weight_lbs, usg = reading
    fixtures.move_clock(api, clock)
    draft = fixtures.create_assessment(
        api,
        wrestler_id,
        scenario.assessor_id,
        assessed_at=assessed_at,
        measured_weight_lbs=measured_weight_lbs,
        body_fat_pct=14.0,
        urine_specific_gravity=usg,
    )
    finalized = _finalize(api, draft["id"], scenario.assessor_id)
    assert finalized["status"] == ASSESSMENT_HYDRATION_FAILED, (
        f"a specific gravity of {usg} is above the 1.025 ceiling, got "
        f"{finalized['status']!r}"
    )
    return finalized


def test_the_severity_band_flips_only_when_the_aggregate_reaches_five(api):
    """Four harmless flags read WATCH and the fifth alone tips PROBATION.

    Per §2.9 the ledger is the sum of ``severity`` over the team's open flags, and
    the posture derived from it is CLEAR at exactly 0, WATCH from 1 through 4
    inclusive, and PROBATION at 5 or more.  A hydration failure contributes 1 and
    only 1, so four of them sit at the very top of the WATCH band and the fifth
    crosses the inclusive PROBATION lower bound.  No single flag is decisive; only
    the aggregate is.

    Design: Corner/calculations/team_posture_aggregate_watch_to_probation_boundary
    """
    scenario = _open_program(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id, "Alex Mercer")

    for reading in _HYDRATION_FAILURES[:4]:
        _fail_hydration(api, scenario, wrestler["id"], reading)

    at_four = fixtures.read_team(api, scenario.team_id)
    assert at_four["open_flag_severity_total"] == 4, (
        "four severity-1 flags total 4, got "
        f"{at_four['open_flag_severity_total']!r}"
    )
    assert at_four["compliance_status"] == TEAM_WATCH, (
        "4 is the inclusive top of the WATCH band, got "
        f"{at_four['compliance_status']!r}"
    )
    assert_severity_ledger(at_four, 4, "team at four open flags")

    _fail_hydration(api, scenario, wrestler["id"], _HYDRATION_FAILURES[4])

    at_five = fixtures.read_team(api, scenario.team_id)
    assert at_five["open_flag_severity_total"] == 5, (
        "the fifth flag brings the total to 5, got "
        f"{at_five['open_flag_severity_total']!r}"
    )
    assert at_five["compliance_status"] == TEAM_PROBATION, (
        "5 is the inclusive PROBATION lower bound, got "
        f"{at_five['compliance_status']!r}"
    )
    assert_severity_ledger(at_five, 5, "team at five open flags")

    rows, meta = validate_paginated(
        api.list_health_flags(
            STATE_OFFICE,
            {"wrestler_id": wrestler["id"], "status": FLAG_OPEN, "limit": 100},
        )
    )
    assert meta["total_count"] == 5, (
        "each failed finalize raised exactly one flag, got "
        f"{meta['total_count']!r}"
    )
    for flag in rows:
        assert flag["source"] == FLAG_HYDRATION_FAIL, (
            f"the raising cascade names its source, got {flag['source']!r}"
        )
        assert_flag_severity_matches_source(flag)


def test_the_failed_hydration_arm_smuggles_in_no_certified_figure(api):
    """A team on probation is reached without ever certifying the wrestler.

    Per §3.3 the hydration-failure arm leaves ``lean_body_weight_lbs``,
    ``minimum_certified_weight_lbs``, ``min_weight_class_lbs`` and
    ``alpha_weight_lbs`` all null and does not repoint ``source_assessment_id``, and
    per §3.1 the certification dimension is left exactly where it was — which for a
    wrestler with no validated assessment is ``UNCERTIFIED``.  The season's
    ``certified_wrestler_count`` counts only wrestlers currently reading
    ``CERTIFIED``, so it stays at 0 throughout.

    Design: Corner/calculations/team_posture_aggregate_watch_to_probation_boundary
    """
    scenario = _open_program(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id, "Alex Mercer")

    for reading in _HYDRATION_FAILURES:
        finalized = _fail_hydration(api, scenario, wrestler["id"], reading)
        assert finalized["hydration_passed"] is False, (
            f"the reading is over-hydrated, got {finalized['hydration_passed']!r}"
        )
        for field in (
            "lean_body_weight_lbs",
            "minimum_certified_weight_lbs",
            "min_weight_class_lbs",
            "alpha_weight_lbs",
        ):
            assert finalized[field] is None, (
                f"no certified figure is produced on this arm, but {field} came "
                f"back {finalized[field]!r}"
            )

    stored = fixtures.read_wrestler(api, wrestler["id"])
    assert stored["certification_status"] == WRESTLER_UNCERTIFIED, (
        "the certification dimension is left untouched, got "
        f"{stored['certification_status']!r}"
    )
    assert stored["eligibility_status"] == ELIGIBILITY_INELIGIBLE, (
        "no eligibility change is smuggled in, got "
        f"{stored['eligibility_status']!r}"
    )
    assert stored["source_assessment_id"] is None, (
        "source_assessment_id is not repointed by a failed reading, got "
        f"{stored['source_assessment_id']!r}"
    )
    for field in (
        "minimum_certified_weight_lbs",
        "min_weight_class_lbs",
        "alpha_weight_lbs",
        "lowest_eligible_class_lbs",
    ):
        assert stored[field] is None, (
            f"the wrestler carries no certified figure, but {field} came back "
            f"{stored[field]!r}"
        )
    assert stored["open_health_flag_count"] == 5, (
        "all five flags are still open on the wrestler, got "
        f"{stored['open_health_flag_count']!r}"
    )

    season = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 0, (
        "nobody was ever certified, got "
        f"{season['certified_wrestler_count']!r}"
    )


# ── The hard-floor clamp on the lowest eligible class ────────────────

def _plan_with_two_allowance_dates(api):
    """A certified plan to class 150 under two growth allowances and two events."""
    scenario = fixtures.certified_wrestler(api)
    fixtures.publish_growth_allowance(
        api, scenario.season_id, "2026-12-01", 1.0, "December growth allowance"
    )
    fixtures.publish_growth_allowance(
        api, scenario.season_id, "2026-12-12", 3.0, "Late-season growth allowance"
    )
    eve = fixtures.create_event(
        api, scenario.season_id, "Eve Dual", "2026-12-11", EVENT_TYPE_DUAL
    )
    day = fixtures.create_event(
        api,
        scenario.season_id,
        "Allowance Day Open",
        "2026-12-12",
        EVENT_TYPE_TOURNAMENT,
    )
    scenario.update(eve_event_id=eve["id"], day_event_id=day["id"])
    return scenario


def test_a_growth_allowance_counts_from_its_own_effective_date_onward(api):
    """The allowance total is inclusive of its effective date and the schedule holds.

    Per §3.7 step one sums ``allowance_lbs`` over every growth allowance whose
    ``effective_date`` is on or before the ``as_of_date``, the lower bound being
    inclusive: as of 2026-12-11 only the December 1 pound counts, and as of
    2026-12-12 the second allowance joins it on its own first day for a total of
    4.0.  Step two keeps the last milestone's value when the ``as_of_date`` runs
    past the end of the schedule, so both dates read 147.9 from the 2026-12-07
    milestone rather than falling back to week 0's 159.6.

    Design: Corner/calculations/lowest_eligible_class_hard_floor_clamp_survives_growth_allowance
    """
    scenario = _plan_with_two_allowance_dates(api)

    eve = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, scenario.eve_event_id, CANON_TARGET_CLASS_LBS
    )
    day = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, scenario.day_event_id, CANON_TARGET_CLASS_LBS
    )

    assert eve["as_of_date"] == "2026-12-11", (
        f"the check copies the event's date, got {eve['as_of_date']!r}"
    )
    assert day["as_of_date"] == "2026-12-12", (
        f"the check copies the event's date, got {day['as_of_date']!r}"
    )
    assert_weight_equals(eve["growth_allowance_lbs"], 1.0, "12-11 growth_allowance_lbs")
    assert_weight_equals(day["growth_allowance_lbs"], 4.0, "12-12 growth_allowance_lbs")
    assert_weight_equals(
        eve["schedule_allowable_weight_lbs"], 147.9, "12-11 schedule value"
    )
    assert_weight_equals(
        day["schedule_allowable_weight_lbs"], 147.9, "12-12 schedule value"
    )


def test_the_allowance_relaxes_the_search_but_never_lowers_the_hard_floor(api):
    """The propagation stops at the class fixed at validation time.

    Per §3.7 step four the candidate class is the smallest whose limit plus the
    growth allowance reaches the floor — on 2026-12-12 that is class 144, because
    144 plus 4.0 is 148.0 and the floor is 147.9 — but the reported class is the
    larger of that candidate and the hard-floor class, which was computed from the
    *unadjusted* minimum and is 150.  So both dates answer 150, the requested class
    144 is refused, and the allowance is never folded back into the wrestler's own
    certified figures.

    Design: Corner/calculations/lowest_eligible_class_hard_floor_clamp_survives_growth_allowance
    """
    scenario = _plan_with_two_allowance_dates(api)

    eve = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, scenario.eve_event_id, CANON_TARGET_CLASS_LBS
    )
    day = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, scenario.day_event_id, CANON_TARGET_CLASS_LBS
    )
    clamped = expected_lowest_eligible_class(
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS, 147.9, 4.0, CANON_MIN_WEIGHT_CLASS_LBS
    )
    assert eve["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS, (
        "one pound of allowance changes nothing on 12-11, got "
        f"{eve['lowest_eligible_class_lbs']!r}"
    )
    assert day["lowest_eligible_class_lbs"] == clamped == CANON_MIN_WEIGHT_CLASS_LBS, (
        "four pounds of allowance drags the candidate to 144 but the clamp holds "
        f"the answer at 150, got {day['lowest_eligible_class_lbs']!r}"
    )
    assert eve["outcome"] == OUTCOME_CLEARED, (
        f"class 150 is at the floor, got {eve['outcome']!r}"
    )
    assert day["outcome"] == OUTCOME_CLEARED, (
        f"class 150 is at the floor, got {day['outcome']!r}"
    )
    assert eve["blocking_error_id"] is None and day["blocking_error_id"] is None, (
        "a cleared outcome names no error, got "
        f"{eve['blocking_error_id']!r} and {day['blocking_error_id']!r}"
    )

    low = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, scenario.day_event_id, 144
    )
    assert low["outcome"] == OUTCOME_BLOCKED_CLASS_BELOW_MINIMUM, (
        "the requested class is below the clamped floor, got "
        f"{low['outcome']!r}"
    )
    assert low["blocking_error_id"] == ERR_CLASS_BELOW_CERTIFIED_MINIMUM, (
        "the check reports the error a real entry would return, got "
        f"{low['blocking_error_id']!r}"
    )

    stored = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert stored["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS, (
        "the hard floor is untouched by any check, got "
        f"{stored['min_weight_class_lbs']!r}"
    )
    assert_weight_equals(
        stored["minimum_certified_weight_lbs"],
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        "wrestler minimum_certified_weight_lbs",
    )
    assert stored["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS, (
        "running a check refreshes the wrestler's own floor to 150, never to 144, "
        f"got {stored['lowest_eligible_class_lbs']!r}"
    )


# ── The capped consecutive-day weigh-in allowance ────────────────────

_EVENT_PER_DAY_ALLOWANCE_LBS = 1.5

# One reading per weigh-in day of a three-day tournament, each as
# (day_index, clock, recorded weight, allowance, effective limit, result).
_THREE_DAY_READINGS = [
    (0, "2026-12-12T07:00:00Z", 151.0, 1.0, 151.0, WEIGH_IN_PASS_WITH_ALLOWANCE),
    (1, "2026-12-13T07:00:00Z", 152.5, 2.5, 152.5, WEIGH_IN_PASS_WITH_ALLOWANCE),
    (2, "2026-12-14T07:00:00Z", 153.1, 3.0, 153.0, WEIGH_IN_FAIL),
]


def _three_day_tournament(api):
    """A certified wrestler entered in a three-day event under a 1.0 lb allowance."""
    scenario = fixtures.certified_wrestler(api)
    fixtures.publish_growth_allowance(
        api, scenario.season_id, "2026-12-01", 1.0, "December growth allowance"
    )
    event = fixtures.create_event(
        api,
        scenario.season_id,
        "Three Day Classic",
        "2026-12-12",
        EVENT_TYPE_TOURNAMENT,
        competition_days=3,
        weigh_in_days=3,
        consecutive_day_allowance_lbs=_EVENT_PER_DAY_ALLOWANCE_LBS,
    )
    entry = fixtures.create_entry(
        api,
        event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=2,
    )
    fixtures.move_clock(api, "2026-12-12T07:00:00Z")
    fixtures.open_weigh_ins(api, event["id"])
    scenario.update(event_id=event["id"], entry_id=entry["id"])
    return scenario


def test_the_season_ceiling_clips_the_third_days_allowance(api):
    """The per-day component is capped before it joins the growth component.

    Per §3.8 the consecutive-day component is the ``day_index`` times the event's
    ``consecutive_day_allowance_lbs``, rounded to one decimal place and then capped
    at the season's ``max_consecutive_day_allowance_lbs``, and the stored
    ``allowance_lbs`` is that capped figure plus the growth-allowance component.  At
    1.5 pounds per day against a 2.0 pound ceiling: day 0 earns nothing and totals
    1.0, day 1 earns 1.5 and totals 2.5, and day 2's raw 3.0 is clipped to 2.0 so
    the total is 3.0 and the limit 153.0 — not the 154.0 an uncapped reading would
    have produced.  That single clipped pound is what turns 153.1 into a failure.

    Design: Corner/calculations/weigh_in_allowance_consecutive_day_season_cap
    """
    scenario = _three_day_tournament(api)

    for day_index, clock, recorded, allowance, limit, result in _THREE_DAY_READINGS:
        fixtures.move_clock(api, clock)
        weigh_in = fixtures.record_weigh_in(
            api, scenario.event_id, scenario.entry_id, day_index, recorded
        )

        expected_day_component = expected_consecutive_day_allowance(
            day_index,
            _EVENT_PER_DAY_ALLOWANCE_LBS,
            DEFAULT_MAX_CONSECUTIVE_DAY_ALLOWANCE_LBS,
        )
        assert_weight_equals(
            weigh_in["allowance_lbs"],
            round(1.0 + expected_day_component, 1),
            f"day {day_index} allowance_lbs",
        )
        assert_weight_equals(
            weigh_in["allowance_lbs"], allowance, f"day {day_index} allowance_lbs"
        )
        assert_weight_equals(
            weigh_in["effective_limit_lbs"], limit, f"day {day_index} effective limit"
        )
        assert weigh_in["result"] == expected_weigh_in_result(
            recorded, CANON_TARGET_CLASS_LBS, limit
        ) == result, (
            f"day {day_index}: {recorded} against class {CANON_TARGET_CLASS_LBS} and "
            f"limit {limit} is {result}, got {weigh_in['result']!r}"
        )


def test_a_failed_third_day_leaves_the_second_days_weight_standing(api):
    """A failure records itself without disturbing the entry's effective weight.

    Per §3.8 a passing weigh-in sets ``latest_effective_weight_lbs`` to the passing
    reading with the greatest ``day_index``, while a failing one never overwrites it
    and does not move the entry, which stays where it was until weigh-ins close.  So
    after the day-2 failure the entry still reads the day-1 value of 152.5 and is
    still weighed in.  Every reading is above the 147.6 certified minimum, so
    ``below_minimum`` is false throughout, no deficit flag is raised, and the team's
    ledger stays empty (§2.9).

    Design: Corner/calculations/weigh_in_allowance_consecutive_day_season_cap
    """
    scenario = _three_day_tournament(api)

    for day_index, clock, recorded, _allowance, _limit, _result in _THREE_DAY_READINGS:
        fixtures.move_clock(api, clock)
        weigh_in = fixtures.record_weigh_in(
            api, scenario.event_id, scenario.entry_id, day_index, recorded
        )
        assert weigh_in["below_minimum"] is False, (
            f"day {day_index}: {recorded} is above the 147.6 certified minimum, got "
            f"{weigh_in['below_minimum']!r}"
        )

    entry = fixtures.read_entry(api, scenario.entry_id)
    assert_weight_equals(
        entry["latest_effective_weight_lbs"], 152.5, "latest_effective_weight_lbs"
    )
    assert entry["status"] == ENTRY_WEIGHED_IN, (
        "the failed reading does not move the entry, got "
        f"{entry['status']!r}"
    )

    _rows, meta = validate_paginated(
        api.list_health_flags(
            STATE_OFFICE, {"wrestler_id": scenario.wrestler_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        "no reading fell below the certified minimum, so no flag was raised, got "
        f"{meta['total_count']!r}"
    )
    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 0)
