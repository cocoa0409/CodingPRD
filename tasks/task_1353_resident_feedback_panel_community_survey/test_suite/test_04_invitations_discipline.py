"""Invitation dispatch gates: washout buffer, cell contact cap, duplicate SENT,
privacy-hold bar, pool floor, reminder cadence/cap, decline/response on
non-SENT invitations."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    create_cell, create_panelist, create_locked_instrument, create_fielding_wave,
    create_armed_wave, create_wave, dispatch_invitation, submit_response,
    set_clock, create_invitation_payload, assert_timestamp_eq,
)

PM = TEST_USERS["panel_manager"]
PO = TEST_USERS["privacy_officer"]


def _enrolled(district="D1", age_band="AGE_18_29", tenure="RENTER", locale="en"):
    p = create_panelist(age_band=age_band, district=district,
                        tenure_bucket=tenure, preferred_locale=locale)
    return validate_success(api_panelist_enroll(p["id"]), 200)


# Bind through the module-level client imported via fixtures; pytest fixture `api`
# is the same object. To keep helpers simple we reference the singleton directly.
from test_helpers import api_client as _api


def api_panelist_enroll(pid):
    return _api.enroll_panelist(pid, PM)


def _standard_fielding(target_size=5, closes_at="2026-08-10T00:00:00Z", **wave_kw):
    cell = create_cell(target_size=target_size)
    panelist = _enrolled()
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], closes_at=closes_at, **wave_kw)
    return cell, panelist, instr, wave


def test_invitation_washout_buffer_window(api):
    """PRD §3.5: "The washout is a per-panelist buffer. When `last_contacted_at` is
    set, dispatch earlier than seven days after it is rejected with
    `ERR_CONTACT_WASHOUT_VIOLATION`, while dispatch at exactly the seven-day mark
    is permitted — the buffer is half-open."

    Design: Difficulty/resource_temporal_overlap/invitation_washout_buffer_window
    """
    cell = create_cell(target_size=10)
    p1 = _enrolled()
    instr = create_locked_instrument()
    w1 = create_fielding_wave(instr["id"], closes_at="2026-08-31T00:00:00Z")
    inv1 = dispatch_invitation(w1["id"], p1["id"])  # sent 2026-08-03

    w2 = create_wave(instr["id"], opens_at="2026-08-05T00:00:00Z",
                     closes_at="2026-08-31T00:00:00Z")
    set_clock("2026-08-04T00:00:00Z")
    validate_success(api.arm_wave(w2["id"], PM), 200)
    set_clock("2026-08-06T00:00:00Z")
    validate_success(api.open_fielding(w2["id"], PM), 200)

    # 2026-08-09 is six days after the 08-03 send -> inside the half-open buffer.
    set_clock("2026-08-09T00:00:00Z")
    err = validate_error(api.create_invitation(
        create_invitation_payload(w2["id"], p1["id"]), PM),
        ApiErrorId.ERR_CONTACT_WASHOUT_VIOLATION)
    assert err["error_id"] == "ERR_CONTACT_WASHOUT_VIOLATION"

    # Exactly seven days after: permitted.
    set_clock("2026-08-10T00:00:00Z")
    inv2 = validate_success(api.create_invitation(
        create_invitation_payload(w2["id"], p1["id"]), PM), 201)
    assert inv2["status"] == "SENT"
    p_after = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert_timestamp_eq(p_after["last_contacted_at"], "2026-08-10T00:00:00Z")


def test_invitation_washout_stamps_last_contacted_at(api):
    """PRD §3.5: "A successful dispatch creates the invitation directly in `SENT`.
    Both `sent_at` and the panelist's `last_contacted_at` are stamped with the
    current time ..."

    Design: Difficulty/resource_temporal_overlap/invitation_washout_buffer_window
    """
    cell = create_cell(target_size=10)
    p1 = _enrolled()
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], closes_at="2026-08-31T00:00:00Z")
    inv = dispatch_invitation(wave["id"], p1["id"])
    assert inv["status"] == "SENT"
    assert_timestamp_eq(inv["sent_at"], "2026-08-03T00:00:00Z")
    p_after = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert_timestamp_eq(p_after["last_contacted_at"], "2026-08-03T00:00:00Z")


def test_cell_contact_cap_sliding_window(api):
    """PRD §3.5: "the per-cell contact cap is rejected with
    `ERR_CELL_CONTACT_CAP_REACHED` when the count of invitations sent into the
    panelist's home cell — of any status, since contact occurred — within the
    trailing seven-day window inclusive of both endpoints has reached 3."

    Design: Difficulty/resource_temporal_overlap/cell_contact_cap_sliding_window
    """
    cell = create_cell(target_size=10)
    p1, p2, p3, p4 = (_enrolled() for _ in range(4))
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], closes_at="2026-08-31T00:00:00Z")
    # Three sends into the cell at 2026-08-03T00:00:00Z.
    dispatch_invitation(wave["id"], p1["id"])
    dispatch_invitation(wave["id"], p2["id"])
    dispatch_invitation(wave["id"], p3["id"])

    # Fourth send at 08-03: cap reached.
    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p4["id"]), PM),
        ApiErrorId.ERR_CELL_CONTACT_CAP_REACHED)
    assert err["error_id"] == "ERR_CELL_CONTACT_CAP_REACHED"

    # At exactly +7d the window lower bound is inclusive: still 3 in window.
    set_clock("2026-08-10T00:00:00Z")
    err_b = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p4["id"]), PM),
        ApiErrorId.ERR_CELL_CONTACT_CAP_REACHED)
    assert err_b["error_id"] == "ERR_CELL_CONTACT_CAP_REACHED"

    # One hour later the original sends have aged out.
    set_clock("2026-08-10T01:00:00Z")
    inv4 = validate_success(api.create_invitation(
        create_invitation_payload(wave["id"], p4["id"]), PM), 201)
    assert inv4["status"] == "SENT"


def test_cell_contact_cap_counts_any_status(api):
    """PRD §3.5: "the per-cell contact cap is rejected with
    `ERR_CELL_CONTACT_CAP_REACHED` when the count of invitations sent into the
    panelist's home cell — of any status, since contact occurred — within the
    trailing seven-day window inclusive of both endpoints has reached 3."

    Design: Difficulty/resource_temporal_overlap/cell_contact_cap_sliding_window
    """
    cell = create_cell(target_size=10)
    p1, p2, p3, p4 = (_enrolled() for _ in range(4))
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], closes_at="2026-08-31T00:00:00Z")
    inv1 = dispatch_invitation(wave["id"], p1["id"])
    inv2 = dispatch_invitation(wave["id"], p2["id"])
    dispatch_invitation(wave["id"], p3["id"])
    # Two of the three sends leave SENT (one completes, one declines); they still
    # count toward the cap because contact occurred.
    submit_response(inv1["id"])
    validate_success(api.decline_invitation(inv2["id"], PM), 200)

    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p4["id"]), PM),
        ApiErrorId.ERR_CELL_CONTACT_CAP_REACHED)
    assert err["error_id"] == "ERR_CELL_CONTACT_CAP_REACHED"


def test_duplicate_invitation_alone_returns_409(api):
    """PRD §3.5: "a live `SENT` invitation already existing for the same wave and
    panelist pair is rejected with `ERR_DUPLICATE_INVITATION` ..."

    Design: Corner/validations/corner_duplicate_invitation_alone_returns_409
    """
    cell, p1, instr, wave = _standard_fielding(closes_at="2026-08-31T00:00:00Z")
    dispatch_invitation(wave["id"], p1["id"])  # sent 2026-08-03
    # §2.8 ranks the seven-day washout (temporal, level 8) ahead of the
    # duplicate-invitation check (capacity, level 9); advance exactly seven
    # days — permitted by the half-open buffer — so the duplicate rule fires
    # alone.
    set_clock("2026-08-10T00:00:00Z")
    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p1["id"]), PM),
        ApiErrorId.ERR_DUPLICATE_INVITATION)
    assert err["error_id"] == "ERR_DUPLICATE_INVITATION"


def test_dispatch_pool_insufficient_alone_returns_402(api):
    """PRD §3.5: "Finally, dispatch requires the wave's
    `incentive_pool_available_cents` to cover at least `base_incentive_cents`,
    else `ERR_INCENTIVE_POOL_INSUFFICIENT`."

    Design: Corner/validations/corner_dispatch_pool_insufficient_alone_returns_402
    """
    cell, p1, instr, wave = _standard_fielding(incentive_pool_total_cents=500,
                                               base_incentive_cents=1000)
    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p1["id"]), PM),
        ApiErrorId.ERR_INCENTIVE_POOL_INSUFFICIENT)
    assert err["error_id"] == "ERR_INCENTIVE_POOL_INSUFFICIENT"


def test_dispatch_suspended_panelist_returns_409(api):
    """PRD §3.5: "the wave must be `FIELDING` (otherwise `ERR_WAVE_NOT_FIELDING`)
    and the panelist must be `ACTIVE` (otherwise `ERR_PANELIST_NOT_ACTIVE`) ..."

    Design: Corner/errors/corner_dispatch_suspended_panelist_returns_409
    """
    cell = create_cell(target_size=5)
    p1 = _enrolled()
    # FULL_SUPPRESS hold suspends the panelist before any wave exists.
    validate_success(api.create_privacy_hold(
        {"panelist_id": p1["id"], "scope": "FULL_SUPPRESS",
         "reason": "resident request"}, PO), 201)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p1["id"]), PM),
        ApiErrorId.ERR_PANELIST_NOT_ACTIVE)
    assert err["error_id"] == "ERR_PANELIST_NOT_ACTIVE"


def test_reminder_cadence_too_soon_then_allowed(api):
    """PRD §3.5: "a reminder at exactly the 48-hour mark is permitted, and anything
    sooner is rejected with `ERR_REMINDER_CADENCE_TOO_SOON`. Each successful
    reminder increments `reminder_count` and stamps `last_reminder_at` with the
    current time."

    Design: Corner/state_machines/corner_reminder_cadence_too_soon_then_allowed
    """
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])  # sent 2026-08-03T00:00:00Z

    set_clock("2026-08-04T00:00:00Z")  # +24h
    err = validate_error(api.remind_invitation(inv["id"], PM),
                         ApiErrorId.ERR_REMINDER_CADENCE_TOO_SOON)
    assert err["error_id"] == "ERR_REMINDER_CADENCE_TOO_SOON"

    set_clock("2026-08-05T00:00:00Z")  # exactly +48h
    ok = validate_success(api.remind_invitation(inv["id"], PM), 200)
    assert ok["reminder_count"] == 1
    assert_timestamp_eq(ok["last_reminder_at"], "2026-08-05T00:00:00Z")


def test_reminder_cap_at_two(api):
    """PRD §3.5: "A reminder is refused when the wave is no longer `FIELDING`
    (`ERR_WAVE_NOT_FIELDING`), when `reminder_count` has already reached 2
    (`ERR_REMINDER_CAP_REACHED`), or when fewer than 48 hours have elapsed since
    the most recent reminder — or since `sent_at` when none has been sent ..."

    Design: Corner/state_machines/corner_reminder_cap_at_two
    """
    cell, p1, instr, wave = _standard_fielding(closes_at="2026-08-31T00:00:00Z")
    inv = dispatch_invitation(wave["id"], p1["id"])  # sent 2026-08-03

    set_clock("2026-08-05T00:00:00Z")
    validate_success(api.remind_invitation(inv["id"], PM), 200)
    set_clock("2026-08-07T00:00:00Z")
    ok = validate_success(api.remind_invitation(inv["id"], PM), 200)
    assert ok["reminder_count"] == 2
    set_clock("2026-08-09T00:00:00Z")
    err = validate_error(api.remind_invitation(inv["id"], PM),
                         ApiErrorId.ERR_REMINDER_CAP_REACHED)
    assert err["error_id"] == "ERR_REMINDER_CAP_REACHED"


def test_invitation_decline_twice_returns_409(api):
    """PRD §3.5: "Either action against an invitation no longer `SENT` fails with
    `ERR_INVITATION_NOT_OPEN`, and so does a response submitted against one."

    Design: Corner/state_machines/corner_invitation_decline_twice_returns_409
    """
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])
    declined = validate_success(api.decline_invitation(inv["id"], PM), 200)
    assert declined["status"] == "DECLINED"
    err = validate_error(api.decline_invitation(inv["id"], PM),
                         ApiErrorId.ERR_INVITATION_NOT_OPEN)
    assert err["error_id"] == "ERR_INVITATION_NOT_OPEN"


def test_response_on_declined_invitation_returns_409(api):
    """PRD §3.6: "There is at most one response per invitation: a second submission
    finds the invitation already `COMPLETED` and fails with
    `ERR_INVITATION_NOT_OPEN`." and PRD §3.5: "Either action against an invitation
    no longer `SENT` fails with `ERR_INVITATION_NOT_OPEN`, and so does a response
    submitted against one."

    Design: Corner/state_machines/corner_response_on_declined_invitation_returns_409
    """
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])
    validate_success(api.decline_invitation(inv["id"], PM), 200)
    err = validate_error(api.create_response(
        {"invitation_id": inv["id"], "answers_payload": {"q1": 1},
         "completeness_pct": 100, "completion_seconds": 300}, PM),
        ApiErrorId.ERR_INVITATION_NOT_OPEN)
    assert err["error_id"] == "ERR_INVITATION_NOT_OPEN"
    rows, meta = validate_paginated(
        api.list_responses(PM, params={"invitation_id": inv["id"]}))
    assert meta["total_count"] == 0


def test_invitation_list_filter_by_status(api):
    """PRD §3.5: "invitation list reads filter by `wave_id`, `panelist_id`, or
    `status`."

    Design: Corner/endpoints/corner_invitation_list_filter_by_status
    """
    cell = create_cell(target_size=5)
    p1 = _enrolled()
    p2 = _enrolled()
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv1 = dispatch_invitation(wave["id"], p1["id"])
    inv2 = dispatch_invitation(wave["id"], p2["id"])
    validate_success(api.decline_invitation(inv2["id"], PM), 200)

    sent_rows, sent_meta = validate_paginated(
        api.list_invitations(PM, params={"wave_id": wave["id"], "status": "SENT"}))
    assert sent_meta["total_count"] == 1
    assert sent_rows[0]["id"] == inv1["id"]

    dec_rows, dec_meta = validate_paginated(
        api.list_invitations(PM, params={"wave_id": wave["id"], "status": "DECLINED"}))
    assert dec_meta["total_count"] == 1
    assert dec_rows[0]["id"] == inv2["id"]
