"""The two fee variants: rounding N times per report against once per season.

Covers the provisional per-report walk with its strictly-earlier cumulative
bracket, the aggregate split of a single season total, the half-up decision at an
exact half cent, the flat schedule that never consults the brackets, and the
minimum annual fee both variants share.
"""
from test_helpers import (
    ApiErrorId,
    accept_use_report,
    authorize_guide,
    create_qualified_guide,
    finalize_fee_assessment,
    read_permit,
    read_use_report,
    setup_issued_permit,
    sole_fee_assessment,
    trip_use_report_payload,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]

PERIODS = [
    ("2027-05-15", "2027-06-15"),
    ("2027-06-15", "2027-07-15"),
    ("2027-07-15", "2027-08-15"),
]


def _fee_permit(fee_schedule_code="GRADUATED"):
    """An ISSUED 200-day permit on the named fee schedule, with one authorized
    LEAD/WFR guide so eight client slots stand open, at clock 2027-09-01."""
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides={"fee_schedule_code": fee_schedule_code},
        clock="2027-09-01T00:00:00Z",
    )
    guide = create_qualified_guide(context["outfitter"]["id"])
    authorize_guide(context["permit"]["id"], guide["id"], context["outfitter"]["id"])
    assert read_permit(context["permit"]["id"])["fee_schedule_code"] == fee_schedule_code
    return context


def _file(context, slot, **overrides):
    start, end = PERIODS[slot]
    return validate_success(
        api_client.create_trip_use_report(
            context["permit"]["id"],
            trip_use_report_payload(
                period_start_date=start, period_end_date=end, **overrides
            ),
            context["holder_headers"],
        ),
        201,
    )


def _accept(context, slot, **overrides):
    report = _file(context, slot, **overrides)
    return accept_use_report(report["id"])


def test_the_same_three_reports_price_differently_before_and_after_finalization():
    """PRD §3.7: "It walks the ordered accepted set carrying a running cumulative adjusted gross
    revenue that starts at zero and, for each report, assigns `applied_rate_bp` from the bracket
    that the cumulative total of *strictly earlier* reports falls into — so a report is charged
    entirely at one rate, the rate its opening cumulative earned, even if the report itself
    carries the total past a ceiling."
    PRD §3.7: "It sets `fee_component_cents` to the report's `adjusted_gross_revenue_cents`
    multiplied by its `applied_rate_bp` and divided by 10000, rounded half-up to the cent; then it
    adds that report's adjusted gross revenue to the cumulative and moves on. The rate fee is the
    sum of the per-report `fee_component_cents`."
    PRD §3.7: "It sums the untouched `adjusted_gross_revenue_cents` over the ordered set into a
    season total, splits that single total across the three brackets — the portion up to 2500000
    cents, the portion between 2500000 and 10000000 cents, and the portion above 10000000 cents —
    multiplies each portion by its own rate, adds the three products, divides by 10000, and rounds
    half-up exactly once."
    PRD §3.7: "Finalization recomputes `reported_agr_cents` and `assessed_fee_cents` under the
    aggregate variant, sets `variant_applied` to `FINAL_AGGREGATE`, stamps `finalized_at`,
    recomputes `balance_due_cents`, `credit_balance_cents`, `minimum_fee_applied`, then the
    permit's `fee_delinquent` and `compliance_status`; the delta against the provisional figure
    appears as either a new balance or a new credit, and the assessment moves
    `PROVISIONAL → FINAL`."

    Design: Difficulty/dual_variant_calc/fee_assessment_provisional_per_report_versus_final_aggregate
    """
    context = _fee_permit()
    permit_id = context["permit"]["id"]

    first = _accept(
        context, 0, service_days_used=60,
        gross_revenue_cents=1_800_050, allowable_deductions_cents=200_000,
    )
    second = _accept(
        context, 1, service_days_used=60,
        gross_revenue_cents=1_500_000, allowable_deductions_cents=100_000,
    )
    third = _accept(
        context, 2, service_days_used=40,
        gross_revenue_cents=900_000, allowable_deductions_cents=0,
    )
    assert first["adjusted_gross_revenue_cents"] == 1_600_050
    assert second["adjusted_gross_revenue_cents"] == 1_400_000
    assert third["adjusted_gross_revenue_cents"] == 900_000

    provisional = sole_fee_assessment(permit_id)
    assert provisional["status"] == "PROVISIONAL"
    assert provisional["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert provisional["reported_agr_cents"] == 3_900_050
    assert provisional["assessed_fee_cents"] == 126_002
    assert provisional["minimum_fee_applied"] is False

    assert read_use_report(first["id"])["applied_rate_bp"] == 300
    assert read_use_report(first["id"])["fee_component_cents"] == 48_002, (
        "48001.5 rounds half up"
    )
    assert read_use_report(second["id"])["applied_rate_bp"] == 300, (
        "an opening cumulative of 1600050 still sits in the first bracket"
    )
    assert read_use_report(second["id"])["fee_component_cents"] == 42_000
    assert read_use_report(third["id"])["applied_rate_bp"] == 400, (
        "the third report opens on a cumulative of 3000050, past the 2500000 ceiling"
    )
    assert read_use_report(third["id"])["fee_component_cents"] == 36_000

    final = finalize_fee_assessment(provisional["id"])
    assert final["status"] == "FINAL"
    assert final["variant_applied"] == "FINAL_AGGREGATE"
    assert final["reported_agr_cents"] == 3_900_050
    assert final["assessed_fee_cents"] == 131_002, (
        "the aggregate splits 2500000 at 300 bp and 1400050 at 400 bp"
    )
    assert final["assessed_fee_cents"] - provisional["assessed_fee_cents"] == 5_000
    assert final["balance_due_cents"] == 131_002, (
        "balance_due_cents is assessed_fee_cents less paid_to_date_cents, and "
        "nothing has been paid"
    )
    assert final["paid_to_date_cents"] == 0
    assert final["credit_balance_cents"] == 0
    assert final["minimum_fee_applied"] is False
    assert final["finalized_at"] is not None
    assert read_permit(permit_id)["fee_delinquent"] is True


def test_both_variants_stop_at_the_minimum_annual_fee_and_finalization_is_gated():
    """PRD §3.7: "`minimum_fee_applied` is true exactly when the computed rate fee falls below the
    30000-cent minimum annual fee, and `assessed_fee_cents` is the greater of that minimum and the
    rate fee — the season's fee is never below the minimum."
    PRD §3.7: "Finalization is available to a `PermitSpecialist` or `ProgramAdministrator`. The
    assessment must be `PROVISIONAL`, and no report for that permit and season may remain
    `SUBMITTED`, else `ERR_USE_REPORTS_PENDING` — the season cannot be closed out while an
    unreviewed report could still change the basis."
    PRD §3.7: "Finalization recomputes `reported_agr_cents` and `assessed_fee_cents` under the
    aggregate variant, sets `variant_applied` to `FINAL_AGGREGATE`, stamps `finalized_at`,
    recomputes `balance_due_cents`, `credit_balance_cents`, `minimum_fee_applied`, then the
    permit's `fee_delinquent` and `compliance_status`; the delta against the provisional figure
    appears as either a new balance or a new credit, and the assessment moves
    `PROVISIONAL → FINAL`."
    PRD §3.7: "either creates the season's fee assessment in `PROVISIONAL` if none exists yet or
    recomputes the existing one"

    Design: Difficulty/dual_variant_calc/fee_assessment_provisional_per_report_versus_final_aggregate
    """
    context = _fee_permit()
    permit_id = context["permit"]["id"]

    _accept(context, 0, service_days_used=20, gross_revenue_cents=500_000)
    lean = sole_fee_assessment(permit_id)
    assert lean["reported_agr_cents"] == 500_000
    assert lean["assessed_fee_cents"] == 30_000, (
        "a 15000-cent rate fee is lifted to the 30000-cent minimum"
    )
    assert lean["minimum_fee_applied"] is True
    assert lean["balance_due_cents"] == 30_000

    pending = _file(context, 1, service_days_used=20, gross_revenue_cents=400_000)
    assert pending["status"] == "SUBMITTED"
    validate_error(
        api_client.finalize_fee_assessment(lean["id"], SPECIALIST),
        ApiErrorId.ERR_USE_REPORTS_PENDING,
    )
    still_provisional = sole_fee_assessment(permit_id)
    assert still_provisional["status"] == "PROVISIONAL"
    assert still_provisional["variant_applied"] == "PROVISIONAL_PER_REPORT"

    accept_use_report(pending["id"])
    recomputed = sole_fee_assessment(permit_id)
    assert recomputed["reported_agr_cents"] == 900_000, (
        "the second acceptance recomputes the existing assessment rather than creating another"
    )
    assert recomputed["assessed_fee_cents"] == 30_000
    assert recomputed["minimum_fee_applied"] is True

    final = finalize_fee_assessment(recomputed["id"])
    assert final["status"] == "FINAL"
    assert final["variant_applied"] == "FINAL_AGGREGATE"
    assert final["reported_agr_cents"] == 900_000
    assert final["assessed_fee_cents"] == 30_000, (
        "27000 under either variant, so both land on the minimum and agree"
    )
    assert final["minimum_fee_applied"] is True
    assert final["balance_due_cents"] == 30_000
    assert final["credit_balance_cents"] == 0


def test_an_exact_half_cent_rounds_up_in_every_report_and_once_in_the_season():
    """PRD §2.8: "There are no fractional cents anywhere: wherever a rate is applied to an amount,
    the product is rounded **half up** to a whole cent."
    PRD §3.7: "When `fee_schedule_code` is `FLAT_THREE_PERCENT`, a single 300-basis-point rate
    replaces the brackets entirely in both variants."
    PRD §3.7: "It sets `fee_component_cents` to the report's `adjusted_gross_revenue_cents`
    multiplied by its `applied_rate_bp` and divided by 10000, rounded half-up to the cent; then it
    adds that report's adjusted gross revenue to the cumulative and moves on. The rate fee is the
    sum of the per-report `fee_component_cents`."
    PRD §3.7: "Under the flat schedule it is the season total times 300 divided by 10000, rounded
    once."
    PRD §3.7: "the provisional variant rounds N times where the final variant rounds once"

    Design: Difficulty/combinatorial_formula/fee_component_round_half_up_at_exact_half
    """
    context = _fee_permit("FLAT_THREE_PERCENT")
    permit_id = context["permit"]["id"]

    first = _accept(
        context, 0, service_days_used=60,
        gross_revenue_cents=1_633_350, allowable_deductions_cents=100_000,
    )
    second = _accept(
        context, 1, service_days_used=60,
        gross_revenue_cents=1_633_350, allowable_deductions_cents=100_000,
    )
    assert first["adjusted_gross_revenue_cents"] == 1_533_350
    assert second["adjusted_gross_revenue_cents"] == 1_533_350

    for report in (first, second):
        row = read_use_report(report["id"])
        assert row["applied_rate_bp"] == 300, (
            "the flat schedule pins 300 bp and never consults the graduated brackets"
        )
        assert row["fee_component_cents"] == 46_001, (
            "1533350 * 300 / 10000 is exactly 46000.5, and half up is 46001"
        )

    provisional = sole_fee_assessment(permit_id)
    assert provisional["variant_applied"] == "PROVISIONAL_PER_REPORT"
    assert provisional["assessed_fee_cents"] == 92_002
    assert provisional["minimum_fee_applied"] is False

    final = finalize_fee_assessment(provisional["id"])
    assert final["variant_applied"] == "FINAL_AGGREGATE"
    assert final["reported_agr_cents"] == 3_066_700
    assert final["assessed_fee_cents"] == 92_001, (
        "3066700 * 300 / 10000 is exactly 92001, with no fraction to round"
    )
    assert provisional["assessed_fee_cents"] - final["assessed_fee_cents"] == 1, (
        "the whole difference is rounding order: identical rate, identical revenue"
    )
    assert final["balance_due_cents"] == 92_001
    assert final["paid_to_date_cents"] == 0
    assert final["credit_balance_cents"] == 0


def test_three_half_cent_reports_round_three_times_and_the_season_rounds_once():
    """PRD §2.8: "There are no fractional cents anywhere: wherever a rate is applied to an amount,
    the product is rounded **half up** to a whole cent."
    PRD §3.7: "When `fee_schedule_code` is `FLAT_THREE_PERCENT`, a single 300-basis-point rate
    replaces the brackets entirely in both variants."
    PRD §3.7: "The rate fee is the sum of the per-report `fee_component_cents`."
    PRD §3.7: "Under the flat schedule it is the season total times 300 divided by 10000, rounded
    once."
    PRD §3.7: "The two variants therefore disagree on identical inputs, by design and in two
    independent ways: the provisional variant rounds N times where the final variant rounds once"

    Design: Difficulty/combinatorial_formula/fee_component_round_half_up_at_exact_half
    """
    context = _fee_permit("FLAT_THREE_PERCENT")
    permit_id = context["permit"]["id"]

    reports = [
        _accept(
            context, slot, service_days_used=60,
            gross_revenue_cents=1_633_350, allowable_deductions_cents=100_000,
        )
        for slot in (0, 1, 2)
    ]
    for report in reports:
        row = read_use_report(report["id"])
        assert row["adjusted_gross_revenue_cents"] == 1_533_350
        assert row["fee_component_cents"] == 46_001

    provisional = sole_fee_assessment(permit_id)
    assert provisional["reported_agr_cents"] == 4_600_050
    assert provisional["assessed_fee_cents"] == 138_003, (
        "three half-cent products rounded up three times"
    )

    final = finalize_fee_assessment(provisional["id"])
    assert final["reported_agr_cents"] == 4_600_050
    assert final["assessed_fee_cents"] == 138_002, (
        "4600050 * 300 / 10000 is 138001.5, rounded up exactly once"
    )
    assert provisional["assessed_fee_cents"] - final["assessed_fee_cents"] == 1
    assert final["balance_due_cents"] == 138_002
    assert read_permit(permit_id)["service_days_used_ytd"] == 180
