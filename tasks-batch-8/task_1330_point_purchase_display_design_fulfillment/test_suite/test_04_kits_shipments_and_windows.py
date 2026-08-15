"""Kitting, shipments, ship-window boundaries, and the delivery grace period."""
import pytest

from test_helpers import (
    APPOINTMENT_AFTER_WINDOW,
    APPOINTMENT_BEFORE_WINDOW,
    APPOINTMENT_ONE_SECOND_AFTER_WINDOW_END,
    LOGISTICS_COORDINATOR,
    PROGRAM_MANAGER,
    SHIP_WINDOW_END,
    SHIP_WINDOW_START,
    TIME_BEFORE_WINDOW,
    TIME_GRACE_END_EXACT,
    TIME_ONE_SECOND_AFTER_GRACE,
    WAREHOUSE_OPERATOR,
    ApiErrorId,
    api_client,
    assert_kit,
    assert_shipment,
    authorize_run,
    create_manual_kit,
    create_production_run_entity,
    create_store,
    deliver_shipment,
    get_kit,
    get_shipment,
    mark_kitted,
    set_appointment,
    set_clock,
    setup_kitted_kit,
    setup_produced_run,
    setup_program_in_production,
    setup_shipment_appointment_set,
    setup_shipment_scheduled,
    setup_shipped,
    start_fulfillment,
    validate_error,
    validate_success,
)


class TestKittingRequiresProducedRun:

    def test_mark_kitted_rejected_when_run_only_authorized(self):
        """PRD §3.4: "The warehouse's kitting step — moving a kit from `PENDING`
        to `KITTED` — requires the kit's parent run to be in `PRODUCED` status;
        kitting against a run in any other state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/kit_mark_kitted_requires_run_produced
        """
        _client, program, design = setup_program_in_production(store_count=3)
        store = create_store(program["id"], store_number="S1")
        run = create_production_run_entity(program, design["id"], overage_pct=0)
        run = authorize_run(run["id"])
        assert run["status"] == "AUTHORIZED"
        kit = create_manual_kit(run["id"], store["id"])

        resp = api_client.mark_kitted(kit["id"], WAREHOUSE_OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        kit_after = get_kit(kit["id"])
        assert kit_after["status"] == "PENDING", \
            f"kit must remain PENDING, got {kit_after['status']}"

    def test_mark_kitted_rejected_when_run_only_planned(self):
        """PRD §3.4: "kitting against a run in any other state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/kit_mark_kitted_requires_run_produced
        """
        _client, program, design = setup_program_in_production(store_count=3)
        store = create_store(program["id"], store_number="S1")
        run = create_production_run_entity(program, design["id"], overage_pct=0)
        assert run["status"] == "PLANNED"
        kit = create_manual_kit(run["id"], store["id"])

        resp = api_client.mark_kitted(kit["id"], WAREHOUSE_OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_kit(kit["id"])["status"] == "PENDING"


class TestShipCascade:

    def test_ship_cascades_kit_to_shipped(self):
        """PRD §2.8: "Shipping a shipment pushes its parent kit from `KITTED` to
        `SHIPPED`; delivering a shipment pushes the kit from `SHIPPED` to
        `DELIVERED`."
        PRD §3.4: "Shipping stamps `shipped_at` and cascades the parent kit from
        `KITTED` to `SHIPPED`."

        Design: Difficulty/transitive_cascade/ship_cascades_kit_then_kit_gates_close
        """
        ctx = setup_shipped(store_count=3, num_stores=1)
        shipment = ctx["shipment"]
        assert_shipment(shipment)
        assert shipment["status"] == "SHIPPED"
        assert shipment.get("shipped_at") is not None
        kit = get_kit(ctx["kit"]["id"])
        assert kit["status"] == "SHIPPED", \
            f"parent kit must cascade to SHIPPED, got {kit['status']}"

    def test_close_rejected_until_every_kit_terminal_then_succeeds(self):
        """PRD §3.1: "Closing a program is permitted only from `FULFILLMENT`,
        and only when every kit of the program has reached a terminal state —
        each kit must be `DELIVERED` or `DAMAGED`."
        PRD §3.4: "Confirming receipt moves the shipment from `SHIPPED` to
        `DELIVERED`, stamps `delivered_at`, and cascades the kit from `SHIPPED`
        to `DELIVERED`".

        Design: Difficulty/transitive_cascade/ship_cascades_kit_then_kit_gates_close
        """
        ctx = setup_shipped(store_count=3, num_stores=1)
        program = start_fulfillment(ctx["program"]["id"])
        assert program["status"] == "FULFILLMENT"

        # The kit is SHIPPED — not terminal — so the close must be rejected.
        resp = api_client.close_program(program["id"], PROGRAM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # Deliver the shipment: the kit cascades to the terminal DELIVERED state
        # and the close then succeeds.
        shipment = deliver_shipment(ctx["shipment"]["id"])
        assert shipment["status"] == "DELIVERED"
        assert get_kit(ctx["kit"]["id"])["status"] == "DELIVERED"
        closed = validate_success(
            api_client.close_program(program["id"], PROGRAM_MANAGER), 200)
        assert closed["status"] == "CLOSED"


class TestShipmentBranching:

    def test_shipped_shipment_can_fail_with_no_delivery_side_effects(self):
        """PRD §3.4: "A shipment that will never make it can instead be moved
        from `SHIPPED` to the terminal `FAILED` state."
        PRD §2.8: "Kit logistics states are never set directly — they move only
        as a cascade of shipment events (and of damage approval, below)."

        Design: Difficulty/non_linear_state_machine/shipment_branching_deliver_or_fail
        """
        ctx = setup_shipped(store_count=3, num_stores=1)
        resp = api_client.fail_shipment(ctx["shipment"]["id"],
                                        LOGISTICS_COORDINATOR)
        shipment = validate_success(resp, 200)
        assert_shipment(shipment)
        assert shipment["status"] == "FAILED"
        assert shipment.get("delivered_at") is None, \
            "a FAILED shipment never confirms receipt, so delivered_at stays unset"
        kit = get_kit(ctx["kit"]["id"])
        assert kit["status"] == "SHIPPED", \
            f"failing a shipment does not cascade; kit stays SHIPPED, got {kit['status']}"

    def test_shipped_shipment_delivers_and_cascades_kit(self):
        """PRD §3.4: "Confirming receipt moves the shipment from `SHIPPED` to
        `DELIVERED`, stamps `delivered_at`, and cascades the kit from `SHIPPED`
        to `DELIVERED`".

        Design: Difficulty/non_linear_state_machine/shipment_branching_deliver_or_fail
        """
        ctx = setup_shipped(store_count=3, num_stores=1)
        shipment = deliver_shipment(ctx["shipment"]["id"])
        assert shipment["status"] == "DELIVERED"
        assert shipment.get("delivered_at") is not None
        kit = get_kit(ctx["kit"]["id"])
        assert kit["status"] == "DELIVERED"


class TestAppointmentWindowBoundaries:

    def test_appointment_at_exact_window_end_accepted(self):
        """PRD §3.4: "moving a shipment from `SCHEDULED` to `APPOINTMENT_SET`
        records an `appointment_at` that must fall within the ship window,
        inclusive of both bounds — an appointment before `ship_window_start` or
        after `ship_window_end` is rejected with `ERR_WINDOW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/ship_window_appointment_at_exact_end
        """
        ctx = setup_shipment_scheduled(store_count=3, num_stores=1)
        resp = api_client.set_appointment(
            ctx["shipment"]["id"], {"appointment_at": SHIP_WINDOW_END},
            LOGISTICS_COORDINATOR)
        shipment = validate_success(resp, 200)
        assert shipment["status"] == "APPOINTMENT_SET", \
            "appointment exactly at ship_window_end is inside the inclusive bounds"

    def test_appointment_one_second_after_window_end_rejected(self):
        """PRD §3.4: "an appointment before `ship_window_start` or after
        `ship_window_end` is rejected with `ERR_WINDOW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/ship_window_appointment_at_exact_end
        """
        ctx = setup_shipment_scheduled(store_count=3, num_stores=1)
        resp = api_client.set_appointment(
            ctx["shipment"]["id"],
            {"appointment_at": APPOINTMENT_ONE_SECOND_AFTER_WINDOW_END},
            LOGISTICS_COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)
        shipment = get_shipment(ctx["shipment"]["id"])
        assert shipment["status"] == "SCHEDULED"

    def test_appointment_before_window_start_rejected(self):
        """PRD §3.4: "an appointment before `ship_window_start` or after
        `ship_window_end` is rejected with `ERR_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/appointment_outside_window_rejected
        """
        ctx = setup_shipment_scheduled(store_count=3, num_stores=1)
        resp = api_client.set_appointment(
            ctx["shipment"]["id"], {"appointment_at": APPOINTMENT_BEFORE_WINDOW},
            LOGISTICS_COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)
        shipment = get_shipment(ctx["shipment"]["id"])
        assert shipment["status"] == "SCHEDULED", \
            f"rejected appointment must leave the shipment SCHEDULED, got {shipment['status']}"

    def test_appointment_well_after_window_end_rejected(self):
        """PRD §3.4: "moving a shipment from `SCHEDULED` to `APPOINTMENT_SET`
        records an `appointment_at` that must fall within the ship window,
        inclusive of both bounds".

        Design: Difficulty/resource_temporal_overlap/appointment_outside_window_rejected
        """
        ctx = setup_shipment_scheduled(store_count=3, num_stores=1)
        resp = api_client.set_appointment(
            ctx["shipment"]["id"], {"appointment_at": APPOINTMENT_AFTER_WINDOW},
            LOGISTICS_COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)
        assert get_shipment(ctx["shipment"]["id"])["status"] == "SCHEDULED"

    def test_appointment_at_exact_window_start_accepted(self):
        """PRD §3.4: "records an `appointment_at` that must fall within the ship
        window, inclusive of both bounds".

        Design: Corner/calculations/ship_window_appointment_boundary_inclusive
        """
        ctx = setup_shipment_scheduled(store_count=3, num_stores=1)
        shipment = set_appointment(ctx["shipment"]["id"],
                                   appointment_at=SHIP_WINDOW_START)
        assert shipment["status"] == "APPOINTMENT_SET", \
            "appointment exactly at ship_window_start is inside the inclusive bounds"


class TestShipAndDeliveryTimeGates:

    def test_ship_rejected_before_window_opens(self):
        """PRD §3.4: "Releasing the truck moves the shipment from
        `APPOINTMENT_SET` to `SHIPPED` and carries two further preconditions:
        the parent kit must be `KITTED` (else `ERR_INVALID_STATE`), and the
        current logical time must be at or after `ship_window_start` — shipping
        before the window opens is rejected with `ERR_WINDOW_VIOLATION`."

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_clock_gates_ship
        """
        ctx = setup_shipment_appointment_set(store_count=3, num_stores=1)
        set_clock(TIME_BEFORE_WINDOW)
        resp = api_client.ship_shipment(ctx["shipment"]["id"],
                                        LOGISTICS_COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)
        shipment = get_shipment(ctx["shipment"]["id"])
        assert shipment["status"] == "APPOINTMENT_SET", \
            f"rejected ship must leave the shipment APPOINTMENT_SET, got {shipment['status']}"

    def test_deliver_at_exact_grace_deadline_accepted(self):
        """PRD §3.4: "delivery is accepted while the current logical time is no
        later than seven days after `ship_window_end` — this seven-day grace is
        the retailer's allowance for late dock arrivals".

        Design: Difficulty/resource_temporal_overlap/deliver_after_grace_period_rejected
        """
        ctx = setup_shipped(store_count=3, num_stores=1)
        # ship_window_end + 7 days exactly: "no later than" is inclusive.
        set_clock(TIME_GRACE_END_EXACT)
        resp = api_client.deliver_shipment(ctx["shipment"]["id"],
                                           LOGISTICS_COORDINATOR)
        shipment = validate_success(resp, 200)
        assert shipment["status"] == "DELIVERED"
        assert get_kit(ctx["kit"]["id"])["status"] == "DELIVERED"

    def test_deliver_one_second_past_grace_rejected(self):
        """PRD §3.4: "a delivery attempted after the window end plus that grace
        is rejected with `ERR_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/deliver_after_grace_period_rejected
        """
        ctx = setup_shipped(store_count=3, num_stores=1)
        set_clock(TIME_ONE_SECOND_AFTER_GRACE)
        resp = api_client.deliver_shipment(ctx["shipment"]["id"],
                                           LOGISTICS_COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_WINDOW_VIOLATION)
        shipment = get_shipment(ctx["shipment"]["id"])
        assert shipment["status"] == "SHIPPED", \
            f"rejected delivery must leave the shipment SHIPPED, got {shipment['status']}"
