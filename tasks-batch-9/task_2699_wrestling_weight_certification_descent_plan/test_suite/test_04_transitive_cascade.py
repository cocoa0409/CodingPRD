"""
Multi-hop cascade chains that rewrite rows the caller never named.

The requirements describe two long chains that each begin with a single
state-office request and then walk, hop by hop, into entities the request body
never mentions.  §3.9 specifies the deepest of them: a failed sampled program
audit that suspends the assessor, voids their in-window work, suspends every
wrestler whose source assessment was voided, cancels the certified wrestler's
descent plan and finally scratches that wrestler's tournament entry.  §3.6
specifies the other: a season compliance sweep that judges due milestones,
breaches a plan at the breach limit, raises the plan-breach health flag, pushes
the owning team's severity ledger over the probation threshold and demotes the
team's eligible wrestlers to restricted.

§2.10 pins the discipline both chains obey: every hop is applied within the same
request, immediately and completely, before the response is emitted, and a
partially applied cascade is never a valid outcome.  Cascade-created rows are
invisible to the triggering caller, so the generated milestones are read back
through the plan's milestone listing and the raised flags through the filtered
health-flag listing, exactly as §2.10 requires.

Every precondition below is built through declared endpoints, because the
service starts each test with an empty database and the logical clock at its
start instant.
"""

from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_all_null,
    assert_audit_score_equals,
    assert_flag_severity_matches_source,
    assert_row_count,
    assert_severity_ledger,
)
from test_helpers.constants import (
    ASSESSMENT_VOIDED,
    ASSESSOR_SUSPENDED,
    AUDIT_FAIL,
    AUDIT_FINALIZED,
    AUDIT_TYPE_ASSESSOR_SAMPLE,
    AUDIT_WORST_CASE_SCORE,
    CANCEL_REASON_WRESTLER_SUSPENDED,
    CANON_USG_FAIL,
    DEFAULT_PLAN_BREACH_LIMIT,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_RESTRICTED,
    ENTRY_SCRATCHED,
    EVENT_SCHEDULED,
    FLAG_OPEN,
    FLAG_PLAN_BREACH,
    FLAG_SEVERITY,
    HOLD_SOURCE_ASSESSMENT_VOIDED,
    MILESTONE_MISSED,
    MILESTONE_SCHEDULED,
    PLAN_BREACHED,
    PLAN_CANCELLED,
    SCORING_WORST_CASE,
    SEX_MALE,
    TEAM_PROBATION,
    TEAM_WATCH,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEEKLY_STEP_MILESTONE_DATES,
    WRESTLER_CERTIFIED,
    WRESTLER_SUSPENDED,
    VOID_REASON_AUDIT_FAIL_PREFIX,
)
from test_helpers.test_users import STATE_OFFICE

# The five certified figures §3.9 hop three sets to null on every wrestler whose
# source assessment the audit failure voided.
_CERTIFIED_FIGURES = (
    "alpha_weight_lbs",
    "body_fat_pct",
    "minimum_certified_weight_lbs",
    "min_weight_class_lbs",
    "lowest_eligible_class_lbs",
)

# The audit's sample window opens on the day all three assessments were taken.
_SAMPLE_WINDOW_START = "2026-11-01"

# The three sampled assessments, as (wrestler name, grade, assessed-at instant,
# measured weight, recorded body fat, hydration reading, remeasured body fat).
# The deviations the auditor's remeasurements imply are 1.20, 2.40 and 0.60,
# which §3.9 scores at 2.40 under WORST_CASE and therefore fails against the
# shipped 2.0 percent threshold.  All three share one UTC calendar day, which is
# exactly the assessor's daily capacity of three.
_SAMPLED_ASSESSMENTS = (
    ("Alex Mercer", 11, "2026-11-01T09:00:00Z", 159.6, 14.0, 1.020, 15.2),
    ("Blake Ito", 12, "2026-11-01T10:00:00Z", 172.0, 16.0, 1.018, 18.4),
    ("Casey Lund", 10, "2026-11-01T11:00:00Z", 200.0, 20.0, 1.015, 20.6),
)

# The event the certified wrestler is entered into, and the class §3.7's
# four-step floor derivation admits on its date: the governing plan's week-one
# milestone allows 157.2 pounds as of 2026-11-10, so the smallest admissible
# class is 165.
_EVENT_NAME = "Northgate Invitational"
_EVENT_DATE = "2026-11-10"
_ENTRY_CLASS_LBS = 165
_ENTRY_SEASON_WINS = 4

# The instant the compliance sweep is taken at: three of the six generated
# milestones have come due on 2026-11-20 and three have not.
_SWEEP_INSTANT = "2026-11-20T00:00:00Z"
_SWEEP_DATE = "2026-11-20"


# ── Scenario builders ────────────────────────────────────────────────

def _audit_cascade_world(api: ApiClient) -> fixtures.Scenario:
    """The world a failed sampled audit cascades through.

    One open season, one team, one assessor trained to the certification
    threshold, and three rostered wrestlers each carrying one validated
    assessment taken by that assessor on 2026-11-01.  Only the first wrestler is
    driven all the way to certified through a certified descent plan and entered
    in a scheduled competition; the other two stay provisional with no plan, so
    the width of §3.9's third hop differs per wrestler.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    scenario.update(assessor=assessor, assessor_id=assessor["id"])

    keys = ("wrestler_a", "wrestler_b", "wrestler_c")
    assessment_keys = ("assess_a", "assess_b", "assess_c")
    samples = []
    for key, assessment_key, spec in zip(keys, assessment_keys, _SAMPLED_ASSESSMENTS):
        full_name, grade, assessed_at, weight, body_fat, usg, remeasured = spec
        wrestler = fixtures.create_wrestler(
            api, scenario.team_id, full_name, SEX_MALE, grade
        )
        assessment = fixtures.create_validated_assessment(
            api,
            wrestler["id"],
            assessor["id"],
            assessed_at=assessed_at,
            measured_weight_lbs=weight,
            body_fat_pct=body_fat,
            urine_specific_gravity=usg,
        )
        scenario[key] = wrestler["id"]
        scenario[assessment_key] = assessment["id"]
        samples.append((assessment["id"], remeasured))

    # Only the first wrestler gets the certified plan, so only that wrestler is
    # inside the season's certified-wrestler counter.
    plan = fixtures.create_certified_plan(
        api, scenario.wrestler_a, scenario.team_id, scenario.assess_a
    )
    event = fixtures.create_event(
        api,
        scenario.season_id,
        _EVENT_NAME,
        _EVENT_DATE,
        competition_days=1,
        weigh_in_days=1,
    )
    entry = fixtures.create_entry(
        api,
        event["id"],
        scenario.wrestler_a,
        scenario.team_id,
        _ENTRY_CLASS_LBS,
        season_win_count=_ENTRY_SEASON_WINS,
    )
    audit = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_WORST_CASE,
        _SAMPLE_WINDOW_START,
        assessor_id=assessor["id"],
        samples=factories.audit_samples(samples),
    )
    scenario.update(
        plan=plan,
        plan_id=plan["id"],
        event=event,
        event_id=event["id"],
        entry=entry,
        entry_id=entry["id"],
        audit=audit,
        audit_id=audit["id"],
    )
    return scenario


def _finalize_failing_audit(api: ApiClient, scenario: fixtures.Scenario) -> Dict[str, Any]:
    """Trigger the cascade with the single declared finalize request."""
    return validate_success(api.finalize_audit(scenario.audit_id, STATE_OFFICE))


def _breach_cascade_world(api: ApiClient) -> fixtures.Scenario:
    """The world a season compliance sweep cascades through.

    One wrestler certified and eligible on a certified compounding plan that
    started 2026-11-02, with no weigh-in ever recorded, and two further
    assessments finalized on the hydration-failure arm so that §3.3 has already
    raised two open hydration flags worth one severity point each.  The team's
    ledger therefore stands at 2 and its posture at WATCH before the sweep, which
    is what lets the breach flag's three points land exactly on the probation
    threshold of 5.
    """
    scenario = fixtures.certified_wrestler(api)
    for assessed_at, weight in (
        ("2026-11-03T09:00:00Z", 158.0),
        ("2026-11-04T09:00:00Z", 157.0),
    ):
        draft = fixtures.create_assessment(
            api,
            scenario.wrestler_id,
            scenario.assessor_id,
            assessed_at=assessed_at,
            measured_weight_lbs=weight,
            urine_specific_gravity=CANON_USG_FAIL,
        )
        fixtures.finalize_assessment(api, draft["id"], scenario.assessor_id)
    scenario.team_before = fixtures.read_team(api, scenario.team_id)
    return scenario


def _run_sweep(api: ApiClient, scenario: fixtures.Scenario) -> Dict[str, Any]:
    """Move the clock past three milestone dates and take the sweep."""
    fixtures.move_clock(api, _SWEEP_INSTANT)
    return validate_success(api.run_compliance(scenario.season_id, STATE_OFFICE))


def _due_week_indices() -> list:
    """The week indices whose effective date has come due by the sweep date."""
    return [
        index
        for index, effective_date in enumerate(WEEKLY_STEP_MILESTONE_DATES)
        if effective_date <= _SWEEP_DATE
    ]


# ── The five-hop assessor-suspension cascade (§3.9) ──────────────────

def test_audit_failure_scores_worst_case_and_suspends_the_assessor(api: ApiClient) -> None:
    """A failing worst-case audit finalizes, scores and takes hop one.

    §3.9 scores each sample as the absolute difference between the auditor's
    remeasurement and the body fat recorded on the assessment, rounded half up to
    two decimal places, and WORST_CASE takes the single largest of them: the
    deviations 1.20, 2.40 and 0.60 score 2.40, which is at or above the shipped
    2.0 percent threshold and therefore FAIL.  Hop one then moves the assessor
    from certified to suspended, stamps the suspension reason with the audit's id
    and records the verdict on the assessor's dossier, whose voided count picks up
    one increment per row hop two voids.

    Design: Difficulty/transitive_cascade/audit_fail_five_hop_suspension_cascade
    """
    scenario = _audit_cascade_world(api)

    audit = _finalize_failing_audit(api, scenario)

    assert audit["status"] == AUDIT_FINALIZED
    assert audit["sample_count"] == 3
    assert_audit_score_equals(
        audit["discrepancy_score"], AUDIT_WORST_CASE_SCORE, "discrepancy_score"
    )
    assert audit["outcome"] == AUDIT_FAIL
    assert audit["voided_assessment_count"] == 3

    assessor = fixtures.read_assessor(api, scenario.assessor_id)
    assert assessor["status"] == ASSESSOR_SUSPENDED
    assert assessor["suspension_reason"] == (
        VOID_REASON_AUDIT_FAIL_PREFIX + scenario.audit_id
    )
    assert assessor["last_audit_outcome"] == AUDIT_FAIL
    assert assessor["voided_assessment_count"] == 3


def test_audit_failure_voids_every_in_window_validated_assessment(api: ApiClient) -> None:
    """Hop two voids all three of the suspended assessor's validated readings.

    §3.9 hop two moves every assessment of that assessor whose status is
    VALIDATED and whose assessed-at date is on or after the audit's sample window
    start to VOIDED, stamping each void reason as ``AUDIT_FAIL:`` followed by the
    audit's id.  All three assessments were taken on the window's opening day, so
    the whole set is voided regardless of which wrestler each belongs to.

    Design: Difficulty/transitive_cascade/audit_fail_five_hop_suspension_cascade
    """
    scenario = _audit_cascade_world(api)

    _finalize_failing_audit(api, scenario)

    expected_reason = VOID_REASON_AUDIT_FAIL_PREFIX + scenario.audit_id
    for key in ("assess_a", "assess_b", "assess_c"):
        assessment = fixtures.read_assessment(api, scenario[key])
        assert assessment["status"] == ASSESSMENT_VOIDED, (
            f"{key}: expected the audit failure to void this assessment"
        )
        assert assessment["void_reason"] == expected_reason, (
            f"{key}: expected void_reason {expected_reason!r}, "
            f"got {assessment['void_reason']!r}"
        )

    # §3.3 exposes the voided set through the filtered assessment listing.
    rows = assert_row_count(
        api.list_assessments(
            STATE_OFFICE,
            {"assessor_id": scenario.assessor_id, "status": ASSESSMENT_VOIDED},
        ),
        3,
        "voided assessments of the suspended assessor",
    )
    assert {row["id"] for row in rows} == {
        scenario.assess_a,
        scenario.assess_b,
        scenario.assess_c,
    }


def test_audit_failure_suspends_the_certified_wrestler_and_clears_its_figures(
    api: ApiClient,
) -> None:
    """Hop three's wide arm strips the certified wrestler back to suspended.

    §3.9 hop three touches every wrestler whose source assessment was just
    voided: the certification dimension moves to SUSPENDED, the source pointer is
    cleared, all five certified figures are set to null, the hold reason records
    ``SOURCE_ASSESSMENT_VOIDED`` and the eligibility dimension drops to
    INELIGIBLE.  A wrestler arriving from CERTIFIED also takes the season's
    certified-wrestler counter down by one, which §3.9 states is never done for a
    wrestler arriving from PROVISIONAL.

    Design: Difficulty/transitive_cascade/audit_fail_five_hop_suspension_cascade
    """
    scenario = _audit_cascade_world(api)

    _finalize_failing_audit(api, scenario)

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_a)
    assert wrestler["certification_status"] == WRESTLER_SUSPENDED
    assert wrestler["certification_hold_reason"] == HOLD_SOURCE_ASSESSMENT_VOIDED
    assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert wrestler["source_assessment_id"] is None
    assert_all_null(wrestler, _CERTIFIED_FIGURES, "the suspended wrestler")

    season = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 0, (
        "the counter is decremented once, for the certified wrestler only"
    )


@pytest.mark.parametrize("wrestler_key", ["wrestler_b", "wrestler_c"])
def test_audit_failure_suspends_the_provisional_wrestlers_too(
    api: ApiClient, wrestler_key: str
) -> None:
    """Hop three's narrow arm reaches the provisional wrestlers as well.

    §3.9 makes the width of hop three depend on the certification state each
    affected wrestler was in, but not the hop itself: a wrestler arriving from
    PROVISIONAL is still moved to SUSPENDED with the source pointer cleared, all
    five certified figures nulled, the hold reason recorded and the eligibility
    dimension dropped to INELIGIBLE.  Only the counter decrement and the plan and
    entry hops are reserved for the formerly certified wrestler.

    Design: Difficulty/transitive_cascade/audit_fail_five_hop_suspension_cascade
    """
    scenario = _audit_cascade_world(api)

    _finalize_failing_audit(api, scenario)

    wrestler = fixtures.read_wrestler(api, scenario[wrestler_key])
    assert wrestler["certification_status"] == WRESTLER_SUSPENDED
    assert wrestler["certification_hold_reason"] == HOLD_SOURCE_ASSESSMENT_VOIDED
    assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert wrestler["source_assessment_id"] is None
    assert_all_null(wrestler, _CERTIFIED_FIGURES, f"the suspended {wrestler_key}")


def test_audit_failure_cancels_the_plan_and_scratches_the_entry(api: ApiClient) -> None:
    """Hops four and five reach the descent plan and then the entry.

    §3.9 hop four cancels the now-suspended wrestler's certified descent plan
    with a cancel reason of ``WRESTLER_SUSPENDED``, and hop five, because that
    plan was cancelled, moves every tournament entry of that wrestler sitting in
    ENTERED, WEIGHED_IN or SEEDED on an event that is still scheduled, open,
    closed or seeded to SCRATCHED.  §2.10 requires both hops inside the same
    finalizing request, and nothing in the chain touches the event's own status.

    Design: Difficulty/transitive_cascade/audit_fail_five_hop_suspension_cascade
    """
    scenario = _audit_cascade_world(api)

    _finalize_failing_audit(api, scenario)

    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["status"] == PLAN_CANCELLED
    assert plan["cancel_reason"] == CANCEL_REASON_WRESTLER_SUSPENDED

    entry = fixtures.read_entry(api, scenario.entry_id)
    assert entry["status"] == ENTRY_SCRATCHED

    event = fixtures.read_event(api, scenario.event_id)
    assert event["status"] == EVENT_SCHEDULED


# ── The compliance-sweep breach-to-probation cascade (§3.6) ───────────

def test_compliance_run_misses_every_due_milestone_and_leaves_the_rest_scheduled(
    api: ApiClient,
) -> None:
    """Hop one judges only the milestones whose effective date has come due.

    §3.6 considers a plan's milestones in week-index ascending order and only
    those still SCHEDULED whose effective date is on or before the current logical
    clock date; a milestone still in the future is skipped and stays SCHEDULED.
    With no weigh-in ever recorded there is no candidate inside any milestone's
    three-day window, so every due milestone becomes MISSED with its evaluated
    weight left null.  The two hydration flags §3.3 already raised put the team's
    ledger at 2 and its posture at WATCH before the sweep is taken.

    Design: Difficulty/transitive_cascade/compliance_run_breach_flag_probation_cascade
    """
    scenario = _breach_cascade_world(api)
    assert_severity_ledger(scenario.team_before, 2, "the team before the sweep")
    assert scenario.team_before["compliance_status"] == TEAM_WATCH

    _run_sweep(api, scenario)

    milestones = fixtures.milestones_of(api, scenario.plan_id)
    assert len(milestones) == WEEKLY_STEP_MILESTONE_COUNT
    due = _due_week_indices()
    assert due == [0, 1, 2], "three of the six milestone dates have come due"
    for milestone in milestones:
        week_index = milestone["week_index"]
        if week_index in due:
            assert milestone["status"] == MILESTONE_MISSED, (
                f"week {week_index}: a due milestone with no weigh-in is missed"
            )
            assert milestone["evaluated_recorded_weight_lbs"] is None, (
                f"week {week_index}: no candidate weigh-in leaves the evaluated "
                "weight null"
            )
        else:
            assert milestone["status"] == MILESTONE_SCHEDULED, (
                f"week {week_index}: a milestone still in the future is skipped"
            )
            assert milestone["evaluated_recorded_weight_lbs"] is None


def test_compliance_run_breaches_the_plan_past_the_breach_limit(api: ApiClient) -> None:
    """Hop two reassesses the plan and declares it breached.

    §3.6 recomputes the plan's missed-milestone count as the number of milestones
    whose status is MISSED, and when that count reaches or exceeds the season's
    breach limit — two, by default — the plan moves from certified to breached and
    its breach count increments by one.  Three of the six milestones were missed,
    so the plan is breached on the same sweep that judged them.

    Design: Difficulty/transitive_cascade/compliance_run_breach_flag_probation_cascade
    """
    scenario = _breach_cascade_world(api)

    _run_sweep(api, scenario)

    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["status"] == PLAN_BREACHED
    assert plan["missed_milestone_count"] == 3
    assert plan["missed_milestone_count"] >= DEFAULT_PLAN_BREACH_LIMIT
    assert plan["breach_count"] == 1


def test_compliance_run_raises_one_open_plan_breach_flag(api: ApiClient) -> None:
    """Hop three raises the plan-breach flag on the wrestler.

    §3.6 raises a health flag with source PLAN_BREACH, severity 3 and status OPEN
    because the plan became breached, and §3.9 pins that severity per source and
    leaves the weigh-in reference null for a plan-sourced flag.  §2.10 makes the
    filtered flag listing the only discovery channel for a cascade-raised flag,
    and the wrestler's open-flag count reports the three flags now sitting open.

    Design: Difficulty/transitive_cascade/compliance_run_breach_flag_probation_cascade
    """
    scenario = _breach_cascade_world(api)

    _run_sweep(api, scenario)

    breach_flags = assert_row_count(
        api.list_health_flags(
            STATE_OFFICE,
            {"wrestler_id": scenario.wrestler_id, "source": FLAG_PLAN_BREACH},
        ),
        1,
        "plan-breach flags of the wrestler",
    )
    flag = breach_flags[0]
    assert flag["status"] == FLAG_OPEN
    assert flag["severity"] == FLAG_SEVERITY[FLAG_PLAN_BREACH]
    assert_flag_severity_matches_source(flag)
    assert flag["weigh_in_id"] is None, "a plan-sourced flag carries no weigh-in id"

    open_flags = assert_row_count(
        api.list_health_flags(
            STATE_OFFICE,
            {"wrestler_id": scenario.wrestler_id, "status": FLAG_OPEN},
        ),
        3,
        "open flags of the wrestler",
    )
    assert sum(int(row["severity"]) for row in open_flags) == 5

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["open_health_flag_count"] == 3


def test_compliance_run_pushes_the_severity_ledger_to_probation(api: ApiClient) -> None:
    """Hop four recomputes the team's ledger and lands it on probation.

    §2.9 defines the ledger as the sum of severity over every flag of the team's
    wrestlers whose status is OPEN or ESCALATED, and derives the posture from it:
    CLEAR at exactly 0, WATCH between 1 and 4 inclusive, PROBATION at 5 or more.
    Two hydration flags worth one point each plus the breach flag's three points
    total exactly 5, so the team crosses from WATCH straight onto PROBATION on the
    same sweep, and §3.6 requires the recomputation inside that request.

    Design: Difficulty/transitive_cascade/compliance_run_breach_flag_probation_cascade
    """
    scenario = _breach_cascade_world(api)

    _run_sweep(api, scenario)

    team = fixtures.read_team(api, scenario.team_id)
    assert team["open_flag_severity_total"] == 5
    assert team["compliance_status"] == TEAM_PROBATION
    assert_severity_ledger(team, 5, "the team after the sweep")


def test_compliance_run_demotes_the_eligible_wrestler_to_restricted(api: ApiClient) -> None:
    """Hop five demotes the wrestler while leaving the certification dimension alone.

    §3.6 demotes any ELIGIBLE wrestler of a team that has just landed on
    PROBATION to RESTRICTED, and §3.9 restates that a probation demotion leaves
    the certification dimension completely untouched.  The wrestler therefore ends
    the sweep still certified but restricted — the two dimensions moved
    independently across the whole five-hop chain.

    Design: Difficulty/transitive_cascade/compliance_run_breach_flag_probation_cascade
    """
    scenario = _breach_cascade_world(api)
    assert scenario.wrestler["certification_status"] == WRESTLER_CERTIFIED

    _run_sweep(api, scenario)

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["eligibility_status"] == ELIGIBILITY_RESTRICTED
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
