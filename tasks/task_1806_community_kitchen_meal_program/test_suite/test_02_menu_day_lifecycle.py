"""Menu day lifecycle: uniqueness, invalid transitions, terminal lockdown,
OCC on lock-forecast, and parent version increments from ledger sync."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_menu_day,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    allocate,
    confirm_item,
    create_accepted_batch,
    create_menu_day,
    create_menu_item,
    create_site,
    get_menu_day,
    set_clock,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestMenuDayUniqueness:
    def test_menu_day_duplicate_site_date_rejected(self, api):
        """PRD 3.2: "Only one menu day may exist per site and service date; a
        duplicate pair is rejected with `ERR_CONSTRAINT_VIOLATION`."

        Design: Corner/entities/menu_day_duplicate_site_date_rejected
        """
        site = create_site(name="Dup Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        payload = {"site_id": site["id"], "service_date": "2026-08-11"}
        get_success_data(api.create_menu_day(payload, MANAGER))

        resp = api.create_menu_day(payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)

        # A different service_date for the same site is accepted.
        resp = api.create_menu_day(
            {"site_id": site["id"], "service_date": "2026-08-12"}, MANAGER
        )
        data = validate_success(resp, 201)
        assert_menu_day(data)


class TestMenuDayStateMachine:
    def test_menu_day_invalid_transition_skip_forecast(self, api):
        """PRD 3.2: "Starting production moves the day `FORECAST_LOCKED` →
        `IN_PRODUCTION`".
        PRD 2.6: "State legality: the target entity is in a state from which
        the requested transition is defined, including all state-machine
        preconditions, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/menu_day_invalid_transition_skip_forecast
        """
        site = create_site(name="SM Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        assert menu_day["status"] == "DRAFT"

        resp = api.start_production(menu_day["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_menu_day_terminal_lockdown(self, api):
        """PRD 3.2: "its lifecycle runs `DRAFT` → `FORECAST_LOCKED` →
        `IN_PRODUCTION` → `SERVING` → `RECONCILED`, with `CANCELLED` as the
        early-exit terminal state available from `DRAFT`."
        PRD 2.6: "State legality: the target entity is in a state from which
        the requested transition is defined, including all state-machine
        preconditions, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/menu_day_terminal_lockdown
        """
        site = create_site(name="Term Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        resp = api.cancel_menu_day(menu_day["id"], MANAGER)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

        # CANCELLED is terminal: a second cancel is not a defined transition.
        resp = api.cancel_menu_day(menu_day["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_lock_forecast(self, api):
        """PRD 2.8: "Locking a menu day's forecast requires the request to
        carry `expected_menu_day_version` equal to the menu day's current
        `version`; if the version the client last observed no longer matches —
        because, for example, an intervening item confirmation advanced the
        menu day's version through ledger synchronization, invalidating the
        client's view of `committed_servings` — the lock is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_on_lock_forecast
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="OCC Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        batch = create_accepted_batch(site["id"], item_description="flour",
                                      quantity_servings=10,
                                      unit_cost_cents_per_serving=50)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        item = create_menu_item(menu_day["id"], name="Bread", planned_servings=5)
        allocate(item["id"], batch["id"], 5)

        # Capture the version BEFORE confirm bumps it via ledger sync.
        v_pre = get_menu_day(menu_day["id"])["version"]
        confirm_item(item["id"])

        resp = api.lock_forecast(
            menu_day["id"], {"expected_menu_day_version": v_pre}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        # Retry with the fresh version succeeds.
        v_now = get_menu_day(menu_day["id"])["version"]
        resp = api.lock_forecast(
            menu_day["id"], {"expected_menu_day_version": v_now}, MANAGER
        )
        data = validate_success(resp, 200)
        assert data["status"] == "FORECAST_LOCKED"


class TestVersionIncrements:
    def test_version_increments_on_every_mutation(self, api):
        """PRD 2.4: "`version` (integer): incremented by one on every mutation
        of the resource, including mutations that only touch derived or ledger
        fields."
        PRD 3.2: "Confirming is a ledger event: the menu day's
        `committed_servings` increases by the item's `planned_servings`, the
        day's `overproduction_ratio` is recomputed, and the menu day's own
        `version` increments as the parent ledger mutation."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Ver Site", dine_in_capacity=30,
                           togo_capacity_per_window=15, delivery_radius_km=5)
        batch = create_accepted_batch(site["id"], item_description="flour",
                                      quantity_servings=10,
                                      unit_cost_cents_per_serving=50)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        v0 = menu_day["version"]
        assert isinstance(v0, int)

        item = create_menu_item(menu_day["id"], name="Bread", planned_servings=5)
        allocate(item["id"], batch["id"], 5)
        confirm_item(item["id"])

        v1 = get_menu_day(menu_day["id"])["version"]
        assert v1 == v0 + 1, (
            f"item confirm must bump the parent menu day version by exactly 1: "
            f"{v0} -> {v1}"
        )
        day = get_menu_day(menu_day["id"])
        assert day["committed_servings"] == 5, (
            f"committed_servings must rise by planned_servings on confirm, "
            f"got {day['committed_servings']}"
        )
