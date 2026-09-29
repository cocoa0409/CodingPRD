"""
Immediate, hierarchically consistent cascade visibility.

§2.10 of the requirements declares the consistency model this service runs on:
every hop of a cascade is applied within the same request, immediately and
completely, before the response is emitted.  There is no deferred or eventual
reconciliation, a partially applied cascade is never a valid outcome, each row a
cascade touches has its ``updated_at`` refreshed and its ``version``
incremented, and every derived counter on a parent row is brought current in the
same request.

The chain exercised below is the one §3.4 specifies for an upheld appeal: a
single ``POST /appeals/{id}/decide`` request voids the contested assessment,
repoints the wrestler at the retest and recomputes its certified figures,
cancels the descent plan whose target has fallen below the newly raised minimum
class, and scratches the wrestler's live tournament entry.  Four entities the
request body never names are rewritten, and §2.10 requires that the reads taken
straight afterwards — with no intervening write, no retry and no delay — already
show every one of them, including the filtered list projections §2.10 nominates
as the discovery channel for cascade-touched rows.

The mirror-image obligation matters just as much: immediate visibility must not
be confused with over-cascading.  §3.4 enumerates exactly the hops an upheld
appeal takes, so the rows outside that enumeration — the producing assessor's
credential and the wrestler's certification dimension — must read exactly as
they did before the decision.

Every precondition is built through the declared endpoints, because the service
starts each test against an empty database with the logical clock at its start
instant.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_row_count,
    assert_weight_equals,
    expected_minimum_certified_weight,
    smallest_class_at_or_above,
)
from test_helpers.constants import (
    APPEAL_RETEST_COMPLETED,
    APPEAL_UPHELD,
    ASSESSMENT_VALIDATED,
    ASSESSMENT_VOIDED,
    ASSESSOR_CERTIFIED,
    CANCEL_REASON_MINIMUM_RAISED,
    CANON_TARGET_CLASS_LBS,
    DEFAULT_MIN_BODY_FAT_PCT_MALE,
    ENTRY_ENTERED,
    ENTRY_SCRATCHED,
    METHOD_SKINFOLD,
    PLAN_CANCELLED,
    PLAN_CERTIFIED,
    SCRATCH_REASON_PLAN_CANCELLED,
    VOID_REASON_APPEAL_UPHELD_PREFIX,
    WRESTLER_CERTIFIED,
)
from test_helpers.test_users import STATE_OFFICE, assessor_headers

# ── The reviewing assessor, who may not be the one who measured ──────
# §3.4 makes segregation of duties structural: the reviewing assessor must not
# be the assessor who produced the contested assessment, and §3.3 forbids that
# same assessor from performing the appeal-ordered retest.
_REVIEWER_NAME = "Priya Nair"
_REVIEWER_CREDENTIAL = "AS-1002"

# The retest reading.  Under §3.3 a 165.0 pound measurement at 8.0 percent body
# fat yields a lean weight of 151.8 pounds and, divided by one minus the 7.0
# percent male floor, a minimum certified weight of 163.2 pounds, whose smallest
# admitting class on the shipped ladder is 165 — strictly above the plan's
# target of 150, which is exactly what arms §3.4's third hop.
_RETEST_ASSESSED_AT = "2026-11-01T15:00:00Z"
_RETEST_WEIGHT_LBS = 165.0
_RETEST_BODY_FAT_PCT = 8.0
_RETEST_USG = 1.018

# The competition the wrestler is entered into before the retest lands, so the
# entry is admissible at 150 when it is created and becomes the tail of the
# cascade once the minimum is raised.
_EVENT_NAME = "State Qualifier"
_EVENT_DATE = "2026-12-12"
_EVENT_SEASON_WINS = 4

_APPEAL_REASON = "Skinfold caliper sites disputed"
_DECISION_NOTE = "Retest supersedes the disputed skinfold reading"


def _expected_retest_minimum() -> float:
    """The retest's minimum certified weight, by §3.3's pinned rounding order."""
    return expected_minimum_certified_weight(
        _RETEST_WEIGHT_LBS, _RETEST_BODY_FAT_PCT, DEFAULT_MIN_BODY_FAT_PCT_MALE
    )


def _expected_retest_class() -> int:
    """The smallest ladder member at or above that minimum, inclusively."""
    return smallest_class_at_or_above(_expected_retest_minimum())


# ── The world one upheld decision cascades through ────────────────────

def _upheld_fork_world(api: ApiClient) -> fixtures.Scenario:
    """Everything the requirements need in place for §3.4's upheld cascade.

    An open season with one team; the measuring assessor and a second assessor
    both trained past the season's credentialing threshold; a wrestler certified
    from the measuring assessor's 159.6 pound, 14.0 percent reading, whose
    minimum class is therefore 150; a certified compounding descent plan
    targeting 150; and a live entry at 150 in a tournament dated 2026-12-12.
    On top of that the coach's appeal against the contested assessment has been
    assigned to the second assessor, a retest has been ordered, and that
    reviewer's 165.0 pound, 8.0 percent retest has been finalized — which
    §3.3 records on the appeal as ``retest_assessment_id`` while moving it to
    RETEST_COMPLETED, and which deliberately leaves the contested assessment in
    VALIDATED so the upheld from-state still exists.
    """
    scenario = fixtures.certified_wrestler(api)

    reviewer = fixtures.create_certified_assessor(
        api,
        full_name=_REVIEWER_NAME,
        credential_number=_REVIEWER_CREDENTIAL,
        certified_methods=[METHOD_SKINFOLD],
    )

    event = fixtures.create_event(api, scenario.season_id, _EVENT_NAME, _EVENT_DATE)
    entry = fixtures.create_entry(
        api,
        event["id"],
        scenario.wrestler_id,
        scenario.team_id,
        CANON_TARGET_CLASS_LBS,
        season_win_count=_EVENT_SEASON_WINS,
    )

    appeal = fixtures.file_appeal(
        api, scenario.assessment_id, scenario.team_id, _APPEAL_REASON
    )
    fixtures.assign_reviewer(api, appeal["id"], reviewer["id"])
    fixtures.order_retest(api, appeal["id"], reviewer["id"])

    retest_draft = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        reviewer["id"],
        method=METHOD_SKINFOLD,
        assessed_at=_RETEST_ASSESSED_AT,
        measured_weight_lbs=_RETEST_WEIGHT_LBS,
        body_fat_pct=_RETEST_BODY_FAT_PCT,
        urine_specific_gravity=_RETEST_USG,
        appeal_id=appeal["id"],
        retest_of_assessment_id=scenario.assessment_id,
    )
    retest = fixtures.finalize_assessment(api, retest_draft["id"], reviewer["id"])

    scenario.update(
        reviewer=reviewer,
        reviewer_id=reviewer["id"],
        event=event,
        event_id=event["id"],
        entry_id=entry["id"],
        appeal_id=appeal["id"],
        retest=retest,
        retest_id=retest["id"],
        # The reads taken at the fork, before any decision is made.
        appeal_before=fixtures.read_appeal(api, appeal["id"]),
        contested_before=fixtures.read_assessment(api, scenario.assessment_id),
        plan_before=fixtures.read_plan(api, scenario.plan_id),
        entry_before=fixtures.read_entry(api, entry["id"]),
    )
    return scenario


def _decide_upheld(api: ApiClient, scenario: fixtures.Scenario) -> Dict[str, Any]:
    """The single declared request that fires the whole chain."""
    return validate_success(
        api.decide_appeal(
            scenario.appeal_id,
            factories.appeal_decision_payload(APPEAL_UPHELD, _DECISION_NOTE),
            assessor_headers(scenario.reviewer_id),
        )
    )


# ── The fork the single decision is taken from ────────────────────────

def test_the_fixture_sits_exactly_at_the_upheld_fork_before_any_decision(
    api: ApiClient,
) -> None:
    """Nothing has cascaded yet: the whole chain is still ahead of the decision.

    §3.4 accepts an UPHELD outcome only out of RETEST_COMPLETED and only when the
    retest assessment recorded on the appeal is itself VALIDATED, and §3.3 makes
    that possible by exempting the assessment an appeal contests from the
    ordinary supersession sweep — an appeal-ordered retest leaves the contested
    reading in VALIDATED precisely so the upheld void cascade still has a
    from-state to work with.  Reading the four rows before the decision therefore
    has to show a live appeal at the fork, a validated contested assessment, a
    certified plan and an entered competitor: no hop of §3.4's chain may have run
    early.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)

    assert scenario.appeal_before["status"] == APPEAL_RETEST_COMPLETED
    assert scenario.appeal_before["retest_assessment_id"] == scenario.retest_id
    assert scenario.appeal_before["decision_note"] is None
    assert scenario.contested_before["status"] == ASSESSMENT_VALIDATED, (
        "a retest carrying an appeal_id does not supersede the assessment it "
        "contests, so the upheld from-state still exists"
    )
    assert scenario.contested_before["void_reason"] is None
    assert scenario.plan_before["status"] == PLAN_CERTIFIED
    assert scenario.plan_before["cancel_reason"] is None
    assert scenario.entry_before["status"] == ENTRY_ENTERED
    assert scenario.entry_before["scratch_reason"] is None


def test_the_retest_raises_the_minimum_class_that_arms_the_third_hop(
    api: ApiClient,
) -> None:
    """The retest's own figures are what make the plan cancellation inevitable.

    §3.3 computes the retest's lean body weight as the measured weight times one
    minus the fat fraction, rounded to one decimal place, and its minimum
    certified weight as that already-rounded lean weight divided by one minus the
    male body-fat floor, rounded again; the minimum weight class is then the
    smallest ladder member at or above that minimum.  A 165.0 pound reading at
    8.0 percent therefore certifies no lower than 165, strictly above the plan's
    target of 150 — which is the condition §3.4's third hop tests.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)

    assert scenario.retest["status"] == ASSESSMENT_VALIDATED
    assert_weight_equals(
        scenario.retest["minimum_certified_weight_lbs"],
        _expected_retest_minimum(),
        "the retest's minimum_certified_weight_lbs",
    )
    assert scenario.retest["min_weight_class_lbs"] == _expected_retest_class()
    assert scenario.plan_before["target_class_lbs"] < _expected_retest_class(), (
        "the plan's target has fallen strictly below the newly certified minimum "
        "class, which is what the third hop cancels a plan for"
    )


def test_the_deciding_response_alone_carries_the_terminal_appeal(api: ApiClient) -> None:
    """One request, one response, and the outcome is already observable in it.

    §4 has an action endpoint return the mutated primary resource, and §3.4 makes
    both UPHELD and DENIED terminal while recording the supplied decision note
    and incrementing the appeal's version.  §2.10 forbids any deferred step, so
    the decide response itself — with no follow-up read at all — must already show
    the appeal in its terminal state carrying the note it was decided with.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)

    decided = _decide_upheld(api, scenario)

    assert decided["id"] == scenario.appeal_id
    assert decided["status"] == APPEAL_UPHELD
    assert decided["decision_note"] == _DECISION_NOTE
    assert decided["version"] == scenario.appeal_before["version"] + 1, (
        "the decision is one mutation of the appeal row, so its version "
        "increments by exactly one"
    )


# ── Every hop, visible on the first read after the decision ───────────

def test_hop_one_void_is_visible_on_the_first_read_with_no_retry(api: ApiClient) -> None:
    """The contested assessment is already voided when it is next read.

    §3.4's first hop moves the contested assessment from VALIDATED to VOIDED and
    stamps its void reason as ``APPEAL_UPHELD:`` followed by the appeal's id.
    §2.10 applies that hop within the deciding request, immediately and
    completely, and refreshes the row's version exactly as a directly addressed
    mutation would — so a single read taken straight afterwards, with no
    intervening write and no second attempt, must show the void already done.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)

    _decide_upheld(api, scenario)

    contested = fixtures.read_assessment(api, scenario.assessment_id)
    assert contested["status"] == ASSESSMENT_VOIDED
    assert contested["void_reason"] == (
        VOID_REASON_APPEAL_UPHELD_PREFIX + scenario.appeal_id
    )
    assert contested["version"] == scenario.contested_before["version"] + 1


def test_hop_two_repoints_the_wrestler_in_the_same_request(api: ApiClient) -> None:
    """The wrestler's certified figures already come from the retest.

    §3.4's second hop fires because the contested assessment was voided: the
    wrestler's source pointer is repointed at the appeal's retest assessment and
    every certified figure — the descent baseline, the body-fat percentage, the
    minimum certified weight and the minimum weight class — is recomputed from
    that retest.  §2.10 leaves no window in which the wrestler still points at the
    voided reading, so the first read after the decision carries the new figures
    and a single version increment.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)
    wrestler_before = fixtures.read_wrestler(api, scenario.wrestler_id)

    _decide_upheld(api, scenario)

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["source_assessment_id"] == scenario.retest_id
    assert_weight_equals(
        wrestler["alpha_weight_lbs"], _RETEST_WEIGHT_LBS, "alpha_weight_lbs"
    )
    assert_weight_equals(
        wrestler["body_fat_pct"], _RETEST_BODY_FAT_PCT, "body_fat_pct"
    )
    assert_weight_equals(
        wrestler["minimum_certified_weight_lbs"],
        _expected_retest_minimum(),
        "minimum_certified_weight_lbs",
    )
    assert wrestler["min_weight_class_lbs"] == _expected_retest_class()
    assert wrestler["version"] == wrestler_before["version"] + 1


def test_hop_three_cancels_the_plan_inside_the_deciding_request(api: ApiClient) -> None:
    """The plan whose target fell below the raised minimum is already cancelled.

    §3.4's third hop fires because the wrestler's minimum weight class may have
    moved upward: any descent plan of that wrestler in CERTIFIED or BREACHED whose
    target class is now strictly below the new minimum class is cancelled with a
    cancel reason of ``MINIMUM_RAISED``.  The plan targeted 150 and the retest
    raised the minimum class to 165, so §2.10's prohibition on a partially applied
    cascade means the plan must read cancelled the very first time it is fetched.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)

    _decide_upheld(api, scenario)

    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["status"] == PLAN_CANCELLED
    assert plan["cancel_reason"] == CANCEL_REASON_MINIMUM_RAISED
    assert plan["version"] == scenario.plan_before["version"] + 1


def test_the_entry_scratch_is_visible_in_the_same_breath(api: ApiClient) -> None:
    """The tail of the chain has landed too, not just its head.

    §3.4's fourth hop fires because the plan was cancelled: every tournament entry
    of that wrestler sitting in ENTERED or WEIGHED_IN moves to SCRATCHED with a
    scratch reason of ``PLAN_CANCELLED``.  This is the hop furthest from the row
    the request named, which is exactly why §2.10 insists a cascade is applied
    completely before the response is emitted — the entry is already scratched
    when the entry endpoint is next asked, with no reconciliation step in between.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)

    _decide_upheld(api, scenario)

    entry = fixtures.read_entry(api, scenario.entry_id)
    assert entry["status"] == ENTRY_SCRATCHED
    assert entry["scratch_reason"] == SCRATCH_REASON_PLAN_CANCELLED
    assert entry["version"] == scenario.entry_before["version"] + 1


# ── Immediate must not be confused with over-cascading ────────────────

def test_immediate_visibility_does_not_spill_past_the_declared_hops(
    api: ApiClient,
) -> None:
    """The rows outside §3.4's enumeration read exactly as they did before.

    §3.4 gives the upheld chain exactly four hops, and the only assessor bookkeeping
    inside it is the increment of the producing assessor's voided-assessment count
    — which §3.2 defines as the count of that assessor's assessments in VOIDED.
    Losing a credential belongs to the audit chain and to administrative
    suspension, not to an upheld appeal, so the measuring assessor is still
    certified afterwards.  Nor does any hop touch the wrestler's certification
    dimension, and because §2.5 derives the season's certified-wrestler counter
    from the wrestlers whose certification dimension currently reads CERTIFIED,
    that counter is unmoved as well.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)
    season_before = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season_before["certified_wrestler_count"] == 1

    _decide_upheld(api, scenario)

    assessor = fixtures.read_assessor(api, scenario.assessor_id)
    assert assessor["voided_assessment_count"] == 1
    assert assessor["status"] == ASSESSOR_CERTIFIED, (
        "an upheld appeal voids one assessment but never suspends the assessor"
    )

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED

    season = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 1


# ── The list projections are consistent immediately too ───────────────

def test_filtered_list_projections_agree_with_the_cascade_immediately(
    api: ApiClient,
) -> None:
    """Every listing the requirements nominate already reflects the whole chain.

    §2.10 makes the filtered listings the discovery channel for rows a cascade
    rewrote without the caller naming them, and there is no separate projection
    step: §3.5's plan listing narrowed to CANCELLED must already return the
    cancelled plan, §3.7's entry listing narrowed to SCRATCHED must already return
    the scratched entry, and §3.3's assessment listing narrowed to VOIDED must
    already return the voided contested reading — each with a total count that
    counts the rows matching the filter.

    Design: Corner/consistency_model/immediate_consistency_every_cascade_hop_visible_without_re_reading
    """
    scenario = _upheld_fork_world(api)

    _decide_upheld(api, scenario)

    cancelled = assert_row_count(
        api.list_descent_plans(
            STATE_OFFICE,
            {"wrestler_id": scenario.wrestler_id, "status": PLAN_CANCELLED},
        ),
        1,
        "cancelled plans of the wrestler",
    )
    assert cancelled[0]["id"] == scenario.plan_id
    assert cancelled[0]["cancel_reason"] == CANCEL_REASON_MINIMUM_RAISED

    scratched = assert_row_count(
        api.list_entries(
            STATE_OFFICE,
            {"event_id": scenario.event_id, "status": ENTRY_SCRATCHED},
        ),
        1,
        "scratched entries of the event",
    )
    assert scratched[0]["id"] == scenario.entry_id

    voided = assert_row_count(
        api.list_assessments(
            STATE_OFFICE,
            {"wrestler_id": scenario.wrestler_id, "status": ASSESSMENT_VOIDED},
        ),
        1,
        "voided assessments of the wrestler",
    )
    assert voided[0]["id"] == scenario.assessment_id
