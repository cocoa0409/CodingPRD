"""Inclusive and strict comparisons walked one unit either side of the line.

The coverage gate is inclusive, so the boundary value must be admitted; the
clearance escalation is strict, so the identical boundary value must be refused.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LEGAL_COUNSEL_HEADERS,
    STUDIO_EXECUTIVE_HEADERS,
)

TARGET_OF_TWO = {"ready_script_target": 2}

SECOND_EPISODE = {
    "episode_number": 2,
    "production_unit": "UNIT_B",
    "production_start_date": "2026-11-16T00:00:00Z",
}

OFFICER_NOTE = "Confirm no serving officer shares the name."
HOSPITAL_NOTE = "Signage must be redressed before the location day."


def _two_ready_episodes(api):
    """Episode one is ready and cleared; episode two is ready but uncleared."""
    world = X.build_cleared_world(api, season_overrides=TARGET_OF_TWO)
    ep2 = X.seed_episode(
        api,
        world["season_id"],
        2,
        production_unit=SECOND_EPISODE["production_unit"],
        production_start_date=SECOND_EPISODE["production_start_date"],
    )
    world["ep2_id"] = ep2["id"]
    a2 = X.seed_assignment(
        api, ep2["id"], world["w1_id"], world["sr_headers"], "TELEPLAY"
    )
    world["a2_id"] = a2["id"]
    X.deliver_all(api, a2["id"], world["w1_id"])
    world["a2"] = X.approve_assignment(api, a2["id"])
    world["a2_milestones"] = X.milestones_of(api, a2["id"])
    return world


def _clear_the_second_episode(api, world):
    """Open a review over episode two's approved teleplay and clear its one item."""
    review = X.seed_clearance_review(
        api, world["a2_id"], world["a2_milestones"][-1]["id"]
    )
    item = X.seed_clearance_item(
        api, review["id"], "NAME", "Harbor Mercy Hospital", "2C"
    )
    X.decide_item(api, item["id"], "CLEARED")
    return review["id"]


def _score_of_thirty(api):
    """A review on a drafting teleplay holding two conditional items worth 30."""
    world = X.build_assignment_world(api)
    outline_id = world["a1_milestone_ids"][0]
    X.deliver_milestone(api, outline_id, world["w1_id"])
    review = X.seed_clearance_review(api, world["a1_id"], outline_id)
    world["review_id"] = review["id"]
    name_item = X.seed_clearance_item(
        api, review["id"], "NAME", "Character surname Kowalczyk", "1A"
    )
    X.decide_item(api, name_item["id"], "CONDITIONAL", HOSPITAL_NOTE)
    depiction_item = X.seed_clearance_item(
        api, review["id"], "DEPICTION", "Real hospital shown mid-malpractice", "3B"
    )
    X.decide_item(api, depiction_item["id"], "CONDITIONAL", HOSPITAL_NOTE)
    world["review"] = X.read_review(api, review["id"])
    return world


def _escalated_review(api):
    """A third conditional name item takes the same review one notch past 30."""
    world = _score_of_thirty(api)
    third = X.seed_clearance_item(
        api, world["review_id"], "NAME", "Officer Dana Pike", "4A"
    )
    X.decide_item(api, third["id"], "CONDITIONAL", OFFICER_NOTE)
    world["review"] = X.read_review(api, world["review_id"])
    return world


def test_the_lock_is_refused_one_ready_script_short_of_the_target(api):
    """A count of one against a target of two fails the inclusive comparison.

    PRD: "Third the coverage gate: the season's `ready_script_count`, counting this episode's own contribution, must be at or above `ready_script_target`, otherwise `ERR_SCRIPT_COVERAGE_INSUFFICIENT`."

    PRD: "An episode with an approved teleplay but a `PENDING`, `CONDITIONAL`, `ESCALATED` or `BLOCKED` clearance posture does not count, and neither does a fully cleared episode whose script is only `NOT_STARTED` or `IN_PROGRESS`."

    Design: Difficulty/boundary_precision_check/coverage_gate_admits_exactly_ready_script_target_inclusive
    """
    world = _two_ready_episodes(api)
    A.assert_field_values(
        X.read_episode(api, world["ep2_id"]),
        script_readiness="READY",
        clearance_posture="PENDING",
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=1,
        coverage_gap=1,
        coverage_posture="AT_RISK",
    )

    validate_error(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.SCRIPT_COVERAGE_INSUFFICIENT,
    )

    A.assert_field_values(
        X.read_episode(api, world["ep1_id"]),
        script_readiness="READY",
        clearance_posture="CLEARED",
        locked_at=None,
    )


def test_the_lock_is_admitted_at_exactly_the_ready_script_target(api):
    """Clearing the second episode lands the count on the target and opens the gate.

    PRD: "The comparison is inclusive: a season whose target is 6 may lock when the count reaches exactly 6, and the episode being locked is included in the count because it is already `READY` and cleared when the gate is evaluated."

    PRD: "A successful lock sets `script_readiness` to `LOCKED`, stamps `locked_at` from the logical clock, recomputes the season's coverage figures and increments the episode's `version`."

    PRD: "Locked episodes keep counting — locking never lowers coverage."

    Design: Difficulty/boundary_precision_check/coverage_gate_admits_exactly_ready_script_target_inclusive
    """
    world = _two_ready_episodes(api)
    _clear_the_second_episode(api, world)

    A.assert_field_values(
        X.read_episode(api, world["ep2_id"]), clearance_posture="CLEARED"
    )
    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=2,
        coverage_gap=0,
        coverage_posture="COVERED",
    )

    before_version = X.read_episode(api, world["ep1_id"])["version"]
    locked = validate_success(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS)
    )
    A.assert_field_values(
        locked,
        script_readiness="LOCKED",
        version=before_version + 1,
    )
    A.assert_instant(locked["locked_at"], K.CLOCK_EPOCH, "locked_at")

    A.assert_field_values(
        X.read_season(api, world["season_id"]),
        ready_script_count=2,
        coverage_gap=0,
        coverage_posture="COVERED",
    )

    validate_error(
        api.lock_episode_for_production(world["ep1_id"], STUDIO_EXECUTIVE_HEADERS),
        ApiErrorId.EPISODE_ALREADY_LOCKED,
    )


def test_a_risk_score_of_exactly_thirty_does_not_escalate_but_thirty_five_does(api):
    """Five and twenty-five sit on the threshold; one more name crosses it.

    PRD: "`ESCALATED` when the `risk_score` is *strictly greater* than the agreement's `clearance_escalation_score` (default 30). A score exactly equal to the escalation score does not escalate."

    PRD: "The review's `risk_score` is then the sum of `risk_weight` over its items whose `decision` is `CLEARED`, `CONDITIONAL` or `BLOCKED`, capped at 100 — the cap applies to the sum, not to any individual weight — and `decided_item_count` is the count of those same items."

    Design: Difficulty/boundary_precision_check/clearance_escalation_at_exactly_thirty_stays_conditional_then_crosses_and_caps
    """
    world = _score_of_thirty(api)
    A.assert_field_values(
        world["review"],
        risk_score=30,
        posture="CONDITIONAL",
        item_count=2,
        decided_item_count=2,
    )

    third = validate_success(
        api.create_clearance_item(
            world["review_id"],
            F.build_clearance_item("NAME", "Officer Dana Pike", "4A"),
            LEGAL_COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(third, decision="SUBMITTED", risk_weight=0)
    A.assert_field_values(
        X.read_review(api, world["review_id"]), risk_score=30, posture="CONDITIONAL"
    )

    validate_success(
        api.decide_clearance_item(
            third["id"],
            F.build_item_decision("CONDITIONAL", OFFICER_NOTE),
            LEGAL_COUNSEL_HEADERS,
        )
    )
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        risk_score=35,
        posture="ESCALATED",
        item_count=3,
        decided_item_count=3,
    )


def test_a_blocked_item_caps_the_score_at_one_hundred_and_pins_the_posture(api):
    """A raw sum of 135 is reported as 100, and BLOCKED outranks the score ladder.

    PRD: "The decision sets the item's `risk_weight` to the agreement's `clearance_item_weights` entry for the item's `item_type` multiplied by a decision multiplier of 0 for `CLEARED`, 1 for `CONDITIONAL` and 4 for `BLOCKED`."

    PRD: "`BLOCKED` when any item's `decision` is `BLOCKED`, whatever the score."

    PRD: "A new item's `decision` is `SUBMITTED`, its `conditional_note` is null, and its `risk_weight` is 0 — an undecided item carries no risk weight even though its type already implies one."

    Design: Difficulty/boundary_precision_check/clearance_escalation_at_exactly_thirty_stays_conditional_then_crosses_and_caps
    """
    world = _escalated_review(api)
    A.assert_field_values(world["review"], risk_score=35, posture="ESCALATED")

    fourth = validate_success(
        api.create_clearance_item(
            world["review_id"],
            F.build_clearance_item(
                "DEPICTION",
                "Named living public figure shown committing a crime",
                "5E",
            ),
            LEGAL_COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        item_count=4,
        decided_item_count=3,
        risk_score=35,
        posture="ESCALATED",
    )

    decided = validate_success(
        api.decide_clearance_item(
            fourth["id"], F.build_item_decision("BLOCKED"), LEGAL_COUNSEL_HEADERS
        )
    )
    A.assert_field_values(decided, risk_weight=100, conditional_note=None)
    A.assert_field_values(
        X.read_review(api, world["review_id"]),
        risk_score=100,
        posture="BLOCKED",
        item_count=4,
        decided_item_count=4,
    )

    validate_error(
        api.grant_clearance_waiver(
            world["review_id"], F.build_waiver(), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.WAIVER_NOT_APPLICABLE,
    )
    validate_error(
        api.decide_clearance_item(
            fourth["id"], F.build_item_decision("CLEARED"), LEGAL_COUNSEL_HEADERS
        ),
        ApiErrorId.ITEM_ALREADY_DECIDED,
    )
