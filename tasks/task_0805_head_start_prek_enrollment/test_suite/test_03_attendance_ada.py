"""Attendance, ADA variants, and PIR aggregation (PRD §3.6, §3.9).

Depth coverage for the period-to-date vs annualized ADA dual variant and the
PIR avg_ada_rate round-then-average order; breadth coverage for the recomputed
ada_rate on an enrollment read.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_active_enrollment, setup_program_and_cohort, add_waitlisted_applicant,
    run_selection, offer_id_for_application, accept_offer, enrollment_for_application,
    record_attendance, create_pir_report_payload,
)

ES = TEST_USERS["enrollment_specialist_headers"]
PA = TEST_USERS["program_admin_headers"]


def _two_active_enrollments_same_program():
    """Program (total_instructional_days=160) with two ACTIVE enrollments."""
    program, cohort = setup_program_and_cohort()
    famB, appB = add_waitlisted_applicant(
        program, cohort,
        family_overrides={"guardian_name": "B", "household_size": 3,
                          "annual_income_cents": 800000, "categorical_eligibility": "TANF"},
        app_overrides={"child_first_name": "Bo", "child_last_name": "B",
                       "child_dob": "2022-01-10"},
        verified_income_cents=800000)
    famA, appA = add_waitlisted_applicant(
        program, cohort,
        family_overrides={"guardian_name": "A", "household_size": 4,
                          "annual_income_cents": 1400000, "categorical_eligibility": "SNAP"},
        app_overrides={"child_first_name": "Al", "child_last_name": "A",
                       "child_dob": "2022-02-20"},
        verified_income_cents=1400000)
    run_selection(cohort["id"])
    accept_offer(offer_id_for_application(appB["id"]), famB["id"])
    accept_offer(offer_id_for_application(appA["id"]), famA["id"])
    enr1 = enrollment_for_application(appB["id"])
    enr2 = enrollment_for_application(appA["id"])
    return program, enr1, enr2


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / ada_period_to_date_vs_annualized
# ---------------------------------------------------------------------------
def test_ada_rate_period_to_date_uses_elapsed_days(api):
    """PRD §3.6: "The period-to-date `ada_rate` is present days divided by elapsed
    instructional days, rounded half-up to four decimals, or zero when no instructional
    days have been recorded."

    Design: Difficulty/dual_variant_calc/ada_period_to_date_vs_annualized
    """
    b = setup_active_enrollment()
    record_attendance(b["enrollment"]["id"], present=9, absent_unexcused=1)
    data = validate_success(api.get_enrollment(b["enrollment"]["id"], ES))
    assert data["ada_rate"] == 0.9, f"expected 0.9, got {data['ada_rate']}"


def test_annualized_ada_rate_uses_program_year_denominator(api):
    """PRD §3.6: "The `annualized_ada_rate` is present days divided by the program's
    `total_instructional_days`, rounded half-up to four decimals, and therefore yields a
    different value from `ada_rate` for the same attendance because it uses the full
    funded-year denominator."

    Design: Difficulty/dual_variant_calc/ada_period_to_date_vs_annualized
    """
    b = setup_active_enrollment()
    record_attendance(b["enrollment"]["id"], present=9, absent_unexcused=1)
    data = validate_success(api.get_enrollment(b["enrollment"]["id"], ES))
    assert data["annualized_ada_rate"] == 0.0563, (
        f"expected 0.0563, got {data['annualized_ada_rate']}")
    assert data["annualized_ada_rate"] != data["ada_rate"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / pir_avg_ada_round_then_average_order
# ---------------------------------------------------------------------------
def test_pir_avg_ada_rounds_each_enrollment_then_averages(api):
    """PRD §3.9: "The `avg_ada_rate` is computed with a mandatory rounding order: each
    pool enrollment's `ada_rate` is first rounded to four decimals, those rounded values
    are then averaged, and the mean is finally rounded half-up to four decimals; this
    per-enrollment-round-then-average order is required and differs from dividing summed
    present days by summed instructional days, which is explicitly not used."

    Design: Difficulty/combinatorial_formula/pir_avg_ada_round_then_average_order
    """
    program, enr1, enr2 = _two_active_enrollments_same_program()
    record_attendance(enr1["id"], present=9, absent_unexcused=1)   # ada 0.9
    record_attendance(enr2["id"], present=4, absent_excused=1)     # ada 0.8
    data = validate_success(
        api.create_pir_report(create_pir_report_payload(program["id"]), PA),
        expected_status=201)
    assert data["avg_ada_rate"] == 0.85, f"expected 0.85, got {data['avg_ada_rate']}"


def test_pir_total_enrolled_counts_pool(api):
    """PRD §3.9: "At creation the system fixes the reporting pool as every enrollment in
    the program whose `status` is `ACTIVE` or `COMPLETED_TRANSITION`, and computes the
    aggregate counts against that pool. The `total_enrolled` is the size of the pool."

    Design: Difficulty/combinatorial_formula/pir_avg_ada_round_then_average_order
    """
    program, enr1, enr2 = _two_active_enrollments_same_program()
    record_attendance(enr1["id"], present=9, absent_unexcused=1)
    record_attendance(enr2["id"], present=4, absent_excused=1)
    data = validate_success(
        api.create_pir_report(create_pir_report_payload(program["id"]), PA),
        expected_status=201)
    assert data["total_enrolled"] == 2


# ---------------------------------------------------------------------------
# Corner: endpoints / enrollment_read_recomputes_ada_after_new_attendance
# ---------------------------------------------------------------------------
def test_enrollment_read_recomputes_ada_rate(api):
    """PRD §3.6: "The period-to-date `ada_rate` is present days divided by elapsed
    instructional days, rounded half-up to four decimals, or zero when no instructional
    days have been recorded."
    PRD §3.6: "The `chronic_absence` flag is true exactly when `unexcused_absence_rate`
    is at least the program's `ada_chronic_threshold_pct`."

    Design: Corner/endpoints/enrollment_read_recomputes_ada_after_new_attendance
    """
    b = setup_active_enrollment()
    record_attendance(b["enrollment"]["id"], present=1, absent_excused=1)  # 1 of 2 => 0.5
    data = validate_success(api.get_enrollment(b["enrollment"]["id"], ES))
    assert data["ada_rate"] == 0.5, f"expected 0.5, got {data['ada_rate']}"
    assert data["chronic_absence"] is False
