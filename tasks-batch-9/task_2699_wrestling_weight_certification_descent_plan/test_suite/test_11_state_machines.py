"""
State-machine behaviour of the Wrestling Weight Certification API.

The families exercised here are the declared transition walks (the event
lifecycle in §3.8 and the season lifecycle in §3.1), the refusal of any
transition not declared out of a row's current status, the birth state every
creating endpoint reports, the threshold-driven assessor auto-transition of
§3.2, terminal-state lockdown, and the disqualification cascade of §3.9 that
releases a seed and forces a rebuild of the bracket.

Every precondition is built through the declared endpoints: the server starts
from an empty database with the logical clock at its start instant, so a season
has to be opened, a team registered, an assessor trained up to the credential
threshold, a wrestler assessed, a descent plan certified, an event scheduled and
its bracket seeded before any of the behaviour below is observable.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_all_null,
    assert_instant_equals,
    assert_seed_integrity_sum,
    assert_weight_equals,
)
from test_helpers.constants import (
    ASSESSMENT_DAY_INSTANT,
    ASSESSMENT_DRAFT,
    ASSESSMENT_HYDRATION_FAILED,
    ASSESSMENT_VALIDATED,
    ASSESSMENT_VOIDED,
    ASSESSOR_CERTIFIED,
    ASSESSOR_PROVISIONAL,
    ASSESSOR_SUSPENDED,
    AUDIT_FINALIZED,
    AUDIT_INCONCLUSIVE,
    AUDIT_OPEN,
    AUDIT_TYPE_ASSESSOR_SAMPLE,
    AUDIT_TYPE_TEAM_COMPLIANCE,
    CANCEL_REASON_DISQUALIFIED,
    CANON_TARGET_CLASS_LBS,
    DEFAULT_ASSESSOR_MIN_TRAINING_HOURS,
    DEFAULT_AUDIT_MIN_SAMPLE_COUNT,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ENTRY_DISQUALIFIED,
    ENTRY_ENTERED,
    ENTRY_SEEDED,
    ENTRY_WEIGHED_IN,
    EVENT_CANCELLED,
    EVENT_COMPLETED,
    EVENT_SCHEDULED,
    EVENT_SEEDED,
    EVENT_TYPE_DUAL,
    EVENT_TYPE_TOURNAMENT,
    EVENT_WEIGH_IN_CLOSED,
    EVENT_WEIGH_IN_OPEN,
    FLAG_ESCALATED,
    METHOD_HYDROSTATIC,
    MILESTONE_SCHEDULED,
    PLAN_CANCELLED,
    PLAN_CERTIFIED,
    PLAN_DRAFT,
    SCORING_SAMPLE_MEAN,
    SCRATCH_REASON_UNHEALTHY,
    SEASON_CLOSED,
    SEASON_OPEN,
    SEASON_SETUP,
    SEX_MALE,
    TEAM_CLEAR,
    VOID_REASON_ASSESSOR_SUSPENDED,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEIGH_IN_PASS,
    WRESTLER_CERTIFIED,
    WRESTLER_DISQUALIFIED,
    WRESTLER_UNCERTIFIED,
)
from test_helpers.test_users import STATE_OFFICE, WEIGH_IN_OFFICIAL, assessor_headers

# The competition day of the tournament the composite chain schedules: a
# weigh-in's recorded_at has to fall on the event date advanced by its day index,
# so the logical clock is moved onto that date before any scale reading.
_EVENT_DAY_INSTANT = "2026-12-12T08:00:00Z"

# A scale reading that clears the 150 pound class outright and still sits above
# the 147.6 pound certified minimum, so the verdict is PASS and below_minimum
# reads false.
_PASSING_WEIGHT_LBS = 149.0
_SECOND_PASSING_WEIGHT_LBS = 149.5


# ── Local builders ───────────────────────────────────────────────────


def _seeded_event_with_one_entry(api) -> fixtures.Scenario:
    """A tournament driven all the way to a seeded bracket holding one entry."""
    scenario = fixtures.entered_wrestler(api)
    fixtures.move_clock(api, _EVENT_DAY_INSTANT)
    fixtures.open_weigh_ins(api, scenario.event_id)
    fixtures.record_weigh_in(
        api, scenario.event_id, scenario.entry_id, 0, _PASSING_WEIGHT_LBS
    )
    fixtures.close_weigh_ins(api, scenario.event_id)
    scenario.event = fixtures.seed_event(api, scenario.event_id)
    return scenario


def _seeded_bracket_with_two_wrestlers(api) -> fixtures.Scenario:
    """Two certified team-mates seeded in the same class, one carrying a flag.

    Both wrestlers are measured identically, so both certify into class 150 and
    both weigh in comfortably.  Wrestler A additionally has a hydration-failed
    third assessment, which raises the health flag §3.3 pins at severity 1; that
    flag is escalated after the bracket is seeded, because §3.7 refuses a
    competition entry for a wrestler carrying an escalated flag.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler_a = fixtures.create_wrestler(api, scenario.team_id, "Alex Mercer")
    wrestler_b = fixtures.create_wrestler(
        api, scenario.team_id, "Blake Nolan", SEX_MALE, 12
    )
    assessment_a = fixtures.create_validated_assessment(
        api, wrestler_a["id"], assessor["id"], assessed_at="2026-11-01T09:00:00Z"
    )
    assessment_b = fixtures.create_validated_assessment(
        api, wrestler_b["id"], assessor["id"], assessed_at="2026-11-01T09:30:00Z"
    )
    dehydrated = fixtures.create_assessment(
        api,
        wrestler_a["id"],
        assessor["id"],
        assessed_at="2026-11-01T10:00:00Z",
        measured_weight_lbs=158.0,
        body_fat_pct=13.8,
        urine_specific_gravity=1.031,
    )
    dehydrated = fixtures.finalize_assessment(
        api, dehydrated["id"], assessor["id"]
    )
    plan_a = fixtures.create_certified_plan(
        api, wrestler_a["id"], scenario.team_id, assessment_a["id"]
    )
    plan_b = fixtures.create_certified_plan(
        api, wrestler_b["id"], scenario.team_id, assessment_b["id"]
    )
    event = fixtures.create_event(
        api, scenario.season_id, "State Qualifier", "2026-12-12", EVENT_TYPE_TOURNAMENT
    )
    entry_a = fixtures.create_entry(
        api,
        event["id"],
        wrestler_a["id"],
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=4,
    )
    entry_b = fixtures.create_entry(
        api,
        event["id"],
        wrestler_b["id"],
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=2,
    )
    fixtures.move_clock(api, _EVENT_DAY_INSTANT)
    fixtures.open_weigh_ins(api, event["id"])
    fixtures.record_weigh_in(api, event["id"], entry_a["id"], 0, _PASSING_WEIGHT_LBS)
    fixtures.record_weigh_in(
        api, event["id"], entry_b["id"], 0, _SECOND_PASSING_WEIGHT_LBS
    )
    fixtures.close_weigh_ins(api, event["id"])
    seeded_event = fixtures.seed_event(api, event["id"])
    flag = fixtures.flags_of_wrestler(api, wrestler_a["id"])[0]
    fixtures.review_flag(api, flag["id"], FLAG_ESCALATED)
    scenario.update(
        assessor_id=assessor["id"],
        wrestler_a_id=wrestler_a["id"],
        wrestler_b_id=wrestler_b["id"],
        hydration_failed_assessment_id=dehydrated["id"],
        plan_a_id=plan_a["id"],
        plan_b_id=plan_b["id"],
        event_id=event["id"],
        seeded_event=seeded_event,
        entry_a_id=entry_a["id"],
        entry_b_id=entry_b["id"],
        flag_a_id=flag["id"],
    )
    return scenario


# ── The declared event walk ──────────────────────────────────────────


def test_event_walk_from_scheduled_to_completed_succeeds_in_order(api):
    """The whole declared event path runs in order and bumps the version each hop.

    §3.8 declares SCHEDULED to WEIGH_IN_OPEN, WEIGH_IN_OPEN to WEIGH_IN_CLOSED,
    the seeding run out of WEIGH_IN_CLOSED and completion out of SEEDED, and
    states that the event's version increments on each of them.  The bracket lock
    flips to true exactly at seeding, and with a single seeded entry the
    conserved seed sum lands on 1.

    Design: Corner/state_machines/event_status_valid_transition_walk_to_completed
    """
    scenario = fixtures.entered_wrestler(api)
    fixtures.move_clock(api, _EVENT_DAY_INSTANT)

    scheduled = fixtures.read_event(api, scenario.event_id)
    assert scheduled["status"] == EVENT_SCHEDULED
    assert scheduled["bracket_locked"] is False

    opened = validate_success(
        api.set_event_status(
            scenario.event_id,
            factories.event_status_payload(EVENT_WEIGH_IN_OPEN),
            STATE_OFFICE,
        )
    )
    assert opened["status"] == EVENT_WEIGH_IN_OPEN
    assert opened["bracket_locked"] is False
    assert opened["version"] == scheduled["version"] + 1

    fixtures.record_weigh_in(
        api, scenario.event_id, scenario.entry_id, 0, _PASSING_WEIGHT_LBS
    )

    before_close = fixtures.read_event(api, scenario.event_id)
    closed = validate_success(
        api.set_event_status(
            scenario.event_id,
            factories.event_status_payload(EVENT_WEIGH_IN_CLOSED),
            STATE_OFFICE,
        )
    )
    assert closed["status"] == EVENT_WEIGH_IN_CLOSED
    assert closed["version"] == before_close["version"] + 1

    seeded = validate_success(api.seed_event(scenario.event_id, STATE_OFFICE))
    assert seeded["status"] == EVENT_SEEDED
    assert seeded["bracket_locked"] is True
    assert seeded["reseed_required"] is False
    assert seeded["seeded_entry_count"] == 1
    assert_seed_integrity_sum(seeded, [1])
    assert seeded["version"] == closed["version"] + 1

    completed = validate_success(
        api.set_event_status(
            scenario.event_id,
            factories.event_status_payload(EVENT_COMPLETED),
            STATE_OFFICE,
        )
    )
    assert completed["status"] == EVENT_COMPLETED
    assert completed["version"] == seeded["version"] + 1


def test_event_walk_carries_the_passing_entry_through_to_seeded(api):
    """The entry follows the event: it weighs in, survives the close and is seeded.

    §3.8 pins the day-zero allowance at nothing, the effective limit at the
    entered class, the verdict at PASS for a reading at or below that class, and
    the advance ENTERED to WEIGHED_IN with latest_effective_weight_lbs set.  The
    weigh-in close scratches only entries still in ENTERED or whose most recent
    reading failed, so this entry is left alone and then seeded at 1.

    Design: Corner/state_machines/event_status_valid_transition_walk_to_completed
    """
    scenario = fixtures.entered_wrestler(api)
    fixtures.move_clock(api, _EVENT_DAY_INSTANT)
    fixtures.open_weigh_ins(api, scenario.event_id)

    weigh_in = validate_success(
        api.create_weigh_in(
            scenario.event_id,
            factories.weigh_in_payload(scenario.entry_id, 0, _PASSING_WEIGHT_LBS),
            WEIGH_IN_OFFICIAL,
        ),
        expected_status=201,
    )
    assert_weight_equals(weigh_in["allowance_lbs"], 0.0, "allowance_lbs")
    assert_weight_equals(
        weigh_in["effective_limit_lbs"],
        float(CANON_TARGET_CLASS_LBS),
        "effective_limit_lbs",
    )
    assert weigh_in["result"] == WEIGH_IN_PASS
    assert weigh_in["below_minimum"] is False

    weighed = fixtures.read_entry(api, scenario.entry_id)
    assert weighed["status"] == ENTRY_WEIGHED_IN
    assert_weight_equals(
        weighed["latest_effective_weight_lbs"],
        _PASSING_WEIGHT_LBS,
        "latest_effective_weight_lbs",
    )

    fixtures.close_weigh_ins(api, scenario.event_id)
    survived = fixtures.read_entry(api, scenario.entry_id)
    assert survived["status"] == ENTRY_WEIGHED_IN
    assert survived["scratch_reason"] is None

    fixtures.seed_event(api, scenario.event_id)
    seeded_entry = fixtures.read_entry(api, scenario.entry_id)
    assert seeded_entry["status"] == ENTRY_SEEDED
    assert seeded_entry["seed_number"] == 1
    assert_weight_equals(
        seeded_entry["latest_effective_weight_lbs"],
        _PASSING_WEIGHT_LBS,
        "latest_effective_weight_lbs",
    )
    assert seeded_entry["weight_class_change_count"] == 0


# ── The guarded season close ─────────────────────────────────────────


def test_season_close_refused_while_an_event_sits_seeded(api):
    """A season may not close over an unfinished bracket.

    §3.1 requires that no event of the season is in WEIGH_IN_OPEN or SEEDED for
    the OPEN to CLOSED hop, and refuses the attempt with ERR_RESEED_REQUIRED.
    The refused call leaves the season in OPEN with its version untouched.

    Design: Corner/state_machines/season_close_blocked_while_event_is_seeded
    """
    scenario = _seeded_event_with_one_entry(api)
    assert scenario.event["status"] == EVENT_SEEDED

    before = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    validate_error(
        api.set_season_status(
            scenario.season_id,
            factories.season_status_payload(SEASON_CLOSED),
            STATE_OFFICE,
        ),
        api_errors.ERR_RESEED_REQUIRED,
        409,
    )

    after = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert after["status"] == SEASON_OPEN
    assert after["version"] == before["version"]


def test_season_close_after_completion_sweeps_scheduled_events_forward(api):
    """Once the bracket is finished the same close succeeds and sweeps the rest.

    §3.8 accepts completion out of SEEDED while reseed_required is false, after
    which §3.1's close precondition is satisfied.  The successful close moves
    every SCHEDULED or WEIGH_IN_CLOSED event of the season to COMPLETED and
    increments the season's version exactly once across the two attempts,
    because the rejected one never mutated the row.

    Design: Corner/state_machines/season_close_blocked_while_event_is_seeded
    """
    scenario = _seeded_event_with_one_entry(api)
    other_event = fixtures.create_event(
        api, scenario.season_id, "Consolation Meet", "2026-12-20", EVENT_TYPE_DUAL
    )
    assert other_event["status"] == EVENT_SCHEDULED

    before = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    validate_error(
        api.set_season_status(
            scenario.season_id,
            factories.season_status_payload(SEASON_CLOSED),
            STATE_OFFICE,
        ),
        api_errors.ERR_RESEED_REQUIRED,
        409,
    )

    finished = validate_success(
        api.set_event_status(
            scenario.event_id,
            factories.event_status_payload(EVENT_COMPLETED),
            STATE_OFFICE,
        )
    )
    assert finished["status"] == EVENT_COMPLETED

    closed = validate_success(
        api.set_season_status(
            scenario.season_id,
            factories.season_status_payload(SEASON_CLOSED),
            STATE_OFFICE,
        )
    )
    assert closed["status"] == SEASON_CLOSED
    assert closed["version"] == before["version"] + 1

    swept = fixtures.read_event(api, other_event["id"])
    assert swept["status"] == EVENT_COMPLETED


# ── The training threshold that certifies an assessor ────────────────


def test_training_hours_accumulate_before_the_threshold_certifies(api):
    """Hours are always added, but the credential hop waits for the threshold.

    §3.2 states that logged hours are always added to the cumulative total and
    that the PROVISIONAL to CERTIFIED hop fires only when that total reaches or
    exceeds the season's assessor_min_training_hours, eight by default.  Four
    hours therefore leaves the assessor provisional at 4.0, and the next four
    take the total to exactly eight and certify them.  Each logged record is one
    mutation of the assessor row, so §2.4 pins one version increment apiece.

    Design: Corner/state_machines/assessor_training_threshold_side_effect_applied
    """
    fixtures.create_open_season(api)
    assessor = fixtures.create_assessor(api)
    assert assessor["status"] == ASSESSOR_PROVISIONAL
    assert assessor["training_hours_completed"] == pytest.approx(0.0, abs=0.01)

    fixtures.log_training(api, assessor["id"], 4)
    after_first = fixtures.read_assessor(api, assessor["id"])
    assert after_first["status"] == ASSESSOR_PROVISIONAL
    assert after_first["training_hours_completed"] == pytest.approx(4.0, abs=0.01)
    assert after_first["version"] == assessor["version"] + 1

    fixtures.log_training(api, assessor["id"], 4)
    after_second = fixtures.read_assessor(api, assessor["id"])
    assert after_second["status"] == ASSESSOR_CERTIFIED
    assert after_second["training_hours_completed"] == pytest.approx(8.0, abs=0.01)
    assert after_second["version"] == after_first["version"] + 1

    assert after_second["validated_assessment_count"] == 0
    assert after_second["voided_assessment_count"] == 0
    assert after_second["last_audit_outcome"] is None
    assert after_second["suspension_reason"] is None


def test_one_training_record_reaching_the_threshold_certifies_immediately(api):
    """A single record that meets the threshold certifies in one hop.

    §3.2's threshold comparison is inclusive, so one record worth the season's
    whole assessor_min_training_hours figure certifies the assessor without an
    intermediate provisional step, leaving the quality dossier at its registration
    values.

    Design: Corner/state_machines/assessor_training_threshold_side_effect_applied
    """
    fixtures.create_open_season(api)
    assessor = fixtures.create_assessor(
        api,
        full_name="Sam Okafor",
        credential_number="AS-1002",
        certified_methods=[METHOD_HYDROSTATIC],
    )
    assert assessor["status"] == ASSESSOR_PROVISIONAL

    fixtures.log_training(api, assessor["id"], DEFAULT_ASSESSOR_MIN_TRAINING_HOURS)
    certified = fixtures.read_assessor(api, assessor["id"])
    assert certified["status"] == ASSESSOR_CERTIFIED
    assert certified["training_hours_completed"] == pytest.approx(
        float(DEFAULT_ASSESSOR_MIN_TRAINING_HOURS), abs=0.01
    )
    assert certified["version"] == assessor["version"] + 1
    assert certified["validated_assessment_count"] == 0
    assert certified["voided_assessment_count"] == 0
    assert certified["last_audit_outcome"] is None
    assert certified["suspension_reason"] is None


# ── Transitions that are not declared out of the current status ──────


def test_scheduled_event_refuses_every_undeclared_transition(api):
    """Out of SCHEDULED only WEIGH_IN_OPEN and CANCELLED are declared.

    §3.8 accepts a seeding run only out of WEIGH_IN_CLOSED or an event awaiting a
    reseed, WEIGH_IN_CLOSED only out of WEIGH_IN_OPEN, and completion only out of
    WEIGH_IN_CLOSED or SEEDED; anything else is ERR_EVENT_INVALID_STATE.  None of
    the refused calls may mutate the event.

    Design: Corner/state_machines/event_invalid_from_state_transitions_rejected
    """
    season = fixtures.create_open_season(api)
    event = fixtures.create_event(
        api, season["id"], "State Qualifier", "2026-12-12", EVENT_TYPE_TOURNAMENT
    )
    assert event["status"] == EVENT_SCHEDULED
    assert event["version"] == 1

    validate_error(
        api.seed_event(event["id"], STATE_OFFICE),
        api_errors.ERR_EVENT_INVALID_STATE,
        409,
    )
    for undeclared in (EVENT_WEIGH_IN_CLOSED, EVENT_COMPLETED):
        validate_error(
            api.set_event_status(
                event["id"], factories.event_status_payload(undeclared), STATE_OFFICE
            ),
            api_errors.ERR_EVENT_INVALID_STATE,
            409,
        )

    unchanged = fixtures.read_event(api, event["id"])
    assert unchanged["status"] == EVENT_SCHEDULED
    assert unchanged["version"] == 1
    assert unchanged["seeded_entry_count"] == 0
    assert unchanged["seed_integrity_sum"] == 0


def test_cancelled_event_refuses_a_return_to_weigh_in_open(api):
    """CANCELLED is terminal, so even the one declared forward hop is refused.

    §3.8 allows cancellation out of SCHEDULED and names CANCELLED terminal, so a
    later request for WEIGH_IN_OPEN is ERR_EVENT_INVALID_STATE.

    Design: Corner/state_machines/event_invalid_from_state_transitions_rejected
    """
    season = fixtures.create_open_season(api)
    event = fixtures.create_event(
        api, season["id"], "Consolation Meet", "2026-12-20", EVENT_TYPE_DUAL
    )

    cancelled = validate_success(
        api.set_event_status(
            event["id"], factories.event_status_payload(EVENT_CANCELLED), STATE_OFFICE
        )
    )
    assert cancelled["status"] == EVENT_CANCELLED

    validate_error(
        api.set_event_status(
            event["id"],
            factories.event_status_payload(EVENT_WEIGH_IN_OPEN),
            STATE_OFFICE,
        ),
        api_errors.ERR_EVENT_INVALID_STATE,
        409,
    )
    assert fixtures.read_event(api, event["id"])["status"] == EVENT_CANCELLED


# ── Birth states ─────────────────────────────────────────────────────


def test_created_rows_report_their_declared_initial_state(api):
    """Every creating endpoint hands back the birth state the requirements pin.

    A season begins in SETUP (§3.1), an assessor in PROVISIONAL (§3.2), a team at
    CLEAR with an empty ledger and roster (§3.1), a wrestler at UNCERTIFIED and
    INELIGIBLE (§3.1), an assessment in DRAFT (§3.3) and a descent plan in DRAFT
    with no schedule yet computed (§3.5).

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    season = fixtures.create_season(api)
    assert season["status"] == SEASON_SETUP

    assessor = fixtures.create_assessor(api)
    assert assessor["status"] == ASSESSOR_PROVISIONAL
    assert assessor["training_hours_completed"] == pytest.approx(0.0, abs=0.01)

    fixtures.set_season_status(api, season["id"], SEASON_OPEN)
    fixtures.log_training(api, assessor["id"], DEFAULT_ASSESSOR_MIN_TRAINING_HOURS)
    fixtures.move_clock(api, ASSESSMENT_DAY_INSTANT)

    team = fixtures.create_team(api, season["id"])
    assert team["compliance_status"] == TEAM_CLEAR
    assert team["open_flag_severity_total"] == 0
    assert team["roster_count"] == 0

    wrestler = fixtures.create_wrestler(api, team["id"])
    assert wrestler["certification_status"] == WRESTLER_UNCERTIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert wrestler["open_health_flag_count"] == 0

    assessment = fixtures.create_assessment(api, wrestler["id"], assessor["id"])
    assert assessment["status"] == ASSESSMENT_DRAFT
    assert_all_null(
        assessment,
        (
            "hydration_passed",
            "lean_body_weight_lbs",
            "minimum_certified_weight_lbs",
            "min_weight_class_lbs",
            "alpha_weight_lbs",
            "void_reason",
        ),
        "draft assessment",
    )

    fixtures.finalize_assessment(api, assessment["id"], assessor["id"])
    plan = fixtures.create_plan(api, wrestler["id"], team["id"], assessment["id"])
    assert plan["status"] == PLAN_DRAFT
    assert plan["total_weeks"] is None
    assert plan["projected_certification_date"] is None
    assert plan["milestone_count"] == 0
    assert plan["missed_milestone_count"] == 0
    assert plan["breach_count"] == 0
    assert plan["revision_count"] == 0


def test_generated_and_competition_rows_start_in_their_declared_state(api):
    """Cascade-generated milestones and the competition rows start where declared.

    §3.5 has plan certification generate one milestone per week index from zero
    through total_weeks inclusive, each starting SCHEDULED with no evaluated
    weight; §3.7 starts an event at SCHEDULED with every bracket counter at zero
    and an entry at ENTERED with no seed; §3.9 starts an audit at OPEN with its
    score and outcome unset.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    scenario = fixtures.certified_wrestler(api)

    rows, meta = validate_paginated(
        api.list_plan_milestones(scenario.plan_id, STATE_OFFICE, {"limit": 100})
    )
    assert meta["total_count"] == WEEKLY_STEP_MILESTONE_COUNT
    assert len(rows) == WEEKLY_STEP_MILESTONE_COUNT
    for row in rows:
        assert row["status"] == MILESTONE_SCHEDULED
        assert row["evaluated_recorded_weight_lbs"] is None

    event = fixtures.create_event(
        api, scenario.season_id, "Northgate Duals", "2026-11-04", EVENT_TYPE_DUAL
    )
    assert event["status"] == EVENT_SCHEDULED
    assert event["bracket_locked"] is False
    assert event["reseed_required"] is False
    assert event["entry_count"] == 0
    assert event["weighed_in_count"] == 0
    assert event["seeded_entry_count"] == 0
    assert event["seed_integrity_sum"] == 0

    entry = fixtures.create_entry(
        api, event["id"], scenario.wrestler_id, scenario.team_id, 165
    )
    assert entry["status"] == ENTRY_ENTERED
    assert entry["seed_number"] is None
    assert entry["latest_effective_weight_lbs"] is None
    assert entry["scratch_reason"] is None
    assert entry["weight_class_change_count"] == 0

    audit = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_TEAM_COMPLIANCE,
        SCORING_SAMPLE_MEAN,
        "2026-11-01",
    )
    assert audit["status"] == AUDIT_OPEN
    assert audit["sample_count"] == 0
    assert audit["discrepancy_score"] is None
    assert audit["outcome"] is None
    assert audit["voided_assessment_count"] == 0


# ── Asking again for a hop that already happened ─────────────────────


def test_repeating_an_already_performed_hop_is_refused(api):
    """A second request for a hop already taken is refused per row family.

    Opening a season requires it to be in SETUP (§3.1), finalizing an assessment
    requires DRAFT and names a second finalize ERR_ASSESSMENT_INVALID_STATE
    (§3.3), and certifying a plan requires DRAFT (§3.5).  Each refusal names its
    own row family and leaves that row exactly where the first hop put it,
    version included.

    Design: Corner/state_machines/repeating_a_completed_transition_rejected
    """
    season = fixtures.create_season(api)
    opened = fixtures.set_season_status(api, season["id"], SEASON_OPEN)
    assert opened["status"] == SEASON_OPEN

    validate_error(
        api.set_season_status(
            season["id"], factories.season_status_payload(SEASON_OPEN), STATE_OFFICE
        ),
        api_errors.ERR_SEASON_INVALID_STATE,
        409,
    )
    season_after = get_success_data(api.get_season(season["id"], STATE_OFFICE))
    assert season_after["status"] == SEASON_OPEN
    assert season_after["version"] == opened["version"]

    fixtures.move_clock(api, ASSESSMENT_DAY_INSTANT)
    team = fixtures.create_team(api, season["id"])
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, team["id"])
    draft = fixtures.create_assessment(api, wrestler["id"], assessor["id"])
    validated = fixtures.finalize_assessment(api, draft["id"], assessor["id"])
    assert validated["status"] == ASSESSMENT_VALIDATED

    validate_error(
        api.finalize_assessment(draft["id"], assessor_headers(assessor["id"])),
        api_errors.ERR_ASSESSMENT_INVALID_STATE,
        409,
    )
    assessment_after = fixtures.read_assessment(api, draft["id"])
    assert assessment_after["status"] == ASSESSMENT_VALIDATED
    assert assessment_after["version"] == validated["version"]

    plan = fixtures.create_plan(api, wrestler["id"], team["id"], draft["id"])
    certified = fixtures.certify_plan(api, plan["id"])
    assert certified["status"] == PLAN_CERTIFIED

    validate_error(
        api.certify_descent_plan(plan["id"], STATE_OFFICE),
        api_errors.ERR_PLAN_INVALID_STATE,
        409,
    )
    plan_after = fixtures.read_plan(api, plan["id"])
    assert plan_after["status"] == PLAN_CERTIFIED
    assert plan_after["version"] == certified["version"]


def test_a_refused_repeat_certification_does_not_re_run_its_side_effects(api):
    """The refused second certification leaves the first one's cascade intact.

    §3.5 has plan certification generate the whole milestone progression once and
    move the wrestler to CERTIFIED and ELIGIBLE, which is what the season's
    certified-wrestler counter of §3.1 tracks.  Because the repeat is refused on
    the from-state, none of that is duplicated: the milestone listing still holds
    exactly the six rows the weekly-step schedule declares and the counter stays
    at one.

    Design: Corner/state_machines/repeating_a_completed_transition_rejected
    """
    scenario = fixtures.certified_wrestler(api)
    assert scenario.plan["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT
    assert scenario.wrestler["certification_status"] == WRESTLER_CERTIFIED

    validate_error(
        api.certify_descent_plan(scenario.plan_id, STATE_OFFICE),
        api_errors.ERR_PLAN_INVALID_STATE,
        409,
    )

    plan_after = fixtures.read_plan(api, scenario.plan_id)
    assert plan_after["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT
    assert plan_after["revision_count"] == 0
    _rows, meta = validate_paginated(
        api.list_plan_milestones(scenario.plan_id, STATE_OFFICE, {"limit": 100})
    )
    assert meta["total_count"] == WEEKLY_STEP_MILESTONE_COUNT

    season_after = get_success_data(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season_after["certified_wrestler_count"] == 1
    wrestler_after = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler_after["certification_status"] == WRESTLER_CERTIFIED


# ── Terminal rows ────────────────────────────────────────────────────


def test_a_voided_assessment_can_never_be_finalized(api):
    """A cascade-voided draft is closed for good, so finalize is refused.

    §3.2 has the suspension of a certified assessor void every DRAFT assessment of
    theirs with void_reason ASSESSOR_SUSPENDED, and §3.3 requires a DRAFT
    from-state for finalizing.  §2.8 runs that from-state check ahead of the
    credential rule, so the refusal names the assessment, and the fork never runs:
    no certified figure appears and the wrestler stays uncertified.

    Design: Corner/state_machines/terminal_rows_reject_every_further_transition
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    draft = fixtures.create_assessment(api, wrestler["id"], assessor["id"])
    assert draft["status"] == ASSESSMENT_DRAFT

    fixtures.suspend_assessor(api, assessor["id"], "Records review pending.")
    voided = fixtures.read_assessment(api, draft["id"])
    assert voided["status"] == ASSESSMENT_VOIDED
    assert voided["void_reason"] == VOID_REASON_ASSESSOR_SUSPENDED

    validate_error(
        api.finalize_assessment(draft["id"], assessor_headers(assessor["id"])),
        api_errors.ERR_ASSESSMENT_INVALID_STATE,
        409,
    )

    after = fixtures.read_assessment(api, draft["id"])
    assert after["status"] == ASSESSMENT_VOIDED
    assert after["void_reason"] == VOID_REASON_ASSESSOR_SUSPENDED
    assert after["version"] == voided["version"]
    assert_all_null(
        after,
        (
            "hydration_passed",
            "lean_body_weight_lbs",
            "minimum_certified_weight_lbs",
            "min_weight_class_lbs",
            "alpha_weight_lbs",
        ),
        "voided assessment",
    )
    wrestler_after = fixtures.read_wrestler(api, wrestler["id"])
    assert wrestler_after["certification_status"] == WRESTLER_UNCERTIFIED
    assert wrestler_after["source_assessment_id"] is None


def test_a_suspended_assessor_cannot_be_suspended_again(api):
    """SUSPENDED terminates the credential lifecycle, so the hop cannot repeat.

    §3.2 accepts an administrative suspension only against a CERTIFIED assessor
    and names any other from-state — provisional, already suspended, or expired —
    ERR_ASSESSOR_INVALID_STATE.  The refused repeat leaves the recorded reason from
    the first suspension in place.

    Design: Corner/state_machines/terminal_rows_reject_every_further_transition
    """
    fixtures.create_open_season(api)
    assessor = fixtures.create_certified_assessor(api)
    assert assessor["status"] == ASSESSOR_CERTIFIED

    first_reason = "Calibration records incomplete."
    suspended = fixtures.suspend_assessor(api, assessor["id"], first_reason)
    assert suspended["status"] == ASSESSOR_SUSPENDED
    assert suspended["suspension_reason"] == first_reason

    validate_error(
        api.suspend_assessor(
            assessor["id"],
            factories.suspension_payload("Second administrative review."),
            STATE_OFFICE,
        ),
        api_errors.ERR_ASSESSOR_INVALID_STATE,
        409,
    )

    after = fixtures.read_assessor(api, assessor["id"])
    assert after["status"] == ASSESSOR_SUSPENDED
    assert after["suspension_reason"] == first_reason
    assert after["version"] == suspended["version"]


def test_a_finalized_audit_cannot_be_scored_twice(api):
    """FINALIZED is where every audit lands, and scoring is accepted only from OPEN.

    §3.9 makes an audit carrying fewer samples than the season's
    audit_min_sample_count unscoreable: the outcome is INCONCLUSIVE, the
    discrepancy score stays null, the audit still lands in FINALIZED and the
    subject assessor's last recorded outcome reflects that verdict, while an
    inconclusive result triggers no cascade at all.  A second finalize is then
    ERR_AUDIT_INVALID_STATE and changes none of it.

    Design: Corner/state_machines/terminal_rows_reject_every_further_transition
    """
    scenario = fixtures.assessed_wrestler(api)
    audit = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        SCORING_SAMPLE_MEAN,
        "2026-11-01",
        assessor_id=scenario.assessor_id,
        samples=factories.audit_samples([(scenario.assessment_id, 15.2)]),
    )
    assert audit["status"] == AUDIT_OPEN
    assert audit["sample_count"] == 1
    assert audit["sample_count"] < DEFAULT_AUDIT_MIN_SAMPLE_COUNT

    finalized = fixtures.finalize_audit(api, audit["id"])
    assert finalized["status"] == AUDIT_FINALIZED
    assert finalized["outcome"] == AUDIT_INCONCLUSIVE
    assert finalized["discrepancy_score"] is None
    assert finalized["voided_assessment_count"] == 0

    validate_error(
        api.finalize_audit(audit["id"], STATE_OFFICE),
        api_errors.ERR_AUDIT_INVALID_STATE,
        409,
    )

    after = fixtures.read_audit(api, audit["id"])
    assert after["status"] == AUDIT_FINALIZED
    assert after["outcome"] == AUDIT_INCONCLUSIVE
    assert after["discrepancy_score"] is None
    assert after["voided_assessment_count"] == 0
    assert after["version"] == finalized["version"]

    assessor_after = fixtures.read_assessor(api, scenario.assessor_id)
    assert assessor_after["status"] == ASSESSOR_CERTIFIED
    assert assessor_after["last_audit_outcome"] == AUDIT_INCONCLUSIVE
    assert assessor_after["voided_assessment_count"] == 0
    assert fixtures.read_assessment(api, scenario.assessment_id)["status"] == (
        ASSESSMENT_VALIDATED
    )


# ── The disqualification cascade over a locked bracket ───────────────


def test_disqualification_fans_out_across_plan_entry_and_bracket(api):
    """One disqualification rewrites the wrestler, the plan, the entry and the event.

    §3.9 has a cited escalated flag drive the wrestler to DISQUALIFIED with the
    supplied reason held as the certification hold and the eligibility dimension
    dropped to INELIGIBLE, cancels every plan of theirs with cancel_reason
    DISQUALIFIED, moves every live entry to DISQUALIFIED with scratch_reason
    UNHEALTHY_WEIGHT_MANAGEMENT, clears the seed that entry held, reduces the
    event's seeded count and conserved seed sum accordingly, raises the reseed
    flag, decrements the team's roster count and — because this wrestler was
    CERTIFIED rather than PROVISIONAL — decrements the season's certified count.
    §2.10 requires every one of those hops inside the same request.

    Design: Corner/state_machines/disqualification_cascade_clears_seed_and_forces_reseed
    """
    scenario = _seeded_bracket_with_two_wrestlers(api)
    assert scenario.seeded_event["status"] == EVENT_SEEDED
    assert scenario.seeded_event["seeded_entry_count"] == 2
    assert_seed_integrity_sum(scenario.seeded_event, [2], "bracket before the removal")
    assert fixtures.read_team(api, scenario.team_id)["roster_count"] == 2
    before_season = get_success_data(api.get_season(scenario.season_id, STATE_OFFICE))
    assert before_season["certified_wrestler_count"] == 2

    reason = "Unhealthy weight management pattern."
    disqualified = fixtures.disqualify_wrestler(
        api, scenario.wrestler_a_id, scenario.flag_a_id, reason
    )
    assert disqualified["certification_status"] == WRESTLER_DISQUALIFIED
    assert disqualified["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert disqualified["certification_hold_reason"] == reason
    assert_instant_equals(
        disqualified["disqualified_at"], _EVENT_DAY_INSTANT, "disqualified_at"
    )

    plan_a = fixtures.read_plan(api, scenario.plan_a_id)
    assert plan_a["status"] == PLAN_CANCELLED
    assert plan_a["cancel_reason"] == CANCEL_REASON_DISQUALIFIED

    entry_a = fixtures.read_entry(api, scenario.entry_a_id)
    assert entry_a["status"] == ENTRY_DISQUALIFIED
    assert entry_a["scratch_reason"] == SCRATCH_REASON_UNHEALTHY
    assert entry_a["seed_number"] is None

    event = fixtures.read_event(api, scenario.event_id)
    assert event["status"] == EVENT_SEEDED
    assert event["seeded_entry_count"] == 1
    assert event["seed_integrity_sum"] == 2
    assert event["reseed_required"] is True
    assert event["bracket_locked"] is True

    assert fixtures.read_team(api, scenario.team_id)["roster_count"] == 1
    after_season = get_success_data(api.get_season(scenario.season_id, STATE_OFFICE))
    assert after_season["certified_wrestler_count"] == 1


def test_the_invalidated_bracket_blocks_completion_until_it_is_rebuilt(api):
    """The raised reseed flag holds the event open until the bracket is rebuilt.

    §3.8 accepts completion out of SEEDED only while reseed_required is false and
    otherwise refuses it with ERR_RESEED_REQUIRED, and it accepts a reseed out of
    SEEDED which re-ranks the pool of entries still WEIGHED_IN or SEEDED, excluding
    the disqualified one, resets the flag and refreshes both counters.  With one
    competitor left in the class the conserved sum of §2.9 comes back to 1, and
    only then does completion succeed.

    Design: Corner/state_machines/disqualification_cascade_clears_seed_and_forces_reseed
    """
    scenario = _seeded_bracket_with_two_wrestlers(api)
    fixtures.disqualify_wrestler(
        api, scenario.wrestler_a_id, scenario.flag_a_id, "Escalated hydration failure."
    )
    invalidated = fixtures.read_event(api, scenario.event_id)
    assert invalidated["reseed_required"] is True

    validate_error(
        api.set_event_status(
            scenario.event_id,
            factories.event_status_payload(EVENT_COMPLETED),
            STATE_OFFICE,
        ),
        api_errors.ERR_RESEED_REQUIRED,
        409,
    )
    still_seeded = fixtures.read_event(api, scenario.event_id)
    assert still_seeded["status"] == EVENT_SEEDED
    assert still_seeded["reseed_required"] is True
    assert still_seeded["version"] == invalidated["version"]

    reseeded = fixtures.seed_event(api, scenario.event_id)
    assert reseeded["status"] == EVENT_SEEDED
    assert reseeded["reseed_required"] is False
    assert reseeded["seeded_entry_count"] == 1
    assert_seed_integrity_sum(reseeded, [1], "rebuilt bracket")
    assert reseeded["version"] == invalidated["version"] + 1

    entry_b = fixtures.read_entry(api, scenario.entry_b_id)
    assert entry_b["status"] == ENTRY_SEEDED
    assert entry_b["seed_number"] == 1
    entry_a = fixtures.read_entry(api, scenario.entry_a_id)
    assert entry_a["status"] == ENTRY_DISQUALIFIED
    assert entry_a["seed_number"] is None

    completed = fixtures.complete_event(api, scenario.event_id)
    assert completed["status"] == EVENT_COMPLETED
    assert completed["seeded_entry_count"] == 1
    assert completed["seed_integrity_sum"] == 1


def test_the_cascade_leaves_the_other_competitor_entirely_alone(api):
    """Only the disqualified wrestler's own rows are rewritten.

    §3.9 scopes the cascade to the plans and entries of the named wrestler, so the
    team-mate keeps their certified plan, their certified and eligible standing and
    their bracket position, and no assessment is touched at all: the hydration-failed
    reading that produced the cited flag stays in its own terminal state.

    Design: Corner/state_machines/disqualification_cascade_clears_seed_and_forces_reseed
    """
    scenario = _seeded_bracket_with_two_wrestlers(api)
    entry_b_before = fixtures.read_entry(api, scenario.entry_b_id)
    assert entry_b_before["seed_number"] == 2

    fixtures.disqualify_wrestler(
        api, scenario.wrestler_a_id, scenario.flag_a_id, "Escalated hydration failure."
    )

    plan_b = fixtures.read_plan(api, scenario.plan_b_id)
    assert plan_b["status"] == PLAN_CERTIFIED
    assert plan_b["cancel_reason"] is None

    wrestler_b = fixtures.read_wrestler(api, scenario.wrestler_b_id)
    assert wrestler_b["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler_b["eligibility_status"] == ELIGIBILITY_ELIGIBLE

    entry_b_after = fixtures.read_entry(api, scenario.entry_b_id)
    assert entry_b_after["status"] == ENTRY_SEEDED
    assert entry_b_after["seed_number"] == 2
    assert entry_b_after["scratch_reason"] is None
    assert entry_b_after["version"] == entry_b_before["version"]

    dehydrated = fixtures.read_assessment(
        api, scenario.hydration_failed_assessment_id
    )
    assert dehydrated["status"] == ASSESSMENT_HYDRATION_FAILED
    assert dehydrated["void_reason"] is None
