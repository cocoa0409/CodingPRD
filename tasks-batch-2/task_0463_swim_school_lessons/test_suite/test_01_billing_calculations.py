"""Billing calculations: proration variants, sibling discount, pinned rounding,
and the parent ledger derived-field reconciliation.

Difficulty queue (A): dual_variant_calc (Invoice), combinatorial_formula.
Corner queue (B): cross_cutting_complexity_layers derived-field instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_invoice,
    assert_invoice_total_invariant,
    create_invoice_payload,
    create_student_payload,
    create_enrollment_payload,
    TEST_USERS,
    make_parent_headers,
    set_clock,
    create_location,
    create_level,
    create_instructor,
    create_class_session,
    open_session,
    create_parent,
    create_student,
    create_active_enrollment,
    setup_single_enrollment_for_billing,
    create_invoice,
    issue_invoice,
    get_session_version,
)

ADMIN = TEST_USERS["school_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

CYCLE_START = "2026-01-01T00:00:00Z"
CYCLE_END = "2026-02-01T00:00:00Z"
DUE_AT = "2026-02-15T00:00:00Z"


def test_forward_looking_charges_whole_cycle(api):
    """PRD §3.9: "Otherwise, when the variant is `FORWARD_LOOKING`, the charged
    window is the full occurrence total, billing the whole upcoming cycle
    regardless of how many classes have actually been delivered."

    One ACTIVE Level-1 enrollment (basis 12000) in a Tuesday session; the
    January cycle has 4 Tuesday occurrences, so a FORWARD_LOOKING invoice with
    the clock mid-cycle charges the full basis of 12000.

    Design: Difficulty/dual_variant_calc/tuition_forward_vs_chronological_diverge_on_invoice
    """
    env = setup_single_enrollment_for_billing(
        clock="2026-01-10T00:00:00Z", tuition_cents=12000, day_of_week=1
    )
    res = api.create_invoice(
        create_invoice_payload(
            env["parent"]["id"], CYCLE_START, CYCLE_END, DUE_AT,
            variant="FORWARD_LOOKING",
        ),
        BILLING,
    )
    inv = validate_success(res, 201)
    assert_invoice(inv)
    assert inv["total_cents"] == 12000, f"expected 12000, got {inv['total_cents']}"


def test_chronological_charges_only_delivered_occurrences(api):
    """PRD §3.9: "Otherwise, when the variant is `CHRONOLOGICAL`, the charged
    window is the number of occurrence dates strictly before the current
    logical instant, billing only the classes delivered so far."

    With the clock at 2026-01-10 only 1 of the 4 January Tuesday occurrences
    (Jan 6) precedes it, so the CHRONOLOGICAL charge is round_half_up(12000*1/4)
    = 3000 — strictly smaller than the FORWARD_LOOKING 12000.

    Design: Difficulty/dual_variant_calc/tuition_forward_vs_chronological_diverge_on_invoice
    """
    env = setup_single_enrollment_for_billing(
        clock="2026-01-10T00:00:00Z", tuition_cents=12000, day_of_week=1
    )
    fwd = validate_success(
        api.create_invoice(
            create_invoice_payload(
                env["parent"]["id"], CYCLE_START, CYCLE_END, DUE_AT,
                variant="FORWARD_LOOKING",
            ),
            BILLING,
        ),
        201,
    )
    chr_inv = validate_success(
        api.create_invoice(
            create_invoice_payload(
                env["parent"]["id"], CYCLE_START, CYCLE_END, DUE_AT,
                variant="CHRONOLOGICAL",
            ),
            BILLING,
        ),
        201,
    )
    assert chr_inv["total_cents"] == 3000, (
        f"expected 3000 for chronological, got {chr_inv['total_cents']}"
    )
    assert chr_inv["total_cents"] != fwd["total_cents"], (
        "chronological total must diverge from forward-looking total mid-cycle"
    )


def _two_sibling_setup(clock="2026-01-01T00:00:00Z", tuition_cents=12000):
    """Two Level-1 students of one parent, each ACTIVE in its own Tuesday
    session for the whole month. Returns the parent dict."""
    set_clock(clock)
    location = create_location()
    level = create_level(
        min_age_months=0, max_age_months=200,
        max_students_per_instructor=4, monthly_tuition_cents=tuition_cents,
    )
    instructor = create_instructor(certified_level_ids=[level["id"]])
    sess_a = create_class_session(
        location["id"], level["id"], instructor["id"],
        lane_number=1, day_of_week=1, start_minute=600, end_minute=645,
    )
    sess_a = open_session(sess_a["id"])
    sess_b = create_class_session(
        location["id"], level["id"], instructor["id"],
        lane_number=2, day_of_week=1, start_minute=700, end_minute=745,
    )
    sess_b = open_session(sess_b["id"])
    parent = create_parent()
    s1 = create_student(parent, level["id"], full_name="Kid One",
                        birthdate="2021-01-01T00:00:00Z")
    s2 = create_student(parent, level["id"], full_name="Kid Two",
                        birthdate="2021-02-01T00:00:00Z")
    create_active_enrollment(parent, s1, sess_a)
    create_active_enrollment(parent, s2, sess_b)
    return parent


def test_sibling_discount_two_students_tiered_argmax(api):
    """PRD §3.9: "with exactly two students it is 10%"
    PRD §3.9: "One student is exempted from the discount entirely — the student
    carrying the single highest per-line prorated charge among their lines pays
    full price (with ties broken by the earliest student `created_at`, never by
    student id)."

    Two equal-basis (12000) full-month lines, n=2 → 10%. The full-price student
    (earliest created_at on the tie) pays 12000; the sibling pays
    round_half_up(12000*0.90) = 10800. subtotal 24000, discount 1200, total 22800.

    Design: Difficulty/combinatorial_formula/sibling_discount_tiered_argmax_exclusion
    """
    parent = _two_sibling_setup()
    inv = validate_success(
        api.create_invoice(
            create_invoice_payload(parent["id"], CYCLE_START, CYCLE_END, DUE_AT,
                                   variant="FORWARD_LOOKING"),
            BILLING,
        ),
        201,
    )
    assert inv["subtotal_cents"] == 24000, f"subtotal {inv['subtotal_cents']}"
    assert inv["discount_cents"] == 1200, f"discount {inv['discount_cents']}"
    assert inv["total_cents"] == 22800, f"total {inv['total_cents']}"


def test_sibling_discount_total_equals_subtotal_minus_discount(api):
    """PRD §3.9: "the `total_cents` is the sum of the lines' `line_total_cents`
    — equivalently the subtotal minus the discount."

    The pinned-order assembly means total == subtotal - discount holds exactly
    on the two-sibling invoice (24000 - 1200 = 22800).

    Design: Difficulty/combinatorial_formula/sibling_discount_tiered_argmax_exclusion
    """
    parent = _two_sibling_setup()
    inv = validate_success(
        api.create_invoice(
            create_invoice_payload(parent["id"], CYCLE_START, CYCLE_END, DUE_AT,
                                   variant="FORWARD_LOOKING"),
            BILLING,
        ),
        201,
    )
    assert_invoice_total_invariant(inv)
    assert inv["total_cents"] == inv["subtotal_cents"] - inv["discount_cents"]


def _two_tots_midcycle_setup():
    """Two Tots students (basis 10000) of one parent, each ACTIVE-joined
    2026-01-14 in its own Tuesday session. Cycle Jan1-Jan22 has 3 Tuesdays
    (6,13,20); remaining from Jan14 = 1 (Jan20). Returns the parent dict."""
    set_clock("2026-01-14T00:00:00Z")
    location = create_location()
    tots = create_level(
        name="Tots", sequence_order=1, min_age_months=6, max_age_months=36,
        max_students_per_instructor=3, monthly_tuition_cents=10000,
    )
    instructor = create_instructor(certified_level_ids=[tots["id"]])
    sess_a = create_class_session(
        location["id"], tots["id"], instructor["id"],
        lane_number=1, day_of_week=1, start_minute=540, end_minute=570,
    )
    sess_a = open_session(sess_a["id"])
    sess_b = create_class_session(
        location["id"], tots["id"], instructor["id"],
        lane_number=2, day_of_week=1, start_minute=600, end_minute=630,
    )
    sess_b = open_session(sess_b["id"])
    parent = create_parent()
    s1 = create_student(parent, tots["id"], full_name="Tot One",
                        birthdate="2024-06-01T00:00:00Z")
    s2 = create_student(parent, tots["id"], full_name="Tot Two",
                        birthdate="2024-06-15T00:00:00Z")
    create_active_enrollment(parent, s1, sess_a)
    create_active_enrollment(parent, s2, sess_b)
    return parent


def test_proration_rounds_per_line_then_sums_subtotal(api):
    """PRD §2.7: "each invoice line is rounded to whole cents on its own, and
    only then are lines summed. Summing un-rounded line values and rounding once
    at the end is explicitly forbidden, because round-per-line-then-sum can
    legitimately differ from sum-then-round by as much as one cent, and only the
    per-line order is correct here."

    Two mid-cycle Tots lines each prorate to round_half_up(10000/3)=3333; the
    pinned per-line order gives subtotal 6666 (not the 6667 a sum-then-round
    would produce from raw 6666.67).

    Design: Difficulty/combinatorial_formula/proration_round_per_line_then_sum
    """
    parent = _two_tots_midcycle_setup()
    inv = validate_success(
        api.create_invoice(
            create_invoice_payload(parent["id"], CYCLE_START,
                                   "2026-01-22T00:00:00Z", DUE_AT,
                                   variant="FORWARD_LOOKING"),
            BILLING,
        ),
        201,
    )
    assert inv["subtotal_cents"] == 6666, (
        f"round-per-line-then-sum must yield 6666, got {inv['subtotal_cents']}"
    )


def test_proration_two_tots_discount_and_total(api):
    """PRD §3.9: "the invoice's `subtotal_cents` is the sum of the lines'
    `prorated_cents`, the `discount_cents` is the sum of the per-line discount
    amounts, and the `total_cents` is the sum of the lines' `line_total_cents`"

    With two students (10% tier) and equal per-line prorated 3333, the full-price
    student keeps 3333 and the sibling pays round_half_up(3333*0.90)=3000, so
    discount = 333 and total = 3333 + 3000 = 6333.

    Design: Difficulty/combinatorial_formula/proration_round_per_line_then_sum
    """
    parent = _two_tots_midcycle_setup()
    inv = validate_success(
        api.create_invoice(
            create_invoice_payload(parent["id"], CYCLE_START,
                                   "2026-01-22T00:00:00Z", DUE_AT,
                                   variant="FORWARD_LOOKING"),
            BILLING,
        ),
        201,
    )
    assert inv["total_cents"] == 6333, f"total {inv['total_cents']}"
    assert inv["discount_cents"] == 333, f"discount {inv['discount_cents']}"


# ─── Corner queue (B): derived-field reconciliation on the parent ledger ───
def test_issue_invoice_increments_outstanding_balance(api):
    """PRD §3.10: "Issuing adds the invoice's `total_cents` to the parent's
    `outstanding_balance_cents`, keeping the ledger in sync."

    A 12000 full-month invoice issued drives the parent's
    outstanding_balance_cents to 12000.

    Design: Corner/cross_cutting_complexity_layers/invoice_issue_increments_outstanding_balance
    """
    env = setup_single_enrollment_for_billing(
        clock="2026-01-01T00:00:00Z", tuition_cents=12000, day_of_week=1
    )
    inv = create_invoice(env["parent"]["id"], CYCLE_START, CYCLE_END, DUE_AT,
                         variant="FORWARD_LOOKING")
    assert inv["total_cents"] == 12000, f"invoice total {inv['total_cents']}"
    validate_success(api.issue_invoice(inv["id"], BILLING), 200)
    parent = validate_success(api.get_parent(env["parent"]["id"], BILLING), 200)
    assert parent["outstanding_balance_cents"] == 12000, (
        f"expected balance 12000, got {parent['outstanding_balance_cents']}"
    )


def test_pay_invoice_reverses_outstanding_balance(api):
    """PRD §3.10: "A successful payment subtracts the invoice's `total_cents`
    from the parent's `outstanding_balance_cents`, recomputes the parent's
    `account_standing`, and increments the invoice's `version` by one."

    After issue (+12000) then pay with the correct expected_invoice_version, the
    balance returns to 0 and the invoice is PAID.

    Design: Corner/cross_cutting_complexity_layers/invoice_pay_reverses_balance_compensating
    """
    env = setup_single_enrollment_for_billing(
        clock="2026-01-01T00:00:00Z", tuition_cents=12000, day_of_week=1
    )
    inv = create_invoice(env["parent"]["id"], CYCLE_START, CYCLE_END, DUE_AT,
                         variant="FORWARD_LOOKING")
    issued = issue_invoice(inv["id"])
    paid = validate_success(
        api.pay_invoice(inv["id"], {"expected_invoice_version": issued["version"]},
                        BILLING),
        200,
    )
    assert paid["status"] == "PAID"
    parent = validate_success(api.get_parent(env["parent"]["id"], BILLING), 200)
    assert parent["outstanding_balance_cents"] == 0, (
        f"expected balance 0 after pay, got {parent['outstanding_balance_cents']}"
    )
