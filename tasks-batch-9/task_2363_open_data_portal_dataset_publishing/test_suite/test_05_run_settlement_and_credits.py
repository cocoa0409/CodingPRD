"""
Run settlement: the six-step charge, the reliability tier keyed on the
pre-discount subtotal, and the escrow-first waterfall that conserves the
department's four credit buckets.
"""

from test_helpers import (
    assert_credit_buckets,
    assert_credit_conservation,
    assert_money,
    assert_scorecard_balanced,
    assert_settlement,
    fixtures,
)

MONTHLY_SETUP = {
    "dataset_overrides": {"update_frequency": "MONTHLY"},
    "metadata_overrides": {"declared_update_frequency": "MONTHLY"},
    "pipeline_overrides": {"cadence": "MONTHLY"},
}


def test_reliability_tier_keys_on_the_pre_discount_subtotal(api):
    """A subtotal of exactly 40 earns the 0.10 tier and settles at 36.00, not 38.00.

    The PRD: "Step four keys `reliability_discount_pct` on that subtotal and on nothing
    else: 0.10 when `subtotal_credits` is 40 or more, 0.05 when it is 20 or more but
    below 40, and 0.00 below 20." and "The tier is never re-evaluated against the
    discounted figure: a subtotal of exactly 40 settles at 36.00 credits, not at 38.00."

    95000 rows ingested is 10 compute units once the quotient of the PRD's rule to
    "divide `rows_ingested` by 10000 rows per compute unit" is rounded up, so
    `compute_credits` is 40.00; a successful run dispatches no alert, so
    `subtotal_credits` is 40.00 too. Re-reading the tier against the discounted 36.00
    would drop it to 0.05 and produce 38.00.

    Design: Difficulty/combinatorial_formula/settlement_tier_keyed_on_pre_discount_subtotal
    """
    ctx = fixtures.setup_running_run(api=api)

    run = fixtures.report_success(ctx["run_id"], 95000, api=api)

    assert run["status"] == "SUCCEEDED", f"Expected SUCCEEDED, got {run['status']}"
    assert_settlement(
        run,
        compute_credits=40.00,
        alert_credits=0.00,
        subtotal_credits=40.00,
        reliability_discount_pct=0.10,
        discount_credits=4.00,
        total_charge_credits=36.00,
    )


def test_the_charge_is_drawn_escrow_first_and_conserves_the_credit_buckets(api):
    """The 36.00 charge exhausts the 10.00 escrow before touching the balance.

    The PRD: "`escrow_drawn_units` is the lesser of the pipeline's current
    `escrowed_credit_units` and `total_charge_credits`; `balance_drawn_units` is
    whatever remains of the charge after that." and "The pipeline's
    `escrowed_credit_units` and the department's `credits_escrowed_units` are each
    reduced by `escrow_drawn_units`, the department's `credit_balance_units` is reduced
    by `balance_drawn_units`, and the department's `credits_consumed_units` is increased
    by the full `total_charge_credits` — which keeps the conservation invariant of §2.10
    intact."

    The department was granted 100.00 and escrowed 10.00 at arming, so the settlement
    draws all 10.00 of escrow and 26.00 of balance, leaving 64.00 / 0.00 / 36.00 against
    an unchanged 100.00 issued.

    Design: Difficulty/combinatorial_formula/settlement_tier_keyed_on_pre_discount_subtotal
    """
    ctx = fixtures.setup_running_run(api=api)

    run = fixtures.report_success(ctx["run_id"], 95000, api=api)

    assert_settlement(run, escrow_drawn_units=10.00, balance_drawn_units=26.00)
    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert_money(pipeline["escrowed_credit_units"], 0.00, "escrowed_credit_units")

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(
        department, issued=100.00, balance=64.00, escrowed=0.00, consumed=36.00
    )
    assert_credit_conservation(department)


def test_subtotal_of_exactly_twenty_earns_the_five_percent_tier(api):
    """The 20.00 boundary is inclusive, so a 20.00 subtotal is discounted by 1.00.

    The PRD keys the tier on the subtotal alone: "0.10 when `subtotal_credits` is 40 or
    more, 0.05 when it is 20 or more but below 40, and 0.00 below 20." 45000 rows is 5
    compute units and so 20.00 of compute with no alert, which sits exactly on the
    inclusive 20 boundary: the discount is 1.00 and the charge 19.00, drawn 10.00 from
    escrow and 9.00 from the balance.

    Design: Difficulty/boundary_precision_check/settlement_discount_tier_boundary_at_subtotal_twenty
    """
    ctx = fixtures.setup_running_run(api=api)

    run = fixtures.report_success(ctx["run_id"], 45000, api=api)

    assert_settlement(
        run,
        compute_credits=20.00,
        alert_credits=0.00,
        subtotal_credits=20.00,
        reliability_discount_pct=0.05,
        discount_credits=1.00,
        total_charge_credits=19.00,
        escrow_drawn_units=10.00,
        balance_drawn_units=9.00,
    )


def test_subtotal_one_tier_below_the_boundary_earns_no_discount(api):
    """A 16.00 subtotal falls below 20 and is charged in full from the balance.

    The PRD sets the lowest tier at "0.00 below 20", and by then the escrow is gone, so
    the waterfall has only one bucket left to draw on: "`escrow_drawn_units` is the
    lesser of the pipeline's current `escrowed_credit_units` and `total_charge_credits`;
    `balance_drawn_units` is whatever remains of the charge after that." A second run
    ingesting 35000 rows is 4 compute units, so 16.00 is both subtotal and charge, drawn
    entirely from the balance.

    Across the two settlements the department spends 9.00 then 16.00 of balance beyond
    the 10.00 escrow it had already set aside, landing at 65.00 / 0.00 / 35.00, and the
    ledger of published versions has moved twice past the initial publication.

    Design: Difficulty/boundary_precision_check/settlement_discount_tier_boundary_at_subtotal_twenty
    """
    ctx = fixtures.setup_running_run(api=api)
    second_run = fixtures.schedule_run(ctx["pipeline_id"], "2026-08-01T09:00:00Z", api=api)
    fixtures.report_success(ctx["run_id"], 45000, api=api)

    fixtures.start_run(second_run["id"], api=api)
    run = fixtures.report_success(second_run["id"], 35000, api=api)

    assert_settlement(
        run,
        compute_credits=16.00,
        subtotal_credits=16.00,
        reliability_discount_pct=0.00,
        discount_credits=0.00,
        total_charge_credits=16.00,
        escrow_drawn_units=0.00,
        balance_drawn_units=16.00,
    )

    department = fixtures.read_department(ctx["department_id"], api=api)
    assert_credit_buckets(
        department, issued=100.00, balance=65.00, escrowed=0.00, consumed=35.00
    )
    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["live_row_count"] == 35000, (
        f"Expected live_row_count 35000, got {dataset['live_row_count']}"
    )
    assert dataset["version_index_high_water"] == 3, (
        f"Expected version_index_high_water 3, got {dataset['version_index_high_water']}"
    )


def test_monthly_cadence_escrows_two_credits_and_they_are_drawn_first(api):
    """Escrow is sized from the cadence alone, and the waterfall still starts there.

    The PRD sizes the reservation over a thirty-day horizon, where "the number of runs
    the cadence implies is the horizon divided by the cadence length in days" and
    "That run count is multiplied by 2 credits per run, and the product is capped at 60
    credits, giving `escrow_required_units`." A `MONTHLY` cadence spans 30 days, so one
    run is implied and only 2.00 is escrowed — a fraction of the 19.00 charge that a
    45000-row run settles at.

    The waterfall therefore draws the 2.00 of escrow and the remaining 17.00 from the
    balance, and the pipeline stays `ARMED` with its escrow emptied.

    Design: Difficulty/compensating_invariant/settlement_waterfall_conserves_department_credit_buckets
    """
    ctx = fixtures.setup_running_run(api=api, **MONTHLY_SETUP)
    assert_money(ctx["pipeline"]["escrow_required_units"], 2.00, "escrow_required_units")

    run = fixtures.report_success(ctx["run_id"], 45000, api=api)

    assert_settlement(
        run,
        subtotal_credits=20.00,
        total_charge_credits=19.00,
        escrow_drawn_units=2.00,
        balance_drawn_units=17.00,
    )
    pipeline = fixtures.read_pipeline(ctx["pipeline_id"], api=api)
    assert pipeline["status"] == "ARMED", (
        f"A settled run must leave the pipeline ARMED, got {pipeline['status']}"
    )
    assert_money(pipeline["escrowed_credit_units"], 0.00, "escrowed_credit_units")


def test_scorecard_reconciles_after_a_settlement_that_spans_both_buckets(api):
    """The scorecard's own reconciliation flag must agree with the bucket arithmetic.

    The PRD requires the department's ledger to hold at all times —
    "`credit_balance_units` plus `credits_escrowed_units` plus `credits_consumed_units`
    equals `credits_issued_units`" — and exposes that as "a boolean
    `credit_ledger_balanced` asserting that the conservation invariant of §2.10
    currently holds."

    After the 19.00 charge the buckets read 81.00 / 0.00 / 19.00 against 100.00 issued.
    The successful run also rolls the dataset forward, so with a `MONTHLY` cadence
    "`next_due_at`, `days_overdue` and `currency_status` are re-derived" from the
    publication instant of 2026-08-01T09:00:00Z, putting the next obligation 30 days
    later.

    Design: Difficulty/compensating_invariant/settlement_waterfall_conserves_department_credit_buckets
    """
    ctx = fixtures.setup_running_run(api=api, **MONTHLY_SETUP)

    fixtures.report_success(ctx["run_id"], 45000, api=api)

    scorecard = fixtures.read_scorecard(ctx["department_id"], api=api)
    assert_credit_buckets(
        scorecard, issued=100.00, balance=81.00, escrowed=0.00, consumed=19.00
    )
    assert_scorecard_balanced(scorecard)

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["live_row_count"] == 45000, (
        f"Expected live_row_count 45000, got {dataset['live_row_count']}"
    )
    assert str(dataset["next_due_at"]).startswith("2026-08-31T09:00:00"), (
        f"Expected next_due_at at 2026-08-31T09:00:00Z, got {dataset['next_due_at']!r}"
    )
