"""Boundary precision: the exact edge, and the smallest possible step past it.

Three thresholds of the contract are walked from both sides here: the
per-consumer volume ceiling of PRD §3.6, where equality clears and any excess at
all fails; the liter-tier multiplier of PRD §3.5 step 4, where the comparison is
"at most 9.000 litres" rather than "below"; and the filing-substance threshold of
PRD §3.9, where a `shipment_count` of exactly 1 files and 0 files only where the
state demands zero filings.

Every cent and every litre asserted below was recomputed from the twelve-step
chain of PRD §3.5 and the rounding discipline of PRD §2.7.  Screening outcomes are
read from the order body, because PRD §2.9 says screening never returns an error
envelope.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_charge_chain,
    assert_instant_equals,
    assert_ledger_sums_to,
    assert_liters,
    assert_order_dimensions,
    assert_rejection,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.fixtures import (
    add_nm_state,
    append_manual_adjustment,
    build_landscape,
    set_clock,
)
from test_helpers.test_users import OFFICER_A

CLOCK_JULY_10 = "2026-07-10T00:00:00Z"
CLOCK_AUG_1 = "2026-08-01T00:00:00Z"


def _line(bottles, bottle_ml=750, unit_price_cents=4200, sku="CAB-750"):
    return [
        {
            "sku": sku,
            "bottle_ml": bottle_ml,
            "bottles": bottles,
            "unit_price_cents": unit_price_cents,
        }
    ]


# =========================================================================
# boundary_precision_check /
# consumer_volume_limit_exact_equality_clears_then_one_bottle_breaches
# =========================================================================
def _headroom_of_exactly_4500_landscape(api):
    """22.500 L already inside the rolling window against a 27.000 L TX ceiling.

    The adjustment is dated 2026-07-15, inside the ROLLING_12_MONTHS window of the
    2026-08-01 clock, so exactly 4.500 L of headroom is left.
    """
    scape = build_landscape(api)
    append_manual_adjustment(
        api,
        scape.consumer_id,
        scape.winery_id,
        22.500,
        state_code="TX",
        occurred_at="2026-07-15T00:00:00Z",
    )
    return scape


def test_rolling_volume_landing_exactly_on_the_consumer_limit_clears(api):
    """22.500 + 4.500 == 27.000 is on the limit, and the order clears.

    PRD §3.6: "The consumer's accumulated rolling liters for the destination
    state, taken from `rolling_liters_by_state`, plus this order's
    `total_liters`, must be at most the state's `per_consumer_limit_liters`."
    and "Landing exactly on the limit clears; exceeding it by any amount at all
    fails with `ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED`."

    PRD §2.7: "**Volume** is carried in liters with exactly **3 decimal places**,
    rounded **half up**."

    Design: Difficulty/boundary_precision_check/consumer_volume_limit_exact_equality_clears_then_one_bottle_breaches
    """
    scape = _headroom_of_exactly_4500_landscape(api)
    order = scape.create_order(lines=_line(6))

    screened = validate_success(api.screen_order(order["id"], {}, OFFICER_A), 200)

    assert_order_dimensions(
        screened, compliance_status="CLEARED", fulfillment_status="UNFULFILLED"
    )
    assert screened["rejection_error_id"] is None, (
        f"A cleared order carries no recorded failure, got "
        f"{screened['rejection_error_id']!r}"
    )
    assert_instant_equals(screened["cleared_at"], CLOCK_STARTUP_DEFAULT)
    assert_charge_chain(
        screened,
        total_liters=4.500,
        subtotal_cents=25200,
        shipping_gross_cents=2490,
        shipping_tiered_cents=2490,
        shipping_discount_cents=0,
        shipping_cents=2490,
        excise_tax_cents=211,
        sales_tax_cents=2284,
        pre_fee_total_cents=30185,
        compliance_handling_fee_cents=0,
        total_cents=30185,
    )

    consumer = scape.read_consumer()
    assert_liters(consumer["rolling_liters_by_state"]["TX"], 27.000, "rolling TX liters")
    assert_cents(
        scape.read_winery()["excise_accrued_cents"], 211, "excise_accrued_cents"
    )


def test_one_further_bottle_past_the_consumer_limit_parks_the_order(api):
    """27.000 + 0.750 == 27.750 exceeds the ceiling by the smallest step available.

    PRD §3.6: "Landing exactly on the limit clears; exceeding it by any amount at
    all fails with `ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED`." and "This failure is
    **overridable**."

    PRD §3.5: "`compliance_handling_fee_cents` is 0 when `pre_fee_total_cents` is
    at least 20,000 cents — two hundred dollars — and otherwise 900 cents."

    Design: Difficulty/boundary_precision_check/consumer_volume_limit_exact_equality_clears_then_one_bottle_breaches
    """
    scape = _headroom_of_exactly_4500_landscape(api)
    at_the_limit = scape.create_order(lines=_line(6))
    cleared = scape.screen(at_the_limit["id"])
    assert_order_dimensions(cleared, compliance_status="CLEARED")

    one_bottle = scape.create_order(lines=_line(1))
    screened = validate_success(api.screen_order(one_bottle["id"], {}, OFFICER_A), 200)

    assert_rejection(screened, "ERR_CONSUMER_VOLUME_LIMIT_EXCEEDED")
    assert_order_dimensions(
        screened, compliance_status="OVERRIDE_PENDING", fulfillment_status="UNFULFILLED"
    )
    assert_charge_chain(
        screened,
        total_liters=0.750,
        subtotal_cents=4200,
        shipping_gross_cents=1665,
        shipping_tiered_cents=1665,
        shipping_discount_cents=0,
        shipping_cents=1665,
        excise_tax_cents=35,
        sales_tax_cents=484,
        pre_fee_total_cents=6384,
        compliance_handling_fee_cents=900,
        total_cents=7284,
    )


def test_the_override_pending_order_leaves_the_rolling_total_on_the_limit(api):
    """The breaching screen reserves nothing: the ledger keeps exactly two rows.

    PRD §3.6: "A **`DRAFT` → `OVERRIDE_PENDING`** outcome likewise writes the
    overridable identifier into `rejection_error_id` and appends no ledger entry —
    the liters are not reserved while the exception is pending."

    PRD §3.4: "`rolling_liters_by_state` then holds, for each state, the signed sum
    of that consumer's ledger entries for that state whose `occurred_at` falls in
    the window, rounded half up to three decimal places — every event type
    included, with `SHIPMENT_ACCEPTED` adding, `RETURN_CREDIT` subtracting, and
    `MANUAL_ADJUSTMENT` doing either according to its sign."

    Design: Difficulty/boundary_precision_check/consumer_volume_limit_exact_equality_clears_then_one_bottle_breaches
    """
    scape = _headroom_of_exactly_4500_landscape(api)
    at_the_limit = scape.create_order(lines=_line(6))
    scape.screen(at_the_limit["id"])
    one_bottle = scape.create_order(lines=_line(1))
    scape.screen(one_bottle["id"])

    rows = scape.ledger_rows(consumer_id=scape.consumer_id)
    assert len(rows) == 2, f"Expected exactly two ledger rows, got {rows}"
    event_types = sorted(row["event_type"] for row in rows)
    assert event_types == ["MANUAL_ADJUSTMENT", "SHIPMENT_ACCEPTED"], event_types
    assert_ledger_sums_to(rows, 27.000)

    by_order = {row["order_id"]: row for row in rows}
    assert one_bottle["id"] not in by_order, (
        "the OVERRIDE_PENDING order must not have appended a ledger entry"
    )
    assert_liters(by_order[at_the_limit["id"]]["liters"], 4.500, "liters")

    consumer = scape.read_consumer()
    assert_liters(consumer["rolling_liters_by_state"]["TX"], 27.000, "rolling TX liters")
    assert_cents(
        scape.read_winery()["excise_accrued_cents"], 211, "excise_accrued_cents"
    )


# =========================================================================
# boundary_precision_check / shipping_liter_tier_multiplier_at_exactly_nine_liters
# =========================================================================
def test_total_liters_exactly_at_the_tier_edge_keeps_the_multiplier_at_one(api):
    """12 x 750 ml is exactly 9.000 L, so shipping stays at the untiered 3480 cents.

    PRD §3.5: "A liter-tier multiplier is selected from `total_liters`: it is 1.00
    when `total_liters` is at most 9.000 litres, 0.90 when `total_liters` is
    greater than 9.000 litres and at most 18.000 litres, and 0.80 when
    `total_liters` is greater than 18.000 litres."

    PRD §3.5: "`shipping_gross_cents` is a flat base of 1,500 cents — fifteen
    dollars — plus 220 cents for every litre of `total_liters`, the whole
    expression rounded half up to whole cents." and "`shipping_tiered_cents` is
    `shipping_gross_cents` multiplied by that tier multiplier, rounded half up to
    whole cents."

    Design: Difficulty/boundary_precision_check/shipping_liter_tier_multiplier_at_exactly_nine_liters
    """
    scape = build_landscape(api)
    order = scape.create_order(lines=_line(12))

    screened = validate_success(api.screen_order(order["id"], {}, OFFICER_A), 200)

    assert_order_dimensions(screened, compliance_status="CLEARED")
    assert_charge_chain(
        screened,
        total_liters=9.000,
        subtotal_cents=50400,
        shipping_gross_cents=3480,
        shipping_tiered_cents=3480,
        shipping_discount_cents=0,
        shipping_cents=3480,
        excise_tax_cents=421,
        sales_tax_cents=4445,
        pre_fee_total_cents=58746,
        compliance_handling_fee_cents=0,
        total_cents=58746,
    )


def test_one_step_past_the_tier_edge_applies_the_zero_point_nine_multiplier(api):
    """16 x 750 ml is 12.000 L, so the gross 4140 is tiered down to 3726 cents.

    PRD §3.5: "A liter-tier multiplier is selected from `total_liters`: it is 1.00
    when `total_liters` is at most 9.000 litres, 0.90 when `total_liters` is
    greater than 9.000 litres and at most 18.000 litres, and 0.80 when
    `total_liters` is greater than 18.000 litres."

    PRD §2.7: "First, **every step that this document names as a rounding point
    rounds, and no intermediate is ever rounded twice**: if the charge chain says
    shipping is rounded to whole cents at one step and the tier multiplier is
    applied at a later step, the later step multiplies the already-rounded value
    and rounds again — it does not revisit the unrounded original."

    Design: Difficulty/boundary_precision_check/shipping_liter_tier_multiplier_at_exactly_nine_liters
    """
    scape = build_landscape(api)
    at_the_edge = scape.create_order(lines=_line(12))
    scape.screen(at_the_edge["id"])

    order = scape.create_order(lines=_line(16))
    screened = validate_success(api.screen_order(order["id"], {}, OFFICER_A), 200)

    assert_order_dimensions(screened, compliance_status="CLEARED")
    assert_charge_chain(
        screened,
        total_liters=12.000,
        subtotal_cents=67200,
        shipping_gross_cents=4140,
        shipping_tiered_cents=3726,
        shipping_discount_cents=0,
        shipping_cents=3726,
        excise_tax_cents=561,
        sales_tax_cents=5851,
        pre_fee_total_cents=77338,
        compliance_handling_fee_cents=0,
        total_cents=77338,
    )
    consumer = scape.read_consumer()
    assert_liters(consumer["rolling_liters_by_state"]["TX"], 21.000, "rolling TX liters")


def test_both_sides_of_the_tier_edge_accrue_their_own_credited_excise(api):
    """The 9.000 L and 12.000 L orders accrue 421 + 561 == 982 cents of excise.

    PRD §3.5: "The small-producer credit is then applied: a winery whose
    `annual_production_gallons` is at most 250,000 earns a credit of 1,500 basis
    points — fifteen percent — of the gross excise, while a winery above that
    production figure earns no credit at all."

    PRD §3.6: "The winery's `excise_accrued_cents` grows by the order's
    `excise_tax_cents` — that counter is the running sum of `excise_tax_cents`
    across every order of the winery that has reached `CLEARED` at least once —
    and `Winery.version` increments by 1."

    Design: Difficulty/boundary_precision_check/shipping_liter_tier_multiplier_at_exactly_nine_liters
    """
    scape = build_landscape(api)
    at_the_edge = scape.screen(scape.create_order(lines=_line(12))["id"])
    one_tier_up = scape.screen(scape.create_order(lines=_line(16))["id"])

    assert_cents(at_the_edge["excise_tax_cents"], 421, "excise_tax_cents")
    assert_cents(one_tier_up["excise_tax_cents"], 561, "excise_tax_cents")
    assert_order_dimensions(at_the_edge, compliance_status="CLEARED")
    assert_order_dimensions(one_tier_up, compliance_status="CLEARED")
    assert_cents(
        scape.read_winery()["excise_accrued_cents"], 982, "excise_accrued_cents"
    )


# =========================================================================
# boundary_precision_check / remittance_zero_shipment_period_at_the_filing_threshold
# =========================================================================
def _two_state_remittance_landscape(api):
    """One CLEARED NM order dated 2026-07-10, with the clock then at 2026-08-01.

    TX carries ``zero_filing_required`` true and NM carries it false.  The single
    order ships into NM, so a TX period is empty however it is drawn, and the NM
    2025 period is empty because the order cleared in 2026.  The clock is advanced
    after the clearance so that a July period has actually closed — PRD §3.9
    refuses a period whose ``period_end`` is later than the clock date.
    """
    scape = build_landscape(
        api,
        clock=CLOCK_JULY_10,
        program_overrides={"states_served": ["TX", "NM"]},
    )
    add_nm_state(api, scape)
    order = scape.create_order(ship_to_state_code="NM", ship_to_zip="87501")
    cleared = scape.screen(order["id"])
    assert_order_dimensions(cleared, compliance_status="CLEARED")
    set_clock(api, CLOCK_AUG_1)
    return scape, cleared


def test_empty_period_below_the_threshold_files_where_zero_filing_is_required(api):
    """shipment_count 0 files in TX, with every frozen amount at literal zero.

    PRD §3.9: "Filing also has a substance requirement: the remittance's
    `shipment_count` must be at least 1, **unless** the governing state rule's
    `zero_filing_required` is true, in which case an empty period may and indeed
    must be filed."

    PRD §3.9: "From the selected set the remittance records:
    `excise_accrued_cents`, the sum of `excise_tax_cents` across the selected
    orders; `sales_tax_accrued_cents`, the sum of their `sales_tax_cents`;
    `excise_reversed_cents` and `sales_tax_reversed_cents`, the same two sums
    restricted to those selected orders whose `returned_at` is non-null and falls
    **strictly before** `period_end`; `excise_due_cents`, the accrued excise less
    the reversed excise; `sales_tax_due_cents`, the accrued sales tax less the
    reversed sales tax; `liters_total`, the sum of the selected orders'
    `total_liters` rounded half up to three decimal places; `shipment_count`, the
    count of selected orders; and `included_order_ids`, the identifiers of the
    selected orders ordered by `cleared_at` ascending and then by `created_at`
    ascending."

    Design: Difficulty/boundary_precision_check/remittance_zero_shipment_period_at_the_filing_threshold
    """
    scape, _cleared = _two_state_remittance_landscape(api)

    remittance = scape.open_remittance(
        "TX", "2026-07-01", "2026-08-01", period_type="MONTHLY", basis="ACCRUAL_BASIS"
    )
    assert remittance["shipment_count"] == 0
    assert remittance["included_order_ids"] == [], (
        "an empty selection is an empty array, never null: "
        f"{remittance['included_order_ids']!r}"
    )
    assert_liters(remittance["liters_total"], 0.000, "liters_total")
    assert_cents(remittance["excise_accrued_cents"], 0, "excise_accrued_cents")
    assert_cents(remittance["sales_tax_accrued_cents"], 0, "sales_tax_accrued_cents")
    assert_cents(remittance["excise_due_cents"], 0, "excise_due_cents")
    assert_cents(remittance["sales_tax_due_cents"], 0, "sales_tax_due_cents")
    assert remittance["status"] == "OPEN"

    filed = validate_success(api.file_remittance(remittance["id"], {}, OFFICER_A), 200)
    assert filed["status"] == "FILED"
    assert_instant_equals(filed["filed_at"], CLOCK_AUG_1)
    assert filed["shipment_count"] == 0
    assert_liters(filed["liters_total"], 0.000, "liters_total")


def test_empty_period_is_refused_where_zero_filing_is_not_required(api):
    """The same zero shipment_count is refused in NM, which demands no zero filing.

    PRD §3.9: "A filing with nothing to report in a state that does not demand
    zero filings is refused with `ERR_NOTHING_TO_REMIT` (HTTP 422)."

    PRD §3.9: "Under **`ACCRUAL_BASIS`**, the selected orders are those whose
    `compliance_status` is `CLEARED` and whose `cleared_at` falls inside the
    half-open period."

    Design: Difficulty/boundary_precision_check/remittance_zero_shipment_period_at_the_filing_threshold
    """
    scape, _cleared = _two_state_remittance_landscape(api)

    remittance = scape.open_remittance(
        "NM", "2025-01-01", "2026-01-01", period_type="ANNUAL", basis="ACCRUAL_BASIS"
    )
    assert remittance["shipment_count"] == 0
    assert remittance["included_order_ids"] == []

    response = api.file_remittance(remittance["id"], {}, OFFICER_A)
    validate_error(response, "ERR_NOTHING_TO_REMIT", 422)

    stored = scape.read_remittance(remittance["id"])
    assert stored["status"] == "OPEN"
    assert stored["filed_at"] is None, f"A refused filing stamps nothing: {stored}"


def test_exactly_one_selected_order_at_the_threshold_files(api):
    """shipment_count 1 — the threshold value itself — files even in NM.

    PRD §3.9: "Filing also has a substance requirement: the remittance's
    `shipment_count` must be at least 1, **unless** the governing state rule's
    `zero_filing_required` is true, in which case an empty period may and indeed
    must be filed."

    PRD §3.9: "The interval is always **half-open**: `period_start` is inclusive
    and `period_end` is exclusive, so an order whose key date falls exactly on
    `period_end` belongs to the *next* period, not this one." and "`period_start`
    must be strictly before `period_end`, and `period_end` must fall on or before
    the logical clock date — a period that has not closed yet cannot be reported."

    PRD §3.5: "Finally, and strictly last, the state's
    `excise_cap_cents_per_shipment` is applied as a ceiling: `excise_tax_cents` is
    the lesser of the credited excise and the cap."

    Design: Difficulty/boundary_precision_check/remittance_zero_shipment_period_at_the_filing_threshold
    """
    scape, cleared = _two_state_remittance_landscape(api)

    assert_cents(cleared["excise_tax_cents"], 300, "excise_tax_cents")
    assert_cents(cleared["sales_tax_cents"], 0, "sales_tax_cents")
    assert_cents(cleared["total_cents"], 27990, "total_cents")
    assert_liters(cleared["total_liters"], 4.500, "total_liters")

    remittance = scape.open_remittance(
        "NM", "2026-07-01", "2026-08-01", period_type="MONTHLY", basis="ACCRUAL_BASIS"
    )
    assert remittance["shipment_count"] == 1
    assert remittance["included_order_ids"] == [cleared["id"]]
    assert_liters(remittance["liters_total"], 4.500, "liters_total")
    assert_cents(remittance["excise_accrued_cents"], 300, "excise_accrued_cents")
    assert_cents(remittance["excise_due_cents"], 300, "excise_due_cents")
    assert_cents(remittance["sales_tax_due_cents"], 0, "sales_tax_due_cents")

    filed = validate_success(api.file_remittance(remittance["id"], {}, OFFICER_A), 200)
    assert filed["status"] == "FILED"
    assert_instant_equals(filed["filed_at"], CLOCK_AUG_1)
    assert filed["shipment_count"] == 1
