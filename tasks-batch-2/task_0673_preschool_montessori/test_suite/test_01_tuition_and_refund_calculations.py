"""Tuition-net and refund-amount calculations — the dual-variant and combinatorial
pricing/refund engines (PRD §3.6, §3.8).

Each test translates exactly one design-index instance and cites the verbatim PRD
sentence that uniquely determines the asserted figure.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_tier_payload, accept_offer_payload, create_refund_request_payload,
    create_student_payload, create_application_payload,
    setup_enrolled_child, setup_withdrawn_with_payments,
    set_clock, create_tier, create_room_with_staff, create_student, enroll_child,
    application_offered, capture_deposit, capture_installment,
    make_parent_headers, TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# ─── dual_variant_calc / refund_forward_vs_chronological_diverge ───────────────

def test_refund_forward_method_earned_and_refund(api):
    """PRD §3.8: "The earned amount is the retained deposit plus that count of started
    months times the monthly figure; the month of withdrawal counts as fully earned, and
    no proration is performed (this method involves no division)."
    PRD §3.8: "the refund owed to the family — the request's refund_cents — is the
    enrollment's paid_to_date_cents minus the earned amount, but never less than zero."

    Design: Difficulty/dual_variant_calc/refund_forward_vs_chronological_diverge
    """
    room, tier, student, enr = setup_withdrawn_with_payments(
        deposit_cents=100_000, installment_cents=600_000,
        program_start_date="2026-09-01T00:00:00Z", clock="2026-09-01T00:00:00Z")

    rr = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "FORWARD"),
        REGISTRAR), 201)
    # Started months Sep, Oct, Nov => 3 * 100000 monthly + 100000 deposit = 400000 earned.
    assert rr["earned_cents"] == 400000, f"FORWARD earned, got {rr['earned_cents']}"
    # paid_to_date 700000 - earned 400000 = 300000 refund.
    assert rr["refund_cents"] == 300000, f"FORWARD refund, got {rr['refund_cents']}"


def test_refund_chronological_diverges_from_forward(api):
    """PRD §3.8: "the withdrawal month itself is prorated by days attended. The attended
    days are the day-of-month of the effective_date, counted inclusively from one."
    PRD §3.8: "Because the two methods treat the withdrawal month differently, identical
    inputs yield different earned amounts and therefore different refunds under the two
    methods."

    Design: Difficulty/dual_variant_calc/refund_forward_vs_chronological_diverge
    """
    room, tier, student, enr = setup_withdrawn_with_payments(
        deposit_cents=100_000, installment_cents=600_000,
        program_start_date="2026-09-01T00:00:00Z", clock="2026-09-01T00:00:00Z")

    # First create a FORWARD request and void it so the CHRONOLOGICAL one is eligible.
    fwd = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "FORWARD"),
        REGISTRAR), 201)
    validate_success(api.void_refund(fwd["id"], REGISTRAR), 200)

    chrono = validate_success(api.create_refund_request(
        create_refund_request_payload(enr["id"], "2026-11-20T00:00:00Z", "CHRONOLOGICAL"),
        REGISTRAR), 201)
    # Sep, Oct full (2 * 100000) + Nov prorated round_half_up(100000*20/30)=66667
    # + deposit 100000 = 366667 earned; refund 700000 - 366667 = 333333.
    assert chrono["earned_cents"] == 366667, f"CHRONO earned, got {chrono['earned_cents']}"
    assert chrono["refund_cents"] == 333333, f"CHRONO refund, got {chrono['refund_cents']}"
    assert chrono["refund_cents"] != fwd["refund_cents"], "methods must diverge"


# ─── dual_variant_calc / tuition_net_sibling_discount_vs_none ──────────────────

def test_tuition_net_with_sibling_discount(api):
    """PRD §3.6: "if the application's student has a sibling_of_student_id that references a
    student who has an enrollment in placed status, the running figure is reduced by ten
    percent, that is, multiplied by the quantity one minus ten percent and rounded half up
    to whole cents."

    Design: Difficulty/dual_variant_calc/tuition_net_sibling_discount_vs_none
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="PREMIUM", level="PRIMARY", base_annual_cents=1_800_000,
                       deposit_pct=0.10, installments=10, extended_day_annual_cents=200_000)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)

    # Older sibling enrolled + PLACED.
    older = create_student(parent_user_id="parent-1", full_name="Older Sib")
    enroll_child(older["id"], room["id"], tier["id"], parent_user_id="parent-1")

    # Younger child references the older sibling.
    younger = create_student(parent_user_id="parent-1", full_name="Younger Sib",
                             sibling_of_student_id=older["id"])
    yenr = enroll_child(younger["id"], room["id"], tier["id"], parent_user_id="parent-1")
    # 1800000 * 0.9 = 1620000 (no extended day, no aid).
    assert yenr["net_annual_cents"] == 1620000, f"got {yenr['net_annual_cents']}"


def test_tuition_net_without_sibling_full_base(api):
    """PRD §3.6: "The running figure begins at the tier's base_annual_cents." and the
    sibling discount applies only "if the application's student has a sibling_of_student_id
    that references a student who has an enrollment in placed status".

    Design: Difficulty/dual_variant_calc/tuition_net_sibling_discount_vs_none
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="PREMIUM", level="PRIMARY", base_annual_cents=1_800_000,
                       deposit_pct=0.10, installments=10, extended_day_annual_cents=200_000)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)

    # Sibling-less child, no extended day, no aid.
    student = create_student(parent_user_id="parent-9", full_name="Only Child")
    enr = enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-9")
    assert enr["net_annual_cents"] == 1800000, f"got {enr['net_annual_cents']}"


# ─── combinatorial_formula / tuition_net_three_inputs_nonlinear ────────────────

def test_tuition_net_sibling_extended_day_and_aid_pinned_order(api):
    """PRD §3.6: "The net annual tuition is computed once, at the moment an offer is
    accepted and the enrollment is created, in a fixed three-step order where each step's
    result feeds the next."
    PRD §3.6: "The order is significant: financial aid is applied last, after the
    extended-day surcharge has already been folded in, because applying aid before the
    add-on would yield a different total."

    Design: Difficulty/combinatorial_formula/tuition_net_three_inputs_nonlinear
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="PREMIUM", level="PRIMARY", base_annual_cents=1_800_000,
                       deposit_pct=0.10, installments=10, extended_day_annual_cents=200_000)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)

    older = create_student(parent_user_id="parent-1", full_name="Older Sib")
    enroll_child(older["id"], room["id"], tier["id"], parent_user_id="parent-1")

    younger = create_student(parent_user_id="parent-1", full_name="Younger Sib",
                             sibling_of_student_id=older["id"])
    yenr = enroll_child(younger["id"], room["id"], tier["id"], parent_user_id="parent-1",
                        extended_day_opt_in=True, financial_aid_pct=0.20)
    # 1800000*0.9=1620000 +200000=1820000 *0.8=1456000.
    assert yenr["net_annual_cents"] == 1456000, f"got {yenr['net_annual_cents']}"


def test_combined_enrollment_deposit_off_base(api):
    """PRD §3.6: "The enrollment's deposit_cents is the tier's base_annual_cents multiplied
    by the tier's deposit_pct, rounded half up to whole cents. The deposit is taken off
    base_annual_cents, never off net_annual_cents, and it is non-refundable."

    Design: Difficulty/combinatorial_formula/tuition_net_three_inputs_nonlinear
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="PREMIUM", level="PRIMARY", base_annual_cents=1_800_000,
                       deposit_pct=0.10, installments=10, extended_day_annual_cents=200_000)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)

    older = create_student(parent_user_id="parent-1", full_name="Older Sib")
    enroll_child(older["id"], room["id"], tier["id"], parent_user_id="parent-1")
    younger = create_student(parent_user_id="parent-1", full_name="Younger Sib",
                             sibling_of_student_id=older["id"])
    yenr = enroll_child(younger["id"], room["id"], tier["id"], parent_user_id="parent-1",
                        extended_day_opt_in=True, financial_aid_pct=0.20)
    # deposit = 1800000 * 0.10 = 180000, off base regardless of discounts/aid.
    assert yenr["deposit_cents"] == 180000, f"got {yenr['deposit_cents']}"


# ─── combinatorial_formula / monthly_installment_round_once_not_per_month ──────

def test_monthly_installment_rounds_once_on_quotient(api):
    """PRD §3.6: "the per-month charge is the enrollment's monthly_installment_cents,
    computed as the net_annual_cents divided by the tier's installments and rounded half up
    to whole cents. Rounding is performed once, on the single quotient, rather than
    accumulated month by month."

    Design: Difficulty/combinatorial_formula/monthly_installment_round_once_not_per_month
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STANDARD_ODD", level="PRIMARY", base_annual_cents=1_000_001,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    enr = enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1")
    # net = 1000001 (no adjustments); round_half_up(1000001/10) = 100000.
    assert enr["net_annual_cents"] == 1000001, f"net got {enr['net_annual_cents']}"
    assert enr["monthly_installment_cents"] == 100000, (
        f"installment got {enr['monthly_installment_cents']}")


def test_monthly_installment_even_division(api):
    """PRD §3.6: "the per-month charge is the enrollment's monthly_installment_cents,
    computed as the net_annual_cents divided by the tier's installments and rounded half up
    to whole cents."

    Design: Difficulty/combinatorial_formula/monthly_installment_round_once_not_per_month
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    enr = enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1")
    # net 1000000 / 10 = 100000 exactly.
    assert enr["net_annual_cents"] == 1000000
    assert enr["monthly_installment_cents"] == 100000, (
        f"installment got {enr['monthly_installment_cents']}")
