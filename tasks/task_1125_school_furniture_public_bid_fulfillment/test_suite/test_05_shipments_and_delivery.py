"""Summer-window shipments and delivery verification (PRD §2.8, §2.9, §3.5)."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, make_district_buyer_headers,
    validate_error, validate_success, add_accepted_po,
    build_accepted_award_context, create_shipment, deliver_shipment, get_po_line,
)

FC = TEST_USERS["fulfillment_coordinator_headers"]


def _delivered_ctx(api, ordered_qty=10):
    """Accepted award + accepted PO with one line fully delivered."""
    ctx = build_accepted_award_context()
    po, lines = add_accepted_po(ctx, line_qtys=(ordered_qty,))
    shipment = create_shipment(
        po["id"], ctx["site"]["id"],
        [{"po_line_id": lines[0]["id"], "qty": ordered_qty}],
        scheduled_date="2026-07-01")
    deliver_shipment(shipment["id"], [{
        "po_line_id": lines[0]["id"], "delivered_qty": ordered_qty,
        "manufacturer": "Acme", "model": "Desk-100",
    }])
    return ctx, po, lines, shipment


class TestDeliveryWindow:
    def test_delivery_window_bounds_inclusive(self, api):
        """PRD §3.5: "The scheduled date must lie within the bid specification's
        delivery window — on or after `delivery_window_start` and on or before
        `delivery_window_end` — or the request is rejected with
        `ERR_OUTSIDE_DELIVERY_WINDOW`."

        Design: Corner/validations/delivery_window_bounds_inclusive_start_exclusive_beyond_end
        """
        ctx = build_accepted_award_context(with_crew=False)
        po, lines = add_accepted_po(ctx, line_qtys=(15,))
        l1 = lines[0]["id"]

        at_start = validate_success(api.create_shipment(
            {"purchase_order_id": po["id"], "school_site_id": ctx["site"]["id"],
             "scheduled_date": "2026-06-15", "lines": [{"po_line_id": l1, "qty": 5}]}, FC), 201)
        assert at_start["status"] == "SCHEDULED"

        at_end = validate_success(api.create_shipment(
            {"purchase_order_id": po["id"], "school_site_id": ctx["site"]["id"],
             "scheduled_date": "2026-08-15", "lines": [{"po_line_id": l1, "qty": 5}]}, FC), 201)
        assert at_end["status"] == "SCHEDULED"

        past_end = api.create_shipment(
            {"purchase_order_id": po["id"], "school_site_id": ctx["site"]["id"],
             "scheduled_date": "2026-08-16", "lines": [{"po_line_id": l1, "qty": 5}]}, FC)
        validate_error(past_end, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW)


class TestNoSubstitution:
    def test_substitution_at_delivery_rejected(self, api):
        """PRD §2.9: "a spec line pins an exact `manufacturer` and `model`, and
        delivered goods must match them exactly — a delivery entry naming a
        different manufacturer or model is rejected outright with
        `ERR_SUBSTITUTION_NOT_ALLOWED`."

        Design: Corner/validations/substitution_at_delivery_rejected
        """
        ctx = build_accepted_award_context(with_crew=False)
        po, lines = add_accepted_po(ctx, line_qtys=(10,))
        shipment = create_shipment(
            po["id"], ctx["site"]["id"],
            [{"po_line_id": lines[0]["id"], "qty": 10}], scheduled_date="2026-07-01")

        resp = api.mark_delivered(shipment["id"], {"lines": [{
            "po_line_id": lines[0]["id"], "delivered_qty": 10,
            "manufacturer": "AcmeClone", "model": "Desk-100",
        }]}, FC)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_ALLOWED)

        line = get_po_line(lines[0]["id"])
        assert line["delivered_qty"] == 0
        assert line["status"] == "ORDERED"


class TestDeliveryQuantity:
    def test_delivery_over_ordered_returns_delivery_exceeds_ordered(self, api):
        """PRD §3.5: "an entry's `delivered_qty` may not exceed the line's
        remaining undelivered quantity — its `ordered_qty` minus its already
        accumulated `delivered_qty` — on pain of `ERR_DELIVERY_EXCEEDS_ORDERED`."

        Design: Corner/errors/delivery_over_ordered_returns_delivery_exceeds_ordered
        """
        ctx = build_accepted_award_context(with_crew=False)
        po, lines = add_accepted_po(ctx, line_qtys=(10,))
        shipment = create_shipment(
            po["id"], ctx["site"]["id"],
            [{"po_line_id": lines[0]["id"], "qty": 10}], scheduled_date="2026-07-01")

        resp = api.mark_delivered(shipment["id"], {"lines": [{
            "po_line_id": lines[0]["id"], "delivered_qty": 11,
            "manufacturer": "Acme", "model": "Desk-100",
        }]}, FC)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_EXCEEDS_ORDERED)

    def test_shipment_mark_delivered_twice_returns_invalid_state(self, api):
        """PRD §3.5: "Recording delivery is the coordinator's next act, valid only
        while the shipment is `SCHEDULED`."
        PRD §2.8: "the target resource's current status permits the requested
        transition (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/shipment_mark_delivered_twice_returns_invalid_state
        """
        ctx, po, lines, shipment = _delivered_ctx(api, ordered_qty=10)

        resp = api.mark_delivered(shipment["id"], {"lines": [{
            "po_line_id": lines[0]["id"], "delivered_qty": 10,
            "manufacturer": "Acme", "model": "Desk-100",
        }]}, FC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_po_line(lines[0]["id"])["delivered_qty"] == 10


class TestShipmentExistence:
    def test_get_shipment_not_found_returns_404(self, api):
        """PRD §2.8: "path identifiers are resolved left to right, and a missing id
        is rejected with `ERR_NOT_FOUND` (HTTP 404) before any later id is examined"

        Design: Corner/entities/get_shipment_not_found_returns_404
        """
        resp = api.get_shipment(NON_EXISTENT_UUID, FC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
