"""Calculation precision: the frozen charge chain, the rolling windows and the
derived aggregates of the Winery DTC Shipping Compliance API.

Every figure asserted here is recomputed by hand from the narrative of PRD §2.7
(liters to three decimal places, money in whole integer cents, both rounded half
up, and the per-line-then-sum order for sales tax), the twelve-step chain of
PRD §3.5, the rolling-window and risk arithmetic of PRD §3.4, the winery
aggregate of PRD §3.4, the remittance figures of PRD §3.9 and the renewal
calendar of PRD §3.9.

The harness restarts the server and empties the database before every test, so
each test stands its own landscape up from scratch.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CLOCK_DEFAULT_CANONICAL,
    CLOCK_STARTUP_DEFAULT,
    CONSUMER_BEN,
    DEFAULT_HORIZON_DAYS,
    WINERY_ESTATE_2,
)
from test_helpers.test_users import (
    OFFICER_A,
    OFFICER_A_USER_ID,
    make_winery_operator_headers,
)

# A magnum line and a standard line: 2 x 3000 ml = 6.000 L carries the whole
# large-format surcharge, 2 x 750 ml = 1.500 L carries none (PRD §3.5).
MIXED_FORMAT_LINES = [
    f.order_line(sku="MAGNUM-3000", bottle_ml=3000, bottles=2, unit_price_cents=9000),
    f.order_line(sku="CAB-750", bottle_ml=750, bottles=2, unit_price_cents=4200),
]

# Three unequal bottle sizes, one bottle each: 0.375 + 0.500 + 1.000 = 1.875 L.
INDIVISIBLE_POOL_LINES = [
    f.order_line(sku="HALF-375", bottle_ml=375, bottles=1, unit_price_cents=4200),
    f.order_line(sku="TENTH-500", bottle_ml=500, bottles=1, unit_price_cents=4200),
    f.order_line(sku="LITRE-1000", bottle_ml=1000, bottles=1, unit_price_cents=4200),
]


def _lines_by_index(api, order_id, headers):
    """The order's frozen lines, ordered by ``line_index`` ascending."""
    rows = get_success_data(api.list_order_lines(order_id, headers, {"limit": 100}))
    return sorted(rows, key=lambda row: row["line_index"])


def _by_state(rows):
    return {row["state_code"]: row for row in rows}


# ---------------------------------------------------------------------------
# The twelve-step chain on a mixed-format order
# ---------------------------------------------------------------------------
def test_charge_chain_walks_all_twelve_steps_for_a_mixed_format_order(api, landscape):
    """Every named step of the chain is asserted on its own stored field.

    "`total_liters` is the sum of every line's `line_liters`, rounded half up to
    three decimal places, and `subtotal_cents` is the sum of every line's
    `line_subtotal_cents`." (PRD 3.5)

    "`shipping_gross_cents` is a flat base of 1,500 cents — fifteen dollars —
    plus 220 cents for every litre of `total_liters`, the whole expression
    rounded half up to whole cents." (PRD 3.5)

    "A liter-tier multiplier is selected from `total_liters`: it is 1.00 when
    `total_liters` is at most 9.000 litres, 0.90 when `total_liters` is greater
    than 9.000 litres and at most 18.000 litres, and 0.80 when `total_liters` is
    greater than 18.000 litres." (PRD 3.5)

    "`shipping_discount_cents` is the wine-club shipping concession: when
    `club_subscription_id` is not null it is 2,500 basis points — one quarter —
    of `shipping_tiered_cents`, rounded half up to whole cents; when
    `club_subscription_id` is null it is 0." (PRD 3.5)

    "A large-format surcharge is added on top: the system sums `line_liters`
    across only those lines whose `bottle_ml` is **strictly greater** than 1500 —
    a 1500 ml line contributes exactly zero surcharge litres — rounds that sum
    half up to three decimal places, multiplies it by the state's
    `large_format_surcharge_cents_per_liter`, and rounds half up to whole
    cents." (PRD 3.5)

    "`pre_fee_total_cents` is `subtotal_cents` plus `shipping_cents` plus
    `excise_tax_cents` plus `sales_tax_cents`." (PRD 3.5)

    "`compliance_handling_fee_cents` is 0 when `pre_fee_total_cents` is at least
    20,000 cents — two hundred dollars — and otherwise 900 cents." (PRD 3.5)

    "The order itself opens with `compliance_status` `DRAFT` and
    `fulfillment_status` `UNFULFILLED`" (PRD 3.5)

    Design: Corner/calculations/charge_chain_walks_all_twelve_steps_for_a_mixed_format_order
    """
    order = landscape.create_order(lines=MIXED_FORMAT_LINES)

    a.assert_charge_chain(
        order,
        total_liters=7.500,
        subtotal_cents=26400,
        shipping_gross_cents=3150,
        shipping_tiered_cents=3150,
        shipping_discount_cents=0,
        shipping_cents=3150,
        excise_tax_cents=453,
        sales_tax_cents=2438,
        pre_fee_total_cents=32441,
        compliance_handling_fee_cents=0,
        total_cents=32441,
    )
    a.assert_order_dimensions(
        order, compliance_status="DRAFT", fulfillment_status="UNFULFILLED"
    )
    assert order["rejection_error_id"] is None
    assert order["adult_signature_required"] is True


def test_mixed_format_order_freezes_the_per_line_arithmetic(api, landscape):
    """Step 1 and the step-9 allocation, line by line.

    "For each line, in `line_index` order: `line_liters` is the bottle count
    multiplied by the bottle size in millilitres, divided by 1,000, rounded half
    up to three decimal places; and `line_subtotal_cents` is the bottle count
    multiplied by the per-bottle price in cents." (PRD 3.5)

    "Creation records one line per element of the `lines` array and assigns each
    an `order_id` pointing back at the order plus a `line_index` running from 1
    upward in exactly the request's array order." (PRD 3.5)

    "Each line's `line_taxable_cents` is then its `line_subtotal_cents` plus its
    final `allocated_shipping_cents`, and its `line_sales_tax_cents` is
    `line_taxable_cents` multiplied by the state's `sales_tax_rate_bps` divided
    by 10,000, rounded half up to whole cents." (PRD 3.5)

    Design: Corner/calculations/charge_chain_walks_all_twelve_steps_for_a_mixed_format_order
    """
    order = landscape.create_order(lines=MIXED_FORMAT_LINES)
    lines = _lines_by_index(api, order["id"], landscape.officer)

    assert [row["line_index"] for row in lines] == [1, 2]
    assert [row["order_id"] for row in lines] == [order["id"], order["id"]]

    a.assert_liters(lines[0]["line_liters"], 6.000, "line_liters[1]")
    a.assert_cents(lines[0]["line_subtotal_cents"], 18000, "line_subtotal_cents[1]")
    a.assert_liters(lines[1]["line_liters"], 1.500, "line_liters[2]")
    a.assert_cents(lines[1]["line_subtotal_cents"], 8400, "line_subtotal_cents[2]")

    # The 3150 c pool divides exactly in the 6.000 / 1.500 ratio: 2520 and 630.
    a.assert_cents(lines[0]["allocated_shipping_cents"], 2520, "allocated[1]")
    a.assert_cents(lines[1]["allocated_shipping_cents"], 630, "allocated[2]")
    a.assert_cents(lines[0]["line_taxable_cents"], 20520, "line_taxable_cents[1]")
    a.assert_cents(lines[1]["line_taxable_cents"], 9030, "line_taxable_cents[2]")
    a.assert_cents(lines[0]["line_sales_tax_cents"], 1693, "line_sales_tax_cents[1]")
    a.assert_cents(lines[1]["line_sales_tax_cents"], 745, "line_sales_tax_cents[2]")
    assert lines[0]["line_sales_tax_cents"] + lines[1]["line_sales_tax_cents"] == (
        order["sales_tax_cents"]
    )


# ---------------------------------------------------------------------------
# The indivisible shipping pool: floor, then walk the remainder
# ---------------------------------------------------------------------------
def test_shipping_pool_is_floor_allocated_then_the_remainder_walks_by_liters(
    api, landscape
):
    """Three unequal lines leave exactly one cent to hand out.

    "Each line's raw share of that pool is the pool multiplied by the line's
    `line_liters` divided by the order's `total_liters`; the line's
    `allocated_shipping_cents` is that raw share truncated downward to a whole
    cent." (PRD 3.5)

    "Truncating every line leaves a remainder — the pool less the sum of the
    truncated shares — and those remaining whole cents are handed out one at a
    time, walking the lines ordered by `line_liters` descending and then by
    `line_index` ascending, never by identifier, giving one extra cent to each
    line in turn until the remainder is exhausted." (PRD 3.5)

    "First the pool is assembled: it consists of `shipping_cents` when the
    state's `tax_on_shipping` is true and nothing otherwise, plus
    `excise_tax_cents` when the state's `excise_in_tax_base` is true and nothing
    otherwise." (PRD 3.5)

    Design: Corner/calculations/shipping_pool_is_floor_allocated_then_the_remainder_walks_by_liters
    """
    order = landscape.create_order(lines=INDIVISIBLE_POOL_LINES)
    lines = _lines_by_index(api, order["id"], landscape.officer)

    assert [row["line_index"] for row in lines] == [1, 2, 3]
    a.assert_liters(lines[0]["line_liters"], 0.375, "line_liters[1]")
    a.assert_liters(lines[1]["line_liters"], 0.500, "line_liters[2]")
    a.assert_liters(lines[2]["line_liters"], 1.000, "line_liters[3]")

    # Raw shares of the 1913 c pool are 382.6, 510.133... and 1020.266...; the
    # floors sum to 1912, so the single remaining cent goes to the 1.000 L line.
    assert [row["allocated_shipping_cents"] for row in lines] == [382, 510, 1021]
    assert sum(row["allocated_shipping_cents"] for row in lines) == (
        order["shipping_cents"]
    )


def test_per_line_sales_tax_is_rounded_before_it_is_summed(api, landscape):
    """378 + 389 + 431 is 1198, where a single rounding of the summed base gives 1197.

    "Second, where a tax is computed across several lines, the document states
    explicitly whether rounding happens per line and then sums, or on a summed
    base." (PRD 2.7)

    "The per-line-then-sum order is the one this system uses for sales tax."
    (PRD 2.7)

    "The order's `sales_tax_cents` is the sum of the per-line figures." (PRD 3.5)

    Design: Corner/calculations/shipping_pool_is_floor_allocated_then_the_remainder_walks_by_liters
    """
    order = landscape.create_order(lines=INDIVISIBLE_POOL_LINES)
    lines = _lines_by_index(api, order["id"], landscape.officer)

    assert [row["line_taxable_cents"] for row in lines] == [4582, 4710, 5221]
    assert [row["line_sales_tax_cents"] for row in lines] == [378, 389, 431]
    a.assert_cents(order["sales_tax_cents"], 1198, "sales_tax_cents")


def test_indivisible_pool_order_freezes_the_whole_chain(api, landscape):
    """The exact half at step 3 rounds up and the sub-threshold total pays the fee.

    "**Money** is carried in whole **cents** as integers, rounded **half up**."
    (PRD 2.7)

    "`shipping_gross_cents` is a flat base of 1,500 cents — fifteen dollars —
    plus 220 cents for every litre of `total_liters`, the whole expression
    rounded half up to whole cents." (PRD 3.5)

    "`compliance_handling_fee_cents` is 0 when `pre_fee_total_cents` is at least
    20,000 cents — two hundred dollars — and otherwise 900 cents." (PRD 3.5)

    "`total_cents` is `pre_fee_total_cents` plus `compliance_handling_fee_cents`."
    (PRD 3.5)

    Design: Corner/calculations/shipping_pool_is_floor_allocated_then_the_remainder_walks_by_liters
    """
    order = landscape.create_order(lines=INDIVISIBLE_POOL_LINES)

    a.assert_charge_chain(
        order,
        total_liters=1.875,
        subtotal_cents=12600,
        # 1500 + 220 * 1.875 = 1912.5, and half up takes it to 1913.
        shipping_gross_cents=1913,
        shipping_tiered_cents=1913,
        shipping_discount_cents=0,
        shipping_cents=1913,
        # No bottle exceeds 1500 ml, so there is no surcharge at all.
        excise_tax_cents=88,
        sales_tax_cents=1198,
        pre_fee_total_cents=15799,
        compliance_handling_fee_cents=900,
        total_cents=16699,
    )


# ---------------------------------------------------------------------------
# The small-producer excise credit at its inclusive ceiling
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "gallons,ttb_permit_number,name,expected_excise_cents,expected_total_cents",
    [
        (249999, "TTB-1002", "Estate 2", 211, 30185),
        (250000, "TTB-1003", "Estate 3", 211, 30185),
        (250001, "TTB-1004", "Estate 4", 248, 30222),
    ],
    ids=["one_gallon_below", "exactly_at_the_ceiling", "one_gallon_above"],
)
def test_small_producer_excise_credit_switches_off_one_gallon_past_the_ceiling(
    api, landscape, gallons, ttb_permit_number, name, expected_excise_cents,
    expected_total_cents,
):
    """250,000 gallons still earns the credit; 250,001 earns none.

    "The small-producer credit is then applied: a winery whose
    `annual_production_gallons` is at most 250,000 earns a credit of 1,500 basis
    points — fifteen percent — of the gross excise, while a winery above that
    production figure earns no credit at all." (PRD 3.5)

    "The credit amount is rounded half up to whole cents **before** it is
    subtracted, and the difference is the credited excise." (PRD 3.5)

    "That last figure looks like trivia but is load-bearing: it is the sole input
    that decides whether the winery qualifies for the small-producer excise
    credit described in §3.5." (PRD 3.1)

    Design: Corner/calculations/small_producer_excise_credit_switches_off_one_gallon_past_the_ceiling
    """
    winery = fx.create_winery(
        api,
        name=name,
        ttb_permit_number=ttb_permit_number,
        annual_production_gallons=gallons,
    )
    order = landscape.create_order(
        winery_id=winery["id"],
        headers=make_winery_operator_headers(winery["id"]),
    )

    # Gross excise is round_half_up(4.500 * 55) = 248 with no surcharge litres;
    # the credit is round_half_up(248 * 1500 / 10000) = 37 when it applies.
    a.assert_charge_chain(
        order,
        total_liters=4.500,
        subtotal_cents=25200,
        shipping_cents=2490,
        excise_tax_cents=expected_excise_cents,
        # excise_in_tax_base is false, so the credit never moves the tax base.
        sales_tax_cents=2284,
        total_cents=expected_total_cents,
    )


# ---------------------------------------------------------------------------
# Rolling windows: the inclusive lower edge, the state axis, the consumer axis
# ---------------------------------------------------------------------------
def _seed_rolling_window_ledger(api):
    """Ada carries a TX 12-month window and an NM 30-day window at once."""
    scape = fx.build_landscape(api)
    fx.create_state_rule_nm(api)
    ben = fx.create_consumer(api, **CONSUMER_BEN)
    fx.append_manual_adjustment(
        api, scape.consumer_id, scape.winery_id, 20.000,
        occurred_at="2025-07-31T23:59:59Z",
        reason="Pre-window TX volume, one second outside",
    )
    fx.append_manual_adjustment(
        api, scape.consumer_id, scape.winery_id, 3.000,
        occurred_at="2025-08-01T00:00:00Z",
        reason="Exactly on the 365-day lower edge",
    )
    fx.append_manual_adjustment(
        api, scape.consumer_id, scape.winery_id, 1.250,
        occurred_at="2026-07-15T00:00:00Z",
        reason="Inside the TX window",
    )
    fx.append_manual_adjustment(
        api, scape.consumer_id, scape.winery_id, 5.000, state_code="NM",
        occurred_at="2026-07-20T00:00:00Z",
        reason="Inside the NM 30-day window",
    )
    fx.append_manual_adjustment(
        api, ben["id"], scape.winery_id, 8.000,
        occurred_at="2026-07-15T00:00:00Z",
        reason="Another consumer entirely",
    )
    return scape, ben


def test_rolling_window_counts_the_exact_lower_edge_and_drops_the_instant_before(api):
    """3.000 L on the edge counts, 20.000 L one second earlier does not.

    "`ROLLING_12_MONTHS` admits entries whose `occurred_at` is on or after the
    logical clock instant minus 365 days and on or before the logical clock
    instant." (PRD 3.4)

    "All three windows are **inclusive at the lower edge**: an entry whose
    `occurred_at` is exactly the clock instant minus 365 days is counted."
    (PRD 3.4)

    "`rolling_liters_by_state` then holds, for each state, the signed sum of that
    consumer's ledger entries for that state whose `occurred_at` falls in the
    window, rounded half up to three decimal places — every event type included,
    with `SHIPMENT_ACCEPTED` adding, `RETURN_CREDIT` subtracting, and
    `MANUAL_ADJUSTMENT` doing either according to its sign." (PRD 3.4)

    "`rolling_liters_settled_by_state` is the same sum over the same window,
    restricted to entries whose `order_id` is null or whose order's
    `fulfillment_status` is one of `IN_TRANSIT`, `DELIVERED` or `RETURNED`."
    (PRD 3.4)

    "An optional `state_code` filter narrows the `per_state` map to one state."
    (PRD 3.4)

    Design: Corner/calculations/rolling_window_counts_the_exact_lower_edge_and_drops_the_instant_before
    """
    scape, ben = _seed_rolling_window_ledger(api)

    ada = scape.read_consumer()
    a.assert_liters(ada["rolling_liters_by_state"]["TX"], 4.250, "rolling TX")
    a.assert_liters(ada["rolling_liters_by_state"]["NM"], 5.000, "rolling NM")
    # Every seeded entry is a manual adjustment, so order_id is null throughout
    # and the settled map equals the gross map.
    a.assert_liters(ada["rolling_liters_settled_by_state"]["TX"], 4.250, "settled TX")
    a.assert_liters(ada["rolling_liters_settled_by_state"]["NM"], 5.000, "settled NM")

    # The filter is per consumer: Ben's 8.000 L never reaches Ada's map.
    other = scape.read_consumer(ben["id"])
    a.assert_liters(other["rolling_liters_by_state"]["TX"], 8.000, "Ben rolling TX")

    tx_view = scape.volume_summary(state_code="TX")
    assert tx_view["consumer_id"] == scape.consumer_id
    a.assert_instant_equals(tx_view["as_of"], CLOCK_DEFAULT_CANONICAL)
    assert set(tx_view["per_state"].keys()) == {"TX"}

    nm_view = scape.volume_summary(state_code="NM")
    assert set(nm_view["per_state"].keys()) == {"NM"}

    both = scape.volume_summary()
    assert set(both["per_state"].keys()) == {"NM", "TX"}


def test_utilisation_picks_the_greatest_ratio_while_audit_ignores_the_window(api):
    """NM wins the screening ratio; the all-time audit variant picks TX instead.

    "The third factor is a utilisation term: among the states present in the
    relevant liters map, the system selects the state with the greatest ratio of
    accumulated liters to that state's `per_consumer_limit_liters`, breaking a tie
    in favour of the alphabetically earlier `state_code`; the factor is then 30
    multiplied by the selected state's liters divided by that state's
    per-consumer limit, truncated downward to a whole number, and capped at 30."
    (PRD 3.4)

    "The **audit** variant is written to `risk_score_audit` and never gates any
    operation: its scope is every ledger entry of the consumer for all time and
    every `DENIED` exception for all time, regardless of the source order's
    `fulfillment_status`, and its utilisation term reads the all-time, all-status
    liters per state." (PRD 3.4)

    "From the screening score alone the system derives `screening_tier`, which is
    `STANDARD` while `risk_score_screening` is below 50 and becomes `ELEVATED` as
    soon as `risk_score_screening` reaches 50 or more." (PRD 3.4)

    Design: Corner/calculations/rolling_window_counts_the_exact_lower_edge_and_drops_the_instant_before
    """
    scape, _ = _seed_rolling_window_ledger(api)

    # Screening scope: NM 5.000 / 9.000 beats TX 4.250 / 27.000, so the factor is
    # floor(30 * 5.000 / 9.000) = 16.  Audit scope: TX 24.250 / 27.000 beats NM,
    # so the factor is floor(30 * 24.250 / 27.000) = 26.
    ada = scape.read_consumer()
    assert ada["risk_score_screening"] == 16
    assert ada["risk_score_audit"] == 26
    assert ada["screening_tier"] == "STANDARD"
    assert ada["return_credit_count"] == 0
    assert ada["denied_exception_count"] == 0

    summary = scape.volume_summary()
    assert summary["risk_score_screening"] == 16
    assert summary["risk_score_audit"] == 26
    assert summary["screening_tier"] == "STANDARD"
    assert summary["return_credit_count"] == 0
    assert summary["denied_exception_count"] == 0


# ---------------------------------------------------------------------------
# The renewal calendar's default and overridden horizon
# ---------------------------------------------------------------------------
def _renewal_calendar_winery(api):
    """One winery, two states, two ACTIVE permits expiring far apart."""
    fx.set_clock(api, CLOCK_STARTUP_DEFAULT)
    winery = fx.create_winery(api)
    fx.create_state_rule(api)
    fx.create_state_rule(
        api, state_code="OR", reporting_frequency="ANNUAL", zero_filing_required=False
    )
    fx.create_active_permit(api, winery["id"], expiration_date="2026-10-15")
    fx.create_active_permit(
        api, winery["id"], state_code="OR", permit_number="OR-DTC-1",
        effective_date="2026-06-01", expiration_date="2027-06-01",
    )
    return winery


def test_renewal_calendar_default_horizon_is_ninety_days(api):
    """With `horizon_days` omitted only the TX permit is inside the look-ahead.

    "The last piece of the reporting picture is the **renewal calendar**, a
    computed read available to a `ComplianceOfficer` or the owning
    `WineryOperator` for a supplied `winery_id`, with an optional `horizon_days`
    look-ahead that defaults to 90 days and must lie between 1 and 365." (PRD 3.9)

    "For each remaining permit the system computes a `renewal_due_date` equal to
    the permit's `expiration_date` less the governing state rule's
    `renewal_lead_days` days, and then assigns a `calendar_status` by testing four
    conditions **in this order**: the status is `OVERDUE` when `renewal_due_date`
    falls strictly before the logical clock date and the permit is not in
    `RENEWAL_FILED`; otherwise it is `FILED` when the permit is in
    `RENEWAL_FILED`; otherwise it is `DUE` when `renewal_due_date` falls on or
    before the logical clock date plus `horizon_days` days; and otherwise it is
    `SCHEDULED`." (PRD 3.9)

    "Only permits whose `calendar_status` is `OVERDUE`, `FILED` or `DUE` appear in
    `permits_expiring`; `SCHEDULED` permits are outside the horizon and are
    omitted." (PRD 3.9)

    "A `MONTHLY` state's `report_period` runs from the first day of the month
    before the logical clock's month, inclusive, to the first day of the logical
    clock's own month, exclusive, and its `report_due_date` is the 15th of the
    logical clock's month." (PRD 3.9)

    Design: Corner/calculations/renewal_calendar_default_horizon_is_ninety_days_and_is_overridable
    """
    winery = _renewal_calendar_winery(api)

    body = get_success_data(
        api.get_renewal_calendar(OFFICER_A, {"winery_id": winery["id"]})
    )
    assert body["winery_id"] == winery["id"]
    assert body["horizon_days"] == DEFAULT_HORIZON_DAYS
    a.assert_instant_equals(body["as_of"], CLOCK_DEFAULT_CANONICAL)

    # 2026-10-15 less 45 days is 2026-08-31, inside 2026-08-01 plus 90 days
    # (2026-10-30); the OR permit's 2027-04-17 is not, so it is SCHEDULED and
    # therefore omitted.
    permits = body["permits_expiring"]
    assert [row["state_code"] for row in permits] == ["TX"]
    assert permits[0]["renewal_due_date"] == "2026-08-31"
    assert permits[0]["calendar_status"] == "DUE"

    reports = body["reports_due"]
    assert [row["state_code"] for row in reports] == ["TX"]
    assert reports[0]["period_type"] == "MONTHLY"
    assert reports[0]["report_due_date"] == "2026-08-15"
    assert reports[0]["report_filed"] is False


def test_renewal_calendar_horizon_is_overridable(api):
    """A 300-day horizon pulls the OR permit and its annual report into view.

    "It answers with the `winery_id`, an `as_of` instant from the logical clock,
    the effective `horizon_days`, and two ordered lists: `permits_expiring` and
    `reports_due`." (PRD 3.9)

    "The list is ordered by `renewal_due_date` ascending and then by `state_code`
    ascending." (PRD 3.9)

    "An `ANNUAL` state's `report_period` runs from January 1 of the year before
    the logical clock's year, inclusive, to January 1 of the logical clock's own
    year, exclusive, and its `report_due_date` is January 31 of the logical
    clock's year." (PRD 3.9)

    "The `reports_due` list is ordered by `report_due_date` ascending and then by
    `state_code` ascending." (PRD 3.9)

    "Each entry also carries `report_filed`, which is true exactly when a
    remittance already exists for that winery, that `state_code`, that
    `period_type`, and that period's `period_start` and `period_end` with a
    `status` of either `FILED` or `REMITTED`." (PRD 3.9)

    Design: Corner/calculations/renewal_calendar_default_horizon_is_ninety_days_and_is_overridable
    """
    winery = _renewal_calendar_winery(api)

    body = get_success_data(
        api.get_renewal_calendar(
            OFFICER_A, {"winery_id": winery["id"], "horizon_days": 300}
        )
    )
    assert body["horizon_days"] == 300

    # 2026-08-01 plus 300 days is 2027-05-28, so 2027-04-17 is now DUE too.
    permits = body["permits_expiring"]
    assert [row["state_code"] for row in permits] == ["TX", "OR"]
    assert [row["renewal_due_date"] for row in permits] == ["2026-08-31", "2027-04-17"]
    assert [row["calendar_status"] for row in permits] == ["DUE", "DUE"]

    reports = body["reports_due"]
    assert [row["state_code"] for row in reports] == ["OR", "TX"]
    by_state = _by_state(reports)
    assert by_state["OR"]["period_type"] == "ANNUAL"
    assert by_state["OR"]["report_due_date"] == "2026-01-31"
    assert by_state["OR"]["report_filed"] is False
    assert by_state["TX"]["period_type"] == "MONTHLY"
    assert by_state["TX"]["report_due_date"] == "2026-08-15"
    assert by_state["TX"]["report_filed"] is False


# ---------------------------------------------------------------------------
# The winery's calendar-year state aggregate, netted by a return
# ---------------------------------------------------------------------------
WY_SHIP_TO = {"ship_to_state_code": "WY", "ship_to_zip": "82001"}
SINGLE_BOTTLE_LINES = [f.order_line(bottles=1)]


def _build_wy_scenario(api):
    """Two 4.500 L orders fill a 9.000 L annual limit, then one comes back."""
    scape = fx.build_landscape(
        api,
        state_rule_overrides={
            "state_code": "WY",
            "per_winery_annual_limit_liters": 9.000,
        },
        permit_overrides={"state_code": "WY", "permit_number": "WY-DTC-1"},
        program_overrides={"states_served": ["WY"]},
        consumer_overrides={"state_code": "WY", "zip_code": "82001"},
    )
    order_a = scape.create_cleared_order(**WY_SHIP_TO)
    order_b = scape.create_cleared_order(**WY_SHIP_TO)

    over_limit = scape.create_order(lines=SINGLE_BOTTLE_LINES, **WY_SHIP_TO)
    screened_over_limit = scape.screen(over_limit["id"])

    shipment_b = scape.label(order_b["id"])
    scape.pickup(shipment_b["id"])
    scape.return_to_sender(shipment_b["id"])
    rows_after_return = scape.ledger_rows(
        winery_id=scape.winery_id, state_code="WY"
    )

    after_return = scape.create_order(lines=SINGLE_BOTTLE_LINES, **WY_SHIP_TO)
    screened_after_return = scape.screen(after_return["id"])

    return {
        "scape": scape,
        "order_a": order_a,
        "order_b": order_b,
        "over_limit": screened_over_limit,
        "rows_after_return": rows_after_return,
        "after_return": screened_after_return,
    }


def test_winery_annual_state_liters_gates_at_equality_then_frees_after_a_return(api):
    """9.000 L exactly clears, the next 0.750 L is referred, and the return frees it.

    "The winery's calendar-year accumulated liters into the destination state plus
    this order's `total_liters` must be at most the state's
    `per_winery_annual_limit_liters`. Equality clears; exceeding fails with
    `ERR_WINERY_VOLUME_LIMIT_EXCEEDED`. This failure is **overridable**."
    (PRD 3.6)

    "The **winery's** annual state volume is a separate aggregate with a fixed
    window: for a winery-and-state pair it is the signed sum, rounded half up to
    three decimal places, of all ledger entries for that pair — across every
    consumer, every event type — whose `occurred_at` falls on or after January 1
    at `00:00:00.000Z` of the logical clock's calendar year and on or before the
    logical clock instant." (PRD 3.4)

    "A **`DRAFT` → `OVERRIDE_PENDING`** outcome likewise writes the overridable
    identifier into `rejection_error_id` and appends no ledger entry — the liters
    are not reserved while the exception is pending." (PRD 3.6)

    Design: Corner/calculations/winery_annual_state_liters_accumulates_then_nets_out_a_returned_shipment
    """
    built = _build_wy_scenario(api)
    scape = built["scape"]

    # 4.500 + 4.500 == 9.000, and equality clears.
    a.assert_order_dimensions(built["order_b"], compliance_status="CLEARED")

    # 9.000 + 0.750 exceeds 9.000, and the failure is overridable.
    a.assert_order_dimensions(built["over_limit"], compliance_status="OVERRIDE_PENDING")
    a.assert_rejection(built["over_limit"], "ERR_WINERY_VOLUME_LIMIT_EXCEEDED")
    assert scape.ledger_rows(order_id=built["over_limit"]["id"]) == []

    # The return released 4.500 L, so 4.500 + 0.750 fits again.
    a.assert_order_dimensions(built["after_return"], compliance_status="CLEARED")
    a.assert_rejection(built["after_return"], None)


def test_returned_shipment_nets_the_aggregate_without_erasing_the_original_debit(api):
    """The compensating entry sits beside the original rows rather than replacing them.

    "Because the order became `RETURNED`, a ledger entry with `event_type`
    `RETURN_CREDIT` is appended carrying `liters` equal to negative
    `total_liters`, `order_id` set, `shipment_id` set to this shipment, and
    `occurred_at` at the logical clock; the order's `excise_reversed_cents` is set
    to its `excise_tax_cents` and its `sales_tax_reversed_cents` to its
    `sales_tax_cents`; and the winery's `excise_reversed_cents` grows by the
    order's `excise_tax_cents`." (PRD 3.7)

    "Note what a return does **not** do: it leaves the order's
    `compliance_status` at `CLEARED`." (PRD 3.7)

    "The winery's `excise_accrued_cents` grows by the order's `excise_tax_cents` —
    that counter is the running sum of `excise_tax_cents` across every order of
    the winery that has reached `CLEARED` at least once — and `Winery.version`
    increments by 1." (PRD 3.7)

    "`return_credit_count` is the number of that consumer's ledger entries with
    `event_type` `RETURN_CREDIT` falling inside the widest `per_consumer_period`
    window in play" (PRD 3.4)

    Design: Corner/calculations/winery_annual_state_liters_accumulates_then_nets_out_a_returned_shipment
    """
    built = _build_wy_scenario(api)
    scape = built["scape"]

    # Two SHIPMENT_ACCEPTED rows of 4.500 and one RETURN_CREDIT row of -4.500.
    rows = built["rows_after_return"]
    assert len(rows) == 3
    assert sorted(row["event_type"] for row in rows) == [
        "RETURN_CREDIT",
        "SHIPMENT_ACCEPTED",
        "SHIPMENT_ACCEPTED",
    ]
    credits = [row for row in rows if row["event_type"] == "RETURN_CREDIT"]
    a.assert_ledger_entry(
        credits[0], event_type="RETURN_CREDIT", liters=-4.500, state_code="WY",
        order_id=built["order_b"]["id"],
    )
    a.assert_ledger_sums_to(rows, 4.500)

    returned = scape.read_order(built["order_b"]["id"])
    a.assert_order_dimensions(
        returned, compliance_status="CLEARED", fulfillment_status="RETURNED"
    )
    a.assert_instant_equals(returned["returned_at"], CLOCK_DEFAULT_CANONICAL)
    a.assert_cents(returned["excise_reversed_cents"], 211, "excise_reversed_cents")

    # 211 + 211 for the two 4.500 L orders and 35 for the 0.750 L order that
    # cleared after the return; only the returned order was reversed.
    winery = scape.read_winery()
    a.assert_cents(winery["excise_accrued_cents"], 457, "excise_accrued_cents")
    a.assert_cents(winery["excise_reversed_cents"], 211, "excise_reversed_cents")

    consumer = scape.read_consumer()
    assert consumer["return_credit_count"] == 1
    a.assert_liters(consumer["rolling_liters_by_state"]["WY"], 5.250, "rolling WY")


# ---------------------------------------------------------------------------
# A remittance that nets a return landing inside its own period
# ---------------------------------------------------------------------------
def _build_july_remittance_scenario(api):
    """Two July orders, one delivered on the 25th and one returned on the 25th."""
    scape = fx.build_landscape(api, clock="2026-07-10T00:00:00Z")

    order_a = scape.create_cleared_order()
    shipment_a = scape.label(order_a["id"])
    scape.pickup(shipment_a["id"])

    fx.set_clock(api, "2026-07-20T00:00:00Z")
    order_b = scape.create_cleared_order()
    shipment_b = scape.label(order_b["id"])
    scape.pickup(shipment_b["id"])

    fx.set_clock(api, "2026-07-25T00:00:00Z")
    scape.deliver(shipment_a["id"])
    scape.return_to_sender(shipment_b["id"])

    fx.set_clock(api, CLOCK_STARTUP_DEFAULT)
    remittance = scape.open_remittance(
        "TX", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
    )
    return {
        "scape": scape,
        "order_a": order_a,
        "order_b": order_b,
        "remittance": remittance,
    }


def test_remittance_nets_a_return_that_landed_inside_the_filing_period(api):
    """Both July orders accrue; only the returned one is reversed out again.

    "From the selected set the remittance records: `excise_accrued_cents`, the sum
    of `excise_tax_cents` across the selected orders; `sales_tax_accrued_cents`,
    the sum of their `sales_tax_cents`; `excise_reversed_cents` and
    `sales_tax_reversed_cents`, the same two sums restricted to those selected
    orders whose `returned_at` is non-null and falls **strictly before**
    `period_end`; `excise_due_cents`, the accrued excise less the reversed excise;
    `sales_tax_due_cents`, the accrued sales tax less the reversed sales tax;
    `liters_total`, the sum of the selected orders' `total_liters` rounded half up
    to three decimal places; `shipment_count`, the count of selected orders; and
    `included_order_ids`, the identifiers of the selected orders ordered by
    `cleared_at` ascending and then by `created_at` ascending." (PRD 3.9)

    "Under **`ACCRUAL_BASIS`**, the selected orders are those whose
    `compliance_status` is `CLEARED` and whose `cleared_at` falls inside the
    half-open period." (PRD 3.9)

    Design: Corner/calculations/remittance_nets_a_return_that_landed_inside_the_filing_period
    """
    built = _build_july_remittance_scenario(api)
    remittance = built["remittance"]

    assert remittance["status"] == "OPEN"
    assert remittance["basis"] == "ACCRUAL_BASIS"
    assert remittance["shipment_count"] == 2
    a.assert_liters(remittance["liters_total"], 9.000, "liters_total")
    assert remittance["included_order_ids"] == [
        built["order_a"]["id"],
        built["order_b"]["id"],
    ]

    # Two 4.500 L TX orders: 211 cents of excise and 2284 of sales tax each.
    a.assert_cents(remittance["excise_accrued_cents"], 422, "excise_accrued_cents")
    a.assert_cents(
        remittance["sales_tax_accrued_cents"], 4568, "sales_tax_accrued_cents"
    )
    # Only order B came back, and it came back before 2026-08-01.
    a.assert_cents(remittance["excise_reversed_cents"], 211, "excise_reversed_cents")
    a.assert_cents(
        remittance["sales_tax_reversed_cents"], 2284, "sales_tax_reversed_cents"
    )
    a.assert_cents(remittance["excise_due_cents"], 211, "excise_due_cents")
    a.assert_cents(remittance["sales_tax_due_cents"], 2284, "sales_tax_due_cents")


def test_remittance_figures_are_frozen_at_creation_and_filing_stamps_the_officer(api):
    """The winery counters and the per-order reversals agree with the filing.

    "All of a remittance's figures are computed once, at creation, from the `basis`
    field, and then frozen onto the row." (PRD 3.9)

    "Filing lodges the return with the state, moving the remittance `OPEN` →
    `FILED`, and is available only from `OPEN`" (PRD 3.9)

    "On success, `filed_at` is stamped from the logical clock and
    `filed_by_user_id` records the filing officer's `X-User-ID`." (PRD 3.9)

    Design: Corner/calculations/remittance_nets_a_return_that_landed_inside_the_filing_period
    """
    built = _build_july_remittance_scenario(api)
    scape = built["scape"]

    filed = get_success_data(
        api.file_remittance(built["remittance"]["id"], None, OFFICER_A)
    )
    assert filed["status"] == "FILED"
    a.assert_instant_equals(filed["filed_at"], CLOCK_DEFAULT_CANONICAL)
    assert filed["filed_by_user_id"] == OFFICER_A_USER_ID

    # Filing changed no figure.
    a.assert_cents(filed["excise_due_cents"], 211, "excise_due_cents")
    a.assert_cents(filed["sales_tax_due_cents"], 2284, "sales_tax_due_cents")
    assert filed["shipment_count"] == 2

    # The delivered order was never reversed; the returned one was.
    order_a = scape.read_order(built["order_a"]["id"])
    a.assert_cents(order_a["excise_reversed_cents"], 0, "excise_reversed_cents")
    a.assert_cents(order_a["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents")
    order_b = scape.read_order(built["order_b"]["id"])
    a.assert_cents(order_b["excise_reversed_cents"], 211, "excise_reversed_cents")
    a.assert_cents(order_b["sales_tax_reversed_cents"], 2284, "sales_tax_reversed_cents")

    winery = scape.read_winery()
    a.assert_cents(winery["excise_accrued_cents"], 422, "excise_accrued_cents")
    a.assert_cents(winery["excise_reversed_cents"], 211, "excise_reversed_cents")


# ---------------------------------------------------------------------------
# A club run whose candidate set is empty
# ---------------------------------------------------------------------------
def test_club_run_with_no_eligible_subscription_is_an_empty_success(api):
    """A future schedule and another winery's club leave nothing to generate.

    "Candidate selection considers only subscriptions of the requested winery
    whose `status` is `ACTIVE` or `WEATHER_HELD`, whose `next_run_date` is non-null
    and falls on or before the `run_date`, and whose `remaining_allotment` — always
    `annual_allotment` less `consumed_shipments`, and never negative — is at least
    1." (PRD 3.8)

    "An empty candidate set is not an error: the run answers HTTP 200 with
    `generated_count` 0 and an empty `generated_order_ids` array." (PRD 3.8)

    "The run answers with the `winery_id` and `run_date` it acted on, a
    `generated_count` and `skipped_count`, a `generated_order_ids` array listing
    the orders it created in processing order, and a `skipped_subscription_ids`
    array listing the candidates it passed over." (PRD 3.8)

    Design: Corner/calculations/club_run_with_no_eligible_subscription_is_an_empty_success
    """
    scape = fx.build_landscape(api)
    other_winery = fx.create_winery(api, **WINERY_ESTATE_2)

    # Due only in September, so not a candidate for an August run.
    not_yet_due = scape.create_subscription(next_run_date="2026-09-01")
    # Due today, but it belongs to a different winery's club.
    other_club = scape.create_subscription(
        winery_id=other_winery["id"], next_run_date="2026-08-01", headers=OFFICER_A
    )

    run = scape.club_run("2026-08-01")

    assert run["winery_id"] == scape.winery_id
    assert run["run_date"] == "2026-08-01"
    assert run["generated_count"] == 0
    assert run["skipped_count"] == 0
    assert run["generated_order_ids"] == []
    assert run["skipped_subscription_ids"] == []

    # A run that generated nothing advanced nothing and blamed nobody.
    untouched = scape.read_subscription(not_yet_due["id"])
    assert untouched["status"] == "ACTIVE"
    assert untouched["next_run_date"] == "2026-09-01"
    assert untouched["missed_run_count"] == 0
    assert untouched["consumed_shipments"] == 0
    assert untouched["remaining_allotment"] == 12

    foreign = scape.read_subscription(other_club["id"])
    assert foreign["status"] == "ACTIVE"
    assert foreign["next_run_date"] == "2026-08-01"
    assert foreign["missed_run_count"] == 0
    assert foreign["consumed_shipments"] == 0

    orders, _meta = validate_paginated(api.list_orders(OFFICER_A, {"limit": 100}))
    assert orders == []
