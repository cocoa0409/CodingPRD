"""Meal services: capacity boundary, release conservation, close auto-expiry,
to-go capacity shape, supervisor gate, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_meal_order,
    assert_meal_service,
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
    create_service,
    create_site,
    get_menu_day,
    lock_forecast,
    open_service,
    set_clock,
    setup_open_service_with_volunteer,
    start_production,
)


def _open_dine_in_service(api, capacity, num_guests=3, planned=10):
    """Serving chain: menu day SERVING, DINE_IN service OPEN with `capacity`,
    plus a pool of guests with household_size 2."""
    set_clock("2026-08-10T08:00:00Z")
    site = create_site(dine_in_capacity=50, togo_capacity_per_window=20,
                       delivery_radius_km=8)
    # Headroom over planned: exact-fit allocation would auto-DEPLETE the batch
    # (PRD 3.3) and the confirm gate requires status ACCEPTED (PRD 3.2).
    batch = create_accepted_batch(site["id"], quantity_servings=planned + 10)
    menu_day = create_menu_day(site["id"], "2026-08-10")
    item = create_menu_item(menu_day["id"], planned_servings=planned)
    allocate(item["id"], batch["id"], planned)
    confirm_item(item["id"])
    guests = [create_guest(household_size=2) for _ in range(num_guests)]
    lock_forecast(menu_day["id"])
    start_production(menu_day["id"])
    service = create_service(
        menu_day["id"], service_model="DINE_IN",
        window_start="2026-08-10T11:00:00Z",
        window_end="2026-08-10T13:00:00Z", capacity=capacity,
    )
    set_clock("2026-08-10T10:30:00Z")
    open_service(service["id"])
    return site, menu_day, item, service, guests


class TestServiceCapacityExactFill:
    """Queue A: boundary_precision_check / service_capacity_exact_fill."""

    def test_capacity_two_accepts_second_rejects_third(self, api):
        """PRD 3.5: "an order is accepted while the service's `reserved_count`
        remains strictly below its `capacity` — the order that brings the
        count exactly up to capacity is the last one accepted, and the next
        reservation attempt is rejected with `ERR_CAPACITY_FULL`."

        Design: Difficulty/boundary_precision_check/service_capacity_exact_fill
        """
        site, menu_day, item, service, guests = _open_dine_in_service(api, capacity=2)

        o1 = create_order(service["id"], guests[0]["id"], item["id"], quantity=1)
        assert_meal_order(o1)
        o2 = create_order(service["id"], guests[1]["id"], item["id"], quantity=1)
        assert_meal_order(o2)

        service = get_success_data(api.get_meal_service(service["id"], MANAGER))
        assert service["reserved_count"] == 2

        resp = api.create_meal_order(
            {
                "meal_service_id": service["id"],
                "guest_id": guests[2]["id"],
                "menu_item_id": item["id"],
                "quantity": 1,
                "substitution_allowed": False,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL)

    def test_capacity_one_accepts_first_rejects_second(self, api):
        """PRD 3.5: "an order is accepted while the service's `reserved_count`
        remains strictly below its `capacity` — the order that brings the
        count exactly up to capacity is the last one accepted, and the next
        reservation attempt is rejected with `ERR_CAPACITY_FULL`."

        Design: Difficulty/boundary_precision_check/service_capacity_exact_fill
        """
        site, menu_day, item, service, guests = _open_dine_in_service(api, capacity=1)

        create_order(service["id"], guests[0]["id"], item["id"], quantity=1)
        resp = api.create_meal_order(
            {
                "meal_service_id": service["id"],
                "guest_id": guests[1]["id"],
                "menu_item_id": item["id"],
                "quantity": 1,
                "substitution_allowed": False,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL)


class TestCapacityReturnedOnRelease:
    """Queue A: compensating_invariant / service_capacity_returned_on_release."""

    def test_release_frees_slot_for_new_order(self, api):
        """PRD 3.7: "Release is the no-charge cancellation path, `RESERVED` →
        `RELEASED`, returning capacity to the pool."
        PRD 3.7: "Every release decrements the service's `reserved_count` by
        one and re-evaluates whether the referenced item has sold out."

        Design: Difficulty/compensating_invariant/service_capacity_returned_on_release
        """
        site, menu_day, item, service, guests = _open_dine_in_service(
            api, capacity=1, num_guests=2
        )
        o1 = create_order(service["id"], guests[0]["id"], item["id"], quantity=1)

        get_success_data(api.release_order(o1["id"], MANAGER))
        service = get_success_data(api.get_meal_service(service["id"], MANAGER))
        assert service["reserved_count"] == 0, (
            f"release must return the slot: reserved_count 0, "
            f"got {service['reserved_count']}"
        )

        # The returned slot is real: a fresh order on the full-again service.
        o2 = create_order(service["id"], guests[1]["id"], item["id"], quantity=1)
        assert_meal_order(o2)

    def test_release_decrements_reserved_count_by_one(self, api):
        """PRD 3.7: "Every release decrements the service's `reserved_count`
        by one and re-evaluates whether the referenced item has sold out."

        Design: Difficulty/compensating_invariant/service_capacity_returned_on_release
        """
        site, menu_day, item, service, guests = _open_dine_in_service(
            api, capacity=5, num_guests=2
        )
        o1 = create_order(service["id"], guests[0]["id"], item["id"], quantity=1)
        o2 = create_order(service["id"], guests[1]["id"], item["id"], quantity=1)

        service = get_success_data(api.get_meal_service(service["id"], MANAGER))
        assert service["reserved_count"] == 2

        get_success_data(api.release_order(o1["id"], MANAGER))
        service = get_success_data(api.get_meal_service(service["id"], MANAGER))
        assert service["reserved_count"] == 1, (
            f"one release must decrement reserved_count to 1, "
            f"got {service['reserved_count']}"
        )


class TestServiceCloseAutoExpiry:
    def test_service_close_auto_expires_reserved_orders(self, api):
        """PRD 3.6: "Closing is terminal and available from either `OPEN` or
        `PAUSED`: every order still non-terminal — fulfillment `RESERVED`,
        whatever its preparation state — is automatically moved to `EXPIRED`,
        and the service's `reserved_count` is decremented once per expired
        order."

        Design: Corner/state_machines/service_close_auto_expires_reserved_orders
        """
        site, menu_day, item, service, guests = _open_dine_in_service(
            api, capacity=5, num_guests=1
        )
        order = create_order(service["id"], guests[0]["id"], item["id"], quantity=1)

        resp = api.close_service(service["id"], MANAGER)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED"
        assert data["reserved_count"] == 0, (
            f"close must decrement reserved_count per expired order, "
            f"got {data['reserved_count']}"
        )

        order = get_success_data(api.get_meal_order(order["id"], MANAGER))
        assert order["fulfillment_status"] == "EXPIRED", (
            f"still-RESERVED order must auto-expire at close, "
            f"got {order['fulfillment_status']!r}"
        )


class TestTogoCapacityShape:
    def test_togo_capacity_shape_rule(self, api):
        """PRD 3.6: "a to-go service's capacity must not exceed the site's
        `togo_capacity_per_window` multiplied by the number of whole
        thirty-minute slots that fit inside the window; and a delivery
        service's capacity is unbounded by site shape, since every delivery
        order is instead range-checked individually. A broken shape rule is
        rejected with `ERR_CONSTRAINT_VIOLATION`."

        Design: Corner/endpoints/togo_capacity_shape_rule
        """
        # The menu day must be IN_PRODUCTION: state legality (PRD 2.6 priority
        # 4, "attaching a service to a day in any other state is rejected with
        # ERR_INVALID_STATE") precedes the capacity-shape rule (priority 7).
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="TG Site", dine_in_capacity=30,
                           togo_capacity_per_window=20, delivery_radius_km=5)
        batch = create_accepted_batch(site["id"], quantity_servings=20)
        menu_day = create_menu_day(site["id"], "2026-08-11")
        item = create_menu_item(menu_day["id"], name="TG Meal", planned_servings=10)
        allocate(item["id"], batch["id"], 10)
        confirm_item(item["id"])
        lock_forecast(menu_day["id"])
        start_production(menu_day["id"])

        # 60-minute window = 2 whole 30-minute slots -> max capacity 40.
        resp = api.create_meal_service(
            {
                "menu_day_id": menu_day["id"],
                "service_model": "TO_GO",
                "window_start": "2026-08-11T11:00:00Z",
                "window_end": "2026-08-11T12:00:00Z",
                "capacity": 41,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)

        resp = api.create_meal_service(
            {
                "menu_day_id": menu_day["id"],
                "service_model": "TO_GO",
                "window_start": "2026-08-11T11:00:00Z",
                "window_end": "2026-08-11T12:00:00Z",
                "capacity": 40,
            },
            MANAGER,
        )
        data = validate_success(resp, 201)
        assert_meal_service(data)
        assert data["capacity"] == 40


class TestSupervisorGate:
    def test_supervisor_required_gate(self, api):
        """PRD 3.6: "when `requires_supervisor` is true there must exist a
        shift at the same site with `role_on_shift` `SUPERVISOR_ON_DUTY`
        currently `CHECKED_IN` whose half-open shift interval overlaps the
        service window, else `ERR_SUPERVISOR_REQUIRED`."

        Design: Corner/validations/supervisor_required_gate
        """
        from test_helpers.fixtures import create_volunteer, create_shift
        from test_helpers.test_users import make_volunteer_headers

        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="Sup Site", dine_in_capacity=50,
                           togo_capacity_per_window=20, delivery_radius_km=8)
        batch = create_accepted_batch(site["id"], item_description="soup",
                                      quantity_servings=20)
        menu_day = create_menu_day(site["id"], "2026-08-10")
        item = create_menu_item(menu_day["id"], name="Soup", planned_servings=10)
        allocate(item["id"], batch["id"], 10)
        confirm_item(item["id"])
        supervisor = create_volunteer(
            full_name="Sup One", certification_level="SUPERVISOR",
            certification_expires_at="2027-01-01T00:00:00Z",
        )
        lock_forecast(menu_day["id"])
        start_production(menu_day["id"])
        service = create_service(
            menu_day["id"], service_model="DINE_IN",
            window_start="2026-08-10T11:00:00Z",
            window_end="2026-08-10T13:00:00Z", capacity=10,
            requires_supervisor=True,
        )
        shift = create_shift(
            site["id"], supervisor["id"], menu_day["id"],
            role_on_shift="SUPERVISOR_ON_DUTY",
            starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T14:00:00Z",
        )
        set_clock("2026-08-10T10:30:00Z")

        # Supervisor shift exists but is not CHECKED_IN: open is rejected.
        version = get_menu_day(menu_day["id"])["version"]
        resp = api.open_service(
            service["id"], {"expected_menu_day_version": version}, MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_REQUIRED)

        # After the supervisor checks in, the same open succeeds.
        get_success_data(
            api.check_in_shift(shift["id"], make_volunteer_headers(supervisor["id"]))
        )
        version = get_menu_day(menu_day["id"])["version"]
        resp = api.open_service(
            service["id"], {"expected_menu_day_version": version}, MANAGER
        )
        data = validate_success(resp, 200)
        assert data["status"] == "OPEN"


class TestReferentialBeatsFiscal:
    """Queue A: priority_pair_validation_conflict / referential_vs_fiscal_on_order_create."""

    def test_unavailable_item_on_full_service_reports_reference_invalid(self, api):
        """PRD 2.6: "8. Referential integrity with state: cross-referenced
        resources exist and are in an admissible state, else
        `ERR_REFERENCE_INVALID` (HTTP 422). 9. Capacity and quota ceilings —
        service capacity, batch remainder, the rescue cap — are enforced last
        of all, else `ERR_CAPACITY_FULL` (HTTP 422)."
        PRD 3.5: "an item that is missing from that menu day, merely
        `PLANNED`, `UNAVAILABLE`, or `SOLD_OUT` is rejected with
        `ERR_REFERENCE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_order_create
        """
        set_clock("2026-08-10T08:00:00Z")
        site = create_site(name="P2 Kitchen", dine_in_capacity=50,
                           togo_capacity_per_window=20, delivery_radius_km=8)
        batch = create_accepted_batch(site["id"], item_description="pasta",
                                      quantity_servings=30)
        menu_day = create_menu_day(site["id"], "2026-08-10")
        item1 = create_menu_item(menu_day["id"], name="Pasta", planned_servings=10)
        allocate(item1["id"], batch["id"], 10)
        confirm_item(item1["id"])
        item2 = create_menu_item(menu_day["id"], name="Salad", planned_servings=10)
        allocate(item2["id"], batch["id"], 10)
        confirm_item(item2["id"])
        g1 = create_guest(full_name="G One", household_size=2)
        g2 = create_guest(full_name="G Two", household_size=2)
        lock_forecast(menu_day["id"])
        start_production(menu_day["id"])
        service = create_service(
            menu_day["id"], service_model="DINE_IN",
            window_start="2026-08-10T11:00:00Z",
            window_end="2026-08-10T13:00:00Z", capacity=1,
        )
        set_clock("2026-08-10T10:30:00Z")
        open_service(service["id"])
        # Fill the service's only slot with an order for item2.
        create_order(service["id"], g1["id"], item2["id"], quantity=1)
        # Pull item1 (no orders reference it).
        get_success_data(api.mark_item_unavailable(item1["id"], MANAGER))

        # g2's order targets an UNAVAILABLE item on a FULL service: the
        # referential failure (priority 8) must surface before capacity (9).
        resp = api.create_meal_order(
            {
                "meal_service_id": service["id"],
                "guest_id": g2["id"],
                "menu_item_id": item1["id"],
                "quantity": 1,
                "substitution_allowed": False,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_INVALID)

    def test_item_from_other_menu_day_on_full_service_reports_reference_invalid(self, api):
        """PRD 3.5: "The referenced item must belong to the service's menu day
        and be `CONFIRMED`; an item that is missing from that menu day, merely
        `PLANNED`, `UNAVAILABLE`, or `SOLD_OUT` is rejected with
        `ERR_REFERENCE_INVALID`."
        PRD 2.6: "9. Capacity and quota ceilings — service capacity, batch
        remainder, the rescue cap — are enforced last of all, else
        `ERR_CAPACITY_FULL` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_order_create
        """
        site, menu_day, item, service, guests = _open_dine_in_service(
            api, capacity=1, num_guests=2
        )
        # Fill the service.
        create_order(service["id"], guests[0]["id"], item["id"], quantity=1)

        # An item belonging to a DIFFERENT menu day (never confirmed there).
        other_day = create_menu_day(site["id"], "2026-08-12")
        foreign_item = create_menu_item(other_day["id"], name="Foreign",
                                        planned_servings=5)

        resp = api.create_meal_order(
            {
                "meal_service_id": service["id"],
                "guest_id": guests[1]["id"],
                "menu_item_id": foreign_item["id"],
                "quantity": 1,
                "substitution_allowed": False,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_INVALID)


class TestImmediateConsistency:
    def test_immediate_consistency_on_order_create(self, api):
        """PRD 2.9: "Consistency is immediate: there is no deferred or
        eventual recalculation of any derived tally."
        PRD 3.5: "A new reservation starts with `prep_status` `QUEUED` and
        `fulfillment_status` `RESERVED`, and its creation increments the
        service's `reserved_count` by one".

        Design: Corner/consistency_model/immediate_consistency_on_order_create
        """
        site, menu_day, item, service, guests = _open_dine_in_service(
            api, capacity=5, num_guests=1
        )
        create_order(service["id"], guests[0]["id"], item["id"], quantity=1)

        service = get_success_data(api.get_meal_service(service["id"], MANAGER))
        assert service["reserved_count"] == 1, (
            f"reserved_count must reflect the new order immediately, "
            f"got {service['reserved_count']}"
        )
