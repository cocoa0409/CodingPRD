"""Meal-period pipeline state gates, production-forecast state/cardinality
rules, and the forecast-create OCC guard."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_forecast,
    create_forecast_payload,
    create_hall,
    create_published_cycle,
    create_recipe,
    create_scheduled_period,
    drive_period_to_forecast_locked,
    get_period,
    lock_forecast,
    setup_hall_cycle_recipe,
    suspend_hall,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["dining_admin_headers"]
HALL_MANAGER = TEST_USERS["hall_manager_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]


class TestMealPeriodBasics:
    def test_missing_period_returns_not_found(self, api):
        """PRD §2.7: "3. **Existence** — path identifiers resolve left-to-right,
        then request-body foreign keys resolve in their declared input order;
        failures yield `ERR_NOT_FOUND`."

        Design: Corner/entities/meal_period_not_found_returns_404
        """
        resp = api.get_meal_period(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)

    def test_open_service_before_forecast_lock_rejected(self, api):
        """PRD §3.3: "Opening service (`FORECAST_LOCKED` → `IN_SERVICE`) requires
        the hall to be `ACTIVE`; a suspended hall refuses with
        `ERR_HALL_SUSPENDED`."
        PRD §2.7: "4. **State** — the target entity sits in one of the
        transition's from-states (`ERR_INVALID_STATE`), and the cross-entity
        state gates live at this same tier: `ERR_HALL_SUSPENDED` when an
        operation requires an `ACTIVE` hall, `ERR_CONTRACT_NOT_ACTIVE` when a
        statement operation requires an `ACTIVE` contract,
        `ERR_FORECAST_LOCKED_PERIOD` when a forecast operation requires a
        `SCHEDULED` period, `ERR_PENDING_WASTE_LOGS` when a period close finds
        unposted waste, and `ERR_INSPECTION_INCOMPLETE` when a report close
        finds unverified actions."

        Design: Corner/state_machines/meal_period_open_before_lock_rejected
        """
        hall = create_hall(name="Hall SM1")
        cycle = create_published_cycle(hall["id"])
        period = create_scheduled_period(hall["id"], cycle["id"], "2026-08-24")
        resp = api.open_meal_period_service(period["id"], HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_period(period["id"])["status"] == "SCHEDULED"


class TestForecastStateGates:
    def test_forecast_create_after_period_lock_rejected(self, api):
        """PRD §3.3: "The parent period must still be `SCHEDULED`; once it has
        advanced past scheduling, forecast creation is refused with
        `ERR_FORECAST_LOCKED_PERIOD`."

        Design: Corner/state_machines/forecast_create_after_period_lock_rejected
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall SM9")
        recipe2 = create_recipe(hall["id"], name="R2", station="DELI",
                                popularity_share=0.3, unit_cost_cents=400)
        period = drive_period_to_forecast_locked(hall["id"], cycle["id"],
                                                 recipe["id"], "2026-08-28")
        fresh_version = get_period(period["id"])["version"]
        resp = api.create_production_forecast(
            period["id"],
            create_forecast_payload(recipe2["id"], fresh_version),
            KITCHEN_LEAD)
        validate_error(resp, ApiErrorId.ERR_FORECAST_LOCKED_PERIOD)
        assert get_period(period["id"])["status"] == "FORECAST_LOCKED"

    def test_lock_twice_rejected(self, api):
        """PRD §3.3: "Each forecast is stored against its period through its
        `meal_period_id`, starts `DRAFT`, and may be locked by a `KitchenLead`
        (`DRAFT` → `LOCKED`); locking likewise requires the parent period to
        still be `SCHEDULED`, else `ERR_FORECAST_LOCKED_PERIOD`."

        Design: Corner/state_machines/forecast_lock_twice_rejected
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall SM4")
        period = create_scheduled_period(hall["id"], cycle["id"], "2026-08-26")
        forecast = create_forecast(period["id"], recipe["id"])
        locked = lock_forecast(forecast["id"])
        assert locked["status"] == "LOCKED"
        resp = api.lock_production_forecast(forecast["id"], KITCHEN_LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_production_forecast(forecast["id"],
                                                             KITCHEN_LEAD))
        assert after["status"] == "LOCKED"
        assert after["version"] == locked["version"], (
            "the rejected second lock must not increment version")

    def test_duplicate_draft_forecast_rejected(self, api):
        """PRD §3.3: "Two forecasts for the same period-and-recipe pair may not
        both sit in `DRAFT` — a second attempt is refused with
        `ERR_DUPLICATE_FORECAST`."

        Design: Corner/errors/forecast_duplicate_draft_rejected
        """
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall E10")
        period = create_scheduled_period(hall["id"], cycle["id"], "2026-09-03")
        create_forecast(period["id"], recipe["id"])  # stays DRAFT
        fresh_version = get_period(period["id"])["version"]
        resp = api.create_production_forecast(
            period["id"],
            create_forecast_payload(recipe["id"], fresh_version),
            KITCHEN_LEAD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FORECAST)


class TestOpenServiceHallGate:
    def _setup_forecast_locked_then_suspend(self, api):
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall XE1")
        period = drive_period_to_forecast_locked(hall["id"], cycle["id"],
                                                 recipe["id"], "2026-08-13")
        suspend_hall(hall["id"])
        return hall, period

    def test_open_service_on_suspended_hall_rejected(self, api):
        """PRD §3.3: "Opening service (`FORECAST_LOCKED` → `IN_SERVICE`) requires
        the hall to be `ACTIVE`; a suspended hall refuses with
        `ERR_HALL_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/open_service_requires_hall_active
        """
        _hall, period = self._setup_forecast_locked_then_suspend(api)
        resp = api.open_meal_period_service(period["id"], HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_HALL_SUSPENDED)
        assert get_period(period["id"])["status"] == "FORECAST_LOCKED"

    def test_suspension_leaves_forecast_locked_period_untouched(self, api):
        """PRD §2.10: "Meal periods that have already advanced to
        `FORECAST_LOCKED` or beyond are deliberately *not* auto-cancelled,
        because they carry locked forecasts or live service data that must
        settle through their own lifecycle."

        Design: Difficulty/cross_entity_state_dependency/open_service_requires_hall_active
        """
        hall, period = self._setup_forecast_locked_then_suspend(api)
        assert get_period(period["id"])["status"] == "FORECAST_LOCKED", (
            "the hall-suspension cascade cancels only SCHEDULED periods")
        resp = api.reactivate_dining_hall(hall["id"], ADMIN)
        assert resp.status_code == 200
        opened = validate_success(api.open_meal_period_service(period["id"],
                                                               HALL_MANAGER))
        assert opened["status"] == "IN_SERVICE"


class TestForecastCreateOcc:
    def test_stale_period_version_rejected_then_fresh_retry_succeeds(self, api):
        """PRD §2.8: "Creating a production forecast against a meal period
        requires the request to carry `expected_meal_period_version`, holding
        the `version` of the parent `MealPeriodService` the client last
        observed. If the period's current `version` does not match — for
        instance because another planner has just created a forecast, which
        legitimately supersedes the prior locked forecast for the same recipe
        and advances the period's version — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a
        period state it has not observed."

        Design: Corner/cross_cutting_layers/occ_forecast_create_stale_version
        """
        hall, _recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall L1")
        recipe1 = create_recipe(hall["id"], name="R1", unit_cost_cents=500)
        recipe2 = create_recipe(hall["id"], name="R2", station="DELI",
                                popularity_share=0.4, unit_cost_cents=400)
        period = create_scheduled_period(hall["id"], cycle["id"], "2026-09-07")
        stale_version = period["version"]

        create_forecast(period["id"], recipe1["id"],
                        expected_version=stale_version)
        mid_version = get_period(period["id"])["version"]
        assert mid_version == stale_version + 1, (
            "each accepted forecast create advances the parent period's version")

        resp = api.create_production_forecast(
            period["id"],
            create_forecast_payload(recipe2["id"], stale_version),
            KITCHEN_LEAD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_period(period["id"])["version"]
        created = validate_success(api.create_production_forecast(
            period["id"],
            create_forecast_payload(recipe2["id"], fresh_version),
            KITCHEN_LEAD), expected_status=201)
        assert created["status"] == "DRAFT"
        assert get_period(period["id"])["version"] == fresh_version + 1


class TestLockedForecastCardinality:
    def _setup_period_with_locked_forecast(self, api):
        hall, recipe, cycle = setup_hall_cycle_recipe(hall_name="Hall INV2",
                                                      dining_capacity=1000)
        period = create_scheduled_period(hall["id"], cycle["id"], "2026-08-17")
        f1 = create_forecast(period["id"], recipe["id"])
        lock_forecast(f1["id"])
        return period, recipe, f1

    def test_successor_create_supersedes_incumbent_locked(self, api):
        """PRD §3.3: "When the create succeeds, any previously `LOCKED` forecast
        for the same pair is superseded by cascade, moving to `SUPERSEDED` with
        its own `version` incremented; the invariant maintained before and after
        is that at most one `LOCKED` forecast exists per period-and-recipe pair
        at any time."

        Design: Difficulty/compensating_invariant/forecast_locked_cardinality_conservation
        """
        period, recipe, f1 = self._setup_period_with_locked_forecast(api)
        f2 = create_forecast(period["id"], recipe["id"])
        assert f2["status"] == "DRAFT"
        f1_after = validate_success(api.get_production_forecast(f1["id"],
                                                                KITCHEN_LEAD))
        assert f1_after["status"] == "SUPERSEDED", (
            "the LOCKED count for the pair drops to 0 while the successor is DRAFT")

    def test_locking_successor_restores_exactly_one_locked(self, api):
        """PRD §3.3: "When the create succeeds, any previously `LOCKED` forecast
        for the same pair is superseded by cascade, moving to `SUPERSEDED` with
        its own `version` incremented; the invariant maintained before and after
        is that at most one `LOCKED` forecast exists per period-and-recipe pair
        at any time."

        Design: Difficulty/compensating_invariant/forecast_locked_cardinality_conservation
        """
        period, recipe, f1 = self._setup_period_with_locked_forecast(api)
        f2 = create_forecast(period["id"], recipe["id"])
        lock_forecast(f2["id"])
        data, meta = validate_paginated(api.list_production_forecasts(KITCHEN_LEAD))
        assert meta["total_count"] == 2, "history is retained, not deleted"
        pair = [row for row in data
                if row["meal_period_id"] == period["id"]
                and row["recipe_id"] == recipe["id"]]
        assert len(pair) == 2
        locked = [row for row in pair if row["status"] == "LOCKED"]
        superseded = [row for row in pair if row["status"] == "SUPERSEDED"]
        assert len(locked) == 1 and locked[0]["id"] == f2["id"]
        assert len(superseded) == 1 and superseded[0]["id"] == f1["id"]
