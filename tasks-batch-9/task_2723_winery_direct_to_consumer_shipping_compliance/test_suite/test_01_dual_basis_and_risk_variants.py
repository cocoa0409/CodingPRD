"""Two dual-variant calculations of the Winery DTC contract.

The first pair is the remittance basis fork of PRD §3.9: the identical July
window over the identical two orders yields different due amounts because
``ACCRUAL_BASIS`` selects on ``Order.cleared_at`` while ``DELIVERY_BASIS``
selects on the delivering shipment's ``delivered_at``.

The second pair is the consumer risk fork of PRD §3.4: one back-dated
``MANUAL_ADJUSTMENT`` scores 0 on the screening variant, which only sees the
rolling window, and 25 on the audit variant, which sees all time.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (fixture type)
from test_helpers.assertions import (
    assert_cents,
    assert_charge_chain,
    assert_immutable_identity,
    assert_instant_equals,
    assert_ledger_entry,
    assert_liters,
    assert_order_dimensions,
)
from test_helpers.constants import (
    CANONICAL_ORDER_EXCISE_CENTS,
    CANONICAL_ORDER_SALES_TAX_CENTS,
    CANONICAL_ORDER_SHIPPING_CENTS,
    CANONICAL_ORDER_SUBTOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_CENTS,
    CANONICAL_ORDER_TOTAL_LITERS,
    ELEVATED_TIER_THRESHOLD,
    STATE_RULE_TX,
)
from test_helpers.fixtures import (
    build_landscape,
    create_state_rule,
    create_verified_consumer,
    create_winery,
    set_clock,
)
from test_helpers.test_users import OFFICER_A

# ---------------------------------------------------------------------------
# The July window of PRD §3.9, expressed half-open: start inclusive, end
# exclusive.  Both remittances below are opened over exactly this interval.
# ---------------------------------------------------------------------------
JULY_PERIOD_START = "2026-07-01T00:00:00Z"
JULY_PERIOD_END = "2026-08-01T00:00:00Z"

# The canonical 4.500 L TX order recomputed from the PRD §3.5 chain:
#   line_liters      6 * 750 / 1000                     = 4.500 L
#   subtotal         6 * 4200                           = 25200 c
#   shipping_gross   round_half_up(1500 + 220 * 4.500)  = 2490 c
#   tier             4.500 <= 9.000                     -> x1.00
#   shipping         2490 c (no club subscription, so no discount)
#   excise base      round_half_up(4.500 * 55)          = 248 c
#   surcharge        no line above 1500 ml              = 0 c
#   credit           round_half_up(248 * 0.15)          = 37 c  (120000 gal)
#   excise           min(248 - 37, 100000)              = 211 c
#   sales-tax pool   shipping 2490 c, excise excluded   = 2490 c
#   line taxable     25200 + 2490                       = 27690 c
#   sales tax        round_half_up(27690 * 825 / 10000) = 2284 c
#   pre-fee total    25200 + 2490 + 211 + 2284          = 30185 c  (>= 20000)
#   total            30185 + 0                          = 30185 c
ORDER_EXCISE_CENTS = CANONICAL_ORDER_EXCISE_CENTS
ORDER_SALES_TAX_CENTS = CANONICAL_ORDER_SALES_TAX_CENTS
ORDER_LITERS = CANONICAL_ORDER_TOTAL_LITERS

# Two such orders inside one accrual period.
ACCRUAL_EXCISE_CENTS = 2 * ORDER_EXCISE_CENTS          # 422
ACCRUAL_SALES_TAX_CENTS = 2 * ORDER_SALES_TAX_CENTS    # 4568
ACCRUAL_LITERS = 9.000

# Only the order delivered inside the period on a delivery basis.
DELIVERY_EXCISE_CENTS = ORDER_EXCISE_CENTS             # 211
DELIVERY_SALES_TAX_CENTS = ORDER_SALES_TAX_CENTS       # 2284
DELIVERY_LITERS = 4.500


def _build_july_two_order_scenario(api):
    """Stand up the PRD §3.9 worked example: two identical 4.500 L TX orders.

    Order 1 clears 2026-07-10 and is delivered 2026-07-20 — inside July on both
    bases.  Order 2 clears 2026-07-28 but is delivered 2026-08-03 — inside July
    on an accrual basis only.  The clock ends at 2026-08-05 so that the July
    period has closed and may be reported.
    """
    scape = build_landscape(api, clock="2026-07-05T00:00:00Z")

    # -- order 1: cleared 2026-07-10, delivered 2026-07-20 -----------------
    set_clock(api, "2026-07-10T00:00:00Z")
    order_1 = scape.create_order()
    cleared_1 = scape.screen(order_1["id"])
    shipment_1 = scape.label(order_1["id"])
    scape.pickup(shipment_1["id"])
    set_clock(api, "2026-07-20T00:00:00Z")
    scape.deliver(shipment_1["id"])

    # -- order 2: cleared 2026-07-28, delivered 2026-08-03 -----------------
    set_clock(api, "2026-07-28T00:00:00Z")
    order_2 = scape.create_order()
    cleared_2 = scape.screen(order_2["id"])
    shipment_2 = scape.label(order_2["id"])
    scape.pickup(shipment_2["id"])
    set_clock(api, "2026-08-03T00:00:00Z")
    scape.deliver(shipment_2["id"])

    set_clock(api, "2026-08-05T00:00:00Z")
    return scape, cleared_1, cleared_2, shipment_1, shipment_2


def test_accrual_basis_july_period_captures_both_cleared_orders(api):
    """Accrual basis selects on cleared_at, so both July clearances are in.

    PRD §3.9: "Under **`ACCRUAL_BASIS`**, the selected orders are those whose
    `compliance_status` is `CLEARED` and whose `cleared_at` falls inside the
    half-open period."

    PRD §3.9: "For two otherwise identical 4.500-litre orders each carrying 211
    cents of excise, cleared on 2026-07-10 and 2026-07-28 and delivered on
    2026-07-20 and 2026-08-03, a July monthly period yields an
    `excise_due_cents` of 422 on `ACCRUAL_BASIS` and 211 on `DELIVERY_BASIS`."

    PRD §3.9: "From the selected set the remittance records:
    `excise_accrued_cents`, the sum of `excise_tax_cents` across the selected
    orders; `sales_tax_accrued_cents`, the sum of their `sales_tax_cents`;
    `excise_reversed_cents` and `sales_tax_reversed_cents`, the same two sums
    restricted to those selected orders whose `returned_at` is non-null and
    falls **strictly before** `period_end`; `excise_due_cents`, the accrued
    excise less the reversed excise; `sales_tax_due_cents`, the accrued sales
    tax less the reversed sales tax; `liters_total`, the sum of the selected
    orders' `total_liters` rounded half up to three decimal places;
    `shipment_count`, the count of selected orders; and `included_order_ids`,
    the identifiers of the selected orders ordered by `cleared_at` ascending
    and then by `created_at` ascending."

    Design: Difficulty/dual_variant_calc/remittance_accrual_vs_delivery_basis_diverge
    """
    scape, order_1, order_2, _, _ = _build_july_two_order_scenario(api)

    response = api.create_remittance(
        f.remittance_payload(
            scape.winery_id, "TX", JULY_PERIOD_START, JULY_PERIOD_END,
            period_type="MONTHLY", basis="ACCRUAL_BASIS",
        ),
        OFFICER_A,
    )
    accrual = validate_success(response, 201)

    assert accrual["basis"] == "ACCRUAL_BASIS"
    assert accrual["shipment_count"] == 2
    assert_liters(accrual["liters_total"], ACCRUAL_LITERS, "liters_total")

    # 211 + 211 = 422 cents of excise, nothing returned so nothing reversed.
    assert_cents(accrual["excise_accrued_cents"], ACCRUAL_EXCISE_CENTS,
                 "excise_accrued_cents")
    assert_cents(accrual["excise_reversed_cents"], 0, "excise_reversed_cents")
    assert_cents(accrual["excise_due_cents"], ACCRUAL_EXCISE_CENTS,
                 "excise_due_cents")

    # 2284 + 2284 = 4568 cents of sales tax.
    assert_cents(accrual["sales_tax_accrued_cents"], ACCRUAL_SALES_TAX_CENTS,
                 "sales_tax_accrued_cents")
    assert_cents(accrual["sales_tax_reversed_cents"], 0,
                 "sales_tax_reversed_cents")
    assert_cents(accrual["sales_tax_due_cents"], ACCRUAL_SALES_TAX_CENTS,
                 "sales_tax_due_cents")

    # Ordered by cleared_at ascending: 2026-07-10 before 2026-07-28.
    assert accrual["included_order_ids"] == [order_1["id"], order_2["id"]]


def test_delivery_basis_july_period_excludes_the_august_delivery(api):
    """Delivery basis selects on delivered_at, so the August delivery drops out.

    PRD §3.9: "Under **`DELIVERY_BASIS`**, the selected orders are those that
    have a shipment in `DELIVERED` status whose `delivered_at` falls inside the
    half-open period."

    PRD §3.9: "The two bases genuinely disagree, and the disagreement is the
    point: an order cleared on 2026-07-28 but delivered on 2026-08-03 **is** in
    the July monthly period on an accrual basis and is **not** in it on a
    delivery basis."

    PRD §3.9: "The interval is always **half-open**: `period_start` is
    inclusive and `period_end` is exclusive, so an order whose key date falls
    exactly on `period_end` belongs to the *next* period, not this one."

    Design: Difficulty/dual_variant_calc/remittance_accrual_vs_delivery_basis_diverge
    """
    scape, order_1, order_2, _, _ = _build_july_two_order_scenario(api)

    response = api.create_remittance(
        f.remittance_payload(
            scape.winery_id, "TX", JULY_PERIOD_START, JULY_PERIOD_END,
            period_type="MONTHLY", basis="DELIVERY_BASIS",
        ),
        OFFICER_A,
    )
    delivery = validate_success(response, 201)

    assert delivery["basis"] == "DELIVERY_BASIS"
    # Only the 2026-07-20 delivery lands inside the half-open July window.
    assert delivery["shipment_count"] == 1
    assert_liters(delivery["liters_total"], DELIVERY_LITERS, "liters_total")

    assert_cents(delivery["excise_accrued_cents"], DELIVERY_EXCISE_CENTS,
                 "excise_accrued_cents")
    assert_cents(delivery["excise_due_cents"], DELIVERY_EXCISE_CENTS,
                 "excise_due_cents")
    assert_cents(delivery["sales_tax_accrued_cents"], DELIVERY_SALES_TAX_CENTS,
                 "sales_tax_accrued_cents")
    assert_cents(delivery["sales_tax_due_cents"], DELIVERY_SALES_TAX_CENTS,
                 "sales_tax_due_cents")

    assert delivery["included_order_ids"] == [order_1["id"]]
    assert order_2["id"] not in delivery["included_order_ids"]

    # The divergence itself: the accrual figure over the same window is double.
    assert delivery["excise_due_cents"] != ACCRUAL_EXCISE_CENTS


def test_both_bases_open_the_same_july_period_over_identically_frozen_orders(api):
    """The same July period is legal once per basis, over identical frozen money.

    PRD §3.9: "Because the check is also scoped by `basis`, the two bases are
    separate filing families and the very same calendar period may legitimately
    be opened once on each."

    PRD §3.9: "A new remittance's half-open interval must not overlap the
    interval of any existing remittance for the same combination of
    `winery_id`, `state_code`, `period_type` **and** `basis` whose `status` is
    anything other than `AMENDED`; a collision is refused with
    `ERR_REMITTANCE_PERIOD_OVERLAP` (HTTP 409)."

    PRD §3.5: "Every monetary and volumetric field on the order and on each of
    its lines is computed exactly once, at creation, from the governing state
    rule and the winery, and then **frozen**."

    Design: Difficulty/dual_variant_calc/remittance_accrual_vs_delivery_basis_diverge
    """
    scape, order_1, order_2, _, _ = _build_july_two_order_scenario(api)

    # Both orders carry the identical frozen chain of PRD §3.5.
    for order_id in (order_1["id"], order_2["id"]):
        frozen = scape.read_order(order_id)
        assert_order_dimensions(frozen, compliance_status="CLEARED",
                                fulfillment_status="DELIVERED")
        assert_charge_chain(
            frozen,
            total_liters=ORDER_LITERS,
            subtotal_cents=CANONICAL_ORDER_SUBTOTAL_CENTS,
            shipping_cents=CANONICAL_ORDER_SHIPPING_CENTS,
            excise_tax_cents=ORDER_EXCISE_CENTS,
            sales_tax_cents=ORDER_SALES_TAX_CENTS,
            total_cents=CANONICAL_ORDER_TOTAL_CENTS,
        )

    payload_accrual = f.remittance_payload(
        scape.winery_id, "TX", JULY_PERIOD_START, JULY_PERIOD_END,
        period_type="MONTHLY", basis="ACCRUAL_BASIS",
    )
    payload_delivery = f.remittance_payload(
        scape.winery_id, "TX", JULY_PERIOD_START, JULY_PERIOD_END,
        period_type="MONTHLY", basis="DELIVERY_BASIS",
    )

    accrual = validate_success(
        api.create_remittance(payload_accrual, OFFICER_A), 201
    )
    # The second call carries the identical winery, state, period_type and
    # window; only the basis differs, so it is not an overlap.
    delivery = validate_success(
        api.create_remittance(payload_delivery, OFFICER_A), 201
    )

    assert accrual["id"] != delivery["id"]
    assert accrual["status"] == "OPEN"
    assert delivery["status"] == "OPEN"
    assert_instant_equals(accrual["period_start"], JULY_PERIOD_START)
    assert_instant_equals(accrual["period_end"], JULY_PERIOD_END)
    assert_instant_equals(delivery["period_start"], JULY_PERIOD_START)
    assert_instant_equals(delivery["period_end"], JULY_PERIOD_END)

    # The two filing families disagree on the very same window.
    assert accrual["shipment_count"] == 2
    assert delivery["shipment_count"] == 1
    assert_cents(accrual["excise_due_cents"], ACCRUAL_EXCISE_CENTS,
                 "excise_due_cents")
    assert_cents(delivery["excise_due_cents"], DELIVERY_EXCISE_CENTS,
                 "excise_due_cents")


# ===========================================================================
# consumer_risk_screening_vs_audit_diverge
#
# Clock 2026-08-01T00:00:00Z, so the ROLLING_12_MONTHS window opens at
# 2025-08-01T00:00:00Z (the clock instant less 365 days).  One MANUAL_ADJUSTMENT
# of 22.500 L for TX dated 2025-06-01 therefore sits two months outside it.
#
#   screening variant   f1 = 0 (no RETURN_CREDIT rows)
#                       f2 = 0 (no DENIED exceptions)
#                       f3 = 0 (rolling_liters_settled_by_state has no
#                               in-window TX volume at all)
#                       -> risk_score_screening 0, screening_tier STANDARD
#   audit variant       f1 = 0, f2 = 0
#                       f3 = trunc(30 * 22.500 / 27.000) = trunc(25.0) = 25
#                       -> risk_score_audit 25
# ===========================================================================
RISK_ADJUSTMENT_LITERS = 22.500
RISK_ADJUSTMENT_OCCURRED_AT = "2025-06-01T00:00:00Z"
RISK_CLOCK = "2026-08-01T00:00:00Z"
EXPECTED_SCREENING_SCORE = 0
EXPECTED_AUDIT_SCORE = 25


def _build_backdated_adjustment_scenario(api):
    """Clock, winery, TX rule and an ID-verified consumer; nothing else."""
    set_clock(api, RISK_CLOCK)
    winery = create_winery(api)
    state_rule = create_state_rule(api)
    consumer = create_verified_consumer(api)
    return winery, state_rule, consumer


def _append_backdated_adjustment(api, consumer_id, winery_id):
    response = api.create_volume_ledger_entry(
        f.manual_adjustment_payload(
            consumer_id, winery_id, RISK_ADJUSTMENT_LITERS,
            state_code="TX",
            occurred_at=RISK_ADJUSTMENT_OCCURRED_AT,
            reason="Historical volume migrated from legacy compliance system",
        ),
        OFFICER_A,
    )
    return validate_success(response, 201)


def test_backdated_manual_adjustment_is_appended_outside_the_rolling_window(api):
    """The officer's back-dated MANUAL_ADJUSTMENT lands with occurred_at honoured.

    PRD §3.4: "The officer supplies `consumer_id`, `winery_id`, `state_code`, a
    signed `liters` value, an `occurred_at` instant and a `reason`; the system
    stamps `event_type` as `MANUAL_ADJUSTMENT`."

    PRD §3.4: "Aggregation keys on `occurred_at` and never on `created_at`,
    which is exactly what makes back-dated manual adjustments meaningful."

    PRD §3.4: "`ROLLING_12_MONTHS` admits entries whose `occurred_at` is on or
    after the logical clock instant minus 365 days and on or before the logical
    clock instant."

    Design: Difficulty/dual_variant_calc/consumer_risk_screening_vs_audit_diverge
    """
    winery, _, consumer = _build_backdated_adjustment_scenario(api)

    entry = _append_backdated_adjustment(api, consumer["id"], winery["id"])

    assert_ledger_entry(
        entry,
        event_type="MANUAL_ADJUSTMENT",
        liters=RISK_ADJUSTMENT_LITERS,
        state_code="TX",
    )
    assert_immutable_identity(entry)
    # occurred_at is the supplied instant, not the 2026-08-01 clock.
    assert_instant_equals(entry["occurred_at"], RISK_ADJUSTMENT_OCCURRED_AT)
    assert entry["order_id"] is None
    assert entry["shipment_id"] is None
    assert entry["consumer_id"] == consumer["id"]
    assert entry["winery_id"] == winery["id"]

    # The window opened 2025-08-01, so nothing of the 22.500 L is in scope.
    refreshed = get_success_data(api.get_consumer(consumer["id"], OFFICER_A))
    rolling = refreshed["rolling_liters_by_state"]
    assert_liters(rolling.get("TX", 0.0), 0.000, "rolling_liters_by_state[TX]")
    settled = refreshed["rolling_liters_settled_by_state"]
    assert_liters(settled.get("TX", 0.0), 0.000,
                  "rolling_liters_settled_by_state[TX]")


def test_screening_variant_scores_zero_and_leaves_the_consumer_standard(api):
    """The screening variant sees only the rolling window, so it scores 0.

    PRD §3.4: "The **screening** variant is written to `risk_score_screening`
    and is the only variant that gates anything: its scope is ledger entries
    inside the state's `per_consumer_period` window whose `order_id` is null or
    whose order's `fulfillment_status` is `IN_TRANSIT`, `DELIVERED` or
    `RETURNED`, its utilisation term reads `rolling_liters_settled_by_state`,
    and its denial count includes only exceptions decided inside that same
    window."

    PRD §3.4: "From the screening score alone the system derives
    `screening_tier`, which is `STANDARD` while `risk_score_screening` is below
    50 and becomes `ELEVATED` as soon as `risk_score_screening` reaches 50 or
    more."

    Design: Difficulty/dual_variant_calc/consumer_risk_screening_vs_audit_diverge
    """
    winery, _, consumer = _build_backdated_adjustment_scenario(api)

    _append_backdated_adjustment(api, consumer["id"], winery["id"])

    refreshed = get_success_data(api.get_consumer(consumer["id"], OFFICER_A))
    # f1 = 0, f2 = 0 and f3 = 0 because no in-window settled liters exist.
    assert refreshed["risk_score_screening"] == EXPECTED_SCREENING_SCORE
    assert refreshed["return_credit_count"] == 0
    assert refreshed["denied_exception_count"] == 0
    assert refreshed["risk_score_screening"] < ELEVATED_TIER_THRESHOLD
    assert refreshed["screening_tier"] == "STANDARD"


def test_audit_variant_scores_twenty_five_from_the_same_single_entry(api):
    """The audit variant reads all-time liters, so the same entry scores 25.

    PRD §3.4: "The **audit** variant is written to `risk_score_audit` and never
    gates any operation: its scope is every ledger entry of the consumer for all
    time and every `DENIED` exception for all time, regardless of the source
    order's `fulfillment_status`, and its utilisation term reads the all-time,
    all-status liters per state."

    PRD §3.4: "The third factor is a utilisation term: among the states present
    in the relevant liters map, the system selects the state with the greatest
    ratio of accumulated liters to that state's `per_consumer_limit_liters`,
    breaking a tie in favour of the alphabetically earlier `state_code`; the
    factor is then 30 multiplied by the selected state's liters divided by that
    state's per-consumer limit, truncated downward to a whole number, and
    capped at 30."

    PRD §3.4: "The two therefore diverge routinely rather than exceptionally —
    a consumer holding a 22.500-litre adjustment dated outside the rolling
    window plus one cleared but unfulfilled 4.500-litre order against a
    27.000-litre limit scores 0 on the screening variant and 30 on the audit
    variant."

    Design: Difficulty/dual_variant_calc/consumer_risk_screening_vs_audit_diverge
    """
    winery, _, consumer = _build_backdated_adjustment_scenario(api)

    _append_backdated_adjustment(api, consumer["id"], winery["id"])

    refreshed = get_success_data(api.get_consumer(consumer["id"], OFFICER_A))
    # trunc(30 * 22.500 / 27.000) = trunc(25.0) = 25, and f1 = f2 = 0.
    assert STATE_RULE_TX["per_consumer_limit_liters"] == 27.000
    assert refreshed["risk_score_audit"] == EXPECTED_AUDIT_SCORE
    # The two variants diverge on identical inputs.
    assert refreshed["risk_score_screening"] == EXPECTED_SCREENING_SCORE
    assert refreshed["risk_score_audit"] != refreshed["risk_score_screening"]
    # The audit score never gates: the tier is derived from the screening score.
    assert refreshed["screening_tier"] == "STANDARD"


def test_volume_summary_reports_both_risk_variants_side_by_side(api):
    """The computed volume read carries both variants in one payload.

    PRD §3.4: "A consumer's whole volume picture is available as a single
    computed read that reports the `consumer_id`, an `as_of` instant taken from
    the logical clock, a `per_state` map — keyed by state code, giving that
    state's accumulated rolling liters, the state's per-consumer limit, and the
    headroom remaining between them — and, side by side,
    `risk_score_screening`, `risk_score_audit`, `screening_tier`,
    `return_credit_count` and `denied_exception_count`."

    Design: Difficulty/dual_variant_calc/consumer_risk_screening_vs_audit_diverge
    """
    winery, _, consumer = _build_backdated_adjustment_scenario(api)

    _append_backdated_adjustment(api, consumer["id"], winery["id"])

    summary = get_success_data(
        api.get_volume_summary(consumer["id"], OFFICER_A, {})
    )
    assert summary["consumer_id"] == consumer["id"]
    assert_instant_equals(summary["as_of"], RISK_CLOCK)
    assert summary["risk_score_screening"] == EXPECTED_SCREENING_SCORE
    assert summary["risk_score_audit"] == EXPECTED_AUDIT_SCORE
    assert summary["screening_tier"] == "STANDARD"
    assert summary["return_credit_count"] == 0
    assert summary["denied_exception_count"] == 0

    # The rolling picture the summary reports is the in-window one: 0.000 L of
    # TX volume, so the whole 27.000 L limit is still headroom.
    per_state = summary["per_state"]
    if "TX" in per_state:
        tx = per_state["TX"]
        numbers = [v for v in tx.values() if isinstance(v, (int, float))
                   and not isinstance(v, bool)]
        assert any(abs(value - 0.000) < 0.0005 for value in numbers)
        assert any(abs(value - 27.000) < 0.0005 for value in numbers)
