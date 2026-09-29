"""Two named variants of one calculation must not collapse into each other."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import (
    assert_instant,
    assert_ledger_sequence,
    assert_no_entry_of_type,
    assert_total_count,
)
from test_helpers.constants import (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_SUSPENDED,
    ENTRY_ACCRUAL,
    ENTRY_WITHHOLDING,
    ENTRY_WITHHOLDING_TRUE_UP,
    FAILED_CRITERION_POLICY,
    FORM_W8BEN,
    METHODOLOGY_GUARANTEED_FLOOR,
    METHODOLOGY_PRO_RATA,
    PERIOD_CLOSED,
    PERIOD_FINALIZED,
    SOURCE_EARNINGS_STATEMENT,
    STATEMENT_FINALIZED,
    VARIANT_FINAL,
    VARIANT_PROVISIONAL,
)
from test_helpers.fixtures import (
    august_period,
    close,
    eligible_creator,
    eligible_creator_with_watch_time,
    finalize,
    july_period,
    ledger_rows,
    new_creator,
    post_event,
    refresh_creator,
    statement_for,
    tips_product,
    verified_tax_profile,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER


def _three_event_statement(api):
    """A non-resident channel with three equal 500-cent accruals in July."""
    creator = eligible_creator(api, country_code="GB")
    verified_tax_profile(
        api,
        creator,
        form_type=FORM_W8BEN,
        country_code="GB",
        tin_provided=True,
        treaty_claimed=False,
    )
    product = tips_product(
        api, name="Tips Odd Split", creator_share_bps=6700, platform_fee_bps=3300
    )
    period = july_period(api)
    for day in ("2026-07-05", "2026-07-06", "2026-07-07"):
        event = post_event(
            api,
            creator["id"],
            product["id"],
            gross_amount_cents=500,
            occurred_at=f"{day}T00:00:00Z",
        )
        assert event["creator_share_cents"] == 335
    close(api, period["id"])
    return creator, period, statement_for(api, creator["id"], period["id"])


def test_provisional_withholding_rounds_the_aggregate_exactly_once(api):
    """Closing a period withholds on the summed share, not per event.

    Three 335-cent shares total 1005; one half-up rounding of 1005 at 3000
    basis points yields 302 and a net payable of 703.

    Design: Difficulty/dual_variant_calc/statement_withholding_provisional_vs_final_rounding_order
    """
    creator, _period, statement = _three_event_statement(api)

    assert statement["withholding_variant"] == VARIANT_PROVISIONAL
    assert statement["gross_cents"] == 1500
    assert statement["creator_share_cents"] == 1005
    assert statement["withholding_rate_bps"] == 3000
    assert statement["withholding_cents"] == 302
    assert statement["net_payable_cents"] == 703
    assert statement["event_count"] == 3

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 4)
    assert_ledger_sequence(
        rows,
        [(ENTRY_ACCRUAL, 335)] * 3 + [(ENTRY_WITHHOLDING, -302)],
    )
    assert_no_entry_of_type(rows, ENTRY_WITHHOLDING_TRUE_UP)


def test_finalization_rounds_each_event_then_sums_and_writes_the_true_up(api):
    """Finalizing withholds per event, so 1005 at 3000 basis points yields 303.

    Rounding each of the three 335-cent shares up to 101 sums to 303 rather
    than 302, and the one-cent divergence is booked as a true-up entry.

    Design: Difficulty/dual_variant_calc/statement_withholding_provisional_vs_final_rounding_order
    """
    creator, period, statement = _three_event_statement(api)

    final = finalize(api, statement["id"])
    assert final["withholding_variant"] == VARIANT_FINAL
    assert final["status"] == STATEMENT_FINALIZED
    assert final["withholding_cents"] == 303
    assert final["net_payable_cents"] == 702
    assert final["creator_share_cents"] == 1005

    true_ups = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_WITHHOLDING_TRUE_UP}
        ),
        1,
    )
    assert true_ups[0]["amount_cents"] == -1
    assert true_ups[0]["source_entity"] == SOURCE_EARNINGS_STATEMENT
    assert true_ups[0]["source_id"] == statement["id"]

    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 702
    reloaded = validate_success(api.get_period(period["id"], FINANCE))
    assert reloaded["status"] == PERIOD_FINALIZED
    assert reloaded["statement_count"] == 1
    assert reloaded["finalized_statement_count"] == 1


def _struck_creator_at_late_clock(api):
    creator = eligible_creator(api)
    struck = get_success_data(
        api.create_policy_strike(
            creator["id"], fac.policy_strike_payload(), REVIEWER
        )
    )
    assert struck["eligibility_status"] == ELIGIBILITY_SUSPENDED
    get_success_data(api.set_clock(fac.clock_payload("2026-10-30T00:00:00Z"), ADMIN))
    return creator


def test_on_demand_evaluation_never_lapses_an_aged_strike(api):
    """An explicit evaluation reads the stored strike count as it stands.

    Ninety days after the strike the channel is still suspended on the policy
    criterion, because strike lapse is only applied while closing a period.

    Design: Difficulty/dual_variant_calc/eligibility_ondemand_vs_period_close_strike_lapse
    """
    creator = _struck_creator_at_late_clock(api)

    evaluated = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert evaluated["eligibility_status"] == ELIGIBILITY_SUSPENDED
    assert evaluated["last_evaluation_failed_criteria"] == [FAILED_CRITERION_POLICY]
    assert evaluated["active_strike_count"] == 1
    # Eligibility evaluation (1), the strike's automatic re-run (2) and this
    # on-demand evaluation (3) each increment the counter — PRD 3.1.
    assert evaluated["evaluation_count"] == 3


def test_period_close_lapses_the_aged_strike_before_re_evaluating(api):
    """Closing a period expires strikes older than ninety days first.

    The lapse drops the strike count to zero, so the same channel that an
    explicit evaluation left suspended comes out of the close eligible.

    Design: Difficulty/dual_variant_calc/eligibility_ondemand_vs_period_close_strike_lapse
    """
    creator = _struck_creator_at_late_clock(api)
    validate_success(api.evaluate_creator(creator["id"], FINANCE))
    period = july_period(api)

    closed = validate_success(api.close_period(period["id"], FINANCE))
    assert closed["status"] == PERIOD_CLOSED
    assert closed["statement_count"] == 0

    after = refresh_creator(api, creator["id"])
    assert after["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert after["last_evaluation_failed_criteria"] == []
    assert after["active_strike_count"] == 0
    # Eligibility evaluation (1), the strike's re-run (2), the explicit
    # evaluation above (3) and the close pipeline's step 3 (4) — PRD 3.1/3.5.
    assert after["evaluation_count"] == 4
    assert_instant(after["last_evaluated_at"], "2026-10-30T00:00:00Z")


def _three_watch_time_creators(api):
    ids = []
    for name, minutes in (
        ("Ida Pool", 500000),
        ("Jon Pool", 300000),
        ("Kim Pool", 200001),
    ):
        creator = eligible_creator_with_watch_time(api, minutes, display_name=name)
        ids.append(creator["id"])
    return ids


def _allocate(api, period_id, methodology, name):
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period_id,
                name=name,
                total_pool_cents=100000,
                methodology=methodology,
                min_watch_time_minutes=0,
            ),
            ADMIN,
        )
    )
    assert fund["methodology"] == methodology
    allocated = validate_success(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    rows = assert_total_count(api.list_fund_allocations(fund["id"], FINANCE), 3)
    return fund, allocated, sorted(rows, key=lambda r: r["rank"])


def test_pro_rata_methodology_splits_the_pool_strictly_by_watch_time(api):
    """Proportional allocation truncates then hands out the leftover cents.

    Watch times of 500000, 300000 and 200001 minutes against a 100000-cent
    pool truncate to 49999, 29999 and 20000, and the two leftover cents go to
    the two highest ranks, giving 50000, 30000 and 20000.

    Design: Difficulty/dual_variant_calc/fund_methodology_pro_rata_vs_guaranteed_floor_same_pool
    """
    ids = _three_watch_time_creators(api)
    period = july_period(api)

    _fund, allocated, rows = _allocate(
        api, period["id"], METHODOLOGY_PRO_RATA, "Pro Rata Fund"
    )
    assert allocated["allocated_cents"] == 100000
    assert allocated["unallocated_remainder_cents"] == 0
    assert allocated["recipient_count"] == 3
    assert [r["creator_id"] for r in rows] == ids
    assert [r["amount_cents"] for r in rows] == [50000, 30000, 20000]

    for creator_id in ids:
        creator = refresh_creator(api, creator_id)
        assert creator["fund_credit_balance_cents"] == 0
        assert_total_count(api.list_ledger_entries(creator_id, FINANCE), 0)


def test_guaranteed_floor_methodology_splits_the_same_pool_differently(api):
    """A guaranteed floor reserves 5000 cents each before proportioning.

    The same pool and the same three channels yield 47500, 30500 and 22000
    once every recipient is guaranteed its floor first.

    Design: Difficulty/dual_variant_calc/fund_methodology_pro_rata_vs_guaranteed_floor_same_pool
    """
    ids = _three_watch_time_creators(api)
    period = august_period(api)

    _fund, allocated, rows = _allocate(
        api, period["id"], METHODOLOGY_GUARANTEED_FLOOR, "Floor Fund"
    )
    assert allocated["allocated_cents"] == 100000
    assert allocated["unallocated_remainder_cents"] == 0
    assert allocated["recipient_count"] == 3
    assert [r["creator_id"] for r in rows] == ids
    assert [r["amount_cents"] for r in rows] == [47500, 30500, 22000]
