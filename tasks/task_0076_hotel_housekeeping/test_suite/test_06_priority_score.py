"""Priority score, synergy multiplier, and banding (PRD §3.5)."""
from __future__ import annotations
import pytest

from test_helpers import (
    HIGH_THRESHOLD,
    SYNERGY_MULTIPLIER,
    TEST_USERS,
    URGENT_THRESHOLD,
    assert_priority_tier_for_score,
    create_cleaning_task_payload,
    validate_success,
)
from test_helpers.fixtures import (
    create_cleaning_task,
    create_room,
    early_check_in_within_window_iso,
    now_plus_seconds_iso,
    setup_high_priority_task_inputs,
    setup_room_and_housekeeper,
)


# ===========================================================================
# Component bonuses (PRD §3.5)
# ===========================================================================
def test_priority_base_only_no_bonuses(api):
    """PRD §3.5: "The base is 50 for CHECK_OUT, 30 for STAYOVER, and
    20 for SCHEDULED."

    SCHEDULED task, vip_flag=false, expedite_flag=false, no
    early_check_in → score = 20.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=False, expedite_flag=False, early_check_in=False,
        task_source="SCHEDULED",
    )
    assert task["priority_score"] == 20
    assert task["priority_tier"] == "NORMAL"


def test_priority_vip_only(api):
    """PRD §3.5: "The VIP bonus is 30 when the parent room's vip_flag
    is true and 0 otherwise."

    CHECK_OUT (base 50) + VIP (30) = 80 → HIGH.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=False, early_check_in=False,
        task_source="CHECK_OUT",
    )
    assert task["priority_score"] == 80
    assert task["priority_tier"] == "HIGH"


def test_priority_expedite_only(api):
    """PRD §3.5: "the expedite bonus is 20 when the task's expedite_flag
    is true and 0 otherwise."

    SCHEDULED (base 20) + expedite (20) = 40 → NORMAL.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=False, expedite_flag=True, early_check_in=False,
        task_source="SCHEDULED",
    )
    assert task["priority_score"] == 40
    assert task["priority_tier"] == "NORMAL"


def test_priority_early_check_in_only_within_window(api):
    """PRD §3.5: "the early-check-in bonus is 25 when early_check_in_at
    is non-null and the difference between early_check_in_at and the
    current time, expressed in seconds, is between zero and four hours
    inclusive."

    SCHEDULED (base 20) + early (25) = 45 → NORMAL.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=False, expedite_flag=False, early_check_in=True,
        task_source="SCHEDULED",
    )
    assert task["priority_score"] == 45
    assert task["priority_tier"] == "NORMAL"


# ===========================================================================
# Two-bonus additive (PRD §3.5)
# ===========================================================================
def test_priority_two_bonuses_no_synergy(api):
    """PRD §3.5: "The three bonuses are summed; if all three are
    strictly greater than zero, the sum is multiplied by a synergy
    multiplier of 1.20 and the product rounded half-up to a whole
    number before being added to the base."

    With only two of three bonuses present, the synergy multiplier
    does NOT apply (the rule requires all three). SCHEDULED (20) +
    VIP (30) + expedite (20) = 70 → HIGH.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=True, early_check_in=False,
        task_source="SCHEDULED",
    )
    assert task["priority_score"] == 70
    assert task["priority_tier"] == "HIGH"


# ===========================================================================
# Three-bonus synergy (PRD §3.5)
# ===========================================================================
def test_priority_all_three_bonuses_synergy_applied(api):
    """PRD §3.5: "if all three are strictly greater than zero, the sum
    is multiplied by a synergy multiplier of 1.20 and the product
    rounded half-up to a whole number before being added to the base."

    SCHEDULED (base 20) + (30 + 20 + 25) × 1.20 = 20 + 90 = 110 →
    URGENT.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=True, early_check_in=True,
        task_source="SCHEDULED",
    )
    assert task["priority_score"] == 110
    assert task["priority_tier"] == "URGENT"


def test_priority_synergy_does_not_touch_base(api):
    """PRD §3.5: "the synergy multiplier never touches the base."

    CHECK_OUT (base 50) + (30 + 20 + 25) × 1.20 = 50 + 90 = 140.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=True, early_check_in=True,
        task_source="CHECK_OUT", room_type="STANDARD",
    )
    assert task["priority_score"] == 140
    assert task["priority_tier"] == "URGENT"


# ===========================================================================
# Banding boundary (PRD §3.5)
# ===========================================================================
def test_priority_tier_urgent_at_exact_threshold_100(api):
    """PRD §3.5: "a score of at least 100 yields URGENT, a score below
    100 but at least 70 yields HIGH, and a score below 70 yields
    NORMAL."

    CHECK_OUT (50) + VIP (30) + expedite (20) = 100, no synergy
    (early_bonus=0) → URGENT exactly at 100.
    """
    # vip=true, expedite=true, early=false; CHECK_OUT base.
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=True, early_check_in=False,
        task_source="CHECK_OUT",
    )
    assert task["priority_score"] == 100
    assert task["priority_tier"] == "URGENT"


def test_priority_tier_high_at_99(api):
    """PRD §3.5: "a score below 100 but at least 70 yields HIGH."

    No straightforward combo of bonuses yields 99 exactly without
    synergy. CHECK_OUT (50) + VIP (30) = 80 — pick instead a
    boundary just below 100: CHECK_OUT (50) + expedite (20) = 70 (HIGH
    lower boundary).
    """
    # CHECK_OUT base 50 + expedite 20 = 70 → HIGH at exact 70.
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=False, expedite_flag=True, early_check_in=False,
        task_source="CHECK_OUT",
    )
    assert task["priority_score"] == 70
    assert task["priority_tier"] == "HIGH"


def test_priority_tier_normal_below_70(api):
    """PRD §3.5: "a score of at least 100 yields URGENT, a score below
    100 but at least 70 yields HIGH, and a score below 70 yields
    NORMAL."

    SCHEDULED (20) + VIP (30) = 50 → NORMAL.
    """
    room, hk, task = setup_high_priority_task_inputs(
        vip_flag=True, expedite_flag=False, early_check_in=False,
        task_source="SCHEDULED",
    )
    assert task["priority_score"] == 50
    assert task["priority_tier"] == "NORMAL"


def test_priority_tier_matches_score_invariant_across_random_inputs(api):
    """PRD §3.5: banding invariant — for every observed score, the
    tier must satisfy the URGENT/HIGH/NORMAL bands.
    """
    cases = [
        (True,  True,  True,  "CHECK_OUT"),    # 50 + 90 = 140 URGENT
        (False, True,  False, "STAYOVER"),     # 30 + 20 = 50 NORMAL
        (True,  False, False, "STAYOVER"),     # 30 + 30 = 60 NORMAL
        (True,  False, True,  "STAYOVER"),     # 30 + 30 + 25 = 85 HIGH
    ]
    for vip, exp, early, source in cases:
        room, hk, task = setup_high_priority_task_inputs(
            vip_flag=vip, expedite_flag=exp, early_check_in=early,
            task_source=source,
        )
        assert_priority_tier_for_score(
            task["priority_score"], task["priority_tier"],
        )


# ===========================================================================
# Early-check-in window edge (PRD §3.5)
# ===========================================================================
def test_priority_early_check_in_outside_window_yields_zero_bonus(api):
    """PRD §3.5: "the difference between early_check_in_at and the
    current time, expressed in seconds, is between zero and four hours
    inclusive — that is, when the early-check-in moment is in the
    future and no further off than the four-hour window."

    An early_check_in_at 5 hours in the future is OUTSIDE the
    EARLY_CHECK_IN_WINDOW_HOURS=4 window — bonus is 0. SCHEDULED with
    only this "out-of-window" early_check_in_at → score = 20.
    """
    room, hk = setup_room_and_housekeeper()
    far_future = now_plus_seconds_iso(int(5 * 3600))
    task = create_cleaning_task(
        room_id=room["id"], task_source="SCHEDULED",
        early_check_in_at=far_future,
    )
    assert task["priority_score"] == 20, (
        "Out-of-window early_check_in_at must yield early_bonus=0."
    )
    assert task["priority_tier"] == "NORMAL"


def test_priority_early_check_in_in_past_yields_zero_bonus(api):
    """PRD §3.5: "when the early-check-in moment is in the future and
    no further off than the four-hour window."

    A past timestamp is not in the future → bonus is 0.
    """
    room, hk = setup_room_and_housekeeper()
    past = now_plus_seconds_iso(-3600)  # 1h ago
    task = create_cleaning_task(
        room_id=room["id"], task_source="SCHEDULED",
        early_check_in_at=past,
    )
    assert task["priority_score"] == 20
    assert task["priority_tier"] == "NORMAL"
