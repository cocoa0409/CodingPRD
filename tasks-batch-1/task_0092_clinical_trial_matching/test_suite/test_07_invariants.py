"""Conserved-quantity invariants: allocation occupancy restored on withdraw,
safety occupancy restored on an unrelated adjudication, and derived-counter
reconciliation after randomize (PRD §3.4, §3.5)."""
from test_helpers import (
    validate_success,
    set_clock,
    setup_randomized_enrollment,
    report_adverse_event, triage_adverse_event, adjudicate_adverse_event,
    TEST_USERS,
)


# ─── Difficulty: compensating_invariant / allocation occupancy ─────


def test_withdraw_restores_trial_enrolled_count(api):
    """PRD §3.4: "if the enrollment was in `RANDOMIZED` or `ACTIVE`, it also
    decrements that enrollment's randomization arm's `assigned_count` by one
    and decrements the trial's `enrolled_count` by one as a compensating
    cascade"

    Design: Difficulty/compensating_invariant/ci_withdraw_restores_enrolled_and_arm_counts
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    trial_before = validate_success(api.get_trial(ctx["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial_before["enrolled_count"] == 1, "one randomized enrollment occupies one slot"

    res = api.transition_enrollment(
        ctx["enrollment_id"], {"action": "WITHDRAW"}, TEST_USERS["coordinator_headers"],
    )
    enr = validate_success(res, 200)
    assert enr["enrollment_status"] == "WITHDRAWN"

    trial_after = validate_success(api.get_trial(ctx["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial_after["enrolled_count"] == 0, "withdraw restores enrolled_count to its pre-randomize value 0"


def test_withdraw_restores_assigned_arm_count(api):
    """PRD §3.4: "if the enrollment was in `RANDOMIZED` or `ACTIVE`, it also
    decrements that enrollment's randomization arm's `assigned_count` by one
    and decrements the trial's `enrolled_count` by one as a compensating
    cascade"

    Design: Difficulty/compensating_invariant/ci_withdraw_restores_enrolled_and_arm_counts
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    enr_before = validate_success(api.get_enrollment(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assigned_arm_id = enr_before["arm_id"]
    assert assigned_arm_id is not None, "the enrollment was assigned an arm at randomize"

    api.transition_enrollment(
        ctx["enrollment_id"], {"action": "WITHDRAW"}, TEST_USERS["coordinator_headers"],
    )
    arms = validate_success(api.list_arms(ctx["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assigned_arm = next(a for a in arms if a["id"] == assigned_arm_id)
    assert assigned_arm["assigned_count"] == 0, \
        f"the assigned arm's count returns to 0 after withdraw, got {assigned_arm['assigned_count']}"


# ─── Difficulty: compensating_invariant / safety occupancy ─────────


def test_unrelated_adjudication_restores_safety_clear(api):
    """PRD §3.5: "With `relation` `UNRELATED`, the event becomes
    `ADJUDICATED_UNRELATED`, the adjudicator is recorded, and if no other
    adverse event on the enrollment remains in `REPORTED` or `UNDER_REVIEW`,
    the enrollment transitions `FLAGGED → CLEAR`."

    Design: Difficulty/compensating_invariant/ci_unrelated_adjudication_restores_safety_clear
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    ae = report_adverse_event(ctx["enrollment_id"], severity="MODERATE",
                              occurred_at="2026-06-01T09:00:00Z")
    triage_adverse_event(ae["id"])  # CLEAR -> FLAGGED

    flagged = validate_success(api.get_enrollment(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert flagged["safety_status"] == "FLAGGED", "triage flags the enrollment"

    adjudicate_adverse_event(ae["id"], "UNRELATED")
    enr = validate_success(api.get_enrollment(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["safety_status"] == "CLEAR", "an unrelated adjudication restores safety_status to CLEAR"


def test_unrelated_adjudication_leaves_trial_holds_zero(api):
    """PRD §3.5: "An enrollment's `safety_status` is a second, fully
    independent dimension that evolves on its own track through `CLEAR`,
    `FLAGGED`, and `HOLD`, driven entirely by adverse events"

    Design: Difficulty/compensating_invariant/ci_unrelated_adjudication_restores_safety_clear
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    ae = report_adverse_event(ctx["enrollment_id"], severity="MODERATE",
                              occurred_at="2026-06-01T09:00:00Z")
    triage_adverse_event(ae["id"])
    adjudicate_adverse_event(ae["id"], "UNRELATED")

    trial = validate_success(api.get_trial(ctx["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial["active_safety_holds"] == 0, \
        "an unrelated adjudication never places a hold, so active_safety_holds stays 0"


# ─── Corner: cross_cutting / derived counter reconciliation ────────


def test_derived_enrolled_count_after_randomize(api):
    """PRD §2.5: "On a `Trial`, four fields are derived: ... `enrolled_count`
    is the number of this trial's enrollments whose `enrollment_status` is
    `RANDOMIZED`, `ACTIVE`, or `COMPLETED`"
    PRD §2.5: "On a `RandomizationArm`, `assigned_count` is the number of
    enrollments randomized to that arm whose `enrollment_status` is
    `RANDOMIZED`, `ACTIVE`, or `COMPLETED`."

    Design: Corner/cross_cutting_complexity_layers/derived_enrolled_count_after_randomize
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()

    trial = validate_success(api.get_trial(ctx["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial["enrolled_count"] == 1, "one randomize reconciles enrolled_count to 1"

    enr = validate_success(api.get_enrollment(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    arms = validate_success(api.list_arms(ctx["trial_id"], TEST_USERS["sponsor_headers"]), 200)
    assigned_arm = next(a for a in arms if a["id"] == enr["arm_id"])
    assert assigned_arm["assigned_count"] == 1, "the assigned arm's assigned_count reconciles to 1"
