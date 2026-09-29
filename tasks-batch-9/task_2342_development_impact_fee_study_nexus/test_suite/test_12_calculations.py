"""The arithmetic the statute pins by example: the two cost readings, the
half-cent rounding of a schedule line, the credit that counts, the half-open
fiscal year, and the first-in first-out order the fund is consumed in."""

from test_helpers import FINANCE_1, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, validate_error
from test_helpers import validate_paginated, validate_success
from test_helpers.fixtures import ADMIN, ANALYST, FINANCE

SECOND_PAYMENT_INSTANT = "2026-07-01T00:00:00Z"
PARKS_DEADLINE = "2031-05-10T00:00:00Z"


def test_the_roads_allocation_reproduces_the_documented_cost_per_demand_unit(api):
    """Multiply `planned_facility_cost_cents` by `planned_growth_share_bp` divided
    by ten thousand and round that product half up to whole cents; subtract
    `planned_other_funding_cents` from it to get the net growth cost. Divide that
    net growth cost by the smaller of `growth_demand_units` and
    `planned_capacity_demand_units`, and round the quotient half up to whole cents.
    Multiply the facility category's `unit_cost_cents` by the applicable level of
    service and round half up to whole cents. Proportionality evidence is stored
    alongside the price as `nexus_ratio`: `planned_capacity_demand_units` divided
    by `growth_demand_units`, rounded half up to four decimal places, and null when
    `growth_demand_units` is zero. A successful allocation stamps `allocated_at`
    from the logical clock, sets `allocation_status` to `VALID`, and increments the
    component's `version`.

    Design: Corner/calculations/roads_allocation_produces_the_documented_cost_per_unit
    """
    chain = fixtures.program_with_categories(api)
    study = fixtures.create_study(api, chain.program_id)
    component = fixtures.create_roads_component(api, study["id"], chain.roads_category_id)

    allocated = validate_success(api.allocate_nexus_component(component["id"], ANALYST))

    check.assert_four_decimal_equals(
        allocated["growth_demand_units"], K.ROADS_GROWTH_DEMAND_UNITS, "growth_demand_units"
    )
    check.assert_money_equals(
        allocated["plan_based_cost_per_unit_cents"],
        K.ROADS_PLAN_BASED_COST_PER_UNIT,
        "plan_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        allocated["standard_based_cost_per_unit_cents"],
        K.ROADS_STANDARD_BASED_COST_PER_UNIT,
        "standard_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        allocated["adopted_cost_per_unit_cents"],
        K.ROADS_ADOPTED_COST_PER_UNIT,
        "adopted_cost_per_unit_cents",
    )
    check.assert_four_decimal_equals(
        allocated["nexus_ratio"], K.ROADS_NEXUS_RATIO, "nexus_ratio"
    )
    assert allocated["allocation_status"] == K.ALLOCATION_VALID
    check.assert_timestamp_equals(
        allocated["allocated_at"], K.CLOCK_PROGRAM_SETUP, "allocated_at"
    )


def test_the_planned_standard_policy_prices_the_higher_level_of_service(api):
    """Which standard is applicable is decided by the program's `los_policy`: under
    `EXISTING_DEFICIENCY_EXCLUDED` it is `existing_los_per_demand_unit`, and under
    `PLANNED_STANDARD_ALLOWED` it is the greater of `existing_los_per_demand_unit`
    and `planned_los_per_demand_unit`. A category with a unit cost of 45,000,000
    cents, an existing standard of 0.0030 and a planned standard of 0.0040
    therefore prices at 135,000 cents under the default policy and at 180,000 cents
    once the planned standard is allowed; where the planned standard sits below the
    existing one — 0.0006 against 0.0008 — taking the greater of the two keeps the
    existing standard and the policy flag changes nothing. `adopted_cost_per_unit_cents`
    is then the study's chosen reading less the existing-tax credit, floored at
    zero: take `plan_based_cost_per_unit_cents` when the study's `methodology` is
    `PLAN_BASED` and `standard_based_cost_per_unit_cents` when it is
    `STANDARD_BASED`, subtract `existing_tax_credit_per_unit_cents`, and use zero
    instead if the subtraction would go negative.

    Design: Corner/calculations/planned_standard_allowed_prices_the_higher_level_of_service
    """
    chain = fixtures.program_with_categories(
        api,
        program_payload=factories.fee_program_payload(
            los_policy=K.LOS_POLICY_PLANNED_STANDARD_ALLOWED
        ),
        with_roads=False,
    )
    study = fixtures.create_study(
        api, chain.program_id, methodology=K.METHODOLOGY_STANDARD_BASED
    )
    component = fixtures.create_parks_component(api, study["id"], chain.parks_category_id)

    allocated = fixtures.allocate(api, component["id"])

    check.assert_four_decimal_equals(
        allocated["growth_demand_units"], K.PARKS_GROWTH_DEMAND_UNITS, "growth_demand_units"
    )
    check.assert_money_equals(
        allocated["standard_based_cost_per_unit_cents"],
        K.PARKS_STANDARD_BASED_PLANNED_LOS_COST_PER_UNIT,
        "standard_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        allocated["plan_based_cost_per_unit_cents"],
        K.PARKS_PLAN_BASED_COST_PER_UNIT,
        "plan_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        allocated["adopted_cost_per_unit_cents"], 165000, "adopted_cost_per_unit_cents"
    )
    check.assert_four_decimal_equals(
        allocated["nexus_ratio"], K.PARKS_NEXUS_RATIO, "nexus_ratio"
    )
    assert allocated["allocation_status"] == K.ALLOCATION_VALID


def test_a_schedule_line_rounds_the_half_cent_upward(api):
    """The line's `fee_per_unit_cents` is the component's
    `adopted_cost_per_unit_cents` multiplied by the `conversion_factor`, rounded
    half up to whole cents, and rounded exactly once. A parks component adopting
    101,667 cents per demand unit with a single-family conversion factor of 2.5000
    stores 254,168 cents per dwelling — the unrounded 254,167.5 rounds up — and
    with a multi-family factor of 1.8000 stores 183,001 cents. Lines are adopted
    only while the parent study is `DRAFT`, otherwise `ERR_STUDY_INVALID_STATE`,
    and a line can only be created while its component's `allocation_status` is
    `VALID` — which is why a schedule line is always born with `schedule_status`
    `VALID`, mirroring its parent component's allocation state for that land use.

    Design: Corner/calculations/schedule_line_fees_round_half_up_at_the_half_cent
    """
    chain = fixtures.program_with_categories(api, with_roads=False)
    study = fixtures.create_study(api, chain.program_id)
    component = fixtures.create_parks_component(api, study["id"], chain.parks_category_id)
    allocated = fixtures.allocate(api, component["id"])
    check.assert_money_equals(
        allocated["adopted_cost_per_unit_cents"],
        K.PARKS_ADOPTED_COST_PER_UNIT,
        "adopted_cost_per_unit_cents",
    )

    single_family = validate_success(
        api.create_fee_schedule_item(
            component["id"],
            factories.schedule_item_payload(
                land_use_category=K.LAND_USE_SINGLE_FAMILY, conversion_factor=2.5
            ),
            ANALYST,
        ),
        201,
    )
    multi_family = validate_success(
        api.create_fee_schedule_item(
            component["id"],
            factories.schedule_item_payload(
                land_use_category=K.LAND_USE_MULTI_FAMILY, conversion_factor=1.5
            ),
            ANALYST,
        ),
        201,
    )

    check.assert_money_equals(
        single_family["fee_per_unit_cents"],
        K.PARKS_SINGLE_FAMILY_FEE_PER_UNIT,
        "fee_per_unit_cents",
    )
    check.assert_money_equals(multi_family["fee_per_unit_cents"], 152501, "fee_per_unit_cents")
    assert single_family["schedule_status"] == K.SCHEDULE_VALID
    assert multi_family["schedule_status"] == K.SCHEDULE_VALID
    parent = get_success_data(api.get_nexus_component(component["id"], ADMIN))
    assert parent["allocation_status"] == K.ALLOCATION_VALID
    lines, meta = validate_paginated(api.list_fee_schedule_items(component["id"], ADMIN))
    check.assert_pagination_meta(meta, total_count=2)
    assert len(lines) == 2


def test_a_denied_and_an_undecided_claim_both_price_as_no_credit(api):
    """For each line, sum the `approved_cents` of every credit claim on this
    application whose `facility_category_code` matches the line's facility category
    `code` and whose `status` is `APPROVED_FULL` or `APPROVED_PARTIAL`. Claims that
    are still `SUBMITTED`, and claims that were `DENIED`, contribute nothing.

    Design: Corner/calculations/only_approved_credits_enter_the_assessment
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    denied_claim = fixtures.file_credit_claim(
        api,
        chain.application_id,
        facility_category_code=K.PARKS_CODE,
        credit_type=K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        valuation_method=K.VALUATION_NOMINAL,
        improvement_value_cents=1000000,
        annual_tax_contribution_cents=0,
        contribution_years=0,
    )
    fixtures.decide_credit_claim(
        api, denied_claim["id"], chain.application_id, K.DECISION_DENY
    )
    pending_claim = fixtures.file_credit_claim(
        api,
        chain.application_id,
        facility_category_code=K.ROADS_CODE,
        credit_type=K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        valuation_method=K.VALUATION_NOMINAL,
        improvement_value_cents=800000,
        annual_tax_contribution_cents=0,
        contribution_years=0,
    )

    reassessed = fixtures.assess(api, chain.application_id)

    assert reassessed["assessment_status"] == K.ASSESSMENT_REASSESSED
    check.assert_application_totals(
        reassessed,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        credit_applied_cents=0,
        admin_charge_cents=K.BASELINE_ADMIN_CHARGE,
        net_due_cents=K.BASELINE_NET_DUE,
    )
    parks_line = check.line_for_code(reassessed["assessed_lines"], K.PARKS_CODE)
    roads_line = check.line_for_code(reassessed["assessed_lines"], K.ROADS_CODE)
    check.assert_line_codes_ascending(reassessed["assessed_lines"])
    check.assert_assessed_line(
        parks_line, line_credit_cents=0, line_net_cents=K.BASELINE_PARKS_LINE_NET
    )
    check.assert_assessed_line(
        roads_line, line_credit_cents=0, line_net_cents=K.BASELINE_ROADS_LINE_NET
    )
    claims = get_success_data(api.list_credit_claims(chain.application_id, ADMIN))
    still_pending = [row for row in claims if row["id"] == pending_claim["id"]][0]
    assert still_pending["status"] == K.CLAIM_SUBMITTED, "a re-assessment decides nothing"


def _two_payments_straddling_the_fiscal_boundary(api):
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    fixtures.paid_application(api, chain)
    second = fixtures.file_application(api, chain.program_id, permit_number="BP-1002")
    fixtures.set_clock(api, SECOND_PAYMENT_INSTANT)
    fixtures.assess(api, second["id"])
    fixtures.pay(api, second["id"], K.BASELINE_NET_DUE)
    return chain


def test_the_fiscal_year_window_excludes_its_own_closing_instant(api):
    """A fiscal year is a half-open window: `window_start` is the first instant of
    the program's `fiscal_year_start_month` in the requested `fiscal_year`, and
    `window_end` is exactly one year later and is exclusive. An entry stamped
    precisely at `window_start` is inside the year; an entry stamped precisely at
    `window_end` belongs to the next one. `collections_cents` sums `amount_cents`
    over `COLLECTION` rows whose `vintage_at` falls inside the window. The
    remaining three are cumulative, not windowed, because the statutory disclosure
    is the balance at the close of the year including money collected in earlier
    years: `unexpended_cents` sums `unexpended_cents` over every `COLLECTION` row
    whose `vintage_at` is before `window_end`, `refund_obligation_cents` sums
    `unexpended_cents` over those same rows restricted to `entry_status`
    `REFUND_DUE`, and `earliest_deadline_at` is the earliest `deadline_at` among
    those same rows restricted to `entry_status` `OPEN` or `PARTIALLY_EXPENDED`.
    The read exposes `fiscal_year`, `window_start`, `window_end`, the six
    program-level figures, the `categories` array, `filed_late` and
    `report_status`, where `report_status` reads `UNFILED` until the year has
    actually been filed.

    Design: Corner/calculations/annual_report_window_is_half_open_at_the_fiscal_year_boundary
    """
    chain = _two_payments_straddling_the_fiscal_boundary(api)

    closed_year = validate_success(
        api.get_annual_report(chain.program_id, FINANCE, {"fiscal_year": 2025})
    )
    open_year = validate_success(
        api.get_annual_report(chain.program_id, FINANCE, {"fiscal_year": 2026})
    )

    check.assert_timestamp_equals(
        closed_year["window_start"], "2025-07-01T00:00:00Z", "window_start"
    )
    check.assert_timestamp_equals(
        closed_year["window_end"], SECOND_PAYMENT_INSTANT, "window_end"
    )
    check.assert_money_equals(
        closed_year["collections_cents"], K.BASELINE_NET_DUE, "collections_cents"
    )
    check.assert_money_equals(closed_year["expenditures_cents"], 0, "expenditures_cents")
    check.assert_money_equals(closed_year["refunds_cents"], 0, "refunds_cents")
    check.assert_money_equals(
        closed_year["unexpended_cents"], K.BASELINE_NET_DUE, "unexpended_cents"
    )
    check.assert_money_equals(
        closed_year["refund_obligation_cents"], 0, "refund_obligation_cents"
    )
    check.assert_timestamp_equals(
        closed_year["earliest_deadline_at"], PARKS_DEADLINE, "earliest_deadline_at"
    )
    assert [row["code"] for row in closed_year["categories"]] == [K.PARKS_CODE, K.ROADS_CODE]
    check.assert_money_equals(
        closed_year["categories"][0]["collections_cents"],
        K.BASELINE_PARKS_LINE_NET,
        "PARKS collections_cents",
    )
    check.assert_money_equals(
        closed_year["categories"][1]["collections_cents"],
        K.BASELINE_ROADS_LINE_NET,
        "ROADS collections_cents",
    )

    check.assert_timestamp_equals(
        open_year["window_start"], SECOND_PAYMENT_INSTANT, "window_start"
    )
    check.assert_timestamp_equals(
        open_year["window_end"], "2027-07-01T00:00:00Z", "window_end"
    )
    check.assert_money_equals(
        open_year["collections_cents"],
        K.BASELINE_NET_DUE,
        "the boundary payment falls into the later year only",
    )
    check.assert_money_equals(
        open_year["unexpended_cents"], 2 * K.BASELINE_NET_DUE, "unexpended_cents"
    )
    check.assert_timestamp_equals(
        open_year["earliest_deadline_at"], PARKS_DEADLINE, "earliest_deadline_at"
    )
    for report in (closed_year, open_year):
        assert report["filed_late"] is False
        assert report["report_status"] == K.REPORT_STATUS_UNFILED, "a read never files"


def test_two_collections_of_the_same_vintage_are_consumed_in_creation_order(api):
    """Eligible money is the `unexpended_cents` of the category's `COLLECTION` rows
    whose `entry_status` is `OPEN` or `PARTIALLY_EXPENDED`, ordered by `vintage_at`
    ascending with `created_at` ascending as the tie-break; rows that are
    `REFUND_DUE`, `REFUNDED` or `FULLY_EXPENDED` are excluded, because money that
    has already breached its statutory deadline may not be spent out from under the
    refund obligation it created. Walk the eligible rows in that order and take
    from each the smaller of its remaining `unexpended_cents` and the amount still
    to be funded; reduce that row's `unexpended_cents` by what was taken, and stop
    as soon as the amount is fully funded.

    Design: Corner/calculations/fifo_ties_on_vintage_are_broken_by_creation_order
    """
    chain = fixtures.effective_program(api)
    first_filed = fixtures.file_application(api, chain.program_id)
    second_filed = fixtures.file_application(api, chain.program_id, permit_number="BP-1002")
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)
    fixtures.assess(api, first_filed["id"])
    fixtures.assess(api, second_filed["id"])
    fixtures.set_clock(api, K.CLOCK_PAYMENT)
    fixtures.pay(api, second_filed["id"], K.BASELINE_NET_DUE)
    fixtures.pay(api, first_filed["id"], K.BASELINE_NET_DUE)
    before = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(before, fund_balance_cents=2 * K.BASELINE_PARKS_LINE_NET)

    expenditure = fixtures.spend(api, chain.parks_category_id, 3000000)

    assert expenditure["kind"] == K.LEDGER_KIND_EXPENDITURE
    check.assert_money_equals(expenditure["amount_cents"], 3000000, "amount_cents")
    assert expenditure["entry_status"] == K.ENTRY_POSTED
    check.assert_money_equals(expenditure["unexpended_cents"], 0, "unexpended_cents")
    check.assert_fields_null(expenditure, "deadline_at")
    assert expenditure["authorized_by_user_id"] == FINANCE_1
    rows = fixtures.collection_rows_for(api, chain.parks_category_id)
    paid_first = [
        row for row in rows if row["development_application_id"] == second_filed["id"]
    ][0]
    paid_second = [
        row for row in rows if row["development_application_id"] == first_filed["id"]
    ][0]
    assert paid_first["entry_status"] == K.ENTRY_FULLY_EXPENDED
    check.assert_money_equals(paid_first["unexpended_cents"], 0, "unexpended_cents")
    assert paid_second["entry_status"] == K.ENTRY_PARTIALLY_EXPENDED
    check.assert_money_equals(paid_second["unexpended_cents"], 2235860, "unexpended_cents")
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=2235860,
        refund_due_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
        oldest_unexpended_vintage_at=K.CLOCK_PAYMENT,
    )
    check.assert_version_advanced_by(before["version"], parks["version"], 1)


def test_an_open_row_without_an_overpayment_may_not_be_refunded(api):
    """A row whose `entry_status` is `OPEN` is only ever an overpayment refund, and
    it requires the row's application to have `paid_cents` strictly greater than
    `net_due_cents`; without that surplus the request is refused with
    `ERR_REFUND_NOT_ELIGIBLE` (HTTP 422). The refunded amount is the smaller of the
    row's `unexpended_cents` and the application's overpayment, that overpayment
    being `paid_cents` minus `net_due_cents`.

    Design: Corner/calculations/open_entry_without_overpayment_is_not_refundable
    """
    chain = fixtures.effective_program_with_paid_application(api)
    parks_row = fixtures.collection_rows_for(api, chain.parks_category_id)[0]
    assert parks_row["entry_status"] == K.ENTRY_OPEN
    check.assert_timestamp_equals(parks_row["deadline_at"], PARKS_DEADLINE, "deadline_at")

    response = api.refund_ledger_entry(
        parks_row["id"], FINANCE, factories.refund_payload(reason="developer requested")
    )

    validate_error(response, err.ERR_REFUND_NOT_ELIGIBLE, 422)
    _, meta = validate_paginated(
        api.list_fund_ledger_entries(
            ADMIN,
            {"facility_category_id": chain.parks_category_id, "kind": K.LEDGER_KIND_REFUND},
        )
    )
    check.assert_pagination_meta(meta, total_count=0)
    source = get_success_data(api.get_fund_ledger_entry(parks_row["id"], ADMIN))
    assert source["entry_status"] == K.ENTRY_OPEN
    check.assert_money_equals(
        source["unexpended_cents"], K.BASELINE_PARKS_LINE_NET, "unexpended_cents"
    )
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=K.BASELINE_PARKS_LINE_NET,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
    )
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application, net_due_cents=K.BASELINE_NET_DUE, paid_cents=K.BASELINE_NET_DUE
    )
