"""Two-basis computations that must diverge on identical underlying data.

Covers the delivery promise under its QUOTED and RECOMPUTED variants on the order
side, and the vendor scorecard under its EVENT_EQUAL and UNIT_WEIGHTED metric
variants on the vendor-performance side.
"""

from typing import Any, Dict

from test_helpers import (
    CARE,
    MM,
    OPS,
    ApiClient,
    acknowledge_payload,
    cancel_line,
    create_order_payload,
    create_seeded_scorecard,
    get_success_data,
    make_vendor_user_headers,
    order_line_input,
    order_lines_of,
    place_and_transmit_order,
    publish_seeded_scorecard,
    refresh_order,
    refresh_vendor,
    set_clock,
    setup_vendor_with_active_offer,
    ship_confirm,
    validate_success,
)

# The seeded prior history that scores GOLD: half of 9200, plus three tenths of
# 9600, plus two tenths of 9400, is 9360 basis points.
GOLD_SEEDS = {
    "avg_ship_hours": 40.0,
    "on_time_bps": 9200,
    "cancellation_bps": 400,
    "defect_bps": 600,
}


def _place_two_unit_order(api: ApiClient, item_id: str, order_ref: str) -> Dict[str, Any]:
    """Place a two-unit order for one offer into the default US-WEST zone."""
    return get_success_data(
        api.create_order(
            create_order_payload(order_ref, [order_line_input(item_id, 2)]), CARE
        )
    )


def _one_shipped_line_and_one_cancelled_line(
    api: ApiClient, suffix: str, order_ref_shipped: str, order_ref_cancelled: str
) -> Dict[str, Any]:
    """One shipped line of one unit and one vendor-cancelled line of nine units.

    Both lines are transmitted on 2026-08-03, so both fall inside an August period.
    The shipped line goes out two hours after transmission, well inside its ship
    deadline, so its shipment record is on time.
    """
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    placed_shipped = place_and_transmit_order(
        api, base["item_id"], quantity=1, order_ref=order_ref_shipped
    )
    placed_cancelled = place_and_transmit_order(
        api, base["item_id"], quantity=9, order_ref=order_ref_cancelled
    )
    line_shipped = placed_shipped["lines"][0]
    line_cancelled = placed_cancelled["lines"][0]
    get_success_data(
        api.acknowledge_line(
            line_shipped["id"],
            acknowledge_payload("ACCEPTED"),
            make_vendor_user_headers(base["vendor_id"]),
        )
    )
    set_clock(api, "2026-08-03T12:00:00Z")
    ship_confirm(api, line_shipped["id"], base["vendor_id"], 1)
    cancel_line(api, line_cancelled["id"], base["vendor_id"])
    return base


# ─── The delivery promise: QUOTED versus RECOMPUTED ───


def test_quoted_promise_adds_contracted_lead_transit_and_tier_padding(api):
    """PRD §3.5: "To that the platform adds the offer's contracted `lead_time_days`, the coverage row's `transit_days`, and the vendor's `promise_padding_days`, all as whole calendar days."

    An order captured on 2026-08-03 at 10:00Z, before the 18:00Z cutoff, against a
    three-day lead time, four transit days and the one padding day a GOLD vendor
    earns, is promised 2026-08-11. Nothing has been transmitted, so the QUOTED
    variant is the one in effect and there is no divergence to report yet.

    Design: Difficulty/dual_variant_calc/promise_quoted_vs_recomputed_diverges_on_order_domain
    """
    base = setup_vendor_with_active_offer(api, suffix="PQA")
    scorecard = publish_seeded_scorecard(api, base["vendor_id"], **GOLD_SEEDS)
    assert scorecard["composite_score"] == 93.60
    assert scorecard["tier"] == "GOLD"
    assert refresh_vendor(api, base["vendor_id"])["promise_padding_days"] == 1

    order = validate_success(
        api.create_order(
            create_order_payload("ORD-PQA-1", [order_line_input(base["item_id"], 2)]),
            CARE,
        ),
        201,
    )
    assert order["quoted_promise_date"] == "2026-08-11"
    assert order["recomputed_promise_date"] is None
    assert order["promise_variant_in_effect"] == "QUOTED"

    promise = validate_success(api.get_order_promise(order["id"], CARE))
    assert promise["quoted_promise_date"] == "2026-08-11"
    assert promise["recomputed_promise_date"] is None
    assert promise["promise_variant_in_effect"] == "QUOTED"
    assert promise["promise_divergence_days"] == 0


def test_recomputed_promise_uses_published_avg_ship_hours_and_no_padding(api):
    """PRD §3.6: "Second, the lead time comes from observed performance instead of contract: the platform takes the vendor's scorecard with `status` `PUBLISHED` having the greatest `period_end`, breaking a tie by the greatest `created_at`, and if such a scorecard exists and carries a non-null `avg_ship_hours`, the lead days become that `avg_ship_hours` divided by 24 and rounded *up* to a whole day, floored at a minimum of 1 day; when no scorecard is published or the published one has a null `avg_ship_hours`, the offer's contracted `lead_time_days` is used instead."

    The published scorecard reports 40 observed ship hours, so the recomputed lead
    is two days instead of the contracted three, and padding drops to zero: the
    same order that was quoted 2026-08-11 is recomputed to 2026-08-09.

    Design: Difficulty/dual_variant_calc/promise_quoted_vs_recomputed_diverges_on_order_domain
    """
    base = setup_vendor_with_active_offer(api, suffix="PQB")
    publish_seeded_scorecard(api, base["vendor_id"], **GOLD_SEEDS)
    order = _place_two_unit_order(api, base["item_id"], "ORD-PQB-1")
    assert order["quoted_promise_date"] == "2026-08-11"

    validate_success(api.transmit_order(order["id"], MM))

    after = refresh_order(api, order["id"])
    assert after["quoted_promise_date"] == "2026-08-11"
    assert after["recomputed_promise_date"] == "2026-08-09"
    assert after["promise_variant_in_effect"] == "RECOMPUTED"
    assert order_lines_of(api, order["id"])[0]["line_promise_date"] == "2026-08-09"

    promise = validate_success(api.get_order_promise(order["id"], CARE))
    assert promise["quoted_promise_date"] == "2026-08-11"
    assert promise["recomputed_promise_date"] == "2026-08-09"
    assert promise["promise_divergence_days"] == 2


def test_draft_scorecard_leaves_the_recomputed_lead_on_the_contracted_lead_time(api):
    """PRD §3.6: "`DRAFT` scorecards are invisible to this computation."

    An unpublished scorecard reporting 40 observed ship hours must not move either
    variant: the vendor keeps its default two padding days, so the quote is
    2026-08-12, and the recomputed promise still uses the contracted three-day lead
    for 2026-08-10.

    Design: Difficulty/dual_variant_calc/promise_quoted_vs_recomputed_diverges_on_order_domain
    """
    base = setup_vendor_with_active_offer(api, suffix="PQC")
    draft = create_seeded_scorecard(api, base["vendor_id"], **GOLD_SEEDS)
    assert draft["status"] == "DRAFT"
    assert draft["avg_ship_hours"] == 40.0
    assert refresh_vendor(api, base["vendor_id"])["promise_padding_days"] == 2

    order = _place_two_unit_order(api, base["item_id"], "ORD-PQC-1")
    assert order["quoted_promise_date"] == "2026-08-12"

    validate_success(api.transmit_order(order["id"], MM))

    after = refresh_order(api, order["id"])
    assert after["quoted_promise_date"] == "2026-08-12"
    assert after["recomputed_promise_date"] == "2026-08-10"
    assert after["promise_variant_in_effect"] == "RECOMPUTED"


# ─── The scorecard: EVENT_EQUAL versus UNIT_WEIGHTED ───


def test_event_equal_variant_counts_each_line_once_for_silver(api):
    """PRD §3.9: "The choice of variant is consequential rather than cosmetic: a period holding one shipped line of one unit and one cancelled line of nine units yields a cancellation rate of 5000 basis points and a composite of 85.00 under `EVENT_EQUAL`, but 9000 basis points and a composite of 73.00 under `UNIT_WEIGHTED` — a two-band tier swing on identical underlying data."

    Under EVENT_EQUAL the nine-unit cancellation weighs exactly as much as the
    one-unit shipment, so one cancelled line out of two transmitted lines is 5000
    basis points and the composite bands at SILVER with two padding days.

    Design: Difficulty/dual_variant_calc/scorecard_event_equal_vs_unit_weighted_diverges_on_vendor_domain
    """
    base = _one_shipped_line_and_one_cancelled_line(
        api, "SCA", "ORD-SCA-A", "ORD-SCA-B"
    )

    scorecard = validate_success(
        api.create_scorecard(
            base["vendor_id"],
            {
                "period_start": "2026-08-01",
                "period_end": "2026-08-31",
                "metric_variant": "EVENT_EQUAL",
            },
            OPS,
        ),
        201,
    )
    assert scorecard["transmitted_line_count"] == 2
    assert scorecard["shipped_line_count"] == 1
    assert scorecard["cancelled_line_count"] == 1
    assert scorecard["defect_return_count"] == 0
    assert scorecard["on_time_ship_rate_bps"] == 10000
    assert scorecard["cancellation_rate_bps"] == 5000
    assert scorecard["defect_rate_bps"] == 0
    assert scorecard["avg_ship_hours"] == 2.00
    assert scorecard["composite_score"] == 85.00
    assert scorecard["tier"] == "SILVER"
    assert scorecard["promise_padding_days"] == 2


def test_unit_weighted_variant_weighs_each_line_by_quantity_for_watch(api):
    """PRD §3.9: "Under `UNIT_WEIGHTED` each line is weighted by its `quantity` and every denominator becomes a unit sum: `on_time_ship_rate_bps` is 0 when `shipped_unit_count` is 0 and otherwise 10000 multiplied by the sum of `quantity` over the on-time shipped lines, divided by `shipped_unit_count`, rounded half up; `cancellation_rate_bps` is 10000 multiplied by `cancelled_unit_count`, divided by `transmitted_unit_count`, rounded half up; and `defect_rate_bps` is 0 when `shipped_unit_count` is 0 and otherwise 10000 multiplied by `defect_unit_count`, divided by `shipped_unit_count`, rounded half up."

    The very same two lines weighed by units give nine cancelled units out of ten
    transmitted, so the cancellation rate is 9000 basis points and the composite
    falls two bands to WATCH with three padding days.

    Design: Difficulty/dual_variant_calc/scorecard_event_equal_vs_unit_weighted_diverges_on_vendor_domain
    """
    base = _one_shipped_line_and_one_cancelled_line(
        api, "SCB", "ORD-SCB-A", "ORD-SCB-B"
    )

    scorecard = validate_success(
        api.create_scorecard(
            base["vendor_id"],
            {
                "period_start": "2026-08-01",
                "period_end": "2026-08-31",
                "metric_variant": "UNIT_WEIGHTED",
            },
            OPS,
        ),
        201,
    )
    assert scorecard["transmitted_unit_count"] == 10
    assert scorecard["shipped_unit_count"] == 1
    assert scorecard["cancelled_unit_count"] == 9
    assert scorecard["defect_unit_count"] == 0
    assert scorecard["on_time_ship_rate_bps"] == 10000
    assert scorecard["cancellation_rate_bps"] == 9000
    assert scorecard["defect_rate_bps"] == 0
    assert scorecard["avg_ship_hours"] == 2.00
    assert scorecard["composite_score"] == 73.00
    assert scorecard["tier"] == "WATCH"
    assert scorecard["promise_padding_days"] == 3


def test_both_variants_stay_draft_and_leave_the_vendor_unrated(api):
    """PRD §3.9: "A `DRAFT` scorecard is inert — it never touches the vendor row, and neither `performance_tier` nor `promise_padding_days` on the vendor moves while it stays in draft."

    Computing both variants over the same period produces two SILVER-and-WATCH
    drafts, and neither of them may relabel the vendor: it stays UNRATED on the
    default two padding days until somebody publishes one.

    Design: Difficulty/dual_variant_calc/scorecard_event_equal_vs_unit_weighted_diverges_on_vendor_domain
    """
    base = _one_shipped_line_and_one_cancelled_line(
        api, "SCC", "ORD-SCC-A", "ORD-SCC-B"
    )
    period = {"period_start": "2026-08-01", "period_end": "2026-08-31"}

    event_equal = validate_success(
        api.create_scorecard(
            base["vendor_id"], {**period, "metric_variant": "EVENT_EQUAL"}, OPS
        ),
        201,
    )
    unit_weighted = validate_success(
        api.create_scorecard(
            base["vendor_id"], {**period, "metric_variant": "UNIT_WEIGHTED"}, OPS
        ),
        201,
    )
    assert event_equal["status"] == "DRAFT"
    assert unit_weighted["status"] == "DRAFT"
    assert event_equal["tier"] == "SILVER"
    assert unit_weighted["tier"] == "WATCH"

    vendor = refresh_vendor(api, base["vendor_id"])
    assert vendor["performance_tier"] == "UNRATED"
    assert vendor["promise_padding_days"] == 2
