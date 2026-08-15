"""Survey wave lifecycle: arm guard, open-fielding window, terminal lockdown,
early-close rate gate, close cascade visibility."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_cell, create_panelist, create_locked_instrument, create_wave,
    create_armed_wave, create_fielding_wave, dispatch_invitation, submit_response,
    set_clock,
)

PM = TEST_USERS["panel_manager"]
DA = TEST_USERS["data_analyst"]


def test_wave_arm_requires_instrument_locked(api):
    """PRD §3.4: "Arming readies a wave and is guarded by three checks: the
    instrument must be `LOCKED` (else `ERR_INSTRUMENT_NOT_LOCKED`); every locale in
    its `required_locales` must hold a `CERTIFIED` translation at the instrument's
    current `revision` (else `ERR_TRANSLATION_NOT_CERTIFIED`); and the current time
    must not yet be past `opens_at` (else `ERR_WAVE_WINDOW_NOT_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/wave_arm_requires_instrument_locked
    """
    from test_helpers import (
        create_instrument_payload, create_translation_payload,
    )
    SD = TEST_USERS["survey_designer"]
    instr = validate_success(api.create_instrument(create_instrument_payload(), SD), 201)
    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    tr = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="en"), SD), 201)
    validate_success(api.certify_translation(tr["id"], SD), 200)
    validate_success(api.approve_instrument(instr["id"], SD), 200)

    wave = create_wave(instr["id"])
    err = validate_error(api.arm_wave(wave["id"], PM),
                         ApiErrorId.ERR_INSTRUMENT_NOT_LOCKED)
    assert err["error_id"] == "ERR_INSTRUMENT_NOT_LOCKED"

    validate_success(api.lock_instrument(instr["id"], SD), 200)
    armed = validate_success(api.arm_wave(wave["id"], PM), 200)
    assert armed["status"] == "ARMED"


def test_wave_arm_rejected_at_each_pre_lock_status(api):
    """PRD §3.4: "Arming readies a wave and is guarded by three checks: the
    instrument must be `LOCKED` (else `ERR_INSTRUMENT_NOT_LOCKED`) ..."

    Design: Difficulty/cross_entity_state_dependency/wave_arm_requires_instrument_locked
    """
    from test_helpers import create_instrument_payload, create_translation_payload
    SD = TEST_USERS["survey_designer"]
    instr = validate_success(api.create_instrument(create_instrument_payload(), SD), 201)

    # Instrument DRAFT: arm fails.
    wave1 = create_wave(instr["id"])
    err = validate_error(api.arm_wave(wave1["id"], PM),
                         ApiErrorId.ERR_INSTRUMENT_NOT_LOCKED)
    assert err["error_id"] == "ERR_INSTRUMENT_NOT_LOCKED"

    # Instrument APPROVED (certified but not locked): arm still fails.
    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    tr = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="en"), SD), 201)
    validate_success(api.certify_translation(tr["id"], SD), 200)
    validate_success(api.approve_instrument(instr["id"], SD), 200)
    wave2 = create_wave(instr["id"])
    err2 = validate_error(api.arm_wave(wave2["id"], PM),
                          ApiErrorId.ERR_INSTRUMENT_NOT_LOCKED)
    assert err2["error_id"] == "ERR_INSTRUMENT_NOT_LOCKED"

    # After lock, the same arm call succeeds.
    validate_success(api.lock_instrument(instr["id"], SD), 200)
    armed = validate_success(api.arm_wave(wave2["id"], PM), 200)
    assert armed["status"] == "ARMED"


def test_wave_arm_twice_returns_409(api):
    """PRD §3.4: "Other wave moves are invalid: arming an already-`ARMED` wave or
    cancelling a `FIELDING` one is rejected with `ERR_WAVE_INVALID_STATE` ..."

    Design: Corner/state_machines/corner_wave_arm_twice_returns_409
    """
    instr = create_locked_instrument()
    wave = create_armed_wave(instr["id"])
    err = validate_error(api.arm_wave(wave["id"], PM),
                         ApiErrorId.ERR_WAVE_INVALID_STATE)
    assert err["error_id"] == "ERR_WAVE_INVALID_STATE"
    after = validate_success(api.get_wave(wave["id"], PM), 200)
    assert after["status"] == "ARMED"


def test_cancelled_wave_terminal_lockdown(api):
    """PRD §3.4: "`PUBLISHED` and `CANCELLED` are terminal — any further transition
    attempt against them fails with `ERR_WAVE_ALREADY_TERMINAL`."

    Design: Corner/state_machines/corner_cancelled_wave_terminal_lockdown
    """
    instr = create_locked_instrument()
    wave = create_wave(instr["id"])
    cancelled = validate_success(api.cancel_wave(wave["id"], PM), 200)
    assert cancelled["status"] == "CANCELLED"

    err_arm = validate_error(api.arm_wave(wave["id"], PM),
                             ApiErrorId.ERR_WAVE_ALREADY_TERMINAL)
    assert err_arm["error_id"] == "ERR_WAVE_ALREADY_TERMINAL"
    err_close = validate_error(api.close_wave(wave["id"], PM),
                               ApiErrorId.ERR_WAVE_ALREADY_TERMINAL)
    assert err_close["error_id"] == "ERR_WAVE_ALREADY_TERMINAL"


def test_open_fielding_window_and_arm_errors(api):
    """PRD §3.4: "Opening fielding moves `ARMED` → `FIELDING` and requires the
    current time to fall within the declared window inclusive of both bounds —
    outside it, `ERR_WAVE_WINDOW_NOT_OPEN` — and attempting it from any status
    other than `ARMED` is `ERR_WAVE_NOT_ARMED`."

    Design: Corner/errors/corner_open_fielding_window_and_arm_errors
    """
    instr = create_locked_instrument()
    w1 = create_wave(instr["id"])                       # stays DRAFT
    w2 = create_armed_wave(instr["id"])                 # ARMED; clock still 2026-08-01
    err1 = validate_error(api.open_fielding(w1["id"], PM),
                          ApiErrorId.ERR_WAVE_NOT_ARMED)
    assert err1["error_id"] == "ERR_WAVE_NOT_ARMED"
    # opens_at is 2026-08-02; the startup clock reads 2026-08-01 -> outside window.
    err2 = validate_error(api.open_fielding(w2["id"], PM),
                          ApiErrorId.ERR_WAVE_WINDOW_NOT_OPEN)
    assert err2["error_id"] == "ERR_WAVE_WINDOW_NOT_OPEN"


def test_wave_early_close_min_rate_boundary(api):
    """PRD §3.4: "One of two gates must then hold: either the current time is
    strictly past `closes_at`, or the wave closes early with at least one invitation
    dispatched and the ratio of `completed_count` to `invited_count` at least
    `min_response_rate`; failing both yields `ERR_MIN_RESPONSE_NOT_MET`."

    Design: Corner/state_machines/corner_wave_early_close_min_rate_boundary
    """
    ca = create_cell(target_size=5)
    cb = create_cell(target_size=5, age_band="AGE_30_44", tenure_bucket="OWNER")
    p1 = validate_success(api.enroll_panelist(create_panelist()["id"], PM), 200)
    p2 = validate_success(api.enroll_panelist(create_panelist()["id"], PM), 200)
    p3 = validate_success(api.enroll_panelist(
        create_panelist(age_band="AGE_30_44", tenure_bucket="OWNER")["id"], PM), 200)
    p4 = validate_success(api.enroll_panelist(
        create_panelist(age_band="AGE_30_44", tenure_bucket="OWNER")["id"], PM), 200)
    instr = create_locked_instrument()
    wa = create_fielding_wave(instr["id"], min_response_rate=0.5,
                              closes_at="2026-08-20T00:00:00Z")
    # The clock is parked at 2026-08-03 after wa opened fielding; arming
    # requires "the current time must not yet be past opens_at" (PRD §3.4),
    # so wb's window opens at 08-03 rather than the earlier default.
    wb = create_fielding_wave(instr["id"], min_response_rate=0.75,
                              opens_at="2026-08-03T00:00:00Z",
                              closes_at="2026-08-20T00:00:00Z")
    inva1 = dispatch_invitation(wa["id"], p1["id"])
    dispatch_invitation(wa["id"], p2["id"])
    invb1 = dispatch_invitation(wb["id"], p3["id"])
    dispatch_invitation(wb["id"], p4["id"])
    submit_response(inva1["id"])    # WA: 1 completed of 2 -> rate 0.5 == min
    submit_response(invb1["id"])    # WB: 1 completed of 2 -> rate 0.5 < 0.75

    closed = validate_success(api.close_wave(wa["id"], PM), 200)
    assert closed["status"] == "CLOSED"
    err = validate_error(api.close_wave(wb["id"], PM),
                         ApiErrorId.ERR_MIN_RESPONSE_NOT_MET)
    assert err["error_id"] == "ERR_MIN_RESPONSE_NOT_MET"
    wb_after = validate_success(api.get_wave(wb["id"], PM), 200)
    assert wb_after["status"] == "FIELDING"


def test_close_cascade_immediately_visible(api):
    """PRD §3.4: "A successful close cascades in three hops. First, every invitation
    of the wave still `SENT` moves to `EXPIRED`. Second, for each affected panelist
    the `missed_streak` is recomputed by the chronological walk of §3.2 — each
    expiry extends its owner's streak — and each expiry releases its reservation,
    so the home cells' `reserved_count` re-derives."

    Design: Corner/consistency_model/corner_close_cascade_immediately_visible
    """
    cell = create_cell(target_size=5)
    p1 = validate_success(api.enroll_panelist(create_panelist()["id"], PM), 200)
    p2 = validate_success(api.enroll_panelist(create_panelist()["id"], PM), 200)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv1 = dispatch_invitation(wave["id"], p1["id"])
    inv2 = dispatch_invitation(wave["id"], p2["id"])
    set_clock("2026-08-11T00:00:00Z")

    closed = validate_success(api.close_wave(wave["id"], PM), 200)
    assert closed["status"] == "CLOSED"
    i1 = validate_success(api.get_invitation(inv1["id"], PM), 200)
    i2 = validate_success(api.get_invitation(inv2["id"], PM), 200)
    assert i1["status"] == "EXPIRED"
    assert i2["status"] == "EXPIRED"
    cell_after = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert cell_after["reserved_count"] == 0
