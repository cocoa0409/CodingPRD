"""Attempt scheduling guards: enumerator window overlap, per-case contact
cooldown, and the max-attempts count boundary.

Translates queue-A resource_temporal_overlap (both instances) and
boundary_precision_check (max_attempts leg).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_enumerator_headers,
    TEST_USERS,
    create_attempt_payload,
    setup_assigned_case,
    setup_two_assigned_cases,
    log_attempt,
)

ADMIN = TEST_USERS["survey_admin_headers"]


# ── resource_temporal_overlap: enumerator_window_overlap ──────────────────────

def test_enumerator_overlapping_windows_conflict(api):
    """PRD §3.5: "a new attempt's window must not overlap any other LOGGED attempt
    by the same enumerator, treating each window as half-open from its start up to
    but not including its end, so that back-to-back windows sharing an instant (one
    window's end equal to the next window's start) are allowed with no buffer; an
    overlap here is rejected with `ERR_ENUMERATOR_SCHEDULE_CONFLICT`."

    Two different cases, same enumerator: 10:00-11:00 then 10:30-11:30 overlap.

    Design: Difficulty/resource_temporal_overlap/enumerator_window_overlap
    """
    ctx = setup_two_assigned_cases()
    en_id = ctx["enumerator"]["id"]
    log_attempt(ctx["case_a"]["id"], en_id, mode="IN_PERSON",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T11:00:00Z",
                disposition="NO_ONE_HOME", mileage_miles=0)
    res = api.create_attempt(
        ctx["case_b"]["id"],
        create_attempt_payload(mode="IN_PERSON", window_start="2026-03-01T10:30:00Z",
                               window_end="2026-03-01T11:30:00Z", disposition="NO_ONE_HOME",
                               mileage_miles=0),
        make_enumerator_headers(en_id))
    validate_error(res, "ERR_ENUMERATOR_SCHEDULE_CONFLICT", expected_status=409)


def test_enumerator_adjacent_windows_allowed(api):
    """PRD §3.5: "a new attempt's window must not overlap any other LOGGED attempt
    by the same enumerator, treating each window as half-open from its start up to
    but not including its end, so that back-to-back windows sharing an instant (one
    window's end equal to the next window's start) are allowed with no buffer; an
    overlap here is rejected with `ERR_ENUMERATOR_SCHEDULE_CONFLICT`."

    Two different cases, same enumerator: 10:00-11:00 then 11:00-11:30 are adjacent
    (end == start) and therefore permitted.

    Design: Difficulty/resource_temporal_overlap/enumerator_window_overlap
    """
    ctx = setup_two_assigned_cases()
    en_id = ctx["enumerator"]["id"]
    log_attempt(ctx["case_a"]["id"], en_id, mode="IN_PERSON",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T11:00:00Z",
                disposition="NO_ONE_HOME", mileage_miles=0)
    res = api.create_attempt(
        ctx["case_b"]["id"],
        create_attempt_payload(mode="IN_PERSON", window_start="2026-03-01T11:00:00Z",
                               window_end="2026-03-01T11:30:00Z", disposition="NO_ONE_HOME",
                               mileage_miles=0),
        make_enumerator_headers(en_id))
    attempt = validate_success(res, 201)
    assert attempt["status"] == "LOGGED"


# ── resource_temporal_overlap: case_contact_cooldown ──────────────────────────

def test_case_contact_cooldown_under_buffer_rejected(api):
    """PRD §3.5: "a case enforces a contact cooldown of 240 minutes: taking the new
    window and every other LOGGED attempt on the same case, two attempts collide
    when the gap between the earlier window's `window_end` and the later window's
    `window_start` is less than 240 minutes, and such a collision is rejected with
    `ERR_CASE_CONTACT_COOLDOWN`."

    Same case: 10:00-10:30 then 12:00-12:30 — a 90-minute gap (< 240).

    Design: Difficulty/resource_temporal_overlap/case_contact_cooldown
    """
    ctx = setup_assigned_case()
    en_id = ctx["enumerator"]["id"]
    log_attempt(ctx["case"]["id"], en_id, mode="PHONE",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="NO_ONE_HOME")
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="PHONE", window_start="2026-03-01T12:00:00Z",
                               window_end="2026-03-01T12:30:00Z", disposition="NO_ONE_HOME"),
        make_enumerator_headers(en_id))
    validate_error(res, "ERR_CASE_CONTACT_COOLDOWN", expected_status=409)


def test_case_contact_cooldown_at_exact_buffer_allowed(api):
    """PRD §3.5: "a case enforces a contact cooldown of 240 minutes: taking the new
    window and every other LOGGED attempt on the same case, two attempts collide
    when the gap between the earlier window's `window_end` and the later window's
    `window_start` is less than 240 minutes, and such a collision is rejected with
    `ERR_CASE_CONTACT_COOLDOWN`."

    Same case: 10:00-10:30 then 14:30-15:00 — a gap of exactly 240 minutes, which
    is not less than 240 and is therefore permitted.

    Design: Difficulty/resource_temporal_overlap/case_contact_cooldown
    """
    ctx = setup_assigned_case()
    en_id = ctx["enumerator"]["id"]
    log_attempt(ctx["case"]["id"], en_id, mode="PHONE",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="NO_ONE_HOME")
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="PHONE", window_start="2026-03-01T14:30:00Z",
                               window_end="2026-03-01T15:00:00Z", disposition="NO_ONE_HOME"),
        make_enumerator_headers(en_id))
    attempt = validate_success(res, 201)
    assert attempt["status"] == "LOGGED"


# ── boundary_precision_check: max_attempts_boundary_close ──────────────────────

def test_max_attempts_boundary_closes_and_rejects_next(api):
    """PRD §3.5: "When a non-`CONTACT_MADE` attempt pushes `attempt_count` up to
    the project's `max_attempts` and the case is not otherwise closed, the system
    auto-closes the case to `MAX_ATTEMPTS`: the area's `in_progress_case_count`
    decrements by one, its `max_attempts_case_count` increments by one, the active
    assignment is released, and coverage is recomputed."
    PRD §3.5: "an attempt beyond that boundary is refused with
    `ERR_MAX_ATTEMPTS_REACHED`."

    With max_attempts=2, the 2nd NO_ONE_HOME attempt closes the case; a 3rd is
    refused.

    Design: Difficulty/boundary_precision_check/max_attempts_boundary_close
    """
    ctx = setup_assigned_case(max_attempts=2)
    en_id = ctx["enumerator"]["id"]
    log_attempt(ctx["case"]["id"], en_id, mode="PHONE",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="NO_ONE_HOME")
    log_attempt(ctx["case"]["id"], en_id, mode="PHONE",
                window_start="2026-03-01T15:00:00Z", window_end="2026-03-01T15:30:00Z",
                disposition="NO_ONE_HOME")

    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "MAX_ATTEMPTS"
    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["max_attempts_case_count"] == 1

    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="PHONE", window_start="2026-03-01T20:00:00Z",
                               window_end="2026-03-01T20:30:00Z", disposition="NO_ONE_HOME"),
        make_enumerator_headers(en_id))
    validate_error(res, "ERR_MAX_ATTEMPTS_REACHED", expected_status=409)


def test_below_max_attempts_boundary_stays_in_progress(api):
    """PRD §3.5: "Once a case is `IN_PROGRESS`, a further attempt with
    `NO_ONE_HOME`, `APPOINTMENT_SET`, `LANGUAGE_BARRIER`, or `CONTACT_MADE` keeps
    it `IN_PROGRESS` — the revisit loop — and is permitted only while
    `attempt_count` remains below the project's `max_attempts`".

    With max_attempts=2, after just the 1st NO_ONE_HOME attempt the case is still
    IN_PROGRESS with attempt_count 1 (below the boundary).

    Design: Difficulty/boundary_precision_check/max_attempts_boundary_close
    """
    ctx = setup_assigned_case(max_attempts=2)
    en_id = ctx["enumerator"]["id"]
    log_attempt(ctx["case"]["id"], en_id, mode="PHONE",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="NO_ONE_HOME")
    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "IN_PROGRESS"
    assert case["attempt_count"] == 1
