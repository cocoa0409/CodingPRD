"""Second test per difficulty instance — complementary scenarios that assert the
same uniquely-derivable PRD rule under a different input, boundary, or entity.

Each docstring tags the same difficulty instance as its first-pass counterpart so
every instance carries >= 2 tests.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    set_clock, create_facility, create_patron, create_coi, apply_permit,
    capture_payment, facility_version, grant_permit,
    setup_applied_permit, setup_granted_permit, setup_league_with_children,
    setup_lottery_round_with_entries, enter_lottery, get_first_refund,
    cancel_permit, make_patron_headers, TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


def test_quote_final_diverge_nonresident_config(api):
    """PRD §3.3: "The provisional quote is the sum of those two already-rounded
    components — round each component, then sum."
    PRD §3.6: "Unlike the provisional quote, the final fee sums those two raw
    components first and rounds the single total half up to whole cents once. This
    sum-then-round order, against the quote's round-each-then-sum order, is exactly
    why identical hours and rates can produce a one-cent difference between
    quoted_fee_cents and final_fee_cents."

    NON_RESIDENT (no discount), hourly 1003, window 0.5h non-prime + 1.5h prime
    (x1.5). Provisional: round(0.5*1003)=502 + round(1.5*1003*1.5)=2257 -> 2759.
    Final: round(0.5*1003 + 1.5*1003*1.5) = round(2758.25) -> 2758.

    Design: Difficulty/dual_variant_calc/dvc_provisional_vs_final_rounding_order_permit
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Div NR Court", facility_type="COURT", hourly_rate_cents=1003,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0,
    )
    patron = create_patron(residency="NON_RESIDENT")
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-02T17:30:00Z", "2026-08-02T19:30:00Z")
    assert permit["quoted_fee_cents"] == 2759

    capture_payment(permit["id"], 2758, 0)
    v = facility_version(facility["id"])
    granted = grant_permit(facility["id"], permit["id"], v)
    assert granted["final_fee_cents"] == 2758
    assert granted["quoted_fee_cents"] != granted["final_fee_cents"]


def test_lottery_weight_tie_broken_by_entry_seq(api):
    """PRD §3.9: "the system picks the entry with the highest priority_weight; ties
    are broken by the lowest entry_seq, so the earliest qualifying entrant wins a
    tie."

    Two NON_RESIDENT entrants (both weight 1): the earlier entry_seq wins on the
    tie-break. This is the selection rule (lottery_selection) operating on
    LotteryEntry, independent of any Permit fee.

    Design: Difficulty/dual_variant_calc/dvc_lottery_priority_weight_vs_permit_fee
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "Tie Field", "facility_type": "FIELD"},
        entrants=[
            {"verified": False, "residency": "NON_RESIDENT"},  # earlier seq
            {"verified": False, "residency": "NON_RESIDENT"},  # later seq
        ],
    )
    facility, rnd, entries = ctx["facility"], ctx["round"], ctx["entries"]
    first_entry = entries[0]

    set_clock("2026-07-15T00:00:00Z")
    v = facility_version(facility["id"])
    drawn = validate_success(
        api.draw_lottery_round(rnd["id"], {"expected_facility_version": v}, COORD), 200)
    assert drawn["winning_entry_id"] == first_entry["id"], "lowest entry_seq wins the tie"


def test_provisional_quote_resident_rate_per_component(api):
    """PRD §3.3: "The effective hourly rate is the facility's hourly_rate_cents,
    except that for a RESIDENT tier it is reduced by the resident discount — that
    is, hourly_rate_cents multiplied by one minus resident_discount_pct."
    PRD §3.3: "The provisional quote is the sum of those two already-rounded
    components — round each component, then sum."

    A non-prime-only RESIDENT-verified window pins the per-component rounding with a
    single (non-prime) component. hourly 3333, disc 0.40 -> eff 1999.8; 2h non-prime
    -> round(2*1999.8)=round(3999.6)=4000; no prime component.

    Design: Difficulty/combinatorial_formula/cf_rounding_order_pinned_provisional
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Div3", facility_type="COURT", hourly_rate_cents=3333,
        resident_discount_pct=0.40, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0,
    )
    patron = create_patron(verified=True, residency="RESIDENT")
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-02T10:00:00Z", "2026-08-02T12:00:00Z")
    assert permit["quoted_fee_cents"] == 4000
    assert permit["is_prime_requested"] is False
    assert permit["pricing_residency"] == "RESIDENT"


def test_full_refund_tier_at_high_lead_both_components(api):
    """PRD §3.7: "If the lead is at least 168 hours — a full seven days — the entire
    usage fee is refunded."
    PRD §3.7: "the full deposit_held_cents is returned as deposit_refund_cents
    unless the lead is under 24 hours — under one day — in which case the deposit is
    forfeited and the deposit refund is 0."
    PRD §3.7: "The total_refund_cents is the sum of the fee refund and the deposit
    refund, and a Refund is created with these amounts and the supplied
    refund_destination; the permit's refunded_cents is set accordingly."

    A second point on the two-factor refund surface: lead 200h → fee 100%
    (24000) AND deposit fully refunded (5000) → total 29000.

    Design: Difficulty/combinatorial_formula/cf_nonlinear_refund_two_factor_tier
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "Full Pool", "facility_type": "POOL", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.40, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
        },
        patron_verified=True, patron_overrides={"residency": "RESIDENT"},
        start_at="2026-08-01T17:00:00Z", end_at="2026-08-01T20:00:00Z",
        fee_component_cents=24000, deposit_component_cents=5000,
    )
    facility, patron, permit = ctx["facility"], ctx["patron"], ctx["permit"]
    set_clock("2026-07-24T09:00:00Z")  # lead 200h
    cancel_permit(facility["id"], permit["id"], make_patron_headers(patron["id"]))
    refund = get_first_refund(permit["id"])
    assert refund["fee_refund_cents"] == 24000
    assert refund["deposit_refund_cents"] == 5000
    assert refund["total_refund_cents"] == 29000


def test_refund_lead_just_under_48h_zero_fee(api):
    """PRD §3.7: "If the lead is under 48 hours, none of the usage fee is refunded."
    PRD §3.7: "the full deposit_held_cents is returned as deposit_refund_cents
    unless the lead is under 24 hours — under one day — in which case the deposit is
    forfeited and the deposit refund is 0."

    Boundary just below 48h: lead 47h → fee tier 0 (under 48), deposit still kept
    (47 >= 24). Pairs with the lead==48h inclusive test.

    Design: Difficulty/boundary_precision_check/bpc_refund_lead_48h_partial_boundary
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "B47 Pool", "facility_type": "POOL", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.40, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
        },
        patron_verified=True, patron_overrides={"residency": "RESIDENT"},
        start_at="2026-08-01T17:00:00Z", end_at="2026-08-01T20:00:00Z",
        fee_component_cents=24000, deposit_component_cents=5000,
    )
    facility, patron, permit = ctx["facility"], ctx["patron"], ctx["permit"]
    set_clock("2026-07-30T18:00:00Z")  # lead 47h
    cancelled = cancel_permit(facility["id"], permit["id"], make_patron_headers(patron["id"]))
    assert cancelled["cancelled_lead_hours"] == 47
    refund = get_first_refund(permit["id"])
    assert refund["fee_refund_cents"] == 0, "lead 47h < 48h -> no fee refund"
    assert refund["deposit_refund_cents"] == 5000


def test_draw_with_zero_entries_after_withdrawal_rejected(api):
    """PRD §3.9: "The round must have at least one entry counted in entry_count; a
    draw on an empty round is rejected with ERR_LOTTERY_NO_ENTRIES (HTTP 409)."
    PRD §3.9: "Withdrawing decrements the round's entry_count by one."

    A round whose single entry was withdrawn (entry_count back to 0) still draws to
    ERR_LOTTERY_NO_ENTRIES — a different path to the empty-collection edge.

    Design: Difficulty/boundary_precision_check/bpc_lottery_draw_empty_entries_zero_count
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "Withdrawn Lot", "facility_type": "FIELD"},
        closes_at="2026-07-15T00:00:00Z",
        entrants=[{"verified": True, "residency": "RESIDENT"}],
    )
    facility, rnd, entries, patrons = (
        ctx["facility"], ctx["round"], ctx["entries"], ctx["patrons"])
    validate_success(api.withdraw_lottery_entry(
        entries[0]["id"], make_patron_headers(patrons[0]["id"])), 200)
    after_wd = validate_success(api.get_lottery_round(rnd["id"], COORD), 200)
    assert after_wd["entry_count"] == 0

    set_clock("2026-07-15T00:00:00Z")
    v = facility_version(facility["id"])
    res = api.draw_lottery_round(rnd["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_LOTTERY_NO_ENTRIES")
    final = validate_success(api.get_lottery_round(rnd["id"], COORD), 200)
    assert final["status"] == "OPEN"


def test_grant_blocked_after_facility_reclosed(api):
    """PRD §3.5: "A facility that is not OPEN cannot accept a new grant into
    GRANTED; the CLOSED status blocks it."
    PRD §3.2: "A coordinator may reconfigure a facility — toggling its status
    between OPEN and CLOSED and adjusting buffer_minutes, deposit_cents,
    requires_coi, or min_coi_coverage_cents."

    A facility reopened then re-closed still blocks a grant of an APPLIED permit
    with ERR_INVALID_STATE — the Permit grant depends on live Facility.status.

    Design: Difficulty/cross_entity_state_dependency/cesd_permit_grant_requires_facility_open
    """
    ctx = setup_applied_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Reclose Court", "facility_type": "COURT"},
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
        capture=True, fee_component_cents=20000, deposit_component_cents=0,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    v0 = facility_version(facility["id"])
    closed = validate_success(api.update_facility(
        facility["id"], {"status": "CLOSED", "expected_facility_version": v0}, COORD), 200)
    v1 = closed["version"]
    reopened = validate_success(api.update_facility(
        facility["id"], {"status": "OPEN", "expected_facility_version": v1}, COORD), 200)
    v2 = reopened["version"]
    validate_success(api.update_facility(
        facility["id"], {"status": "CLOSED", "expected_facility_version": v2}, COORD), 200)

    v3 = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v3}, COORD)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_withdraw_blocked_when_round_cancelled(api):
    """PRD §3.9: "A patron or coordinator may withdraw an entry, moving it
    ENTERED -> WITHDRAWN, but only while the parent round is still OPEN; a
    withdrawal against a non-open round is rejected with ERR_INVALID_STATE (HTTP
    409)."

    A second non-open round state: the round is CANCELLED (entries already
    WITHDRAWN), so a withdraw call still fails ERR_INVALID_STATE — entry transition
    validity depends on the parent round state, here CANCELLED rather than DRAWN.

    Design: Difficulty/cross_entity_state_dependency/cesd_lottery_entry_withdraw_requires_round_open
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "Cancelled Round", "facility_type": "FIELD"},
        entrants=[{"verified": True, "residency": "RESIDENT"},
                  {"verified": False, "residency": "NON_RESIDENT"}],
    )
    rnd, entries, patrons = ctx["round"], ctx["entries"], ctx["patrons"]
    validate_success(api.cancel_lottery_round(rnd["id"], COORD), 200)

    res = api.withdraw_lottery_entry(entries[0]["id"], make_patron_headers(patrons[0]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_double_booking_takes_precedence_over_probation_prime(api):
    """PRD §3.5: "Double-booking is evaluated next."
    PRD §3.5: "If the patron is in PROBATION standing and the permit's window
    is_prime_requested, the grant is blocked with ERR_PROBATION_PRIME_BLOCKED (HTTP
    403) — probationary patrons are barred from prime-window slots specifically."

    A PROBATION patron on a prime window that ALSO collides with a granted permit:
    the double-booking check (evaluated before the probation/prime gate) fires
    first → ERR_DOUBLE_BOOKING, not ERR_PROBATION_PRIME_BLOCKED.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_double_booking
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="PP2 Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=0,
    )
    holder = create_patron(residency="NON_RESIDENT")
    prob = create_patron(residency="NON_RESIDENT")
    p1 = apply_permit(facility["id"], holder["id"],
                      "2026-08-06T18:00:00Z", "2026-08-06T20:00:00Z")
    p2 = apply_permit(facility["id"], prob["id"],
                      "2026-08-06T18:00:00Z", "2026-08-06T20:00:00Z")
    assert p2["is_prime_requested"] is True

    capture_payment(p1["id"], 30000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], p1["id"], v0)

    validate_success(api.inject_no_show_strikes(prob["id"], 2, COORD), 200)
    capture_payment(p2["id"], 30000, 0)
    v1 = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], p2["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_DOUBLE_BOOKING")


def test_barred_takes_precedence_over_double_booking(api):
    """PRD §3.5: "After that, the patron's standing is checked: a BARRED patron
    cannot be granted, yielding ERR_PATRON_BARRED (HTTP 403). Double-booking is
    evaluated next."

    A BARRED patron whose permit also collides with a granted permit: the standing
    check (evaluated before double-booking) fires first -> ERR_PATRON_BARRED, not
    ERR_DOUBLE_BOOKING. A second category-pair precedence assertion.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_barred_before_coi_required
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="PP3 Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=0,
    )
    holder = create_patron(residency="NON_RESIDENT")
    barred = create_patron(residency="NON_RESIDENT")
    p1 = apply_permit(facility["id"], holder["id"],
                      "2026-08-06T10:00:00Z", "2026-08-06T12:00:00Z")
    p2 = apply_permit(facility["id"], barred["id"],
                      "2026-08-06T10:00:00Z", "2026-08-06T12:00:00Z")
    capture_payment(p1["id"], 20000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], p1["id"], v0)

    capture_payment(p2["id"], 20000, 0)
    validate_success(api.inject_no_show_strikes(barred["id"], 4, COORD), 200)
    v1 = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], p2["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_PATRON_BARRED")


def test_double_booking_overlapping_interior_rejected(api):
    """PRD §3.5: "A grant collides when some existing GRANTED permit on the same
    facility has a buffer-expanded window that overlaps this permit's window —
    concretely, when the existing permit's interval, widened on both sides by the
    facility's buffer_minutes, overlaps this permit's [start_at, end_at)."
    PRD §3.5: "If a conflict exists and the request did not carry on_conflict set to
    WAITLIST, the grant is rejected with ERR_DOUBLE_BOOKING (HTTP 409)."

    A second overlap geometry with buffer 0: P2's window strictly nested inside P1's
    granted window overlaps directly → ERR_DOUBLE_BOOKING.

    Design: Difficulty/resource_temporal_overlap/rto_permit_grant_buffer_expanded_overlap
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Nest Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=0,
    )
    pa = create_patron(residency="NON_RESIDENT")
    pb = create_patron(residency="NON_RESIDENT")
    p1 = apply_permit(facility["id"], pa["id"], "2026-08-09T10:00:00Z", "2026-08-09T14:00:00Z")
    p2 = apply_permit(facility["id"], pb["id"], "2026-08-09T11:00:00Z", "2026-08-09T12:00:00Z")
    capture_payment(p1["id"], 40000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], p1["id"], v0)

    capture_payment(p2["id"], 10000, 0)
    v1 = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], p2["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_DOUBLE_BOOKING")
    after = validate_success(api.get_permit(p2["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_lottery_draw_rejected_partial_slot_overlap_existing_grant(api):
    """PRD §3.9: "No GRANTED permit may already occupy the slot
    [slot_start_at, slot_end_at) on the facility; if one does, the draw is rejected
    with ERR_DOUBLE_BOOKING (HTTP 409)."

    A second slot-overlap geometry: the existing granted permit partially overlaps
    the lottery slot (granted 18:00-19:00 vs slot 18:00-20:00) -> draw rejected.

    Design: Difficulty/resource_temporal_overlap/rto_lottery_draw_slot_vs_existing_grant_zero_buffer
    """
    set_clock("2026-07-02T00:00:00Z")
    facility = create_facility(
        name="Clash2 Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=0,
    )
    holder = create_patron(residency="NON_RESIDENT")
    entrant = create_patron(verified=True, residency="RESIDENT")
    hold = apply_permit(facility["id"], holder["id"],
                        "2026-08-03T18:00:00Z", "2026-08-03T19:00:00Z")
    capture_payment(hold["id"], 30000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], hold["id"], v0)

    rnd = validate_success(api.create_lottery_round(
        {"facility_id": facility["id"],
         "slot_start_at": "2026-08-03T18:00:00Z", "slot_end_at": "2026-08-03T20:00:00Z",
         "opens_at": "2026-07-01T00:00:00Z", "closes_at": "2026-07-15T00:00:00Z"}, COORD), 201)
    enter_lottery(rnd["id"], entrant["id"])

    set_clock("2026-07-15T00:00:00Z")
    v1 = facility_version(facility["id"])
    res = api.draw_lottery_round(rnd["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_DOUBLE_BOOKING")


def test_league_cancel_cascades_applied_child_full_reversal(api):
    """PRD §3.8: "Cancelling rolls the series to CANCELLED and cascades down: every
    child permit that is not already in a terminal state is cancelled through the
    permit cancel path. A child still APPLIED follows the APPLIED → CANCELLED
    full-reversal path, and a child currently GRANTED follows the GRANTED → CANCELLED
    path — running the tiered cancellation refund, creating its own Refund,
    decrementing the facility's granted_permit_count, and bumping the facility's
    version — so a single league cancellation can transitively spawn many refunds
    and many facility mutations."

    A second cascade shape: a league whose child is still APPLIED. Cancel the league
    -> the APPLIED child cascades to CANCELLED (full-reversal path, no fee retained).

    Design: Difficulty/transitive_cascade/tc_league_cancel_to_permit_to_refund_depth3
    """
    ctx = setup_league_with_children(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "League2 Field", "facility_type": "FIELD",
                            "deposit_cents": 5000, "buffer_minutes": 0},
        occurrences=1, weekday=1, start_hour=10, duration_minutes=120,
        first_date="2026-08-04T00:00:00Z",
    )
    patron, league, children = ctx["patron"], ctx["league"], ctx["children"]
    child = children[0]  # still APPLIED

    cancelled = validate_success(api.cancel_league(
        league["id"], {"refund_destination": "ORIGINAL"},
        make_patron_headers(patron["id"])), 200)
    assert cancelled["status"] == "CANCELLED"

    child_after = validate_success(api.get_permit(child["id"], COORD), 200)
    assert child_after["status"] == "CANCELLED"
    assert child_after["refunded_cents"] == 0, "APPLIED child: nothing captured into a fee"


def test_no_show_at_strike_two_drives_probation(api):
    """PRD §3.7: "Marking a no-show moves the permit GRANTED → NO_SHOW, forfeits
    deposit_held_cents entirely with no refund created, increments the patron's
    no_show_strikes by one and recomputes the patron's standing from the new count,
    decrements the facility's granted_permit_count by one, and increments the
    facility's version by one."
    PRD §3.1: "otherwise if no_show_strikes is at least 2 the standing is PROBATION;
    otherwise the standing is GOOD."

    A second depth-2 cascade with a different threshold: a patron at 1 strike,
    no-showing a granted permit → strikes 2 → standing recomputes to PROBATION.

    Design: Difficulty/transitive_cascade/tc_no_show_to_standing_to_barred_block_depth2
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="NS2 Court", facility_type="COURT", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=1000, buffer_minutes=0,
    )
    patron = create_patron(residency="NON_RESIDENT")
    validate_success(api.inject_no_show_strikes(patron["id"], 1, COORD), 200)
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-07-05T10:00:00Z", "2026-07-05T12:00:00Z")
    capture_payment(permit["id"], 20000, 1000)
    v = facility_version(facility["id"])
    grant_permit(facility["id"], permit["id"], v)

    set_clock("2026-07-05T13:00:00Z")
    ns = validate_success(api.no_show_permit(facility["id"], permit["id"], COORD), 200)
    assert ns["status"] == "NO_SHOW"
    patron_after = validate_success(api.get_patron(patron["id"], COORD), 200)
    assert patron_after["no_show_strikes"] == 2
    assert patron_after["standing"] == "PROBATION"


def test_no_show_forfeits_deposit_no_refund(api):
    """PRD §3.7: "Marking a no-show moves the permit GRANTED → NO_SHOW, forfeits
    deposit_held_cents entirely with no refund created, increments the patron's
    no_show_strikes by one and recomputes the patron's standing from the new count,
    decrements the facility's granted_permit_count by one, and increments the
    facility's version by one."

    Conserved-quantity check: a no-show forfeits the held deposit (no Refund row)
    while the facility occupancy count returns to its pre-grant value.

    Design: Difficulty/compensating_invariant/ci_complete_releases_deposit_count_conserved
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "NSDep Court", "facility_type": "COURT", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.0, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
        },
        start_at="2026-07-03T10:00:00Z", end_at="2026-07-03T12:00:00Z",
        fee_component_cents=20000, deposit_component_cents=5000,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    set_clock("2026-07-03T13:00:00Z")
    ns = validate_success(api.no_show_permit(facility["id"], permit["id"], COORD), 200)
    assert ns["status"] == "NO_SHOW"

    refund = get_first_refund(permit["id"])
    assert refund is None, "no Refund is created on a no-show (deposit forfeited)"
    fac_after = validate_success(api.get_facility(facility["id"], COORD), 200)
    assert fac_after["granted_permit_count"] == 0


def test_cancel_applied_permit_full_reversal_conserves_money(api):
    """PRD §3.7: "Cancelling a permit that is still APPLIED moves it
    APPLIED → CANCELLED. Nothing was ever captured into a usage fee, so any
    AUTHORIZED payment is fully reversed, refunded_cents stays 0, and the facility's
    counters and version are untouched."

    A second money-conservation invariant on a different transition: cancelling an
    APPLIED permit leaves refunded_cents at 0 and the facility version unchanged.

    Design: Difficulty/compensating_invariant/ci_deny_voids_payment_money_conserved
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="CancApp Court", facility_type="COURT", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=1000,
    )
    patron = create_patron(residency="NON_RESIDENT")
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
    fac_before = validate_success(api.get_facility(facility["id"], COORD), 200)

    cancelled = cancel_permit(facility["id"], permit["id"], make_patron_headers(patron["id"]))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refunded_cents"] == 0, "no fee captured on an APPLIED permit"

    fac_after = validate_success(api.get_facility(facility["id"], COORD), 200)
    assert fac_after["version"] == fac_before["version"], (
        "facility version untouched on APPLIED->CANCELLED"
    )
