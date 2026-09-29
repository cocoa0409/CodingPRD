"""Prorated baselines, the two-decimal rounding chain and variant inputs."""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN_HQ_HEADERS,
    ApiErrorId,
    assert_cents,
    make_manufacturer_headers,
)
from test_helpers.factories import lift_measurement_payload
from test_helpers.fixtures import (
    approve,
    event_version,
    new_baseline,
    new_club,
    new_demo_event,
    new_manufacturer,
    new_non_food_product,
    submit,
)
from test_helpers.types import (
    DayPart,
    MeasurementVariant,
    ProductCategory,
    WindowBoundary,
)


def _decimal2(value):
    """Coerce a two-decimal API value into an exact Decimal for comparison."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_the_prorated_baseline_is_rounded_before_the_downstream_figures_use_it(api):
    """PRD §3.8: "`baseline_units_expected` prorates the weekly baseline over the window: it is the snapshotted `baseline_weekly_units` multiplied by `attribution_days`, divided by 7, rounded half-up to two decimal places."

    PRD §3.8: "`lift_units` is `units_sold_in_window` less `baseline_units_expected` less `cannibalization_units`, rounded half-up to two decimal places; it may legitimately be negative when a demo underperformed its own baseline."

    PRD §3.8: "`lift_pct` reads 0.00 whenever `baseline_units_expected` is zero, and otherwise is `lift_units` divided by `baseline_units_expected`, multiplied by 100, rounded half-up to two decimal places."

    PRD §3.8: "`incremental_revenue_cents` is `lift_units` multiplied by the snapshotted `baseline_unit_price_cents`, rounded half-up to whole cents."

    PRD §3.8: "Its `attribution_days` is fixed at 3, its `window_boundary` is `CLOSED`, its `window_start_date` is the event's `event_date`, and its `window_end_date` is the `event_date` plus two days — that is, the `event_date` plus one day fewer than `attribution_days` — with that end date **included** in the window."

    Design: Corner/calculations/provisional_lift_rounds_a_non_terminating_baseline_quotient_to_two_decimals
    """
    vendor = new_manufacturer(api, legal_name="Zellwood Brands", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6023",
        name="Zellwood Club 6023",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="ZB-MUG-023",
        name="Travel Mug",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1600,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    baseline = new_baseline(
        api,
        club["id"],
        product["id"],
        baseline_weekly_units=50,
        baseline_unit_price_cents=499,
        baseline_week_start_date="2026-09-14",
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=3,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])
    vendor_headers = make_manufacturer_headers(vendor["id"])

    measurement = validate_success(
        api.create_lift_measurement(
            event["id"],
            lift_measurement_payload(
                MeasurementVariant.PROVISIONAL, 30, event_version(api, event["id"])
            ),
            vendor_headers,
        ),
        201,
    )

    assert measurement["attribution_days"] == 3
    assert measurement["window_boundary"] == WindowBoundary.CLOSED
    assert measurement["window_start_date"] == "2026-09-14"
    assert measurement["window_end_date"] == "2026-09-16"
    assert _decimal2(measurement["baseline_units_expected"]) == Decimal("21.43")
    assert _decimal2(measurement["cannibalization_units"]) == Decimal("0.00")
    assert _decimal2(measurement["lift_units"]) == Decimal("8.57")
    assert _decimal2(measurement["lift_pct"]) == Decimal("39.99")
    assert_cents(measurement["incremental_revenue_cents"], 4276, "incremental_revenue_cents")
    assert measurement["baseline_weekly_units"] == 50
    assert_cents(measurement["baseline_unit_price_cents"], 499, "baseline_unit_price_cents")

    stored_baseline = validate_success(api.get_baseline(baseline["id"], ADMIN_HQ_HEADERS))
    assert stored_baseline["restatement_count"] == 0


def test_the_final_variant_needs_a_filed_count_that_the_provisional_one_does_not(api):
    """PRD §3.8: "Before it can be computed it requires the event's reconciliation row to exist; when none does, the posting is refused with `ERR_RECONCILIATION_UNRESOLVED`."

    PRD §3.8: "Its `cannibalization_units` is 0.00; no deduction is taken for the samples the demo itself gave away."

    PRD §3.8: "Its `attribution_days` is the event's own `attribution_window_days`, its `window_boundary` is `HALF_OPEN`, its `window_start_date` is again the event's `event_date`, and its `window_end_date` is the `event_date` plus `attribution_days` days with that end date **excluded** from the window."

    PRD §2.8: "**Reconciliation resolved.** Issuing an invoice requires the event's reconciliation to be in `BALANCED` or `WRITTEN_OFF`, and posting a `FINAL` lift measurement requires a reconciliation row to exist at all. Either failure is `ERR_RECONCILIATION_UNRESOLVED` (409)."

    Design: Corner/calculations/final_lift_variant_requires_a_reconciliation_row_while_provisional_does_not
    """
    vendor = new_manufacturer(api, legal_name="Abercarn Home", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6024",
        name="Abercarn Club 6024",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="AH-TWL-024",
        name="Bath Towel Set",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=2900,
        samples_per_case=4,
        weekly_sample_case_pool=20,
    )
    new_baseline(
        api,
        club["id"],
        product["id"],
        baseline_weekly_units=70,
        baseline_unit_price_cents=500,
        baseline_week_start_date="2026-09-14",
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=3,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])
    guard_version = event_version(api, event["id"])

    validate_error(
        api.create_lift_measurement(
            event["id"],
            lift_measurement_payload(MeasurementVariant.FINAL, 100, guard_version),
            ADMIN_HQ_HEADERS,
        ),
        ApiErrorId.RECONCILIATION_UNRESOLVED,
        409,
    )

    provisional = validate_success(
        api.create_lift_measurement(
            event["id"],
            lift_measurement_payload(MeasurementVariant.PROVISIONAL, 100, guard_version),
            ADMIN_HQ_HEADERS,
        ),
        201,
    )

    assert provisional["measurement_variant"] == MeasurementVariant.PROVISIONAL
    assert provisional["attribution_days"] == 3
    assert provisional["window_boundary"] == WindowBoundary.CLOSED
    assert _decimal2(provisional["cannibalization_units"]) == Decimal("0.00")
    assert _decimal2(provisional["baseline_units_expected"]) == Decimal("30.00")

    stored_event = validate_success(
        api.get_demo_event(event["id"], make_manufacturer_headers(vendor["id"]))
    )
    assert stored_event["attribution_window_days"] == 14

    final_rows = validate_success(
        api.list_lift_measurements(
            event["id"],
            ADMIN_HQ_HEADERS,
            {"measurement_variant": MeasurementVariant.FINAL},
        )
    )
    assert final_rows == []
