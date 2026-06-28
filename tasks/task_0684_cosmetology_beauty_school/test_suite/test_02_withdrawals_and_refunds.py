"""Withdrawal R2T4 / institutional refund calculations and the finalize cascade.

Covers the scheduled-vs-actual basis divergence between the federal R2T4 return
and the institutional refund, the >60% R2T4 ceiling, and the depth-three
finalize cascade (Withdrawal -> Enrollment -> Disbursement -> ledger).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_withdrawal,
    setup_posted_disbursement,
    setup_calculated_withdrawal_with_posted_disbursement,
    make_financial_aid_officer_headers,
)

FAO = make_financial_aid_officer_headers()


# ==========================================================================
# dual_variant_calc / r2t4_scheduled_vs_institutional_actual_on_withdrawal (queue A)
# ==========================================================================
def test_withdrawal_r2t4_uses_scheduled_hours_basis(api):
    """PRD §3.6: "the enrollment's `scheduled_hours_to_date` divided by the
    program's `total_clock_hours`, multiplied by 100, rounded half up to two
    decimal places. Note the basis — R2T4 uses *scheduled* hours as of the
    withdrawal date, not hours actually attended."

    450/1500 = 30.00% completed; earned = 30% of 600000 posted net = 180000, so
    title_iv_return_cents = 600000 - 180000 = 420000.

    Design: Difficulty/dual_variant_calc/r2t4_scheduled_vs_institutional_actual_on_withdrawal
    """
    program, student, instructor, enrollment, dis = setup_posted_disbursement(
        program_overrides={
            "total_clock_hours": 1500, "tuition_cents": 1200000,
            "kit_fee_cents": 150000, "lab_fee_cents": 50000,
            "clinic_phase_start_hour": 300, "admin_fee_cap_cents": 15000,
        },
        actual_hours=405, scheduled_hours_to_date=450,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    wd = validate_success(
        api.create_withdrawal(
            {"enrollment_id": enrollment["id"], "withdrawal_type": "OFFICIAL",
             "last_date_of_attendance_iso": "2026-05-01T00:00:00Z"},
            FAO,
        ),
        201,
    )
    assert wd["pct_completed"] == 30.00, f"pct_completed should be 30.00, got {wd['pct_completed']}"
    assert wd["title_iv_return_cents"] == 420000, (
        f"R2T4 return should be 420000, got {wd['title_iv_return_cents']}"
    )


def test_withdrawal_institutional_refund_uses_actual_hours_basis(api):
    """PRD §3.6: "Compute the fraction used as the enrollment's `actual_hours`
    divided by the program's `total_clock_hours`. The refund before the
    administrative fee is the program's `tuition_cents` multiplied by one minus
    that used fraction, rounded half up to whole cents. From that, subtract the
    program's `admin_fee_cap_cents` ... and floor the result at 0."

    actual 405/1500 = 0.27 used; refund_before_fee = 1200000*(1-0.27) = 876000;
    minus 15000 cap = 861000, which differs from the 420000 R2T4 figure.

    Design: Difficulty/dual_variant_calc/r2t4_scheduled_vs_institutional_actual_on_withdrawal
    """
    program, student, instructor, enrollment, dis = setup_posted_disbursement(
        program_overrides={
            "total_clock_hours": 1500, "tuition_cents": 1200000,
            "kit_fee_cents": 150000, "lab_fee_cents": 50000,
            "clinic_phase_start_hour": 300, "admin_fee_cap_cents": 15000,
        },
        actual_hours=405, scheduled_hours_to_date=450,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    wd = validate_success(
        api.create_withdrawal(
            {"enrollment_id": enrollment["id"], "withdrawal_type": "OFFICIAL",
             "last_date_of_attendance_iso": "2026-05-01T00:00:00Z"},
            FAO,
        ),
        201,
    )
    assert wd["institutional_refund_cents"] == 861000, (
        f"institutional refund should be 861000, got {wd['institutional_refund_cents']}"
    )
    assert wd["title_iv_return_cents"] != wd["institutional_refund_cents"], (
        "R2T4 (scheduled basis) and institutional refund (actual basis) must differ"
    )


# ==========================================================================
# transitive_cascade / withdrawal_finalize_depth3_cascade  (queue A)
# ==========================================================================
def test_finalize_withdrawal_cascades_to_withdrawn_and_returns_disbursement(api):
    """PRD §3.6: "the owning enrollment transitions to `WITHDRAWN`, which then
    drives three cascades on the enrollment's children, all within the same
    operation: every `SCHEDULED` disbursement on the enrollment is moved to
    `RETURNED` (and because each such return is processed through the ledger sync,
    a disbursement that had been posted is debited back out of
    `total_credits_cents` and the `ledger_balance_cents` recomputed ...)."

    Design: Difficulty/transitive_cascade/withdrawal_finalize_depth3_cascade
    """
    program, student, instructor, enrollment, dis, wd = (
        setup_calculated_withdrawal_with_posted_disbursement(
            program_overrides={
                "total_clock_hours": 1500, "tuition_cents": 1200000,
                "kit_fee_cents": 150000, "lab_fee_cents": 50000,
                "clinic_phase_start_hour": 300,
            },
            actual_hours=405, scheduled_hours_to_date=450,
            gross_amount_cents=600000, origination_fee_cents=0,
        )
    )
    enr = validate_success(api.get_enrollment(enrollment["id"], FAO))
    final = validate_success(api.finalize_withdrawal(wd["id"], enr["version"], FAO))
    assert final["status"] == "FINALIZED"
    enr_after = validate_success(api.get_enrollment(enrollment["id"], FAO))
    assert enr_after["status"] == "WITHDRAWN"
    dis_after = validate_success(api.get_disbursement(dis["id"], FAO))
    assert dis_after["status"] == "RETURNED"


def test_finalize_withdrawal_recomputes_ledger_after_return(api):
    """PRD §3.6: "a disbursement that had been posted is debited back out of
    `total_credits_cents` and the `ledger_balance_cents` recomputed."

    The posted 600000 is reversed, so the enrollment's ledger_balance_cents
    recomputes back to the full charges 1400000.

    Design: Difficulty/transitive_cascade/withdrawal_finalize_depth3_cascade
    """
    program, student, instructor, enrollment, dis, wd = (
        setup_calculated_withdrawal_with_posted_disbursement(
            program_overrides={
                "total_clock_hours": 1500, "tuition_cents": 1200000,
                "kit_fee_cents": 150000, "lab_fee_cents": 50000,
                "clinic_phase_start_hour": 300,
            },
            actual_hours=405, scheduled_hours_to_date=450,
            gross_amount_cents=600000, origination_fee_cents=0,
        )
    )
    enr = validate_success(api.get_enrollment(enrollment["id"], FAO))
    validate_success(api.finalize_withdrawal(wd["id"], enr["version"], FAO))
    enr_after = validate_success(api.get_enrollment(enrollment["id"], FAO))
    assert enr_after["ledger_balance_cents"] == 1400000, (
        f"ledger should recompute to 1400000, got {enr_after['ledger_balance_cents']}"
    )


# ==========================================================================
# calculations / r2t4_over_60_percent_returns_zero  (queue B)
# ==========================================================================
def test_r2t4_over_sixty_percent_returns_zero(api):
    """PRD §3.6: "If `pct_completed` is strictly greater than 60.00, the student is
    treated as having earned 100% of their aid and `title_iv_return_cents` is 0."

    1200/1500 = 80.00% > 60.00, so no Title IV is returned despite 600000 posted.

    Design: Corner/calculations/r2t4_over_60_percent_returns_zero
    """
    program, student, instructor, enrollment, dis = setup_posted_disbursement(
        program_overrides={
            "total_clock_hours": 1500, "tuition_cents": 1200000,
            "kit_fee_cents": 150000, "lab_fee_cents": 50000,
            "clinic_phase_start_hour": 300,
        },
        actual_hours=1200, scheduled_hours_to_date=1200,
        gross_amount_cents=600000, origination_fee_cents=0,
        post_clock_iso="2026-08-01T00:00:00Z",
    )
    wd = validate_success(
        api.create_withdrawal(
            {"enrollment_id": enrollment["id"], "withdrawal_type": "OFFICIAL",
             "last_date_of_attendance_iso": "2026-07-01T00:00:00Z"},
            FAO,
        ),
        201,
    )
    assert wd["pct_completed"] == 80.00, f"pct_completed should be 80.00, got {wd['pct_completed']}"
    assert wd["title_iv_return_cents"] == 0, (
        f"R2T4 return should be 0 above 60%, got {wd['title_iv_return_cents']}"
    )
