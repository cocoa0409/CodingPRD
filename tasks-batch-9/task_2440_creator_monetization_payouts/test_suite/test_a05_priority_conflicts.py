"""When one request breaks two rules, the ranked rule must be the one heard."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_ledger_sequence, assert_total_count
from test_helpers.constants import (
    ALLOCATION_ACTIVE,
    ENTRY_ACCRUAL,
    ENTRY_FUND_CREDIT,
    ENTRY_WITHHOLDING,
    ENTRY_WITHHOLDING_TRUE_UP,
    EVENT_CLAWED_BACK,
    FUND_DISBURSED,
    INVESTIGATION_SUBSTANTIATED,
    PAYOUT_STATE_ACCRUING,
    PAYOUT_STATE_ARREARS,
    PERIOD_OPEN,
    STATEMENT_FINALIZED,
    VARIANT_FINAL,
)
from test_helpers.fixtures import (
    ads_product,
    close,
    content_item,
    eligible_creator,
    finalize,
    july_period,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, REVIEWER_ALT


def _creator_in_arrears(api):
    """A payable channel whose whole balance has become unrecovered debt."""
    creator, _profile = payable_creator(api)
    product = tips_product(api)
    july_period(api)
    event = post_event(
        api, creator["id"], product["id"], gross_amount_cents=40000
    )
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Tip laundering review.",
                violation_window_end="2026-07-31T23:59:59Z",
                hold_payouts=False,
            ),
            REVIEWER,
        )
    )
    resolved = get_success_data(
        api.substantiate_investigation(
            investigation["id"],
            fac.substantiate_payload(
                finding="Tips were self-funded through stolen instruments."
            ),
            REVIEWER_ALT,
        )
    )
    return creator, event, resolved


def test_the_arrears_state_is_reported_ahead_of_the_empty_balance(api):
    """A channel in debt hears about the debt, not about the zero balance.

    With nothing recovered the whole 20000-cent base becomes arrears and the
    available balance falls to zero, and asking for a disbursement is refused as
    unpayable rather than as having no payable balance.

    Design: Difficulty/priority_pair_validation_conflict/payout_create_arrears_state_outranks_zero_balance_fiscal
    """
    creator, _event, resolved = _creator_in_arrears(api)
    assert resolved["state"] == INVESTIGATION_SUBSTANTIATED
    assert resolved["clawback_unrecovered_cents"] == 20000

    before = refresh_creator(api, creator["id"])
    assert before["payout_state"] == PAYOUT_STATE_ARREARS
    assert before["available_balance_cents"] == 0
    assert before["ledger_balance_cents"] == 20000

    response = api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    validate_error(response, err.ERR_CREATOR_NOT_PAYABLE, 409)


def test_the_refused_disbursement_leaves_the_debt_exactly_as_it_was(api):
    """Losing the ranked check must not partially apply the request.

    No disbursement record appears, the 20000-cent debt and clawed-back event
    stand, and the ledger still holds only the original accrual.

    Design: Difficulty/priority_pair_validation_conflict/payout_create_arrears_state_outranks_zero_balance_fiscal
    """
    creator, event, _resolved = _creator_in_arrears(api)
    api.create_payout(fac.payout_payload(creator["id"]), FINANCE)

    assert_total_count(api.list_payouts(FINANCE, {"creator_id": creator["id"]}), 0)
    after = refresh_creator(api, creator["id"])
    assert after["outstanding_clawback_cents"] == 20000
    assert after["payout_state"] == PAYOUT_STATE_ARREARS
    assert after["ledger_balance_cents"] == 20000

    events = validate_success(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]})
    )
    assert [row["status"] for row in events if row["id"] == event["id"]] == [
        EVENT_CLAWED_BACK
    ]
    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 1)
    assert_ledger_sequence(rows, [(ENTRY_ACCRUAL, 20000)])


def test_a_closed_case_is_reported_before_the_reviewer_separation_rule(api):
    """Re-resolving a finished case fails on the case, not on who asked.

    The reviewer who opened the case asks to resolve it a second time, which
    breaks both the lifecycle rule and the separation rule, and the answer is
    that the case is no longer open.

    Design: Difficulty/priority_pair_validation_conflict/substantiate_closed_investigation_state_outranks_segregation_safety
    """
    creator = eligible_creator(api, country_code="US")
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Bot-driven subscription review.",
                violation_window_end="2026-07-31T23:59:59Z",
                hold_payouts=False,
            ),
            REVIEWER,
        )
    )
    assert investigation["opened_by_user_id"] == "reviewer-r1"
    resolved = get_success_data(
        api.substantiate_investigation(
            investigation["id"],
            fac.substantiate_payload(
                finding="Subscriptions were purchased with compromised cards."
            ),
            REVIEWER_ALT,
        )
    )
    assert resolved["state"] == INVESTIGATION_SUBSTANTIATED
    assert resolved["resolved_by_user_id"] == "reviewer-r2"

    response = api.substantiate_investigation(
        investigation["id"],
        fac.substantiate_payload(finding="Re-confirming my own original finding."),
        REVIEWER,
    )
    validate_error(response, err.ERR_INVESTIGATION_NOT_OPEN, 409)

    unchanged = validate_success(api.get_investigation(investigation["id"], FINANCE))
    assert unchanged["resolved_by_user_id"] == "reviewer-r2"
    assert unchanged["finding"] == (
        "Subscriptions were purchased with compromised cards."
    )
    after = refresh_creator(api, creator["id"])
    assert after["active_strike_count"] == 1
    assert after["outstanding_clawback_cents"] == 0
    assert after["payout_state"] == PAYOUT_STATE_ACCRUING
    assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 0)


def _untaxed_channel_below_threshold(api):
    creator = eligible_creator(
        api, display_name="Ned NoTax", country_code="GB",
        payout_method="BANK_TRANSFER",
    )
    product = tips_product(api)
    period = july_period(api)
    post_event(api, creator["id"], product["id"], gross_amount_cents=10000)
    close(api, period["id"])
    provisional = statement_for(api, creator["id"], period["id"])
    return creator, provisional


def test_the_missing_tax_form_is_reported_ahead_of_the_low_balance(api):
    """Two unprocessable conditions collide and the tax form wins.

    Without a tax form the backup rate of 2400 basis points leaves only 3800
    cents payable, below the 10000-cent threshold, yet the refusal names the
    missing documentation.

    Design: Difficulty/priority_pair_validation_conflict/payout_create_missing_tax_safety_outranks_below_threshold_fiscal
    """
    creator, provisional = _untaxed_channel_below_threshold(api)
    assert provisional["withholding_rate_bps"] == 2400
    assert provisional["withholding_cents"] == 1200

    final = finalize(api, provisional["id"])
    assert final["net_payable_cents"] == 3800

    before = refresh_creator(api, creator["id"])
    assert before["available_balance_cents"] == 3800
    assert before["payout_state"] == PAYOUT_STATE_ACCRUING

    response = api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    validate_error(response, err.ERR_TAX_DOCUMENTATION_MISSING, 422)


def test_the_undocumented_statement_stays_finalized_and_unattached(api):
    """The refused disbursement leaves the finalized statement free.

    No disbursement is stored, the statement keeps its final variant with no
    disbursement attached, and only the accrual and the single withholding
    entry stand behind the 3800-cent balance.

    Design: Difficulty/priority_pair_validation_conflict/payout_create_missing_tax_safety_outranks_below_threshold_fiscal
    """
    creator, provisional = _untaxed_channel_below_threshold(api)
    finalize(api, provisional["id"])
    api.create_payout(fac.payout_payload(creator["id"]), FINANCE)

    assert_total_count(api.list_payouts(FINANCE, {"creator_id": creator["id"]}), 0)
    statement = validate_success(api.get_statement(provisional["id"], FINANCE))
    assert statement["status"] == STATEMENT_FINALIZED
    assert statement["payout_id"] is None
    assert statement["withholding_variant"] == VARIANT_FINAL

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 2)
    assert_ledger_sequence(
        rows, [(ENTRY_ACCRUAL, 5000), (ENTRY_WITHHOLDING, -1200)]
    )
    assert all(row["entry_type"] != ENTRY_WITHHOLDING_TRUE_UP for row in rows)
    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 3800


def test_the_wrong_owner_of_a_clip_is_reported_before_the_stale_date(api):
    """A borrowed clip and an out-of-window date collide on one accrual.

    The clip belongs to another channel and the date sits outside every open
    period, and the refusal names the ownership mismatch.

    Design: Difficulty/priority_pair_validation_conflict/revenue_event_content_mismatch_referential_outranks_no_open_period_temporal
    """
    first = eligible_creator(api, display_name="Ora A")
    second = eligible_creator(api, display_name="Pax B")
    borrowed = content_item(api, second["id"], title="Pax Only Clip")
    product = ads_product(api)
    period = july_period(api)

    response = api.create_revenue_event(
        fac.revenue_event_payload(
            first["id"],
            product["id"],
            content_item_id=borrowed["id"],
            occurred_at="2026-09-15T00:00:00Z",
        ),
        FINANCE,
    )
    validate_error(response, err.ERR_CONTENT_CREATOR_MISMATCH, 422)

    assert_total_count(
        api.list_revenue_events(FINANCE, {"creator_id": first["id"]}), 0
    )
    assert_total_count(api.list_ledger_entries(first["id"], FINANCE), 0)
    assert validate_success(api.get_content_item(borrowed["id"], FINANCE))[
        "creator_id"
    ] == second["id"]
    reloaded = validate_success(api.get_period(period["id"], FINANCE))
    assert reloaded["status"] == PERIOD_OPEN
    assert reloaded["statement_count"] == 0


def _disbursed_fund(api):
    creator = new_creator(api, display_name="Quin Fund", country_code="US")
    get_success_data(api.evaluate_creator(creator["id"], FINANCE))
    period = july_period(api)
    fund = get_success_data(
        api.create_fund(fac.fund_payload(period["id"], name="Solo Fund"), ADMIN)
    )
    allocated = validate_success(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    disbursed = validate_success(api.disburse_fund(fund["id"], FINANCE))
    return creator, fund, allocated, disbursed


def test_a_finished_fund_is_reported_before_the_stale_version_token(api):
    """The lifecycle check is ranked ahead of the concurrency check.

    Re-running allocation on a disbursed fund with the version read before
    disbursement breaks both rules, and the refusal says the fund can no longer
    be allocated rather than complaining about the token.

    Design: Difficulty/priority_pair_validation_conflict/allocate_disbursed_fund_state_outranks_stale_fund_version_occ
    """
    _creator, fund, allocated, disbursed = _disbursed_fund(api)
    assert allocated["allocated_cents"] == 100000
    assert allocated["unallocated_remainder_cents"] == 0
    assert allocated["version"] == fund["version"] + 1
    assert disbursed["status"] == FUND_DISBURSED
    assert disbursed["version"] == allocated["version"] + 1

    response = api.allocate_fund(
        fund["id"], fac.allocate_payload(allocated["version"]), FINANCE
    )
    validate_error(response, err.ERR_FUND_NOT_ALLOCATABLE, 409)


def test_the_refused_reallocation_leaves_one_run_and_one_credit(api):
    """A rejected second run must not touch the pool it already paid out.

    The fund keeps a single allocation run and a single active row for the whole
    100000-cent pool, and the recipient keeps exactly one fund credit entry.

    Design: Difficulty/priority_pair_validation_conflict/allocate_disbursed_fund_state_outranks_stale_fund_version_occ
    """
    creator, fund, allocated, disbursed = _disbursed_fund(api)
    api.allocate_fund(fund["id"], fac.allocate_payload(allocated["version"]), FINANCE)

    reloaded = validate_success(api.get_fund(fund["id"], FINANCE))
    assert reloaded["status"] == FUND_DISBURSED
    assert reloaded["allocation_run_count"] == 1
    assert reloaded["recipient_count"] == 1
    assert reloaded["allocated_cents"] == 100000
    assert reloaded["version"] == disbursed["version"]

    rows = assert_total_count(api.list_fund_allocations(fund["id"], FINANCE), 1)
    assert rows[0]["status"] == ALLOCATION_ACTIVE
    assert rows[0]["rank"] == 1
    assert rows[0]["amount_cents"] == 100000
    assert rows[0]["void_reason"] is None

    after = refresh_creator(api, creator["id"])
    assert after["fund_credit_balance_cents"] == 100000
    assert after["available_balance_cents"] == 100000
    credits = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_FUND_CREDIT}
        ),
        1,
    )
    assert credits[0]["amount_cents"] == 100000
