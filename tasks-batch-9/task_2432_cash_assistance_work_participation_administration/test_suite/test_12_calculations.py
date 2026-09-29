"""Arithmetic paths: discount factors, filtered input sets and table extension."""
from test_helpers import caseworker_headers
from test_helpers import assertions as asrt
from test_helpers import fixtures as fx


def test_self_reported_hours_are_halved_and_then_floored_to_a_whole_hour(api):
    """PRD §3.6: "A report whose `verification_source` is `SELF_REPORT` is credited at
    half its accepted figure; every other documentation type is credited in full."
    PRD §3.6: "The credited figure is the accepted figure multiplied by that factor and
    then floored to a whole hour, so 45 self-reported hours credit 22 and not 23."
    PRD §3.6: "The assignment's rollup follows immediately: `cumulative_verified_hours`
    becomes the total of `verified_hours` across that assignment's `VERIFIED` reports."
    PRD §3.6: "The predicate drives the assignment's `compliance_flag`, which becomes
    `SHORTFALL` when the predicate is false for the reported month and `NONE` when it is
    true."

    Design: Corner/calculations/self_report_verification_source_halves_credited_hours_with_a_floor
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Self Report Household"},
        incomes=(),
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    report = fx.file_report(
        api,
        assignment["id"],
        report_month="2026-08",
        reported_hours=41,
        verification_source="SELF_REPORT",
    )

    fx.verify_report(api, report["id"], 41)

    asrt.assert_report_credits(
        fx.read_report(api, assignment["id"], report["id"]),
        status="VERIFIED",
        verified_hours=20,
        core_hours_credited=20,
        non_core_hours_credited=0,
    )
    stored = fx.read_assignment(api, assignment["id"])
    assert stored["cumulative_verified_hours"] == 20
    assert stored["compliance_flag"] == "SHORTFALL"


def test_prospective_budgeting_drops_an_unverified_recurring_source_entirely(api):
    """PRD §3.2: "Under `PROSPECTIVE` budgeting, only income sources whose
    `verification_status` is `VERIFIED` **and** whose `is_recurring` flag is true
    participate, and each participating source contributes its `gross_monthly_cents`
    unchanged."
    PRD §3.2: "Gross earned income is first reduced by a flat earned-income disregard of
    12000 cents, floored at zero."
    PRD §3.2: "Half of whatever earned income survives that flat disregard is countable,
    rounded half up to a whole number of cents."
    PRD §3.2: "Income sources of one application can be listed with optional
    `source_type` and `verification_status` filters."

    Design: Corner/calculations/unverified_recurring_income_is_excluded_from_prospective_budgeting
    """
    built = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": "Corner Filtering Household"},
        application_overrides={"budgeting_method": "PROSPECTIVE"},
        incomes=(
            {
                "source_type": "EARNED",
                "gross_monthly_cents": 40000,
                "month_1_cents": 40000,
                "month_2_cents": 40000,
                "month_3_cents": 40000,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
            {
                "source_type": "EARNED",
                "gross_monthly_cents": 30000,
                "month_1_cents": 30000,
                "month_2_cents": 30000,
                "month_3_cents": 30000,
                "is_recurring": True,
            },
        ),
    )
    application = built["application"]

    asrt.assert_money(application["countable_income_cents"], 14000, "countable income")
    asrt.assert_money(
        application["determined_benefit_cents"], 29750, "determined benefit"
    )
    assert application["status"] == "DETERMINED"
    unverified = asrt.find_by_id(
        asrt.assert_page(
            api.list_income_sources(application["id"], caseworker_headers())
        ),
        built["income_source_ids"][1],
    )
    assert unverified["verification_status"] == "UNVERIFIED"
    asrt.assert_page(
        api.list_income_sources(
            application["id"],
            caseworker_headers(),
            params={"verification_status": "VERIFIED"},
        ),
        total_count=1,
        row_count=1,
    )


def test_a_household_of_eight_extends_the_standard_by_the_additional_person_amount(api):
    """PRD §3.2: "Step one establishes the **payment standard** for the household size:
    26000 cents for a unit of one, 39000 for two, 49000 for three, 59000 for four, 68000
    for five and 76000 for six; for a unit larger than six, the standard is the
    six-person figure of 76000 cents plus 7000 cents for each person beyond the sixth."
    PRD §3.2: "Step three applies the ratable reduction, multiplying the deficit by 0.85
    and rounding half up to a whole cent."
    PRD §3.2: "Step four caps that pre-sanction figure at a maximum grant of 90000
    cents, taking whichever is smaller."

    Design: Corner/calculations/payment_standard_extends_by_the_additional_person_amount_above_size_six
    """
    built = fx.build_determined_application(
        api,
        household_overrides={
            "head_of_household_name": "Corner Large Household",
            "household_size": 8,
            "adult_count": 1,
            "youngest_child_age_months": 84,
        },
        application_overrides={"budgeting_method": "PROSPECTIVE"},
        incomes=(),
    )

    application = built["application"]

    asrt.assert_money(application["countable_income_cents"], 0, "countable income")
    asrt.assert_money(
        application["determined_benefit_cents"], 76500, "determined benefit"
    )
    assert application["snapshot_family_type"] == "SINGLE_PARENT"


def test_a_child_only_case_owes_no_hours_and_burns_neither_clock(api):
    """PRD §3.1: "First, a unit with an adult count of zero is `CHILD_ONLY`."
    PRD §3.3: "A `CHILD_ONLY` case therefore carries zero in all four and sits in
    `NOT_REQUIRED`."
    PRD §3.4: "For the **state clock**, which is the 24-month limit, a month counts when
    assistance was issued, **and** the case's frozen `family_type` is anything other
    than `CHILD_ONLY`, **and** no `GRANTED` hardship extension of that case covers the
    benefit month — where "covers" means the benefit month falls at or after the
    extension's `first_effective_month` and at or before its `last_effective_month`."
    PRD §3.4: "For the **federal clock**, which is the 60-month limit, a month counts
    when assistance was issued **and** the case's frozen `family_type` is anything other
    than `CHILD_ONLY`."

    Design: Corner/calculations/child_only_case_requires_no_hours_and_consumes_no_clock_months
    """
    built = fx.build_determined_application(
        api,
        household_overrides={
            "head_of_household_name": "Corner Child Only Household",
            "household_size": 3,
            "adult_count": 0,
            "youngest_child_age_months": 60,
        },
        application_overrides={"budgeting_method": "PROSPECTIVE"},
        incomes=(),
    )
    household_id = built["household"]["id"]
    assert fx.read_household(api, household_id)["family_type"] == "CHILD_ONLY"
    case = fx.approve(api, built["application"]["id"])

    fx.issue_month(api, case["id"], "2026-08")

    stored = fx.read_case(api, case["id"])
    asrt.assert_case_state(
        stored,
        benefit_status="ACTIVE",
        compliance_status="NOT_REQUIRED",
        benefit_amount_cents=41650,
    )
    assert stored["required_weekly_hours"] == 0
    assert stored["required_core_weekly_hours"] == 0
    assert stored["required_monthly_hours"] == 0
    assert stored["required_core_monthly_hours"] == 0
    rows = fx.list_time_limit_months(api, case["id"])
    asrt.assert_time_limit_month(
        asrt.find_time_limit_month(rows, "2026-08"),
        assistance_issued=True,
        state_clock_countable=False,
        federal_clock_countable=False,
        non_countable_reason="CHILD_ONLY_CASE",
    )
    asrt.assert_household_clocks(
        fx.read_household(api, household_id),
        state_clock_months_used=0,
        federal_clock_months_used=0,
        issued_countable_months=0,
    )
