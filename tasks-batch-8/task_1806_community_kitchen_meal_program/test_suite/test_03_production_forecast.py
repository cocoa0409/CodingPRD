"""Production forecast: dual-variant divergence and the empty-history seed."""
import pytest

from test_helpers import (
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    allocate,
    confirm_item,
    create_accepted_batch,
    create_menu_day,
    create_menu_item,
    create_reconciled_day,
    create_site,
    create_volunteer,
    create_guest,
    get_menu_day,
    lock_forecast,
    set_clock,
)


def _build_history(site_id, guest_id, volunteer_id):
    """Two reconciled days on one site: Friday 2026-08-21 served 100,
    Monday 2026-08-24 served 10 (PRD 3.2 forecast input set)."""
    create_reconciled_day(
        site_id,
        "2026-08-21",
        served_quantity=100,
        guest_id=guest_id,
        volunteer_id=volunteer_id,
        batch_quantity=120,
        planned_servings=100,
        window_start="2026-08-21T11:00:00Z",
        window_end="2026-08-21T13:00:00Z",
        shift_start="2026-08-21T10:00:00Z",
        shift_end="2026-08-21T14:00:00Z",
        service_clock="2026-08-21T10:30:00Z",
        service_capacity=200,
        batch_use_by="2026-09-30T00:00:00Z",
    )
    create_reconciled_day(
        site_id,
        "2026-08-24",
        served_quantity=10,
        guest_id=guest_id,
        volunteer_id=volunteer_id,
        batch_quantity=20,
        planned_servings=10,
        window_start="2026-08-24T11:00:00Z",
        window_end="2026-08-24T13:00:00Z",
        shift_start="2026-08-24T10:00:00Z",
        shift_end="2026-08-24T14:00:00Z",
        service_clock="2026-08-24T10:30:00Z",
        service_capacity=200,
        batch_use_by="2026-09-30T00:00:00Z",
    )


def _fresh_draft_day_with_confirmed_item(site_id, service_date, variant):
    set_clock("2026-08-27T08:00:00Z")
    batch = create_accepted_batch(
        site_id, item_description="forecast stock", quantity_servings=10,
        received_at="2026-08-27T07:00:00Z", use_by="2026-09-10T00:00:00Z",
        unit_cost_cents_per_serving=50,
    )
    menu_day = create_menu_day(site_id, service_date, forecast_variant=variant)
    item = create_menu_item(menu_day["id"], name="Forecast Meal", planned_servings=5)
    allocate(item["id"], batch["id"], 5)
    confirm_item(item["id"])
    return menu_day


class TestForecastVariantDivergence:
    def test_trailing_average_and_dow_weighted_diverge(self, api):
        """PRD 3.2: "Under the `TRAILING_AVERAGE` variant, the forecast is the
        mean of the `served_count` values over all such reconciled days,
        regardless of weekday, multiplied by a growth factor of 1.05, with the
        product rounded up to the next whole serving. Under the `DOW_WEIGHTED`
        variant, the system blends two means — the mean `served_count` of the
        most recent four reconciled menu days at the site falling on the same
        weekday as the `service_date`, weighted six-tenths, and the mean
        `served_count` over all reconciled days in the same twenty-eight-day
        window regardless of weekday, weighted four-tenths — rounds the blend
        up to a whole serving first, and then multiplies by the 1.05 growth
        factor."
        PRD 2.10: "Servings are whole numbers; where a computation yields a
        fractional serving count, such as the production forecast, the result
        is rounded up to the next whole serving."

        Design: Difficulty/dual_variant_calc/production_forecast_variant_divergence
        """
        set_clock("2026-08-20T08:00:00Z")
        s1 = create_site(name="Site One", dine_in_capacity=200,
                         togo_capacity_per_window=100, delivery_radius_km=10)
        s2 = create_site(name="Site Two", dine_in_capacity=200,
                         togo_capacity_per_window=100, delivery_radius_km=10)
        guest = create_guest(full_name="Big Household", household_size=120)
        v1 = create_volunteer(full_name="Vol One")
        v2 = create_volunteer(full_name="Vol Two")

        # Identical history on both sites: Friday 100 served, Monday 10 served.
        _build_history(s1["id"], guest["id"], v1["id"])
        _build_history(s2["id"], guest["id"], v2["id"])

        # Fresh days on 2026-08-28 (a Friday), one per variant.
        f1 = _fresh_draft_day_with_confirmed_item(s1["id"], "2026-08-28", "TRAILING_AVERAGE")
        f2 = _fresh_draft_day_with_confirmed_item(s2["id"], "2026-08-28", "DOW_WEIGHTED")

        d1 = lock_forecast(f1["id"])
        d2 = lock_forecast(f2["id"])

        # TRAILING_AVERAGE: ceil(mean(100, 10) * 1.05) = ceil(57.75) = 58.
        assert d1["forecast_servings"] == 58, (
            f"TRAILING_AVERAGE forecast must be 58, got {d1['forecast_servings']}"
        )
        # DOW_WEIGHTED: ceil(ceil(0.6*100 + 0.4*55) * 1.05) = ceil(86.1) = 87.
        assert d2["forecast_servings"] == 87, (
            f"DOW_WEIGHTED forecast must be 87, got {d2['forecast_servings']}"
        )
        assert d1["forecast_servings"] != d2["forecast_servings"], (
            "identical history under different variants must pin different forecasts"
        )

    def test_forecast_seeded_at_sixty_without_history(self, api):
        """PRD 3.2: "If no reconciled history exists at all, the forecast is
        seeded at sixty servings."

        Design: Difficulty/dual_variant_calc/production_forecast_variant_divergence
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Seed Kitchen", dine_in_capacity=50,
                           togo_capacity_per_window=20, delivery_radius_km=8)
        batch = create_accepted_batch(site["id"], quantity_servings=10)
        menu_day = create_menu_day(site["id"], "2026-08-12")
        item = create_menu_item(menu_day["id"], name="Seed Meal", planned_servings=5)
        allocate(item["id"], batch["id"], 5)
        confirm_item(item["id"])

        day = lock_forecast(menu_day["id"])
        assert day["forecast_servings"] == 60, (
            f"empty reconciled history must seed the forecast at 60, "
            f"got {day['forecast_servings']}"
        )
