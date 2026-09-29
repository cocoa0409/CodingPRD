"""Running totals that must be backed out before they are re-added, and derived
balances that must survive a full cycle of money in and money out."""

from test_helpers import ANALYST_2, FINANCE_1, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data, make_analyst_headers, validate_error
from test_helpers.fixtures import ADMIN, CLERK

REVIEWER = make_analyst_headers(ANALYST_2)
SECOND_VINTAGE = "2026-06-01T00:00:00Z"
TWO_COLLECTIONS_CENTS = 2 * K.BASELINE_PARKS_LINE_NET
REMAINDER_CENTS = TWO_COLLECTIONS_CENTS - 3000000


def _parks_fund_with_two_vintages(api):
    """Two identical projects paid a month apart, so the parks fund carries two
    collection vintages."""
    chain = fixtures.effective_program_with_paid_application(api)
    second = fixtures.file_application(api, chain.program_id, permit_number="BP-1002")
    fixtures.set_clock(api, SECOND_VINTAGE)
    fixtures.assess(api, second["id"])
    fixtures.pay(api, second["id"], K.BASELINE_NET_DUE)
    fixtures.set_clock(api, "2026-06-15T00:00:00Z")
    return chain, second


def test_a_first_in_first_out_expenditure_moves_cash_without_drift(api):
    """Consumption itself is strict first-in, first-out on vintage. A row taken
    down to zero moves to `FULLY_EXPENDED` — from `OPEN` if this expenditure
    consumed its whole remainder, or from `PARTIALLY_EXPENDED` if an earlier
    expenditure had already bitten into it. A row taken down to a positive
    remainder moves `OPEN → PARTIALLY_EXPENDED`.

    Design: Difficulty/compensating_invariant/fund_cash_is_conserved_across_collection_expenditure_and_refund
    """
    chain, _ = _parks_fund_with_two_vintages(api)
    parks_before = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(parks_before, fund_balance_cents=TWO_COLLECTIONS_CENTS)

    expenditure = fixtures.spend(api, chain.parks_category_id, 3000000)

    assert expenditure["kind"] == K.LEDGER_KIND_EXPENDITURE
    assert expenditure["entry_status"] == K.ENTRY_POSTED
    check.assert_money_equals(expenditure["unexpended_cents"], 0, "unexpended_cents")
    check.assert_fields_null(expenditure, "deadline_at", "development_application_id")
    assert expenditure["authorized_by_user_id"] == FINANCE_1

    rows = fixtures.collection_rows_for(api, chain.parks_category_id)
    oldest = [row for row in rows if row["vintage_at"].startswith("2026-05-10")][0]
    newest = [row for row in rows if row["vintage_at"].startswith("2026-06-01")][0]
    assert oldest["entry_status"] == K.ENTRY_FULLY_EXPENDED
    check.assert_money_equals(oldest["unexpended_cents"], 0, "unexpended_cents")
    assert newest["entry_status"] == K.ENTRY_PARTIALLY_EXPENDED
    check.assert_money_equals(newest["unexpended_cents"], REMAINDER_CENTS, "unexpended_cents")

    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=REMAINDER_CENTS,
        oldest_unexpended_vintage_at=SECOND_VINTAGE,
    )
    check.assert_fund_cash_conserved(
        fixtures.ledger_rows(api, {"facility_category_id": chain.parks_category_id}),
        parks["fund_balance_cents"],
    )


def test_the_statutory_refund_returns_the_fund_to_zero(api):
    """The row moves `REFUND_DUE → REFUNDED` with `unexpended_cents` set to 0.
    Either way a `REFUND` row is created `POSTED` for the refunded amount with
    `refunded_entry_id` pointing at the source row and `authorized_by_user_id`
    from the caller, the source row's `version` increments, the category's
    `fund_balance_cents` drops by the refunded amount while `refund_due_cents`,
    `oldest_unexpended_vintage_at` and `fund_posture` are recomputed and the
    category's `version` increments, and the paying application's `paid_cents` is
    recomputed with its `version` incremented.

    Design: Difficulty/compensating_invariant/fund_cash_is_conserved_across_collection_expenditure_and_refund
    """
    chain, _ = _parks_fund_with_two_vintages(api)
    fixtures.spend(api, chain.parks_category_id, 3000000)
    fixtures.set_clock(api, "2031-06-01T00:00:00Z")
    fixtures.sweep(api, chain.program_id)
    remainder_row = [
        row
        for row in fixtures.collection_rows_for(api, chain.parks_category_id)
        if row["vintage_at"].startswith("2026-06-01")
    ][0]
    assert remainder_row["entry_status"] == K.ENTRY_REFUND_DUE
    swept_parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(swept_parks, refund_due_cents=REMAINDER_CENTS)

    refund_row = fixtures.refund(api, remainder_row["id"])

    check.assert_money_equals(refund_row["amount_cents"], REMAINDER_CENTS, "amount_cents")
    assert refund_row["kind"] == K.LEDGER_KIND_REFUND
    assert refund_row["refunded_entry_id"] == remainder_row["id"]
    assert refund_row["authorized_by_user_id"] == FINANCE_1
    source = get_success_data(api.get_fund_ledger_entry(remainder_row["id"], ADMIN))
    assert source["entry_status"] == K.ENTRY_REFUNDED
    check.assert_money_equals(source["unexpended_cents"], 0, "unexpended_cents")
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=0,
        refund_due_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
    )
    check.assert_fields_null(parks, "oldest_unexpended_vintage_at")
    check.assert_fund_cash_conserved(
        fixtures.ledger_rows(api, {"facility_category_id": chain.parks_category_id}),
        parks["fund_balance_cents"],
    )


def _noticed_study_with_two_filings(api):
    chain = fixtures.noticed_program(api, with_roads=False)
    first = fixtures.record_protest(
        api, chain.study_id, protester_name="Harbor Heights Owners", parcel_count=12, weight_bp=3000
    )
    second = fixtures.record_protest(
        api,
        chain.study_id,
        protester_name="Downtown Merchants Group",
        parcel_count=9,
        weight_bp=2500,
    )
    return chain, first, second


def test_a_withdrawal_subtracts_its_weight_exactly_once(api):
    """A recorded filing may be withdrawn, which moves it `RECORDED → WITHDRAWN`,
    subtracts its `weight_bp` from the study's tally, subtracts one from
    `protest_count`, and again increments the study's `version`. On a `FeeStudy`,
    `protest_weight_bp` is the sum of `weight_bp` over that study's filings whose
    `status` is `RECORDED`, and `protest_count` is the number of such filings.

    Design: Difficulty/compensating_invariant/protest_weight_tally_is_conserved_across_filing_and_withdrawal
    """
    chain, first, second = _noticed_study_with_two_filings(api)
    noticed = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert noticed["protest_weight_bp"] == 5500
    assert noticed["protest_count"] == 2

    withdrawn = get_success_data(api.withdraw_protest_filing(second["id"], CLERK))

    assert withdrawn["status"] == K.PROTEST_WITHDRAWN
    assert withdrawn["weight_bp"] == 2500, "the withdrawn row keeps its own weight"
    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["protest_weight_bp"] == 3000
    assert study["protest_count"] == 1

    response = api.withdraw_protest_filing(second["id"], CLERK)

    validate_error(response, err.ERR_PROTEST_INVALID_STATE, 409)
    after = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert after["protest_weight_bp"] == 3000, "the weight may not be subtracted twice"
    assert after["protest_count"] == 1
    filings = get_success_data(api.list_protest_filings(chain.study_id, ADMIN))
    surviving = [row for row in filings if row["id"] == first["id"]][0]
    assert surviving["status"] == K.PROTEST_RECORDED
    assert surviving["weight_bp"] == 3000


def test_the_compensated_tally_clears_the_window(api):
    """The study's `version` increments. Every `RECORDED` filing is left exactly
    as it is, so the tally that the council relied on stays on the record.

    Design: Difficulty/compensating_invariant/protest_weight_tally_is_conserved_across_filing_and_withdrawal
    """
    chain, first, second = _noticed_study_with_two_filings(api)
    api.withdraw_protest_filing(second["id"], CLERK)
    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)

    cleared = fixtures.close_protest_window(api, chain.study_id)

    assert cleared["status"] == K.STUDY_PROTEST_CLEARED
    assert cleared["revision_round"] == 0
    assert cleared["protest_weight_bp"] == 3000
    assert cleared["protest_count"] == 1
    filings = get_success_data(api.list_protest_filings(chain.study_id, ADMIN))
    surviving = [row for row in filings if row["id"] == first["id"]][0]
    assert surviving["status"] == K.PROTEST_RECORDED


def _assessed_application_with_a_pending_parks_claim(api):
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    claim = fixtures.file_credit_claim(
        api,
        chain.application_id,
        facility_category_code=K.PARKS_CODE,
        credit_type=K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        valuation_method=K.VALUATION_NOMINAL,
        improvement_value_cents=1000000,
        annual_tax_contribution_cents=0,
        contribution_years=0,
    )
    return chain, claim


def test_an_identical_re_assessment_does_not_double_the_committed_units(api):
    """Assessment also updates the facility standards it touched. On a first
    assessment the application moves `UNASSESSED → ASSESSED`; on a re-run it moves
    `ASSESSED → REASSESSED` or re-enters `REASSESSED`, and a re-run additionally
    requires that `collection_status` is not `PAID` and that `co_issued_at` is
    still null, either failure returning `ERR_APPLICATION_INVALID_STATE`. A
    re-assessment never moves the collection dimension at all, in either
    direction.

    Design: Difficulty/compensating_invariant/committed_demand_units_are_conserved_across_reassessment
    """
    chain, _ = _assessed_application_with_a_pending_parks_claim(api)

    reassessed = fixtures.assess(api, chain.application_id)

    assert reassessed["assessment_status"] == K.ASSESSMENT_REASSESSED
    check.assert_timestamp_equals(
        reassessed["reassessed_at"], K.CLOCK_ASSESSMENT, "reassessed_at"
    )
    assert reassessed["collection_status"] == K.COLLECTION_DUE
    check.assert_application_totals(
        reassessed, credit_applied_cents=0, net_due_cents=K.BASELINE_NET_DUE
    )
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ADMIN))
    check.assert_category_fund(parks, committed_demand_units=K.BASELINE_PARKS_DEMAND_UNITS)
    check.assert_category_fund(roads, committed_demand_units=K.BASELINE_ROADS_DEMAND_UNITS)


def test_an_approved_credit_moves_the_money_and_leaves_the_units_alone(api):
    """Both approval branches carry identical consequences beyond the claim row.
    All three status values `APPROVED_FULL`, `APPROVED_PARTIAL` and `DENIED` are
    terminal for the claim.

    Design: Difficulty/compensating_invariant/committed_demand_units_are_conserved_across_reassessment
    """
    chain, claim = _assessed_application_with_a_pending_parks_claim(api)
    fixtures.assess(api, chain.application_id)

    decided = fixtures.decide_credit_claim(
        api, claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )

    assert decided["status"] == K.CLAIM_APPROVED_FULL
    check.assert_money_equals(decided["approved_cents"], 1000000, "approved_cents")
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application,
        credit_applied_cents=1000000,
        admin_charge_cents=121151,
        net_due_cents=4159521,
    )
    parks_line = check.line_for_code(application["assessed_lines"], K.PARKS_CODE)
    roads_line = check.line_for_code(application["assessed_lines"], K.ROADS_CODE)
    check.assert_assessed_line(parks_line, demand_units=K.BASELINE_PARKS_DEMAND_UNITS)
    check.assert_assessed_line(roads_line, demand_units=K.BASELINE_ROADS_DEMAND_UNITS)
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ADMIN))
    check.assert_category_fund(parks, committed_demand_units=K.BASELINE_PARKS_DEMAND_UNITS)
    check.assert_category_fund(roads, committed_demand_units=K.BASELINE_ROADS_DEMAND_UNITS)
