"""Meal orders: parallel prep/fulfillment dimensions, allergen gates,
household cap, delivery range, and the item-pull cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_meal_order,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    allocate,
    confirm_item,
    create_accepted_batch,
    create_guest,
    create_menu_day,
    create_menu_item,
    create_order,
    create_site,
    get_menu_day,
    lock_forecast,
    open_service,
    prep_order_to_ready,
    serve_order,
    set_clock,
    setup_open_service_with_volunteer,
    start_production,
)


class TestParallelDimensions:
    """Queue A: non_linear_state_machine / meal_order_parallel_dimensions."""

    def _setup_order_reworked_to_in_prep(self, api):
        ctx = setup_open_service_with_volunteer(
            service_date="2026-08-10", role_on_shift="PREP",
            guest_overrides={"full_name": "G P", "household_size": 2},
        )
        order = create_order(
            ctx["service"]["id"], ctx["guest"]["id"], ctx["item"]["id"], quantity=1
        )
        prep_order_to_ready(ctx, order["id"])
        order = get_success_data(
            api.rework_order(
                order["id"], {"reason": "allergen re-check flagged cross-contact"},
                ctx["volunteer_headers"],
            )
        )
        return ctx, order

    def test_serve_rejected_while_prep_in_prep_after_rework(self, api):
        """PRD 3.7: "When that re-check fails in practice, the rework loop
        moves `READY` back to `IN_PREP`, recording a `reason` and appending an
        audit note".
        PRD 3.7: "Serving moves `RESERVED` → `SERVED`, is performed by a
        `Volunteer`, and requires the order's `prep_status` to be `READY`, the
        service's `service_model` to be `DINE_IN`, and the service still
        `OPEN`."
        PRD 2.6: "State legality: the target entity is in a state from which
        the requested transition is defined, including all state-machine
        preconditions, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/meal_order_parallel_dimensions
        """
        ctx, order = self._setup_order_reworked_to_in_prep(api)
        assert order["prep_status"] == "IN_PREP", (
            f"rework must move prep back to IN_PREP, got {order['prep_status']!r}"
        )
        assert order["fulfillment_status"] == "RESERVED", (
            "rework touches only the prep dimension; fulfillment must stay "
            f"RESERVED, got {order['fulfillment_status']!r}"
        )

        resp = api.serve_order(order["id"], ctx["volunteer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rework_loop_recovers_to_ready_and_serves(self, api):
        """PRD 3.7: "The kitchen-side `prep_status` runs `QUEUED` → `IN_PREP`
        → `READY` with a rework loop back".
        PRD 3.7: "Marking an order ready moves `IN_PREP` → `READY`".
        PRD 3.7: "Serving moves `RESERVED` → `SERVED`, is performed by a
        `Volunteer`, and requires the order's `prep_status` to be `READY`, the
        service's `service_model` to be `DINE_IN`, and the service still
        `OPEN`."

        Design: Difficulty/non_linear_state_machine/meal_order_parallel_dimensions
        """
        ctx, order = self._setup_order_reworked_to_in_prep(api)

        order = get_success_data(api.mark_ready(order["id"], ctx["volunteer_headers"]))
        assert order["prep_status"] == "READY"

        order = serve_order(ctx, order["id"])
        assert order["fulfillment_status"] == "SERVED", (
            f"after rework recovery the order must serve, "
            f"got {order['fulfillment_status']!r}"
        )

        # Ledger cascade: served_count, visits_count, reserved_count.
        day = get_menu_day(ctx["menu_day"]["id"])
        assert day["served_count"] == 1
        guest = get_success_data(api.get_guest(ctx["guest"]["id"], MANAGER))
        assert guest["visits_count"] == 1
        service = get_success_data(api.get_meal_service(ctx["service"]["id"], MANAGER))
        assert service["reserved_count"] == 0


class TestAllergenGateAtOrderCreate:
    def test_allergen_conflict_at_order_create(self, api):
        """PRD 3.5: "The item's `allergen_tags` must have an empty
        intersection with the guest's `allergens` at creation time, else
        `ERR_ALLERGEN_CONFLICT`."

        Design: Corner/validations/allergen_conflict_at_order_create
        """
        ctx = setup_open_service_with_volunteer(
            service_date="2026-08-10",
            batch_overrides={"item_description": "satay",
                             "allergen_tags": ["PEANUT"]},
            item_overrides={"name": "Satay", "allergen_tags": ["PEANUT"]},
            guest_overrides={"full_name": "Allergic", "household_size": 2,
                             "allergens": ["PEANUT"]},
        )
        resp = api.create_meal_order(
            {
                "meal_service_id": ctx["service"]["id"],
                "guest_id": ctx["guest"]["id"],
                "menu_item_id": ctx["item"]["id"],
                "quantity": 1,
                "substitution_allowed": False,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT)


class TestHouseholdCap:
    def test_meal_order_quantity_capped_by_household(self, api):
        """PRD 3.5: "The `quantity` must be at least 1 and no more than the
        guest's `household_size`, else `ERR_CONSTRAINT_VIOLATION`."

        Design: Corner/entities/meal_order_quantity_capped_by_household
        """
        ctx = setup_open_service_with_volunteer(
            service_date="2026-08-10",
            guest_overrides={"full_name": "Solo", "household_size": 1},
        )
        resp = api.create_meal_order(
            {
                "meal_service_id": ctx["service"]["id"],
                "guest_id": ctx["guest"]["id"],
                "menu_item_id": ctx["item"]["id"],
                "quantity": 2,
                "substitution_allowed": False,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)


class TestDeliveryRange:
    def test_delivery_out_of_range(self, api):
        """PRD 3.5: "For a delivery service, the guest's
        `delivery_distance_km` must not exceed the site's
        `delivery_radius_km`, else `ERR_DELIVERY_OUT_OF_RANGE`."

        Design: Corner/validations/delivery_out_of_range
        """
        ctx = setup_open_service_with_volunteer(
            service_date="2026-08-10",
            service_overrides={"service_model": "DELIVERY"},
            guest_overrides={
                "full_name": "Far Guest", "household_size": 2,
                "delivery_address": "12km away", "delivery_distance_km": 12,
            },
        )
        # Site delivery_radius_km defaults to 8 in the factory; 12 > 8.
        resp = api.create_meal_order(
            {
                "meal_service_id": ctx["service"]["id"],
                "guest_id": ctx["guest"]["id"],
                "menu_item_id": ctx["item"]["id"],
                "quantity": 1,
                "substitution_allowed": False,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_OUT_OF_RANGE)


class TestBatchQuarantineCascade:
    """Queue A: transitive_cascade / batch_quarantine_item_orders_cascade."""

    def _setup_serving_day_with_order(self, api, substitution_allowed=False,
                                      add_second_item=False):
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Cascade Kitchen", dine_in_capacity=50,
                           togo_capacity_per_window=20, delivery_radius_km=8)
        # Headroom over the item's planned 20: exact-fit allocation would
        # auto-DEPLETE the batch (PRD 3.3), blocking both confirm (PRD 3.2)
        # and the routine re-inspection (PRD 3.3) this test drives later.
        batch = create_accepted_batch(
            site["id"], item_description="chicken", quantity_servings=30,
            unit_cost_cents_per_serving=80,
        )
        menu_day = create_menu_day(site["id"], "2026-08-10")
        item = create_menu_item(menu_day["id"], name="Chicken Plate",
                                planned_servings=20)
        allocate(item["id"], batch["id"], 20)
        confirm_item(item["id"])
        second_item = None
        if add_second_item:
            batch2 = create_accepted_batch(
                site["id"], item_description="rice", quantity_servings=10,
                received_at="2026-08-10T07:05:00Z",
            )
            second_item = create_menu_item(menu_day["id"], name="Rice Plate",
                                           planned_servings=5)
            allocate(second_item["id"], batch2["id"], 5)
            confirm_item(second_item["id"])
        guest = create_guest(full_name="G C", household_size=2)
        lock_forecast(menu_day["id"])
        start_production(menu_day["id"])
        from test_helpers.fixtures import create_service
        service = create_service(
            menu_day["id"], service_model="DINE_IN",
            window_start="2026-08-10T11:00:00Z",
            window_end="2026-08-10T13:00:00Z", capacity=5,
        )
        set_clock("2026-08-10T10:30:00Z")
        open_service(service["id"])
        order = create_order(
            service["id"], guest["id"], item["id"], quantity=1,
            substitution_allowed=substitution_allowed,
        )
        return site, batch, menu_day, item, second_item, service, order

    def _fail_routine_reinspection(self, api, batch_id):
        from test_helpers.fixtures import OFFICER
        get_success_data(api.begin_inspection(batch_id, OFFICER))
        return get_success_data(
            api.record_inspection(batch_id, {"result": "FAILED"}, OFFICER)
        )

    def test_quarantine_cascades_item_unavailable_order_released(self, api):
        """PRD 3.3: "A fail moves `INSPECTING` → `QUARANTINED`, sets
        `inspection_result` to `FAILED`, and fires a depth-3 cascade: every
        batch allocation drawn from this batch leads to its owning menu item,
        and each such item still `CONFIRMED` is moved to `UNAVAILABLE`; that
        item transition in turn cascades to its reserved orders
        (substitute-or-release, per §3.7) and decrements the parent menu
        day's `committed_servings` ledger."
        PRD 3.7: "otherwise the order is released, moving fulfillment to
        `RELEASED` and decrementing `reserved_count`."

        Design: Difficulty/transitive_cascade/batch_quarantine_item_orders_cascade
        """
        site, batch, menu_day, item, _, service, order = (
            self._setup_serving_day_with_order(api, substitution_allowed=False)
        )
        assert get_menu_day(menu_day["id"])["committed_servings"] == 20

        batch = self._fail_routine_reinspection(api, batch["id"])
        assert batch["status"] == "QUARANTINED"

        item = get_success_data(api.get_menu_item(item["id"], MANAGER))
        assert item["status"] == "UNAVAILABLE", (
            f"link 1: allocated CONFIRMED item must go UNAVAILABLE, "
            f"got {item['status']!r}"
        )
        order = get_success_data(api.get_meal_order(order["id"], MANAGER))
        assert order["fulfillment_status"] == "RELEASED", (
            f"link 2: order with substitution_allowed false must be released, "
            f"got {order['fulfillment_status']!r}"
        )
        service = get_success_data(api.get_meal_service(service["id"], MANAGER))
        assert service["reserved_count"] == 0, (
            f"link 2 side effect: reserved_count must fall to 0, "
            f"got {service['reserved_count']}"
        )
        day = get_menu_day(menu_day["id"])
        assert day["committed_servings"] == 0, (
            f"link 3: committed_servings ledger debits to 0, "
            f"got {day['committed_servings']}"
        )

    def test_quarantine_cascade_substitutes_when_allowed(self, api):
        """PRD 3.7: "if the order's `substitution_allowed` is set, the order
        is re-pointed to a `CONFIRMED`, allergen-compatible item on the same
        menu day chosen by the kitchen's selector policy".

        Design: Difficulty/transitive_cascade/batch_quarantine_item_orders_cascade
        """
        site, batch, menu_day, item, second_item, service, order = (
            self._setup_serving_day_with_order(
                api, substitution_allowed=True, add_second_item=True
            )
        )

        self._fail_routine_reinspection(api, batch["id"])

        order = get_success_data(api.get_meal_order(order["id"], MANAGER))
        assert order["fulfillment_status"] == "RESERVED", (
            f"substituted order stays in the pipeline, "
            f"got {order['fulfillment_status']!r}"
        )
        assert order["menu_item_id"] == second_item["id"], (
            "order must be re-pointed to the other CONFIRMED, "
            f"allergen-compatible item on the same day, got {order['menu_item_id']}"
        )
        service = get_success_data(api.get_meal_service(service["id"], MANAGER))
        assert service["reserved_count"] == 1, (
            f"substitution keeps the reservation: reserved_count 1, "
            f"got {service['reserved_count']}"
        )
