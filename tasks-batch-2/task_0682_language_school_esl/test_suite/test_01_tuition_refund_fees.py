"""Tuition invoicing, add-on fees, and withdrawal refund calculations (PRD §3.6, §3.7).

Difficulty queue: dual_variant_calc (refund), combinatorial_formula (tuition, immersion fee).
Corner queue: tuition rounding, immersion surcharge boundary, week-0 full refund,
              completion-read computed score, consistency-model immediate tuition.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_corporate_contract_payload, create_cohort_payload,
    create_student_payload, create_placement_test_payload, score_placement_test_payload,
    create_enrollment_payload, confirm_enrollment_payload, create_add_on_payload,
    TEST_USERS, make_student_headers, set_clock,
    create_contract, create_cohort, create_placed_student, create_enrollment, confirm,
    setup_enrolled_student, setup_pending_enrollment, setup_completed_enrollment,
)

REG = TEST_USERS["registrar_headers"]
INSTR = TEST_USERS["instructor_headers"]


# =====================================================================
# Difficulty / combinatorial_formula / tuition_invoice_pinned_evaluation_order_mode_c
# =====================================================================
def test_gold_tuition_discount_pinned_on_base_only(api):
    """PRD §3.6: "the discount in cents is computed by multiplying the cohort's
    base_tuition_cents alone by the discount percentage and rounding that product
    half up to a whole number of cents; the discount is computed off the base
    tuition only and never off the add-ons."
    PRD §3.6: "GOLD yields 20 percent"

    Design: Difficulty/combinatorial_formula/tuition_invoice_pinned_evaluation_order_mode_c
    """
    contract = create_contract(contracted_seats=3, discount_tier="GOLD", company_name="Acme2")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=3, weekly_hours=18,
                           base_tuition_cents=300000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    # PRIVATE_TUTORING units 5 -> fee 30000 (6000 * 5), no surcharge.
    get_success_data(api.create_add_on(
        create_add_on_payload(stu["id"], enr["id"], "PRIVATE_TUTORING", 5), REG))
    data = validate_success(api.confirm_enrollment(
        enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), REG))
    # gross 330000 - round_half_up(300000*0.20)=60000 -> 270000 (NOT 264000).
    assert data["tuition_invoice_cents"] == 270000, (
        f"expected 270000 (discount on base only), got {data['tuition_invoice_cents']}")


def test_gold_tuition_not_discounted_on_gross(api):
    """PRD §3.6: "the discount is computed off the base tuition only and never off
    the add-ons."

    Design: Difficulty/combinatorial_formula/tuition_invoice_pinned_evaluation_order_mode_c
    """
    contract = create_contract(contracted_seats=3, discount_tier="GOLD")
    cohort = create_cohort(base_tuition_cents=300000, capacity=3)
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    get_success_data(api.create_add_on(
        create_add_on_payload(stu["id"], enr["id"], "PRIVATE_TUTORING", 5), REG))
    data = validate_success(api.confirm_enrollment(
        enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), REG))
    # Discounting the gross (330000*0.20 -> 264000) is the WRONG evaluation order.
    assert data["tuition_invoice_cents"] != 264000, "discount must not apply to add-ons"


# =====================================================================
# Difficulty / combinatorial_formula / immersion_addon_fee_nonlinear_surcharge_mode_a
# =====================================================================
def test_immersion_addon_fee_nonlinear_surcharge(api):
    """PRD §3.6: "when units exceeds 2, the surcharge is the unit rate multiplied
    by the number of units above 2, multiplied by 0.15, rounded half up to a whole
    number of cents; when units is 2 or fewer, the surcharge is 0. The immersion
    fee_cents is the base plus that surcharge."
    PRD §3.6: "an IMMERSION_ABROAD unit costs 40,000 cents."

    Design: Difficulty/combinatorial_formula/immersion_addon_fee_nonlinear_surcharge_mode_a
    """
    cohort = create_cohort(schedule_block="EVENING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    headers = make_student_headers(stu["id"])
    # units 4: base 160000 + round_half_up(40000*2*0.15)=12000 -> 172000.
    data = validate_success(api.create_add_on(
        create_add_on_payload(stu["id"], enr["id"], "IMMERSION_ABROAD", 4), headers), 201)
    assert data["fee_cents"] == 172000, f"expected 172000, got {data['fee_cents']}"


def test_immersion_addon_fee_not_linear(api):
    """PRD §3.6: "For IMMERSION_ABROAD, a tiered surcharge applies: the first 2
    weeks carry no surcharge, and each additional week beyond the first 2 adds a
    surcharge of 15 percent of that week's base rate."

    Design: Difficulty/combinatorial_formula/immersion_addon_fee_nonlinear_surcharge_mode_a
    """
    cohort = create_cohort(schedule_block="EVENING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    headers = make_student_headers(stu["id"])
    data = validate_success(api.create_add_on(
        create_add_on_payload(stu["id"], enr["id"], "IMMERSION_ABROAD", 4), headers), 201)
    # The linear (no-surcharge) result 160000 is rejected.
    assert data["fee_cents"] != 160000, "surcharge must apply for units > 2"


# =====================================================================
# Difficulty / dual_variant_calc / refund_chronological_schedule_differs_from_prorata_on_enrollment
# =====================================================================
def test_refund_chronological_week2_schedule(api):
    """PRD §3.7: "2 or 3 weeks elapsed refunds 0.50"
    PRD §3.7: "The refund_cents is the enrollment's pinned tuition_invoice_cents
    multiplied by that fraction, rounded half up to a whole number of cents."
    PRD §3.7: "The refund is driven entirely by calendar weeks elapsed since
    term_start, independent of how many class sessions actually took place; an
    alternative reading that would prorate by remaining sessions is explicitly not
    used and would produce a different value."

    Design: Difficulty/dual_variant_calc/refund_chronological_schedule_differs_from_prorata_on_enrollment
    """
    contract = create_contract(contracted_seats=5, discount_tier="GOLD", company_name="Acme")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=300000, schedule_block="MORNING",
                           term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                           total_sessions=40)
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    get_success_data(api.create_add_on(
        create_add_on_payload(stu["id"], enr["id"], "PRIVATE_TUTORING", 5), REG))
    confirmed = validate_success(api.confirm_enrollment(
        enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), REG))
    assert confirmed["tuition_invoice_cents"] == 270000
    # weeks_elapsed = floor((2026-05-19 - 2026-05-04)/7) = floor(15/7) = 2 -> 0.50.
    set_clock("2026-05-19T00:00:00Z")
    data = validate_success(api.withdraw_enrollment(enr["id"], REG))
    assert data["refund_cents"] == 135000, f"expected 135000 (0.50*270000), got {data['refund_cents']}"
    assert data["status"] == "WITHDRAWN"


def test_refund_chronological_week1_schedule(api):
    """PRD §3.7: "1 week elapsed refunds 0.75"
    PRD §3.7: "The refund is driven entirely by calendar weeks elapsed since
    term_start, independent of how many class sessions actually took place; an
    alternative reading that would prorate by remaining sessions is explicitly not
    used and would produce a different value."

    Design: Difficulty/dual_variant_calc/refund_chronological_schedule_differs_from_prorata_on_enrollment
    """
    # Self-pay net tuition 100000; withdraw at week 1 (clock term_start+10 days).
    cohort = create_cohort(level="B1", track="GENERAL", base_tuition_cents=100000,
                           schedule_block="MORNING", term_start="2026-05-04T00:00:00Z")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    # floor((2026-05-14 - 2026-05-04)/7) = floor(10/7) = 1 -> 0.75.
    set_clock("2026-05-14T00:00:00Z")
    data = validate_success(api.withdraw_enrollment(enr["id"], REG))
    assert data["refund_cents"] == 75000, f"expected 75000 (0.75*100000), got {data['refund_cents']}"


def test_refund_full_in_week_zero(api):
    """PRD §3.7: "0 weeks elapsed refunds the full amount (fraction 1.00, the
    withdrawal lands before the first week completes)"

    Design: Corner/calculations/refund_full_in_week_zero
    """
    cohort = create_cohort(level="B1", track="GENERAL", base_tuition_cents=100000,
                           schedule_block="MORNING", term_start="2026-05-04T00:00:00Z")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    # clock 2026-05-07: floor(3/7)=0 weeks -> 1.00.
    set_clock("2026-05-07T00:00:00Z")
    data = validate_success(api.withdraw_enrollment(enr["id"], REG))
    assert data["refund_cents"] == 100000, f"expected full 100000, got {data['refund_cents']}"


# =====================================================================
# Corner / calculations / tuition_silver_discount_rounding_half_up
# =====================================================================
def test_silver_tuition_discount_rounds_half_up(api):
    """PRD §3.6: "SILVER yields 10 percent"
    PRD §3.6: "the discount in cents is computed by multiplying the cohort's
    base_tuition_cents alone by the discount percentage and rounding that product
    half up to a whole number of cents"

    Design: Corner/calculations/tuition_silver_discount_rounding_half_up
    """
    contract = create_contract(contracted_seats=3, discount_tier="SILVER", company_name="Round")
    cohort = create_cohort(level="B1", track="GENERAL", base_tuition_cents=12345,
                           schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    data = validate_success(api.confirm_enrollment(
        enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), REG))
    # discount = round_half_up(12345*0.10)=round_half_up(1234.5)=1235; 12345-1235=11110.
    assert data["tuition_invoice_cents"] == 11110, (
        f"expected 11110 (12345 - rhu(1234.5)=1235), got {data['tuition_invoice_cents']}")


# =====================================================================
# Corner / calculations / addon_immersion_no_surcharge_at_two_weeks
# =====================================================================
def test_immersion_no_surcharge_at_two_weeks(api):
    """PRD §3.6: "when units is 2 or fewer, the surcharge is 0."

    Design: Corner/calculations/addon_immersion_no_surcharge_at_two_weeks
    """
    cohort = create_cohort(level="B1", track="GENERAL")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    # Registrar may create add-ons on a student's behalf (PRD §3.6).
    data = validate_success(api.create_add_on(
        create_add_on_payload(stu["id"], enr["id"], "IMMERSION_ABROAD", 2), REG), 201)
    # base 40000*2 = 80000, surcharge 0.
    assert data["fee_cents"] == 80000, f"expected 80000, got {data['fee_cents']}"


# =====================================================================
# Corner / endpoints / completion_read_returns_computed_score
# =====================================================================
def test_completion_read_returns_computed_score(api):
    """PRD §3.7: "it combines them as 0.7 times the rounded skill average plus 0.3
    times the rounded attendance points, and rounds that result half up to a whole
    number — this is the completion_score."
    PRD §3.5: "The attendance_rate is sessions_attended divided by sessions_elapsed,
    expressed as a fraction between 0 and 1"

    Design: Corner/endpoints/completion_read_returns_computed_score
    """
    # 9 PRESENT + 1 ABSENT -> rate 0.9; report 80/82/78/84 -> skill_avg rhu(81.0)=81;
    # attendance_pts rhu(90.0)=90; rhu(0.7*81 + 0.3*90)=rhu(56.7+27)=rhu(83.7)=84.
    stu, cohort, enr = setup_completed_enrollment(
        weekly_hours=9, total_sessions=10, present_sessions=9, absent_sessions=1,
        speaking=80, listening=82, reading=78, writing=84)
    data = validate_success(api.get_enrollment(enr["id"], REG))
    assert data["completion_score"] == 84, f"expected 84, got {data['completion_score']}"
    assert data["attendance_rate"] == pytest.approx(0.9, abs=0.001)
    assert data["status"] == "COMPLETED"


def test_completion_score_latest_progress_report_wins(api):
    """PRD §3.7: "the system takes the latest progress report (greatest assessed_at,
    ties broken by earlier created_at) and computes a skill average as the sum of
    its speaking, listening, reading, and writing sub-scores divided by 4, rounded
    half up to a whole number."

    Design: Corner/calculations/completion_score_latest_progress_report_wins
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=9, base_tuition_cents=100000,
                           schedule_block="MORNING", term_start="2026-04-01T00:00:00Z",
                           term_end="2026-04-10T00:00:00Z", total_sessions=10)
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    get_success_data(api.create_attendance(
        {"enrollment_id": enr["id"], "session_index": 1, "status": "PRESENT"}, INSTR))
    # Earlier high report (95s), then later 70s report — latest (70s) must win.
    set_clock("2026-04-05T00:00:00Z")
    get_success_data(api.create_progress_report(
        {"enrollment_id": enr["id"], "speaking": 95, "listening": 95, "reading": 95, "writing": 95}, INSTR))
    set_clock("2026-04-08T00:00:00Z")
    get_success_data(api.create_progress_report(
        {"enrollment_id": enr["id"], "speaking": 70, "listening": 70, "reading": 70, "writing": 70}, INSTR))
    set_clock("2026-04-11T00:00:00Z")
    data = validate_success(api.complete_enrollment(enr["id"], REG))
    # skill_avg rhu(70)=70; attendance rhu(100)=100; rhu(0.7*70+0.3*100)=rhu(79)=79.
    assert data["completion_score"] == 79, f"expected 79 (latest report), got {data['completion_score']}"


# =====================================================================
# Corner / consistency_model / confirm_response_reflects_tuition_immediately
# =====================================================================
def test_confirm_response_reflects_tuition_immediately(api):
    """PRD §3.3: "Upon a successful ENROLLED confirm, the system stamps enrolled_at
    with the current logical clock, computes and pins tuition_invoice_cents per §3.6"
    PRD §3.6: "For a self-pay student this reduces to base_tuition_cents plus the
    add-on total with no discount."

    Design: Corner/consistency_model/confirm_response_reflects_tuition_immediately
    """
    cohort = create_cohort(level="B1", track="GENERAL", base_tuition_cents=300000,
                           schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    # The confirm response ITSELF carries the computed values (no re-read).
    data = validate_success(api.confirm_enrollment(
        enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), REG))
    assert data["tuition_invoice_cents"] == 300000
    assert data["status"] == "ENROLLED"
