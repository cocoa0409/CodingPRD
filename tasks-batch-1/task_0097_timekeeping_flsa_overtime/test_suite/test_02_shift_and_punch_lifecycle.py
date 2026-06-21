"""Shift scheduling, punch open/close/void lifecycle, detention, and the
temporal-overlap interval semantics (punch closed-interval vs shift half-open).

Covers Queue B state_machine/validation instances plus Queue A
boundary_precision_check (detention) and resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_shift_payload, open_punch_payload, close_punch_payload,
    setup_ca_employer, create_employee as mk_employee,
    create_scheduled_shift, create_closed_punch, create_open_punch,
    make_employee_headers,
    SUP1,
)


# ─── Shift / punch state machine (Queue B) ────────────

def test_cancel_already_cancelled_shift_invalid_state(api):
    """PRD §3.2: "A Supervisor may cancel a shift only while it is still SCHEDULED
    with no punch opened, moving it to CANCELLED; an attempt to cancel once the
    shift has progressed is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_already_cancelled_shift_invalid_state
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift = create_scheduled_shift(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    validate_success(api.cancel_shift(shift["id"], SUP1), 200)
    resp = api.cancel_shift(shift["id"], SUP1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_close_already_closed_punch_invalid_state(api):
    """PRD §3.2: "Closing is permitted only while the punch is OPEN, and the
    clock-out must fall strictly after the effective clock-in".

    Design: Corner/state_machines/close_already_closed_punch_invalid_state
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    resp = api.close_punch(punch["id"], close_punch_payload("2026-06-01T17:00:00Z"),
                           make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_void_open_punch_reverts_shift_to_scheduled(api):
    """PRD §3.3: "Voiding an OPEN punch sets it to VOIDED and, if its shift had no
    other punch, reverts that shift back to SCHEDULED."

    Design: Corner/state_machines/void_open_punch_reverts_shift_to_scheduled
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift, punch = create_open_punch(api, employee["id"], worksite["id"],
                                     "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                     "2026-06-01T08:00:00Z")
    voided = validate_success(api.void_punch(punch["id"], SUP1), 200)
    assert voided["status"] == "VOIDED"
    shift_after = validate_success(api.get_shift(shift["id"], SUP1), 200)
    assert shift_after["status"] == "SCHEDULED"


# ─── Validation: scheduling and closing (Queue B) ─────

def test_shift_end_before_start_invalid_schedule(api):
    """PRD §3.2: "fixing its scheduled_start and scheduled_end as ISO 8601 UTC
    instants; the end must fall strictly after the start, and a schedule that does
    not satisfy this is rejected with ERR_INVALID_SCHEDULE."

    Design: Corner/validations/shift_create_end_before_start_invalid_schedule
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    resp = api.create_shift(
        create_shift_payload(employee["id"], worksite["id"],
                             "2026-06-01T16:00:00Z", "2026-06-01T08:00:00Z"), SUP1)
    validate_error(resp, ApiErrorId.ERR_INVALID_SCHEDULE.value, 422)


def test_close_punch_negative_duration_rejected(api):
    """PRD §3.2: "the clock-out must fall strictly after the effective clock-in, or
    the close is rejected with ERR_NEGATIVE_DURATION."

    Design: Corner/validations/close_punch_negative_duration
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift, punch = create_open_punch(api, employee["id"], worksite["id"],
                                     "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                     "2026-06-01T08:00:00Z")
    resp = api.close_punch(punch["id"], close_punch_payload("2026-06-01T07:00:00Z"),
                           make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_DURATION.value, 422)


def test_second_open_punch_rejected(api):
    """PRD §3.2: "when the employee has no other OPEN punch anywhere — a second
    concurrent open is rejected with ERR_PUNCH_ALREADY_OPEN."

    Design: Corner/validations/second_open_punch_rejected
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_open_punch(api, employee["id"], worksite["id"],
                      "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z", "2026-06-01T08:00:00Z")
    shift_b = create_scheduled_shift(api, employee["id"], worksite["id"],
                                     "2026-06-01T13:00:00Z", "2026-06-01T18:00:00Z")
    resp = api.open_punch(shift_b["id"], open_punch_payload("2026-06-01T13:00:00Z"),
                          make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_PUNCH_ALREADY_OPEN.value, 409)


# ─── Detention boundary (Queue A boundary_precision_check) ──

def test_detention_at_15_minutes_not_flagged(api):
    """PRD §3.2: "detention_minutes becomes the whole minutes by which the actual
    clock-out exceeds scheduled_end, never going below zero, and detention_flagged
    becomes true precisely when detention_minutes exceeds the fifteen-minute grace
    allowance, marking unauthorized over-detention."

    Design: Difficulty/boundary_precision_check/detention_flag_at_15_vs_16_minutes
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift, punch = create_open_punch(api, employee["id"], worksite["id"],
                                     "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                     "2026-06-01T08:00:00Z")
    # clock out exactly 15 minutes past scheduled_end (16:15): grace is strict (>15).
    validate_success(api.close_punch(punch["id"], close_punch_payload("2026-06-01T16:15:00Z"),
                                     make_employee_headers(employee["id"])), 200)
    shift_after = validate_success(api.get_shift(shift["id"], SUP1), 200)
    assert shift_after["detention_minutes"] == 15
    assert shift_after["detention_flagged"] is False


def test_detention_at_16_minutes_flagged(api):
    """PRD §3.2: "detention_flagged becomes true precisely when detention_minutes
    exceeds the fifteen-minute grace allowance, marking unauthorized over-detention."

    Design: Difficulty/boundary_precision_check/detention_flag_at_15_vs_16_minutes
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift, punch = create_open_punch(api, employee["id"], worksite["id"],
                                     "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                     "2026-06-01T08:00:00Z")
    # clock out 16 minutes past scheduled_end (16:16): exceeds the 15-minute grace.
    validate_success(api.close_punch(punch["id"], close_punch_payload("2026-06-01T16:16:00Z"),
                                     make_employee_headers(employee["id"])), 200)
    shift_after = validate_success(api.get_shift(shift["id"], SUP1), 200)
    assert shift_after["detention_minutes"] == 16
    assert shift_after["detention_flagged"] is True


# ─── Temporal overlap (Queue A resource_temporal_overlap) ──

def test_punch_overlap_at_closed_interval_changeover_rejected(api):
    """PRD §3.2: "here the interval is treated as closed on both ends: a new
    clock_in exactly equal to a prior punch's clock_out does collide, because a
    worker cannot be in two places at the instant of changeover. Such a collision
    is rejected with ERR_PUNCH_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/punch_overlap_closed_interval_changeover
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    shift_2 = create_scheduled_shift(api, employee["id"], worksite["id"],
                                     "2026-06-01T16:00:00Z", "2026-06-01T20:00:00Z")
    resp = api.open_punch(shift_2["id"], open_punch_payload("2026-06-01T16:00:00Z"),
                          make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_PUNCH_OVERLAP.value, 409)


def test_punch_overlap_strictly_inside_prior_interval_rejected(api):
    """PRD §3.2: "the new punch's interval may not overlap any existing
    non-VOIDED, CLOSED punch for the same employee, and here the interval is treated
    as closed on both ends ... Such a collision is rejected with ERR_PUNCH_OVERLAP."

    A clock_in strictly inside a prior CLOSED punch's interval (12:00, within
    08:00–16:00) collides just as the changeover instant does.

    Design: Difficulty/resource_temporal_overlap/punch_overlap_closed_interval_changeover
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    # The second shift must not overlap the first (now-CLOSED) shift's half-open
    # window, so it is scheduled back-to-back (16:00-20:00). The punch overlap rule
    # (§3.2) is independent of the shift window: a clock_in of 12:00 falls strictly
    # inside the prior CLOSED punch's 08:00-16:00 interval and so collides.
    shift_2 = create_scheduled_shift(api, employee["id"], worksite["id"],
                                     "2026-06-01T16:00:00Z", "2026-06-01T20:00:00Z")
    resp = api.open_punch(shift_2["id"], open_punch_payload("2026-06-01T12:00:00Z"),
                          make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_PUNCH_OVERLAP.value, 409)


def test_shift_overlap_straddling_rejected_adjacency_allowed(api):
    """PRD §3.2: "A new shift may not overlap an existing non-CANCELLED shift for
    the same employee, where shift intervals are treated as half-open — the span
    runs from the start up to but not including the end — so two shifts that meet
    exactly, one ending at the instant the next begins, do not overlap; a genuine
    overlap is rejected with ERR_SHIFT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_adjacency_allowed
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    # 08:00-16:00 and a back-to-back 16:00-20:00 (adjacency must be allowed).
    create_scheduled_shift(api, employee["id"], worksite["id"],
                           "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    create_scheduled_shift(api, employee["id"], worksite["id"],
                           "2026-06-01T16:00:00Z", "2026-06-01T20:00:00Z")
    # A genuinely straddling shift (15:00-18:00) overlaps both → rejected.
    resp = api.create_shift(
        create_shift_payload(employee["id"], worksite["id"],
                             "2026-06-01T15:00:00Z", "2026-06-01T18:00:00Z"), SUP1)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value, 409)


def test_shift_back_to_back_adjacency_allowed(api):
    """PRD §3.2: "shift intervals are treated as half-open — the span runs from the
    start up to but not including the end — so two shifts that meet exactly, one
    ending at the instant the next begins, do not overlap".

    The accepting side of the half-open semantics: a shift starting exactly when the
    prior one ends (16:00) is created successfully (201), not rejected.

    Design: Difficulty/resource_temporal_overlap/shift_overlap_half_open_adjacency_allowed
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_scheduled_shift(api, employee["id"], worksite["id"],
                           "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    resp = api.create_shift(
        create_shift_payload(employee["id"], worksite["id"],
                             "2026-06-01T16:00:00Z", "2026-06-01T20:00:00Z"), SUP1)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
