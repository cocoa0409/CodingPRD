"""Shipment creation gate, stepwise advance machine, and the delivery cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_part_item,
    create_shipment_payload,
    setup_delivered_order,
    setup_qualified_order,
    setup_qualified_with_pa,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShipmentGate:
    def test_shipment_blocked_while_pa_only_submitted(self, api, warehouse_operator_headers,
                                                      care_coordinator_headers):
        """PRD §3.4: "If it is true, an `APPROVED` prior authorization must exist whose
        `approved_until` has not passed; absent an approved PA the shipment is rejected
        with `ERR_PRIOR_AUTH_REQUIRED`".

        Design: Difficulty/cross_entity_state_dependency/shipment_blocked_until_prior_auth_approved
        """
        ctx = setup_qualified_with_pa()
        res = api.create_shipment(
            create_shipment_payload(pump_order_id=ctx["order"]["id"], tracking_number="1Z-G"),
            warehouse_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRIOR_AUTH_REQUIRED, expected_status=409)

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "QUALIFIED"

    def test_blocked_shipment_leaves_pa_untouched_and_creates_nothing(
        self, api, warehouse_operator_headers, care_coordinator_headers
    ):
        """PRD §3.4: "absent an approved PA the shipment is rejected with
        `ERR_PRIOR_AUTH_REQUIRED`" — the gate rejects the request, so the order still has
        no shipments.

        Design: Difficulty/cross_entity_state_dependency/shipment_blocked_until_prior_auth_approved
        """
        ctx = setup_qualified_with_pa()
        api.create_shipment(
            create_shipment_payload(pump_order_id=ctx["order"]["id"], tracking_number="1Z-G"),
            warehouse_operator_headers,
        )
        pa = validate_success(
            api.get_prior_authorization(ctx["pa"]["id"], care_coordinator_headers), 200
        )
        assert pa["status"] == "SUBMITTED"

        data, meta = validate_paginated(
            api.list_shipments(warehouse_operator_headers,
                               params={"pump_order_id": ctx["order"]["id"]})
        )
        assert meta["total_count"] == 0
        assert data == []


class TestShipmentStateMachine:
    def test_skip_transition_label_created_to_delivered_rejected(
        self, api, warehouse_operator_headers, care_coordinator_headers
    ):
        """PRD §3.4: "The warehouse then advances carrier status stepwise:
        `LABEL_CREATED → IN_TRANSIT`, `IN_TRANSIT → OUT_FOR_DELIVERY`, and
        `OUT_FOR_DELIVERY → DELIVERED`, each by declaring the target `to_status`."

        Design: Corner/state_machines/shipment_skip_transition_rejected
        """
        ctx = setup_qualified_order()
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(pump_order_id=ctx["order"]["id"],
                                        tracking_number="1Z-K1"),
                warehouse_operator_headers,
            ), 201
        )
        res = api.advance_shipment(shipment["id"], {"to_status": "DELIVERED"},
                                   warehouse_operator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        shipment_after = validate_success(
            api.get_shipment(shipment["id"], warehouse_operator_headers), 200
        )
        assert shipment_after["status"] == "LABEL_CREATED"
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "SHIPPED"

    def test_delivered_shipment_is_terminal(self, api, warehouse_operator_headers):
        """PRD §3.4: "Off the happy path, a shipment in `LABEL_CREATED` or `IN_TRANSIT`
        may be marked `LOST`, and one `OUT_FOR_DELIVERY` may be marked `RETURNED`;
        `DELIVERED`, `RETURNED`, and `LOST` are terminal."

        Design: Corner/state_machines/delivered_shipment_terminal_lockdown
        """
        ctx = setup_delivered_order()
        res = api.advance_shipment(ctx["shipment"]["id"], {"to_status": "LOST"},
                                   warehouse_operator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        shipment = validate_success(
            api.get_shipment(ctx["shipment"]["id"], warehouse_operator_headers), 200
        )
        assert shipment["status"] == "DELIVERED"


class TestShipmentRequestShape:
    def test_shipment_without_any_order_fk_rejected(self, api, warehouse_operator_headers):
        """PRD §2.9: "A `Shipment` references either a pump order via `pump_order_id` or a
        resupply order via `resupply_order_id` — exactly one of the two must be set, never
        both, never neither; a violation is a request-shape error (`ERR_VALIDATION`)."

        Design: Corner/endpoints/shipment_without_order_fk_returns_invalid_request
        """
        res = api.create_shipment({"carrier": "UPS", "tracking_number": "1Z-NONE"},
                                  warehouse_operator_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestDeliveryCascade:
    def test_delivery_stamps_order_and_creates_schedules(self, api, care_coordinator_headers):
        """PRD §3.4: "A **first, non-replacement pump shipment** whose order is `SHIPPED`
        moves that order `SHIPPED → DELIVERED` and stamps the order's `delivery_date` with
        the current logical date. Then, for every catalog part with
        `covered_under_resupply` true, the server creates a `ResupplySchedule`: `member_id`
        and `pump_order_id` taken from the delivered order, `catalog_item_id` naming the
        part, `frequency_days` and `schedule_mode` snapshotted from the policy at that
        moment, `anchor_date` set to the order's `delivery_date`, `last_fulfilled_date`
        null, `next_eligible_date` computed per the cadence rule of §3.5, and `status`
        `ACTIVE`."

        Design: Difficulty/transitive_cascade/delivery_cascade_order_to_schedules_to_member
        """
        ctx = setup_delivered_order(
            policy_overrides={"resupply_frequency_days": 90, "schedule_mode": "ROLLING"},
            part_items=[{"sku": "PART-VALVE", "name": "Valve", "unit_price_cents": 500},
                        {"sku": "PART-TUBE", "name": "Tube", "unit_price_cents": 800,
                         "max_qty_per_frequency": 2}],
        )
        order = ctx["order"]
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["delivery_date"] == "2026-05-01"

        data, meta = validate_paginated(
            api.list_resupply_schedules(care_coordinator_headers,
                                        params={"member_id": ctx["member"]["id"]})
        )
        assert meta["total_count"] == 2
        assert all(s["status"] == "ACTIVE" for s in data)
        valve = next(s for s in data if s["catalog_item_id"] == ctx["parts"][0]["id"])
        assert valve["anchor_date"] == "2026-05-01"
        # 2026-05-01 + 90 days = 2026-07-30 (PRD §3.5: "with no fulfillment yet, the first
        # eligibility falls exactly `frequency_days` after `anchor_date`").
        assert valve["next_eligible_date"] == "2026-07-30"

    def test_delivery_recomputes_member_aggregates(self, api, care_coordinator_headers):
        """PRD §3.4: "Finally the member's `active_schedule_count` and `next_resupply_date`
        are recomputed over her now-`ACTIVE` schedules."
        PRD §2.10: "`next_resupply_date` (the earliest `next_eligible_date` among those
        schedules, or null when none are `ACTIVE`)".

        Design: Difficulty/transitive_cascade/delivery_cascade_order_to_schedules_to_member
        """
        ctx = setup_delivered_order(
            policy_overrides={"resupply_frequency_days": 90, "schedule_mode": "ROLLING"},
            part_items=[{"sku": "PART-VALVE", "name": "Valve", "unit_price_cents": 500},
                        {"sku": "PART-TUBE", "name": "Tube", "unit_price_cents": 800,
                         "max_qty_per_frequency": 2}],
        )
        member = validate_success(
            api.get_member(ctx["member"]["id"], care_coordinator_headers), 200
        )
        assert member["active_schedule_count"] == 2
        assert member["next_resupply_date"] == "2026-07-30"


class TestOrderCancelGate:
    def test_cancel_from_shipped_rejected(self, api, care_coordinator_headers,
                                          warehouse_operator_headers):
        """PRD §3.8: "A patient or coordinator may cancel a pump order while it is
        `PENDING_QUALIFICATION` or `QUALIFIED`; anything further along is locked
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/cancel_from_shipped_rejected
        """
        ctx = setup_qualified_order()
        validate_success(
            api.create_shipment(
                create_shipment_payload(pump_order_id=ctx["order"]["id"],
                                        tracking_number="1Z-C1"),
                warehouse_operator_headers,
            ), 201
        )
        res = api.cancel_pump_order(ctx["order"]["id"], care_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "SHIPPED"
