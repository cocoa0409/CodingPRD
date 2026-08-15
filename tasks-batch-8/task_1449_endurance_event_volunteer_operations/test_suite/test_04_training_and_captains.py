"""Training records and captain designation (PRD §3.4, §3.5)."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    validate_success, validate_error,
    create_event, register_volunteer, register_eligible_volunteer,
    create_training_record_payload,
    setup_event_with_shift, create_confirmed_signup,
    enroll_and_pass, set_clock,
    assert_training_record, assert_signup,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_training_record_create_defaults(api):
    """PRD §3.4: "A fresh record starts `ENROLLED` with `attempt_count` at
    one; the status vocabulary is `ENROLLED`, `PASSED`, `FAILED`, and
    `EXPIRED`, none of them terminal."
    PRD §3.4: "it returns the record to `ENROLLED`, increments `attempt_count`
    by one, and clears `passed_at` and `valid_until` back to null."

    Design: Corner/entities/training_record_create_defaults
    """
    event = create_event(clock=None)
    vol = register_volunteer(event["id"])
    resp = api_client.create_training_record(
        create_training_record_payload(event["id"], vol["id"],
                                       module_code="MEDICAL_RESPONSE"),
        COORDINATOR)
    data = validate_success(resp, expected_status=201)
    assert_training_record(data)
    assert data["status"] == "ENROLLED"
    assert data["attempt_count"] == 1
    assert data["passed_at"] is None
    assert data["valid_until"] is None


def test_duplicate_training_record_rejected(api):
    """PRD §3.4: "One record exists per volunteer per module: a second
    enrollment for the same pair is rejected with
    `ERR_DUPLICATE_TRAINING_RECORD`, and the remedy is re-enrollment of the
    existing record, not a new one."

    Design: Corner/validations/duplicate_training_record_rejected
    """
    event = create_event(clock=None)
    vol = register_volunteer(event["id"])
    first = api_client.create_training_record(
        create_training_record_payload(event["id"], vol["id"]), COORDINATOR)
    validate_success(first, expected_status=201)
    dup = api_client.create_training_record(
        create_training_record_payload(event["id"], vol["id"]), COORDINATOR)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_TRAINING_RECORD)


# ---------------------------------------------------------------------------
# The cyclic machine: ENROLLED -> FAILED -> ENROLLED -> PASSED -> EXPIRED ->
# ENROLLED on a single record (PRD §3.4).
# ---------------------------------------------------------------------------

def _setup_training_cycle(api):
    """Volunteer enrolled in SAFETY_BRIEFING at 2026-08-20, failed once,
    re-enrolled, then passed. Returns (event, volunteer, record_after_pass)."""
    event = create_event()  # clock pinned at 2026-08-20 inside the window
    vol = register_volunteer(event["id"])
    rec = validate_success(api_client.create_training_record(
        create_training_record_payload(event["id"], vol["id"],
                                       module_code="SAFETY_BRIEFING"),
        COORDINATOR), expected_status=201)
    failed = validate_success(api_client.fail_training_record(rec["id"], COORDINATOR))
    assert failed["status"] == "FAILED"
    return event, vol, rec


def test_training_retry_loop_fail_then_reenroll(api):
    """PRD §3.4: "Re-enrollment is permitted from `FAILED` or `EXPIRED` only
    (`ERR_TRAINING_INVALID_STATE` otherwise); it returns the record to
    `ENROLLED`, increments `attempt_count` by one, and clears `passed_at` and
    `valid_until` back to null."
    PRD §3.4: "Passing — allowed only from `ENROLLED`, otherwise
    `ERR_TRAINING_INVALID_STATE` — moves the record to `PASSED`, stamps
    `passed_at` with the current instant, and sets `valid_until` by adding the
    module's validity window: thirty days for `SAFETY_BRIEFING`, three hundred
    sixty-five days for `CAPTAIN_COURSE`, and seven hundred thirty days for
    `MEDICAL_RESPONSE`."

    Design: Difficulty/non_linear_state_machine/training_record_retry_expiry_cycle
    """
    event, vol, rec = _setup_training_cycle(api)
    reenrolled = validate_success(api_client.re_enroll_training_record(rec["id"], COORDINATOR))
    assert reenrolled["status"] == "ENROLLED"
    assert reenrolled["attempt_count"] == 2, "first retry loop leg bumps the attempt counter"
    passed = validate_success(api_client.pass_training_record(rec["id"], COORDINATOR))
    assert passed["status"] == "PASSED"
    assert _parse_ts(passed["passed_at"]) == _parse_ts("2026-08-20T00:00:00Z")
    assert _parse_ts(passed["valid_until"]) == _parse_ts("2026-09-19T00:00:00Z"), \
        "SAFETY_BRIEFING passed at 2026-08-20 is valid for thirty days"


def test_training_expiry_then_reenroll_cycle(api):
    """PRD §3.9: "First, the sweep expires credentials: every `PASSED`
    training record of the event whose `valid_until` has passed moves to
    `EXPIRED`, firing the cancellation cascade of §3.4."
    PRD §3.4: "Re-enrollment is permitted from `FAILED` or `EXPIRED` only
    (`ERR_TRAINING_INVALID_STATE` otherwise); it returns the record to
    `ENROLLED`, increments `attempt_count` by one, and clears `passed_at` and
    `valid_until` back to null."

    Design: Difficulty/non_linear_state_machine/training_record_retry_expiry_cycle
    """
    event, vol, rec = _setup_training_cycle(api)
    validate_success(api_client.re_enroll_training_record(rec["id"], COORDINATOR))
    validate_success(api_client.pass_training_record(rec["id"], COORDINATOR))
    set_at = "2026-09-20T00:00:00Z"
    set_clock(set_at)
    sweep = validate_success(api_client.run_epoch_sweep(event["id"], DIRECTOR))
    assert rec["id"] in sweep["expired_training_record_ids"]
    expired = validate_success(api_client.get_training_record(rec["id"], COORDINATOR))
    assert expired["status"] == "EXPIRED", "sweep must move the lapsed PASSED record to EXPIRED"
    reenrolled = validate_success(api_client.re_enroll_training_record(rec["id"], COORDINATOR))
    assert reenrolled["status"] == "ENROLLED"
    assert reenrolled["attempt_count"] == 3, "second loop leg (post-expiry) bumps the counter again"
    assert reenrolled["passed_at"] is None
    assert reenrolled["valid_until"] is None


# ---------------------------------------------------------------------------
# Captain designation (PRD §3.5)
# ---------------------------------------------------------------------------

def test_captain_assignment_requires_current_captain_course(api):
    """PRD §3.5: "A coordinator marks a `CONFIRMED` signup as the shift's
    captain: the volunteer must hold a current `CAPTAIN_COURSE` training
    record (`ERR_TRAINING_NOT_CURRENT`), and the shift must not already have
    a captain"

    Design: Corner/state_machines/captain_assignment_requires_current_captain_course
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg = create_confirmed_signup(vol["id"], ctx["shift"]["id"])
    blocked = api_client.assign_captain(sg["id"], COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_TRAINING_NOT_CURRENT)
    enroll_and_pass(ev, vol["id"], "CAPTAIN_COURSE")
    assigned = validate_success(api_client.assign_captain(sg["id"], COORDINATOR))
    assert assigned["is_captain"] is True


def test_second_captain_rejected_until_removed(api):
    """PRD §3.5: "Every shift may designate at most one captain."
    PRD §3.5: "if another signup on the shift already has `is_captain` true,
    the assignment is rejected with `ERR_CAPTAIN_SLOT_TAKEN`. The designation
    sets `is_captain` true on the signup, and a coordinator may later clear
    the flag, releasing the slot."

    Design: Corner/state_machines/second_captain_rejected_until_removed
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    v1 = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    v2 = register_eligible_volunteer(ev, full_name="V Two", date_of_birth="2000-01-02")
    enroll_and_pass(ev, v1["id"], "CAPTAIN_COURSE")
    enroll_and_pass(ev, v2["id"], "CAPTAIN_COURSE")
    sg1 = create_confirmed_signup(v1["id"], ctx["shift"]["id"])
    sg2 = create_confirmed_signup(v2["id"], ctx["shift"]["id"])
    validate_success(api_client.assign_captain(sg1["id"], COORDINATOR))
    blocked = api_client.assign_captain(sg2["id"], COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_CAPTAIN_SLOT_TAKEN)
    removed = validate_success(api_client.remove_captain(sg1["id"], COORDINATOR))
    assert removed["is_captain"] is False
    assigned = validate_success(api_client.assign_captain(sg2["id"], COORDINATOR))
    assert assigned["is_captain"] is True
