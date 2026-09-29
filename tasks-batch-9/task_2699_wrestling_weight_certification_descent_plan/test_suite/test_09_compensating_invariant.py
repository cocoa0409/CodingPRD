"""
Conserved aggregates and the compensating actions that restore them.

The requirements document declares two figures in this service to be conserved:
they are recomputed from their constituent rows on every relevant mutation rather
than incremented blindly, and a compensating action must restore them to exactly
their prior value (§2.9).  This module exercises two of them end to end through
HTTP.

The first is ``Team.open_flag_severity_total`` — a weighted severity ledger over
the team's health flags in ``OPEN`` or ``ESCALATED`` (§2.9, §3.9).  A severity-4
weigh-in-deficit raise pushes a team that already carries a severity-1 hydration
flag from ``WATCH`` to ``PROBATION`` and demotes its eligible wrestlers to
``RESTRICTED``; the medical dismissal of that one flag has to bring the ledger
back to exactly 1 — the surviving hydration flag — and unwind the posture and the
eligibility dimension with it, while the certification dimension never moves.

The second is ``Season.certified_wrestler_count`` — a population count over a
state predicate (§2.5, §3.5).  Opening a replacement descent plan supersedes the
wrestler's certified plan, steps the certification dimension back to
``PROVISIONAL`` and decrements the counter; certifying the successor plan is the
forward action that restores it to exactly its pre-supersede value.
"""

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_flag_severity_matches_source,
    assert_milestone,
    assert_row_count,
    assert_severity_ledger,
    assert_weight_equals,
    expected_min_eligible_class,
    expected_severity_total,
    ids_of,
)
from test_helpers.constants import (
    CANON_BODY_FAT_PCT,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_TARGET_CLASS_LBS,
    CANON_USG_FAIL,
    CANCEL_REASON_SUPERSEDED,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_RESTRICTED,
    ENTRY_WEIGHED_IN,
    EVENT_TYPE_DUAL,
    FLAG_DISMISSED,
    FLAG_HYDRATION_FAIL,
    FLAG_OPEN,
    FLAG_SEVERITY,
    FLAG_WEIGH_IN_DEFICIT,
    MILESTONE_SCHEDULED,
    PLAN_CANCELLED,
    PLAN_CERTIFIED,
    PLAN_DRAFT,
    TEAM_PROBATION,
    TEAM_WATCH,
    VARIANT_LINEAR_RATE,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEEKLY_STEP_MILESTONE_DATES,
    WEEKLY_STEP_SCHEDULE,
    WEIGH_IN_PASS,
    WRESTLER_CERTIFIED,
    WRESTLER_PROVISIONAL,
)
from test_helpers.test_users import (
    MEDICAL_REVIEWER,
    MEDICAL_REVIEWER_USER_ID,
    STATE_OFFICE,
    WEIGH_IN_OFFICIAL,
    coach_headers,
)

# ── Fixed points the two chains reuse ────────────────────────────────
# The second assessment is stamped on a different UTC calendar day than the
# first, so the assessor's daily capacity of three is never approached (§3.3).
_DRY_ASSESSED_AT = "2026-11-03T09:00:00Z"
_DRY_MEASURED_WEIGHT_LBS = 158.0

_EVENT_NAME = "Region Duals"
_EVENT_DATE = "2026-12-12"
_WEIGH_IN_INSTANT = "2026-12-12T08:00:00Z"
_SEASON_WIN_COUNT = 6

# 147.5 is at or under the 150 pound class, so the verdict is PASS outright and
# the allowance is never consulted; it is nonetheless strictly below the 147.6
# pound certified minimum, which is what raises the deficit flag (§3.8).
_DEFICIT_WEIGHT_LBS = 147.5

# The successor plan: a different variant, a later start and a higher target,
# all of which remain admissible against the wrestler's 150 pound hard floor.
_SUCCESSOR_TARGET_CLASS_LBS = 157
_SUCCESSOR_PLAN_START_DATE = "2026-11-09"


def _read_season(api, season_id):
    """The season row, whose ``certified_wrestler_count`` is the conserved count."""
    return validate_success(api.get_season(season_id, STATE_OFFICE), 200)


def _certified_wrestler_count(api, season_id):
    return _read_season(api, season_id)["certified_wrestler_count"]


def _flags_by_source(api, wrestler_id, source):
    """The filtered flag listing, the only discovery channel for raised flags."""
    rows, _meta = validate_paginated(
        api.list_health_flags(
            MEDICAL_REVIEWER,
            {"wrestler_id": wrestler_id, "source": source, "limit": 100},
        )
    )
    return rows


def _ledger_scenario(api):
    """A certified, eligible wrestler on a team already carrying one flag.

    The canonical chain is driven to a certified ``WEEKLY_STEP`` plan, then a
    second assessment is finalized on the hydration-failure arm so a severity-1
    ``HYDRATION_FAIL`` flag sits ``OPEN`` and the team reads ``WATCH`` (§3.3).
    Because a ``WATCH`` posture changes no wrestler's eligibility, the wrestler
    stays ``ELIGIBLE``.  An event is then scheduled, the wrestler entered at the
    150 pound class, weigh-ins opened and the clock moved onto the event date.
    """
    scenario = fixtures.certified_wrestler(api)
    dry = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=_DRY_ASSESSED_AT,
        measured_weight_lbs=_DRY_MEASURED_WEIGHT_LBS,
        body_fat_pct=CANON_BODY_FAT_PCT,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    fixtures.finalize_assessment(api, dry["id"], scenario.assessor_id)
    event = fixtures.create_event(
        api,
        scenario.season_id,
        _EVENT_NAME,
        _EVENT_DATE,
        EVENT_TYPE_DUAL,
        competition_days=1,
        weigh_in_days=1,
    )
    entry = fixtures.create_entry(
        api,
        event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=_SEASON_WIN_COUNT,
    )
    fixtures.open_weigh_ins(api, event["id"])
    fixtures.move_clock(api, _WEIGH_IN_INSTANT)
    scenario.update(
        hydration_assessment=dry,
        hydration_assessment_id=dry["id"],
        event=event,
        event_id=event["id"],
        entry=entry,
        entry_id=entry["id"],
    )
    return scenario


def _record_deficit_weigh_in(api, scenario):
    """Record the below-minimum reading that raises the severity-4 flag."""
    payload = factories.weigh_in_payload(scenario.entry_id, 0, _DEFICIT_WEIGHT_LBS)
    return validate_success(
        api.create_weigh_in(scenario.event_id, payload, WEIGH_IN_OFFICIAL), 201
    )


def _dismiss(api, flag_id, note):
    """Dismiss a flag as the program physician, the compensating action (§3.9)."""
    payload = factories.flag_review_payload(FLAG_DISMISSED, note)
    return validate_success(api.review_health_flag(flag_id, payload, MEDICAL_REVIEWER), 200)


def _open_successor_plan(api, scenario):
    """Open the replacement plan that supersedes the wrestler's certified plan."""
    payload = factories.descent_plan_payload(
        source_assessment_id=scenario.assessment_id,
        target_class_lbs=_SUCCESSOR_TARGET_CLASS_LBS,
        plan_start_date=_SUCCESSOR_PLAN_START_DATE,
        expected_wrestler_version=fixtures.wrestler_version(api, scenario.wrestler_id),
        plan_variant=VARIANT_LINEAR_RATE,
    )
    return validate_success(
        api.create_descent_plan(
            scenario.wrestler_id, payload, coach_headers(scenario.team_id)
        ),
        201,
    )


# ─────────────────────────────────────────────────────────────────────
# The weighted severity ledger and its dismissal
# ─────────────────────────────────────────────────────────────────────


def test_deficit_raise_pushes_weighted_ledger_from_one_to_five(api):
    """A severity-4 raise on top of a severity-1 flag lands the team on probation.

    The specification pins the ledger as the sum of ``severity`` over the team's
    flags in ``OPEN`` or ``ESCALATED`` (§2.9), with severity fixed per source: a
    hydration failure contributes 1 and a weigh-in deficit contributes 4.  Before
    the weigh-in the ledger therefore reads exactly 1 and the posture is ``WATCH``;
    the deficit raise takes it to exactly 5, which is the inclusive lower bound of
    ``PROBATION`` (§3.9).

    Design: Difficulty/compensating_invariant/team_severity_ledger_restored_by_dismissal
    """
    scenario = _ledger_scenario(api)

    # The pre-raise state: one open hydration flag worth 1, posture WATCH, and a
    # wrestler still eligible because WATCH is purely advisory (§3.9).
    team_before = fixtures.read_team(api, scenario.team_id)
    assert_severity_ledger(team_before, 1, "team before the deficit raise")
    assert team_before["compliance_status"] == TEAM_WATCH

    wrestler_before = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler_before["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler_before["eligibility_status"] == ELIGIBILITY_ELIGIBLE

    _record_deficit_weigh_in(api, scenario)

    team_peak = fixtures.read_team(api, scenario.team_id)
    assert_severity_ledger(team_peak, 5, "team at the ledger peak")
    assert team_peak["compliance_status"] == TEAM_PROBATION

    # The ledger the server reports must equal the ledger its own flag rows imply.
    flags = fixtures.flags_of_wrestler(api, scenario.wrestler_id)
    assert expected_severity_total(flags) == 5


def test_deficit_weigh_in_passes_yet_still_raises_the_severity_four_flag(api):
    """The deficit flag follows from ``below_minimum``, not from the verdict.

    A 147.5 pound reading against the 150 pound class passes outright, so the
    allowance is never consulted (§3.8): the growth component is 0 and day zero
    earns nothing, making ``effective_limit_lbs`` exactly the class limit.  The
    same reading is strictly below the wrestler's 147.6 pound certified minimum,
    so ``below_minimum`` is true and a ``WEIGH_IN_DEFICIT`` flag of severity 4 is
    raised carrying that weigh-in's id, while the entry still advances to
    ``WEIGHED_IN``.

    Design: Difficulty/compensating_invariant/team_severity_ledger_restored_by_dismissal
    """
    scenario = _ledger_scenario(api)

    weigh_in = _record_deficit_weigh_in(api, scenario)

    assert weigh_in["result"] == WEIGH_IN_PASS
    assert weigh_in["below_minimum"] is True
    assert weigh_in["recorded_weight_lbs"] == pytest.approx(
        _DEFICIT_WEIGHT_LBS, abs=0.01
    )
    assert_weight_equals(weigh_in["allowance_lbs"], 0.0, "allowance_lbs")
    assert_weight_equals(
        weigh_in["effective_limit_lbs"], float(CANON_TARGET_CLASS_LBS), "effective_limit_lbs"
    )

    deficit_flags = _flags_by_source(
        api, scenario.wrestler_id, FLAG_WEIGH_IN_DEFICIT
    )
    assert len(deficit_flags) == 1
    deficit = deficit_flags[0]
    assert deficit["status"] == FLAG_OPEN
    assert deficit["severity"] == FLAG_SEVERITY[FLAG_WEIGH_IN_DEFICIT]
    assert_flag_severity_matches_source(deficit)
    assert deficit["weigh_in_id"] == weigh_in["id"]

    # The probation demotion moves the eligibility dimension alone (§3.9).
    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["eligibility_status"] == ELIGIBILITY_RESTRICTED
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED

    entry = fixtures.read_entry(api, scenario.entry_id)
    assert entry["status"] == ENTRY_WEIGHED_IN
    assert entry["latest_effective_weight_lbs"] == pytest.approx(
        _DEFICIT_WEIGHT_LBS, abs=0.01
    )


def test_dismissal_restores_the_ledger_to_exactly_one_not_zero(api):
    """Dismissing the deficit flag restores the ledger to its exact pre-raise value.

    ``OPEN → DISMISSED`` is the compensating action the specification names: it
    removes that flag's ``severity`` from ``open_flag_severity_total``, restoring
    the ledger to exactly its pre-raise value, recomputes ``compliance_status``,
    and — because the team thereby leaves ``PROBATION`` — returns every wrestler
    whose ``eligibility_status`` is ``RESTRICTED`` and whose
    ``certification_status`` is ``CERTIFIED`` to ``ELIGIBLE`` (§3.9).  Because the
    conserved quantity is a weighted sum, the restored value is a non-zero 1 — the
    surviving hydration flag — and not 0.

    Design: Difficulty/compensating_invariant/team_severity_ledger_restored_by_dismissal
    """
    scenario = _ledger_scenario(api)
    _record_deficit_weigh_in(api, scenario)

    deficit = _flags_by_source(api, scenario.wrestler_id, FLAG_WEIGH_IN_DEFICIT)[0]
    assert fixtures.read_team(api, scenario.team_id)["open_flag_severity_total"] == 5

    note = "Scale calibration error confirmed; deficit flag dismissed."
    reviewed = _dismiss(api, deficit["id"], note)

    assert reviewed["status"] == FLAG_DISMISSED
    assert reviewed["review_note"] == note
    assert reviewed["reviewer_user_id"] == MEDICAL_REVIEWER_USER_ID

    team_after = fixtures.read_team(api, scenario.team_id)
    assert team_after["open_flag_severity_total"] == 1
    assert_severity_ledger(team_after, 1, "team after the dismissal")
    assert team_after["compliance_status"] == TEAM_WATCH

    wrestler_after = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler_after["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert wrestler_after["certification_status"] == WRESTLER_CERTIFIED


def test_dismissal_leaves_the_surviving_hydration_flag_and_the_entry_alone(api):
    """The compensating action removes one flag's severity and nothing else.

    The ledger sums only flags in ``OPEN`` or ``ESCALATED`` (§2.9), so the
    severity-1 ``HYDRATION_FAIL`` flag must still be ``OPEN`` after the deficit
    flag is dismissed, and it must be the only open flag left — which is also what
    ``open_health_flag_count`` reports (§3.9).  The certification dimension never
    moved and the entry the deficit reading advanced stays ``WEIGHED_IN``
    throughout: nothing in the review path touches a competition entry.

    Design: Difficulty/compensating_invariant/team_severity_ledger_restored_by_dismissal
    """
    scenario = _ledger_scenario(api)
    _record_deficit_weigh_in(api, scenario)

    deficit = _flags_by_source(api, scenario.wrestler_id, FLAG_WEIGH_IN_DEFICIT)[0]
    _dismiss(api, deficit["id"], "Deficit flag dismissed after review.")

    hydration_flags = _flags_by_source(
        api, scenario.wrestler_id, FLAG_HYDRATION_FAIL
    )
    assert len(hydration_flags) == 1
    assert hydration_flags[0]["status"] == FLAG_OPEN
    assert hydration_flags[0]["severity"] == FLAG_SEVERITY[FLAG_HYDRATION_FAIL]

    open_rows = assert_row_count(
        api.list_health_flags(
            MEDICAL_REVIEWER,
            {
                "wrestler_id": scenario.wrestler_id,
                "status": FLAG_OPEN,
                "limit": 100,
            },
        ),
        1,
        "open flags of the wrestler",
    )
    assert ids_of(open_rows) == [hydration_flags[0]["id"]]

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["open_health_flag_count"] == 1
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["minimum_certified_weight_lbs"] == pytest.approx(
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS, abs=0.01
    )

    entry = fixtures.read_entry(api, scenario.entry_id)
    assert entry["status"] == ENTRY_WEIGHED_IN


# ─────────────────────────────────────────────────────────────────────
# The certified-wrestler population counter and its restoration
# ─────────────────────────────────────────────────────────────────────


def test_superseding_a_certified_plan_decrements_the_population_counter_once(api):
    """Opening a replacement plan drops the counter from 1 to exactly 0.

    ``Season.certified_wrestler_count`` counts the wrestlers on the season's teams
    whose certification dimension currently reads ``CERTIFIED`` (§2.5).  Creating a
    plan cancels the wrestler's prior non-terminal plan with ``cancel_reason``
    ``SUPERSEDED`` and sets the new plan's ``supersedes_plan_id`` to it; because
    the superseded plan had been ``CERTIFIED``, the wrestler steps back
    ``CERTIFIED → PROVISIONAL``, ``eligibility_status`` drops to ``INELIGIBLE`` and
    the counter is decremented by one — exactly once (§3.5).

    Design: Difficulty/compensating_invariant/certified_wrestler_population_counter_restored_by_supersede
    """
    scenario = fixtures.certified_wrestler(api)
    assert _certified_wrestler_count(api, scenario.season_id) == 1

    successor = _open_successor_plan(api, scenario)

    assert _certified_wrestler_count(api, scenario.season_id) == 0

    assert successor["status"] == PLAN_DRAFT
    assert successor["supersedes_plan_id"] == scenario.plan_id

    superseded = fixtures.read_plan(api, scenario.plan_id)
    assert superseded["status"] == PLAN_CANCELLED
    assert superseded["cancel_reason"] == CANCEL_REASON_SUPERSEDED

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
    assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE


def test_certifying_the_successor_plan_restores_the_counter_to_exactly_one(api):
    """The forward action restores the population counter to its prior value.

    Certifying the successor plan drives ``DRAFT → CERTIFIED``, steps the wrestler
    ``PROVISIONAL → CERTIFIED``, takes the eligibility dimension out of
    ``INELIGIBLE`` to ``ELIGIBLE`` because the owning team is ``CLEAR``, and
    increments ``certified_wrestler_count`` by one (§3.5).  The counter is
    therefore back to exactly 1 — its pre-supersede value — and it never reads 2 at
    any observation point, which a forgotten decrement or a double increment would
    expose.

    Design: Difficulty/compensating_invariant/certified_wrestler_population_counter_restored_by_supersede
    """
    scenario = fixtures.certified_wrestler(api)
    observed = [_certified_wrestler_count(api, scenario.season_id)]

    successor = _open_successor_plan(api, scenario)
    observed.append(_certified_wrestler_count(api, scenario.season_id))

    certified = validate_success(
        api.certify_descent_plan(successor["id"], STATE_OFFICE), 200
    )
    observed.append(_certified_wrestler_count(api, scenario.season_id))

    assert observed == [1, 0, 1]
    assert 2 not in observed

    assert certified["status"] == PLAN_CERTIFIED
    assert certified["target_class_lbs"] == _SUCCESSOR_TARGET_CLASS_LBS

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_ELIGIBLE


def test_successor_alone_governs_and_the_cancelled_plan_keeps_its_schedule(api):
    """After the restoration the successor, not the cancelled plan, is the certified one.

    The plan listing narrowed by ``wrestler_id`` and ``status`` must return exactly
    one row — the successor — because the specification allows at most one plan of a
    wrestler in ``CERTIFIED`` or ``BREACHED`` (§3.7).  Nothing in the supersede path
    touches the cancelled plan's milestones: milestone rows are only waived or
    deleted by a revision (§3.6), so the six ``WEEKLY_STEP`` rows the first
    certification generated survive untouched, all still ``SCHEDULED``, and the
    cancelled plan's ``milestone_count`` still reads six.

    Design: Difficulty/compensating_invariant/certified_wrestler_population_counter_restored_by_supersede
    """
    scenario = fixtures.certified_wrestler(api)
    successor = _open_successor_plan(api, scenario)
    validate_success(api.certify_descent_plan(successor["id"], STATE_OFFICE), 200)

    certified_rows = assert_row_count(
        api.list_descent_plans(
            STATE_OFFICE,
            {
                "wrestler_id": scenario.wrestler_id,
                "status": PLAN_CERTIFIED,
                "limit": 100,
            },
        ),
        1,
        "certified plans of the wrestler",
    )
    assert ids_of(certified_rows) == [successor["id"]]

    cancelled = fixtures.read_plan(api, scenario.plan_id)
    assert cancelled["status"] == PLAN_CANCELLED
    assert cancelled["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT

    milestones = fixtures.milestones_of(api, scenario.plan_id)
    assert len(milestones) == WEEKLY_STEP_MILESTONE_COUNT
    for week_index, milestone in enumerate(milestones):
        allowable = WEEKLY_STEP_SCHEDULE[week_index]
        assert_milestone(
            milestone,
            week_index,
            WEEKLY_STEP_MILESTONE_DATES[week_index],
            allowable,
            expected_min_eligible_class(
                allowable, CANON_MINIMUM_CERTIFIED_WEIGHT_LBS
            ),
            MILESTONE_SCHEDULED,
            f"cancelled plan milestone week {week_index}",
        )
