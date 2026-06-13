"""Lottery selection, OCC on grant/draw, immediate consistency, scheduled clock.

Covers difficulty instance dual_variant_calc (lottery weighted selection vs permit
fee) and corner instances across errors (stale version), cross_cutting_complexity
(correct-version grant; clock gating), and consistency_model (immediate).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    set_clock, create_facility, create_patron, apply_permit, capture_payment,
    facility_version, grant_permit, setup_applied_permit, setup_granted_permit,
    setup_lottery_round_with_entries, get_first_refund,
    make_patron_headers, TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


def test_lottery_winner_by_weight_beats_earlier_entrant(api):
    """PRD §3.9: "Among the entries still in ENTERED status, the system picks the
    entry with the highest priority_weight; ties are broken by the lowest
    entry_seq, so the earliest qualifying entrant wins a tie."
    PRD §3.9: "The weight is 2 when the entrant is a verified resident — residency
    of RESIDENT with residency_verified true — and 1 otherwise."

    Non-resident (weight 1) enters first; verified resident (weight 2) enters
    second. Despite the later entry_seq, the resident wins on weight.

    Design: Difficulty/dual_variant_calc/dvc_lottery_priority_weight_vs_permit_fee
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={
            "name": "Lot Field", "facility_type": "FIELD", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.40, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
        },
        slot_start_at="2026-08-03T18:00:00Z", slot_end_at="2026-08-03T20:00:00Z",
        closes_at="2026-07-15T00:00:00Z",
        entrants=[
            {"verified": False, "residency": "NON_RESIDENT"},  # entry_seq earlier, weight 1
            {"verified": True, "residency": "RESIDENT"},       # entry_seq later, weight 2
        ],
    )
    facility, rnd, entries = ctx["facility"], ctx["round"], ctx["entries"]
    entry_non, entry_res = entries[0], entries[1]

    set_clock("2026-07-15T00:00:00Z")
    v = facility_version(facility["id"])
    drawn = validate_success(
        api.draw_lottery_round(rnd["id"], {"expected_facility_version": v}, COORD), 200)
    assert drawn["winning_entry_id"] == entry_res["id"], "weight 2 beats weight 1"

    got_res = validate_success(api.get_lottery_entry(entry_res["id"], COORD), 200)
    got_non = validate_success(api.get_lottery_entry(entry_non["id"], COORD), 200)
    assert got_res["status"] == "WON"
    assert got_non["status"] == "LOST"


def test_grant_with_stale_facility_version_rejected(api):
    """PRD §2.6: "When a permit is granted, the request must carry
    expected_facility_version matching the target facility's current version. If
    another writer — a competing grant, or a lottery draw that just placed a permit
    into the same prime window — has advanced the facility's version since the
    client last read it, the value no longer matches and the grant is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Two non-overlapping APPLIED permits. Grant P1 (version bumps). Grant P2 with the
    pre-P1 version (stale) -> ERR_STALE_VERSION.

    Design: Corner/errors/error_stale_version_grant_explicit
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(name="OCC Field", facility_type="FIELD")
    p1 = create_patron(residency="NON_RESIDENT")
    p2 = create_patron(residency="NON_RESIDENT")
    perm1 = apply_permit(facility["id"], p1["id"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z")
    perm2 = apply_permit(facility["id"], p2["id"], "2026-09-01T14:00:00Z", "2026-09-01T16:00:00Z")
    capture_payment(perm1["id"], 20000, 0)
    capture_payment(perm2["id"], 20000, 0)

    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], perm1["id"], v0)  # bumps facility version

    res = api.grant_permit(facility["id"], perm2["id"], {"expected_facility_version": v0}, COORD)
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_permit(perm2["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_grant_with_correct_version_succeeds_and_bumps(api):
    """PRD §2.6: "Both require the caller to submit expected_facility_version as a
    mandatory field carrying the version of the target Facility as the client last
    observed it."
    PRD §2.4: "The version field is an integer that begins at 1 on creation and
    increments by one on every mutation; it underpins the optimistic-concurrency
    mechanism described in §2.6."
    PRD §3.5: "increments the facility's version by one."

    Grant with the current version succeeds; facility version goes 1 → 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_grant_succeeds_and_bumps
    """
    ctx = setup_applied_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "OK Field", "facility_type": "FIELD"},
        start_at="2026-09-04T10:00:00Z", end_at="2026-09-04T12:00:00Z",
        capture=True, fee_component_cents=20000, deposit_component_cents=0,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    assert facility["version"] == 1
    granted = grant_permit(facility["id"], permit["id"], 1)
    assert granted["status"] == "GRANTED"
    fac_after = validate_success(api.get_facility(facility["id"], COORD), 200)
    assert fac_after["version"] == 2, "was 1, +1 on grant"


def test_clock_advance_enables_completion(api):
    """PRD §3.10: "A companion test-driving capability advances the server's logical
    clock to a supplied to_iso8601 instant, and that clock governs every temporal
    check in the system — window validity at application, lead time at cancellation,
    completion and no-show eligibility, certificate expiry, and lottery close."
    PRD §3.7: "Completion is a coordinator action on a GRANTED permit and is only
    allowed once the reservation has ended: the current clock must be at or after
    the permit's end_at."

    Granted permit; advancing the clock past end_at enables COMPLETE.

    Design: Corner/cross_cutting_complexity_layers/clock_set_gates_temporal_precondition
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Clk Pool", "facility_type": "POOL",
                            "deposit_cents": 3000},
        start_at="2026-09-05T10:00:00Z", end_at="2026-09-05T12:00:00Z",
        fee_component_cents=20000, deposit_component_cents=3000,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    set_clock("2026-09-05T13:00:00Z")
    completed = validate_success(api.complete_permit(facility["id"], permit["id"], COORD), 200)
    assert completed["status"] == "COMPLETED"
    refund = get_first_refund(permit["id"])
    assert refund is not None
    assert refund["deposit_refund_cents"] == 3000


def test_grant_effects_visible_in_grant_response(api):
    """PRD §3.5: "On a successful grant the system computes final_fee_cents ... It
    sets deposit_held_cents to the facility's deposit_cents, increments the
    facility's granted_permit_count by one, and increments the facility's version
    by one."
    PRD §2.2: "operations that create or modify a resource will return the created
    or updated resource object in the data field."

    Non-prime 2h window, NON_RESIDENT, hourly 10000 -> final 20000; deposit 1500.
    The grant's own response carries status GRANTED, final_fee_cents, deposit.

    Design: Corner/consistency_model/immediate_grant_visible_in_same_response
    """
    ctx = setup_applied_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "Imm Field", "facility_type": "FIELD", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.0, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 1500,
        },
        start_at="2026-09-06T10:00:00Z", end_at="2026-09-06T12:00:00Z",
        capture=True, fee_component_cents=20000, deposit_component_cents=1500,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    v = facility_version(facility["id"])
    granted = grant_permit(facility["id"], permit["id"], v)
    assert granted["status"] == "GRANTED"
    assert granted["final_fee_cents"] == 20000
    assert granted["deposit_held_cents"] == 1500
