"""
Writes whose legality lives in a different entity's state: a technician's
suspension, a leak event's non-terminal status, and a repair attempt's outcome
that a later sibling row mutated.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_OPEN_LEAK_EVENT_BLOCKS_RETIREMENT,
    ERR_REPAIR_ATTEMPT_NOT_CURRENT,
    ERR_TECHNICIAN_SUSPENDED,
)
from test_helpers.assertions import (
    assert_instant,
    assert_leak_event_schedule,
    assert_mass,
    assert_money,
    assert_store_posture,
    assert_system_axes,
    assert_system_charge,
)
from test_helpers.test_users import COMPLIANCE_MANAGER_HEADERS, make_technician_headers
from test_helpers.types import (
    ATTEMPT_AWAITING_VERIFICATION,
    ATTEMPT_SUPERSEDED,
    ATTEMPT_VERIFIED,
    EVENT_FOLLOWUP_PENDING,
    EVENT_OPEN,
    EVENT_VERIFICATION_PENDING,
    EVENT_VOIDED,
    PLAN_APPROVED,
    POSTURE_COMPLIANT,
    RESULT_PASS,
    SEQUENCE_INITIAL,
    STATE_RETIRED_EXEMPT,
    SYSTEM_ACTIVE,
    SYSTEM_RETIRED,
    TECHNICIAN_ACTIVE,
    TECHNICIAN_SUSPENDED,
)


# ─── a service record depends on the technician's live status ─────────


def _suspended_technician(api):
    """
    A commissioned store whose only repairing technician has just been suspended
    for a certification review. Nothing about the system, the machine or the
    cylinder changed.
    """
    env = X.base_env(api, with_second_technician=False)
    env["version"] = X.system_version(api, env["system_id"])
    env["suspended"] = X.suspend_technician(api, env["tech1_id"], "CERT_UNDER_REVIEW")
    return env


def _the_same_record(api, env):
    return api.create_service_record(
        F.service_record_payload(
            env["system_id"],
            env["tech1_id"],
            env["eq1_id"],
            env["version"],
            cylinder_id=env["cyl1_id"],
            refrigerant_added_lbs=10.0,
            performed_at="2026-08-01T00:00:00Z",
            duration_minutes=60,
        ),
        make_technician_headers(env["tech1_id"]),
    )


def test_service_record_is_refused_while_the_technician_is_suspended(api):
    """
    The payload references the technician but carries none of its state, so the
    refusal can only come from the technician row itself; nothing is written.

    Design: Difficulty/cross_entity_state_dependency/service_record_blocked_by_suspended_technician_state
    """
    env = _suspended_technician(api)

    assert env["suspended"]["status"] == TECHNICIAN_SUSPENDED
    assert env["suspended"]["suspension_reason_code"] == "CERT_UNDER_REVIEW"

    validate_error(_the_same_record(api, env), ERR_TECHNICIAN_SUSPENDED, 422)

    system = X.get_system(api, env["system_id"])
    assert_system_charge(system, current_charge_lbs=80.0)
    assert system["version"] == env["version"]


def test_the_identical_record_succeeds_once_the_technician_is_reinstated(api):
    """
    Reinstatement clears the suspension reason, and the byte-identical payload
    that was refused now posts and moves the charge — so the dependency was on
    live status, not on anything cached when the reference was made.

    Design: Difficulty/cross_entity_state_dependency/service_record_blocked_by_suspended_technician_state
    """
    env = _suspended_technician(api)
    validate_error(_the_same_record(api, env), ERR_TECHNICIAN_SUSPENDED, 422)

    reinstated = X.reinstate_technician(api, env["tech1_id"], "CERT_REVIEW_CLEARED")
    assert reinstated["status"] == TECHNICIAN_ACTIVE
    assert reinstated["suspension_reason_code"] is None

    record = validate_success(_the_same_record(api, env), expected_status=201)
    assert_mass(record["system_charge_after_lbs"], 90.0, "system_charge_after_lbs")
    assert_money(record["leak_rate_pct_after"], 10.0, "leak_rate_pct_after")

    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0
    assert_store_posture(
        X.get_store(api, env["store_id"]), compliance_status=POSTURE_COMPLIANT
    )
    assert_mass(
        X.get_cylinder(api, env["cyl1_id"])["current_contents_lbs"],
        30.0,
        "current_contents_lbs",
    )


# ─── a retirement depends on the leak event and on a third entity ─────


def _fully_recovered_system_with_an_open_event(api):
    """
    A 60.0 lb system commissioned empty, so its charge precondition for
    retirement is already met, carrying one OPEN manually declared event and a
    RETIRE plan that has only been submitted.
    """
    return X.retire_plan_env(api)


def _retire_naming_the_plan(api, env):
    return api.retire_system(
        env["system_id"],
        F.retirement_payload(retrofit_plan_id=env["plan_id"]),
        COMPLIANCE_MANAGER_HEADERS,
    )


def test_retirement_is_blocked_while_the_leak_event_is_non_terminal(api):
    """
    A merely submitted RETIRE plan is not the escape hatch, so the open event
    still blocks; neither the system nor the event moves.

    Design: Difficulty/cross_entity_state_dependency/system_retirement_blocked_by_non_terminal_leak_event_state
    """
    env = _fully_recovered_system_with_an_open_event(api)

    validate_error(
        _retire_naming_the_plan(api, env), ERR_OPEN_LEAK_EVENT_BLOCKS_RETIREMENT, 422
    )

    assert_system_axes(
        X.get_system(api, env["system_id"]), operational_status=SYSTEM_ACTIVE
    )
    assert X.get_leak_event(api, env["event_id"])["status"] == EVENT_OPEN


def test_approving_the_retire_plan_unblocks_the_identical_retirement(api):
    """
    Approving the third entity is the only change, and the same call now retires
    the system and voids the event while the plan itself stays APPROVED.

    Design: Difficulty/cross_entity_state_dependency/system_retirement_blocked_by_non_terminal_leak_event_state
    """
    env = _fully_recovered_system_with_an_open_event(api)
    validate_error(
        _retire_naming_the_plan(api, env), ERR_OPEN_LEAK_EVENT_BLOCKS_RETIREMENT, 422
    )

    assert X.approve_plan(api, env["plan_id"])["status"] == PLAN_APPROVED

    system = validate_success(_retire_naming_the_plan(api, env))
    assert_system_axes(
        system,
        operational_status=SYSTEM_RETIRED,
        compliance_state=STATE_RETIRED_EXEMPT,
    )
    assert_instant(system["retired_on"], "2026-08-01T00:00:00Z", "retired_on")

    assert X.get_leak_event(api, env["event_id"])["status"] == EVENT_VOIDED
    assert X.get_plan(api, env["plan_id"])["status"] == PLAN_APPROVED
    assert_store_posture(
        X.get_store(api, env["store_id"]),
        open_leak_event_count=0,
        compliance_status=POSTURE_COMPLIANT,
    )


# ─── a verification depends on the attempt's per-row outcome ──────────


def _two_attempts_on_one_event(api):
    """
    Two repair attempts on the same event by the same technician with the same
    machine, filed in order, so only the later one is current.
    """
    env = X.repaired_event_env(api)
    attempt2 = X.file_repair_attempt(
        api,
        env["event_id"],
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        "2026-08-07T09:00:00Z",
        repair_method_code="REPLACE_GASKET",
    )
    env["attempt2_id"] = attempt2["id"]
    return env


def _verify(api, env, attempt_id):
    return api.create_verification_test(
        F.verification_test_payload(
            env["event_id"],
            attempt_id,
            env["tech2_id"],
            "2026-08-07T13:00:00Z",
            test_method_code="PRESSURE_DECAY",
            result=RESULT_PASS,
            measured_leak_rate_pct=2.0,
        ),
        make_technician_headers(env["tech2_id"]),
    )


def test_verifying_the_superseded_attempt_is_refused(api):
    """
    Filing the second attempt flipped the first out of AWAITING_VERIFICATION, and
    that outcome field is the only difference between two otherwise
    interchangeable rows; no test row is written.

    Design: Difficulty/cross_entity_state_dependency/verification_test_blocked_by_superseded_repair_attempt_state
    """
    env = _two_attempts_on_one_event(api)

    attempt1 = X.get_repair_attempt(api, env["attempt1_id"])
    assert attempt1["outcome"] == ATTEMPT_SUPERSEDED
    assert attempt1["attempt_number"] == 1
    attempt2 = X.get_repair_attempt(api, env["attempt2_id"])
    assert attempt2["outcome"] == ATTEMPT_AWAITING_VERIFICATION
    assert attempt2["attempt_number"] == 2

    validate_error(
        _verify(api, env, env["attempt1_id"]), ERR_REPAIR_ATTEMPT_NOT_CURRENT, 422
    )

    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_VERIFICATION_PENDING
    assert event["failed_verification_count"] == 0


def test_verifying_the_current_attempt_succeeds_and_never_revives_the_other(api):
    """
    The same test against the current attempt passes and moves the event on,
    while the superseded attempt keeps its outcome — supersession is permanent.

    Design: Difficulty/cross_entity_state_dependency/verification_test_blocked_by_superseded_repair_attempt_state
    """
    env = _two_attempts_on_one_event(api)
    validate_error(
        _verify(api, env, env["attempt1_id"]), ERR_REPAIR_ATTEMPT_NOT_CURRENT, 422
    )

    test = validate_success(
        _verify(api, env, env["attempt2_id"]), expected_status=201
    )
    assert test["test_sequence"] == SEQUENCE_INITIAL
    assert test["result"] == RESULT_PASS

    assert X.get_repair_attempt(api, env["attempt2_id"])["outcome"] == ATTEMPT_VERIFIED
    event = X.get_leak_event(api, env["event_id"])
    assert event["status"] == EVENT_FOLLOWUP_PENDING
    assert_leak_event_schedule(event, verification_deadline="2026-08-17T13:00:00Z")

    assert X.get_repair_attempt(api, env["attempt1_id"])["outcome"] == ATTEMPT_SUPERSEDED
