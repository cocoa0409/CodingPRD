"""Parking-pass fee computation, lot capacity boundary, and space conservation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_parking_pass_payload,
    setup_lot, new_parking_pass,
)

CLERK = TEST_USERS["parking_clerk_headers"]


# --- Combinatorial DAILY fee: weekend x oversized x resident -----------------

def test_daily_weekend_oversized_resident_fee(api):
    """PRD §3.7: "For a `DAILY` pass, start from the lot's `daily_rate_cents` multiplied by the
    day-type factor — 1.5 on a weekend, 1.0 on a weekday — then add a surcharge of 2000 cents
    if the `vehicle_type` is `OVERSIZED` (and nothing otherwise); finally, if `is_resident` is
    true, apply a resident discount by multiplying the running amount by one-half (that is, take
    fifty percent off), and if not, apply no discount; the final amount is rounded half-up to
    whole cents."

    Design: Difficulty/combinatorial_formula/parking_fee_weekend_oversized_resident_nonlinear
    """
    beach, lot = setup_lot(api, total_spaces=50, daily_rate_cents=1200, clock="2026-07-18T10:00:00Z")
    payload = create_parking_pass_payload(lot["id"], "ABC123", "OVERSIZED", "DAILY", is_resident=True)
    data = validate_success(api.create_parking_pass(payload, CLERK), 201)
    assert data["fee_cents"] == 1900, f"expected round((1200*1.5+2000)*0.5)=1900, got {data['fee_cents']}"


def test_daily_weekend_oversized_resident_fee_persists(api):
    """PRD §3.7: "For a `DAILY` pass, start from the lot's `daily_rate_cents` multiplied by the
    day-type factor — 1.5 on a weekend, 1.0 on a weekday — then add a surcharge of 2000 cents
    if the `vehicle_type` is `OVERSIZED` (and nothing otherwise); finally, if `is_resident` is
    true, apply a resident discount by multiplying the running amount by one-half (that is, take
    fifty percent off), and if not, apply no discount; the final amount is rounded half-up to
    whole cents."

    Design: Difficulty/combinatorial_formula/parking_fee_weekend_oversized_resident_nonlinear
    """
    beach, lot = setup_lot(api, total_spaces=50, daily_rate_cents=1200, clock="2026-07-18T10:00:00Z")
    payload = create_parking_pass_payload(lot["id"], "ABC123", "OVERSIZED", "DAILY", is_resident=True)
    created = validate_success(api.create_parking_pass(payload, CLERK), 201)
    fetched = validate_success(api.get_parking_pass(created["id"], CLERK), 200)
    assert fetched["fee_cents"] == 1900, f"persisted fee must be 1900, got {fetched['fee_cents']}"


# --- Lot capacity zero-space boundary ----------------------------------------

def test_first_pass_at_one_space_is_active(api):
    """PRD §3.7: "On issuance the server computes the `fee_cents`, decrements the lot's
    `available_spaces` by one, stamps `issued_at` from the logical clock, and sets the pass to
    `ACTIVE`."

    Design: Difficulty/boundary_precision_check/lot_full_zero_space_boundary
    """
    beach, lot = setup_lot(api, total_spaces=1, daily_rate_cents=1000)
    payload = create_parking_pass_payload(lot["id"], "P1", "CAR", "DAILY")
    data = validate_success(api.create_parking_pass(payload, CLERK), 201)
    assert data["status"] == "ACTIVE", f"first pass at available=1 must be ACTIVE, got {data['status']}"


def test_second_pass_at_zero_spaces_is_lot_full(api):
    """PRD §3.7: "A pass may be issued only when the lot has at least one available space,
    otherwise it is rejected with `ERR_LOT_FULL` (409)."

    Design: Difficulty/boundary_precision_check/lot_full_zero_space_boundary
    """
    beach, lot = setup_lot(api, total_spaces=1, daily_rate_cents=1000)
    new_parking_pass(api, lot["id"], plate="P1")  # consumes the only space
    payload = create_parking_pass_payload(lot["id"], "P2", "CAR", "DAILY")
    resp = api.create_parking_pass(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_LOT_FULL.value)


# --- Compensating invariant: available spaces conserved ----------------------

def test_issuing_pass_decrements_available_spaces(api):
    """PRD §3.7: "Its `available_spaces` is a derived count, always equal to `total_spaces`
    minus the number of passes on the lot that are currently `ACTIVE`, and it starts equal to
    `total_spaces`."

    Design: Difficulty/compensating_invariant/parking_spaces_conserved_issue_then_revoke
    """
    beach, lot = setup_lot(api, total_spaces=10, daily_rate_cents=1000)
    new_parking_pass(api, lot["id"], plate="P1")
    lot_after = validate_success(api.get_parking_lot(lot["id"], CLERK), 200)
    assert lot_after["available_spaces"] == 9, f"issue must drop available to 9, got {lot_after['available_spaces']}"


def test_revoking_pass_restores_available_spaces(api):
    """PRD §3.7: "Revocation is a compensating action: it increments the lot's
    `available_spaces` back up by one."

    Design: Difficulty/compensating_invariant/parking_spaces_conserved_issue_then_revoke
    """
    beach, lot = setup_lot(api, total_spaces=10, daily_rate_cents=1000)
    pass_ = new_parking_pass(api, lot["id"], plate="P1")
    validate_success(api.revoke_parking_pass(pass_["id"], {}, CLERK), 200)
    lot_after = validate_success(api.get_parking_lot(lot["id"], CLERK), 200)
    assert lot_after["available_spaces"] == 10, f"revoke must restore available to 10, got {lot_after['available_spaces']}"


# --- Corner fee cases --------------------------------------------------------

def test_daily_weekday_car_nonresident_base_fee(api):
    """PRD §3.7: "First the day type is derived from the logical-clock date: it is a weekend if
    that date falls on Saturday or Sunday, and otherwise a weekday."
    PRD §3.7: "For a `DAILY` pass, start from the lot's `daily_rate_cents` multiplied by the
    day-type factor — 1.5 on a weekend, 1.0 on a weekday"

    Design: Corner/calculations/corner_parking_fee_daily_weekday_car_nonresident_base
    """
    beach, lot = setup_lot(api, total_spaces=50, daily_rate_cents=1000, clock="2026-07-15T10:00:00Z")
    payload = create_parking_pass_payload(lot["id"], "P1", "CAR", "DAILY", is_resident=False)
    data = validate_success(api.create_parking_pass(payload, CLERK), 201)
    assert data["fee_cents"] == 1000, f"weekday CAR non-resident base must be 1000, got {data['fee_cents']}"


def test_season_nonresident_car_flat_fee(api):
    """PRD §3.7: "For a `SEASON` pass, the base is 15000 cents when `is_resident` is true and
    30000 cents when it is false, plus an additional 5000 cents when the `vehicle_type` is
    `OVERSIZED`; the result is already in whole cents."

    Design: Corner/calculations/corner_parking_fee_season_nonresident_car_flat
    """
    beach, lot = setup_lot(api, total_spaces=50, daily_rate_cents=1200, clock="2026-07-18T10:00:00Z")
    payload = create_parking_pass_payload(lot["id"], "P1", "CAR", "SEASON", is_resident=False)
    data = validate_success(api.create_parking_pass(payload, CLERK), 201)
    assert data["fee_cents"] == 30000, f"SEASON non-resident CAR must be flat 30000, got {data['fee_cents']}"
