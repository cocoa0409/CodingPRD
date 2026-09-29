"""Shipment creation, the manifest, and the five-hop cancellation cascade.

PRD §3.8 loads only units in status exactly `COMPLETE`, and cancelling a shipment
unwinds the load, the plan's production dimension, the booking and the crew.
"""

import pytest

from test_helpers import *  # noqa: F401,F403


class TestShipmentManifest:
    """PRD §3.8 — the manifest is assembled from COMPLETE units only."""

    def test_01_manifest_counts_only_complete_units(self, api):
        """One finished case ships while its half-built peer stays behind.

        PRD §3.8: "Units that are `QUEUED`, anywhere in fabrication, `HELD`,
        already `SHIPPED` or `SCRAPPED` are excluded, so a plan with no completed
        units yields the empty set and trips the rank-27 rejection."

        Design: Corner/calculations/shipment_manifest_counts_only_complete_units
        """
        ctx = setup_plan_with_completed_units(
            line_overrides={"quantity": 2}, complete_units=1
        )
        in_progress = ctx["work_orders"][1]
        for _ in range(2):
            in_progress = validate_success(
                api.advance_work_order(
                    in_progress["id"], TEST_USERS["plant_supervisor_headers"]
                )
            )
        assert in_progress["status"] == "FOAM_INJECTION"

        shipment = validate_success(
            create_shipment_for_plan(ctx), expected_status=201
        )
        assert_shipment(shipment)
        assert shipment["status"] == "STAGED"
        assert shipment["unit_count"] == 1
        assert shipment["linear_feet"] == 8
        assert shipment.get("handoff_at") is None

        plan = refresh_store_plan(ctx)
        assert plan["units_completed_count"] == 1
        assert plan["units_shipped_count"] == 1
        assert plan["production_status"] == "IN_PRODUCTION", (
            "production only completes when every unit of the plan has shipped"
        )

        loaded, meta = validate_paginated(
            api.list_work_orders(
                TEST_USERS["plant_supervisor_headers"],
                params={"shipment_id": shipment["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert loaded[0]["status"] == "SHIPPED"

    def test_02_shipment_with_no_complete_units_is_rejected(self, api):
        """A freshly released plan has nothing to load.

        PRD §3.8: "At rank 27 the plan must have at least one work order in
        status exactly `COMPLETE` to load, else `ERR_NO_SHIPPABLE_UNITS` (HTTP
        422)."

        Design: Corner/validations/shipment_with_no_complete_units_rejected
        """
        ctx = setup_released_plan()
        assert ctx["work_orders"][0]["status"] == "QUEUED"

        response = create_shipment_for_plan(ctx)
        validate_error(response, ApiErrorId.ERR_NO_SHIPPABLE_UNITS.value)

        _rows, meta = validate_paginated(
            api.list_shipments(TEST_USERS["logistics_coordinator_headers"])
        )
        assert meta["total_count"] == 0

    def test_03_delivery_outside_the_remodel_window_is_rejected(self, api):
        """A delivery eight days past the window's last day is refused.

        PRD §3.8: "At rank 28 the `delivery_date` must fall inside the plan's
        closed remodel window running from `remodel_window_start` through
        `remodel_window_end` inclusive, and must also be at or after the
        `ship_date`; a violation of either half is
        `ERR_DELIVERY_OUTSIDE_REMODEL_WINDOW` (HTTP 422)."

        Design: Corner/validations/shipment_delivery_outside_remodel_window_rejected
        """
        ctx = setup_plan_with_completed_units()
        assert ctx["store_plan"]["remodel_window_end"].startswith("2026-09-27")

        response = create_shipment_for_plan(
            ctx, ship_date="2026-10-02", delivery_date="2026-10-05"
        )
        validate_error(response, ApiErrorId.ERR_DELIVERY_OUTSIDE_REMODEL_WINDOW.value)

        unit = validate_success(
            api.get_work_order(
                ctx["work_orders"][0]["id"], TEST_USERS["plant_supervisor_headers"]
            )
        )
        assert unit["status"] == "COMPLETE"
        assert unit.get("shipment_id") is None

    def test_04_shipment_on_a_plan_under_compliance_hold_is_rejected(self, api):
        """A held line blocks freight even when the case is built and ready.

        PRD §3.8: "At rank 16 the plan must carry no held line, else
        `ERR_PLAN_ON_COMPLIANCE_HOLD` (HTTP 409)."

        Design: Corner/validations/shipment_on_plan_under_compliance_hold_rejected
        """
        ctx = setup_plan_with_completed_units()
        assert ctx["work_orders"][0]["status"] == "COMPLETE"

        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=ctx["refrigerant"]["id"],
                charge_grams=3900,
                line_set_length_ft=120,
                change_note="Charge reduction for low-GWP retrofit",
            )
        )

        response = create_shipment_for_plan(ctx)
        validate_error(response, ApiErrorId.ERR_PLAN_ON_COMPLIANCE_HOLD.value)

        plan = refresh_store_plan(ctx)
        assert plan["commercial_status"] == "HOLD_PENDING_RECERT"
        assert plan["production_status"] == "IN_PRODUCTION"
        assert plan["held_line_count"] == 1

    def test_05_stale_store_plan_version_is_rejected_on_shipment_creation(self, api):
        """A token read at approval time is refused once release has moved on.

        PRD §2.7: "If that value does not equal the plan's current `version`, the
        create is rejected with `ERR_STALE_STORE_PLAN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_store_plan_version_rejected_on_shipment_create
        """
        ctx = setup_approved_plan()
        stale_token = ctx["store_plan"]["version"]

        ctx["store_plan"] = validate_success(
            api.release_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["plant_supervisor_headers"]
            )
        )
        refresh_work_orders(ctx)
        complete_unit(ctx["work_orders"][0]["id"])
        refresh_store_plan(ctx)
        assert ctx["store_plan"]["version"] > stale_token

        stale = create_shipment_for_plan(
            ctx, expected_store_plan_version=stale_token
        )
        validate_error(stale, ApiErrorId.ERR_STALE_STORE_PLAN_VERSION.value)

        accepted = validate_success(
            create_shipment_for_plan(ctx), expected_status=201
        )
        assert accepted["status"] == "STAGED"
        assert accepted["unit_count"] == 1
        assert accepted["linear_feet"] == 8

        unit = validate_success(
            api.get_work_order(
                ctx["work_orders"][0]["id"], TEST_USERS["plant_supervisor_headers"]
            )
        )
        assert unit["status"] == "SHIPPED"


class TestShipmentCancellation:
    """PRD §3.8 — one cancel walks shipment, unit, plan, booking and crew."""

    def test_06_cancelling_a_loaded_shipment_runs_the_five_hop_cascade(self, api):
        """The case returns to COMPLETE and the crew gets its case-days back.

        PRD §3.8: "Hop 5, firing because those bookings were released, decreases
        the reserved crew's `committed_case_days` by that booking's
        `cases_committed` multiplied by its `day_count`."

        Design: Difficulty/transitive_cascade/shipment_cancel_five_hop_logistics_to_crew_cascade
        """
        ctx = setup_booked_shipment()
        assert ctx["install_crew"]["committed_case_days"] == 2
        loaded = validate_success(
            api.advance_shipment(
                ctx["shipment"]["id"], TEST_USERS["logistics_coordinator_headers"]
            )
        )
        assert loaded["status"] == "LOADED"

        cancelled = validate_success(
            api.cancel_shipment(
                ctx["shipment"]["id"],
                {"cancel_reason": "Store remodel slipped two weeks"},
                TEST_USERS["logistics_coordinator_headers"],
            )
        )
        assert cancelled["status"] == "CANCELLED"

        units = refresh_work_orders(ctx)
        assert units[0]["status"] == "COMPLETE"
        assert units[0].get("shipment_id") is None

        plan = refresh_store_plan(ctx)
        assert plan["units_shipped_count"] == 0
        assert plan["units_completed_count"] == 1
        assert plan["production_status"] == "IN_PRODUCTION"

        booking = refresh_install_booking(ctx)
        assert booking["status"] == "RELEASED"
        assert booking["day_count"] == 2

        assert refresh_install_crew(ctx)["committed_case_days"] == 0

    def test_07_cancelling_from_staged_runs_the_identical_cascade(self, api):
        """A trailer cancelled before loading unwinds exactly as a loaded one does.

        PRD §3.8: "All three starting states are treated identically: `STAGED →
        CANCELLED`, `LOADED → CANCELLED` and `IN_TRANSIT → CANCELLED` each run
        the same five-hop cascade with no branch differences whatsoever."

        Design: Difficulty/transitive_cascade/shipment_cancel_five_hop_logistics_to_crew_cascade
        """
        ctx = setup_booked_shipment()
        assert ctx["shipment"]["status"] == "STAGED"
        assert refresh_store_plan(ctx)["production_status"] == "COMPLETE"

        cancelled = validate_success(
            api.cancel_shipment(
                ctx["shipment"]["id"],
                {"cancel_reason": "Store remodel slipped two weeks"},
                TEST_USERS["logistics_coordinator_headers"],
            )
        )
        assert cancelled["status"] == "CANCELLED"

        units = refresh_work_orders(ctx)
        assert units[0]["status"] == "COMPLETE"
        assert units[0].get("shipment_id") is None

        plan = refresh_store_plan(ctx)
        assert plan["units_shipped_count"] == 0
        assert plan["production_status"] == "IN_PRODUCTION"

        assert refresh_install_booking(ctx)["status"] == "RELEASED"
        assert refresh_install_crew(ctx)["committed_case_days"] == 0
