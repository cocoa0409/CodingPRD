"""Validation-priority pairs, RBAC guards, missed-streak boundary and lapse
cascade, reserved-count conservation, weight-mass supersede conservation,
pagination envelope defaults."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    create_cell, create_panelist, create_locked_instrument, create_fielding_wave,
    create_wave, dispatch_invitation, submit_response, accept_response,
    get_award_for_response, set_clock, create_invitation_payload,
    create_privacy_hold_payload, create_snapshot, create_finalized_snapshot,
    create_cell_payload, make_liaison_headers, assert_timestamp_eq,
)

PM = TEST_USERS["panel_manager"]
SD = TEST_USERS["survey_designer"]
DA = TEST_USERS["data_analyst"]
IC = TEST_USERS["incentive_clerk"]
PO = TEST_USERS["privacy_officer"]

from test_helpers import api_client as _api


def _enroll(pid):
    return validate_success(_api.enroll_panelist(pid, PM), 200)


def _standard_fielding(closes_at="2026-08-10T00:00:00Z", target_size=5, **wave_kw):
    cell = create_cell(target_size=target_size)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], closes_at=closes_at, **wave_kw)
    return cell, p1, instr, wave


def _expire_wave(instr_id, p1_id, opens_at, closes_at, invite_at, close_at):
    """One wave where p1 is invited, never responds, and the wave is closed past
    closes_at (invitation EXPIRED)."""
    wave = create_wave(instr_id, opens_at=opens_at, closes_at=closes_at)
    # PRD §3.4: arming requires "the current time must not yet be past
    # opens_at" — arm while the clock is still at or before opens_at, then
    # advance into the fielding window.
    validate_success(_api.arm_wave(wave["id"], PM), 200)
    set_clock(invite_at)
    validate_success(_api.open_fielding(wave["id"], PM), 200)
    inv = dispatch_invitation(wave["id"], p1_id)
    set_clock(close_at)
    wave = validate_success(_api.close_wave(wave["id"], PM), 200)
    return wave, inv


# ---------------------------------------------------------------------------
# Priority pairs (Rule 5)
# ---------------------------------------------------------------------------

def test_invite_wave_not_fielding_and_pool_insufficient_returns_409_state_error(api):
    """PRD §2.8: "When several rules could reject the same request, the server
    evaluates them in a fixed priority order and surfaces the earliest failure"
    with "6. **State preconditions.** The target resource must be in the
    from-state the operation requires: the wave `FIELDING` for dispatch and
    reminders ..." ahead of "10. **Fiscal sufficiency.** Dispatch requires the
    wave's available pool to cover the base incentive ..."

    Design: Difficulty/priority_pair_validation_conflict/invite_wave_not_fielding_and_pool_insufficient_returns_409_state_error
    """
    cell = create_cell(target_size=5)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    # ARMED but never fielded; pool total 0 < base 1000.
    wave = create_wave(instr["id"], incentive_pool_total_cents=0,
                       base_incentive_cents=1000)
    validate_success(api.arm_wave(wave["id"], PM), 200)

    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p1["id"]), PM),
        ApiErrorId.ERR_WAVE_NOT_FIELDING)
    assert err["error_id"] == "ERR_WAVE_NOT_FIELDING"
    rows, meta = validate_paginated(
        api.list_invitations(PM, params={"wave_id": wave["id"]}))
    assert meta["total_count"] == 0


def test_invite_wave_not_fielding_rejects_without_persisting(api):
    """PRD §3.4: "Closing ends fielding. The wave must be `FIELDING`; closing from
    any other non-terminal status fails with `ERR_WAVE_NOT_FIELDING`." and
    PRD §3.5: "the wave must be `FIELDING` (otherwise `ERR_WAVE_NOT_FIELDING`) ..."

    Design: Difficulty/priority_pair_validation_conflict/invite_wave_not_fielding_and_pool_insufficient_returns_409_state_error
    """
    cell = create_cell(target_size=5)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    # Ample pool; only the state precondition fails — same winning error.
    wave = create_wave(instr["id"], incentive_pool_total_cents=100000,
                       base_incentive_cents=1000)
    validate_success(api.arm_wave(wave["id"], PM), 200)
    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p1["id"]), PM),
        ApiErrorId.ERR_WAVE_NOT_FIELDING)
    assert err["error_id"] == "ERR_WAVE_NOT_FIELDING"
    rows, meta = validate_paginated(
        api.list_invitations(PM, params={"wave_id": wave["id"]}))
    assert meta["total_count"] == 0
    # Wave state untouched by the rejected dispatch.
    wave_after = validate_success(api.get_wave(wave["id"], PM), 200)
    assert wave_after["status"] == "ARMED"
    assert wave_after["invited_count"] == 0


def test_invite_privacy_hold_and_duplicate_returns_403_safety_error(api):
    """PRD §2.8: "When several rules could reject the same request, the server
    evaluates them in a fixed priority order and surfaces the earliest failure"
    with "7. **Privacy and duty segregation.** An `ACTIVE` privacy hold on the
    panelist bars invitation dispatch and panelist reactivation
    (`ERR_PRIVACY_HOLD_ACTIVE`, HTTP 403) ..." ahead of "9. **Uniqueness and
    capacity.** Evaluated within this priority in exactly the following order: a
    duplicate live invitation for the same wave and panelist
    (`ERR_DUPLICATE_INVITATION`); ..."

    Design: Difficulty/priority_pair_validation_conflict/invite_privacy_hold_and_duplicate_returns_403_safety_error
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv1 = dispatch_invitation(wave["id"], p1["id"])
    # NO_CONTACT hold suspends nothing: the duplicate SENT invitation stays live.
    validate_success(api.create_privacy_hold(
        create_privacy_hold_payload(p1["id"], scope="NO_CONTACT",
                                    reason="pending verification"), PO), 201)

    err = validate_error(api.create_invitation(
        create_invitation_payload(wave["id"], p1["id"]), PM),
        ApiErrorId.ERR_PRIVACY_HOLD_ACTIVE)
    assert err["error_id"] == "ERR_PRIVACY_HOLD_ACTIVE"
    rows, meta = validate_paginated(api.list_invitations(
        PM, params={"wave_id": wave["id"], "panelist_id": p1["id"]}))
    assert meta["total_count"] == 1


def test_privacy_hold_bars_reactivate(api):
    """PRD §3.2: "Reactivation requires the panelist to currently be `LAPSED` —
    anything else fails with `ERR_PANELIST_NOT_LAPSED` — and requires that no
    `ACTIVE` privacy hold exists for them, else `ERR_PRIVACY_HOLD_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/invite_privacy_hold_and_duplicate_returns_403_safety_error
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    # Drive p1 to LAPSED via two expired waves.
    _expire_wave(instr["id"], p1["id"],
                "2026-08-02T00:00:00Z", "2026-08-10T00:00:00Z",
                "2026-08-03T00:00:00Z", "2026-08-11T00:00:00Z")
    _expire_wave(instr["id"], p1["id"],
                "2026-08-12T00:00:00Z", "2026-08-20T00:00:00Z",
                "2026-08-13T00:00:00Z", "2026-08-21T00:00:00Z")
    p_mid = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_mid["status"] == "LAPSED"

    validate_success(api.create_privacy_hold(
        create_privacy_hold_payload(p1["id"], scope="NO_CONTACT",
                                    reason="verification pending"), PO), 201)
    err = validate_error(api.reactivate_panelist(p1["id"], PM),
                         ApiErrorId.ERR_PRIVACY_HOLD_ACTIVE)
    assert err["error_id"] == "ERR_PRIVACY_HOLD_ACTIVE"


# ---------------------------------------------------------------------------
# RBAC (queue B)
# ---------------------------------------------------------------------------

def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or naming a role outside this
    declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/corner_missing_auth_header_returns_401
    """
    resp = api.create_panel_cell(
        create_cell_payload(age_band="AGE_18_29", district="D1",
                            tenure_bucket="RENTER", target_size=3),
        headers={"Content-Type": "application/json"})
    err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert err["error_id"] == "ERR_UNAUTHENTICATED"


def test_existence_before_state_priority(api):
    """PRD §2.8: "When several rules could reject the same request, the server
    evaluates them in a fixed priority order and surfaces the earliest failure"
    with "3. **Existence.** ... every foreign-key reference in the request body
    must resolve." ahead of "6. **State preconditions.** ..."

    Design: Corner/validations/corner_existence_before_state_priority
    """
    instr = create_locked_instrument()
    wave = create_wave(instr["id"])
    validate_success(api.arm_wave(wave["id"], PM), 200)  # ARMED, not FIELDING
    err = validate_error(api.create_invitation(
        {"wave_id": wave["id"],
         "panelist_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"}, PM),
        ApiErrorId.ERR_PANELIST_NOT_FOUND)
    assert err["error_id"] == "ERR_PANELIST_NOT_FOUND"


def test_wrong_role_create_cell_returns_403(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_wrong_role_create_cell_returns_403
    """
    err = validate_error(api.create_panel_cell(
        create_cell_payload(), DA), ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert err["error_id"] == "ERR_FORBIDDEN_ROLE"


def test_designer_cannot_dispatch_invitation_returns_403(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_designer_cannot_dispatch_invitation_returns_403
    """
    ghost = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    err = validate_error(api.create_invitation(
        {"wave_id": ghost, "panelist_id": ghost}, SD),
        ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert err["error_id"] == "ERR_FORBIDDEN_ROLE"


def test_clerk_cannot_review_response_returns_403(api):
    """PRD §2.9: "Response review, weighting, analysis, and publication drafting
    belong to the `DataAnalyst`; incentive authorization, payment, and forfeiture
    belong to the `IncentiveClerk`; privacy holds, the de-identification gate, and
    publish/retract belong to the `PrivacyOfficer`."

    Design: Corner/rbac/corner_clerk_cannot_review_response_returns_403
    """
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    err = validate_error(api.accept_response(r1["id"], IC),
                         ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert err["error_id"] == "ERR_FORBIDDEN_ROLE"
    r_after = validate_success(api.get_response(r1["id"], DA), 200)
    assert r_after["status"] == "SUBMITTED"


def test_analyst_cannot_publish_returns_403(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." and PRD §2.9: "privacy holds,
    the de-identification gate, and publish/retract belong to the
    `PrivacyOfficer`."

    Design: Corner/rbac/corner_analyst_cannot_publish_returns_403
    """
    ghost = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    from test_helpers import build_user_headers
    err = validate_error(api.publish_publication(
        ghost, build_user_headers("analyst-1", "DataAnalyst")),
        ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert err["error_id"] == "ERR_FORBIDDEN_ROLE"


def test_segregation_of_duties_same_user_returns_403(api):
    """PRD §3.7: "third, the publisher's `X-User-ID` must differ from the
    snapshot's `finalized_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`);" and
    PRD §2.9: "The sharpest edge of this split is enforced at publish time: the
    publisher must be a different operator than the snapshot's finalizer."

    Design: Corner/rbac/corner_segregation_of_duties_same_user_returns_403
    """
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    accept_response(r1["id"])
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)
    snap = create_finalized_snapshot(wave["id"], finalizer_user_id="analyst-1")
    from test_helpers import create_publication_payload
    pub = validate_success(api.create_publication(
        create_publication_payload(wave["id"], snap["id"], k_threshold=1), DA), 201)

    # The publisher's X-User-ID equals the snapshot's finalized_by_user_id.
    from test_helpers import make_privacy_headers
    err = validate_error(api.publish_publication(pub["id"],
                                                 make_privacy_headers("analyst-1")),
                         ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES"
    pub_after = validate_success(api.get_publication(pub["id"], PO), 200)
    assert pub_after["status"] == "DRAFT"


def test_liaison_cross_department_returns_403(api):
    """PRD §3.8: "Department scoping is strict: starting, fulfilling, and
    renegotiating a commitment each require the caller's `X-User-ID` to equal the
    commitment's `department_name` exactly, otherwise `ERR_FORBIDDEN_DEPARTMENT`."

    Design: Corner/rbac/corner_liaison_cross_department_returns_403
    """
    from test_helpers import create_publication_payload, create_commitment
    cell, p1, instr, wave = _standard_fielding()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    accept_response(r1["id"])
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)
    snap = create_finalized_snapshot(wave["id"], finalizer_user_id="analyst-1")
    pub = validate_success(api.create_publication(
        create_publication_payload(wave["id"], snap["id"], k_threshold=1), DA), 201)
    from test_helpers import make_privacy_headers
    validate_success(api.publish_publication(pub["id"], make_privacy_headers("privacy-1")), 200)
    cm = create_commitment(pub["id"], department_name="DEPT_TRANSPORT")

    err = validate_error(api.start_commitment(cm["id"],
                                              make_liaison_headers("DEPT_PARKS")),
                         ApiErrorId.ERR_FORBIDDEN_DEPARTMENT)
    assert err["error_id"] == "ERR_FORBIDDEN_DEPARTMENT"
    cm_after = validate_success(api.get_commitment(cm["id"], PM), 200)
    assert cm_after["status"] == "COMMITTED"


# ---------------------------------------------------------------------------
# Missed-streak boundary and close cascade (Rule 6 / Rule 4)
# ---------------------------------------------------------------------------

def test_missed_streak_lapses_at_exactly_two(api):
    """PRD §3.2: "When a wave close sweep recomputes a panelist's streak at 2 or
    more, the panelist transitions `ACTIVE` → `LAPSED`, `lapsed_at` is stamped
    with the current time, and the streak resets to 0, consumed by the lapse."
    and "walking from the front, the system counts leading invitations in
    `EXPIRED` status and stops at the first `COMPLETED` or `DECLINED`."

    Design: Difficulty/boundary_precision_check/missed_streak_lapses_at_exactly_two
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()

    # W1: invited 08-03, DECLINED 08-04 (breaks the streak), closed 08-11.
    w1 = create_wave(instr["id"], opens_at="2026-08-02T00:00:00Z",
                     closes_at="2026-08-10T00:00:00Z")
    # Arm before the clock passes opens_at (PRD §3.4 arm gate).
    validate_success(api.arm_wave(w1["id"], PM), 200)
    set_clock("2026-08-03T00:00:00Z")
    validate_success(api.open_fielding(w1["id"], PM), 200)
    inv1 = dispatch_invitation(w1["id"], p1["id"])
    set_clock("2026-08-04T00:00:00Z")
    validate_success(api.decline_invitation(inv1["id"], PM), 200)
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(w1["id"], PM), 200)

    # W2: expires at close -> streak 1, still ACTIVE.
    _expire_wave(instr["id"], p1["id"],
                "2026-08-12T00:00:00Z", "2026-08-20T00:00:00Z",
                "2026-08-13T00:00:00Z", "2026-08-21T00:00:00Z")
    p_mid = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_mid["missed_streak"] == 1
    assert p_mid["status"] == "ACTIVE"

    # W3: second consecutive expiry -> streak hits exactly 2 -> LAPSED.
    _expire_wave(instr["id"], p1["id"],
                "2026-08-22T00:00:00Z", "2026-08-30T00:00:00Z",
                "2026-08-23T00:00:00Z", "2026-08-31T00:00:00Z")
    p_final = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_final["missed_streak"] == 0
    assert p_final["status"] == "LAPSED"


def test_declined_invitation_breaks_the_streak(api):
    """PRD §3.5: "A `PanelManager` may record a decline, moving `SENT` →
    `DECLINED`, which releases the cell reservation — `reserved_count` decreases
    by one — and recomputes the streak, since a decline breaks it."

    Design: Difficulty/boundary_precision_check/missed_streak_lapses_at_exactly_two
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    # One prior expiry -> streak 1.
    _expire_wave(instr["id"], p1["id"],
                "2026-08-02T00:00:00Z", "2026-08-10T00:00:00Z",
                "2026-08-03T00:00:00Z", "2026-08-11T00:00:00Z")
    p_mid = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_mid["missed_streak"] == 1

    # Next invitation is declined: the streak breaks back to 0.
    w2 = create_wave(instr["id"], opens_at="2026-08-12T00:00:00Z",
                     closes_at="2026-08-20T00:00:00Z")
    # Arm before the clock passes opens_at (PRD §3.4 arm gate).
    validate_success(api.arm_wave(w2["id"], PM), 200)
    set_clock("2026-08-13T00:00:00Z")
    validate_success(api.open_fielding(w2["id"], PM), 200)
    inv2 = dispatch_invitation(w2["id"], p1["id"])
    set_clock("2026-08-14T00:00:00Z")
    validate_success(api.decline_invitation(inv2["id"], PM), 200)
    p_after = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_after["missed_streak"] == 0
    assert p_after["status"] == "ACTIVE"


def test_wave_close_expiry_strike_lapse_cascade(api):
    """PRD §3.4: "A successful close cascades in three hops. First, every
    invitation of the wave still `SENT` moves to `EXPIRED`. Second, for each
    affected panelist the `missed_streak` is recomputed by the chronological walk
    of §3.2 — each expiry extends its owner's streak — and each expiry releases
    its reservation, so the home cells' `reserved_count` re-derives. Third,
    panelists whose recomputed streak reaches 2 lapse: `ACTIVE` → `LAPSED`, with
    `lapsed_at` stamped and the streak reset to 0."

    Design: Difficulty/transitive_cascade/wave_close_expiry_strike_lapse_cascade
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()

    # W1 close: streak 1, still ACTIVE.
    _expire_wave(instr["id"], p1["id"],
                "2026-08-02T00:00:00Z", "2026-08-10T00:00:00Z",
                "2026-08-03T00:00:00Z", "2026-08-11T00:00:00Z")
    p_mid = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_mid["missed_streak"] == 1
    assert p_mid["status"] == "ACTIVE"

    # W2 close: second consecutive expiry -> LAPSED, lapsed_at stamped at close.
    w2, inv2 = _expire_wave(instr["id"], p1["id"],
                            "2026-08-12T00:00:00Z", "2026-08-20T00:00:00Z",
                            "2026-08-13T00:00:00Z", "2026-08-21T00:00:00Z")
    inv2_after = validate_success(api.get_invitation(inv2["id"], PM), 200)
    assert inv2_after["status"] == "EXPIRED"
    p_after = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_after["status"] == "LAPSED"
    assert p_after["missed_streak"] == 0
    assert_timestamp_eq(p_after["lapsed_at"], "2026-08-21T00:00:00Z")
    cell_after = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert cell_after["reserved_count"] == 0


def test_lapsed_panelist_still_counts_toward_active_count(api):
    """PRD §2.6: "`active_count` is the number of seated panelists whose membership
    status is `ACTIVE`, `LAPSED`, or `SUSPENDED`; applicants and panelists who
    have attrited or withdrawn never count."

    Design: Difficulty/transitive_cascade/wave_close_expiry_strike_lapse_cascade
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    _expire_wave(instr["id"], p1["id"],
                "2026-08-02T00:00:00Z", "2026-08-10T00:00:00Z",
                "2026-08-03T00:00:00Z", "2026-08-11T00:00:00Z")
    _expire_wave(instr["id"], p1["id"],
                "2026-08-12T00:00:00Z", "2026-08-20T00:00:00Z",
                "2026-08-13T00:00:00Z", "2026-08-21T00:00:00Z")
    p_after = validate_success(api.get_panelist(p1["id"], PM), 200)
    assert p_after["status"] == "LAPSED"
    cell_after = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert cell_after["active_count"] == 1  # LAPSED still seats


# ---------------------------------------------------------------------------
# Compensating invariants (Rule 9) — reserved count + weight mass
# ---------------------------------------------------------------------------

def test_cell_reserved_count_live_invitation_conservation(api):
    """PRD §2.6: "On each demographic cell, `reserved_count` is the number of live
    invitations — those in `SENT` status — whose panelist is seated in that cell
    ..." and PRD §3.5: "A successful dispatch creates the invitation directly in
    `SENT`. ... the cell's `reserved_count` increases by one with its `version`
    incrementing ..." and "Submitting a response moves the invitation `SENT` →
    `COMPLETED`, increases the wave's `completed_count` by one, likewise releases
    the reservation ..."

    Design: Difficulty/compensating_invariant/cell_reserved_count_live_invitation_conservation
    """
    cell = create_cell(target_size=10)
    p1 = _enroll(create_panelist()["id"])
    p2 = _enroll(create_panelist()["id"])
    p3 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])

    inv1 = dispatch_invitation(wave["id"], p1["id"])
    inv2 = dispatch_invitation(wave["id"], p2["id"])
    c = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert c["reserved_count"] == 2                     # dispatch +1 each

    validate_success(api.decline_invitation(inv1["id"], PM), 200)
    c = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert c["reserved_count"] == 1                     # decline -1

    submit_response(inv2["id"], completeness_pct=90)
    c = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert c["reserved_count"] == 0                     # completion -1

    inv3 = dispatch_invitation(wave["id"], p3["id"])
    c = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert c["reserved_count"] == 1                     # dispatch +1

    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)
    c = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert c["reserved_count"] == 0                     # expiry -1

    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert w["completed_count"] == 1
    assert w["invited_count"] == 3


def test_reserved_count_equals_live_sent_invitations(api):
    """PRD §2.6: "On each demographic cell, `reserved_count` is the number of live
    invitations — those in `SENT` status — whose panelist is seated in that cell
    ..."

    Design: Difficulty/compensating_invariant/cell_reserved_count_live_invitation_conservation
    """
    cell = create_cell(target_size=10)
    panelists = [_enroll(create_panelist()["id"]) for _ in range(3)]
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    for p in panelists:
        dispatch_invitation(wave["id"], p["id"])

    c = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    rows, meta = validate_paginated(api.list_invitations(
        PM, params={"wave_id": wave["id"], "status": "SENT"}))
    assert c["reserved_count"] == 3
    assert meta["total_count"] == 3
    assert c["reserved_count"] == meta["total_count"]


def test_weight_mass_supersede_conservation(api):
    """PRD §3.7: "Creating the snapshot increments the wave's `version` by one,
    supersedes history — every prior `PROVISIONAL` or `FINALIZED` snapshot of the
    wave becomes `SUPERSEDED` — and, when the wave was `WEIGHTED`, reverts it
    `WEIGHTED` → `CLOSED` as analysis reopens." and "The snapshot's `weight_mass`
    is the sum of the final weights, equal to N up to rounding; `accepted_count`
    records N ..."

    Design: Difficulty/compensating_invariant/weight_mass_supersede_conservation
    """
    cell = create_cell(target_size=4)
    cell2 = create_cell(target_size=4, age_band="AGE_30_44", tenure_bucket="OWNER")
    p1 = _enroll(create_panelist()["id"])
    p2 = _enroll(create_panelist(age_band="AGE_30_44", tenure_bucket="OWNER")["id"])
    p3 = _enroll(create_panelist(age_band="AGE_30_44", tenure_bucket="OWNER")["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    for p in (p1, p2, p3):
        inv = dispatch_invitation(wave["id"], p["id"])
        r = submit_response(inv["id"])
        accept_response(r["id"])
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    snap1 = create_snapshot(wave["id"], method="POST_STRAT")
    assert snap1["weight_mass"] == pytest.approx(3, abs=1e-6)
    from test_helpers import make_analyst_headers
    validate_success(api.finalize_weight_snapshot(
        snap1["id"], make_analyst_headers("analyst-1")), 200)
    wave_mid = validate_success(api.get_wave(wave["id"], DA), 200)
    assert wave_mid["status"] == "WEIGHTED"

    snap2 = create_snapshot(wave["id"], method="RIM")
    assert snap2["weight_mass"] == pytest.approx(3, abs=1e-6)
    assert snap2["accepted_count"] == 3

    snap1_after = validate_success(api.get_weight_snapshot(snap1["id"], DA), 200)
    assert snap1_after["status"] == "SUPERSEDED"
    wave_reopened = validate_success(api.get_wave(wave["id"], DA), 200)
    assert wave_reopened["status"] == "CLOSED"


def test_reweighting_reverts_weighted_wave_to_closed(api):
    """PRD §3.4: "After close, two system transitions finish the wave's arc.
    Finalizing a weight snapshot moves the wave `CLOSED` → `WEIGHTED`, and
    publishing a publication moves it `WEIGHTED` → `PUBLISHED`. Creating a new
    snapshot for a `WEIGHTED` wave reopens analysis by reverting it `WEIGHTED` →
    `CLOSED`."

    Design: Difficulty/compensating_invariant/weight_mass_supersede_conservation
    """
    cell = create_cell(target_size=4)
    p1 = _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv = dispatch_invitation(wave["id"], p1["id"])
    r = submit_response(inv["id"])
    accept_response(r["id"])
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    snap1 = create_snapshot(wave["id"], method="POST_STRAT")
    from test_helpers import make_analyst_headers
    validate_success(api.finalize_weight_snapshot(
        snap1["id"], make_analyst_headers("analyst-1")), 200)
    assert validate_success(api.get_wave(wave["id"], DA), 200)["status"] == "WEIGHTED"

    snap2 = create_snapshot(wave["id"], method="POST_STRAT")
    wave_after = validate_success(api.get_wave(wave["id"], DA), 200)
    assert wave_after["status"] == "CLOSED"
    snap1_after = validate_success(api.get_weight_snapshot(snap1["id"], DA), 200)
    assert snap1_after["status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# Pagination envelope (queue B)
# ---------------------------------------------------------------------------

def test_pagination_envelope_defaults(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
    items skipped and defaults to 0." and "The `meta` object of a list response
    carries the pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/corner_pagination_envelope_defaults
    """
    for i in range(9):
        create_cell(target_size=1, age_band="AGE_18_29", district=f"D{i+1}")
    for i in range(3):
        create_cell(target_size=1, age_band="AGE_30_44", district=f"D{i+1}")

    rows, meta = validate_paginated(api.list_panel_cells(PM))
    assert len(rows) == 10
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert meta["limit"] == 10
    assert meta["offset"] == 0

    rows2, meta2 = validate_paginated(
        api.list_panel_cells(PM, params={"limit": 10, "offset": 10}))
    assert len(rows2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False
