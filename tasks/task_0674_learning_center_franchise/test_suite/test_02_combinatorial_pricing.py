"""Combinatorial pricing: nested multi-subject + sibling discounts, and invoice
total computed by summing per-line components before applying the wallet.

Queue A — Difficulty/combinatorial_formula.
"""
from test_helpers import (
    validate_success,
    setup_operating_center_with_subject, create_subject, create_level,
    create_family, create_student, create_and_place_enrollment,
    adjust_wallet, create_invoice,
    make_center_director_headers,
)
from test_helpers import api_client as api

DIRECTOR = make_center_director_headers()


def _two_subject_family_with_three_enrollments(monthly_tuition_cents=15000):
    """OPERATING center + two subjects (MATH, READING) each one level + a family with
    two students. Student A: ACTIVE MATH (first), ACTIVE READING (second). Student B:
    ACTIVE MATH. sibling_count ends at 2. Returns (center, family, en_a_math,
    en_a_read, en_b_math)."""
    center, _ag, subj_m, _lv = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=monthly_tuition_cents, enrollment_fee_cents=5000)
    subj_r = create_subject(center["id"], name="READING", code="READ")
    create_level(subj_r["id"], 1, label="R1", worksheets_to_master=2, mastery_score_threshold=80)
    family = create_family(center["id"])
    st_a = create_student(family["id"], full_name="A")
    st_b = create_student(family["id"], full_name="B", birthdate="2017-01-01T00:00:00Z")
    en_a_math = create_and_place_enrollment(center["id"], st_a["id"], subj_m["id"])
    en_a_read = create_and_place_enrollment(center["id"], st_a["id"], subj_r["id"])
    en_b_math = create_and_place_enrollment(center["id"], st_b["id"], subj_m["id"])
    return center, family, en_a_math, en_a_read, en_b_math


# ===========================================================================
# tuition_rate_multi_subject_then_sibling_nested_discount
# ===========================================================================
def test_first_subject_gets_sibling_only_discount():
    """PRD §3.6: "The first such enrollment receives no multi-subject discount; the
    second receives a 10 percent discount; the third and any beyond receive a 15
    percent discount."
    PRD §3.6: "First, take the base `monthly_tuition_cents`, multiply by one minus the
    multi-subject discount fraction, and floor to a whole cent. Then take that
    intermediate amount, multiply by one minus the sibling discount fraction, and floor
    again to a whole cent; the result is the enrollment's `monthly_rate_cents`."

    Student A's first subject: multi 0%, sibling 5% (sibling_count 2):
    floor(15000*1.0)=15000 -> floor(15000*0.95)=14250.

    Design: Difficulty/combinatorial_formula/tuition_rate_multi_subject_then_sibling_nested_discount
    """
    _c, _f, en_a_math, _r, _b = _two_subject_family_with_three_enrollments()
    fresh = validate_success(api.get_enrollment(en_a_math["id"], DIRECTOR))
    assert fresh["monthly_rate_cents"] == 14250, \
        f"first subject, sibling_count 2 -> 14250, got {fresh['monthly_rate_cents']}"


def test_second_subject_gets_multi_then_sibling_nested_discount():
    """PRD §3.6: "the second receives a 10 percent discount"
    PRD §3.6: "a `sibling_count` of exactly two earns a 5 percent discount"
    PRD §3.6: "the multi-subject step always precedes the sibling step."

    Student A's second subject: multi 10%, sibling 5%:
    floor(15000*0.90)=13500 -> floor(13500*0.95)=12825 — distinct from the first
    subject's 14250.

    Design: Difficulty/combinatorial_formula/tuition_rate_multi_subject_then_sibling_nested_discount
    """
    _c, family, _m, en_a_read, _b = _two_subject_family_with_three_enrollments()
    fresh = validate_success(api.get_enrollment(en_a_read["id"], DIRECTOR))
    assert fresh["monthly_rate_cents"] == 12825, \
        f"second subject, sibling_count 2 -> 12825, got {fresh['monthly_rate_cents']}"
    fam = validate_success(api.get_family(family["id"], DIRECTOR))
    assert fam["sibling_count"] == 2, f"two students each with an ACTIVE enrollment"


# ===========================================================================
# invoice_total_sum_lines_then_apply_wallet_order_pinned
# ===========================================================================
def test_invoice_total_sums_lines_before_applying_wallet():
    """PRD §3.7: "The invoice total is computed by summing the integer per-line
    components first and only then applying the wallet: let the gross be
    `enrollment_fee_component_cents` plus `tuition_component_cents`; the
    `wallet_applied_cents` is the smaller of the family's `wallet_credit_cents` and that
    gross; and the `total_due_cents` is the gross minus `wallet_applied_cents`, which is
    never negative."

    Three enrollments (14250 + 12825 + 14250 = 41325 tuition), two students charged a
    5000 enrollment fee (10000), gross 51325, wallet 3000 -> total_due 48325.

    Design: Difficulty/combinatorial_formula/invoice_total_sum_lines_then_apply_wallet_order_pinned
    """
    center, family, _m, _r, _b = _two_subject_family_with_three_enrollments()
    adjust_wallet(family["id"], 3000)
    inv = create_invoice(family["id"], center["id"], "2026-05")
    issued = validate_success(api.issue_invoice(inv["id"], DIRECTOR))
    assert issued["tuition_component_cents"] == 41325, \
        f"14250+12825+14250=41325, got {issued['tuition_component_cents']}"
    assert issued["wallet_applied_cents"] == 3000
    assert issued["total_due_cents"] == 48325, \
        f"51325 gross - 3000 wallet = 48325, got {issued['total_due_cents']}"


def test_invoice_enrollment_fee_component_sums_per_student_once():
    """PRD §3.7: "the `enrollment_fee_component_cents` is the sum, over the students
    newly charged on this invoice, of the center's `enrollment_fee_cents` (each student
    charged the one-time fee at most once, ever)"

    Two students each newly charged a 5000 enrollment fee -> 10000.

    Design: Difficulty/combinatorial_formula/invoice_total_sum_lines_then_apply_wallet_order_pinned
    """
    center, family, _m, _r, _b = _two_subject_family_with_three_enrollments()
    adjust_wallet(family["id"], 3000)
    inv = create_invoice(family["id"], center["id"], "2026-05")
    issued = validate_success(api.issue_invoice(inv["id"], DIRECTOR))
    assert issued["enrollment_fee_component_cents"] == 10000, \
        f"two students x 5000 = 10000, got {issued['enrollment_fee_component_cents']}"
