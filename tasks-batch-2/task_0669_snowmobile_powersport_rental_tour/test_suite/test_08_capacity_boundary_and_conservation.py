"""Capacity boundary at confirm, and compensating-invariant conservation of the
member deposit hold and the departure rider_count across confirm-then-cancel.
Covers difficulty rules boundary_precision_check (departure-full) and
compensating_invariant."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    create_trail, create_unit, create_departure,
    register_signed_member, create_reservation, create_and_confirm_reservation,
    current_departure_version,
    read_reservation, read_departure, read_member,
    make_member_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]


# ===================================================================
# Rule boundary_precision_check (departure-full capacity)
# ===================================================================

def test_confirm_rejected_when_rider_count_at_effective_capacity(api):
    """PRD §3.6: "The capacity gate at confirmation requires that the departure's
    `rider_count` be strictly less than its effective capacity — the smaller of
    `capacity_riders` and the trail's `max_riders` — before another rider may be added;
    a departure already at its effective cap rejects the confirm with `ERR_DEPARTURE_FULL`."

    Design: Difficulty/boundary_precision_check/departure_full_capacity_boundary_on_confirm
    """
    trail = create_trail(name="Cap", required_class="TRAIL", max_riders=5)
    units = [create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000,
                         tank_capacity_liters=30) for _ in range(3)]
    dep = create_departure(trail["id"], starts_at="2026-12-30T09:00:00Z",
                           ends_at="2026-12-30T12:00:00Z", required_guide_class="TRAIL", capacity_riders=2)
    # Fill effective capacity (2) with two confirmed riders.
    for u in units[:2]:
        m = register_signed_member()
        create_and_confirm_reservation(m, dep["id"], u["id"])
    assert read_departure(dep["id"])["rider_count"] == 2
    # Third confirm: 2 < 2 is false -> ERR_DEPARTURE_FULL.
    m3 = register_signed_member()
    res3 = create_reservation(m3, dep["id"], units[2]["id"])
    dep_ver = current_departure_version(dep["id"])
    resp = api.confirm_reservation(res3["id"], {"expected_tour_departure_version": dep_ver},
                                   make_member_headers(m3["id"]))
    validate_error(resp, "ERR_DEPARTURE_FULL", expected_status=409)
    assert read_departure(dep["id"])["rider_count"] == 2


def test_confirm_accepted_one_below_effective_capacity(api):
    """PRD §3.6: "The capacity gate at confirmation requires that the departure's
    `rider_count` be strictly less than its effective capacity — the smaller of
    `capacity_riders` and the trail's `max_riders` — before another rider may be added;
    a departure already at its effective cap rejects the confirm with `ERR_DEPARTURE_FULL`."

    Design: Difficulty/boundary_precision_check/departure_full_capacity_boundary_on_confirm
    """
    trail = create_trail(name="Cap2", required_class="TRAIL", max_riders=5)
    u1 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    u2 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2026-12-30T09:00:00Z",
                           ends_at="2026-12-30T12:00:00Z", required_guide_class="TRAIL", capacity_riders=2)
    m1 = register_signed_member()
    create_and_confirm_reservation(m1, dep["id"], u1["id"])  # rider_count 1, below cap 2
    assert read_departure(dep["id"])["rider_count"] == 1
    m2 = register_signed_member()
    confirmed = create_and_confirm_reservation(m2, dep["id"], u2["id"])  # 1 < 2 -> ok
    assert confirmed["reservation_status"] == "CONFIRMED"
    assert read_departure(dep["id"])["rider_count"] == 2


# ===================================================================
# Rule compensating_invariant
# ===================================================================

def test_member_deposit_hold_conserved_confirm_then_cancel(api):
    """PRD §3.4: "The member's `deposit_hold_cents` is at all times the sum of the active
    security-deposit holds across that member's reservations currently in the `HELD`
    billing state, recomputed every time a hold is placed or released."
    PRD §3.9: "cancelling a confirmed reservation ... moves its billing state from `HELD`
    to `REFUNDED` with the full `deposit_hold_cents` refunded, and recomputes the
    member's total hold."

    Design: Difficulty/compensating_invariant/deposit_hold_conserved_on_confirm_then_cancel
    """
    trail = create_trail(name="DepInv", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-01-12T09:00:00Z",
                           ends_at="2027-01-12T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_signed_member()
    assert read_member(member["id"])["deposit_hold_cents"] == 0  # before
    res = create_and_confirm_reservation(member, dep["id"], unit["id"], expected_version=dep["version"])
    assert read_member(member["id"])["deposit_hold_cents"] == 25000  # held
    validate_success(api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert read_member(member["id"])["deposit_hold_cents"] == 0  # restored, zero drift
    res_after = read_reservation(res["id"])
    assert res_after["settlement_status"] == "REFUNDED"
    from test_helpers import read_unit
    assert read_unit(unit["id"])["status"] == "AVAILABLE"


def test_departure_rider_count_conserved_confirm_then_cancel(api):
    """PRD §3.6: "The departure's `rider_count` itself is the count of that departure's
    reservations in `CONFIRMED`, `CHECKED_OUT`, or `RETURNED`; it is incremented when a
    reservation confirms and decremented when a confirmed reservation cancels or is
    marked a no-show."

    Design: Difficulty/compensating_invariant/departure_rider_count_conserved_on_confirm_then_cancel
    """
    trail = create_trail(name="RCInv", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-01-14T09:00:00Z",
                           ends_at="2027-01-14T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    assert read_departure(dep["id"])["rider_count"] == 0  # before
    member = register_signed_member()
    res = create_and_confirm_reservation(member, dep["id"], unit["id"], expected_version=dep["version"])
    assert read_departure(dep["id"])["rider_count"] == 1  # incremented
    validate_success(api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert read_departure(dep["id"])["rider_count"] == 0  # net zero drift
    assert read_reservation(res["id"])["reservation_status"] == "CANCELLED"


# ===================================================================
# Second tests per instance (≥2 coverage)
# ===================================================================

def test_member_hold_sums_two_reservations_then_drops_on_one_cancel(api):
    """PRD §3.4: "The member's `deposit_hold_cents` is at all times the sum of the active
    security-deposit holds across that member's reservations currently in the `HELD`
    billing state, recomputed every time a hold is placed or released."

    Design: Difficulty/compensating_invariant/deposit_hold_conserved_on_confirm_then_cancel
    """
    trail = create_trail(name="DepInv2", required_class="TRAIL", max_riders=10)
    u1 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    u2 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=10000, tank_capacity_liters=30)
    d1 = create_departure(trail["id"], starts_at="2027-01-12T09:00:00Z",
                          ends_at="2027-01-12T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d2 = create_departure(trail["id"], starts_at="2027-01-13T09:00:00Z",
                          ends_at="2027-01-13T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    member = register_signed_member()
    res1 = create_and_confirm_reservation(member, d1["id"], u1["id"], expected_version=d1["version"])
    create_and_confirm_reservation(member, d2["id"], u2["id"], expected_version=d2["version"])
    assert read_member(member["id"])["deposit_hold_cents"] == 35000  # 25000 + 10000 both HELD
    validate_success(api.cancel_reservation(res1["id"], make_member_headers(member["id"])), 200)
    assert read_member(member["id"])["deposit_hold_cents"] == 10000  # only res2 remains HELD


def test_rider_count_two_then_one_after_single_cancel(api):
    """PRD §3.6: "The departure's `rider_count` itself is the count of that departure's
    reservations in `CONFIRMED`, `CHECKED_OUT`, or `RETURNED`; it is incremented when a
    reservation confirms and decremented when a confirmed reservation cancels or is
    marked a no-show."

    Design: Difficulty/compensating_invariant/departure_rider_count_conserved_on_confirm_then_cancel
    """
    trail = create_trail(name="RCInv2", required_class="TRAIL", max_riders=10)
    u1 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    u2 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2027-01-14T09:00:00Z",
                           ends_at="2027-01-14T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    m1 = register_signed_member()
    m2 = register_signed_member()
    res1 = create_and_confirm_reservation(m1, dep["id"], u1["id"])
    create_and_confirm_reservation(m2, dep["id"], u2["id"])
    assert read_departure(dep["id"])["rider_count"] == 2
    validate_success(api.cancel_reservation(res1["id"], make_member_headers(m1["id"])), 200)
    assert read_departure(dep["id"])["rider_count"] == 1  # decremented by exactly one
