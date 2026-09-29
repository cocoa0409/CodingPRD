"""
Endpoint surface behaviour: computed reads, bulk sweeps, locked-bracket moves,
three-way creation links, the create/read/list round trip and action endpoints.

Six endpoint families are exercised here, each against the requirements it is
specified by.

* The certification-database check of §3.7 is a *logging* computed read: it
  always answers HTTP 201 and reports the verdict a real entry attempt would
  have produced as data, together with the four pinned derivation steps that
  produced the class floor.
* The season compliance run of §3.6 is a sweep with per-plan semantics: one call
  judges every certified plan's due milestones independently, so one plan's
  missed milestone neither aborts the sweep nor rolls back another plan's met
  one.
* The state-office weight-class change of §3.8 is the only sanctioned way to
  move a competitor on a locked bracket, and it reseeds both the vacated and the
  destination class inline, which is what makes ``seed_integrity_sum`` a
  conserved quantity under §2.9.
* Opening a program audit under §3.9 is a three-way link — the season in the
  path, the ``assessor_id`` in the body and every ``samples[].assessment_id`` —
  and §2.8 resolves each arm before anything is written.
* Season and growth-allowance creation, reads and listings of §3.1 and §2.3
  carry every overridden regulatory constant back unchanged and order the
  child listing by ``effective_date`` ascending rather than by insertion.
* Administrative assessor suspension of §3.2 is an action endpoint whose
  side-effect set is deliberately narrow: it voids the assessor's ``DRAFT``
  assessments only and leaves validated work, and the wrestlers certified from
  it, alone.

Everything runs over HTTP through the shared client.  The server is restarted
before every test, so each precondition is built through the declared endpoints
and the logical clock starts back at its default instant.
"""

from typing import Any, Dict, List, Tuple

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_append_only_row,
    assert_instant_equals,
    assert_mutable_row,
    assert_row_count,
    assert_seed_integrity_sum,
    assert_weight_equals,
    expected_deviation,
    expected_lowest_eligible_class,
    expected_sample_mean_score,
    ids_of,
)
from test_helpers.constants import (
    ASSESSMENT_DAY_INSTANT,
    ASSESSMENT_DRAFT,
    ASSESSMENT_VALIDATED,
    ASSESSMENT_VOIDED,
    ASSESSOR_CERTIFIED,
    ASSESSOR_SUSPENDED,
    AUDIT_FINALIZED,
    AUDIT_OPEN,
    AUDIT_PASS,
    AUDIT_TYPE_ASSESSOR_SAMPLE,
    CANON_BODY_FAT_PCT,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_MIN_WEIGHT_CLASS_LBS,
    CANON_TARGET_CLASS_LBS,
    DEFAULT_AUDIT_FAIL_THRESHOLD_PCT,
    DEFAULT_PLAN_BREACH_LIMIT,
    DEFAULT_TEAM_NAME,
    ENTRY_SEEDED,
    EVENT_TYPE_DUAL,
    EVENT_TYPE_TOURNAMENT,
    METHOD_BIA,
    METHOD_SKINFOLD,
    MILESTONE_MET,
    MILESTONE_MISSED,
    MILESTONE_SCHEDULED,
    OUTCOME_BLOCKED_CLASS_BELOW_MINIMUM,
    OUTCOME_BLOCKED_NOT_CERTIFIED,
    OUTCOME_CLEARED,
    PLAN_CERTIFIED,
    PLAN_START_DATE,
    SCORING_SAMPLE_MEAN,
    SEASON_OPEN,
    SEASON_SETUP,
    SEX_FEMALE,
    TEAM_PROBATION,
    VOID_REASON_ASSESSOR_SUSPENDED,
    WEEKLY_STEP_MILESTONE_DATES,
    WEEKLY_STEP_SCHEDULE,
    WEIGH_IN_PASS,
    WRESTLER_PROVISIONAL,
)
from test_helpers.test_users import STATE_OFFICE, assessor_headers, coach_headers

# Syntactically well formed identifiers that resolve to no stored row, for the
# body-level foreign-key resolution §2.8 requires before anything is written.
_UNKNOWN_ASSESSOR_ID = "b1b1b1b1-b1b1-4b1b-8b1b-b1b1b1b1b1b1"
_UNKNOWN_ASSESSMENT_ID = "b2b2b2b2-b2b2-4b2b-8b2b-b2b2b2b2b2b2"

# The growth-allowance date the class-floor derivation reads, and the event the
# check is run against.  §3.1 makes an allowance inclusive of its own effective
# date, and §3.7 copies the event's date into the check's ``as_of_date``.
_GROWTH_DATE = "2026-12-01"
_GROWTH_LBS = 1.0
_EVENT_DATE = "2026-12-12"

# The last milestone of the canonical compounding schedule, effective
# 2026-12-07, is the one on or before an as-of date of 2026-12-12.
_GOVERNING_ALLOWABLE_LBS = WEEKLY_STEP_SCHEDULE[-1]
_GOVERNING_MILESTONE_DATE = WEEKLY_STEP_MILESTONE_DATES[-1]


def _rows(response) -> List[Dict[str, Any]]:
    """The rows of a list response, with the envelope and pagination validated."""
    rows, _meta = validate_paginated(response)
    return rows


def _milestone_rows(api, plan_id: str) -> List[Dict[str, Any]]:
    """A plan's milestones, which §2.10 makes their only discovery channel."""
    return _rows(api.list_plan_milestones(plan_id, STATE_OFFICE, {"limit": 100}))


def _certified_roster_member(
    api,
    scenario,
    assessor_id: str,
    full_name: str,
    assessed_at: str,
    target_class_lbs: int = CANON_TARGET_CLASS_LBS,
    plan_start_date: str = PLAN_START_DATE,
) -> Tuple[str, str, str]:
    """Roster, assess and certify one wrestler, returning the three ids created.

    This is the chain §3.1 through §3.5 require before a wrestler may be entered
    in a competition: a roster addition, a validated assessment that produces the
    certified figures, and a certified descent plan.
    """
    wrestler = fixtures.create_wrestler(api, scenario.team_id, full_name)
    assessment = fixtures.create_validated_assessment(
        api, wrestler["id"], assessor_id, assessed_at=assessed_at
    )
    plan = fixtures.create_certified_plan(
        api,
        wrestler["id"],
        scenario.team_id,
        assessment["id"],
        target_class_lbs=target_class_lbs,
        plan_start_date=plan_start_date,
    )
    return wrestler["id"], assessment["id"], plan["id"]


# The ladder member immediately beneath the computed floor: 144 plus the 1.0 lb
# growth allowance is 145.0, still short of the 147.9 lb governing schedule
# value, so §3.7 leaves it out of the candidate set.
_BELOW_FLOOR_CLASS_LBS = 144


def _eligibility_scenario(api):
    """An open season carrying one growth-allowance date, one event, one wrestler.

    The wrestler is rostered but not yet assessed, so their certification
    dimension still reads ``UNCERTIFIED`` and §3.7's second outcome applies.
    """
    scenario = fixtures.open_season_with_team(api)
    fixtures.publish_growth_allowance(
        api,
        scenario.season_id,
        _GROWTH_DATE,
        _GROWTH_LBS,
        note="December growth allowance",
    )
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    event = fixtures.create_event(
        api, scenario.season_id, "State Qualifier", _EVENT_DATE, EVENT_TYPE_TOURNAMENT
    )
    scenario.update(
        assessor_id=assessor["id"],
        wrestler_id=wrestler["id"],
        event_id=event["id"],
    )
    return scenario


def _certify_scenario_wrestler(api, scenario) -> Dict[str, Any]:
    """Assess and certify the scenario's wrestler on the canonical measurement."""
    assessment = fixtures.create_validated_assessment(
        api, scenario.wrestler_id, scenario.assessor_id
    )
    plan = fixtures.create_certified_plan(
        api,
        scenario.wrestler_id,
        scenario.team_id,
        assessment["id"],
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
    )
    return plan


def _run_check(api, scenario, requested_class_lbs: int) -> Dict[str, Any]:
    """Run the certification-database check, which §4 answers with HTTP 201."""
    response = api.create_eligibility_check(
        scenario.wrestler_id,
        factories.eligibility_check_payload(scenario.event_id, requested_class_lbs),
        scenario.coach,
    )
    return validate_success(response, 201)


def test_eligibility_check_on_an_uncertified_wrestler_logs_a_blocked_verdict(api):
    """A blocked verdict is data, never a refusal.

    The wrestler has no validated assessment on file, so §3.7 reports
    ``BLOCKED_NOT_CERTIFIED`` carrying the error a real entry attempt would have
    raised — and still answers HTTP 201, logging the row.  Step one of the floor
    derivation and the as-of date are computed even on a blocked check, and the
    governing schedule value reads null because the wrestler holds no plan in
    ``CERTIFIED`` or ``BREACHED``.  §2.4 makes the logged check append-only.

    Design: Corner/endpoints/eligibility_check_computed_read_matches_the_pinned_calculation
    """
    scenario = _eligibility_scenario(api)

    check = _run_check(api, scenario, CANON_TARGET_CLASS_LBS)

    assert_append_only_row(check, "eligibility check")
    assert check["wrestler_id"] == scenario.wrestler_id
    assert check["event_id"] == scenario.event_id
    assert check["requested_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert check["outcome"] == OUTCOME_BLOCKED_NOT_CERTIFIED
    assert check["blocking_error_id"] == api_errors.ERR_WRESTLER_NOT_CERTIFIED
    # §3.7: the as-of date is copied from the referenced event's event_date.
    assert check["as_of_date"] == _EVENT_DATE
    # Step one: the allowance total as of that date, its lower bound inclusive.
    assert_weight_equals(
        check["growth_allowance_lbs"], _GROWTH_LBS, "growth_allowance_lbs"
    )
    # Step two: no plan in CERTIFIED or BREACHED exists, so the value is null.
    assert check["schedule_allowable_weight_lbs"] is None
    assert_instant_equals(check["checked_at"], ASSESSMENT_DAY_INSTANT, "checked_at")


def test_eligibility_check_blocks_a_class_beneath_the_pinned_floor(api):
    """The four pinned derivation steps, and the verdict a class beneath them earns.

    With the canonical measurement the wrestler's minimum certified weight is
    147.6 lb and their hard-floor class is 150.  The certified compounding
    schedule of §3.5 puts its last milestone at 147.9 lb effective 2026-12-07,
    which is the latest milestone on or before the event's 2026-12-12 date, so
    §3.7 step two takes 147.9 as the governing schedule value and step three
    raises the floor to it.  Step four then finds 144 outside the candidate set
    even with the 1.0 lb allowance, and because the governing plan is
    ``CERTIFIED`` rather than ``BREACHED`` the verdict is
    ``BLOCKED_CLASS_BELOW_MINIMUM``.

    Design: Corner/endpoints/eligibility_check_computed_read_matches_the_pinned_calculation
    """
    scenario = _eligibility_scenario(api)
    plan = _certify_scenario_wrestler(api, scenario)
    milestones = _milestone_rows(api, plan["id"])
    assert milestones[-1]["effective_date"] == _GOVERNING_MILESTONE_DATE
    assert_weight_equals(
        milestones[-1]["allowable_weight_lbs"],
        _GOVERNING_ALLOWABLE_LBS,
        "governing milestone allowable_weight_lbs",
    )

    check = _run_check(api, scenario, _BELOW_FLOOR_CLASS_LBS)

    assert check["outcome"] == OUTCOME_BLOCKED_CLASS_BELOW_MINIMUM
    assert check["blocking_error_id"] == api_errors.ERR_CLASS_BELOW_CERTIFIED_MINIMUM
    assert_weight_equals(
        check["schedule_allowable_weight_lbs"],
        _GOVERNING_ALLOWABLE_LBS,
        "schedule_allowable_weight_lbs",
    )
    assert_weight_equals(
        check["growth_allowance_lbs"], _GROWTH_LBS, "growth_allowance_lbs"
    )
    assert check["lowest_eligible_class_lbs"] == expected_lowest_eligible_class(
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        _GOVERNING_ALLOWABLE_LBS,
        _GROWTH_LBS,
        CANON_MIN_WEIGHT_CLASS_LBS,
    )
    assert check["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS


def test_eligibility_check_clears_a_request_at_the_computed_floor(api):
    """A request landing exactly on the computed floor clears.

    §2.6 pins the regime so that landing exactly on a limit is permitted, and
    §3.7 reserves ``CLEARED`` for the case where none of the preceding blocks
    applies, with ``blocking_error_id`` reading null.

    Design: Corner/endpoints/eligibility_check_computed_read_matches_the_pinned_calculation
    """
    scenario = _eligibility_scenario(api)
    _certify_scenario_wrestler(api, scenario)

    check = _run_check(api, scenario, CANON_TARGET_CLASS_LBS)

    assert check["outcome"] == OUTCOME_CLEARED
    assert check["blocking_error_id"] is None
    assert check["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS
    assert_instant_equals(check["checked_at"], ASSESSMENT_DAY_INSTANT, "checked_at")


def test_every_eligibility_check_verdict_is_logged_and_refreshes_the_wrestler(api):
    """Three verdicts from one endpoint, all logged, all discoverable.

    §3.7 logs a check row rather than rejecting on any business rule, so the
    blocked verdicts are retained alongside the cleared one; §2.3 returns the
    listing in ``created_at`` ascending order, oldest first.  Running the check
    also refreshes the wrestler's own cached lowest eligible class.

    Design: Corner/endpoints/eligibility_check_computed_read_matches_the_pinned_calculation
    """
    scenario = _eligibility_scenario(api)
    blocked_uncertified = _run_check(api, scenario, CANON_TARGET_CLASS_LBS)
    _certify_scenario_wrestler(api, scenario)
    blocked_below_floor = _run_check(api, scenario, _BELOW_FLOOR_CLASS_LBS)
    cleared = _run_check(api, scenario, CANON_TARGET_CLASS_LBS)

    rows = assert_row_count(
        api.list_eligibility_checks(
            STATE_OFFICE, {"wrestler_id": scenario.wrestler_id}
        ),
        3,
        "eligibility-check listing",
    )
    assert ids_of(rows) == [
        blocked_uncertified["id"],
        blocked_below_floor["id"],
        cleared["id"],
    ]
    assert rows[0]["outcome"] == OUTCOME_BLOCKED_NOT_CERTIFIED

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS


# ── The season compliance run ────────────────────────────────────────

# Week zero of the canonical compounding schedule starts 2026-11-02, so its
# half-open three-day evaluation window of §3.6 runs [2026-11-02, 2026-11-05).
_SWEEP_EVENT_DATE = "2026-11-04"
_SWEEP_WEIGH_IN_INSTANT = "2026-11-04T08:00:00Z"
_SWEEP_RUN_INSTANT = "2026-11-05T06:00:00Z"
_SWEEP_RECORDED_WEIGHT_LBS = 158.0
_WEEK_ZERO_ALLOWABLE_LBS = WEEKLY_STEP_SCHEDULE[0]
# As of 2026-11-04 the governing schedule value is week zero's 159.6 lb, which
# §3.7 step four turns into the wrestler's lowest eligible class.
_SWEEP_ENTRY_CLASS_LBS = expected_lowest_eligible_class(
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    _WEEK_ZERO_ALLOWABLE_LBS,
    0.0,
    CANON_MIN_WEIGHT_CLASS_LBS,
)


def _compliance_scenario(api):
    """Two wrestlers on identical certified plans, only one of whom weighed in.

    Both plans carry the same week-zero milestone, so the only difference the
    sweep can see is that wrestler A has a qualifying weigh-in inside week zero's
    window and wrestler B has none at all.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler_a, _assessment_a, plan_a = _certified_roster_member(
        api, scenario, assessor["id"], "Alex Mercer", "2026-11-01T09:00:00Z"
    )
    wrestler_b, _assessment_b, plan_b = _certified_roster_member(
        api, scenario, assessor["id"], "Blake Nunez", "2026-11-01T09:30:00Z"
    )
    event = fixtures.create_event(
        api, scenario.season_id, "Early Duals", _SWEEP_EVENT_DATE, EVENT_TYPE_DUAL
    )
    entry_a = fixtures.create_entry(
        api,
        event["id"],
        wrestler_a,
        scenario.team_id,
        _SWEEP_ENTRY_CLASS_LBS,
        season_win_count=1,
    )
    fixtures.open_weigh_ins(api, event["id"])
    fixtures.move_clock(api, _SWEEP_WEIGH_IN_INSTANT)
    weigh_in = fixtures.record_weigh_in(
        api, event["id"], entry_a["id"], 0, _SWEEP_RECORDED_WEIGHT_LBS
    )
    fixtures.move_clock(api, _SWEEP_RUN_INSTANT)
    scenario.update(
        wrestler_a=wrestler_a,
        wrestler_b=wrestler_b,
        plan_a=plan_a,
        plan_b=plan_b,
        weigh_in=weigh_in,
    )
    return scenario


def test_one_compliance_run_judges_each_certified_plan_independently(api):
    """The sweep is per plan: one plan's missed milestone does not undo another's.

    §3.6 walks every plan of the season in ``CERTIFIED``, judging each plan's due
    milestones on its own evidence.  Wrestler A's week-zero milestone finds a
    qualifying weigh-in inside its half-open three-day window and becomes ``MET``
    recording that weight; wrestler B's identical milestone finds no candidate at
    all and becomes ``MISSED`` with the evaluated weight left null.  Neither
    verdict rolls the other back, and with one missed milestone against a breach
    limit of two neither plan breaches, so no flag is raised.

    Design: Corner/endpoints/compliance_run_bulk_semantics_are_per_plan_skip_not_rollback
    """
    scenario = _compliance_scenario(api)
    assert scenario.weigh_in["result"] == WEIGH_IN_PASS
    assert_instant_equals(
        scenario.weigh_in["recorded_at"], _SWEEP_WEIGH_IN_INSTANT, "recorded_at"
    )

    season = validate_success(api.run_compliance(scenario.season_id, STATE_OFFICE))

    milestones_a = _milestone_rows(api, scenario.plan_a)
    milestones_b = _milestone_rows(api, scenario.plan_b)
    assert milestones_a[0]["status"] == MILESTONE_MET
    assert_weight_equals(
        milestones_a[0]["evaluated_recorded_weight_lbs"],
        _SWEEP_RECORDED_WEIGHT_LBS,
        "met milestone evaluated_recorded_weight_lbs",
    )
    assert milestones_b[0]["status"] == MILESTONE_MISSED
    assert milestones_b[0]["evaluated_recorded_weight_lbs"] is None

    plan_a = fixtures.read_plan(api, scenario.plan_a)
    plan_b = fixtures.read_plan(api, scenario.plan_b)
    assert plan_a["status"] == PLAN_CERTIFIED
    assert plan_a["missed_milestone_count"] == 0
    assert plan_b["status"] == PLAN_CERTIFIED
    assert plan_b["missed_milestone_count"] == 1
    assert plan_b["missed_milestone_count"] < DEFAULT_PLAN_BREACH_LIMIT
    assert plan_b["breach_count"] == 0

    assert_row_count(
        api.list_health_flags(STATE_OFFICE, {"wrestler_id": scenario.wrestler_b}),
        0,
        "health-flag listing for the plan that missed one milestone",
    )
    # §3.6 returns the season with refreshed counters; both plans remain
    # certified, so neither certification was rolled back by the missed row.
    assert season["certified_wrestler_count"] == 2


def test_compliance_run_touches_only_milestones_already_due(api):
    """A milestone whose effective date is still in the future is skipped.

    §3.6 considers only milestones whose ``status`` is ``SCHEDULED`` and whose
    ``effective_date`` is on or before the current logical clock date.  Week one
    falls on 2026-11-09, a clear four days beyond the 2026-11-05 clock, so it
    stays ``SCHEDULED`` on both plans even though the same call judged week zero
    on both of them.

    Design: Corner/endpoints/compliance_run_bulk_semantics_are_per_plan_skip_not_rollback
    """
    scenario = _compliance_scenario(api)

    validate_success(api.run_compliance(scenario.season_id, STATE_OFFICE))

    for plan_id, label in (
        (scenario.plan_a, "the plan that met week zero"),
        (scenario.plan_b, "the plan that missed week zero"),
    ):
        milestones = _milestone_rows(api, plan_id)
        assert milestones[1]["week_index"] == 1
        assert milestones[1]["status"] == MILESTONE_SCHEDULED, label
        assert milestones[1]["evaluated_recorded_weight_lbs"] is None, label


# ── The locked bracket and the conserved seed sum ────────────────────

_BRACKET_EVENT_DATE = "2026-12-12"
_BRACKET_WEIGH_IN_INSTANT = "2026-12-12T07:00:00Z"
# Three ladder members at or above the wrestlers' lowest eligible class of 150.
_LOWER_CLASS_LBS = CANON_TARGET_CLASS_LBS
_MIDDLE_CLASS_LBS = 157
_UPPER_CLASS_LBS = 165


def _seeded_bracket(api):
    """Three certified wrestlers weighed in and seeded across two weight classes.

    Class 150 holds two entries and class 157 holds one, so §2.9 makes the
    event's ``seed_integrity_sum`` the sum of 1 plus 2 over the first class and 1
    over the second.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler_a, _assessment_a, _plan_a = _certified_roster_member(
        api, scenario, assessor["id"], "Alex Mercer", "2026-11-01T09:00:00Z"
    )
    wrestler_b, _assessment_b, _plan_b = _certified_roster_member(
        api, scenario, assessor["id"], "Blake Nunez", "2026-11-01T09:30:00Z"
    )
    wrestler_c, _assessment_c, _plan_c = _certified_roster_member(
        api, scenario, assessor["id"], "Cory Pike", "2026-11-01T10:00:00Z"
    )
    event = fixtures.create_event(
        api,
        scenario.season_id,
        "State Qualifier",
        _BRACKET_EVENT_DATE,
        EVENT_TYPE_TOURNAMENT,
    )
    entry_a = fixtures.create_entry(
        api, event["id"], wrestler_a, scenario.team_id, _LOWER_CLASS_LBS,
        season_win_count=5,
    )
    entry_b = fixtures.create_entry(
        api, event["id"], wrestler_b, scenario.team_id, _LOWER_CLASS_LBS,
        season_win_count=3,
    )
    entry_c = fixtures.create_entry(
        api, event["id"], wrestler_c, scenario.team_id, _MIDDLE_CLASS_LBS,
        season_win_count=4,
    )
    fixtures.open_weigh_ins(api, event["id"])
    fixtures.move_clock(api, _BRACKET_WEIGH_IN_INSTANT)
    fixtures.record_weigh_in(api, event["id"], entry_a["id"], 0, 150.0)
    fixtures.record_weigh_in(api, event["id"], entry_b["id"], 0, 149.0)
    fixtures.record_weigh_in(api, event["id"], entry_c["id"], 0, 155.0)
    fixtures.close_weigh_ins(api, event["id"])
    seeded_event = fixtures.seed_event(api, event["id"])
    scenario.update(
        event_id=event["id"],
        seeded_event=seeded_event,
        entry_a_id=entry_a["id"],
        entry_b_id=entry_b["id"],
        entry_c_id=entry_c["id"],
    )
    return scenario


def _assert_initial_bracket(api, scenario) -> Dict[str, Any]:
    """The first seeding run locks the bracket and ranks class 150 by wins."""
    assert scenario.seeded_event["bracket_locked"] is True
    assert scenario.seeded_event["seeded_entry_count"] == 3
    assert_seed_integrity_sum(scenario.seeded_event, [2, 1], "seeded event")
    entry_a = fixtures.read_entry(api, scenario.entry_a_id)
    entry_b = fixtures.read_entry(api, scenario.entry_b_id)
    assert entry_a["seed_number"] == 1
    assert entry_b["seed_number"] == 2
    assert entry_b["status"] == ENTRY_SEEDED
    assert entry_b["weight_class_change_count"] == 0
    return entry_b


def test_weight_class_change_reseeds_the_vacated_and_destination_groups(api):
    """Moving a seeded entry reseeds both class groups inside the same request.

    §3.8 exempts the state-office weight-class change from the bracket lock and
    requires it to reseed the vacated and the destination class so that every
    group again holds a contiguous run of seed numbers beginning at 1.  Moving the
    second seed of class 150 to an empty class 165 therefore makes it the sole
    occupant at seed 1 and recomputes the vacated group, leaving the remaining
    entry at seed 1 by recomputation.  §2.10 forbids deferring any of that, so the
    event's reseed flag stays false and its counters are already current.

    Design: Corner/endpoints/weight_class_change_reseeds_both_groups_and_conserves_integrity_sum
    """
    scenario = _seeded_bracket(api)
    entry_b = _assert_initial_bracket(api, scenario)

    moved = fixtures.change_weight_class(
        api,
        scenario.entry_b_id,
        _UPPER_CLASS_LBS,
        expected_entry_version=entry_b["version"],
    )

    assert_mutable_row(moved, "moved entry")
    assert moved["weight_class_lbs"] == _UPPER_CLASS_LBS
    assert moved["seed_number"] == 1
    assert moved["weight_class_change_count"] == 1
    assert moved["status"] == ENTRY_SEEDED
    assert moved["version"] == entry_b["version"] + 1

    event = fixtures.read_event(api, scenario.event_id)
    # Three classes now hold one entry each: 1 + 1 + 1.
    assert_seed_integrity_sum(event, [1, 1, 1], "event after the move")
    assert event["seeded_entry_count"] == 3
    assert event["reseed_required"] is False
    assert fixtures.read_entry(api, scenario.entry_a_id)["seed_number"] == 1
    assert fixtures.read_entry(api, scenario.entry_c_id)["seed_number"] == 1


def test_reverse_weight_class_change_restores_the_seed_integrity_sum(api):
    """The reverse move restores the conserved sum to exactly its prior value.

    §2.9 declares ``Event.seed_integrity_sum`` conserved: it is recomputed from
    the resulting groups rather than adjusted blindly, so a class change followed
    by the reverse class change restores it exactly.  The per-entry change counter
    is not a conserved quantity and does not decrement on a reversal.

    Design: Corner/endpoints/weight_class_change_reseeds_both_groups_and_conserves_integrity_sum
    """
    scenario = _seeded_bracket(api)
    entry_b = _assert_initial_bracket(api, scenario)
    sum_before = scenario.seeded_event["seed_integrity_sum"]

    moved = fixtures.change_weight_class(
        api,
        scenario.entry_b_id,
        _UPPER_CLASS_LBS,
        expected_entry_version=entry_b["version"],
    )
    returned = fixtures.change_weight_class(
        api,
        scenario.entry_b_id,
        _LOWER_CLASS_LBS,
        expected_entry_version=moved["version"],
    )

    assert returned["weight_class_lbs"] == _LOWER_CLASS_LBS
    assert returned["seed_number"] == 2
    assert returned["weight_class_change_count"] == 2
    assert returned["status"] == ENTRY_SEEDED
    assert fixtures.read_entry(api, scenario.entry_a_id)["seed_number"] == 1

    event = fixtures.read_event(api, scenario.event_id)
    assert_seed_integrity_sum(event, [2, 1], "event after the reverse move")
    assert event["seed_integrity_sum"] == sum_before
    assert event["seeded_entry_count"] == 3


def test_reseeding_is_refused_once_the_inline_reseed_has_cleared_the_flag(api):
    """A reseed out of ``SEEDED`` is conditional on the reseed flag being true.

    §3.8 allows a reseed only when ``reseed_required`` is true, and any seeding
    request against an event that is neither ``WEIGH_IN_CLOSED`` nor awaiting a
    reseed is refused.  Because the class change reseeded inline rather than
    deferring, the flag was never raised and the explicit reseed has nothing to
    do.

    Design: Corner/endpoints/weight_class_change_reseeds_both_groups_and_conserves_integrity_sum
    """
    scenario = _seeded_bracket(api)
    entry_b = _assert_initial_bracket(api, scenario)
    fixtures.change_weight_class(
        api,
        scenario.entry_b_id,
        _UPPER_CLASS_LBS,
        expected_entry_version=entry_b["version"],
    )
    assert fixtures.read_event(api, scenario.event_id)["reseed_required"] is False

    validate_error(
        api.seed_event(scenario.event_id, STATE_OFFICE),
        api_errors.ERR_EVENT_INVALID_STATE,
    )


# ── Opening a program audit: a three-way link ────────────────────────

_SAMPLE_WINDOW_START = "2026-11-01"
# The auditor's remeasured figures against the recorded 14.0 percent.
_REMEASURED_X_PCT = 14.5
_REMEASURED_Y_PCT = 13.3
_REMEASURED_Z_PCT = 14.9
_SAMPLE_DEVIATIONS = [
    expected_deviation(_REMEASURED_X_PCT, CANON_BODY_FAT_PCT),
    expected_deviation(_REMEASURED_Y_PCT, CANON_BODY_FAT_PCT),
    expected_deviation(_REMEASURED_Z_PCT, CANON_BODY_FAT_PCT),
]
_SAMPLE_MEAN_SCORE = expected_sample_mean_score(_SAMPLE_DEVIATIONS)


def _audit_scenario(api):
    """One certified assessor with three validated assessments to sample from.

    Three assessments on 2026-11-01 is exactly the default daily capacity of
    §2.2, so the roster is built without tripping that guard.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler_x = fixtures.create_wrestler(api, scenario.team_id, "Xan Porter")
    wrestler_y = fixtures.create_wrestler(api, scenario.team_id, "Yuri Bloom")
    wrestler_z = fixtures.create_wrestler(
        api, scenario.team_id, "Zoe Kettle", sex=SEX_FEMALE, grade=12
    )
    assessment_x = fixtures.create_validated_assessment(
        api, wrestler_x["id"], assessor["id"], assessed_at="2026-11-01T09:00:00Z"
    )
    assessment_y = fixtures.create_validated_assessment(
        api, wrestler_y["id"], assessor["id"], assessed_at="2026-11-01T09:30:00Z"
    )
    assessment_z = fixtures.create_validated_assessment(
        api,
        wrestler_z["id"],
        assessor["id"],
        method=METHOD_BIA,
        assessed_at="2026-11-01T10:00:00Z",
        measured_weight_lbs=130.0,
    )
    scenario.update(
        assessor_id=assessor["id"],
        assessment_x_id=assessment_x["id"],
        assessment_y_id=assessment_y["id"],
        assessment_z_id=assessment_z["id"],
    )
    return scenario


def _full_sample_set(scenario) -> List[Dict[str, Any]]:
    """The three remeasured samples, in the order they are scored."""
    return factories.audit_samples(
        [
            (scenario.assessment_x_id, _REMEASURED_X_PCT),
            (scenario.assessment_y_id, _REMEASURED_Y_PCT),
            (scenario.assessment_z_id, _REMEASURED_Z_PCT),
        ]
    )


def _open_full_audit(api, scenario) -> Dict[str, Any]:
    """Open the three-sample audit and require the documented 201."""
    payload = factories.audit_payload(
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_SAMPLE_MEAN,
        _SAMPLE_WINDOW_START,
        assessor_id=scenario.assessor_id,
        samples=_full_sample_set(scenario),
    )
    return validate_success(api.create_audit(scenario.season_id, payload, STATE_OFFICE), 201)


def test_audit_creation_resolves_the_assessor_arm_of_the_link(api):
    """An audit naming an unknown assessor is refused before anything is written.

    §3.9 makes ``assessor_id`` a body foreign key of audit opening, and §2.8
    resolves body foreign keys after the path identifier and before any domain
    rule, so an unresolvable assessor is the not-found code for that entity.  The
    refusal must leave no partially linked audit behind.

    Design: Corner/endpoints/audit_creation_links_season_assessor_and_sampled_assessments
    """
    scenario = _audit_scenario(api)
    payload = factories.audit_payload(
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_SAMPLE_MEAN,
        _SAMPLE_WINDOW_START,
        assessor_id=_UNKNOWN_ASSESSOR_ID,
        samples=factories.audit_samples(
            [(scenario.assessment_x_id, _REMEASURED_X_PCT)]
        ),
    )

    validate_error(
        api.create_audit(scenario.season_id, payload, STATE_OFFICE),
        api_errors.ERR_ASSESSOR_NOT_FOUND,
    )

    assert_row_count(
        api.list_audits(STATE_OFFICE, {"season_id": scenario.season_id}),
        0,
        "audits after the refused create",
    )


def test_audit_creation_resolves_every_sampled_assessment(api):
    """One unresolvable sample refuses the whole create.

    §3.9 pairs each ``samples[]`` element with an ``assessment_id``, and §2.8
    resolves every body foreign key, so a sample pointing at nothing is the
    assessment not-found code rather than a silently dropped element.  §2.10
    forbids a half-applied write, so nothing is stored.

    Design: Corner/endpoints/audit_creation_links_season_assessor_and_sampled_assessments
    """
    scenario = _audit_scenario(api)
    payload = factories.audit_payload(
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_SAMPLE_MEAN,
        _SAMPLE_WINDOW_START,
        assessor_id=scenario.assessor_id,
        samples=factories.audit_samples(
            [(_UNKNOWN_ASSESSMENT_ID, _REMEASURED_X_PCT)]
        ),
    )

    validate_error(
        api.create_audit(scenario.season_id, payload, STATE_OFFICE),
        api_errors.ERR_ASSESSMENT_NOT_FOUND,
    )

    assert_row_count(
        api.list_audits(STATE_OFFICE, {"assessor_id": scenario.assessor_id}),
        0,
        "audits after the refused create",
    )


def test_a_created_audit_is_reachable_from_both_reverse_lookup_filters(api):
    """When all three arms resolve the audit is created unscored and discoverable.

    §3.9 puts a new audit in ``OPEN`` with ``sample_count`` equal to the length of
    the samples array and ``discrepancy_score``, ``outcome`` and
    ``voided_assessment_count`` at their unset values, because scoring happens at
    finalize.  The same section makes the listing narrowable by ``season_id``,
    ``assessor_id`` and ``audit_type``, so the row is reachable from either side
    of the link it recorded.

    Design: Corner/endpoints/audit_creation_links_season_assessor_and_sampled_assessments
    """
    scenario = _audit_scenario(api)

    audit = _open_full_audit(api, scenario)

    assert_mutable_row(audit, "audit")
    assert audit["season_id"] == scenario.season_id
    assert audit["assessor_id"] == scenario.assessor_id
    assert audit["audit_type"] == AUDIT_TYPE_ASSESSOR_SAMPLE
    assert audit["scoring_variant"] == SCORING_SAMPLE_MEAN
    assert audit["sample_window_start"] == _SAMPLE_WINDOW_START
    assert audit["sample_count"] == 3
    assert audit["status"] == AUDIT_OPEN
    assert audit["discrepancy_score"] is None
    assert audit["outcome"] is None
    assert audit["voided_assessment_count"] == 0

    by_assessor = assert_row_count(
        api.list_audits(STATE_OFFICE, {"assessor_id": scenario.assessor_id}),
        1,
        "audits by assessor",
    )
    by_season = assert_row_count(
        api.list_audits(
            STATE_OFFICE,
            {"season_id": scenario.season_id, "audit_type": AUDIT_TYPE_ASSESSOR_SAMPLE},
        ),
        1,
        "audits by season and type",
    )
    assert ids_of(by_assessor) == [audit["id"]]
    assert ids_of(by_season) == [audit["id"]]


def test_finalizing_a_sample_mean_audit_scores_the_mean_and_runs_no_cascade(api):
    """The mean of the three deviations passes, so nothing downstream is touched.

    §3.9 makes each sample's deviation the absolute difference between the
    auditor's remeasured percentage and the percentage recorded on the assessment,
    rounded half up to two places, and ``SAMPLE_MEAN`` divides their sum by the
    sample count with the same rounding.  0.50, 0.70 and 0.90 average to 0.70,
    which is below the shipped fail threshold of 2.0, so the outcome is a pass —
    and §3.9 is explicit that a pass triggers no cascade whatsoever: the assessor
    keeps the credential and every assessment stands.

    Design: Corner/endpoints/audit_creation_links_season_assessor_and_sampled_assessments
    """
    scenario = _audit_scenario(api)
    audit = _open_full_audit(api, scenario)

    finalized = fixtures.finalize_audit(api, audit["id"])

    assert finalized["status"] == AUDIT_FINALIZED
    assert finalized["discrepancy_score"] == pytest.approx(_SAMPLE_MEAN_SCORE, abs=0.01)
    assert _SAMPLE_MEAN_SCORE < DEFAULT_AUDIT_FAIL_THRESHOLD_PCT
    assert finalized["outcome"] == AUDIT_PASS
    assert finalized["voided_assessment_count"] == 0

    assessor = fixtures.read_assessor(api, scenario.assessor_id)
    assert assessor["status"] == ASSESSOR_CERTIFIED
    assert assessor["last_audit_outcome"] == AUDIT_PASS
    assert assessor["voided_assessment_count"] == 0
    for label, assessment_id in (
        ("X", scenario.assessment_x_id),
        ("Y", scenario.assessment_y_id),
        ("Z", scenario.assessment_z_id),
    ):
        assessment = fixtures.read_assessment(api, assessment_id)
        assert assessment["status"] == ASSESSMENT_VALIDATED, label
        assert assessment["void_reason"] is None, label


# ── Season and growth allowance: create, read, list ──────────────────

# Every optional regulatory constant moved off its declared default, so a read
# that substituted a default anywhere would be visible.
_CUSTOM_CONSTANTS: Dict[str, Any] = {
    "weight_classes": [106, 120, 132, 145, 160, 180, 220, 285],
    "min_body_fat_pct_male": 8.0,
    "min_body_fat_pct_female": 13.0,
    "hydration_max_specific_gravity": 1.020,
    "max_weekly_descent_pct": 1.0,
    "assessor_min_training_hours": 12,
    "audit_fail_threshold_pct": 1.5,
    "audit_min_sample_count": 4,
    "max_consecutive_day_allowance_lbs": 3.0,
    "appeal_filing_window_days": 7,
    "max_appeal_retest_rounds": 1,
    "plan_breach_limit": 3,
    "assessor_daily_assessment_capacity": 5,
}
_SECOND_TEAM_NAME = "Southgate High"
_EARLY_ALLOWANCE_DATE = "2026-12-01"
_EARLY_ALLOWANCE_LBS = 1.0
_LATE_ALLOWANCE_DATE = "2026-12-12"
_LATE_ALLOWANCE_LBS = 3.0


def _custom_season(api) -> Dict[str, Any]:
    """Create the fully overridden season and check its birth state.

    §3.1 puts a new season in ``SETUP`` with both derived counters at zero, and
    §2.11 fixes the created-resource status code at 201.
    """
    payload = factories.season_payload(
        name="2026-27 Custom Constants Season", **_CUSTOM_CONSTANTS
    )
    created = validate_success(api.create_season(payload, STATE_OFFICE), 201)
    assert created["status"] == SEASON_SETUP
    assert created["team_count"] == 0
    assert created["certified_wrestler_count"] == 0
    return created


def test_season_create_and_read_round_trip_echoes_every_overridden_constant(api):
    """The read hands back every supplied constant with no default substituted.

    §2.5 gives each regulatory constant a default that applies only when the
    season is created without it, so a season created with all thirteen supplied
    must read them all back unchanged.  §3.1 also makes ``team_count`` a derived
    counter maintained by team registration, and §2.10 requires derived counters to
    be current in the same request, so the read reflects both registrations
    immediately.  Registration itself needs the season open, which §3.1 requires.

    Design: Corner/endpoints/season_and_growth_allowance_create_read_list_round_trip
    """
    created = _custom_season(api)
    season_id = created["id"]
    opened = fixtures.set_season_status(api, season_id, SEASON_OPEN)
    assert opened["status"] == SEASON_OPEN
    first_team = fixtures.create_team(api, season_id, DEFAULT_TEAM_NAME)
    fixtures.create_team(api, season_id, _SECOND_TEAM_NAME)

    # Any of the five roles may read a season; a coach reads it here.
    season = validate_success(
        api.get_season(season_id, coach_headers(first_team["id"]))
    )

    assert_mutable_row(season, "season")
    assert season["id"] == season_id
    assert season["weight_classes"] == _CUSTOM_CONSTANTS["weight_classes"]
    assert season["min_body_fat_pct_male"] == pytest.approx(8.0, abs=0.01)
    assert season["min_body_fat_pct_female"] == pytest.approx(13.0, abs=0.01)
    assert season["hydration_max_specific_gravity"] == pytest.approx(1.020, abs=0.0001)
    assert season["max_weekly_descent_pct"] == pytest.approx(1.0, abs=0.01)
    assert season["assessor_min_training_hours"] == 12
    assert season["audit_fail_threshold_pct"] == pytest.approx(1.5, abs=0.01)
    assert season["audit_min_sample_count"] == 4
    assert season["max_consecutive_day_allowance_lbs"] == pytest.approx(3.0, abs=0.01)
    assert season["appeal_filing_window_days"] == 7
    assert season["max_appeal_retest_rounds"] == 1
    assert season["assessor_daily_assessment_capacity"] == 5
    assert season["plan_breach_limit"] == 3
    assert season["team_count"] == 2
    assert season["certified_wrestler_count"] == 0


def test_growth_allowance_listing_is_ordered_by_effective_date_not_insertion(api):
    """The child listing is ordered by effective date even when inserted backwards.

    §2.3 sorts list results by ``created_at`` ascending *unless* the endpoint
    states otherwise, and §3.1 states otherwise for this one: the growth-allowance
    listing is returned in ``effective_date`` ascending order.  Publishing the
    later date first therefore has to come back second.  §3.1 also defaults the
    optional ``note`` to null, and §2.4 makes an allowance an append-only row
    carrying only an identity and a creation stamp.

    Design: Corner/endpoints/season_and_growth_allowance_create_read_list_round_trip
    """
    created = _custom_season(api)
    season_id = created["id"]
    fixtures.set_season_status(api, season_id, SEASON_OPEN)

    late = fixtures.publish_growth_allowance(
        api,
        season_id,
        _LATE_ALLOWANCE_DATE,
        _LATE_ALLOWANCE_LBS,
        note="second growth date, published first",
    )
    early = fixtures.publish_growth_allowance(
        api, season_id, _EARLY_ALLOWANCE_DATE, _EARLY_ALLOWANCE_LBS
    )

    assert_append_only_row(early, "growth allowance")
    assert early["season_id"] == season_id
    assert early["note"] is None
    assert late["note"] == "second growth date, published first"

    rows = assert_row_count(
        api.list_growth_allowances(season_id, STATE_OFFICE), 2, "growth allowances"
    )
    assert ids_of(rows) == [early["id"], late["id"]]
    assert rows[0]["effective_date"] == _EARLY_ALLOWANCE_DATE
    assert_weight_equals(
        rows[0]["allowance_lbs"], _EARLY_ALLOWANCE_LBS, "first allowance"
    )
    assert rows[1]["effective_date"] == _LATE_ALLOWANCE_DATE
    assert_weight_equals(
        rows[1]["allowance_lbs"], _LATE_ALLOWANCE_LBS, "second allowance"
    )


def test_the_team_listing_filter_narrows_rather_than_being_ignored(api):
    """The team listing carries both rows and its posture filter excludes both.

    §2.3 leaves this listing on the default ``created_at`` ascending order, and
    §3.1 allows it to be narrowed by ``compliance_status`` while starting every new
    team at ``CLEAR``.  A filter on ``PROBATION`` therefore has to come back empty
    with a total count of zero rather than returning the unfiltered pair.

    Design: Corner/endpoints/season_and_growth_allowance_create_read_list_round_trip
    """
    created = _custom_season(api)
    season_id = created["id"]
    fixtures.set_season_status(api, season_id, SEASON_OPEN)
    first_team = fixtures.create_team(api, season_id, DEFAULT_TEAM_NAME)
    second_team = fixtures.create_team(api, season_id, _SECOND_TEAM_NAME)

    rows = assert_row_count(
        api.list_season_teams(season_id, STATE_OFFICE), 2, "season teams"
    )
    assert ids_of(rows) == [first_team["id"], second_team["id"]]
    assert rows[0]["school_name"] == DEFAULT_TEAM_NAME
    assert rows[1]["school_name"] == _SECOND_TEAM_NAME

    narrowed = assert_row_count(
        api.list_season_teams(
            season_id, STATE_OFFICE, {"compliance_status": TEAM_PROBATION}
        ),
        0,
        "season teams on probation",
    )
    assert narrowed == []


# ── Administrative assessor suspension ───────────────────────────────

_SUSPENSION_REASON = "Program audit irregularities under investigation"
_DRAFT_ASSESSED_AT = "2026-11-01T09:30:00Z"
_LATER_ASSESSED_AT = "2026-11-01T11:00:00Z"


def _suspension_scenario(api):
    """A certified assessor holding one validated and one still-draft assessment."""
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    assert assessor["status"] == ASSESSOR_CERTIFIED
    wrestler = fixtures.create_wrestler(api, scenario.team_id, "Alex Mercer")
    validated = fixtures.create_validated_assessment(
        api, wrestler["id"], assessor["id"], assessed_at="2026-11-01T09:00:00Z"
    )
    assert validated["status"] == ASSESSMENT_VALIDATED
    draft = fixtures.create_assessment(
        api,
        wrestler["id"],
        assessor["id"],
        method=METHOD_BIA,
        assessed_at=_DRAFT_ASSESSED_AT,
        measured_weight_lbs=158.0,
        body_fat_pct=13.8,
        urine_specific_gravity=1.021,
    )
    assert draft["status"] == ASSESSMENT_DRAFT
    scenario.update(
        assessor=assessor,
        assessor_id=assessor["id"],
        wrestler_id=wrestler["id"],
        validated_id=validated["id"],
        draft_id=draft["id"],
    )
    return scenario


def test_suspending_an_assessor_voids_their_drafts_and_nothing_else(api):
    """Suspension voids draft work only and leaves the certified figures standing.

    §3.2 pins the side-effect set of an administrative suspension exactly: the
    assessor moves ``CERTIFIED → SUSPENDED``, ``suspension_reason`` records the
    supplied text, every ``DRAFT`` assessment of that assessor becomes ``VOIDED``
    with ``void_reason`` ``ASSESSOR_SUSPENDED``, and the version increments.
    Validated work is not in that set — unlike the audit-failure cascade of §3.9,
    which also voids validated assessments — so §3.3's certified wrestler keeps a
    provisional certification pointing at the surviving assessment.  §3.2 also
    defines the dossier counters, which §2.10 brings current in the same request.

    Design: Corner/endpoints/assessor_suspension_action_enforces_preconditions_and_voids_only_drafts
    """
    scenario = _suspension_scenario(api)
    version_before = fixtures.read_assessor(api, scenario.assessor_id)["version"]

    suspended = fixtures.suspend_assessor(
        api, scenario.assessor_id, reason=_SUSPENSION_REASON
    )

    assert_mutable_row(suspended, "assessor")
    assert suspended["status"] == ASSESSOR_SUSPENDED
    assert suspended["suspension_reason"] == _SUSPENSION_REASON
    assert suspended["version"] == version_before + 1
    # The dossier counters are history: one validated assessment still stands and
    # the voided draft is now counted as voided.
    assert suspended["validated_assessment_count"] == 1
    assert suspended["voided_assessment_count"] == 1

    draft = fixtures.read_assessment(api, scenario.draft_id)
    assert draft["status"] == ASSESSMENT_VOIDED
    assert draft["void_reason"] == VOID_REASON_ASSESSOR_SUSPENDED

    validated = fixtures.read_assessment(api, scenario.validated_id)
    assert validated["status"] == ASSESSMENT_VALIDATED
    assert validated["void_reason"] is None

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert wrestler["source_assessment_id"] == scenario.validated_id
    assert wrestler["min_weight_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS
    assert wrestler["certification_hold_reason"] is None


def test_a_suspended_assessor_is_closed_out_and_cannot_be_suspended_twice(api):
    """The action is not idempotent and immediately withdraws the credential.

    §3.2 requires the referenced assessor's status to be exactly ``CERTIFIED`` for
    every operation that needs a credential in force, opening an assessment among
    them, so the suspended assessor is refused with the not-certified code.  The
    same section allows the suspension itself only out of ``CERTIFIED``: a second
    attempt against an already-suspended assessor is the invalid-state code, not a
    silent success.

    Design: Corner/endpoints/assessor_suspension_action_enforces_preconditions_and_voids_only_drafts
    """
    scenario = _suspension_scenario(api)
    fixtures.suspend_assessor(api, scenario.assessor_id, reason=_SUSPENSION_REASON)

    payload = factories.assessment_payload(
        assessor_id=scenario.assessor_id,
        method=METHOD_SKINFOLD,
        assessed_at=_LATER_ASSESSED_AT,
        measured_weight_lbs=157.0,
        body_fat_pct=13.5,
    )
    validate_error(
        api.create_assessment(
            scenario.wrestler_id, payload, assessor_headers(scenario.assessor_id)
        ),
        api_errors.ERR_ASSESSOR_NOT_CERTIFIED,
    )

    validate_error(
        api.suspend_assessor(
            scenario.assessor_id,
            factories.suspension_payload("Second attempt"),
            STATE_OFFICE,
        ),
        api_errors.ERR_ASSESSOR_INVALID_STATE,
    )

    still_suspended = fixtures.read_assessor(api, scenario.assessor_id)
    assert still_suspended["status"] == ASSESSOR_SUSPENDED
    assert still_suspended["suspension_reason"] == _SUSPENSION_REASON
