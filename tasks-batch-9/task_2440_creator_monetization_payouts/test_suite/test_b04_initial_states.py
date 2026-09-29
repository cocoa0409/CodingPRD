"""Where each lifecycle begins, and what it has not got yet."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import assert_array_envelope, assert_total_count
from test_helpers.constants import (
    APPEAL_SUBMITTED,
    BACKUP_WITHHOLDING_BPS,
    ELIGIBILITY_PENDING_REVIEW,
    FORM_W9,
    FUND_DRAFT,
    INVESTIGATION_OPEN,
    PAYOUT_PENDING,
    PAYOUT_STATE_ACCRUING,
    PAYOUT_STATE_IN_FLIGHT,
    RATING_GREEN,
    RATING_RED,
    STATEMENT_PROVISIONAL,
    TAX_DRAFT,
    VARIANT_PROVISIONAL,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    subs_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, make_creator_headers


def test_a_channel_begins_awaiting_review_and_accruing(api):
    """Registration is not approval: the channel accrues but is not cleared.

    Design: Corner/state_machines/creator_initial_state_is_pending_review_and_accruing
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    assert creator["eligibility_status"] == ELIGIBILITY_PENDING_REVIEW
    assert creator["payout_state"] == PAYOUT_STATE_ACCRUING
    assert creator["evaluation_count"] == 0


def test_a_tax_document_begins_a_draft_at_the_backup_rate(api):
    """An unverified document carries the backup rate and no lifecycle stamps.

    Creating the document consumes the channel's version, taking it to two.

    Design: Corner/state_machines/tax_profile_initial_state_is_draft_with_backup_withholding
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    profile = validate_success(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"], creator["version"], form_type=FORM_W9, country_code="US"
            ),
            make_creator_headers(creator["id"]),
        ),
        201,
    )
    assert profile["status"] == TAX_DRAFT
    assert profile["withholding_rate_bps"] == BACKUP_WITHHOLDING_BPS
    assert profile["submitted_at"] is None
    assert profile["verified_at"] is None
    assert profile["expires_at"] is None
    assert refresh_creator(api, creator["id"])["version"] == 2


def test_an_appeal_begins_submitted_with_no_revision_rounds_used(api):
    """A fresh appeal is owned by the channel and has not been decided.

    Design: Corner/state_machines/appeal_initial_state_is_submitted_with_zero_revision_round
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    get_success_data(
        api.rate_content_item(item["id"], fac.rate_payload(RATING_RED), REVIEWER)
    )

    appeal = validate_success(
        api.create_appeal(
            fac.appeal_payload(
                item["id"],
                requested_rating=RATING_GREEN,
                statement_text="The clip is educational commentary.",
            ),
            make_creator_headers(creator["id"]),
        ),
        201,
    )
    assert appeal["state"] == APPEAL_SUBMITTED
    assert appeal["revision_round"] == 0
    assert appeal["creator_id"] == creator["id"]
    assert appeal["decided_by_user_id"] is None
    assert appeal["decided_at"] is None


def test_a_case_begins_open_with_all_three_clawback_totals_empty(api):
    """Opening a case computes no money and, unheld, does not gate the channel.

    Design: Corner/state_machines/investigation_initial_state_is_open_with_zero_clawback_totals
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Reused third-party footage",
                violation_window_start="2026-08-01T00:00:00Z",
                violation_window_end="2026-08-10T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        )
    )
    assert investigation["state"] == INVESTIGATION_OPEN
    assert investigation["finding"] is None
    assert investigation["clawback_base_cents"] == 0
    assert investigation["clawback_recovered_cents"] == 0
    assert investigation["clawback_unrecovered_cents"] == 0
    assert investigation["resolved_by_user_id"] is None
    assert refresh_creator(api, creator["id"])["payout_state"] == PAYOUT_STATE_ACCRUING


def _provisional_subs_statement(api):
    """One channel with a single 1000000-cent subscription accrual, swept."""
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
    return creator, period


def test_a_statement_begins_provisional_on_the_provisional_variant(api):
    """The close sweeps the accrual into an unwithheld provisional statement.

    The aggregates are the gross, the share and the event count, no withholding
    is applied yet, and no clawback or dispute has touched it.

    Design: Corner/state_machines/earnings_statement_initial_state_is_provisional_at_close
    """
    creator, period = _provisional_subs_statement(api)

    closed = validate_success(api.close_period(period["id"], FINANCE))
    assert closed["statement_count"] == 1

    rows, meta = assert_array_envelope(
        api.list_statements(
            FINANCE, {"creator_id": creator["id"], "period_id": period["id"]}
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    statement = rows[0]
    assert statement["status"] == STATEMENT_PROVISIONAL
    assert statement["withholding_variant"] == VARIANT_PROVISIONAL
    assert statement["payout_id"] is None
    assert statement["gross_cents"] == 1000000
    assert statement["creator_share_cents"] == 700000
    assert statement["event_count"] == 1
    assert statement["withholding_rate_bps"] == 0
    assert statement["withholding_cents"] == 0
    assert statement["net_payable_cents"] == 700000
    assert statement["clawback_applied_cents"] == 0
    assert statement["dispute_adjustment_cents"] == 0
    assert statement["finalized_at"] is None


def test_a_disbursement_begins_pending_and_puts_the_channel_in_flight(api):
    """Creation claims the statement but has not yet reached the rail.

    Design: Corner/state_machines/payout_initial_state_is_pending_with_zero_retry_count
    """
    creator, period = _provisional_subs_statement(api)
    validate_success(api.close_period(period["id"], FINANCE))
    statement = get_success_data(
        api.list_statements(
            FINANCE, {"creator_id": creator["id"], "period_id": period["id"]}
        )
    )[0]
    get_success_data(api.finalize_statement(statement["id"], FINANCE))

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["state"] == PAYOUT_PENDING
    assert payout["retry_count"] == 0
    assert payout["failure_code"] is None
    assert payout["submitted_at"] is None
    assert payout["settled_at"] is None
    assert refresh_creator(api, creator["id"])["payout_state"] == PAYOUT_STATE_IN_FLIGHT


def test_a_fund_begins_a_draft_with_no_rows_and_no_runs(api):
    """A declared fund has distributed nothing and lists no allocation rows.

    Design: Corner/state_machines/creator_fund_initial_state_is_draft_before_allocation
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    validate_success(api.evaluate_creator(creator["id"], FINANCE))
    period = august_period(api)

    fund = validate_success(
        api.create_fund(fac.fund_payload(period["id"], name="August Boost"), ADMIN), 201
    )
    assert fund["status"] == FUND_DRAFT
    assert fund["allocation_run_count"] == 0
    assert fund["disbursed_at"] is None
    assert fund["version"] == 1

    rows = assert_total_count(api.list_fund_allocations(fund["id"], FINANCE), 0)
    assert rows == []
