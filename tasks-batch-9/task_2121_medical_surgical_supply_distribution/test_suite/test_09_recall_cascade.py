"""Recall notices and the four-hop quarantine cascade."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_recall_notice,
    cascade_recall_notice,
    create_item,
    create_lot,
    create_recall_notice,
    make_distribution_operator_headers,
    read_lot,
    read_order,
    read_order_line,
    read_recall_notice,
    read_route,
    read_supply_room,
    recall_cascade_payload,
    setup_glove_order,
    validate_error,
    DISTRIBUTION_OPERATOR_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def test_closing_a_notice_before_it_cascades_is_refused(api):
    """PRD §3.8: "`CASCADE` is permitted only from `ISSUED` and drives `ISSUED →
    CASCADED`; `CLOSE` is permitted only from `CASCADED` and drives `CASCADED →
    CLOSED`, touching no lot and no line. Either action requested from the wrong
    state is `ERR_RECALL_STATE_INVALID` (HTTP 409)."
    PRD §3.8: "A new notice is `ISSUED`, with `quarantined_lot_count` and
    `backordered_line_count` at zero and `cascaded_at` null — issuing a notice
    quarantines nothing, and this separation is deliberate, so that the
    notification can be reviewed before it moves stock."

    Design: Corner/state_machines/recall_close_before_cascade_is_rejected
    """
    item = create_item(
        sku="SKU-SM7-CS", description="Recall state probe",
        manufacturer_code="MFR-ACME", uom="CS", wac_cents=2000,
        handling_class="AMBIENT", units_per_parent=10,
    )
    lot = create_lot(
        item["id"], lot_code="LOT-SM7", expiry_date="2027-12-31T00:00:00Z",
        received_quantity=50,
    )
    notice = create_recall_notice(
        item["id"], lot_id=lot["id"], recall_class="CLASS_III",
        reason="Labelling defect",
    )
    assert_recall_notice(notice)

    response = api.cascade_recall_notice(
        notice["id"],
        recall_cascade_payload("CLOSE"),
        make_distribution_operator_headers(DISTRIBUTION_OPERATOR_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_RECALL_STATE_INVALID.value, 409)

    after = read_recall_notice(notice["id"])
    assert after["status"] == "ISSUED"
    assert after["quarantined_lot_count"] == 0
    assert after.get("cascaded_at") is None
    assert read_lot(lot["id"])["status"] == "AVAILABLE"


class TestFourHopRecallCascade:
    """One CASCADE request drives lot, line, order and route in that order."""

    @staticmethod
    def _routed_order_under_recall():
        world = setup_glove_order(
            stage="routed",
            room_overrides={
                "facility_code": "FAC-008", "room_code": "OR-CORE-8",
            },
            lot_overrides={"lot_code": "LOT-R1", "received_quantity": 100},
            route_overrides={"route_code": "RT-8", "service_date": "2026-08-05",
                             "vehicle_class": "AMBIENT_VAN"},
        )
        world["notice"] = create_recall_notice(
            world["item"]["id"], lot_id=world["lot"]["id"], recall_class="CLASS_I",
            reason="Sterile barrier breach detected in lot",
        )
        return world

    def test_cascade_quarantines_the_lot_and_backorders_its_allocated_line(self, api):
        """PRD §3.8: "**Hop one — lots.** Every lot holding the recalled item,
        matching the notice's `lot_id` when one was given, whose `status` is
        `AVAILABLE` or `EXCURSION_HOLD`, is moved to `QUARANTINED`, processing
        lots in ascending `created_at` order. A lot that was on excursion hold
        also has its `excursion_flagged_by_user_id` cleared. The number of lots
        moved is written to `quarantined_lot_count`."
        PRD §3.8: "**Hop two — order lines.** Because a lot became quarantined,
        every order line drawn from that lot whose `line_status` is `ALLOCATED`
        is moved `ALLOCATED → BACKORDERED`, processing lines in ascending
        `created_at` order."

        Design: Difficulty/transitive_cascade/recall_cascade_lot_to_line_to_order_to_route_four_hops
        """
        world = self._routed_order_under_recall()
        cascaded = cascade_recall_notice(world["notice"]["id"])

        lot = read_lot(world["lot"]["id"])
        line = read_order_line(world["order_line"]["id"])

        assert lot["status"] == "QUARANTINED"
        assert cascaded["quarantined_lot_count"] == 1
        assert line["line_status"] == "BACKORDERED"
        assert line["allocated_qty"] == 0
        assert line.get("lot_id") is None
        assert cascaded["backordered_line_count"] == 1
        assert lot["quantity_on_hand"] == 100

    def test_cascade_holds_the_order_and_releases_the_room_commitment(self, api):
        """PRD §3.8: "**Hop three — orders.** Because a line became backordered,
        its parent order recomputes `order_total_cents`, and the destination
        room's `open_commitment_cents` is adjusted by the change in that total.
        If every line of that order is now `BACKORDERED`, `SHORTED` or
        `CANCELLED` and the order's `fulfillment_status` is `ALLOCATED`, the
        order moves `ALLOCATED → HELD`."
        PRD §2.10: "`SupplyRoom.open_commitment_cents` is the sum of
        `order_total_cents` over that room's orders whose `fulfillment_status` is
        `SUBMITTED`, `ALLOCATED`, `IN_TRANSIT` or `HELD`; it is charged at
        submission, adjusted by the delta whenever a submitted order's total is
        recomputed, and released at delivery."

        Design: Difficulty/transitive_cascade/recall_cascade_lot_to_line_to_order_to_route_four_hops
        """
        world = self._routed_order_under_recall()
        assert read_supply_room(world["room"]["id"])["open_commitment_cents"] == 98024

        cascade_recall_notice(world["notice"]["id"])

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "HELD"
        assert order["order_total_cents"] == 0
        assert read_supply_room(world["room"]["id"])["open_commitment_cents"] == 0

    def test_cascade_detaches_the_order_and_cancels_the_emptied_route(self, api):
        """PRD §3.8: "**Hop four — routes.** Because an order moved to held, if it
        was carrying a `route_id` the order is detached from its route:
        `route_id`, `stop_arrival_min`, `stop_service_minutes` and
        `service_date` are all cleared, and the route recomputes
        `planned_order_count` and `cold_units_loaded`. If that recomputation
        leaves a `PLANNED` route with no assigned orders at all, the route moves
        `PLANNED → CANCELLED` and its `cold_units_loaded` is set to zero."
        PRD §3.8: "When the four hops have run, `cascaded_at` is stamped with the
        logical clock."

        Design: Difficulty/transitive_cascade/recall_cascade_lot_to_line_to_order_to_route_four_hops
        """
        world = self._routed_order_under_recall()
        cascaded = cascade_recall_notice(world["notice"]["id"])

        order = read_order(world["order"]["id"])
        assert order.get("route_id") is None
        assert order.get("stop_arrival_min") is None
        assert order.get("stop_service_minutes") is None
        assert order.get("service_date") is None

        route = read_route(world["route"]["id"])
        assert route["status"] == "CANCELLED"
        assert route["planned_order_count"] == 0
        assert route["cold_units_loaded"] == 0

        assert cascaded["status"] == "CASCADED"
        assert_instant_equals(
            cascaded["cascaded_at"], "2026-08-01T00:00:00", "cascaded_at"
        )
