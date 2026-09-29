"""A write's own response already agrees with the next read of the same data."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    ELIGIBILITY_SUSPENDED,
    ENTRY_PAYOUT_DEBIT,
    ENTRY_PAYOUT_FEE,
    FAILED_CRITERION_POLICY,
    PAYOUT_PENDING,
    PERIOD_CLOSED,
    STATEMENT_PROVISIONAL,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    payable_creator,
    post_event,
    statement_for,
    subs_product,
)
from test_helpers.test_users import FINANCE, REVIEWER


def test_a_strike_response_already_carries_the_suspension(api):
    """The suspension is visible in the strike's own response body.

    Design: Corner/consistency_model/policy_strike_response_already_shows_the_suspended_eligibility
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")

    struck = validate_success(
        api.create_policy_strike(
            creator["id"],
            fac.policy_strike_payload(reason="Repeated community guideline breach"),
            REVIEWER,
        )
    )
    assert struck["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert struck["active_strike_count"] == 1
    assert struck["last_evaluation_failed_criteria"] == [FAILED_CRITERION_POLICY]

    reloaded = validate_success(api.get_creator(creator["id"], FINANCE))
    assert reloaded["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert reloaded["active_strike_count"] == 1
    assert reloaded["version"] == struck["version"]


def test_the_close_response_counters_match_the_statements_it_created(api):
    """Both statements are readable at the totals the close reported.

    Design: Corner/consistency_model/close_response_counters_match_statements_readable_in_the_same_instant
    """
    first = eligible_creator(api, display_name="Ada Ads", country_code="US")
    second = eligible_creator(api, display_name="Bob Bits", country_code="US")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    post_event(
        api,
        first["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    post_event(
        api,
        second["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-06T00:00:00Z",
    )

    closed = validate_success(api.close_period(period["id"], FINANCE))
    assert closed["status"] == PERIOD_CLOSED
    assert closed["statement_count"] == 2
    # PRD 3.5 declares only `statement_count` and `finalized_statement_count`
    # on a period; the close leaves both statements `PROVISIONAL`.
    assert closed["finalized_statement_count"] == 0

    rows, meta = validate_paginated(
        api.list_statements(FINANCE, {"period_id": period["id"]})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert rows[0]["status"] == STATEMENT_PROVISIONAL
    assert rows[0]["net_payable_cents"] == 532000
    assert rows[1]["status"] == STATEMENT_PROVISIONAL
    assert rows[1]["net_payable_cents"] == 532000


def test_the_disbursement_response_matches_the_rows_it_appended(api):
    """The debit, the fee and the emptied balance are all readable at once.

    Design: Corner/consistency_model/payout_creation_response_matches_ledger_rows_readable_at_once
    """
    creator, _profile = payable_creator(api, display_name="Ada Ads")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["state"] == PAYOUT_PENDING
    assert payout["payable_before_fee_cents"] == 700000
    assert payout["fee_cents"] == 100
    assert payout["amount_cents"] == 699900

    debits = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_PAYOUT_DEBIT}
        ),
        1,
    )
    assert debits[0]["amount_cents"] == -699900

    fees = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_PAYOUT_FEE}
        ),
        1,
    )
    assert fees[0]["amount_cents"] == -100

    summary = validate_success(api.get_earnings_summary(creator["id"], FINANCE))
    assert summary["available_balance_cents"] == 0
    assert summary["ledger_balance_cents"] == 0
