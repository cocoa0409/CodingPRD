"""Read paths, filters and the clock-driven fiscal-year rollup."""
from test_helpers import SUPERVISOR_ALT_ID, analyst_headers, make_applicant_headers
from test_helpers import api_errors as errs  # noqa: F401  (shared error identifiers)
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx


def test_searching_cases_by_benefit_status_filters_server_side(api):
    """PRD §3.4: "Staff can also search cases with optional `household_id`,
    `application_id`, `benefit_status` and `compliance_status` filters."
    PRD §3.4: "The first successful issuance advances the case
    `PENDING_ISSUANCE → ACTIVE`; every subsequent issuance leaves it `ACTIVE`."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` indicates whether
    rows remain beyond the current window."

    Design: Corner/endpoints/case_search_filters_on_benefit_status_and_reports_total_count
    """
    issued = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Case Search Household A"},
        incomes=(),
    )
    pending = fx.build_approved_case(
        api,
        household_overrides={"head_of_household_name": "Corner Case Search Household B"},
        incomes=(),
        approver=SUPERVISOR_ALT_ID,
    )

    active_rows = asrt.assert_page(
        api.search_cases(analyst_headers(), params={"benefit_status": "ACTIVE"}),
        total_count=1,
        has_more=False,
        row_count=1,
    )

    assert active_rows[0]["id"] == issued.case_id
    asrt.assert_case_state(fx.read_case(api, issued.case_id), benefit_status="ACTIVE")
    asrt.assert_case_state(
        fx.read_case(api, pending.case_id), benefit_status="PENDING_ISSUANCE"
    )
    asrt.assert_page(api.search_cases(analyst_headers()), total_count=2)


def test_the_case_rollup_counts_only_the_fiscal_year_the_clock_is_in(api):
    """PRD §3.8: "Its `fiscal_year` is derived from `period_start` on the federal
    calendar: the federal fiscal year is the calendar year of the start date, except that
    a start date in October, November or December belongs to the *following* fiscal year."
    PRD §3.8: "On a successful authorization the case's `supportive_fy_authorized_cents`
    is recomputed as the total of `authorized_amount_cents` across the case's
    `AUTHORIZED` authorizations whose fiscal year matches the *current* federal fiscal
    year derived from the logical clock — note that this rollup tracks the current year,
    while the waterfall itself is evaluated against the candidate authorization's own
    fiscal year."
    PRD §2.5: "It advances only when an operator explicitly sets it through the
    test-driving capability mounted at `POST /_clock/set_current_utc`, which takes a
    `to_iso8601` instant and returns the new `current_utc`."

    Design: Corner/endpoints/advancing_the_clock_moves_the_current_fiscal_year_for_the_case_rollup
    """
    context = fx.build_active_case(
        api,
        household_overrides={
            "head_of_household_name": "Corner Clock Fiscal Year Household"
        },
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
    october = fx.build_authorized_service(
        api,
        context.case_id,
        assignment["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=25000,
        period_start="2026-10-01",
        period_end="2026-10-31",
    )
    asrt.assert_authorization(
        fx.read_authorization(api, october["id"]),
        status="AUTHORIZED",
        authorized_amount_cents=25000,
        fiscal_year=2027,
    )
    asrt.assert_money(
        fx.read_case(api, context.case_id)["supportive_fy_authorized_cents"],
        0,
        "rollup while the clock sits in the previous fiscal year",
    )

    moved = fx.set_clock(api, "2026-10-01T00:00:00Z")

    assert moved["current_utc"].startswith("2026-10-01T00:00:00")
    november = fx.build_authorized_service(
        api,
        context.case_id,
        assignment["id"],
        service_type="CHILD_CARE",
        requested_amount_cents=30000,
        period_start="2026-11-01",
        period_end="2026-11-30",
    )
    asrt.assert_authorization(
        fx.read_authorization(api, november["id"]),
        status="AUTHORIZED",
        authorized_amount_cents=30000,
        fiscal_year=2027,
    )
    asrt.assert_money(
        fx.read_case(api, context.case_id)["supportive_fy_authorized_cents"],
        55000,
        "rollup once the clock sits in the authorizations' fiscal year",
    )


def test_the_time_limit_ledger_exposes_both_clock_flags_row_by_row(api):
    """PRD §3.4: "The month-by-month ledger for a case can be listed with an optional
    `benefit_month` filter, and each row exposes both countability flags and its
    non-countable reason so the two clocks can be compared row by row."
    PRD §3.4: "Each issuance writes one **time-limit month** row, always with
    `assistance_issued` set to true, and that row is where the program's two lifetime
    clocks are evaluated."
    PRD §3.4: "`state_clock_months_used` is `prior_state_clock_months` plus the number of
    state-countable rows."

    Design: Corner/endpoints/time_limit_ledger_read_exposes_both_clock_flags_per_month
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Ledger Read Household"},
        incomes=(),
        benefit_months=("2026-08", "2026-09"),
    )

    rows = asrt.assert_page(
        api.list_time_limit_months(context.case_id, analyst_headers()),
        total_count=2,
        has_more=False,
        row_count=2,
    )

    for month in ("2026-08", "2026-09"):
        asrt.assert_time_limit_month(
            asrt.find_time_limit_month(rows, month),
            assistance_issued=True,
            state_clock_countable=True,
            federal_clock_countable=True,
            non_countable_reason="NONE",
        )
    asrt.assert_page(
        api.list_time_limit_months(
            context.case_id, analyst_headers(), params={"benefit_month": "2026-09"}
        ),
        total_count=1,
        row_count=1,
    )
    asrt.assert_household_clocks(
        fx.read_household(api, context.household_id),
        state_clock_months_used=2,
        federal_clock_months_used=2,
    )


def test_an_applicant_withdrawal_sweeps_its_own_open_diversion_offer(api):
    """PRD §3.3: "Withdrawal is available to the applicant itself and to a `Caseworker`,
    and is the only disposition reachable from more than one status: an application may be
    withdrawn while it is `RECEIVED`, `DETERMINED` or `DIVERSION_OFFERED`, and any other
    status is refused with `ERR_INVALID_APPLICATION_STATE`."
    PRD §3.3: "Withdrawal also cleans up any outstanding offer: every diversion grant of
    the application still sitting in `OFFERED` is moved to `DECLINED` as part of the same
    request."
    PRD §3.3: "The `lump_sum_cents` is three times the basis, capped at 200000 cents,
    taking whichever is smaller."

    Design: Corner/endpoints/applicant_withdraws_own_application_and_the_open_offer_is_declined
    """
    built = fx.build_determined_application(
        api,
        household_overrides={
            "head_of_household_name": "Corner Applicant Withdraw Household"
        },
        application_overrides={"requested_program": "DIVERSION_CONSIDERED"},
        incomes=(),
    )
    household_id = built["household"]["id"]
    application_id = built["application"]["id"]
    grant = fx.offer_diversion(api, application_id)
    assert grant["status"] == "OFFERED"

    response = api.withdraw_application(
        application_id,
        factories.withdraw_payload("Found employment"),
        make_applicant_headers(household_id),
    )

    asrt.assert_accepted(response)
    application = fx.read_application(api, application_id)
    assert application["status"] == "WITHDRAWN"
    asrt.assert_money(
        application["determined_benefit_cents"], 41650, "determined benefit"
    )
    stored = fx.read_diversion_grant(api, application_id, grant["id"])
    assert stored["status"] == "DECLINED"
    asrt.assert_money(stored["lump_sum_cents"], 124950, "lump sum")
    assert fx.read_household(api, household_id)["diversion_ineligible_through_month"] is None
