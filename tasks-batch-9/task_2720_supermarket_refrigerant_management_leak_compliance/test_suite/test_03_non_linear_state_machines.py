"""
Three machines whose shape is not a line: a leak-event repair cycle, a retrofit
plan revision loop, and a system carrying two parallel state axes.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_leak_event_schedule,
    assert_score,
    assert_store_posture,
    assert_system_axes,
)
from test_helpers.constants import RETIRE_PLAN_GWP_REDUCTION_PCT, RETIRE_PLAN_SCORE
from test_helpers.test_users import make_technician_headers
from test_helpers.types import (
    ATTEMPT_AWAITING_VERIFICATION,
    ATTEMPT_FAILED_VERIFICATION,
    COMPAT_COMPATIBLE,
    EVENT_VERIFICATION_FAILED,
    EVENT_VERIFICATION_PENDING,
    EVENT_VOIDED,
    PLAN_REJECTED,
    PLAN_SUBMITTED,
    POSTURE_COMPLIANT,
    RESULT_FAIL,
    SEQUENCE_INITIAL,
    STATE_LEAK_OPEN,
    STATE_RETIRED_EXEMPT,
    SYSTEM_ACTIVE,
    SYSTEM_RETIRED,
)


# ─── the leak-event repair cycle ──────────────────────────────────────


def test_first_failed_verification_leaves_the_event_in_verification_failed(api):
    """
    The first FAIL takes the event out of VERIFICATION_PENDING into
    VERIFICATION_FAILED with one failure counted and the tested attempt marked
    FAILED_VERIFICATION — the state the cycle then departs from.

    Design: Difficulty/non_linear_state_machine/leak_event_verification_failure_cycles_back_to_verification_pending
    """
    env = X.repaired_event_env(api)

    event_before = X.get_leak_event(api, env["event_id"])
    assert event_before["status"] == EVENT_VERIFICATION_PENDING
    assert event_before["repair_attempt_count"] == 1
    assert event_before["failed_verification_count"] == 0
    assert_leak_event_schedule(event_before, verification_deadline="2026-08-15T09:00:00Z")

    test1 = X.file_verification_test(
        api,
        env["event_id"],
        env["attempt1_id"],
        env["tech2_id"],
        "2026-08-06T09:00:00Z",
        result=RESULT_FAIL,
        measured_leak_rate_pct=18.5,
    )
    assert test1["test_sequence"] == SEQUENCE_INITIAL

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_VERIFICATION_FAILED
    assert event["failed_verification_count"] == 1
    assert (
        X.get_repair_attempt(api, env["attempt1_id"])["outcome"]
        == ATTEMPT_FAILED_VERIFICATION
    )


def test_second_repair_attempt_re_enters_verification_pending_with_carried_counters(api):
    """
    A second attempt returns the event to a state it has already occupied, but
    the loop is not a reset: the failure count is carried, the attempt count has
    advanced, and the verification deadline is re-based on the newer repair while
    the statutory initial repair deadline is untouched.

    Design: Difficulty/non_linear_state_machine/leak_event_verification_failure_cycles_back_to_verification_pending
    """
    env = X.repaired_event_env(api)
    test1 = X.file_verification_test(
        api,
        env["event_id"],
        env["attempt1_id"],
        env["tech2_id"],
        "2026-08-06T09:00:00Z",
        result=RESULT_FAIL,
        measured_leak_rate_pct=18.5,
    )

    attempt2 = validate_success(
        api.create_repair_attempt(
            F.repair_attempt_payload(
                env["event_id"],
                env["system_id"],
                env["tech1_id"],
                env["eq1_id"],
                "2026-08-07T09:00:00Z",
                repair_method_code="REPLACE_VALVE",
            ),
            make_technician_headers(env["tech1_id"]),
        ),
        expected_status=201,
    )
    assert attempt2["attempt_number"] == 2
    assert attempt2["outcome"] == ATTEMPT_AWAITING_VERIFICATION

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_VERIFICATION_PENDING
    assert event["repair_attempt_count"] == 2
    assert event["failed_verification_count"] == 1
    assert_leak_event_schedule(
        event,
        verification_deadline="2026-08-17T09:00:00Z",
        initial_repair_deadline="2026-08-31T00:00:00Z",
    )
    assert_instant(
        event["last_repair_completed_at"],
        "2026-08-07T09:00:00Z",
        "last_repair_completed_at",
    )
    assert test1["test_sequence"] == SEQUENCE_INITIAL
    assert (
        X.get_repair_attempt(api, env["attempt1_id"])["outcome"]
        == ATTEMPT_FAILED_VERIFICATION
    )


# ─── the retrofit plan revision loop ──────────────────────────────────


def test_plan_rejection_records_the_reason_and_leaves_the_first_pass_visible(api):
    """
    The first submission stamps the odometer at 1 and the rejection stamps its own
    decision instant and reason code.

    Design: Difficulty/non_linear_state_machine/retrofit_plan_rejection_resubmission_loop_increments_submission_count
    """
    env = X.draft_plan_env(api, with_second_technician=False)

    submitted = X.submit_plan(api, env["plan_id"], submission_note="initial filing")
    assert submitted["submission_count"] == 1
    assert_instant(submitted["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")

    rejected = X.reject_plan(api, env["plan_id"], "SCOPE_INSUFFICIENT")
    assert rejected["status"] == PLAN_REJECTED
    assert rejected["rejection_reason_code"] == "SCOPE_INSUFFICIENT"
    assert_instant(rejected["decided_at"], "2026-08-01T00:00:00Z", "decided_at")


def test_resubmission_returns_the_plan_to_submitted_with_the_odometer_advanced(api):
    """
    The second visit to SUBMITTED is observably not the first: the submission
    count reads 2, the submission instant moves to the later clock, and the
    rejection instant is not cleared by the resubmission.

    Design: Difficulty/non_linear_state_machine/retrofit_plan_rejection_resubmission_loop_increments_submission_count
    """
    env = X.draft_plan_env(api, with_second_technician=False)
    X.submit_plan(api, env["plan_id"], submission_note="initial filing")
    X.reject_plan(api, env["plan_id"], "SCOPE_INSUFFICIENT")
    X.set_clock(api, "2026-08-10T00:00:00Z")

    resubmitted = X.submit_plan(
        api, env["plan_id"], submission_note="revised scope, same target chemistry"
    )
    assert resubmitted["status"] == PLAN_SUBMITTED
    assert resubmitted["submission_count"] == 2
    assert_instant(resubmitted["submitted_at"], "2026-08-10T00:00:00Z", "submitted_at")
    assert_instant(resubmitted["decided_at"], "2026-08-01T00:00:00Z", "decided_at")
    assert_score(resubmitted["compatibility_score"], 84.1, "compatibility_score")


# ─── the system's two parallel axes ───────────────────────────────────


def test_compliance_axis_moves_to_leak_open_while_the_physical_axis_stays_active(api):
    """
    A declared leak event advances the compliance axis on its own; the physical
    axis is untouched, which is what proves the two are not one combined state.
    A RETIRE plan meanwhile bypasses chemistry scoring altogether.

    Design: Difficulty/non_linear_state_machine/system_operational_and_compliance_axes_move_independently_then_retirement_overrides
    """
    env = X.retire_plan_env(api, with_second_technician=False)

    assert_system_axes(
        X.get_system(api, env["system_id"]),
        operational_status=SYSTEM_ACTIVE,
        compliance_state=STATE_LEAK_OPEN,
    )
    plan = X.get_plan(api, env["plan_id"])
    assert_score(plan["compatibility_score"], RETIRE_PLAN_SCORE, "compatibility_score")
    assert plan["compatibility_result"] == COMPAT_COMPATIBLE
    assert_score(
        plan["gwp_reduction_pct"], RETIRE_PLAN_GWP_REDUCTION_PCT, "gwp_reduction_pct"
    )


def test_retirement_moves_one_axis_and_overrides_the_other(api):
    """
    The single retirement call moves the physical axis to RETIRED and forces the
    compliance axis to RETIRED_EXEMPT over the LEAK_OPEN it was holding, voiding
    the non-terminal event and emptying the store's posture counters.

    Design: Difficulty/non_linear_state_machine/system_operational_and_compliance_axes_move_independently_then_retirement_overrides
    """
    env = X.retire_plan_env(api, with_second_technician=False)
    X.approve_plan(api, env["plan_id"])

    retired = X.retire_system(api, env["system_id"], retrofit_plan_id=env["plan_id"])
    assert_system_axes(
        retired,
        operational_status=SYSTEM_RETIRED,
        compliance_state=STATE_RETIRED_EXEMPT,
    )
    assert_instant(retired["retired_on"], "2026-08-01T00:00:00Z", "retired_on")

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_VOIDED
    assert_instant(event["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

    assert_store_posture(
        X.get_store(api, env["store_id"]),
        compliance_status=POSTURE_COMPLIANT,
        open_leak_event_count=0,
        regulated_system_count=0,
    )
