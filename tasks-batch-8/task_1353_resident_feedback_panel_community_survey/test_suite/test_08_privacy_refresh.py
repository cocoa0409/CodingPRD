"""Privacy holds (FULL_SUPPRESS cascade, partial release, duplicate hold,
release-twice) and refresh runs (abort lockdown, attrition reconciliation,
attrition -> forfeit -> pool-credit cascade)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_cell, create_panelist, create_locked_instrument, create_fielding_wave,
    create_wave, dispatch_invitation, submit_response, accept_response,
    get_award_for_response, set_clock, create_privacy_hold_payload,
    create_refresh_run_payload, assert_timestamp_eq,
)

PM = TEST_USERS["panel_manager"]
DA = TEST_USERS["data_analyst"]
IC = TEST_USERS["incentive_clerk"]
PO = TEST_USERS["privacy_officer"]

from test_helpers import api_client as _api


def _enroll(pid):
    return validate_success(_api.enroll_panelist(pid, PM), 200)


def _standard_fielding(closes_at="2026-08-10T00:00:00Z", **wave_kw):
    cell = create_cell(target_size=5)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], closes_at=closes_at, **wave_kw)
    return cell, p1, instr, wave


def _invite_expire_wave(instr_id, p1_id, opens_at, closes_at, invite_at, close_at):
    """One wave in which p1 is invited and never responds; closed past closes_at
    so the invitation expires. Returns the wave."""
    wave = create_wave(instr_id, opens_at=opens_at, closes_at=closes_at)
    # PRD §3.4: arming requires "the current time must not yet be past
    # opens_at" — arm while the clock is still at or before opens_at, then
    # advance into the fielding window.
    validate_success(_api.arm_wave(wave["id"], PM), 200)
    set_clock(invite_at)
    validate_success(_api.open_fielding(wave["id"], PM), 200)
    dispatch_invitation(wave["id"], p1_id)
    set_clock(close_at)
    return validate_success(_api.close_wave(wave["id"], PM), 200)


def _lapse_panelist_via_two_waves(instr_id, p1_id):
    """Drive p1 ACTIVE -> LAPSED: two consecutive expired waves."""
    _invite_expire_wave(instr_id, p1_id,
                        "2026-08-02T00:00:00Z", "2026-08-10T00:00:00Z",
                        "2026-08-03T00:00:00Z", "2026-08-11T00:00:00Z")
    _invite_expire_wave(instr_id, p1_id,
                        "2026-08-12T00:00:00Z", "2026-08-20T00:00:00Z",
                        "2026-08-13T00:00:00Z", "2026-08-21T00:00:00Z")


def test_privacy_hold_full_suppress_cascades(api):
    """PRD §3.9: "A `FULL_SUPPRESS` hold additionally suspends the panelist —
    `ACTIVE` → `SUSPENDED` — and moves their live `SENT` invitations to
    `SUPPRESSED`, with the affected cells' `reserved_count` re-derived." and
    "at most one `ACTIVE` hold may exist per panelist, and a second attempt fails
    with `ERR_PRIVACY_HOLD_EXISTS`."

    Design: Corner/state_machines/corner_privacy_hold_full_suppress_cascades
    """
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])

    hold = validate_success(api.create_privacy_hold(
        create_privacy_hold_payload(p1["id"], scope="FULL_SUPPRESS",
                                    reason="resident request"), PO), 201)
    p_after = validate_success(api.get_panelist(p1["id"], PO), 200)
    assert p_after["status"] == "SUSPENDED"
    inv_after = validate_success(api.get_invitation(inv["id"], PM), 200)
    assert inv_after["status"] == "SUPPRESSED"
    cell_after = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert cell_after["reserved_count"] == 0

    err = validate_error(api.create_privacy_hold(
        create_privacy_hold_payload(p1["id"], scope="NO_CONTACT", reason="second"),
        PO), ApiErrorId.ERR_PRIVACY_HOLD_EXISTS)
    assert err["error_id"] == "ERR_PRIVACY_HOLD_EXISTS"


def test_privacy_hold_release_reactivates_partially(api):
    """PRD §3.9: "Release is deliberately partial. Releasing moves a hold `ACTIVE` →
    `RELEASED` — any other hold status fails with `ERR_PRIVACY_HOLD_NOT_ACTIVE` —
    and when the released hold was `FULL_SUPPRESS` and no other `ACTIVE` hold
    remains for the panelist, the panelist returns `SUSPENDED` → `ACTIVE`.
    Suppressed invitations are never restored: the compensation is partial by
    policy, and the panelist's contact history is otherwise untouched."

    Design: Corner/state_machines/corner_privacy_hold_release_reactivates_partially
    """
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])
    hold = validate_success(api.create_privacy_hold(
        create_privacy_hold_payload(p1["id"], scope="FULL_SUPPRESS",
                                    reason="resident request"), PO), 201)

    released = validate_success(api.release_privacy_hold(hold["id"], PO), 200)
    assert released["status"] == "RELEASED"
    p_after = validate_success(api.get_panelist(p1["id"], PO), 200)
    assert p_after["status"] == "ACTIVE"
    inv_after = validate_success(api.get_invitation(inv["id"], PM), 200)
    assert inv_after["status"] == "SUPPRESSED"


def test_hold_release_twice_returns_409(api):
    """PRD §3.9: "Releasing moves a hold `ACTIVE` → `RELEASED` — any other hold
    status fails with `ERR_PRIVACY_HOLD_NOT_ACTIVE` ..."

    Design: Corner/errors/corner_hold_release_twice_returns_409
    """
    cell = create_cell(target_size=5)
    p1 = _enroll(create_panelist()["id"])
    hold = validate_success(api.create_privacy_hold(
        create_privacy_hold_payload(p1["id"], scope="NO_CONTACT", reason="check"),
        PO), 201)
    validate_success(api.release_privacy_hold(hold["id"], PO), 200)
    err = validate_error(api.release_privacy_hold(hold["id"], PO),
                         ApiErrorId.ERR_PRIVACY_HOLD_NOT_ACTIVE)
    assert err["error_id"] == "ERR_PRIVACY_HOLD_NOT_ACTIVE"


def test_refresh_run_abort_terminal_lockdown(api):
    """PRD §3.9: "Both apply and abort are possible only from `OPEN` — from any
    other status they fail with `ERR_REFRESH_RUN_NOT_OPEN` — and aborting moves
    `OPEN` → `ABORTED` with no side effects."

    Design: Corner/state_machines/corner_refresh_run_abort_terminal_lockdown
    """
    run = validate_success(api.create_refresh_run(
        create_refresh_run_payload(run_label="r1"), PM), 201)
    aborted = validate_success(api.abort_refresh_run(run["id"], PM), 200)
    assert aborted["status"] == "ABORTED"
    err = validate_error(api.apply_refresh_run(run["id"], PM),
                         ApiErrorId.ERR_REFRESH_RUN_NOT_OPEN)
    assert err["error_id"] == "ERR_REFRESH_RUN_NOT_OPEN"


def test_derived_counts_reconcile_on_attrition(api):
    """PRD §3.9: "Applying executes a three-hop cascade: every grace-expired
    `LAPSED` panelist moves `LAPSED` → `ATTRITED`; ... Each attrition also
    decrements the home cell's `active_count`, re-derives its status, and
    increments its `version` ..." and PRD §2.6: "A cell's `status` is never set by
    clients: it is `OPEN` while `active_count` is below `target_size` and
    `SATURATED` once `active_count` reaches or exceeds `target_size`, re-derived
    automatically on every count change and every target change ..."

    Design: Corner/complexity_layers/corner_derived_counts_reconcile_on_attrition
    """
    cell = create_cell(target_size=1)
    p1 = _enroll(create_panelist()["id"])
    cell_mid = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert cell_mid["status"] == "SATURATED"

    instr = create_locked_instrument()
    _lapse_panelist_via_two_waves(instr["id"], p1["id"])
    p_mid = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_mid["status"] == "LAPSED"

    set_clock("2026-10-01T00:00:00Z")  # lapsed 2026-08-21; 30-day default grace met
    run = validate_success(api.create_refresh_run(
        create_refresh_run_payload(run_label="rr"), PM), 201)
    applied = validate_success(api.apply_refresh_run(run["id"], PM), 200)
    assert applied["applied_attrition_count"] == 1

    cell_after = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert cell_after["active_count"] == 0
    assert cell_after["status"] == "OPEN"
    p_after = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_after["status"] == "ATTRITED"


def test_refresh_apply_attrition_forfeit_pool_credit_cascade(api):
    """PRD §3.9: "Applying executes a three-hop cascade: every grace-expired
    `LAPSED` panelist moves `LAPSED` → `ATTRITED`; each attrited panelist's
    `AUTHORIZED` awards move to `FORFEITED`; and each forfeiture credits its wave's
    `incentive_pool_available_cents` while debiting
    `incentive_pool_reserved_cents`." and "at creation the run computes
    `planned_attrition_count`, the number of `LAPSED` panelists whose `lapsed_at`
    is at least that many days in the past ..."

    Design: Difficulty/transitive_cascade/refresh_apply_attrition_forfeit_pool_credit_cascade
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()

    # W0: p1 answers (100%, 300s -> award 2000), ACCEPTED, award AUTHORIZED.
    w0 = create_fielding_wave(instr["id"], closes_at="2026-08-10T00:00:00Z")
    inv0 = dispatch_invitation(w0["id"], p1["id"])
    r0 = submit_response(inv0["id"])
    accept_response(r0["id"])
    award0 = get_award_for_response(r0["id"])
    validate_success(api.authorize_award(award0["id"], IC), 200)
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(w0["id"], PM), 200)

    # W1 expires (streak 1); W2 expires (streak 2 -> LAPSED at 2026-08-31).
    _invite_expire_wave(instr["id"], p1["id"],
                        "2026-08-12T00:00:00Z", "2026-08-20T00:00:00Z",
                        "2026-08-13T00:00:00Z", "2026-08-21T00:00:00Z")
    _invite_expire_wave(instr["id"], p1["id"],
                        "2026-08-22T00:00:00Z", "2026-08-30T00:00:00Z",
                        "2026-08-23T00:00:00Z", "2026-08-31T00:00:00Z")
    p_mid = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_mid["status"] == "LAPSED"
    assert_timestamp_eq(p_mid["lapsed_at"], "2026-08-31T00:00:00Z")

    set_clock("2026-10-01T00:00:00Z")  # 30 days past lapsed_at: grace met
    run = validate_success(api.create_refresh_run(
        create_refresh_run_payload(run_label="oct-refresh"), PM), 201)
    assert run["planned_attrition_count"] == 1

    applied = validate_success(api.apply_refresh_run(run["id"], PM), 200)
    assert applied["applied_attrition_count"] == 1
    assert applied["applied_forfeit_count"] == 1

    p_after = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_after["status"] == "ATTRITED"
    award_after = validate_success(api.get_award(award0["id"], IC), 200)
    assert award_after["payout_status"] == "FORFEITED"
    w0_after = validate_success(api.get_wave(w0["id"], PM), 200)
    assert w0_after["incentive_pool_available_cents"] == 100000
    assert w0_after["incentive_pool_reserved_cents"] == 0
    assert w0_after["incentive_pool_paid_cents"] == 0


def test_refresh_run_preview_counts_only_grace_expired(api):
    """PRD §3.9: "A `PanelManager` opens a refresh run with a `run_label` and an
    optional `attrition_grace_days` defaulting to 30; at creation the run computes
    `planned_attrition_count`, the number of `LAPSED` panelists whose `lapsed_at`
    is at least that many days in the past, while `applied_attrition_count` and
    `applied_forfeit_count` remain null until the run is applied."

    Design: Difficulty/transitive_cascade/refresh_apply_attrition_forfeit_pool_credit_cascade
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    _lapse_panelist_via_two_waves(instr["id"], p1["id"])  # LAPSED at 2026-08-21

    # Clock 2026-09-10: lapsed 20 days < 30-day default grace -> planned 0.
    set_clock("2026-09-10T00:00:00Z")
    run_early = validate_success(api.create_refresh_run(
        create_refresh_run_payload(run_label="early"), PM), 201)
    assert run_early["planned_attrition_count"] == 0
    assert run_early["applied_attrition_count"] is None
    assert run_early["applied_forfeit_count"] is None

    # Clock 2026-10-01: 41 days past lapse -> planned 1.
    set_clock("2026-10-01T00:00:00Z")
    run_late = validate_success(api.create_refresh_run(
        create_refresh_run_payload(run_label="late"), PM), 201)
    assert run_late["planned_attrition_count"] == 1
