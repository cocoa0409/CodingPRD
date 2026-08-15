"""Production forecasting: BASE vs TREND dual variant, history thresholds,
the capacity fallback, swipe batch atomicity, and reconciliation variance."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_forecast,
    create_historical_period,
    create_scheduled_period,
    drive_period_to_in_service,
    get_period,
    lock_forecast,
    setup_hall_cycle_recipe,
    validate_error,
    validate_paginated,
    validate_success,
)

HALL_MANAGER = TEST_USERS["hall_manager_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]


def _setup_thursday_history(api, cover_counts=(100, 110, 120, 130),
                            start_date="2026-07-30"):
    """Four weekly Thursday LUNCH periods in IN_SERVICE with known cover counts,
    plus a fresh SCHEDULED target period for the following Thursday."""
    from datetime import date, timedelta
    hall, recipe, cycle = setup_hall_cycle_recipe(
        hall_name="North Hall", dining_capacity=1000, unit_cost_cents=800,
        dietary_flags=["VEGAN"])
    base = date.fromisoformat(start_date)
    for k, covers in enumerate(cover_counts):
        service_date = (base + timedelta(weeks=k)).isoformat()
        create_historical_period(hall["id"], cycle["id"], recipe["id"],
                                 service_date, meal_period="LUNCH",
                                 board_count=covers, end_state="IN_SERVICE")
    target_date = (base + timedelta(weeks=len(cover_counts))).isoformat()
    target = create_scheduled_period(hall["id"], cycle["id"], target_date, "LUNCH")
    return hall, recipe, target


class TestBaseVsTrendVariants:
    def test_base_variant_is_plain_moving_average(self, api):
        """PRD §3.3: "When at least two historical occurrences exist, their mean
        cover count is computed and rounded half-up to a whole number. Under the
        `BASE` variant — the default planning variant — that rounded mean is the
        period's base covers." And: "In all cases the forecast's
        `forecasted_portions` is the base covers multiplied by the recipe's
        `popularity_share` and then multiplied by 1.05 — a five percent
        preparation buffer — rounded half-up to a whole portion, and the
        computed `base_covers` is stored on the forecast alongside it."

        Design: Difficulty/dual_variant_calc/forecast_base_vs_trend_variants
        """
        _hall, recipe, target = _setup_thursday_history(api)
        forecast = create_forecast(target["id"], recipe["id"], variant="BASE")
        # mean(100, 110, 120, 130) = 115; round_half_up(115 * 0.5 * 1.05) = 60
        assert forecast["base_covers"] == 115
        assert forecast["forecasted_portions"] == 60
        assert forecast["status"] == "DRAFT"

    def test_trend_variant_adds_slope_and_supersedes_locked_base(self, api):
        """PRD §3.3: "Under the `TREND` variant, a linear slope is added: the
        difference between the newest occurrence's covers and the oldest
        occurrence's covers, divided by one less than the number of selected
        occurrences (which ranges from two to four), is added to the mean, and
        the sum is rounded half-up to give base covers; a non-zero slope
        therefore always produces a different portion count than the plain
        average."
        PRD §3.3: "When the create succeeds, any previously `LOCKED` forecast
        for the same pair is superseded by cascade, moving to `SUPERSEDED` with
        its own `version` incremented; the invariant maintained before and after
        is that at most one `LOCKED` forecast exists per period-and-recipe pair
        at any time."

        Design: Difficulty/dual_variant_calc/forecast_base_vs_trend_variants
        """
        _hall, recipe, target = _setup_thursday_history(api)
        base_forecast = create_forecast(target["id"], recipe["id"], variant="BASE")
        lock_forecast(base_forecast["id"])
        trend = create_forecast(target["id"], recipe["id"], variant="TREND")
        # slope = (130 - 100) / (4 - 1) = 10; base = round_half_up(115 + 10) = 125;
        # portions = round_half_up(125 * 0.5 * 1.05) = round_half_up(65.625) = 66
        assert trend["base_covers"] == 125
        assert trend["forecasted_portions"] == 66
        assert trend["variant"] == "TREND"
        assert trend["status"] == "DRAFT"
        base_after = validate_success(api.get_production_forecast(
            base_forecast["id"], KITCHEN_LEAD))
        assert base_after["status"] == "SUPERSEDED", (
            "both forecasts share identical history inputs — only the variant "
            "differs; creating the successor supersedes the LOCKED incumbent")


class TestInsufficientHistory:
    def test_trend_with_single_occurrence_rejected_base_falls_back(self, api):
        """PRD §3.3: "When fewer than two historical occurrences exist, a `TREND`
        request is refused with `ERR_INSUFFICIENT_HISTORY`, while `BASE` falls
        back to the hall's seats: base covers is the hall's `dining_capacity`
        multiplied by 60 percent, rounded half-up."

        Design: Corner/calculations/forecast_insufficient_history_rejected
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(
            hall_name="Hall C1", dining_capacity=1000)
        create_historical_period(hall["id"], cycle["id"], recipe["id"],
                                 "2026-08-05", board_count=10,
                                 end_state="IN_SERVICE")
        target = create_scheduled_period(hall["id"], cycle["id"], "2026-08-12")
        version = get_period(target["id"])["version"]

        resp = api.create_production_forecast(
            target["id"],
            {"recipe_id": recipe["id"], "variant": "TREND",
             "expected_meal_period_version": version},
            KITCHEN_LEAD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_HISTORY)

        # Same request under BASE succeeds via the capacity fallback.
        base = create_forecast(target["id"], recipe["id"], variant="BASE")
        # round_half_up(1000 * 0.60) = 600; round_half_up(600 * 0.5 * 1.05) = 315
        assert base["base_covers"] == 600
        assert base["forecasted_portions"] == 315


class TestSwipeBatchAtomicity:
    def test_invalid_element_rejects_whole_batch(self, api):
        """PRD §3.3: "The batch is all-or-nothing — any invalid element rejects
        the entire batch with `ERR_VALIDATION` and nothing is persisted. The
        amount rule is conditional on entry type: a `RETAIL_SALE` must carry an
        `amount_cents` strictly greater than 0, while a `BOARD_SWIPE` must carry
        exactly 0."

        Design: Corner/validations/swipe_batch_atomic_conditional_amount
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall V2")
        period = drive_period_to_in_service(hall["id"], cycle["id"], recipe["id"],
                                            "2026-08-31")

        resp1 = api.ingest_swipes(
            period["id"],
            {"events": [{"entry_type": "BOARD_SWIPE", "amount_cents": 5,
                         "count": 1}]},
            HALL_MANAGER)
        validate_error(resp1, ApiErrorId.ERR_VALIDATION)

        resp2 = api.ingest_swipes(
            period["id"],
            {"events": [
                {"entry_type": "BOARD_SWIPE", "amount_cents": 0, "count": 2},
                {"entry_type": "RETAIL_SALE", "amount_cents": 0, "count": 1},
            ]},
            HALL_MANAGER)
        validate_error(resp2, ApiErrorId.ERR_VALIDATION)

        data, meta = validate_paginated(api.list_swipe_events(HALL_MANAGER))
        assert meta["total_count"] == 0, (
            "the 2 valid board swipes in batch 2 were NOT persisted — the batch "
            "is atomic")


class TestReconcileVarianceNull:
    def test_variance_null_when_forecasted_covers_zero(self, api):
        """PRD §3.3: "The `forecast_variance_pct` is then the actual covers minus
        the forecasted covers, divided by the forecasted covers, times one
        hundred, carried to 2 decimal places rounded half-up; when
        `forecasted_covers` is 0 the variance is null rather than a division by
        zero."

        Design: Corner/calculations/reconcile_variance_null_when_forecast_zero
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(
            hall_name="Hall C3", dining_capacity=1000)
        # Two zero-cover Wednesday LUNCH occurrences -> BASE mean is 0.
        for service_date in ("2026-08-05", "2026-08-12"):
            create_historical_period(hall["id"], cycle["id"], recipe["id"],
                                     service_date, board_count=0,
                                     end_state="IN_SERVICE")
        period = create_scheduled_period(hall["id"], cycle["id"], "2026-08-19")
        forecast = create_forecast(period["id"], recipe["id"], variant="BASE")
        assert forecast["forecasted_portions"] == 0, (
            "mean 0 * 0.5 * 1.05 rounds to 0 portions")
        lock_forecast(forecast["id"])
        locked = validate_success(api.lock_meal_period_forecast(period["id"],
                                                                HALL_MANAGER))
        assert locked["forecasted_covers"] == 0

        validate_success(api.open_meal_period_service(period["id"], HALL_MANAGER))
        validate_success(api.ingest_swipes(
            period["id"],
            {"events": [{"entry_type": "BOARD_SWIPE", "amount_cents": 0,
                         "count": 5}]},
            HALL_MANAGER), expected_status=201)
        reconciled = validate_success(api.reconcile_meal_period(period["id"],
                                                                HALL_MANAGER))
        assert reconciled["actual_covers"] == 5
        assert reconciled["forecast_variance_pct"] is None, (
            "division by a zero forecast yields null, not an error")
