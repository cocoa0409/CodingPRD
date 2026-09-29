"""
Version pinning on wrestler and entry writes, and the cumulative breach counter.

Three behaviour families the requirements state as cross-cutting layers over the
rest of the API are exercised here.

The first two are the only two optimistic-concurrency rules §2.7 declares.
Opening a descent plan carries a non-optional ``expected_wrestler_version``, and
a value that does not equal the wrestler's current stored ``version`` is refused
with ``ERR_STALE_WRESTLER_VERSION`` (HTTP 412); changing an entry's weight class
carries a non-optional ``expected_entry_version``, and a mismatch is refused with
``ERR_STALE_ENTRY_VERSION`` (HTTP 412).  §2.7 pins both as pure stale-version
comparisons against the parent row's stored ``version``, and §2.8 places the
version check after every shape, ownership and weight-class check, so a rejection
of an otherwise valid body can only be the version guard firing.  Each rule is
walked twice: once with the stale view, which is refused and mutates nothing, and
once with the current view, which lands and produces exactly the state the stale
writer would have silently discarded.

The third is the cumulative side of the descent-plan breach threshold.  §3.6
recomputes ``missed_milestone_count`` from the plan's milestone rows on every
compliance sweep and moves the plan ``CERTIFIED -> BREACHED`` when that count
reaches or exceeds the season's ``plan_breach_limit``, which the shipped defaults
in §2.5 put at two.  The threshold is walked at limit minus one and at the limit
itself, and then across the two candidate resets: §3.6 states emphatically that a
revision does **not** reset ``missed_milestone_count``, while §3.5 gives a freshly
opened plan its own counters at zero.

Every precondition below is built through the declared endpoints, because the
service starts each test with an empty database and the logical clock at its
start instant.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_milestone,
    assert_row_count,
    assert_seed_integrity_sum,
    assert_seed_sum_matches_entries,
    assert_version_is,
    assert_weight_equals,
    expected_min_eligible_class,
    expected_minimum_certified_weight,
    plus_weeks,
    weekly_step_allowable_weights,
)
from test_helpers.constants import (
    ASSESSMENT_SUPERSEDED,
    ASSESSMENT_VALIDATED,
    CANCEL_REASON_SUPERSEDED,
    CANON_ALPHA_WEIGHT_LBS,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_TARGET_CLASS_LBS,
    DEFAULT_MAX_WEEKLY_DESCENT_PCT,
    DEFAULT_MIN_BODY_FAT_PCT_MALE,
    DEFAULT_PLAN_BREACH_LIMIT,
    ENTRY_SEEDED,
    EVENT_SEEDED,
    FLAG_DISMISSED,
    FLAG_PLAN_BREACH,
    MILESTONE_MISSED,
    MILESTONE_SCHEDULED,
    METHOD_BIA,
    PLAN_BREACHED,
    PLAN_CANCELLED,
    PLAN_CERTIFIED,
    PLAN_START_DATE,
    SEX_MALE,
    VARIANT_WEEKLY_STEP,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEEKLY_STEP_MILESTONE_DATES,
)
from test_helpers.test_users import STATE_OFFICE

# ── The second measurement the stale plan writer never saw ───────────
# A second hydrated reading of the same wrestler, six pounds lighter than the
# canonical one.  §3.3 fixes the derived figures: the lean weight is the measured
# weight times one minus the fat fraction rounded to one place, the minimum
# certified weight is that already-rounded lean weight divided by one minus the
# male floor fraction, and alpha is the measurement itself, unchanged.
_SECOND_MEASURED_WEIGHT_LBS = 158.0
_SECOND_BODY_FAT_PCT = 14.0
_SECOND_USG = 1.018
_SECOND_ASSESSED_AT = "2026-11-01T14:00:00Z"
_SECOND_MINIMUM_CERTIFIED_WEIGHT_LBS = expected_minimum_certified_weight(
    _SECOND_MEASURED_WEIGHT_LBS, _SECOND_BODY_FAT_PCT, DEFAULT_MIN_BODY_FAT_PCT_MALE
)

# The compounding schedule §3.5 generates from the *new* alpha weight: each week
# is the previous week's already-rounded value times one minus the rate.
_SECOND_SCHEDULE = weekly_step_allowable_weights(
    _SECOND_MEASURED_WEIGHT_LBS, DEFAULT_MAX_WEEKLY_DESCENT_PCT, CANON_TARGET_CLASS_LBS
)
_SECOND_TOTAL_WEEKS = len(_SECOND_SCHEDULE) - 1

# The schedule the canonical 159.6 pound alpha produces, which is what a plan
# built from the stale view would have projected instead.
_CANON_SCHEDULE = weekly_step_allowable_weights(
    CANON_ALPHA_WEIGHT_LBS, DEFAULT_MAX_WEEKLY_DESCENT_PCT, CANON_TARGET_CLASS_LBS
)

# ── The locked bracket the entry-version rule guards ─────────────────
_EVENT_NAME = "State Qualifier"
_EVENT_DATE = "2026-12-12"
_WEIGH_IN_INSTANT = "2026-12-12T07:00:00Z"
_ENTRY_CLASS_LBS = CANON_TARGET_CLASS_LBS
_FIRST_MOVE_CLASS_LBS = 157
_SECOND_MOVE_CLASS_LBS = 165
_WRESTLER_A_WINS = 5
_WRESTLER_B_WINS = 3
_WRESTLER_A_WEIGH_IN_LBS = 150.0
_WRESTLER_B_WEIGH_IN_LBS = 149.0
_SECOND_WRESTLER_NAME = "Bailey Novak"
_SECOND_WRESTLER_GRADE = 12
_SECOND_ASSESSED_AT_B = "2026-11-01T10:00:00Z"

# ── The compliance sweep instants ────────────────────────────────────
# §3.6 considers only milestones whose effective_date is on or before the current
# logical clock date.  On 2026-11-05 exactly one of the six generated milestones
# has come due; on 2026-11-12 exactly two have.
_FIRST_SWEEP_INSTANT = "2026-11-05T12:00:00Z"
_SECOND_SWEEP_INSTANT = "2026-11-12T12:00:00Z"
_REVISED_START_DATE = "2026-11-16"
_REPLACEMENT_START_DATE = "2026-11-23"


# ── Scenario builders ────────────────────────────────────────────────

def _wrestler_repointed_at_a_second_assessment(api: ApiClient) -> fixtures.Scenario:
    """A wrestler whose certified figures moved after the coach last looked.

    The canonical chain of §3.1 to §3.3 is walked once, producing a validated
    assessment at 159.6 pounds and 14.0 percent.  The wrestler's ``version`` is
    then read — this is the view a coach would hold — and a *second* hydrated
    assessment is opened and finalized.  §3.3 makes that finalize repoint the
    wrestler's ``source_assessment_id``, recompute every certified figure from the
    new reading and increment the wrestler's ``version``, so the captured view is
    now one behind.
    """
    scenario = fixtures.assessed_wrestler(api)
    stale_version = fixtures.wrestler_version(api, scenario.wrestler_id)
    second = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        method=METHOD_BIA,
        assessed_at=_SECOND_ASSESSED_AT,
        measured_weight_lbs=_SECOND_MEASURED_WEIGHT_LBS,
        body_fat_pct=_SECOND_BODY_FAT_PCT,
        urine_specific_gravity=_SECOND_USG,
    )
    second = fixtures.finalize_assessment(api, second["id"], scenario.assessor_id)
    scenario.update(
        stale_wrestler_version=stale_version,
        second_assessment=second,
        second_assessment_id=second["id"],
    )
    return scenario


def _plan_creation_body(scenario: fixtures.Scenario, expected_wrestler_version: int) -> Dict[str, Any]:
    """The plan-creation body of §3.5, valid but for the pinned version."""
    return factories.descent_plan_payload(
        source_assessment_id=scenario.second_assessment_id,
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
        expected_wrestler_version=expected_wrestler_version,
        plan_variant=VARIANT_WEEKLY_STEP,
    )


def _plans_of(api: ApiClient, wrestler_id: str) -> Any:
    """Every plan of one wrestler, through the filtered listing of §3.5."""
    return api.list_descent_plans(STATE_OFFICE, {"wrestler_id": wrestler_id, "limit": 100})


def _seeded_two_wrestler_bracket(api: ApiClient) -> fixtures.Scenario:
    """A locked single-class bracket holding two seeded entries.

    Two wrestlers of one team are each certified from an identical 159.6 pound
    reading and carry a certified ``WEEKLY_STEP`` plan targeting 150.  Both are
    entered in one single-day tournament at 150 — which §3.7's four-step floor
    derivation admits, because as of the event date the governing plan's last due
    milestone allows 147.9 pounds and the smallest class at or above that is 150 —
    both pass the scale, weigh-ins close and the bracket is seeded, which §3.8
    says sets ``bracket_locked`` true.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler_a = fixtures.create_wrestler(api, scenario.team_id)
    wrestler_b = fixtures.create_wrestler(
        api,
        scenario.team_id,
        full_name=_SECOND_WRESTLER_NAME,
        sex=SEX_MALE,
        grade=_SECOND_WRESTLER_GRADE,
    )
    assess_a = fixtures.create_validated_assessment(api, wrestler_a["id"], assessor["id"])
    assess_b = fixtures.create_validated_assessment(
        api, wrestler_b["id"], assessor["id"], assessed_at=_SECOND_ASSESSED_AT_B
    )
    fixtures.create_certified_plan(
        api, wrestler_a["id"], scenario.team_id, assess_a["id"]
    )
    fixtures.create_certified_plan(
        api, wrestler_b["id"], scenario.team_id, assess_b["id"]
    )
    event = fixtures.create_event(api, scenario.season_id, _EVENT_NAME, _EVENT_DATE)
    entry_a = fixtures.create_entry(
        api,
        event["id"],
        wrestler_a["id"],
        scenario.team_id,
        _ENTRY_CLASS_LBS,
        season_win_count=_WRESTLER_A_WINS,
    )
    entry_b = fixtures.create_entry(
        api,
        event["id"],
        wrestler_b["id"],
        scenario.team_id,
        _ENTRY_CLASS_LBS,
        season_win_count=_WRESTLER_B_WINS,
    )
    fixtures.move_clock(api, _WEIGH_IN_INSTANT)
    fixtures.open_weigh_ins(api, event["id"])
    fixtures.record_weigh_in(
        api, event["id"], entry_a["id"], 0, _WRESTLER_A_WEIGH_IN_LBS
    )
    fixtures.record_weigh_in(
        api, event["id"], entry_b["id"], 0, _WRESTLER_B_WEIGH_IN_LBS
    )
    fixtures.close_weigh_ins(api, event["id"])
    seeded_event = fixtures.seed_event(api, event["id"])
    scenario.update(
        assessor_id=assessor["id"],
        wrestler_a_id=wrestler_a["id"],
        wrestler_b_id=wrestler_b["id"],
        event=seeded_event,
        event_id=event["id"],
        entry_a_id=entry_a["id"],
        entry_b_id=entry_b["id"],
    )
    return scenario


def _breached_plan(api: ApiClient) -> fixtures.Scenario:
    """A certified plan swept twice with no weigh-in on file, landing breached.

    The canonical certified plan of §3.5 generates six milestones seven days
    apart from 2026-11-02.  No weigh-in is ever recorded, so §3.6 finds an empty
    candidate set for every due milestone and marks it ``MISSED``.  Two sweeps —
    one after week zero has come due, one after week one has — take
    ``missed_milestone_count`` to the shipped ``plan_breach_limit`` of two.
    """
    scenario = fixtures.certified_wrestler(api)
    fixtures.move_clock(api, _FIRST_SWEEP_INSTANT)
    fixtures.run_compliance(api, scenario.season_id)
    scenario.update(after_first_sweep=fixtures.read_plan(api, scenario.plan_id))
    fixtures.move_clock(api, _SECOND_SWEEP_INSTANT)
    fixtures.run_compliance(api, scenario.season_id)
    scenario.update(after_second_sweep=fixtures.read_plan(api, scenario.plan_id))
    return scenario


def _milestone_rows(api: ApiClient, plan_id: str) -> List[Dict[str, Any]]:
    """A plan's milestones, in the week-index ascending order §2.3 pins."""
    rows, _meta = validate_paginated(
        api.list_plan_milestones(plan_id, STATE_OFFICE, {"limit": 100})
    )
    return rows


def _flag_rows(api: ApiClient, wrestler_id: str, source: str) -> List[Dict[str, Any]]:
    """One wrestler's flags of one source, through the filtered listing of §3.9."""
    rows, _meta = validate_paginated(
        api.list_health_flags(
            STATE_OFFICE, {"wrestler_id": wrestler_id, "source": source, "limit": 100}
        )
    )
    return rows


# ── §2.7: version pinning on the wrestler parent ─────────────────────

def test_stale_expected_wrestler_version_refuses_the_plan_create(api):
    """A plan create pinned to a superseded wrestler view is refused 412.

    §2.7 makes ``expected_wrestler_version`` non-optional on a plan create and
    rejects the create with ``ERR_STALE_WRESTLER_VERSION`` when it does not equal
    the wrestler's current stored ``version``.  Here the coach's captured view is
    exactly one behind, because §3.3's validated arm incremented the wrestler's
    ``version`` when a second assessment was finalized.  Every other part of the
    body is admissible — the source assessment is ``VALIDATED`` and belongs to this
    wrestler, and the target class is a ladder member at or above the wrestler's
    ``min_weight_class_lbs`` — and §2.8 evaluates all of those checks *before* the
    version pin, so only the version comparison can explain the refusal.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_wrestler_version_rejected_then_accepted
    """
    scenario = _wrestler_repointed_at_a_second_assessment(api)
    stale_version = scenario.stale_wrestler_version

    before = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert_version_is(
        before, stale_version + 1, "wrestler after the second finalize"
    )

    response = api.create_descent_plan(
        scenario.wrestler_id,
        _plan_creation_body(scenario, stale_version),
        scenario.coach,
    )
    validate_error(response, api_errors.ERR_STALE_WRESTLER_VERSION, 412)

    # The refused create performed none of the writes §3.5 declares for it: no
    # plan row exists at all, so nothing was superseded and nothing was built.
    assert_row_count(
        _plans_of(api, scenario.wrestler_id), 0, "plans of the wrestler"
    )

    # The wrestler row is untouched, version included.
    after = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert_version_is(after, stale_version + 1, "wrestler after the refused create")
    assert after["source_assessment_id"] == scenario.second_assessment_id, (
        "the refused create must not repoint the wrestler's source assessment"
    )
    assert_weight_equals(
        after["alpha_weight_lbs"],
        _SECOND_MEASURED_WEIGHT_LBS,
        "wrestler alpha_weight_lbs after the refused create",
    )
    assert_weight_equals(
        after["minimum_certified_weight_lbs"],
        _SECOND_MINIMUM_CERTIFIED_WEIGHT_LBS,
        "wrestler minimum_certified_weight_lbs after the refused create",
    )


def test_current_expected_wrestler_version_accepts_the_plan_on_the_new_baseline(api):
    """The same body succeeds on the current version and projects the new alpha.

    §2.7 describes the pin as a pure stale-version comparison, so the byte-for-byte
    identical body lands as soon as the writer supplies the wrestler's current
    ``version``.  What the stale writer would have discarded is then visible in the
    generated schedule: §3.5 anchors the weekly progression on the wrestler's
    ``alpha_weight_lbs``, which the second finalize moved from 159.6 to 158.0
    pounds, so the compounding schedule arrives at the 150 pound target one week
    sooner and generates one milestone fewer than the stale baseline would have.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_wrestler_version_rejected_then_accepted
    """
    scenario = _wrestler_repointed_at_a_second_assessment(api)
    stale_version = scenario.stale_wrestler_version

    validate_error(
        api.create_descent_plan(
            scenario.wrestler_id,
            _plan_creation_body(scenario, stale_version),
            scenario.coach,
        ),
        api_errors.ERR_STALE_WRESTLER_VERSION,
        412,
    )

    current_version = fixtures.wrestler_version(api, scenario.wrestler_id)
    assert current_version == stale_version + 1, (
        "the second finalize increments the wrestler's version exactly once"
    )

    created = validate_success(
        api.create_descent_plan(
            scenario.wrestler_id,
            _plan_creation_body(scenario, current_version),
            scenario.coach,
        ),
        201,
    )
    assert created["supersedes_plan_id"] is None, (
        "the wrestler held no prior non-terminal plan, so supersedes_plan_id stays null"
    )

    plan = fixtures.certify_plan(api, created["id"])
    assert plan["status"] == PLAN_CERTIFIED
    assert plan["total_weeks"] == _SECOND_TOTAL_WEEKS
    assert plan["milestone_count"] == _SECOND_TOTAL_WEEKS + 1
    assert plan["milestone_count"] < WEEKLY_STEP_MILESTONE_COUNT, (
        "the lighter baseline reaches the target sooner than the stale one would"
    )
    assert plan["projected_certification_date"] == plus_weeks(
        PLAN_START_DATE, _SECOND_TOTAL_WEEKS
    )

    rows = _milestone_rows(api, plan["id"])
    assert len(rows) == len(_SECOND_SCHEDULE)
    for week_index, allowable in enumerate(_SECOND_SCHEDULE):
        assert_milestone(
            rows[week_index],
            week_index,
            plus_weeks(PLAN_START_DATE, week_index),
            allowable,
            expected_min_eligible_class(
                allowable, _SECOND_MINIMUM_CERTIFIED_WEIGHT_LBS
            ),
            MILESTONE_SCHEDULED,
            f"week {week_index} milestone",
        )

    # Week zero is the new baseline, not the one the stale writer held.
    assert_weight_equals(
        rows[0]["allowable_weight_lbs"],
        _SECOND_MEASURED_WEIGHT_LBS,
        "week zero allowable weight",
    )
    assert rows[0]["allowable_weight_lbs"] != CANON_ALPHA_WEIGHT_LBS, (
        "a schedule built from the stale view would have started at 159.6 pounds"
    )
    assert len(_CANON_SCHEDULE) != len(_SECOND_SCHEDULE), (
        "the two baselines genuinely differ in the number of weeks they need"
    )

    # §3.3: the newly validated assessment supersedes the earlier one and becomes
    # the wrestler's source, which is exactly the repoint the pin protects.
    earlier = fixtures.read_assessment(api, scenario.assessment_id)
    assert earlier["status"] == ASSESSMENT_SUPERSEDED
    assert (
        fixtures.read_assessment(api, scenario.second_assessment_id)["status"]
        == ASSESSMENT_VALIDATED
    )
    assert (
        fixtures.read_wrestler(api, scenario.wrestler_id)["source_assessment_id"]
        == scenario.second_assessment_id
    )


# ── §2.7: version pinning on the tournament-entry parent ─────────────

def test_stale_expected_entry_version_refuses_the_replayed_class_change(api):
    """A replayed class change carrying a now-stale entry version is refused 412.

    §2.7 makes ``expected_entry_version`` non-optional on a weight-class change and
    rejects the change with ``ERR_STALE_ENTRY_VERSION`` when it does not equal the
    entry's current stored ``version``.  One change lands with the version the
    state office observed after seeding, and §3.8 increments the entry's ``version``
    as part of it, so replaying that same figure is one behind.  The replayed body
    is otherwise admissible — 165 is a ladder member at or above the wrestler's
    lowest eligible class, the entry is ``SEEDED`` and the bracket is locked — so
    only the version comparison can explain the refusal, and §3.8's reseed of the
    destination group never runs.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_entry_version_rejected_then_accepted
    """
    scenario = _seeded_two_wrestler_bracket(api)

    # §3.8: the initial seeding admits the two weighed-in entries, ranks them by
    # season_win_count descending inside their single class and locks the bracket.
    assert scenario.event["status"] == EVENT_SEEDED
    assert scenario.event["bracket_locked"] is True
    assert scenario.event["reseed_required"] is False
    assert scenario.event["seeded_entry_count"] == 2
    assert_seed_integrity_sum(scenario.event, [2], "event after the initial seeding")

    observed = fixtures.read_entry(api, scenario.entry_b_id)
    assert observed["status"] == ENTRY_SEEDED
    assert observed["seed_number"] == 2, (
        "the wrestler with fewer season wins takes the second seed of the class"
    )
    observed_version = observed["version"]

    first = fixtures.change_weight_class(
        api, scenario.entry_b_id, _FIRST_MOVE_CLASS_LBS, observed_version
    )
    assert first["weight_class_lbs"] == _FIRST_MOVE_CLASS_LBS
    assert first["weight_class_change_count"] == 1
    assert first["status"] == ENTRY_SEEDED

    replay = api.change_entry_weight_class(
        scenario.entry_b_id,
        factories.weight_class_change_payload(
            _SECOND_MOVE_CLASS_LBS, observed_version
        ),
        STATE_OFFICE,
    )
    validate_error(replay, api_errors.ERR_STALE_ENTRY_VERSION, 412)

    # The refused replay is a complete no-op on the entry.
    after = fixtures.read_entry(api, scenario.entry_b_id)
    assert after["weight_class_lbs"] == _FIRST_MOVE_CLASS_LBS
    assert after["weight_class_change_count"] == 1
    assert after["seed_number"] == 1, (
        "the destination group of the accepted change holds a single contiguous seed"
    )
    assert_version_is(
        after, observed_version + 1, "entry after one change and one refusal"
    )

    # §2.9: the conserved seed sum still reflects two single-entry classes, so no
    # group was reseeded on behalf of the refused replay.
    event = fixtures.read_event(api, scenario.event_id)
    assert event["status"] == EVENT_SEEDED
    assert event["seeded_entry_count"] == 2
    assert_seed_integrity_sum(event, [1, 1], "event after the refused replay")


def test_current_entry_version_accepts_the_class_change_and_reseeds_both_groups(api):
    """The refused move lands unchanged once the current entry version is supplied.

    §2.7 describes the entry pin, like the wrestler pin, as a pure stale-version
    comparison, so the very body that was refused succeeds against the current
    ``version``.  §3.8 then reseeds both the vacated and the destination class group
    so each again holds a contiguous run beginning at 1, and §2.9 recomputes
    ``Event.seed_integrity_sum`` from the resulting groups.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_entry_version_rejected_then_accepted
    """
    scenario = _seeded_two_wrestler_bracket(api)
    observed_version = fixtures.read_entry(api, scenario.entry_b_id)["version"]

    fixtures.change_weight_class(
        api, scenario.entry_b_id, _FIRST_MOVE_CLASS_LBS, observed_version
    )
    validate_error(
        api.change_entry_weight_class(
            scenario.entry_b_id,
            factories.weight_class_change_payload(
                _SECOND_MOVE_CLASS_LBS, observed_version
            ),
            STATE_OFFICE,
        ),
        api_errors.ERR_STALE_ENTRY_VERSION,
        412,
    )

    current_version = fixtures.read_entry(api, scenario.entry_b_id)["version"]
    assert current_version == observed_version + 1, (
        "only the accepted change incremented the entry's version"
    )

    moved = validate_success(
        api.change_entry_weight_class(
            scenario.entry_b_id,
            factories.weight_class_change_payload(
                _SECOND_MOVE_CLASS_LBS, current_version
            ),
            STATE_OFFICE,
        ),
        200,
    )
    assert moved["weight_class_lbs"] == _SECOND_MOVE_CLASS_LBS
    assert moved["weight_class_change_count"] == 2
    assert moved["status"] == ENTRY_SEEDED, "the entry remains SEEDED throughout"
    assert moved["seed_number"] == 1, "the wrestler is alone in the destination class"
    assert_version_is(
        moved, observed_version + 2, "entry after two accepted changes"
    )

    # The other competitor was never named by either change and keeps the vacated
    # class, recontracted to a contiguous run beginning at 1.
    entry_a = fixtures.read_entry(api, scenario.entry_a_id)
    assert entry_a["weight_class_lbs"] == _ENTRY_CLASS_LBS
    assert entry_a["seed_number"] == 1
    assert entry_a["weight_class_change_count"] == 0
    assert entry_a["status"] == ENTRY_SEEDED

    event = fixtures.read_event(api, scenario.event_id)
    assert event["status"] == EVENT_SEEDED
    assert event["seeded_entry_count"] == 2
    assert_seed_integrity_sum(event, [1, 1], "event after the accepted retry")
    entry_rows, _meta = validate_paginated(
        api.list_entries(STATE_OFFICE, {"event_id": scenario.event_id, "limit": 100})
    )
    assert_seed_sum_matches_entries(event, entry_rows, "event after the accepted retry")


# ── §3.6: the cumulative breach threshold and its two candidate resets ──

def test_one_missed_milestone_below_the_breach_limit_leaves_the_plan_certified(api):
    """At the limit minus one the plan is judged and stays certified.

    §3.5 generates six milestones seven days apart from the plan start date.  With
    the clock at 2026-11-05 only week zero's ``effective_date`` is on or before the
    clock date, so §3.6 judges that one milestone and skips the rest.  No weigh-in
    exists, so the candidate set is empty and the milestone becomes ``MISSED`` with
    ``evaluated_recorded_weight_lbs`` still null.  One miss is strictly below the
    shipped ``plan_breach_limit`` of two, so the plan simply stays ``CERTIFIED`` and
    waits for the next sweep.

    Design: Corner/cross_cutting_complexity_layers/cumulative_breach_threshold_at_boundary_and_reset_semantics
    """
    scenario = fixtures.certified_wrestler(api)
    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT
    assert plan["missed_milestone_count"] == 0
    assert plan["breach_count"] == 0

    fixtures.move_clock(api, _FIRST_SWEEP_INSTANT)
    fixtures.run_compliance(api, scenario.season_id)

    swept = fixtures.read_plan(api, scenario.plan_id)
    assert swept["status"] == PLAN_CERTIFIED
    assert swept["missed_milestone_count"] == DEFAULT_PLAN_BREACH_LIMIT - 1
    assert swept["breach_count"] == 0

    rows = _milestone_rows(api, scenario.plan_id)
    assert len(rows) == WEEKLY_STEP_MILESTONE_COUNT
    assert rows[0]["status"] == MILESTONE_MISSED
    assert rows[0]["evaluated_recorded_weight_lbs"] is None, (
        "an empty candidate set is a miss with no recorded number"
    )
    for row in rows[1:]:
        assert row["status"] == MILESTONE_SCHEDULED, (
            "a milestone whose effective_date is still in the future is skipped"
        )
        assert row["evaluated_recorded_weight_lbs"] is None

    # Below the limit no breach happened, so §3.6 raised no plan-breach flag.
    assert _flag_rows(api, scenario.wrestler_id, FLAG_PLAN_BREACH) == []


def test_second_missed_milestone_breaches_the_plan_exactly_at_the_limit(api):
    """The threshold fires at two misses, because the comparison is inclusive.

    §3.6 recomputes ``missed_milestone_count`` from the plan's ``MISSED`` milestones
    after each sweep and moves the plan ``CERTIFIED -> BREACHED`` when that count
    *reaches or exceeds* the season's ``plan_breach_limit``.  With the shipped limit
    of two, the second sweep — which brings week one due and finds no weigh-in for
    it either — takes the count to exactly two and therefore breaches, incrementing
    ``breach_count`` by one.

    Design: Corner/cross_cutting_complexity_layers/cumulative_breach_threshold_at_boundary_and_reset_semantics
    """
    scenario = _breached_plan(api)

    first = scenario.after_first_sweep
    assert first["status"] == PLAN_CERTIFIED
    assert first["missed_milestone_count"] == DEFAULT_PLAN_BREACH_LIMIT - 1

    second = scenario.after_second_sweep
    assert second["status"] == PLAN_BREACHED
    assert second["missed_milestone_count"] == DEFAULT_PLAN_BREACH_LIMIT
    assert second["breach_count"] == 1

    rows = _milestone_rows(api, scenario.plan_id)
    assert len(rows) == WEEKLY_STEP_MILESTONE_COUNT
    for week_index in range(DEFAULT_PLAN_BREACH_LIMIT):
        assert rows[week_index]["week_index"] == week_index
        assert rows[week_index]["status"] == MILESTONE_MISSED
        assert rows[week_index]["evaluated_recorded_weight_lbs"] is None
    for week_index in range(DEFAULT_PLAN_BREACH_LIMIT, WEEKLY_STEP_MILESTONE_COUNT):
        assert_milestone(
            rows[week_index],
            week_index,
            WEEKLY_STEP_MILESTONE_DATES[week_index],
            _CANON_SCHEDULE[week_index],
            expected_min_eligible_class(
                _CANON_SCHEDULE[week_index], CANON_MINIMUM_CERTIFIED_WEIGHT_LBS
            ),
            MILESTONE_SCHEDULED,
            f"week {week_index} milestone",
        )


def test_revision_keeps_the_missed_count_and_the_next_sweep_rebreaches(api):
    """A revision returns the plan to certified without laundering the counter.

    §3.6 says ``missed_milestone_count`` is emphatically **not** reset by a revision:
    a breach that has happened stays on the record.  Milestones already ``MISSED``
    are left exactly where they are, every remaining ``SCHEDULED`` row whose
    ``effective_date`` is not strictly before the new start date is deleted, and the
    regenerated rows continue numbering from one greater than the highest
    ``week_index`` still present.  Because the retained count is still at the limit,
    the very next sweep re-breaches the plan without a single newly due milestone,
    which is what makes the counter cumulative rather than per-sweep.

    Design: Corner/cross_cutting_complexity_layers/cumulative_breach_threshold_at_boundary_and_reset_semantics
    """
    scenario = _breached_plan(api)

    revised = fixtures.revise_plan(
        api, scenario.plan_id, scenario.team_id, _REVISED_START_DATE
    )
    assert revised["status"] == PLAN_CERTIFIED
    assert revised["revision_count"] == 1
    assert revised["breach_count"] == 1
    assert revised["missed_milestone_count"] == DEFAULT_PLAN_BREACH_LIMIT, (
        "the revision must carry the accumulated misses forward unchanged"
    )
    assert revised["plan_start_date"] == _REVISED_START_DATE
    assert revised["plan_variant"] == VARIANT_WEEKLY_STEP, (
        "a revision that does not override the variant keeps the one it had"
    )
    assert revised["milestone_count"] == (
        DEFAULT_PLAN_BREACH_LIMIT + len(_CANON_SCHEDULE)
    )

    rows = _milestone_rows(api, scenario.plan_id)
    assert len(rows) == DEFAULT_PLAN_BREACH_LIMIT + len(_CANON_SCHEDULE)

    # The two judged rows are retained untouched.
    for week_index in range(DEFAULT_PLAN_BREACH_LIMIT):
        assert rows[week_index]["week_index"] == week_index
        assert rows[week_index]["status"] == MILESTONE_MISSED
        assert rows[week_index]["effective_date"] == WEEKLY_STEP_MILESTONE_DATES[
            week_index
        ]

    # No milestone was scheduled strictly before the new start date, so §3.6
    # waived none of them and every remaining scheduled row was deleted and
    # regenerated from the new start date, re-anchored on the unchanged baseline.
    for offset, allowable in enumerate(_CANON_SCHEDULE):
        week_index = DEFAULT_PLAN_BREACH_LIMIT + offset
        assert_milestone(
            rows[week_index],
            week_index,
            plus_weeks(_REVISED_START_DATE, offset),
            allowable,
            expected_min_eligible_class(
                allowable, CANON_MINIMUM_CERTIFIED_WEIGHT_LBS
            ),
            MILESTONE_SCHEDULED,
            f"regenerated row {offset}",
        )
    assert all(row["status"] != "WAIVED" for row in rows), (
        "waiving applies only to rows dated strictly before the new start date"
    )

    # The clock has not moved, so the next sweep finds nothing newly due — and
    # still re-breaches, on the strength of the retained count alone.
    fixtures.run_compliance(api, scenario.season_id)
    rebreached = fixtures.read_plan(api, scenario.plan_id)
    assert rebreached["status"] == PLAN_BREACHED
    assert rebreached["missed_milestone_count"] == DEFAULT_PLAN_BREACH_LIMIT
    assert rebreached["breach_count"] == 2

    after_rows = _milestone_rows(api, scenario.plan_id)
    for row in after_rows[DEFAULT_PLAN_BREACH_LIMIT:]:
        assert row["status"] == MILESTONE_SCHEDULED, (
            "no regenerated milestone had come due, so none was judged"
        )


def test_only_a_brand_new_plan_restarts_the_missed_milestone_counter(api):
    """A freshly opened plan starts its counters at zero; the old one keeps its history.

    §3.5 gives a newly opened plan ``milestone_count``, ``missed_milestone_count``,
    ``breach_count`` and ``revision_count`` all at zero, and moves the wrestler's
    prior non-terminal plan to ``CANCELLED`` with ``cancel_reason`` ``SUPERSEDED``
    while recording it in the new plan's ``supersedes_plan_id``.  The cancelled plan
    keeps the misses it accumulated and, being terminal, is no longer swept.  The
    breach flag §3.6 raised is dismissed first, because §3.9 makes that the declared
    compensating action on the team's severity ledger and §3.5 refuses to open a
    plan for a team on probation.

    Design: Corner/cross_cutting_complexity_layers/cumulative_breach_threshold_at_boundary_and_reset_semantics
    """
    scenario = _breached_plan(api)
    assert scenario.after_second_sweep["missed_milestone_count"] == (
        DEFAULT_PLAN_BREACH_LIMIT
    )

    flags = _flag_rows(api, scenario.wrestler_id, FLAG_PLAN_BREACH)
    assert len(flags) == 1, "the single breach raised exactly one plan-breach flag"
    dismissed = fixtures.review_flag(api, flags[0]["id"], FLAG_DISMISSED)
    assert dismissed["status"] == FLAG_DISMISSED

    replacement = fixtures.create_plan(
        api,
        scenario.wrestler_id,
        scenario.team_id,
        scenario.assessment_id,
        plan_start_date=_REPLACEMENT_START_DATE,
    )
    assert replacement["supersedes_plan_id"] == scenario.plan_id
    assert replacement["missed_milestone_count"] == 0
    assert replacement["breach_count"] == 0
    assert replacement["revision_count"] == 0
    assert replacement["milestone_count"] == 0

    certified = fixtures.certify_plan(api, replacement["id"])
    assert certified["status"] == PLAN_CERTIFIED
    assert certified["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT
    assert certified["missed_milestone_count"] == 0

    # The replacement's first milestone is not yet due, so the sweep judges nothing
    # and the fresh counter stays at zero.
    fixtures.run_compliance(api, scenario.season_id)
    swept = fixtures.read_plan(api, replacement["id"])
    assert swept["status"] == PLAN_CERTIFIED
    assert swept["missed_milestone_count"] == 0
    assert swept["breach_count"] == 0

    superseded = fixtures.read_plan(api, scenario.plan_id)
    assert superseded["status"] == PLAN_CANCELLED
    assert superseded["cancel_reason"] == CANCEL_REASON_SUPERSEDED
    assert superseded["missed_milestone_count"] == DEFAULT_PLAN_BREACH_LIMIT, (
        "a terminal plan keeps its history rather than being laundered"
    )
