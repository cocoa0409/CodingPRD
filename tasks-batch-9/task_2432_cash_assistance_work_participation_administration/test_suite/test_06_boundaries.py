"""Values sitting exactly on a published threshold and one unit off it."""
from test_helpers import supervisor_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx

EARNED_ONLY = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)


def _case_with_forty_non_core_hours_and_a_pending_core_report(api, name, core_hours):
    """Non-core hours already credited, with a core month still awaiting verification."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=EARNED_ONLY,
    )
    core = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    non_core = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="JOB_SKILLS_TRAINING_DIRECT",
        scheduled_weekly_hours=10,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    fx.credit_hours(api, non_core["id"], "2026-08", 40)
    report = fx.file_report(
        api,
        core["id"],
        report_month="2026-08",
        reported_hours=core_hours,
        verification_source="TIMESHEET",
    )
    return context, core["id"], report["id"]


def test_core_hours_exactly_at_the_threshold_make_non_core_hours_countable(api):
    """PRD §3.6: "First, if the core total is at least the case's
    `required_core_monthly_hours`, the non-core total is countable; otherwise the
    countable non-core figure is zero."
    PRD §3.6: "Both comparisons are inclusive, so hitting the requirement exactly
    counts as meeting it."

    Design: Difficulty/boundary_precision_check/core_hours_threshold_at_and_one_below_forfeits_all_non_core_hours
    """
    context, core_id, report_id = _case_with_forty_non_core_hours_and_a_pending_core_report(
        api, "Boundary Case X Household", 80
    )
    case = fx.read_case(api, context.case_id)
    assert case["required_core_monthly_hours"] == 80
    assert case["required_monthly_hours"] == 120

    fx.verify_report(api, report_id, 80)

    asrt.assert_report_credits(
        fx.read_report(api, core_id, report_id),
        status="VERIFIED",
        verified_hours=80,
        core_hours_credited=80,
        non_core_hours_credited=0,
    )
    assignment = fx.read_assignment(api, core_id)
    assert assignment["cumulative_verified_hours"] == 80
    assert assignment["compliance_flag"] == "NONE"


def test_one_core_hour_short_forfeits_every_non_core_hour(api):
    """PRD §3.6: "Non-core hours are forfeited *entirely*, not proportionally, when
    the core threshold is missed — a `SINGLE_PARENT` case needing 80 core hours and
    120 total hours that credits 79 core hours and 60 non-core hours has 79 countable
    hours for the month, not 139."
    PRD §3.6: "The predicate drives the assignment's `compliance_flag`, which becomes
    `SHORTFALL` when the predicate is false for the reported month and `NONE` when it
    is true."

    Design: Difficulty/boundary_precision_check/core_hours_threshold_at_and_one_below_forfeits_all_non_core_hours
    """
    _context, core_id, report_id = _case_with_forty_non_core_hours_and_a_pending_core_report(
        api, "Boundary Case Y Household", 79
    )

    fx.verify_report(api, report_id, 79)

    asrt.assert_report_credits(
        fx.read_report(api, core_id, report_id),
        status="VERIFIED",
        verified_hours=79,
        core_hours_credited=79,
        non_core_hours_credited=0,
    )
    assignment = fx.read_assignment(api, core_id)
    assert assignment["cumulative_verified_hours"] == 79
    assert assignment["compliance_flag"] == "SHORTFALL"


def _empty_quarter_period(api):
    """A quarter with no cases at all and a zero comparison-year caseload."""
    return fx.open_period(
        api,
        fiscal_year=2027,
        quarter=1,
        prior_year_caseload=0.00,
        eligibility_change_caseload_effect=0.00,
    )


def test_quarter_with_no_issued_months_reports_zero_rates(api):
    """PRD §3.10: "A quarter with no issued months at all is well defined rather
    than an error: both rates come out 0.00, `current_caseload` comes out 0.00, the
    raw decline comes out 100.00 whenever the prior-year caseload is positive, and
    `target_met` is still evaluated with the same inclusive comparison against the
    adjusted target."
    PRD §3.10: "When the denominator is zero, `wpr_all_families_pct` is 0.00;
    otherwise it is the numerator divided by the denominator, expressed as a
    percentage, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/empty_quarter_reporting_period_yields_zero_rates_and_full_statutory_target
    """
    period = _empty_quarter_period(api)

    fx.calculate_period(api, period["id"])

    calculated = fx.read_period(api, period["id"])
    assert calculated["status"] == "CALCULATED"
    asrt.assert_pct(calculated["current_caseload"], 0.00, "current_caseload")
    asrt.assert_pct(calculated["wpr_all_families_pct"], 0.00, "wpr_all_families_pct")
    asrt.assert_pct(calculated["wpr_two_parent_pct"], 0.00, "wpr_two_parent_pct")


def test_zero_comparison_caseload_leaves_the_full_statutory_target_in_place(api):
    """PRD §3.10: "The raw decline is 0.00 when `prior_year_caseload` is zero;
    otherwise it is the prior-year caseload less the current caseload, divided by the
    prior-year caseload, expressed as a percentage and rounded half up to two decimal
    places."
    PRD §3.10: "The `adjusted_target_all_families_pct` is the statutory all-families
    target of 50.00 percent less the credit, floored at 0.00."

    Design: Difficulty/boundary_precision_check/empty_quarter_reporting_period_yields_zero_rates_and_full_statutory_target
    """
    period = _empty_quarter_period(api)

    fx.calculate_period(api, period["id"])

    calculated = fx.read_period(api, period["id"])
    asrt.assert_pct(
        calculated["caseload_reduction_credit_pct"], 0.00, "caseload_reduction_credit_pct"
    )
    asrt.assert_pct(
        calculated["adjusted_target_all_families_pct"],
        50.00,
        "adjusted_target_all_families_pct",
    )
    assert calculated["target_met"] is False


def _determined_application_with_unearned_income(api, name, unearned_cents):
    built = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=(
            {
                "source_type": "UNEARNED_UI",
                "gross_monthly_cents": unearned_cents,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
        ),
    )
    return built["application"]["id"]


def test_grant_of_exactly_the_minimum_issuance_floor_is_payable(api):
    """PRD §3.2: "Step six applies the minimum-issuance floor: if the post-sanction
    figure is below 1000 cents the grant is zero, and otherwise the grant is the
    post-sanction figure."
    PRD §3.2: "The floor is inclusive at its boundary — a post-sanction figure of
    exactly 1000 cents is payable."

    Design: Difficulty/boundary_precision_check/minimum_issuance_floor_at_exactly_one_thousand_cents_versus_one_cent_below
    """
    application_id = _determined_application_with_unearned_income(
        api, "Minimum Issuance P Household", 47824
    )
    application = fx.read_application(api, application_id)
    asrt.assert_money(application["countable_income_cents"], 47824, "countable income")
    asrt.assert_money(application["determined_benefit_cents"], 1000, "determined benefit")

    case = fx.approve(api, application_id)

    asrt.assert_case_state(
        fx.read_case(api, case["id"]),
        benefit_status="PENDING_ISSUANCE",
        benefit_amount_cents=1000,
    )


def test_grant_one_cent_under_the_floor_is_refused_as_ineligible(api):
    """PRD §3.3: "Finally the application's `determined_benefit_cents` must be
    greater than zero, or the request is refused with `ERR_INELIGIBLE_ZERO_BENEFIT`,
    which is what happens when countable income has consumed the ratably reduced
    standard entirely or when the surviving grant fell under the 1000-cent
    minimum-issuance floor."
    PRD §3.2: "Step three applies the ratable reduction, multiplying the deficit by
    0.85 and rounding half up to a whole cent."

    Design: Difficulty/boundary_precision_check/minimum_issuance_floor_at_exactly_one_thousand_cents_versus_one_cent_below
    """
    application_id = _determined_application_with_unearned_income(
        api, "Minimum Issuance Q Household", 47825
    )
    application = fx.read_application(api, application_id)
    asrt.assert_money(application["countable_income_cents"], 47825, "countable income")
    asrt.assert_money(application["determined_benefit_cents"], 0, "determined benefit")

    response = api.approve_application(
        application_id, factories.approve_payload("2026-08"), supervisor_headers()
    )

    asrt.assert_rejected(response, errs.ERR_INELIGIBLE_ZERO_BENEFIT)
    assert fx.read_application(api, application_id)["status"] == "DETERMINED"


def _determined_application_with_one_liquid_asset(api, name, asset_cents):
    built = fx.build_determined_application(
        api,
        household_overrides={
            "head_of_household_name": name,
            "youngest_child_age_months": 72,
        },
        incomes=EARNED_ONLY,
        resources=(
            {
                "item_type": "LIQUID_ASSET",
                "gross_value_cents": asset_cents,
                "encumbrance_cents": 0,
                "exclusion_type": "NONE",
            },
        ),
    )
    return built["household"]["id"], built["application"]["id"]


def test_resources_exactly_at_the_limit_approve_and_a_child_of_seventy_two_months_is_not_under_six(
    api,
):
    """PRD §3.1: "The under-six exemption uses a strict comparison, so a youngest
    child recorded at exactly 72 months yields `SINGLE_PARENT`, not
    `SINGLE_PARENT_CHILD_UNDER_6`."
    PRD §3.3: "Weekly total hours are 0 for `CHILD_ONLY`, 20 for
    `SINGLE_PARENT_CHILD_UNDER_6`, 30 for `SINGLE_PARENT`, 35 for
    `TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE` and 55 for
    `TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE`; those figures land in
    `required_weekly_hours`."
    PRD §3.3: "The two monthly figures are the weekly figures scaled by a reporting
    month of four weeks: `required_monthly_hours` is four times the weekly total and
    `required_core_monthly_hours` is four times the weekly core figure."

    Design: Difficulty/boundary_precision_check/resource_limit_at_exactly_two_hundred_thousand_and_child_age_at_exactly_seventy_two_months
    """
    household_id, application_id = _determined_application_with_one_liquid_asset(
        api, "Resource At Limit Household", 200000
    )
    assert fx.read_household(api, household_id)["family_type"] == "SINGLE_PARENT"
    application = fx.read_application(api, application_id)
    asrt.assert_money(
        application["countable_resources_cents"], 200000, "countable resources"
    )

    case = fx.approve(api, application_id)

    stored = fx.read_case(api, case["id"])
    assert stored["required_weekly_hours"] == 30
    assert stored["required_core_weekly_hours"] == 20
    assert stored["required_monthly_hours"] == 120
    assert stored["required_core_monthly_hours"] == 80


def test_one_cent_over_the_resource_limit_is_refused(api):
    """PRD §3.3: "The application's `countable_resources_cents` must not exceed the
    program resource limit of 200000 cents — exactly at the limit is eligible, and
    strictly above it is refused with `ERR_RESOURCE_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/resource_limit_at_exactly_two_hundred_thousand_and_child_age_at_exactly_seventy_two_months
    """
    _household_id, application_id = _determined_application_with_one_liquid_asset(
        api, "Resource Over Limit Household", 200001
    )

    response = api.approve_application(
        application_id, factories.approve_payload("2026-08"), supervisor_headers()
    )

    asrt.assert_rejected(response, errs.ERR_RESOURCE_LIMIT_EXCEEDED)
    application = fx.read_application(api, application_id)
    assert application["status"] == "DETERMINED"
    asrt.assert_money(
        application["countable_resources_cents"], 200001, "countable resources"
    )
