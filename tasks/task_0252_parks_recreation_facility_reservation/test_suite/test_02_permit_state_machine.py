"""Permit and lottery-round state machines: branching, terminal lockdown,
idempotency, and cross-entity state dependency.

Covers difficulty instances non_linear_state_machine (permit grant/waitlist/deny
branch; lottery round drawn-vs-cancelled), cross_entity_state_dependency
(grant needs facility OPEN; withdraw needs round OPEN), plus corner
state_machine instances (initial state, invalid transitions, terminal lockdown,
idempotency, league bubble-up, COI expiry sweep).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    set_clock, create_facility, create_patron, create_coi, apply_permit,
    capture_payment, facility_version, grant_permit, setup_applied_permit,
    setup_granted_permit, setup_league_with_children,
    setup_lottery_round_with_entries, enter_lottery,
    make_patron_headers, TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


def test_permit_forks_applied_waitlist_then_rejoins_granted(api):
    """PRD §3.5: "If a conflict exists and the request did carry on_conflict set to
    WAITLIST, the grant short-circuits to the WAITLISTED outcome: the permit
    transitions APPLIED -> WAITLISTED, and the insurance and payment gates below
    are deliberately skipped because the permit is not being placed into GRANTED."
    PRD §3.5: "the permit stays WAITLISTED until an explicit grant call moves it
    WAITLISTED -> GRANTED, at which point the full grant preconditions — no
    overlapping buffer-expanded GRANTED permit any longer, plus the same insurance
    and payment gates as the APPLIED -> GRANTED path — must hold."

    P1 granted on a slot; P2 on the same window grants with on_conflict=WAITLIST ->
    WAITLISTED; cancel P1 frees the slot; re-grant P2 -> GRANTED (rejoin).

    Design: Difficulty/non_linear_state_machine/nlsm_permit_branching_grant_waitlist_deny
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Branch Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=0,
    )
    pa = create_patron(residency="NON_RESIDENT")
    pb = create_patron(residency="NON_RESIDENT")
    p1 = apply_permit(facility["id"], pa["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z")
    p2 = apply_permit(facility["id"], pb["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z")

    capture_payment(p1["id"], 20000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], p1["id"], v0)

    v1 = facility_version(facility["id"])
    waitlisted = grant_permit(facility["id"], p2["id"], v1, on_conflict="WAITLIST")
    assert waitlisted["status"] == "WAITLISTED", "on_conflict=WAITLIST -> WAITLISTED"

    # Cancel P1 to free the slot.
    validate_success(api.cancel_permit(
        facility["id"], p1["id"], {"refund_destination": "ORIGINAL"}, COORD), 200)
    p1_after = validate_success(api.get_permit(p1["id"], COORD), 200)
    assert p1_after["status"] == "CANCELLED"

    capture_payment(p2["id"], 20000, 0)
    v2 = facility_version(facility["id"])
    regranted = grant_permit(facility["id"], p2["id"], v2)
    assert regranted["status"] == "GRANTED", "WAITLISTED -> GRANTED after slot freed"


def test_grant_then_waitlist_holds_nothing(api):
    """PRD §3.5: "The WAITLISTED outcome is comparatively quiet: the permit keeps
    its quoted_fee_cents, no final_fee_cents is set, no deposit is held, the
    facility's granted_permit_count is unchanged, and the facility's version is not
    bumped."

    A second test of the branching machine asserting the WAITLISTED side-effect
    set (no deposit, facility count/version unchanged) distinct from GRANTED.

    Design: Difficulty/non_linear_state_machine/nlsm_permit_branching_grant_waitlist_deny
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Quiet Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=2000, buffer_minutes=0,
    )
    pa = create_patron(residency="NON_RESIDENT")
    pb = create_patron(residency="NON_RESIDENT")
    p1 = apply_permit(facility["id"], pa["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z")
    p2 = apply_permit(facility["id"], pb["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z")

    capture_payment(p1["id"], 20000, 2000)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], p1["id"], v0)

    v1 = facility_version(facility["id"])
    fac_before = validate_success(api.get_facility(facility["id"], COORD), 200)
    waitlisted = grant_permit(facility["id"], p2["id"], v1, on_conflict="WAITLIST")

    assert waitlisted["status"] == "WAITLISTED"
    assert waitlisted["deposit_held_cents"] == 0, "no deposit held on WAITLISTED"
    fac_after = validate_success(api.get_facility(facility["id"], COORD), 200)
    assert fac_after["granted_permit_count"] == fac_before["granted_permit_count"], (
        "granted_permit_count unchanged on WAITLISTED"
    )
    assert fac_after["version"] == fac_before["version"], "facility version not bumped on WAITLISTED"


def test_lottery_round_cancel_branch_withdraws_entries_no_permit(api):
    """PRD §3.9: "A coordinator may instead cancel an OPEN round, moving it
    OPEN -> CANCELLED ... Cancelling the round transitions all still-entered
    entries ENTERED -> WITHDRAWN and synthesizes no permit."
    PRD §3.9: "its winning_entry_id is null until the round is drawn."

    Two entered entries; coordinator cancels before drawing -> both WITHDRAWN,
    no winner, no permit.

    Design: Difficulty/non_linear_state_machine/nlsm_lottery_round_branch_drawn_vs_cancelled
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "CancelRound Court", "facility_type": "COURT"},
        entrants=[
            {"verified": True, "residency": "RESIDENT"},
            {"verified": False, "residency": "NON_RESIDENT"},
        ],
    )
    rnd, entries = ctx["round"], ctx["entries"]

    res = api.cancel_lottery_round(rnd["id"], COORD)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["winning_entry_id"] is None

    for e in entries:
        got = validate_success(api.get_lottery_entry(e["id"], COORD), 200)
        assert got["status"] == "WITHDRAWN"


def test_draw_branch_selects_winner_and_loses_others(api):
    """PRD §3.9: "Drawing moves the round OPEN -> DRAWN, records the chosen entry in
    winning_entry_id, transitions that winning entry ENTERED -> WON, and
    transitions every other still-entered entry ENTERED -> LOST."

    A second test of the round machine asserting the DRAWN branch side-effects
    (WON/LOST), distinct from the CANCELLED branch.

    Design: Difficulty/non_linear_state_machine/nlsm_lottery_round_branch_drawn_vs_cancelled
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "DrawBranch Court", "facility_type": "COURT"},
        entrants=[
            {"verified": False, "residency": "NON_RESIDENT"},
            {"verified": True, "residency": "RESIDENT"},
        ],
    )
    facility, rnd, entries = ctx["facility"], ctx["round"], ctx["entries"]
    entry_non, entry_res = entries[0], entries[1]

    set_clock("2026-07-15T00:00:00Z")
    v = facility_version(facility["id"])
    drawn = validate_success(
        api.draw_lottery_round(rnd["id"], {"expected_facility_version": v}, COORD), 200)
    assert drawn["status"] == "DRAWN"
    assert drawn["winning_entry_id"] == entry_res["id"], "verified resident (weight 2) wins"

    got_res = validate_success(api.get_lottery_entry(entry_res["id"], COORD), 200)
    got_non = validate_success(api.get_lottery_entry(entry_non["id"], COORD), 200)
    assert got_res["status"] == "WON"
    assert got_non["status"] == "LOST"


def test_grant_blocked_when_facility_closed(api):
    """PRD §3.5: "A facility that is not OPEN cannot accept a new grant into
    GRANTED; the CLOSED status blocks it."
    PRD §3.2: "a CLOSED facility blocks new grants."

    Facility PATCHed to CLOSED, then grant of an APPLIED permit -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/cesd_permit_grant_requires_facility_open
    """
    ctx = setup_applied_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Close Court", "facility_type": "COURT"},
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
        capture=True, fee_component_cents=20000, deposit_component_cents=0,
    )
    facility, permit = ctx["facility"], ctx["permit"]

    v0 = facility_version(facility["id"])
    closed = validate_success(api.update_facility(
        facility["id"], {"status": "CLOSED", "expected_facility_version": v0}, COORD), 200)
    assert closed["status"] == "CLOSED"

    v1 = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_INVALID_STATE")

    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED", "permit unchanged after blocked grant"


def test_withdraw_blocked_when_round_already_drawn(api):
    """PRD §3.9: "A patron or coordinator may withdraw an entry, moving it
    ENTERED -> WITHDRAWN, but only while the parent round is still OPEN; a
    withdrawal against a non-open round is rejected with ERR_INVALID_STATE
    (HTTP 409)."

    Single-entry round drawn (winner WON); withdrawing the now-WON entry against
    the DRAWN round -> ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/cesd_lottery_entry_withdraw_requires_round_open
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "Drawn Field", "facility_type": "FIELD"},
        entrants=[{"verified": True, "residency": "RESIDENT"}],
    )
    facility, rnd, entries, patrons = (
        ctx["facility"], ctx["round"], ctx["entries"], ctx["patrons"])
    entry, patron = entries[0], patrons[0]

    set_clock("2026-07-15T00:00:00Z")
    v = facility_version(facility["id"])
    drawn = validate_success(
        api.draw_lottery_round(rnd["id"], {"expected_facility_version": v}, COORD), 200)
    assert drawn["status"] == "DRAWN"

    res = api.withdraw_lottery_entry(entry["id"], make_patron_headers(patron["id"]))
    validate_error(res, "ERR_INVALID_STATE")

    after = validate_success(api.get_lottery_entry(entry["id"], COORD), 200)
    assert after["status"] == "WON", "entry remains WON after the failed withdraw"


# ─── Corner: state_machines ───────────────────────────────────────────────────

def test_new_permit_starts_in_applied(api):
    """PRD §3.3: "A new permit enters status APPLIED."

    Design: Corner/state_machines/permit_initial_state_is_applied
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(name="Init Field", facility_type="FIELD")
    patron = create_patron(residency="NON_RESIDENT")
    permit = apply_permit(
        facility["id"], patron["id"], "2026-08-23T10:00:00Z", "2026-08-23T12:00:00Z")
    assert permit["status"] == "APPLIED"


def test_complete_before_end_at_rejected(api):
    """PRD §3.7: "Completion is a coordinator action on a GRANTED permit and is
    only allowed once the reservation has ended: the current clock must be at or
    after the permit's end_at."

    Granted permit, clock still before end_at -> complete returns ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_before_end_at_invalid_state
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Pre Field", "facility_type": "FIELD",
                            "deposit_cents": 1000},
        start_at="2026-08-24T10:00:00Z", end_at="2026-08-24T12:00:00Z",
        fee_component_cents=20000, deposit_component_cents=1000,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    # clock is still 2026-07-01, before end_at.
    res = api.complete_permit(facility["id"], permit["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "GRANTED"


def test_cancel_completed_permit_rejected(api):
    """PRD §3.7: "A permit can leave GRANTED or APPLIED by cancellation, performed
    by either the owning Patron or a RecCoordinator."
    PRD §3.7: "Completing moves the permit GRANTED → COMPLETED, releases the deposit
    in full by creating a Refund whose deposit_refund_cents equals deposit_held_cents
    and whose fee_refund_cents is 0, decrements the facility's granted_permit_count
    by one, and increments the facility's version by one."

    A COMPLETED permit has no cancel transition defined (cancellation operates only
    from GRANTED or APPLIED), so cancelling it is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_terminal_completed_permit_rejected
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Term Pool", "facility_type": "POOL",
                            "deposit_cents": 2000},
        start_at="2026-07-03T10:00:00Z", end_at="2026-07-03T12:00:00Z",
        fee_component_cents=20000, deposit_component_cents=2000,
    )
    facility, patron, permit = ctx["facility"], ctx["patron"], ctx["permit"]
    set_clock("2026-07-03T13:00:00Z")
    completed = validate_success(api.complete_permit(facility["id"], permit["id"], COORD), 200)
    assert completed["status"] == "COMPLETED"

    res = api.cancel_permit(
        facility["id"], permit["id"], {"refund_destination": "ORIGINAL"},
        make_patron_headers(patron["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "COMPLETED"


def test_second_grant_on_granted_permit_rejected(api):
    """PRD §3.5: "the target permit must be in a state from which a grant is defined
    — that is, APPLIED or WAITLISTED; otherwise ERR_INVALID_STATE (HTTP 409)."

    Granting an already-GRANTED permit again -> ERR_INVALID_STATE.

    Design: Corner/state_machines/grant_idempotency_second_grant_rejected
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Idem Field", "facility_type": "FIELD"},
        start_at="2026-08-25T10:00:00Z", end_at="2026-08-25T12:00:00Z",
        fee_component_cents=20000, deposit_component_cents=0,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    v1 = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "GRANTED"


def test_league_bubbles_to_granted_when_all_children_granted(api):
    """PRD §3.8: "It rolls the series to GRANTED when every child is granted,
    meaning granted_occurrence_count equals occurrences."

    League of 1 occurrence; granting its single child rolls the series to GRANTED.

    Design: Corner/state_machines/league_bubble_up_to_granted_when_all_children_granted
    """
    ctx = setup_league_with_children(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Bub Field", "facility_type": "FIELD",
                            "deposit_cents": 0},
        occurrences=1,
    )
    facility, league, children = ctx["facility"], ctx["league"], ctx["children"]
    child = children[0]
    capture_payment(child["id"], 20000, 0)
    v = facility_version(facility["id"])
    granted = grant_permit(facility["id"], child["id"], v)
    assert granted["status"] == "GRANTED"

    league_after = validate_success(api.get_league(league["id"], COORD), 200)
    assert league_after["status"] == "GRANTED"
    assert league_after["granted_occurrence_count"] == 1


def test_ops_sweep_expires_coi_past_expiry(api):
    """PRD §3.10: "The sweep runs at the current clock and transitions every ACTIVE
    certificate whose expiry_date is at or before the current clock to EXPIRED."
    PRD §3.10: "The sweep reports how many certificates it expired and how many
    patrons it recomputed."

    COI expiring 2026-07-20, sweep at 2026-07-21 -> EXPIRED, expired_coi_count>=1.

    Design: Corner/state_machines/coi_expiry_via_ops_sweep
    """
    set_clock("2026-07-01T00:00:00Z")
    patron = create_patron(residency="NON_RESIDENT")
    coi = create_coi(
        patron["id"], coverage_amount_cents=100000,
        effective_date="2026-07-01T00:00:00Z", expiry_date="2026-07-20T00:00:00Z")
    set_clock("2026-07-21T00:00:00Z")
    swept = validate_success(api.ops_sweep(COORD), 200)
    assert swept["expired_coi_count"] >= 1

    got = validate_success(api.get_insurance_certificate(coi["id"], COORD), 200)
    assert got["status"] == "EXPIRED"
