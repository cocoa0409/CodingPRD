"""Material order placement quantity and clock-gated delivery."""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    bootstrap_actors, create_baselined_project,
)
from test_helpers.factories import create_material_order_payload


class TestMaterialOrderQty:
    def test_ordered_sqft_ceil_and_project_advances_to_ordered(self, api):
        """PRD §3.5: "At placement the system computes `ordered_sqft`: the net sidable
        area of the measurement linked to the baseline estimate, multiplied by one
        plus the estimate's `waste_factor_pct`, then rounded up to a whole square
        foot."
        PRD §3.5: "The placement side effects are to create the order and set the
        project's `workflow_status` to `ORDERED`."

        Design: Corner/calculations/material_order_qty_ceil_to_whole_sqft
        """
        # gross 2000, opening 200 -> net 1800; ceil(1800 * 1.10) = 1980.
        proj, est, line_map, actors = create_baselined_project(
            line_items=[{"scope_kind": "SIDING", "quantity": 1800, "unit_price_cents": 500}],
            measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        # Placing a material order creates a new resource -> 201 (PRD §4).
        mo = get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        assert mo["ordered_sqft"] == 1980, \
            f"ordered_sqft expected ceil(1800*1.10)=1980, got {mo['ordered_sqft']}"
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["workflow_status"] == "ORDERED", \
            f"project should advance to ORDERED, got {refetched['workflow_status']}"


class TestDeliveryClockGate:
    def test_deliver_exactly_at_eta_succeeds(self, api):
        """PRD §3.5: "Delivery — recordable from either `CONFIRMED` or `BACKORDERED` —
        sets the `status` to `DELIVERED`, but only when the server's current logical
        clock has reached or passed the promised `delivery_eta_iso`; recording
        delivery before that instant is rejected with `ERR_DELIVERY_TOO_EARLY` (HTTP
        409)."

        Design: Difficulty/boundary_precision_check/boundary_delivery_exactly_at_eta_succeeds
        """
        proj, est, line_map, actors = create_baselined_project()
        mo = get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(
            mo["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        # Set the clock to exactly the ETA — boundary is inclusive ("reached or passed").
        get_success_data(_ac.set_clock("2026-04-10T00:00:00Z", actors["pm_h"]))
        delivered = validate_success(_ac.deliver_material_order(mo["id"], actors["pm_h"]))
        assert delivered["status"] == "DELIVERED", \
            f"delivery at exact ETA must succeed, got {delivered['status']}"

    def test_deliver_one_second_before_eta_rejected_then_at_eta_succeeds(self, api):
        """PRD §3.5: "Delivery — recordable from either `CONFIRMED` or `BACKORDERED` —
        sets the `status` to `DELIVERED`, but only when the server's current logical
        clock has reached or passed the promised `delivery_eta_iso`; recording
        delivery before that instant is rejected with `ERR_DELIVERY_TOO_EARLY` (HTTP
        409)."

        Boundary precision around the ETA: one second before is rejected, exactly at
        the ETA succeeds.

        Design: Difficulty/boundary_precision_check/boundary_delivery_exactly_at_eta_succeeds
        """
        proj, est, line_map, actors = create_baselined_project()
        mo = get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(
            mo["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        # One second before the ETA -> too early.
        get_success_data(_ac.set_clock("2026-04-09T23:59:59Z", actors["pm_h"]))
        resp_early = _ac.deliver_material_order(mo["id"], actors["pm_h"])
        validate_error(resp_early, ApiErrorId.ERR_DELIVERY_TOO_EARLY.value)
        # Exactly at the ETA -> succeeds (inclusive boundary).
        get_success_data(_ac.set_clock("2026-04-10T00:00:00Z", actors["pm_h"]))
        delivered = validate_success(_ac.deliver_material_order(mo["id"], actors["pm_h"]))
        assert delivered["status"] == "DELIVERED"

    def test_deliver_before_eta_returns_delivery_too_early(self, api):
        """PRD §3.5: "Delivery — recordable from either `CONFIRMED` or `BACKORDERED` —
        sets the `status` to `DELIVERED`, but only when the server's current logical
        clock has reached or passed the promised `delivery_eta_iso`; recording
        delivery before that instant is rejected with `ERR_DELIVERY_TOO_EARLY` (HTTP
        409)."
        PRD §3.12: "The server's startup default clock reads exactly
        2026-04-01T00:00:00Z; before any clock is set it holds that default and never
        falls back to real wall-clock time."

        Design: Corner/errors/deliver_before_eta_returns_delivery_too_early
        """
        proj, est, line_map, actors = create_baselined_project()
        mo = get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(
            mo["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        # Clock left at the default 2026-04-01, which is before the ETA.
        resp = _ac.deliver_material_order(mo["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_DELIVERY_TOO_EARLY.value)
