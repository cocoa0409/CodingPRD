"""Funds, cases and disbursements refuse every out-of-state call."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_total_count
from test_helpers.constants import (
    ENTRY_FUND_CREDIT,
    ENTRY_PAYOUT_DEBIT,
    FUND_DISBURSED,
    FUND_DRAFT,
    INVESTIGATION_CLEARED,
    PAYOUT_PENDING,
    PAYOUT_PROCESSING,
    STATEMENT_FINALIZED,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    finalize,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import (
    ADMIN,
    FINANCE,
    REVIEWER,
    REVIEWER_ALT,
    make_creator_headers,
    make_reviewer_headers,
)


def test_a_draft_fund_has_no_allocations_to_discard(api):
    """Discarding requires an allocation set to exist.

    The fund is untouched: still a draft at its first version.

    Design: Corner/state_machines/void_allocations_on_draft_fund_rejected_as_not_allocated
    """
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(fac.fund_payload(period["id"], name="August Boost"), ADMIN)
    )

    validate_error(
        api.void_fund_allocations(
            fund["id"],
            fac.void_allocations_payload(fund["version"], reason="Nothing to void"),
            FINANCE,
        ),
        err.ERR_FUND_NOT_ALLOCATED,
        409,
    )
    reloaded = validate_success(api.get_fund(fund["id"], FINANCE))
    assert reloaded["status"] == FUND_DRAFT
    assert reloaded["version"] == 1


def test_a_disbursed_fund_cannot_pay_out_twice(api):
    """Disbursement is terminal, so the recipient is credited exactly once.

    Design: Corner/state_machines/disburse_disbursed_fund_rejected_from_terminal_state
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(fac.fund_payload(period["id"], name="August Boost"), ADMIN)
    )
    allocated = get_success_data(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    get_success_data(api.disburse_fund(allocated["id"], FINANCE))

    validate_error(
        api.disburse_fund(fund["id"], FINANCE), err.ERR_FUND_NOT_ALLOCATED, 409
    )
    assert validate_success(api.get_fund(fund["id"], FINANCE))["status"] == (
        FUND_DISBURSED
    )
    rows = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_FUND_CREDIT}
        ),
        1,
    )
    assert rows[0]["amount_cents"] == 100000
    assert refresh_creator(api, creator["id"])["fund_credit_balance_cents"] == 100000


def test_a_cleared_case_cannot_be_cleared_again(api):
    """The second finding is refused and the first resolver stands.

    Design: Corner/state_machines/clear_already_cleared_investigation_rejected_from_terminal_state
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Suspected inorganic engagement",
                violation_window_start="2026-08-02T00:00:00Z",
                violation_window_end="2026-08-09T00:00:00Z",
                hold_payouts=True,
            ),
            REVIEWER,
        )
    )
    get_success_data(
        api.clear_investigation(
            investigation["id"],
            fac.clear_payload(finding="Traffic was organic."),
            REVIEWER_ALT,
        )
    )

    validate_error(
        api.clear_investigation(
            investigation["id"],
            fac.clear_payload(finding="Second look, still organic."),
            make_reviewer_headers("reviewer-r3"),
        ),
        err.ERR_INVESTIGATION_NOT_OPEN,
        409,
    )
    reloaded = validate_success(api.get_investigation(investigation["id"], REVIEWER))
    assert reloaded["state"] == INVESTIGATION_CLEARED
    assert reloaded["finding"] == "Traffic was organic."
    assert reloaded["resolved_by_user_id"] == "reviewer-r2"


def _pending_payout_on_seven_hundred_thousand(api):
    """A verified channel with one pending disbursement of 699900 cents."""
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
    statement = finalize(api, statement_for(api, creator["id"], period["id"])["id"])
    payout = get_success_data(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE)
    )
    return creator, statement, payout


def test_a_disbursement_already_on_the_rail_cannot_be_handed_over_again(api):
    """The second submission is refused and the first stamp survives.

    Design: Corner/state_machines/submit_already_processing_payout_rejected_as_not_pending
    """
    _creator, _statement, payout = _pending_payout_on_seven_hundred_thousand(api)
    get_success_data(api.submit_payout(payout["id"], FINANCE))
    get_success_data(api.set_clock(fac.clock_payload("2026-08-02T00:00:00Z"), ADMIN))

    validate_error(
        api.submit_payout(payout["id"], FINANCE), err.ERR_PAYOUT_NOT_PENDING, 409
    )
    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["state"] == PAYOUT_PROCESSING
    assert_instant(reloaded["submitted_at"], "2026-08-01T00:00:00Z")


def test_a_settlement_cannot_be_recorded_before_the_rail_has_it(api):
    """Nothing is paid and the statement stays attached and finalized.

    Design: Corner/state_machines/record_settlement_on_pending_payout_rejected_as_not_processing
    """
    creator, statement, payout = _pending_payout_on_seven_hundred_thousand(api)

    validate_error(
        api.record_settlement(
            payout["id"], fac.settlement_payload("SUCCEEDED"), FINANCE
        ),
        err.ERR_PAYOUT_NOT_PROCESSING,
        409,
    )
    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["state"] == PAYOUT_PENDING
    assert reloaded["settled_at"] is None
    assert refresh_creator(api, creator["id"])["lifetime_paid_cents"] == 0
    assert validate_success(api.get_statement(statement["id"], FINANCE))["status"] == (
        STATEMENT_FINALIZED
    )


def test_a_disbursement_that_never_failed_cannot_be_retried(api):
    """Retry is refused and the money is debited exactly once.

    Design: Corner/state_machines/retry_never_failed_payout_rejected_as_not_failed
    """
    creator, _statement, payout = _pending_payout_on_seven_hundred_thousand(api)

    validate_error(
        api.retry_payout(payout["id"], FINANCE), err.ERR_PAYOUT_NOT_FAILED, 409
    )
    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["state"] == PAYOUT_PENDING
    assert reloaded["retry_count"] == 0

    rows = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_PAYOUT_DEBIT}
        ),
        1,
    )
    assert rows[0]["amount_cents"] == -699900


def test_a_claimed_statement_cannot_be_disputed(api):
    """Attachment to a disbursement closes the dispute door.

    Design: Corner/state_machines/dispute_statement_attached_to_payout_rejected_as_already_attached
    """
    creator, statement, payout = _pending_payout_on_seven_hundred_thousand(api)

    attached = validate_success(api.get_statement(statement["id"], FINANCE))
    assert attached["status"] == STATEMENT_FINALIZED
    assert attached["payout_id"] == payout["id"]

    validate_error(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(50000, dispute_reason="Sponsorship invoice missing."),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_STATEMENT_ALREADY_ATTACHED,
        409,
    )
    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_FINALIZED
    assert reloaded["dispute_reason"] is None
