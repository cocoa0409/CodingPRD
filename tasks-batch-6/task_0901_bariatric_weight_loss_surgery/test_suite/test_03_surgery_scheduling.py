"""Surgery scheduling: the gate sequence, resource-overlap rules, and bundle pricing.

Covers difficulty queue A (state-vs-temporal precedence, cleared dependency, room
buffer overlap, surgeon strict overlap, estimate-vs-final bundle) and corner queue B
(FK not-found, credentialing, closed room, time-window, past booking).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    setup_scheduled_case, create_cleared_self_pay_program, create_program_for_new_patient,
    create_surgeon, create_operating_room, program_version, get_program,
    schedule_surgery_case_payload, complete_surgery_case_payload, make_surgeon_headers,
)

PC = TEST_USERS["program_coordinator_headers"]


def _schedule(api, program_id, room_id, surgeon_id, version, **overrides):
    payload = schedule_surgery_case_payload(room_id, surgeon_id, version, **overrides)
    return api.schedule_surgery_case(program_id, payload, PC)


# ---------------- Difficulty A: PROGRAM_NOT_CLEARED beats OR_ROOM_CONFLICT ----------------

def test_schedule_not_cleared_beats_room_conflict(api):
    """PRD §3.4: "Scheduling enforces a sequence of gates, and the first to fail
    determines the rejection. The program must be in CLEARED; if it is not, the request
    is rejected with ERR_PROGRAM_NOT_CLEARED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_program_not_cleared_beats_room_conflict
    """
    ctx = setup_scheduled_case(api)  # program B CLEARED with a case in room R [08:00,09:30)
    prog_a = create_program_for_new_patient(api, payment_pathway="SELF_PAY")  # SCREENING
    v_a = program_version(api, prog_a["id"])
    resp = _schedule(api, prog_a["id"], ctx["room"]["id"], ctx["surgeon"]["id"], v_a,
                     scheduled_start="2026-06-15T08:15:00Z", scheduled_end="2026-06-15T09:45:00Z")
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_CLEARED.value)


def test_schedule_not_cleared_leaves_program_in_screening(api):
    """PRD §3.4: "The program must be in CLEARED; if it is not, the request is rejected
    with ERR_PROGRAM_NOT_CLEARED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_program_not_cleared_beats_room_conflict
    """
    ctx = setup_scheduled_case(api)
    prog_a = create_program_for_new_patient(api, payment_pathway="SELF_PAY")
    v_a = program_version(api, prog_a["id"])
    _schedule(api, prog_a["id"], ctx["room"]["id"], ctx["surgeon"]["id"], v_a,
              scheduled_start="2026-06-15T08:15:00Z", scheduled_end="2026-06-15T09:45:00Z")
    after = get_program(api, prog_a["id"])
    assert after["status"] == "SCREENING", f"program must stay SCREENING, got {after['status']}"


# ---------------- Difficulty A: scheduling depends on CLEARED ----------------

def test_schedule_fails_while_clearance_in_progress(api):
    """PRD §3.4: "Once a program is CLEARED, the coordinator schedules its surgery ...
    The program must be in CLEARED; if it is not, the request is rejected with
    ERR_PROGRAM_NOT_CLEARED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/schedule_depends_on_program_cleared
    """
    from test_helpers import create_clearance_in_progress_program
    prog = create_clearance_in_progress_program(api, payment_pathway="SELF_PAY")
    surgeon = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    room = create_operating_room(api)
    v = program_version(api, prog["id"])
    resp = _schedule(api, prog["id"], room["id"], surgeon["id"], v)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_CLEARED.value)


def test_schedule_succeeds_once_cleared(api):
    """PRD §3.4: "A successful schedule creates a surgery case in SCHEDULED, computes its
    estimated_bundle_cents, moves the program from CLEARED to SURGERY_SCHEDULED, and
    increments the program's version."

    Design: Difficulty/cross_entity_state_dependency/schedule_depends_on_program_cleared
    """
    ctx = setup_scheduled_case(api)
    assert ctx["case"]["status"] == "SCHEDULED", f"expected SCHEDULED, got {ctx['case']['status']}"
    assert ctx["program"]["status"] == "SURGERY_SCHEDULED", \
        f"expected SURGERY_SCHEDULED, got {ctx['program']['status']}"


# ---------------- Difficulty A: OR room buffer-extended conflict ----------------

def test_room_turnover_buffer_conflict_rejected(api):
    """PRD §3.4: "a new booking conflicts with any non-cancelled case already in that
    room when the new start falls before the existing case's end extended forward by the
    buffer, and the existing start falls before the new booking's end extended forward by
    the buffer ... any closer and the request is rejected with ERR_OR_ROOM_CONFLICT
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/or_room_turnover_buffer_conflict
    """
    ctx = setup_scheduled_case(api)  # case in room R [08:00,09:30), buffer 30
    surgeon2 = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    prog2 = create_cleared_self_pay_program(api)
    v2 = program_version(api, prog2["id"])
    resp = _schedule(api, prog2["id"], ctx["room"]["id"], surgeon2["id"], v2,
                     scheduled_start="2026-06-15T09:45:00Z", scheduled_end="2026-06-15T10:45:00Z")
    validate_error(resp, ApiErrorId.ERR_OR_ROOM_CONFLICT.value)


def test_room_buffer_conflict_leaves_second_program_cleared(api):
    """PRD §3.4: "two cases in the same room must be separated by at least the room's
    turnover buffer; any closer and the request is rejected with ERR_OR_ROOM_CONFLICT
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/or_room_turnover_buffer_conflict
    """
    ctx = setup_scheduled_case(api)
    surgeon2 = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    prog2 = create_cleared_self_pay_program(api)
    v2 = program_version(api, prog2["id"])
    _schedule(api, prog2["id"], ctx["room"]["id"], surgeon2["id"], v2,
              scheduled_start="2026-06-15T09:45:00Z", scheduled_end="2026-06-15T10:45:00Z")
    after = get_program(api, prog2["id"])
    assert after["status"] == "CLEARED", f"rejected schedule must leave program CLEARED, got {after['status']}"


# ---------------- Difficulty A: surgeon strict (no-buffer) overlap ----------------

def test_surgeon_double_booking_overlap_rejected(api):
    """PRD §3.4: "a new booking conflicts with any non-cancelled case for the same
    surgeon when the two intervals strictly overlap — the new start falls before the
    existing end and the existing start falls before the new end — with back-to-back
    adjacency ... explicitly allowed. A surgeon overlap is rejected with
    ERR_SURGEON_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/surgeon_double_booking_no_buffer_overlap
    """
    ctx = setup_scheduled_case(api)  # surgeon S, room1 [08:00,09:30)
    room2 = create_operating_room(api)
    prog2 = create_cleared_self_pay_program(api)
    v2 = program_version(api, prog2["id"])
    resp = _schedule(api, prog2["id"], room2["id"], ctx["surgeon"]["id"], v2,
                     scheduled_start="2026-06-15T09:00:00Z", scheduled_end="2026-06-15T10:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SURGEON_CONFLICT.value)


def test_surgeon_overlap_leaves_second_program_cleared(api):
    """PRD §3.4: "The surgeon is protected by a stricter but bufferless rule ... A
    surgeon overlap is rejected with ERR_SURGEON_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/surgeon_double_booking_no_buffer_overlap
    """
    ctx = setup_scheduled_case(api)
    room2 = create_operating_room(api)
    prog2 = create_cleared_self_pay_program(api)
    v2 = program_version(api, prog2["id"])
    _schedule(api, prog2["id"], room2["id"], ctx["surgeon"]["id"], v2,
              scheduled_start="2026-06-15T09:00:00Z", scheduled_end="2026-06-15T10:00:00Z")
    after = get_program(api, prog2["id"])
    assert after["status"] == "CLEARED", f"rejected schedule must leave program CLEARED, got {after['status']}"


# ---------------- Difficulty A: estimate vs final bundle ----------------

def test_schedule_stamps_estimated_bundle(api):
    """PRD §3.4: "Take the procedure's base price in cents — 1,800,000 for
    SLEEVE_GASTRECTOMY ... and apply a BMI surcharge multiplier: 15% when the program's
    baseline_bmi is at or above 50, otherwise 8% when it is at or above 40, otherwise no
    surcharge. The estimate is the base multiplied by one plus that surcharge fraction,
    rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/case_bundle_estimate_vs_final
    """
    ctx = setup_scheduled_case(api)  # SLEEVE, FEMALE 170/120 => baseline_bmi 41.5 (8% surcharge)
    assert ctx["case"]["estimated_bundle_cents"] == 1944000, \
        f"expected 1944000, got {ctx['case']['estimated_bundle_cents']}"


def test_complete_computes_final_bundle_with_overtime(api):
    """PRD §3.5: "any minutes of actual_or_minutes beyond the procedure's standard
    allotment (90 minutes for SLEEVE_GASTRECTOMY ...) are billed at 25,000 cents per
    minute ... This overtime term is added after the surcharge rounding, not folded into
    it."

    Design: Difficulty/dual_variant_calc/case_bundle_estimate_vs_final
    """
    ctx = setup_scheduled_case(api)
    est = ctx["case"]["estimated_bundle_cents"]
    surgeon_headers = make_surgeon_headers(ctx["surgeon"]["id"])
    data = validate_success(api.complete_surgery_case(
        ctx["case"]["id"], complete_surgery_case_payload(actual_or_minutes=120), surgeon_headers))
    assert data["final_bundle_cents"] == 2694000, \
        f"expected 2694000, got {data['final_bundle_cents']}"
    assert data["final_bundle_cents"] != est, "final bundle must differ from estimate on overtime"


# ---------------- Corner B: FK not-found on scheduling ----------------

def test_surgeon_not_found_on_schedule(api):
    """PRD §2.8: "body foreign keys (... surgeon_id ...) are resolved, with the
    corresponding not-found error (404) when any does not reference an existing row ...
    a surgeon ERR_SURGEON_NOT_FOUND".

    Design: Corner/errors/surgeon_not_found_on_schedule_returns_404
    """
    room = create_operating_room(api)
    prog = create_program_for_new_patient(api, payment_pathway="SELF_PAY")
    v = program_version(api, prog["id"])
    resp = _schedule(api, prog["id"], room["id"], NON_EXISTENT_UUID, v)
    validate_error(resp, ApiErrorId.ERR_SURGEON_NOT_FOUND.value)


def test_operating_room_not_found_on_schedule(api):
    """PRD §2.8: "body foreign keys (... operating_room_id ...) are resolved, with the
    corresponding not-found error (404) ... an operating room ERR_OPERATING_ROOM_NOT_FOUND".

    Design: Corner/errors/operating_room_not_found_on_schedule_returns_404
    """
    surgeon = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    prog = create_program_for_new_patient(api, payment_pathway="SELF_PAY")
    v = program_version(api, prog["id"])
    resp = _schedule(api, prog["id"], NON_EXISTENT_UUID, surgeon["id"], v)
    validate_error(resp, ApiErrorId.ERR_OPERATING_ROOM_NOT_FOUND.value)


# ---------------- Corner B: business constraints ----------------

def test_surgeon_not_credentialed_for_procedure(api):
    """PRD §3.4: "The named surgeon must be credentialed for the requested procedure —
    that is, the procedure_type must appear in the surgeon's credentialed_procedures —
    otherwise the request is rejected with ERR_SURGEON_NOT_CREDENTIALED (HTTP 409)."

    Design: Corner/endpoints/surgeon_not_credentialed_for_procedure_returns_409
    """
    prog = create_cleared_self_pay_program(api)
    surgeon = create_surgeon(api, credentialed_procedures=["GASTRIC_BYPASS"])
    room = create_operating_room(api)
    v = program_version(api, prog["id"])
    resp = _schedule(api, prog["id"], room["id"], surgeon["id"], v, procedure_type="SLEEVE_GASTRECTOMY")
    validate_error(resp, ApiErrorId.ERR_SURGEON_NOT_CREDENTIALED.value)


def test_schedule_into_closed_room(api):
    """PRD §3.4: "The target operating room must have status of OPEN; scheduling into a
    room whose status is CLOSED is rejected with ERR_ROOM_CLOSED (HTTP 409)."

    Design: Corner/endpoints/schedule_into_closed_room_returns_409
    """
    prog = create_cleared_self_pay_program(api)
    surgeon = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    room = create_operating_room(api, status="CLOSED")
    v = program_version(api, prog["id"])
    resp = _schedule(api, prog["id"], room["id"], surgeon["id"], v)
    validate_error(resp, ApiErrorId.ERR_ROOM_CLOSED.value)


def test_schedule_end_not_after_start(api):
    """PRD §3.4: "The booking window must be valid: scheduled_end must be strictly after
    scheduled_start, or the request is rejected with ERR_INVALID_TIME_WINDOW (HTTP 422)."

    Design: Corner/endpoints/schedule_end_not_after_start_returns_422
    """
    prog = create_cleared_self_pay_program(api)
    surgeon = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    room = create_operating_room(api)
    v = program_version(api, prog["id"])
    resp = _schedule(api, prog["id"], room["id"], surgeon["id"], v,
                     scheduled_start="2026-06-15T08:00:00Z", scheduled_end="2026-06-15T08:00:00Z")
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)


def test_schedule_start_in_past(api):
    """PRD §3.4: "The booking must not be in the past: scheduled_start must be at or after
    the current logical-clock instant, or the request is rejected with ERR_SURGERY_IN_PAST
    (HTTP 422)."

    Design: Corner/endpoints/schedule_start_in_past_returns_422
    """
    prog = create_cleared_self_pay_program(api)
    surgeon = create_surgeon(api, credentialed_procedures=["SLEEVE_GASTRECTOMY"])
    room = create_operating_room(api)
    v = program_version(api, prog["id"])
    resp = _schedule(api, prog["id"], room["id"], surgeon["id"], v,
                     scheduled_start="2026-04-01T08:00:00Z", scheduled_end="2026-04-01T09:30:00Z")
    validate_error(resp, ApiErrorId.ERR_SURGERY_IN_PAST.value)
