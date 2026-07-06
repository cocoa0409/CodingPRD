"""Pricing and invoicing: dual-variant deposit/final divergence and combinatorial
per-seat formulas for shows, group bookings, and rentals.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    create_dome,
    create_open_show,
    create_active_membership,
    create_group_booking,
    create_rental_hall,
)

BOX_OFFICE = TEST_USERS["box_office_headers"]
GROUP_SALES = TEST_USERS["group_sales_headers"]
EVENTS = TEST_USERS["events_manager_headers"]


def test_group_booking_deposit_and_final_diverge(api):
    """PRD §3.5: "The **deposit** runs that grand total over the requested
    `student_count` and `chaperone_count`, takes 25% of it, and floors the result
    to whole cents; that figure is stored in `deposit_cents`."
    PRD §3.5: "At confirm time the system runs the very same grand-total arithmetic,
    but now over the actual head-counts, and sets `balance_cents` to that final grand
    total minus the already-collected `deposit_cents`. Because the estimate and the
    actuals can differ, the final figure is not simply four times the deposit — the
    forward-looking estimate and the actual-count final are independent computations
    on the same booking row."

    Estimate (20 students, 3 chaperones): per_seat=2500, free_chaperones=2,
    billable=1, student_seat=round(2500*0.70)=1750, students=20*1750=35000,
    chaperones=1*2000=2000, grand_total=37000, deposit=floor(37000*0.25)=9250.
    Final (25 students, 2 chaperones): free_chaperones=2, billable=0,
    student_seat=1750, students=25*1750=43750, grand_total=43750,
    balance=43750-9250=34500. 4*9250=37000 != 43750.

    Design: Difficulty/dual_variant_calc/group_invoice_deposit_vs_final_diverges
    """
    show = create_open_show(seated_capacity=60, base_price_cents=2000,
                            feature_surcharge_cents=500, title="Stars")
    gb = create_group_booking(show["id"], student_count=20, chaperone_count=3,
                              organization_name="PS 42")
    assert gb["deposit_cents"] == 9250, f"expected deposit 9250, got {gb['deposit_cents']}"

    validate_success(api.pay_group_deposit(gb["id"], GROUP_SALES))
    confirmed = validate_success(api.confirm_group_booking(
        gb["id"], {"actual_student_count": 25, "actual_chaperone_count": 2}, GROUP_SALES))

    assert confirmed["balance_cents"] == 34500, \
        f"expected balance 34500, got {confirmed['balance_cents']}"
    assert confirmed["deposit_cents"] * 4 != confirmed["balance_cents"] + confirmed["deposit_cents"], \
        "final invoice must diverge from 4x the deposit"


def test_rental_deposit_and_final_diverge(api):
    """PRD §3.7: "The **deposit** runs this grand total over the estimated
    `guest_count`, takes 25% of it, and floors to whole cents, storing the result
    in `deposit_cents`."
    PRD §3.7: "Because the actual guest count can differ from the estimate, the final
    total is independent of four times the deposit."

    Estimate (guest_count=15): tier1=15*500=7500, grand=50000+7500=57500,
    deposit=floor(57500*0.25)=14375.
    Final (actual_guest_count=30): tier1=20*500=10000, tier2=10*300=3000,
    guest_charge=13000, total=50000+13000=63000. 4*14375=57500 != 63000.

    Design: Difficulty/dual_variant_calc/rental_deposit_vs_final_diverges
    """
    hall = create_rental_hall(seated_capacity=80, name="Party Hall")
    rental = validate_success(api.create_rental(
        {"venue_id": hall["id"], "host_name": "Mia",
         "starts_at": "2026-05-02T14:00:00Z", "ends_at": "2026-05-02T17:00:00Z",
         "guest_count": 15, "base_rental_cents": 50000}, EVENTS), expected_status=201)
    assert rental["deposit_cents"] == 14375, \
        f"expected deposit 14375, got {rental['deposit_cents']}"

    validate_success(api.hold_rental(rental["id"], EVENTS))
    confirmed = validate_success(api.confirm_rental(
        rental["id"], {"actual_guest_count": 30}, EVENTS))

    assert confirmed["total_cents"] == 63000, \
        f"expected total 63000, got {confirmed['total_cents']}"
    assert confirmed["deposit_cents"] * 4 != confirmed["total_cents"], \
        "final total must diverge from 4x the deposit"


def test_family_show_pricing_rounds_per_seat_then_sums(api):
    """PRD §3.4: "A `FAMILY` card discounts 50% of the full per-seat total (base plus
    surcharge): take the per-seat price, multiply by 0.50, round half up to whole
    cents, then multiply by `party_size`."

    per_seat=2500, per_seat_disc=round(2500*0.50)=1250, party_size=3,
    member_discount_cents=3*1250=3750, gross=3*2500=7500, net=7500-3750=3750.

    Design: Difficulty/combinatorial_formula/show_pricing_per_seat_round_then_sum
    """
    fam = create_active_membership(tier="FAMILY", home_zip="90210", party_size=4,
                                   dues_cents=12000, primary_member_name="Fam")
    show = create_open_show(seated_capacity=60, base_price_cents=2000,
                            feature_surcharge_cents=500, title="Laser")
    booking = validate_success(api.create_show_booking(
        {"show_event_id": show["id"], "membership_id": fam["id"], "party_size": 3,
         "expected_show_version": show["version"]}, BOX_OFFICE), expected_status=201)

    assert booking["gross_price_cents"] == 7500, \
        f"expected gross 7500, got {booking['gross_price_cents']}"
    assert booking["member_discount_cents"] == 3750, \
        f"expected discount 3750, got {booking['member_discount_cents']}"
    assert booking["net_price_cents"] == 3750, \
        f"expected net 3750, got {booking['net_price_cents']}"


def test_rental_marginal_two_tier_guest_charge(api):
    """PRD §3.7: "the tier-one guests are the smaller of the guest count and 20, the
    tier-two guests are whatever remains above 20 (never below zero), and the guest
    charge is the tier-one count times 500 cents plus the tier-two count times 300
    cents. The grand total is the `base_rental_cents` plus that guest charge."
    PRD §3.7: "The **deposit** runs this grand total over the estimated `guest_count`,
    takes 25% of it, and floors to whole cents, storing the result in `deposit_cents`."

    guest_count=30: tier1=min(30,20)=20*500=10000, tier2=10*300=3000,
    guest_charge=13000, grand=50000+13000=63000, deposit=floor(63000*0.25)=15750.

    Design: Difficulty/combinatorial_formula/rental_marginal_tier_three_inputs
    """
    hall = create_rental_hall(seated_capacity=100, name="Hall C")
    rental = validate_success(api.create_rental(
        {"venue_id": hall["id"], "host_name": "Sam",
         "starts_at": "2026-06-01T12:00:00Z", "ends_at": "2026-06-01T15:00:00Z",
         "guest_count": 30, "base_rental_cents": 50000}, EVENTS), expected_status=201)

    assert rental["deposit_cents"] == 15750, \
        f"expected deposit 15750, got {rental['deposit_cents']}"
