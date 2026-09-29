"""
Cross-entity state dependencies: when an operation on one row is legal or illegal
purely because of the current state of a *different* row.

Two dependencies are exercised here, both taken from the requirements document.

The first runs from a child action to a sibling referenced row.  Certifying a
descent plan requires "the plan's source assessment to *still* be in `status`
`VALIDATED` (a source assessment that has since been superseded or voided yields
`ERR_ASSESSMENT_INVALID_STATE`)" (§3.5).  Nothing about the plan itself changes —
it stays `DRAFT`, on the same wrestler, with the same target — yet the identical
certify call flips from legal to refused because a newer assessment for the same
wrestler pushed the source assessment `VALIDATED → SUPERSEDED` (§3.3).

The second runs from a child action to an ancestor's aggregate posture.  Entering
a competitor is refused with `ERR_TEAM_ON_PROBATION` when "a wrestler whose team
is on `PROBATION`" is entered (§3.7), where the posture is derived live from the
team's severity ledger (§2.9).  The gate is reversible in the same test: a
`DISMISSED` medical review restores the ledger to its pre-raise value, returns the
team to `WATCH`, and the byte-identical entry request then succeeds (§3.9).
"""

from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_row_count,
    assert_severity_ledger,
    assert_weight_equals,
)
from test_helpers.constants import (
    ASSESSMENT_VALIDATED,
    ASSESSMENT_SUPERSEDED,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_MIN_WEIGHT_CLASS_LBS,
    CANON_TARGET_CLASS_LBS,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_RESTRICTED,
    ENTRY_ENTERED,
    EVENT_SCHEDULED,
    EVENT_TYPE_DUAL,
    FLAG_DISMISSED,
    FLAG_ESCALATED,
    FLAG_OPEN,
    FLAG_PLAN_BREACH,
    OUTCOME_BLOCKED_TEAM_PROBATION,
    PLAN_BREACHED,
    PLAN_CERTIFIED,
    PLAN_DRAFT,
    PLAN_START_DATE,
    TEAM_PROBATION,
    TEAM_WATCH,
    VARIANT_LINEAR_RATE,
    VARIANT_WEEKLY_STEP,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEEKLY_STEP_SCHEDULE,
    WEEKLY_STEP_TOTAL_WEEKS,
    WRESTLER_CERTIFIED,
    WRESTLER_PROVISIONAL,
)
from test_helpers.test_users import STATE_OFFICE, coach_headers

# ── The superseding measurement of the first dependency ──────────────
# A second, later assessment of the same wrestler, hydrated well inside the
# 1.025 ceiling so that it finalizes on the validated arm and therefore moves the
# earlier assessment VALIDATED -> SUPERSEDED (§3.3).
SUPERSEDING_CLOCK = "2026-11-02T12:00:00Z"
SUPERSEDING_ASSESSED_AT = "2026-11-02T09:00:00Z"
SUPERSEDING_MEASURED_WEIGHT_LBS = 158.4
SUPERSEDING_USG = 1.019

# ── The probation scenario of the second dependency ──────────────────
# Two hydration failures on distinct UTC calendar days, each contributing a
# severity-1 OPEN flag, which puts the team's ledger at 2 and its posture at
# WATCH (§2.9).
DRY_READINGS = (
    ("2026-11-03T09:00:00Z", 158.0),
    ("2026-11-04T09:00:00Z", 157.0),
)
DRY_USG = 1.030
WATCH_LEDGER_TOTAL = 2
PROBATION_LEDGER_TOTAL = 5

BREACH_EVENT_NAME = "Thanksgiving Duals"
BREACH_EVENT_DATE = "2026-11-25"
SWEEP_CLOCK = "2026-11-20T00:00:00Z"

# On 2026-11-25 the governing milestone is week three, dated 2026-11-23, whose
# allowable weight is 152.5 pounds; with no growth allowance published the
# smallest class at or above that floor is 157, and the hard-floor class is 150,
# so the lowest eligible class is exactly the class entered (§3.7).
GOVERNING_ALLOWABLE_WEIGHT_LBS = WEEKLY_STEP_SCHEDULE[3]
ENTRY_CLASS_LBS = 157
ENTRY_SEASON_WIN_COUNT = 5


def _draft_plan_on_validated_assessment(
    api: ApiClient, plan_variant: str = VARIANT_WEEKLY_STEP
) -> fixtures.Scenario:
    """An open season carrying a never-certified DRAFT plan on a VALIDATED source.

    The chain of §3.1 through §3.5: season opened, team registered, assessor
    trained to the credential threshold, wrestler rostered, one assessment
    finalized on the validated arm, and a plan opened on that assessment with a
    150 pound target and a 2026-11-02 start date.
    """
    scenario = fixtures.assessed_wrestler(api)
    plan = fixtures.create_plan(
        api,
        scenario.wrestler_id,
        scenario.team_id,
        scenario.assessment_id,
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
        plan_variant=plan_variant,
    )
    scenario.update(plan=plan, plan_id=plan["id"])
    return scenario


def _supersede_the_source_assessment(
    api: ApiClient, scenario: fixtures.Scenario
) -> Dict[str, Any]:
    """Finalize a newer validated assessment for the same wrestler.

    §3.3: "Any *other* assessment of the same wrestler currently in `VALIDATED`
    is moved `VALIDATED → SUPERSEDED`", and the wrestler's
    `source_assessment_id` is repointed at the newly validated assessment.
    """
    fixtures.move_clock(api, SUPERSEDING_CLOCK)
    return fixtures.create_validated_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=SUPERSEDING_ASSESSED_AT,
        measured_weight_lbs=SUPERSEDING_MEASURED_WEIGHT_LBS,
        urine_specific_gravity=SUPERSEDING_USG,
    )


def _hydration_failure(api: ApiClient, scenario: fixtures.Scenario,
                       assessed_at: str, measured_weight_lbs: float) -> Dict[str, Any]:
    """Open and finalize an assessment on the hydration-failure arm.

    §3.3: a `urine_specific_gravity` strictly greater than the season's
    `hydration_max_specific_gravity` sets `hydration_passed` false, produces no
    certified figure, leaves the wrestler's `certification_status` untouched and
    does *not* repoint `source_assessment_id`, and raises a `HYDRATION_FAIL` flag
    of severity 1 in `OPEN`.
    """
    assessment = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=assessed_at,
        measured_weight_lbs=measured_weight_lbs,
        urine_specific_gravity=DRY_USG,
    )
    return fixtures.finalize_assessment(api, assessment["id"], scenario.assessor_id)


def _team_on_probation_by_plan_breach(api: ApiClient) -> fixtures.Scenario:
    """A CERTIFIED wrestler on a BREACHED plan whose team has landed on PROBATION.

    Two hydration failures put the severity ledger at 2 (`WATCH`).  A compliance
    run on 2026-11-20 then judges the three milestones already due — weeks zero,
    one and two, dated 2026-11-02, 2026-11-09 and 2026-11-16 — as `MISSED`
    because no weigh-in speaks for any of them, which reaches the season's
    `plan_breach_limit` of two, moves the plan `CERTIFIED → BREACHED` and raises a
    `PLAN_BREACH` flag of severity 3.  The ledger therefore reads 5 and the
    posture is `PROBATION` (§3.6, §2.9).
    """
    scenario = fixtures.certified_wrestler(api)
    for assessed_at, measured_weight_lbs in DRY_READINGS:
        _hydration_failure(api, scenario, assessed_at, measured_weight_lbs)
    event = fixtures.create_event(
        api,
        scenario.season_id,
        BREACH_EVENT_NAME,
        BREACH_EVENT_DATE,
        EVENT_TYPE_DUAL,
        competition_days=1,
        weigh_in_days=1,
    )
    fixtures.move_clock(api, SWEEP_CLOCK)
    fixtures.run_compliance(api, scenario.season_id)
    scenario.update(event=event, event_id=event["id"])
    return scenario


def _flags_by_source(api: ApiClient, wrestler_id: str, source: str):
    """The wrestler's flags of one source; the listing is the only discovery channel."""
    response = api.list_health_flags(
        STATE_OFFICE, {"wrestler_id": wrestler_id, "source": source, "limit": 100}
    )
    rows, _meta = validate_paginated(response)
    return rows


def _attempt_entry(api: ApiClient, scenario: fixtures.Scenario):
    """The identical competition-entry request, as the wrestler's own coach."""
    return api.create_entry(
        scenario.event_id,
        factories.entry_payload(
            scenario.wrestler_id, ENTRY_CLASS_LBS, ENTRY_SEASON_WIN_COUNT
        ),
        coach_headers(scenario.team_id),
    )


# ── Certifying a plan depends on its source assessment's live state ──

@pytest.mark.parametrize("plan_variant", [VARIANT_WEEKLY_STEP, VARIANT_LINEAR_RATE])
def test_certify_refused_once_source_assessment_is_superseded(api, plan_variant):
    """A newer validated assessment makes the unchanged certify call illegal.

    §3.5 requires "the plan's source assessment to *still* be in `status`
    `VALIDATED` (a source assessment that has since been superseded or voided
    yields `ERR_ASSESSMENT_INVALID_STATE`)".  §3.3 supplies the state change: the
    second finalized assessment moves the first `VALIDATED → SUPERSEDED` and
    repoints the wrestler's `source_assessment_id`.  Every other certify
    precondition still holds — the plan is `DRAFT`, the season is `OPEN`, the 150
    pound target still meets the wrestler's `min_weight_class_lbs`, and the
    wrestler is `PROVISIONAL` — so the refusal is attributable only to the
    sibling assessment's state.

    Design: Difficulty/cross_entity_state_dependency/plan_certify_requires_validated_source_assessment
    """
    scenario = _draft_plan_on_validated_assessment(api, plan_variant)

    second = _supersede_the_source_assessment(api, scenario)

    # The sibling row moved, and only the sibling row.
    first = fixtures.read_assessment(api, scenario.assessment_id)
    assert first["status"] == ASSESSMENT_SUPERSEDED
    assert second["status"] == ASSESSMENT_VALIDATED

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["source_assessment_id"] == second["id"]
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL

    response = api.certify_descent_plan(scenario.plan_id, STATE_OFFICE)
    validate_error(response, api_errors.ERR_ASSESSMENT_INVALID_STATE, 409)


def test_certify_refusal_leaves_the_plan_draft_on_its_original_source(api):
    """The refused certification mutates nothing on the plan itself.

    The plan was never party to the state change: §3.5 pins
    `source_assessment_id` at creation and no operation repoints it, and the
    refused `DRAFT → CERTIFIED` transition leaves the plan in `DRAFT` with its
    schedule counters at their creation values — `total_weeks` and
    `projected_certification_date` null, `milestone_count` 0 (§3.5).

    Design: Difficulty/cross_entity_state_dependency/plan_certify_requires_validated_source_assessment
    """
    scenario = _draft_plan_on_validated_assessment(api)
    version_before = fixtures.read_plan(api, scenario.plan_id)["version"]

    _supersede_the_source_assessment(api, scenario)

    response = api.certify_descent_plan(scenario.plan_id, STATE_OFFICE)
    validate_error(response, api_errors.ERR_ASSESSMENT_INVALID_STATE, 409)

    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["status"] == PLAN_DRAFT
    assert plan["source_assessment_id"] == scenario.assessment_id
    assert plan["target_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert plan["total_weeks"] is None
    assert plan["projected_certification_date"] is None
    assert plan["milestone_count"] == 0
    assert plan["version"] == version_before


def test_certify_refusal_generates_no_milestone_schedule(api):
    """No milestone row exists, because only the certifying cascade creates them.

    §2.10: milestones "generated by plan certification are readable only through
    the plan's milestone listing" and `DescentMilestone.plan_id` "is set only by
    the plan-certification cascade".  §3.5 generates the whole progression in one
    shot as part of `DRAFT → CERTIFIED`; a refused certification therefore leaves
    the listing empty.

    Design: Difficulty/cross_entity_state_dependency/plan_certify_requires_validated_source_assessment
    """
    scenario = _draft_plan_on_validated_assessment(api)
    _supersede_the_source_assessment(api, scenario)

    response = api.certify_descent_plan(scenario.plan_id, STATE_OFFICE)
    validate_error(response, api_errors.ERR_ASSESSMENT_INVALID_STATE, 409)

    listing = api.list_plan_milestones(scenario.plan_id, STATE_OFFICE, {"limit": 100})
    assert_row_count(listing, 0, "milestones of an uncertified plan")


def test_certify_refusal_leaves_wrestler_eligibility_and_season_counter_untouched(api):
    """Neither dimension of the wrestler moves, and the season counter stays at zero.

    §3.5 makes plan certification the act that steps the certification dimension
    `PROVISIONAL → CERTIFIED`, takes the eligibility dimension out of
    `INELIGIBLE` and increments the season's `certified_wrestler_count`.  With the
    certification refused none of that happens: §3.3 already states that
    validating an assessment leaves `eligibility_status` "exactly as it was", and
    §3.1 starts every wrestler at `INELIGIBLE`.

    Design: Difficulty/cross_entity_state_dependency/plan_certify_requires_validated_source_assessment
    """
    scenario = _draft_plan_on_validated_assessment(api)
    _supersede_the_source_assessment(api, scenario)

    response = api.certify_descent_plan(scenario.plan_id, STATE_OFFICE)
    validate_error(response, api_errors.ERR_ASSESSMENT_INVALID_STATE, 409)

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE

    season = get_success_data(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 0


def test_certify_succeeds_while_the_source_assessment_is_still_validated(api):
    """The same call on the same plan is legal while the sibling row still reads VALIDATED.

    The baseline of §3.5: out of `DRAFT`, with the source assessment still
    `VALIDATED`, certification generates one milestone per week index from zero
    through `total_weeks` inclusive — six rows for the document's worked
    159.6 pound baseline at 1.5 percent down to 150 — sets `milestone_count` to
    `total_weeks` plus one, steps the wrestler `PROVISIONAL → CERTIFIED`, and
    increments `certified_wrestler_count`.

    Design: Difficulty/cross_entity_state_dependency/plan_certify_requires_validated_source_assessment
    """
    scenario = _draft_plan_on_validated_assessment(api)

    response = api.certify_descent_plan(scenario.plan_id, STATE_OFFICE)
    plan = validate_success(response, 200)
    assert plan["status"] == PLAN_CERTIFIED
    assert plan["total_weeks"] == WEEKLY_STEP_TOTAL_WEEKS
    assert plan["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT

    listing = api.list_plan_milestones(scenario.plan_id, STATE_OFFICE, {"limit": 100})
    assert_row_count(listing, WEEKLY_STEP_MILESTONE_COUNT, "generated schedule")

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_ELIGIBLE

    season = get_success_data(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 1


# ── Entering a competitor depends on the team's live posture ──────────

def test_entry_refused_while_the_team_sits_on_probation(api):
    """A `PROBATION` posture on the ancestor team refuses the entry outright.

    §3.7: "A wrestler whose team is on `PROBATION` is refused with
    `ERR_TEAM_ON_PROBATION`".  §2.9 derives that posture from the severity ledger,
    which the `PLAN_BREACH` raise of severity 3 pushes from 2 to 5, and §3.6
    demotes the team's `ELIGIBLE` wrestlers to `RESTRICTED` at the same moment.

    Design: Difficulty/cross_entity_state_dependency/entry_creation_blocked_by_team_probation
    """
    scenario = _team_on_probation_by_plan_breach(api)

    team = fixtures.read_team(api, scenario.team_id)
    assert_severity_ledger(team, PROBATION_LEDGER_TOTAL, "team after the breach raise")
    assert team["compliance_status"] == TEAM_PROBATION

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_RESTRICTED

    validate_error(
        _attempt_entry(api, scenario), api_errors.ERR_TEAM_ON_PROBATION, 409
    )


def test_refused_entry_persists_no_row_and_leaves_the_event_counter_at_zero(api):
    """The refusal creates nothing: no entry row and no counter movement.

    §3.7 pins the successful path — "A successful entry lands in `ENTERED` ... and
    increments the event's `entry_count`" — so a refused attempt leaves the
    filtered entry listing empty and `entry_count` at the 0 the event was
    scheduled with, with the event still `SCHEDULED`.

    Design: Difficulty/cross_entity_state_dependency/entry_creation_blocked_by_team_probation
    """
    scenario = _team_on_probation_by_plan_breach(api)

    validate_error(
        _attempt_entry(api, scenario), api_errors.ERR_TEAM_ON_PROBATION, 409
    )

    listing = api.list_entries(STATE_OFFICE, {"event_id": scenario.event_id})
    assert_row_count(listing, 0, "entries of the event after the refusal")

    event = fixtures.read_event(api, scenario.event_id)
    assert event["entry_count"] == 0
    assert event["status"] == EVENT_SCHEDULED


def test_probation_is_the_only_thing_blocking_this_entry(api):
    """The logged certification-database check attributes the block to the team alone.

    §3.7 evaluates the check's `outcome` "in the same precedence the entry
    operation itself uses", so a `BLOCKED_TEAM_PROBATION` verdict proves the
    earlier gates all passed: the wrestler is not disqualified, is `CERTIFIED`
    rather than `UNCERTIFIED` or `SUSPENDED`, holds no `ESCALATED` flag, and the
    requested 157 pound class is not beneath his floor.  The four pinned steps put
    that floor exactly at 157: no growth allowance is published, the governing
    `BREACHED` plan's latest milestone due on 2026-11-25 is week three at 152.5
    pounds, the eligibility floor is the larger of that and the 147.6 pound
    certified minimum, the smallest class reaching it is 157, and the 150 pound
    hard-floor class does not raise it.

    Design: Difficulty/cross_entity_state_dependency/entry_creation_blocked_by_team_probation
    """
    scenario = _team_on_probation_by_plan_breach(api)

    validate_error(
        _attempt_entry(api, scenario), api_errors.ERR_TEAM_ON_PROBATION, 409
    )

    check = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, scenario.event_id, ENTRY_CLASS_LBS
    )
    assert check["as_of_date"] == BREACH_EVENT_DATE
    assert_weight_equals(check["growth_allowance_lbs"], 0.0, "growth_allowance_lbs")
    assert_weight_equals(
        check["schedule_allowable_weight_lbs"],
        GOVERNING_ALLOWABLE_WEIGHT_LBS,
        "schedule_allowable_weight_lbs",
    )
    assert check["lowest_eligible_class_lbs"] == ENTRY_CLASS_LBS
    assert check["outcome"] == OUTCOME_BLOCKED_TEAM_PROBATION
    assert check["blocking_error_id"] == api_errors.ERR_TEAM_ON_PROBATION

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert_weight_equals(
        wrestler["minimum_certified_weight_lbs"],
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        "minimum_certified_weight_lbs",
    )
    assert wrestler["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS
    assert_row_count(
        api.list_health_flags(
            STATE_OFFICE,
            {"wrestler_id": scenario.wrestler_id, "status": FLAG_ESCALATED},
        ),
        0,
        "escalated flags",
    )


def test_dismissing_the_breach_flag_readmits_the_identical_entry(api):
    """The gate is read live: the compensating review reopens the same request.

    §3.9 makes `OPEN → DISMISSED` the compensating action on the ledger — it
    "removes the flag's `severity`, restoring the ledger to exactly its pre-raise
    value", recomputes the posture, and returns every `RESTRICTED` and `CERTIFIED`
    wrestler of the team to `ELIGIBLE` when the team leaves `PROBATION`.  With the
    ledger back at 2 the team reads `WATCH`, which "changes no wrestler's
    eligibility", and the byte-identical entry request of §3.7 now lands in
    `ENTERED` and increments `entry_count`.

    Design: Difficulty/cross_entity_state_dependency/entry_creation_blocked_by_team_probation
    """
    scenario = _team_on_probation_by_plan_breach(api)
    validate_error(
        _attempt_entry(api, scenario), api_errors.ERR_TEAM_ON_PROBATION, 409
    )

    breach_flags = _flags_by_source(api, scenario.wrestler_id, FLAG_PLAN_BREACH)
    assert len(breach_flags) == 1
    assert breach_flags[0]["status"] == FLAG_OPEN
    fixtures.review_flag(
        api,
        breach_flags[0]["id"],
        FLAG_DISMISSED,
        "Milestones missed during documented illness; plan breach dismissed.",
    )

    team = fixtures.read_team(api, scenario.team_id)
    assert_severity_ledger(team, WATCH_LEDGER_TOTAL, "team after the dismissal")
    assert team["compliance_status"] == TEAM_WATCH

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_ELIGIBLE

    entry = validate_success(_attempt_entry(api, scenario), 201)
    assert entry["status"] == ENTRY_ENTERED
    assert entry["weight_class_lbs"] == ENTRY_CLASS_LBS
    assert entry["wrestler_id"] == scenario.wrestler_id
    assert entry["seed_number"] is None
    assert entry["weight_class_change_count"] == 0

    event = fixtures.read_event(api, scenario.event_id)
    assert event["entry_count"] == 1


def test_dismissing_the_breach_flag_does_not_rehabilitate_the_plan(api):
    """The dismissal clears the ledger entry, not the plan's breached state.

    §3.9 gives medical review authority over the flag, the ledger, the posture and
    the eligibility dimension only.  §3.6 leaves revision as the coach's sole route
    back out of `BREACHED`, and states that `missed_milestone_count` "is
    emphatically **not** reset — a breach that has happened stays on the record",
    so the plan reads `BREACHED` with its breach recorded both before and after the
    dismissal.

    Design: Difficulty/cross_entity_state_dependency/entry_creation_blocked_by_team_probation
    """
    scenario = _team_on_probation_by_plan_breach(api)

    before = fixtures.read_plan(api, scenario.plan_id)
    assert before["status"] == PLAN_BREACHED
    assert before["breach_count"] == 1

    breach_flags = _flags_by_source(api, scenario.wrestler_id, FLAG_PLAN_BREACH)
    fixtures.review_flag(
        api, breach_flags[0]["id"], FLAG_DISMISSED, "Breach flag dismissed on review."
    )

    after = fixtures.read_plan(api, scenario.plan_id)
    assert after["status"] == PLAN_BREACHED
    assert after["breach_count"] == 1
    assert after["missed_milestone_count"] == before["missed_milestone_count"]
    assert after["revision_count"] == 0
