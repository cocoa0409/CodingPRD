"""Per-line and report-total calculations: mileage rate, lodging per-diem cap,
report total excluding meal lines, business-class short-flight policy.

Queue B (Corner) — section calculations.
"""
from test_helpers import (
    get_success_data,
    setup_base_env,
    create_approved_trip,
    create_report,
    add_flight_line,
    add_flight_line_with_receipt,
    add_lodging_line,
    add_mileage_line,
    add_meal_line,
    submit_report,
)


def test_mileage_reimbursable_rate(api):
    """PRD §3.5: "For a mileage line, the reimbursable_amount_cents is the product of
    miles and the policy's mileage_rate_milli_cents, divided by one thousand to convert
    milli-cents into cents, with that single division rounded half up to a whole cent;
    a mileage line is always in-policy."

    Design: Corner/calculations/mileage_reimbursable_rate_correct
    """
    env = setup_base_env(mileage_rate_milli_cents=67000)
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="Mileage Rpt")
    # 137 * 67000 / 1000 = 9179.0 -> round_half_up -> 9179
    line = add_mileage_line(env, report, miles=137)
    assert line["reimbursable_amount_cents"] == 9179, (
        f"137mi @ 67000 milli-cents = 9179 cents, got {line['reimbursable_amount_cents']}"
    )
    assert line["in_policy"] is True


def test_lodging_capped_at_perdiem_times_nights(api):
    """PRD §3.5: "For a lodging line, the system first computes the number of nights as
    the day count of the half-open interval from check_in_date to check_out_date
    (check-out minus check-in), then sets the cap to the destination's GSA
    lodging_cap_cents — looked up by the trip's destination_state — multiplied by that
    night count; the reimbursable_amount_cents is the smaller of claimed_amount_cents
    and the cap, and the line is in-policy when claimed_amount_cents is less than or
    equal to the cap."

    Design: Corner/calculations/lodging_capped_at_perdiem_nights
    """
    env = setup_base_env(lodging_cap_cents=20000)
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="Lodging Cap Rpt")
    # 2 nights (06-01..06-03) cap 20000*2=40000; claimed 50000 -> reimbursable 40000, out of policy.
    line = add_lodging_line(env, report, claimed_amount_cents=50000,
                            check_in_date="2026-06-01", check_out_date="2026-06-03")
    assert line["reimbursable_amount_cents"] == 40000
    assert line["in_policy"] is False


def test_report_total_excludes_meal_lines(api):
    """PRD §3.6: "The total is then meal_reimbursable_cents plus the sum of the
    reimbursable_amount_cents of every line that is neither rejected nor a meal line —
    that is, every line whose status is not REJECTED and whose line_type is not MEAL."

    Design: Corner/calculations/report_total_excludes_meal_lines
    """
    env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000, max_economy_fare_cents=50000)
    trip = create_approved_trip(env, budget_total_cents=100000,
                                start_date="2026-06-01", end_date="2026-06-03")
    report = create_report(env, trip, per_diem_method="PER_DIEM", title="Total Rpt")
    add_flight_line_with_receipt(env, report, claimed_amount_cents=30000,
                                 cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
    add_mileage_line(env, report, miles=100)  # 6700
    add_meal_line(env, report, claimed_amount_cents=5000)
    data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
    # meal per-diem (3 days, M&IE 8000) = 20000; total = 20000 + 30000 + 6700 = 56700
    assert data["meal_reimbursable_cents"] == 20000
    assert data["total_reimbursable_cents"] == 56700, (
        f"total = 20000 + 30000 + 6700 = 56700, got {data['total_reimbursable_cents']}"
    )


def test_business_class_short_flight_out_of_policy(api):
    """PRD §3.5: "When cabin_class is BUSINESS, the line is in-policy only if
    scheduled_hours is at least business_class_min_hours; a business cabin booked on a
    flight whose scheduled duration is below that minimum is out-of-policy, so in_policy
    is set to false. A business fare that clears the duration minimum is not capped —
    its cap equals the claimed amount itself."

    Design: Corner/calculations/business_class_short_flight_out_of_policy
    """
    env = setup_base_env(business_class_min_hours=6)
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="Biz Flight Rpt")
    # BUSINESS on 3-hour flight (< 6) -> out of policy; cap = claimed -> reimbursable 90000.
    line = add_flight_line(env, report, claimed_amount_cents=90000,
                           cabin_class="BUSINESS", scheduled_hours=3, advance_days=30)
    assert line["reimbursable_amount_cents"] == 90000
    assert line["in_policy"] is False
