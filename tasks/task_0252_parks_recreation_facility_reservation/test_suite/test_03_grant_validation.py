"""Grant-time validation: priority-pair precedence, double-booking (buffer and
slot overlap), COI/payment/standing gates, window validity.

Covers difficulty instances priority_pair_validation_conflict (state-before-
double-booking; barred-before-coi), resource_temporal_overlap (buffer-expanded
overlap; lottery slot overlap), plus corner validations instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    set_clock, create_facility, create_patron, create_coi, apply_permit,
    capture_payment, facility_version, grant_permit,
    setup_applied_permit, setup_lottery_round_with_entries, enter_lottery,
    make_patron_headers, TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


def test_invalid_state_takes_precedence_over_double_booking(api):
    """PRD §3.5: "Then the target permit must be in a state from which a grant is
    defined — that is, APPLIED or WAITLISTED; otherwise ERR_INVALID_STATE (HTTP
    409)."
    PRD §3.5: "Double-booking is evaluated next."

    P1 GRANTED on a window; P2 overlaps, first DENIED (terminal); re-grant P2 ->
    the state check (DENIED, not APPLIED/WAITLISTED) fires before double-booking,
    yielding ERR_INVALID_STATE, not ERR_DOUBLE_BOOKING.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_before_double_booking
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="PP Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=0,
    )
    pa = create_patron(residency="NON_RESIDENT")
    pb = create_patron(residency="NON_RESIDENT")
    p1 = apply_permit(facility["id"], pa["id"], "2026-08-06T10:00:00Z", "2026-08-06T12:00:00Z")
    p2 = apply_permit(facility["id"], pb["id"], "2026-08-06T10:00:00Z", "2026-08-06T12:00:00Z")

    capture_payment(p1["id"], 20000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], p1["id"], v0)
    validate_success(api.deny_permit(facility["id"], p2["id"], COORD), 200)

    v = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], p2["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_INVALID_STATE")

    after = validate_success(api.get_permit(p2["id"], COORD), 200)
    assert after["status"] == "DENIED", "permit stays DENIED"


def test_barred_takes_precedence_over_coi_required(api):
    """PRD §3.5: "After that, the patron's standing is checked: a BARRED patron
    cannot be granted, yielding ERR_PATRON_BARRED (HTTP 403)."
    PRD §3.5: "a missing or non-active certificate yields ERR_COI_REQUIRED (HTTP
    422), and a presented certificate whose coverage is below the minimum or whose
    expiry_date is at or before start_at yields ERR_COI_INSUFFICIENT (HTTP 422)."

    BARRED patron (4 strikes) on a requires_coi facility WITHOUT a COI: the standing
    check fires before the COI check, yielding ERR_PATRON_BARRED, not
    ERR_COI_REQUIRED.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_barred_before_coi_required
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="COI Pool", facility_type="POOL", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0,
        requires_coi=True, min_coi_coverage_cents=100000,
    )
    patron = create_patron(residency="NON_RESIDENT")
    # Apply while the patron is still GOOD (a BARRED patron cannot apply, PRD §3.3),
    # then bar them before the grant so the standing gate is exercised at grant.
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-07T10:00:00Z", "2026-08-07T12:00:00Z")
    capture_payment(permit["id"], 20000, 0)
    validate_success(api.inject_no_show_strikes(patron["id"], 4, COORD), 200)

    v = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_PATRON_BARRED")

    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_double_booking_buffer_expanded_overlap_rejected(api):
    """PRD §3.5: "A grant collides when some existing GRANTED permit on the same
    facility has a buffer-expanded window that overlaps this permit's window —
    concretely, when the existing permit's interval, widened on both sides by the
    facility's buffer_minutes, overlaps this permit's [start_at, end_at)."
    PRD §3.5: "If a conflict exists and the request did not carry on_conflict set to
    WAITLIST, the grant is rejected with ERR_DOUBLE_BOOKING (HTTP 409)."

    buffer_minutes=30. P1 granted 10:00-12:00. P2 requests 12:00-13:00 (adjacent
    but inside P1's [10:00,12:30) buffer) -> ERR_DOUBLE_BOOKING.

    Design: Difficulty/resource_temporal_overlap/rto_permit_grant_buffer_expanded_overlap
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Buf Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=30,
    )
    pa = create_patron(residency="NON_RESIDENT")
    pb = create_patron(residency="NON_RESIDENT")
    p1 = apply_permit(facility["id"], pa["id"], "2026-08-09T10:00:00Z", "2026-08-09T12:00:00Z")
    p2 = apply_permit(facility["id"], pb["id"], "2026-08-09T12:00:00Z", "2026-08-09T13:00:00Z")

    capture_payment(p1["id"], 20000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], p1["id"], v0)

    capture_payment(p2["id"], 10000, 0)
    v1 = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], p2["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_DOUBLE_BOOKING")

    after = validate_success(api.get_permit(p2["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_lottery_draw_rejected_when_slot_already_granted(api):
    """PRD §3.9: "No GRANTED permit may already occupy the slot
    [slot_start_at, slot_end_at) on the facility; if one does, the draw is rejected
    with ERR_DOUBLE_BOOKING (HTTP 409)."

    A permit is GRANTED on the exact slot; a lottery round on the same slot draws
    after close -> ERR_DOUBLE_BOOKING (plain half-open overlap, buffer 0).

    Design: Difficulty/resource_temporal_overlap/rto_lottery_draw_slot_vs_existing_grant_zero_buffer
    """
    set_clock("2026-07-02T00:00:00Z")
    facility = create_facility(
        name="Clash Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, buffer_minutes=0,
    )
    holder = create_patron(residency="NON_RESIDENT")
    entrant = create_patron(verified=True, residency="RESIDENT")

    hold_permit = apply_permit(
        facility["id"], holder["id"], "2026-08-03T18:00:00Z", "2026-08-03T20:00:00Z")
    capture_payment(hold_permit["id"], 30000, 0)
    v0 = facility_version(facility["id"])
    grant_permit(facility["id"], hold_permit["id"], v0)

    rnd = validate_success(api.create_lottery_round(
        {"facility_id": facility["id"],
         "slot_start_at": "2026-08-03T18:00:00Z", "slot_end_at": "2026-08-03T20:00:00Z",
         "opens_at": "2026-07-01T00:00:00Z", "closes_at": "2026-07-15T00:00:00Z"}, COORD), 201)
    enter_lottery(rnd["id"], entrant["id"])

    set_clock("2026-07-15T00:00:00Z")
    v1 = facility_version(facility["id"])
    res = api.draw_lottery_round(rnd["id"], {"expected_facility_version": v1}, COORD)
    validate_error(res, "ERR_DOUBLE_BOOKING")

    after = validate_success(api.get_lottery_round(rnd["id"], COORD), 200)
    assert after["status"] == "OPEN"


def test_draw_empty_round_rejected(api):
    """PRD §3.9: "The round must have at least one entry counted in entry_count; a
    draw on an empty round is rejected with ERR_LOTTERY_NO_ENTRIES (HTTP 409)."

    A closed round with zero entries drawn -> ERR_LOTTERY_NO_ENTRIES, round stays
    OPEN.

    Design: Difficulty/boundary_precision_check/bpc_lottery_draw_empty_entries_zero_count
    """
    set_clock("2026-07-02T00:00:00Z")
    facility = create_facility(name="Empty Lot", facility_type="FIELD")
    rnd = validate_success(api.create_lottery_round(
        {"facility_id": facility["id"],
         "slot_start_at": "2026-08-03T18:00:00Z", "slot_end_at": "2026-08-03T20:00:00Z",
         "opens_at": "2026-07-01T00:00:00Z", "closes_at": "2026-07-15T00:00:00Z"}, COORD), 201)
    assert rnd["entry_count"] == 0

    set_clock("2026-07-15T00:00:00Z")
    v = facility_version(facility["id"])
    res = api.draw_lottery_round(rnd["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_LOTTERY_NO_ENTRIES")

    after = validate_success(api.get_lottery_round(rnd["id"], COORD), 200)
    assert after["status"] == "OPEN"


# ─── Corner: validations ──────────────────────────────────────────────────────

def test_apply_past_window_rejected(api):
    """PRD §3.3: "The reservation window must be well-formed: start_at must be
    strictly before end_at, and both must lie in the future relative to the current
    clock at application time. A window that violates either rule is rejected with
    ERR_INVALID_WINDOW (HTTP 422)."

    Design: Corner/validations/apply_past_window_returns_invalid_window
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(name="Past Field", facility_type="FIELD")
    patron = create_patron(residency="NON_RESIDENT")
    res = api.apply_permit(
        facility["id"],
        {"patron_id": patron["id"], "start_at": "2026-06-01T10:00:00Z",
         "end_at": "2026-06-01T12:00:00Z"},
        make_patron_headers(patron["id"]))
    validate_error(res, "ERR_INVALID_WINDOW")


def test_apply_start_after_end_rejected(api):
    """PRD §3.3: "The reservation window must be well-formed: start_at must be
    strictly before end_at, and both must lie in the future relative to the current
    clock at application time. A window that violates either rule is rejected with
    ERR_INVALID_WINDOW (HTTP 422)."

    Design: Corner/validations/apply_start_after_end_returns_invalid_window
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(name="Inv Field", facility_type="FIELD")
    patron = create_patron(residency="NON_RESIDENT")
    res = api.apply_permit(
        facility["id"],
        {"patron_id": patron["id"], "start_at": "2026-08-27T12:00:00Z",
         "end_at": "2026-08-27T10:00:00Z"},
        make_patron_headers(patron["id"]))
    validate_error(res, "ERR_INVALID_WINDOW")


def test_grant_without_payment_rejected(api):
    """PRD §3.5: "Finally, a CAPTURED payment must exist for this permit covering
    the sum of final_fee_cents and the facility's deposit_cents; if no such payment
    exists the grant is rejected with ERR_PAYMENT_REQUIRED (HTTP 422)."

    Design: Corner/validations/grant_without_payment_returns_payment_required
    """
    ctx = setup_applied_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={"name": "Pay Field", "facility_type": "FIELD",
                            "deposit_cents": 1000},
        start_at="2026-08-28T10:00:00Z", end_at="2026-08-28T12:00:00Z",
        capture=False,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    v = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_PAYMENT_REQUIRED")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_grant_coi_under_coverage_rejected(api):
    """PRD §3.5: "a presented certificate whose coverage is below the minimum or
    whose expiry_date is at or before start_at yields ERR_COI_INSUFFICIENT (HTTP
    422)."

    requires_coi facility, min 100000, COI coverage 50000 presented -> insufficient.

    Design: Corner/validations/grant_coi_under_coverage_returns_insufficient
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="CoiLow Pool", facility_type="POOL", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22,
        requires_coi=True, min_coi_coverage_cents=100000,
    )
    patron = create_patron(residency="NON_RESIDENT")
    coi = create_coi(patron["id"], coverage_amount_cents=50000,
                     effective_date="2026-07-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z")
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-29T10:00:00Z", "2026-08-29T12:00:00Z", coi_id=coi["id"])
    capture_payment(permit["id"], 20000, 0)
    v = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_COI_INSUFFICIENT")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_grant_requires_coi_none_presented_rejected(api):
    """PRD §3.5: "If the facility's requires_coi is set, a coi_id must be present,
    its certificate must be ACTIVE, its coverage_amount_cents must be at least the
    facility's min_coi_coverage_cents, and its expiry_date must be strictly after
    the permit's start_at; a missing or non-active certificate yields
    ERR_COI_REQUIRED (HTTP 422)"

    requires_coi facility, permit has no coi_id -> ERR_COI_REQUIRED.

    Design: Corner/validations/grant_requires_coi_none_returns_required
    """
    ctx = setup_applied_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "CoiReq Pool", "facility_type": "POOL",
            "requires_coi": True, "min_coi_coverage_cents": 100000,
        },
        start_at="2026-08-30T10:00:00Z", end_at="2026-08-30T12:00:00Z",
        capture=True, fee_component_cents=20000, deposit_component_cents=0,
    )
    facility, permit = ctx["facility"], ctx["permit"]
    v = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_COI_REQUIRED")


def test_grant_probation_on_prime_window_blocked(api):
    """PRD §3.5: "If the patron is in PROBATION standing and the permit's window
    is_prime_requested, the grant is blocked with ERR_PROBATION_PRIME_BLOCKED (HTTP
    403) — probationary patrons are barred from prime-window slots specifically."

    PROBATION patron (2 strikes), prime window 18:00-20:00 -> blocked.

    Design: Corner/validations/grant_probation_on_prime_window_blocked
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Prob Field", facility_type="FIELD", hourly_rate_cents=10000,
        resident_discount_pct=0.0, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22,
    )
    patron = create_patron(residency="NON_RESIDENT")
    validate_success(api.inject_no_show_strikes(patron["id"], 2, COORD), 200)
    permit = apply_permit(facility["id"], patron["id"],
                          "2026-08-31T18:00:00Z", "2026-08-31T20:00:00Z")
    assert permit["is_prime_requested"] is True
    capture_payment(permit["id"], 30000, 0)
    v = facility_version(facility["id"])
    res = api.grant_permit(facility["id"], permit["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_PROBATION_PRIME_BLOCKED")
    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "APPLIED"


def test_lottery_draw_before_close_rejected(api):
    """PRD §3.9: "The current clock must be at or after the round's closes_at; a
    draw before close is rejected with ERR_LOTTERY_NOT_CLOSED (HTTP 409)."

    Round closes 2026-07-15; draw at 2026-07-10 (before close) -> not closed.

    Design: Corner/validations/lottery_draw_before_close_returns_not_closed
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "Early Lot", "facility_type": "FIELD"},
        closes_at="2026-07-15T00:00:00Z",
        entrants=[{"verified": True, "residency": "RESIDENT"}],
    )
    facility, rnd = ctx["facility"], ctx["round"]
    set_clock("2026-07-10T00:00:00Z")
    v = facility_version(facility["id"])
    res = api.draw_lottery_round(rnd["id"], {"expected_facility_version": v}, COORD)
    validate_error(res, "ERR_LOTTERY_NOT_CLOSED")
    after = validate_success(api.get_lottery_round(rnd["id"], COORD), 200)
    assert after["status"] == "OPEN"


def test_duplicate_lottery_entry_rejected(api):
    """PRD §3.9: "A patron may hold at most one ENTERED entry per round; a second
    entry by the same patron in the same round is rejected with ERR_DUPLICATE_ENTRY
    (HTTP 409)."

    Design: Corner/validations/duplicate_lottery_entry_rejected
    """
    ctx = setup_lottery_round_with_entries(
        clock="2026-07-02T00:00:00Z",
        facility_overrides={"name": "Dup Lot", "facility_type": "FIELD"},
        entrants=[{"verified": True, "residency": "RESIDENT"}],
    )
    rnd, patrons = ctx["round"], ctx["patrons"]
    patron = patrons[0]
    res = api.create_lottery_entry(
        rnd["id"], {"patron_id": patron["id"]}, make_patron_headers(patron["id"]))
    validate_error(res, "ERR_DUPLICATE_ENTRY")
    after = validate_success(api.get_lottery_round(rnd["id"], COORD), 200)
    assert after["entry_count"] == 1
