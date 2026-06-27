"""Quantitative rules: day-pass pricing, rental settlement (return vs lost),
deposit conservation, route difficulty points, and the setter report.

Covers dual-variant rental settlement, the combinatorial day-pass price, the
deposit-conservation invariant, and corner instances on pricing edges, late-fee
cap, route points, strip, and the aggregation report.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_rental, assert_deposit_conservation,
    create_member, create_member_with_waiver, create_membership,
    create_facility, create_rental, create_route, check_in, set_clock,
    make_setter_headers, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]
SETTER = TEST_USERS["setter_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: rental return vs lost dual-variant settlement ────────────
def test_returned_vs_lost_rental_settle_differently(api):
    """PRD §3.7: "The raw fee is 800 cents per day late, and the late_fee_cents is
    that raw fee capped at deposit_cents — it never exceeds the deposit. The
    refund_cents is deposit_cents minus late_fee_cents, and that refund is
    credited to the member's wallet_credit_cents."
    PRD §3.7: "Reporting an out rental lost forfeits the whole deposit:
    late_fee_cents is set to the full deposit_cents regardless of timing, and
    refund_cents is 0 with no wallet credit."

    Design: Difficulty/dual_variant_calc/rental_settlement_returned_vs_lost_variant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    rent_a = create_rental(member["id"], item_kind="HARNESS", deposit_cents=5000)
    rent_b = create_rental(member["id"], item_kind="SHOES", deposit_cents=5000)
    # due_at = 2026-06-02T00:00:00Z; return at 2026-06-04T02:00:00Z is 50h late
    # → days_late = ceil(50/24) = 3 → raw 2400, capped under deposit → fee 2400.
    set_clock("2026-06-04T02:00:00Z")
    returned = validate_success(api.return_rental(
        rent_a["id"], {"expected_rental_version": rent_a["version"]}, FD), 200)
    assert returned["late_fee_cents"] == 2400
    assert returned["refund_cents"] == 2600
    lost = validate_success(api.report_lost_rental(
        rent_b["id"], {"expected_rental_version": rent_b["version"]}, FD), 200)
    assert lost["late_fee_cents"] == 5000, "lost forfeits the full deposit"
    assert lost["refund_cents"] == 0
    member_after = validate_success(api.get_member(member["id"], FD), 200)
    assert member_after["wallet_credit_cents"] == 2600, \
        "only the returned refund hits the wallet; lost credits nothing"


def test_lost_rental_credits_nothing_to_wallet(api):
    """PRD §3.7: "Reporting an out rental lost forfeits the whole deposit:
    late_fee_cents is set to the full deposit_cents regardless of timing, and
    refund_cents is 0 with no wallet credit."

    Design: Difficulty/dual_variant_calc/rental_settlement_returned_vs_lost_variant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    rental = create_rental(member["id"], item_kind="ROPE", deposit_cents=4200)
    lost = validate_success(api.report_lost_rental(
        rental["id"], {"expected_rental_version": rental["version"]}, FD), 200)
    assert lost["status"] == "LOST"
    assert lost["late_fee_cents"] == 4200
    assert lost["refund_cents"] == 0
    member_after = validate_success(api.get_member(member["id"], FD), 200)
    assert member_after["wallet_credit_cents"] == 0


# ─── Difficulty: day-pass price youth + gear nested floor ─────────────────
def test_day_pass_price_youth_with_gear_applies_floored_discount(api):
    """PRD §3.7: "Start with a subtotal equal to the base day-pass fee of 2500
    cents, plus an additional 1200 cents when the gear_bundle flag is set
    (bundling a harness and shoes), and nothing extra otherwise. If the member is
    a youth, a discount is taken: the youth discount is 20 percent of the
    subtotal, floored to a whole cent (truncated toward zero). The final
    price_cents is the subtotal minus that youth discount"

    Design: Difficulty/combinatorial_formula/day_pass_price_youth_gear_nested_floor_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver(
        date_of_birth="2010-06-01", minor_guardian_name="Pat Parent")
    facility = create_facility(name="Boulder Cave", floor_capacity=50)
    # subtotal = 2500 + 1200 = 3700; discount = floor(3700*0.20) = 740; price = 2960
    ci = check_in(member["id"], facility["id"], facility["version"],
                  entry_kind="DAY_PASS", gear_bundle=True)
    assert ci["price_cents"] == 2960
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 1


def test_day_pass_price_adult_with_gear_no_discount(api):
    """PRD §3.7: "for a non-youth member the discount is zero and the price equals
    the subtotal."

    Design: Difficulty/combinatorial_formula/day_pass_price_youth_gear_nested_floor_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver(date_of_birth="1985-01-01")
    facility = create_facility(name="Adult Cave", floor_capacity=50)
    # subtotal = 2500 + 1200 = 3700; adult → discount 0 → price 3700
    ci = check_in(member["id"], facility["id"], facility["version"],
                  entry_kind="DAY_PASS", gear_bundle=True)
    assert ci["price_cents"] == 3700


# ─── Difficulty: deposit conservation invariant ───────────────────────────
def test_rental_deposit_conserved_across_return(api):
    """PRD §2.7: "when a rental is settled, the original deposit_cents always
    splits exactly into a late fee plus a refund — the late fee and refund sum
    back to the deposit with nothing lost."
    PRD §3.7: "The refund_cents is deposit_cents minus late_fee_cents, and that
    refund is credited to the member's wallet_credit_cents."

    Design: Difficulty/compensating_invariant/rental_deposit_conservation_invariant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    rental = create_rental(member["id"], item_kind="ROPE", deposit_cents=5000)
    set_clock("2026-06-04T02:00:00Z")  # 50h late → fee 2400, refund 2600
    returned = validate_success(api.return_rental(
        rental["id"], {"expected_rental_version": rental["version"]}, FD), 200)
    assert returned["late_fee_cents"] == 2400
    assert returned["refund_cents"] == 2600
    assert_deposit_conservation(returned)


def test_deposit_conserved_on_lost_branch(api):
    """PRD §2.7: "a deposit always splits cleanly into a late fee plus a refund."
    PRD §3.7: "Reporting an out rental lost forfeits the whole deposit:
    late_fee_cents is set to the full deposit_cents regardless of timing, and
    refund_cents is 0 with no wallet credit."

    Design: Difficulty/compensating_invariant/rental_deposit_conservation_invariant
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    rental = create_rental(member["id"], item_kind="HARNESS", deposit_cents=3300)
    lost = validate_success(api.report_lost_rental(
        rental["id"], {"expected_rental_version": rental["version"]}, FD), 200)
    assert_deposit_conservation(lost)  # 3300 = 3300 + 0


# ─── Corner: day-pass adult base only ─────────────────────────────────────
def test_day_pass_price_adult_no_gear_base_only(api):
    """PRD §3.7: "Start with a subtotal equal to the base day-pass fee of 2500
    cents, plus an additional 1200 cents when the gear_bundle flag is set ... and
    nothing extra otherwise. ... for a non-youth member the discount is zero and
    the price equals the subtotal."

    Design: Corner/calculations/day_pass_price_adult_no_gear_base_only
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver(date_of_birth="1985-01-01")
    facility = create_facility(name="Adult Wall", floor_capacity=10)
    ci = check_in(member["id"], facility["id"], facility["version"], entry_kind="DAY_PASS")
    assert ci["price_cents"] == 2500


# ─── Corner: membership check-in is free ──────────────────────────────────
def test_membership_checkin_price_is_zero(api):
    """PRD §3.6: "computes price_cents (0 for a membership entry, or the day-pass
    price for a day-pass entry)"
    PRD §3.7: "A membership entry has a price_cents of 0 and never invokes this
    calculation."

    Design: Corner/calculations/membership_checkin_price_is_zero
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver(date_of_birth="1985-01-01")
    create_membership(member["id"], plan_tier="BASIC")
    facility = create_facility(name="Member Wall", floor_capacity=10)
    ci = check_in(member["id"], facility["id"], facility["version"], entry_kind="MEMBERSHIP")
    assert ci["price_cents"] == 0


# ─── Corner: rental on-time and capped late fee ───────────────────────────
def test_on_time_return_zero_fee_full_refund(api):
    """PRD §3.7: "The hours late are the hours between due_at and the current
    return clock, never less than zero (a rental returned by its due date is not
    late). The whole days late are those hours divided by 24 and rounded up to the
    next whole day (so 0 hours is 0 days late, ...). The raw fee is 800 cents per
    day late, and the late_fee_cents is that raw fee capped at deposit_cents"

    Design: Corner/calculations/rental_on_time_return_zero_late_fee_full_refund
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    rental = create_rental(member["id"], item_kind="SHOES", deposit_cents=5000)
    set_clock("2026-06-02T00:00:00Z")  # exactly due_at → 0h late
    returned = validate_success(api.return_rental(
        rental["id"], {"expected_rental_version": rental["version"]}, FD), 200)
    assert returned["late_fee_cents"] == 0
    assert returned["refund_cents"] == 5000
    member_after = validate_success(api.get_member(member["id"], FD), 200)
    assert member_after["wallet_credit_cents"] == 5000


def test_late_fee_capped_at_deposit(api):
    """PRD §3.7: "The raw fee is 800 cents per day late, and the late_fee_cents is
    that raw fee capped at deposit_cents — it never exceeds the deposit. The
    refund_cents is deposit_cents minus late_fee_cents"

    Design: Corner/calculations/rental_late_fee_capped_at_deposit
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    rental = create_rental(member["id"], item_kind="ROPE", deposit_cents=5000)
    # due 2026-06-02; return 2026-06-10T08:00:00Z = 200h late → days 9 → raw 7200,
    # capped at 5000.
    set_clock("2026-06-10T08:00:00Z")
    returned = validate_success(api.return_rental(
        rental["id"], {"expected_rental_version": rental["version"]}, FD), 200)
    assert returned["late_fee_cents"] == 5000
    assert returned["refund_cents"] == 0


# ─── Corner: route difficulty points + strip ──────────────────────────────
def test_route_difficulty_points_computed_on_create(api):
    """PRD §3.7: "Each route's difficulty_points is computed at creation as the
    base points times the style multiplier, rounded half up to a whole integer.
    The base points are 100 plus the grade times 50. The style multiplier is 1.0
    for SLAB, 1.25 for OVERHANG, and 1.50 for ROOF."

    Design: Corner/entities/route_difficulty_points_computed_on_create
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Route Wall", floor_capacity=20)
    route = create_route(facility["id"], grade=5, style="OVERHANG")
    # round_half_up((100 + 250) * 1.25) = round_half_up(437.5) = 438
    assert route["difficulty_points"] == 438
    assert route["status"] == "OPEN"


def test_strip_open_route_retains_points(api):
    """PRD §3.5: "A setter may strip an open route, retiring it: stripping moves
    status from OPEN to STRIPPED (only valid from OPEN, else ERR_INVALID_STATE)
    and increments the version. ... A stripped route stops counting toward
    open-route listings but keeps its difficulty_points so that historical setter
    aggregation remains accurate."

    Design: Corner/state_machines/strip_open_route_succeeds_and_retains_points
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Strip Wall", floor_capacity=10)
    route = create_route(facility["id"], grade=3, style="ROOF")
    # round_half_up((100 + 150) * 1.50) = round_half_up(375.0) = 375
    assert route["difficulty_points"] == 375
    stripped = validate_success(api.strip_route(
        route["id"], {"expected_route_version": route["version"]},
        make_setter_headers("setter-1")), 200)
    assert stripped["status"] == "STRIPPED"
    assert stripped["difficulty_points"] == 375


# ─── Corner: setter report aggregation ────────────────────────────────────
def test_setter_report_sums_open_and_stripped_routes(api):
    """PRD §3.7: "The setter report then sums the difficulty_points of every route
    on the requested facility that was set by the requested setter_user_id and
    whose set_on instant falls in the requested month ... including routes whose
    status is OPEN as well as those that have been STRIPPED. The report returns
    that integer total_points together with a route_count of the routes summed"

    Design: Corner/calculations/setter_monthly_points_aggregates_open_and_stripped
    """
    set_clock("2026-06-05T00:00:00Z")
    facility = create_facility(name="Agg Wall", floor_capacity=10)
    create_route(facility["id"], grade=5, style="OVERHANG")  # 438
    r2 = create_route(facility["id"], grade=3, style="ROOF")  # 375
    create_route(facility["id"], grade=0, style="SLAB")  # round_half_up(100*1.0)=100
    validate_success(api.strip_route(
        r2["id"], {"expected_route_version": r2["version"]},
        make_setter_headers("setter-1")), 200)
    report = validate_success(api.setter_report(
        facility["id"], make_setter_headers("setter-1"),
        params={"setter_user_id": "setter-1", "month": "2026-06"}), 200)
    assert report["total_points"] == 913  # 438 + 375 + 100
    assert report["route_count"] == 3


def test_setter_report_excludes_other_setters(api):
    """PRD §3.7: "sums the difficulty_points of every route on the requested
    facility that was set by the requested setter_user_id and whose set_on instant
    falls in the requested month"

    Design: Corner/endpoints/facility_setter_report_filters_other_setters
    """
    set_clock("2026-06-05T00:00:00Z")
    facility = create_facility(name="Filter Wall", floor_capacity=10)
    create_route(facility["id"], grade=5, style="OVERHANG", setter_user_id="setter-1")
    report = validate_success(api.setter_report(
        facility["id"], make_setter_headers("setter-2"),
        params={"setter_user_id": "setter-2", "month": "2026-06"}), 200)
    assert report["total_points"] == 0
    assert report["route_count"] == 0


def test_list_facility_routes_filtered_by_status(api):
    """PRD §3.5: "A stripped route stops counting toward open-route listings but
    keeps its difficulty_points so that historical setter aggregation remains
    accurate."

    Design: Corner/endpoints/list_facility_routes_filtered_by_status
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="List Wall", floor_capacity=10)
    create_route(facility["id"], grade=2, style="SLAB")  # stays OPEN
    r2 = create_route(facility["id"], grade=4, style="ROOF")
    validate_success(api.strip_route(
        r2["id"], {"expected_route_version": r2["version"]},
        make_setter_headers("setter-1")), 200)
    res = api.list_facility_routes(
        facility["id"], make_setter_headers("setter-1"), params={"status": "OPEN"})
    data = validate_success(res, 200)
    open_routes = [r for r in data if r["status"] == "OPEN"]
    assert len(open_routes) == 1, "exactly one OPEN route after stripping the other"
