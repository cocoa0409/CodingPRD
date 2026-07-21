"""Cage boarding: dual-variant cost, cleaning-buffer conflict, check-in capacity."""
from test_helpers import (
    validate_success, validate_error,
    new_customer, new_boarding_cage, new_reservation,
    make_customer_headers, TEST_USERS,
)

SM = TEST_USERS["store_manager_headers"]
STAFF = TEST_USERS["aviary_staff_headers"]


# ── dual_variant_calc: boarding provisional vs final cost ────────────────────

def test_boarding_provisional_cost_at_reservation(api):
    """PRD 3.5: "The provisional boarding cost is computed at reservation as the cage's
    nightly_rate_cents multiplied by the number of nights in the planned window, where
    the number of nights is the difference between planned_check_out and planned_check_in
    divided by one day (86,400 seconds) and rounded up to the next whole night, with any
    partial day counting as a full night and a minimum of one night."

    Design: Difficulty/dual_variant_calc/boarding_provisional_vs_final_cost
    """
    cust = new_customer(wallet_cents=30000)
    cage = new_boarding_cage(capacity=2, nightly_rate_cents=5000)
    validate_success(api.set_clock("2026-07-01T12:00:00Z", SM), 200)
    res = new_reservation(cust["id"], cage["id"],
                          "2026-07-02T00:00:00Z", "2026-07-05T00:00:00Z")
    assert res["provisional_cost_cents"] == 15000  # 3 planned nights * 5000


def test_boarding_final_cost_and_wallet_at_checkout(api):
    """PRD 3.5: "the final cost is computed as the cage's nightly_rate_cents multiplied
    by the actual number of nights (the same night-counting rule applied between
    planned_check_in and actual_check_out) plus a late fee of 2,000 cents when the
    actual_check_out is later than the planned_check_out, and no late fee otherwise.
    That final_cost_cents is debited from the customer's wallet_credit_cents, subject to
    the floor-zero wallet rule (ERR_INSUFFICIENT_WALLET)."

    Design: Difficulty/dual_variant_calc/boarding_provisional_vs_final_cost
    """
    cust = new_customer(wallet_cents=30000)
    cage = new_boarding_cage(capacity=2, nightly_rate_cents=5000)
    validate_success(api.set_clock("2026-07-01T12:00:00Z", SM), 200)
    res = new_reservation(cust["id"], cage["id"],
                          "2026-07-02T00:00:00Z", "2026-07-05T00:00:00Z")
    validate_success(api.set_clock("2026-07-02T00:00:00Z", SM), 200)
    validate_success(api.check_in(res["id"], STAFF), 200)
    validate_success(api.set_clock("2026-07-06T09:00:00Z", SM), 200)
    out = validate_success(api.check_out(res["id"], STAFF), 200)
    # actual window 07-02T00:00 -> 07-06T09:00 = 4d9h -> 5 nights; 5*5000 + 2000 late = 27000
    assert out["final_cost_cents"] == 27000
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["wallet_credit_cents"] == 3000  # 30000 - 27000


# ── resource_temporal_overlap: cage cleaning buffer ──────────────────────────

def test_cage_reservation_within_cleaning_buffer_rejected(api):
    """PRD 3.5: "At reservation, the system rejects any window that overlaps another
    non-cancelled reservation on the same cage, where overlap includes a 12-hour cleaning
    buffer applied after a prior reservation's planned_check_out; a conflict is rejected
    with ERR_CAGE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/cage_within_cleaning_buffer_rejected
    """
    cust = new_customer()
    cage = new_boarding_cage(capacity=2, nightly_rate_cents=3000)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    new_reservation(cust["id"], cage["id"], "2026-07-03T00:00:00Z", "2026-07-05T00:00:00Z")
    # R2 starts only 6h after R1's checkout -> inside the 12h buffer.
    res = api.create_reservation(
        {"customer_id": cust["id"], "cage_id": cage["id"],
         "planned_check_in": "2026-07-05T06:00:00Z", "planned_check_out": "2026-07-07T00:00:00Z"},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_CAGE_TIME_CONFLICT", expected_status=409)


def test_cage_buffer_conflict_despite_available_capacity(api):
    """PRD 3.5: "At reservation, the system rejects any window that overlaps another
    non-cancelled reservation on the same cage, where overlap includes a 12-hour cleaning
    buffer applied after a prior reservation's planned_check_out; a conflict is rejected
    with ERR_CAGE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/cage_within_cleaning_buffer_rejected
    """
    cust = new_customer()
    # capacity 2: proves the rejection is a buffer conflict, not a capacity conflict.
    cage = new_boarding_cage(capacity=2, nightly_rate_cents=3000)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    new_reservation(cust["id"], cage["id"], "2026-07-03T00:00:00Z", "2026-07-05T00:00:00Z")
    res = api.create_reservation(
        {"customer_id": cust["id"], "cage_id": cage["id"],
         "planned_check_in": "2026-07-05T06:00:00Z", "planned_check_out": "2026-07-07T00:00:00Z"},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_CAGE_TIME_CONFLICT", expected_status=409)


# ── cross_entity_state_dependency: boarding check-in vs cage capacity ─────────

def test_boarding_checkin_rejected_at_capacity(api):
    """PRD 3.5: "Checking in a reservation moves it from RESERVED to CHECKED_IN. It
    requires the current clock to be at or after planned_check_in, and requires the target
    cage to not be OUT_OF_SERVICE and to have current_occupancy strictly below capacity,
    else ERR_NO_BOARDING_CAPACITY."

    Design: Difficulty/cross_entity_state_dependency/boarding_checkin_depends_on_cage_capacity
    """
    cust = new_customer()
    cage = new_boarding_cage(capacity=1, nightly_rate_cents=3000)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    r1 = new_reservation(cust["id"], cage["id"], "2026-07-03T00:00:00Z", "2026-07-05T00:00:00Z")
    r2 = new_reservation(cust["id"], cage["id"], "2026-07-06T00:00:00Z", "2026-07-08T00:00:00Z")
    validate_success(api.set_clock("2026-07-03T00:00:00Z", SM), 200)
    validate_success(api.check_in(r1["id"], STAFF), 200)  # cage now OCCUPIED
    validate_success(api.set_clock("2026-07-06T00:00:00Z", SM), 200)
    res = api.check_in(r2["id"], STAFF)
    validate_error(res, "ERR_NO_BOARDING_CAPACITY", expected_status=409)


def test_boarding_checkin_capacity_block_leaves_state_unchanged(api):
    """PRD 3.5: "requires the target cage to not be OUT_OF_SERVICE and to have
    current_occupancy strictly below capacity, else ERR_NO_BOARDING_CAPACITY."

    Design: Difficulty/cross_entity_state_dependency/boarding_checkin_depends_on_cage_capacity
    """
    cust = new_customer()
    cage = new_boarding_cage(capacity=1, nightly_rate_cents=3000)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    r1 = new_reservation(cust["id"], cage["id"], "2026-07-03T00:00:00Z", "2026-07-05T00:00:00Z")
    r2 = new_reservation(cust["id"], cage["id"], "2026-07-06T00:00:00Z", "2026-07-08T00:00:00Z")
    validate_success(api.set_clock("2026-07-03T00:00:00Z", SM), 200)
    validate_success(api.check_in(r1["id"], STAFF), 200)
    validate_success(api.set_clock("2026-07-06T00:00:00Z", SM), 200)
    validate_error(api.check_in(r2["id"], STAFF), "ERR_NO_BOARDING_CAPACITY", expected_status=409)
    r2_after = validate_success(api.get_reservation(r2["id"], SM), 200)
    assert r2_after["status"] == "RESERVED"
    cage_after = validate_success(api.get_cage(cage["id"], SM), 200)
    assert cage_after["current_occupancy"] == 1


# ── corner: cancel an already-cancelled reservation ──────────────────────────

def test_cancel_already_cancelled_reservation_invalid_state(api):
    """PRD 2.1: "(6) state-machine legality of the requested transition (ERR_INVALID_STATE
    and its domain-specific variants, HTTP 409)"

    Design: Corner/state_machines/cancel_already_cancelled_reservation_invalid_state
    """
    cust = new_customer()
    cage = new_boarding_cage(capacity=1, nightly_rate_cents=3000)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    res = new_reservation(cust["id"], cage["id"], "2026-07-03T00:00:00Z", "2026-07-05T00:00:00Z")
    validate_success(api.cancel_reservation(res["id"], make_customer_headers(cust["id"])), 200)
    again = api.cancel_reservation(res["id"], make_customer_headers(cust["id"]))
    validate_error(again, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_reservation(res["id"], SM), 200)
    assert after["status"] == "CANCELLED"
