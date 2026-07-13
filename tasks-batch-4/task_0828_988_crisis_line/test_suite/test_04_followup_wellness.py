"""Follow-up wellness-check retry cycle and the max-attempts abandonment boundary."""
from test_helpers import (
    api_client as api,
    validate_success,
    TEST_USERS,
    create_resolved_de_escalation_with_followup,
)

COUNSELOR = TEST_USERS["counselor_headers"]


# ─── non_linear_state_machine / followup_reschedule_cycle_returns_to_rescheduled ─

def test_first_no_answer_returns_task_to_rescheduled():
    """PRD §3.8: "it increments `attempt_count` by 1 and stores the given `outcome`."
    PRD §3.8: "if the `outcome` is `NO_ANSWER` and the incremented `attempt_count` has reached or exceeded `max_attempts`, the task is abandoned to `ABANDONED`; otherwise the task moves to `RESCHEDULED` and its `scheduled_at` is reset to the supplied `next_scheduled_at`."

    Design: Difficulty/non_linear_state_machine/followup_reschedule_cycle_returns_to_rescheduled
    """
    _, task = create_resolved_de_escalation_with_followup("fu-cyc-01")
    res = api.follow_up_attempt(
        task["id"], {"outcome": "NO_ANSWER", "next_scheduled_at": "2026-03-02T00:00:00Z"}, COUNSELOR)
    t = validate_success(res, 200)
    assert t["status"] == "RESCHEDULED", f"expected RESCHEDULED after 1st NO_ANSWER, got {t['status']}"
    assert t["attempt_count"] == 1, f"expected attempt_count 1, got {t['attempt_count']}"


def test_second_no_answer_loops_back_to_rescheduled():
    """PRD §3.8: "if the `outcome` is `NO_ANSWER` and the incremented `attempt_count` has reached or exceeded `max_attempts`, the task is abandoned to `ABANDONED`; otherwise the task moves to `RESCHEDULED` and its `scheduled_at` is reset to the supplied `next_scheduled_at`."
    PRD §3.8: "The `RESCHEDULED`-attempt-`RESCHEDULED` loop is the wellness-check retry cycle, and it terminates either when the caller is reached or when the attempt ceiling is hit."

    Design: Difficulty/non_linear_state_machine/followup_reschedule_cycle_returns_to_rescheduled
    """
    _, task = create_resolved_de_escalation_with_followup("fu-cyc-02")
    validate_success(api.follow_up_attempt(
        task["id"], {"outcome": "NO_ANSWER", "next_scheduled_at": "2026-03-02T00:00:00Z"}, COUNSELOR), 200)
    res = api.follow_up_attempt(
        task["id"], {"outcome": "NO_ANSWER", "next_scheduled_at": "2026-03-03T00:00:00Z"}, COUNSELOR)
    t = validate_success(res, 200)
    assert t["status"] == "RESCHEDULED", f"expected RESCHEDULED after 2nd NO_ANSWER, got {t['status']}"
    assert t["attempt_count"] == 2, f"expected attempt_count 2, got {t['attempt_count']}"


# ─── boundary_precision_check / followup_max_attempts_ge_boundary ──────────────

def test_task_stays_rescheduled_below_max_attempts():
    """PRD §3.8: "Each task also carries a `max_attempts` ceiling that defaults to 3 and governs when outreach is abandoned."
    PRD §3.8: "if the `outcome` is `NO_ANSWER` and the incremented `attempt_count` has reached or exceeded `max_attempts`, the task is abandoned to `ABANDONED`; otherwise the task moves to `RESCHEDULED` and its `scheduled_at` is reset to the supplied `next_scheduled_at`."

    Design: Difficulty/boundary_precision_check/followup_max_attempts_ge_boundary
    """
    _, task = create_resolved_de_escalation_with_followup("bp-fu-01")
    validate_success(api.follow_up_attempt(
        task["id"], {"outcome": "NO_ANSWER", "next_scheduled_at": "2026-03-02T00:00:00Z"}, COUNSELOR), 200)
    res = api.follow_up_attempt(
        task["id"], {"outcome": "NO_ANSWER", "next_scheduled_at": "2026-03-03T00:00:00Z"}, COUNSELOR)
    t = validate_success(res, 200)
    assert t["attempt_count"] == 2, f"expected attempt_count 2, got {t['attempt_count']}"
    assert t["status"] == "RESCHEDULED", (
        f"count 2 < max 3 must stay RESCHEDULED, got {t['status']}"
    )


def test_third_no_answer_abandons_at_max_attempts():
    """PRD §3.8: "if the `outcome` is `NO_ANSWER` and the incremented `attempt_count` has reached or exceeded `max_attempts`, the task is abandoned to `ABANDONED`; otherwise the task moves to `RESCHEDULED` and its `scheduled_at` is reset to the supplied `next_scheduled_at`."

    Design: Difficulty/boundary_precision_check/followup_max_attempts_ge_boundary
    """
    _, task = create_resolved_de_escalation_with_followup("bp-fu-02")
    validate_success(api.follow_up_attempt(
        task["id"], {"outcome": "NO_ANSWER", "next_scheduled_at": "2026-03-02T00:00:00Z"}, COUNSELOR), 200)
    validate_success(api.follow_up_attempt(
        task["id"], {"outcome": "NO_ANSWER", "next_scheduled_at": "2026-03-03T00:00:00Z"}, COUNSELOR), 200)
    res = api.follow_up_attempt(task["id"], {"outcome": "NO_ANSWER"}, COUNSELOR)
    t = validate_success(res, 200)
    assert t["attempt_count"] == 3, f"expected attempt_count 3, got {t['attempt_count']}"
    assert t["status"] == "ABANDONED", (
        f"count 3 >= max 3 must ABANDON, got {t['status']}"
    )
