"""Pricing, group-discount, insurance premium, and milestone-split calculations.

Covers difficulty rules: dual_variant_calc (milestone provisional vs finalized),
combinatorial_formula (group discount round-then-multiply, deposit round + balance
remainder), boundary_precision_check (milestone settled at exact due); plus the
corresponding corner calculation/computed-field claims.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_agency_payload, set_clock_payload, create_customer_payload,
    create_supplier_payload, create_tour_package_payload, create_booking_payload,
    add_traveler_payload, create_component_payload, create_insurance_payload,
    create_payment_payload, reserve_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_agency, create_customer, create_supplier, create_published_package,
    open_draft_booking, add_travelers, attach_insurance, request_component,
    setup_draft_booking_with_travelers, setup_reserved_booking,
    setup_reserved_deposit_settled, get_milestone_id, get_booking, _booking_version,
    pay_milestone, AGENT, ADMIN,
)


# ─── dual_variant_calc: provisional vs finalized quote ───────────────────
def test_reserve_freezes_grand_total_with_insurance_into_milestones(api):
    """PRD §3.8: "The deposit's `amount_due_cents` is the `grand_total_cents`
    multiplied by the package's `deposit_pct`, divided by one hundred, rounded
    half-up to whole cents."
    PRD §3.6: "On reserve, the price is frozen — this is the **finalized quote**:
    `subtotal_cents`, `insurance_premium_cents`, and `grand_total_cents` are computed
    one final time from the current travelers and active policies and then fixed".
    PRD §3.4: "a `PREMIUM` policy costs 4000 cents per traveler".

    1 traveler base 100000 (no discount) => subtotal 100000; PREMIUM insurance
    1*4000 => grand frozen at 104000; DEPOSIT = round_half_up(104000*20/100)=20800,
    BALANCE = 104000-20800 = 83200.

    Design: Difficulty/dual_variant_calc/dvc_milestone_provisional_vs_finalized_quote
    """
    agency = create_agency(clock="2026-01-01T00:00:00.000Z")
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000,
                                       deposit_pct=20)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"],
                                 departure_date="2026-06-01T00:00:00.000Z")
    version = add_travelers(booking["id"], 1, booking["version"])

    # Provisional grand total before insurance: 100000.
    provisional = get_booking(booking["id"])
    assert provisional["grand_total_cents"] == 100000

    attach_insurance(booking["id"], "PREMIUM")
    request_component(booking["id"], supplier["id"], kind="FLIGHT",
                      starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T12:00:00.000Z")
    version = _booking_version(booking["id"])
    reserved = validate_success(api.reserve_booking(booking["id"], reserve_payload(version), AGENT), 200)
    assert reserved["grand_total_cents"] == 104000

    deposit = validate_success(api.get_milestone(get_milestone_id(booking["id"], "DEPOSIT"), AGENT), 200)
    balance = validate_success(api.get_milestone(get_milestone_id(booking["id"], "BALANCE"), AGENT), 200)
    assert deposit["amount_due_cents"] == 20800
    assert balance["amount_due_cents"] == 83200


def test_provisional_quote_tracks_insurance_attach_live(api):
    """PRD §3.4: "every traveler add and every insurance attach re-derives
    `subtotal_cents`, `insurance_premium_cents`, and `grand_total_cents` against
    the live roster of travelers and policies, and no payment milestones exist yet."
    PRD §3.4: "a `PREMIUM` policy costs 4000 cents per traveler".

    2 travelers base 100000 => subtotal 200000; PREMIUM 2*4000 => insurance 8000;
    grand = 208000 (provisional, while DRAFT).

    Design: Difficulty/dual_variant_calc/dvc_milestone_provisional_vs_finalized_quote
    """
    ctx = setup_draft_booking_with_travelers(
        num_travelers=2, clock=None,
        pkg_overrides={"base_price_per_person_cents": 100000, "min_group_size_for_discount": 5})
    attach_insurance(ctx["booking_id"], "PREMIUM")
    booking = get_booking(ctx["booking_id"])
    assert booking["insurance_premium_cents"] == 8000
    assert booking["grand_total_cents"] == 208000


# ─── combinatorial_formula: group discount round-then-multiply ───────────
def test_group_discount_round_per_person_then_multiply(api):
    """PRD §3.3: "The per-person price is then computed in a pinned order that must
    not be rearranged: first take the base, multiply by one hundred minus the discount
    percentage, divide by one hundred, and round that per-person figure half-up to whole
    cents; only then multiply the rounded per-person price by n to obtain `subtotal_cents`."
    PRD §3.3: "if n is at least `min_group_size_for_discount` but fewer than 8, the
    discount is 5 percent".

    base 33333, 6 travelers (5% tier): per_person = round_half_up(33333*0.95)=31666,
    subtotal = 31666*6 = 189996 (round-then-multiply, not 189998).

    Design: Difficulty/combinatorial_formula/cf_group_discount_round_then_multiply
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=33333,
                                       min_group_size_for_discount=5)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    add_travelers(booking["id"], 6, booking["version"])
    result = get_booking(booking["id"])
    assert result["traveler_count"] == 6
    assert result["subtotal_cents"] == 189996
    assert result["grand_total_cents"] == 189996


def test_group_discount_round_then_multiply_falsifies_sum_then_round(api):
    """PRD §3.3: "Rounding happens once, on the per-person amount, before the multiply
    — never after."
    PRD §3.3: "if n is at least `min_group_size_for_discount` but fewer than 8, the
    discount is 5 percent".

    base 33333, 6 travelers => 189996; the sum-then-round variant (189998) is rejected.

    Design: Difficulty/combinatorial_formula/cf_group_discount_round_then_multiply
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=33333,
                                       min_group_size_for_discount=5)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    add_travelers(booking["id"], 6, booking["version"])
    result = get_booking(booking["id"])
    assert result["subtotal_cents"] == 189996
    assert result["subtotal_cents"] != 189998


# ─── combinatorial_formula: deposit round + balance remainder ────────────
def test_deposit_rounded_balance_exact_remainder(api):
    """PRD §3.8: "The deposit's `amount_due_cents` is the `grand_total_cents` multiplied
    by the package's `deposit_pct`, divided by one hundred, rounded half-up to whole cents.
    The balance's `amount_due_cents` is then the exact remainder — `grand_total_cents`
    minus the deposit's `amount_due_cents` — and is never independently rounded, so that
    the deposit and balance always sum back to the grand total with zero cent drift."

    grand 100002, deposit_pct 25 => DEPOSIT = round_half_up(25000.5)=25001,
    BALANCE = 100002-25001 = 75001, DEPOSIT+BALANCE == 100002.

    Design: Difficulty/combinatorial_formula/cf_milestone_deposit_round_then_balance_remainder
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100002, "deposit_pct": 25,
                       "min_group_size_for_discount": 5})
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    balance = validate_success(api.get_milestone(ctx["balance_ms_id"], AGENT), 200)
    assert deposit["amount_due_cents"] == 25001
    assert balance["amount_due_cents"] == 75001
    assert deposit["amount_due_cents"] + balance["amount_due_cents"] == 100002


def test_milestone_split_sums_to_grand_total(api):
    """PRD §3.8: "the deposit and balance always sum back to the grand total with zero
    cent drift."
    PRD §3.8: "The deposit's `amount_due_cents` is the `grand_total_cents` multiplied by
    the package's `deposit_pct`, divided by one hundred, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/cf_milestone_deposit_round_then_balance_remainder
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100002, "deposit_pct": 25,
                       "min_group_size_for_discount": 5})
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    balance = validate_success(api.get_milestone(ctx["balance_ms_id"], AGENT), 200)
    booking = get_booking(ctx["booking_id"])
    assert deposit["amount_due_cents"] + balance["amount_due_cents"] == booking["grand_total_cents"]


# ─── boundary_precision_check: milestone SETTLED at exact due ────────────
def test_milestone_settled_when_payment_meets_due(api):
    """PRD §3.8: "It is `SETTLED` exactly when its `settled_amount_cents` reaches or
    exceeds its `amount_due_cents` (a "meets-or-exceeds" test, not strictly greater)."
    PRD §3.8: "if the `DEPOSIT` milestone is `SETTLED`, it is `DEPOSIT_PAID`".

    Pay exactly 20000 against a DEPOSIT of 20000 => SETTLED, payment_status DEPOSIT_PAID.

    Design: Difficulty/boundary_precision_check/bpc_milestone_settled_at_exact_due
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    pay = validate_success(api.create_payment(
        create_payment_payload(ctx["booking_id"], ctx["deposit_ms_id"], 20000), AGENT), 201)
    assert pay["status"] == "APPLIED"
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    assert deposit["status"] == "SETTLED"
    assert deposit["settled_amount_cents"] == 20000
    booking = get_booking(ctx["booking_id"])
    assert booking["payment_status"] == "DEPOSIT_PAID"


def test_milestone_open_when_payment_below_due(api):
    """PRD §3.8: "It is `SETTLED` exactly when its `settled_amount_cents` reaches or
    exceeds its `amount_due_cents` (a "meets-or-exceeds" test, not strictly greater)."

    Paying 19999 against a 20000 DEPOSIT leaves it OPEN (below the due, not yet settled).

    Design: Difficulty/boundary_precision_check/bpc_milestone_settled_at_exact_due
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    validate_success(api.create_payment(
        create_payment_payload(ctx["booking_id"], ctx["deposit_ms_id"], 19999), AGENT), 201)
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    assert deposit["status"] == "OPEN"
    assert deposit["settled_amount_cents"] == 19999


# ─── Corner calculations ─────────────────────────────────────────────────
def test_basic_insurance_premium_non_refundable(api):
    """PRD §3.4: "a `BASIC` policy costs 1500 cents per traveler and a `PREMIUM` policy
    costs 4000 cents per traveler, with the premium being simply that per-traveler rate
    multiplied by the headcount in exact whole cents with no rounding."
    PRD §3.4: "`BASIC` policies are non-refundable, and `PREMIUM` policies are refundable."

    3 travelers, BASIC => premium 3*1500 = 4500, refundable false.

    Design: Corner/calculations/insurance_basic_premium_non_refundable
    """
    ctx = setup_draft_booking_with_travelers(
        num_travelers=3, clock=None,
        pkg_overrides={"base_price_per_person_cents": 100000})
    policy = validate_success(api.create_insurance_policy(
        create_insurance_payload(ctx["booking_id"], "BASIC"), AGENT), 201)
    assert policy["premium_cents"] == 4500
    assert policy["refundable"] is False


def test_group_discount_below_threshold_no_discount(api):
    """PRD §3.3: "if n is below the package's `min_group_size_for_discount`, the discount
    is 0 percent".

    4 travelers (< min_group_size 5), base 100000 => subtotal 100000*4 = 400000.

    Design: Corner/calculations/group_discount_below_threshold_no_discount
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=100000,
                                       min_group_size_for_discount=5)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    add_travelers(booking["id"], 4, booking["version"])
    result = get_booking(booking["id"])
    assert result["traveler_count"] == 4
    assert result["subtotal_cents"] == 400000
