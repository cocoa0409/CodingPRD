"""A fund's own lifecycle: draft, allocated, discarded, disbursed."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import assert_instant, assert_total_count
from test_helpers.constants import (
    ALLOCATION_VOIDED,
    ENTRY_FUND_CREDIT,
    FUND_DISBURSED,
    FUND_DRAFT,
    SOURCE_FUND_ALLOCATION,
)
from test_helpers.fixtures import august_period, new_creator, refresh_creator
from test_helpers.test_users import ADMIN, FINANCE


def _two_channel_fund(api):
    """Two eligible channels on 800000 and 240000 minutes, and a 104000 pool."""
    top = new_creator(
        api,
        display_name="Top Creator",
        country_code="US",
        follower_count=50000,
        watch_time_minutes_365d=800000,
    )
    nxt = new_creator(
        api,
        display_name="Next Creator",
        country_code="GB",
        follower_count=50000,
        watch_time_minutes_365d=240000,
    )
    validate_success(api.evaluate_creator(top["id"], FINANCE))
    validate_success(api.evaluate_creator(nxt["id"], FINANCE))
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"], name="August Boost", total_pool_cents=104000
            ),
            ADMIN,
        )
    )
    allocated = get_success_data(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    return top, nxt, allocated


def test_discarding_an_allocation_set_returns_the_fund_to_draft(api):
    """The pool is wholly unallocated again but the run still counts.

    Both rows are retired with the supplied reason and its instant, and no
    channel was ever credited.

    Design: Corner/state_machines/fund_allocate_then_void_allocations_returns_fund_to_draft
    """
    top, _nxt, allocated = _two_channel_fund(api)

    voided = validate_success(
        api.void_fund_allocations(
            allocated["id"],
            fac.void_allocations_payload(
                allocated["version"], reason="Corrected watch-time inputs"
            ),
            FINANCE,
        )
    )
    assert voided["status"] == FUND_DRAFT
    assert voided["allocated_cents"] == 0
    assert voided["unallocated_remainder_cents"] == 104000
    assert voided["recipient_count"] == 0
    assert voided["allocation_run_count"] == 1

    rows = assert_total_count(
        api.list_fund_allocations(
            allocated["id"], FINANCE, {"status": ALLOCATION_VOIDED}
        ),
        2,
    )
    assert rows[0]["status"] == ALLOCATION_VOIDED
    assert rows[0]["void_reason"] == "Corrected watch-time inputs"
    assert_instant(rows[0]["voided_at"], "2026-08-01T00:00:00Z")
    assert refresh_creator(api, top["id"])["fund_credit_balance_cents"] == 0


def test_disbursing_credits_each_recipient_in_rank_order(api):
    """Every active row becomes one fund-credit entry naming its own row.

    The pool is fully distributed to two recipients, 80000 to the higher-ranked
    channel and 24000 to the other, and each credit raises that channel's own
    available balance.

    Design: Corner/state_machines/fund_allocated_to_disbursed_writes_fund_credit_entries_in_rank_order
    """
    top, nxt, allocated = _two_channel_fund(api)
    rows = get_success_data(api.list_fund_allocations(allocated["id"], FINANCE))
    ranked = sorted(rows, key=lambda row: row["rank"])

    disbursed = validate_success(api.disburse_fund(allocated["id"], FINANCE))
    assert disbursed["status"] == FUND_DISBURSED
    assert_instant(disbursed["disbursed_at"], "2026-08-01T00:00:00Z")
    assert disbursed["allocated_cents"] == 104000
    assert disbursed["unallocated_remainder_cents"] == 0
    assert disbursed["recipient_count"] == 2

    first = assert_total_count(
        api.list_ledger_entries(
            top["id"], FINANCE, {"entry_type": ENTRY_FUND_CREDIT}
        ),
        1,
    )
    assert first[0]["amount_cents"] == 80000
    assert first[0]["source_entity"] == SOURCE_FUND_ALLOCATION
    assert first[0]["source_id"] == ranked[0]["id"]

    second = assert_total_count(
        api.list_ledger_entries(
            nxt["id"], FINANCE, {"entry_type": ENTRY_FUND_CREDIT}
        ),
        1,
    )
    assert second[0]["amount_cents"] == 24000
    assert second[0]["source_id"] == ranked[1]["id"]

    top_after = refresh_creator(api, top["id"])
    assert top_after["fund_credit_balance_cents"] == 80000
    assert top_after["available_balance_cents"] == 80000
    assert refresh_creator(api, nxt["id"])["fund_credit_balance_cents"] == 24000
