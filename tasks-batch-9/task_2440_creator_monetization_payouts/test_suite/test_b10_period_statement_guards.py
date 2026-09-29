"""Windows close in order, and statements move one step at a time."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_total_count
from test_helpers.constants import (
    ENTRY_DISPUTE_ADJUSTMENT,
    ENTRY_WITHHOLDING_TRUE_UP,
    PERIOD_CLOSED,
    PERIOD_OPEN,
    SOURCE_EARNINGS_STATEMENT,
    STATEMENT_ADJUSTED,
    STATEMENT_FINALIZED,
    STATEMENT_PROVISIONAL,
    STATEMENT_UNDER_DISPUTE,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    july_period,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import ADMIN, FINANCE, make_creator_headers


def test_a_closed_window_cannot_be_closed_again(api):
    """The second close is refused and the original stamp survives.

    Design: Corner/state_machines/close_already_closed_period_rejected_as_not_open
    """
    period = august_period(api)
    get_success_data(api.close_period(period["id"], FINANCE))
    get_success_data(api.set_clock(fac.clock_payload("2026-08-02T00:00:00Z"), ADMIN))

    validate_error(
        api.close_period(period["id"], FINANCE), err.ERR_PERIOD_NOT_OPEN, 409
    )
    reloaded = validate_success(api.get_period(period["id"], FINANCE))
    assert reloaded["status"] == PERIOD_CLOSED
    assert_instant(reloaded["closed_at"], "2026-08-01T00:00:00Z")


def test_a_later_window_cannot_close_before_an_earlier_one(api):
    """Closing out of chronological order is refused and closes nothing.

    Design: Corner/state_machines/close_newer_period_before_older_open_period_rejected
    """
    july = july_period(api)
    august = august_period(api)

    validate_error(
        api.close_period(august["id"], FINANCE),
        err.ERR_PERIOD_CLOSE_OUT_OF_ORDER,
        409,
    )
    assert validate_success(api.get_period(august["id"], FINANCE))["status"] == (
        PERIOD_OPEN
    )
    assert validate_success(api.get_period(july["id"], FINANCE))["status"] == PERIOD_OPEN


def _provisional_statement(api):
    """An untaxed channel with a single 1000000-cent subscription accrual."""
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
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
    return creator, period, statement_for(api, creator["id"], period["id"])


def test_a_finalized_statement_cannot_be_finalized_twice(api):
    """The second finalization is refused and writes no second true-up.

    The withheld amount stays at the backup rate applied once, so the net payable
    is unchanged.

    Design: Corner/state_machines/finalize_already_finalized_statement_rejected
    """
    creator, _period, statement = _provisional_statement(api)
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    validate_error(
        api.finalize_statement(statement["id"], FINANCE),
        err.ERR_STATEMENT_NOT_PROVISIONAL,
        409,
    )
    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_FINALIZED
    assert reloaded["withholding_cents"] == 168000
    assert reloaded["net_payable_cents"] == 532000
    assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_WITHHOLDING_TRUE_UP}
        ),
        0,
    )


def test_a_provisional_statement_cannot_be_disputed(api):
    """Only a finalized or adjusted statement carries a disputable figure.

    Design: Corner/state_machines/dispute_provisional_statement_rejected_as_not_disputable
    """
    creator, _period, statement = _provisional_statement(api)

    validate_error(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(
                100000, dispute_reason="Two sponsorship invoices are missing."
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_STATEMENT_NOT_DISPUTABLE,
        409,
    )
    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_PROVISIONAL
    assert reloaded["dispute_reason"] is None


def test_a_dispute_cannot_be_resolved_before_it_is_opened(api):
    """Resolution is refused and no adjustment is written anywhere.

    Design: Corner/state_machines/resolve_dispute_on_finalized_statement_rejected
    """
    creator, _period, statement = _provisional_statement(api)
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    validate_error(
        api.resolve_dispute(
            statement["id"], fac.resolve_dispute_payload("UPHELD", 50000), FINANCE
        ),
        err.ERR_STATEMENT_NOT_UNDER_DISPUTE,
        409,
    )
    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_FINALIZED
    assert reloaded["dispute_adjustment_cents"] == 0
    assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_DISPUTE_ADJUSTMENT}
        ),
        0,
    )


def test_an_upheld_dispute_adjusts_the_statement_and_the_ledger(api):
    """The granted adjustment is credited once and raises the payable.

    The statement lands on the adjusted status carrying its granted amount, and
    the single adjustment entry names the statement it came from.

    Design: Corner/state_machines/statement_dispute_upheld_moves_to_adjusted_with_ledger_entry
    """
    creator, _period, statement = _provisional_statement(api)
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    disputed = validate_success(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(
                100000, dispute_reason="Two sponsorship invoices are missing."
            ),
            make_creator_headers(creator["id"]),
        )
    )
    assert disputed["status"] == STATEMENT_UNDER_DISPUTE
    assert disputed["dispute_claimed_amount_cents"] == 100000

    resolved = validate_success(
        api.resolve_dispute(
            statement["id"], fac.resolve_dispute_payload("UPHELD", 100000), FINANCE
        )
    )
    assert resolved["status"] == STATEMENT_ADJUSTED
    assert resolved["dispute_resolution"] == "UPHELD"
    assert resolved["dispute_adjustment_cents"] == 100000
    assert resolved["net_payable_cents"] == 532000

    rows = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_DISPUTE_ADJUSTMENT}
        ),
        1,
    )
    assert rows[0]["amount_cents"] == 100000
    assert rows[0]["source_entity"] == SOURCE_EARNINGS_STATEMENT
    assert rows[0]["source_id"] == statement["id"]
    assert refresh_creator(api, creator["id"])["statement_payable_cents"] == 632000
