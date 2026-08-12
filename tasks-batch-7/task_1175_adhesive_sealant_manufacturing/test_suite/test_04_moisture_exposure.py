"""Moisture exposure log, hold cascade across run -> lot -> shipment, hold release."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_exposure_event,
    create_and_complete_run,
    create_distributor,
    create_dry_room,
    create_formulation,
    create_mixed_batch,
    create_shipment_payload,
    create_vessel,
    release_lot,
    set_clock,
    setup_released_lot,
    lot_under_review_with_passing_full,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestExposureEventLog:
    def test_exposure_event_immutable_no_version_field(self, api, batch_operator_headers, plant_manager_headers):
        """PRD §2.4: "The `MoistureExposureEvent` entity is the single exception: it is an append-only log record and carries only `id` and `created_at` — both `updated_at` and `version` are absent on this resource."
        PRD §3.5: "An exposure of less than 30 minutes is merely recorded."

        Design: Corner/entities/exposure_event_immutable_no_version_field
        """
        set_clock()
        formulation = create_formulation("EPX-EV-1", activate=True)
        vessel = create_vessel("V-EV-1", capacity_liters=100)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        run = api.create_packaging_run(
            {
                "batch_id": batch["id"],
                "pack_format": "PAIL",
                "unit_volume_ml": 5000,
                "planned_units": 1,
                "planned_start_at": "2026-05-01T08:10:00Z",
                "planned_end_at": "2026-05-01T09:30:00Z",
            },
            batch_operator_headers,
        ).json()["data"]
        resp = api.create_exposure_event(
            run["id"], {"exposure_minutes": 10, "occurred_at": "2026-05-01T08:20:00Z"}, batch_operator_headers
        )
        event = validate_success(resp, expected_status=201)
        assert_exposure_event(event)

        run_after = validate_success(api.get_packaging_run(run["id"], plant_manager_headers))
        assert run_after["status"] == "OPEN"

    def test_exposure_below_threshold_no_state_change(self, api, batch_operator_headers, plant_manager_headers, qa_manager_headers):
        """PRD §3.5: "An exposure of less than 30 minutes is merely recorded. An exposure of 30 minutes or more triggers the hold cascade."

        Design: Corner/state_machines/exposure_below_threshold_no_state_change
        """
        ctx = setup_released_lot("EPX-SUB", volume_ml=5000, planned_units=3)
        run_id = ctx["run"]["id"]
        lot_id = ctx["lot_id"]
        resp = api.create_exposure_event(
            run_id, {"exposure_minutes": 29, "occurred_at": "2026-05-01T08:45:00Z"}, batch_operator_headers
        )
        event = validate_success(resp, expected_status=201)
        assert event["id"]

        data, meta = validate_paginated(
            api.list_exposure_events(plant_manager_headers, params={"packaging_run_id": run_id})
        )
        assert meta["total_count"] == 1

        run_after = validate_success(api.get_packaging_run(run_id, plant_manager_headers))
        assert run_after["status"] == "SEALED"
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["hold_status"] == "CLEAR"
        assert lot["units_quarantined"] == 0


class TestParallelQaHoldDimensions:
    """Difficulty instance production_lot_parallel_qa_hold_dimensions."""

    def _setup(self, api, batch_operator_headers):
        ctx = setup_released_lot(
            "SIL-PAR-1", volume_ml=5000, planned_units=3,
            chemistry_family="SILICONE", moisture_sensitive=True, with_dry_room=True,
        )
        set_clock("2026-05-01T09:00:00Z")
        resp = api.create_exposure_event(
            ctx["run"]["id"],
            {"exposure_minutes": 45, "occurred_at": "2026-05-01T08:45:00Z", "note": "humidity log breach"},
            batch_operator_headers,
        )
        validate_success(resp, expected_status=201)
        return ctx

    def test_hold_cascade_flips_only_the_hold_dimension(self, api, batch_operator_headers, qa_manager_headers):
        """PRD §3.5: "On a `SEALED` run, the cascade has three hops: the run moves to `HOLD` with `held_from` recording `SEALED`; the lot absorbs the quarantine — its `units_quarantined` grows by the run's `units_produced` and its `hold_status` becomes `QUARANTINE_HOLD`; and every shipment in `PLANNED` or `CONFIRMED` containing a line for that lot is forced into `EXCEPTION`."

        Design: Difficulty/non_linear_state_machine/production_lot_parallel_qa_hold_dimensions
        """
        ctx = self._setup(api, batch_operator_headers)
        lot = validate_success(api.get_production_lot(ctx["lot_id"], qa_manager_headers))
        assert lot["qa_status"] == "RELEASED"  # qa dimension untouched by the hold cascade
        assert lot["hold_status"] == "QUARANTINE_HOLD"
        assert lot["units_quarantined"] == 3

    def test_hold_release_restores_hold_dimension_only(self, api, batch_operator_headers, qa_manager_headers, plant_manager_headers):
        """PRD §3.5: "With `outcome` `RELEASE`, the run returns to whatever status `held_from` recorded (`OPEN` or `SEALED`), `held_from` is cleared, and for a run that had been `SEALED` the lot's `units_quarantined` is decremented by the run's `units_produced`; the lot's `hold_status` returns to `CLEAR` when no other run of that lot remains in `HOLD`, and stays `QUARANTINE_HOLD` otherwise."

        Design: Difficulty/non_linear_state_machine/production_lot_parallel_qa_hold_dimensions
        """
        ctx = self._setup(api, batch_operator_headers)
        resp = api.hold_release(ctx["run"]["id"], {"outcome": "RELEASE"}, qa_manager_headers)
        run_after = validate_success(resp)
        assert run_after["status"] == "SEALED"  # held_from restored

        lot = validate_success(api.get_production_lot(ctx["lot_id"], qa_manager_headers))
        assert lot["hold_status"] == "CLEAR"
        assert lot["units_quarantined"] == 0
        assert lot["qa_status"] == "RELEASED"


class TestExposureRunLotShipmentChain:
    """Difficulty instance moisture_exposure_run_lot_shipment_chain."""

    def _setup(self, api, logistics_headers, batch_operator_headers):
        ctx = setup_released_lot(
            "EPX-CAS-1", volume_ml=5000, planned_units=3,
            chemistry_family="EPOXY", moisture_sensitive=True, with_dry_room=True,
        )
        distributor = create_distributor(name="Dist CAS", contact_email="c@x.com")
        shipment = validate_success(
            api.create_shipment(create_shipment_payload(distributor["id"]), logistics_headers),
            expected_status=201,
        )
        validate_success(
            api.add_shipment_line(shipment["id"], {"lot_id": ctx["lot_id"], "units": 2}, logistics_headers)
        )
        shipment = validate_success(api.plan_shipment(shipment["id"], logistics_headers))
        assert shipment["status"] == "PLANNED"
        set_clock("2026-05-01T09:00:00Z")
        ctx["distributor"] = distributor
        ctx["shipment"] = shipment
        return ctx

    def test_exposure_hops_run_and_lot(self, api, logistics_headers, batch_operator_headers, plant_manager_headers, qa_manager_headers):
        """PRD §3.5: "On a `SEALED` run, the cascade has three hops: the run moves to `HOLD` with `held_from` recording `SEALED`; the lot absorbs the quarantine — its `units_quarantined` grows by the run's `units_produced` and its `hold_status` becomes `QUARANTINE_HOLD`; and every shipment in `PLANNED` or `CONFIRMED` containing a line for that lot is forced into `EXCEPTION`."

        Design: Difficulty/transitive_cascade/moisture_exposure_run_lot_shipment_chain
        """
        ctx = self._setup(api, logistics_headers, batch_operator_headers)
        resp = api.create_exposure_event(
            ctx["run"]["id"],
            {"exposure_minutes": 45, "occurred_at": "2026-05-01T08:45:00Z", "note": "door left open"},
            batch_operator_headers,
        )
        validate_success(resp, expected_status=201)

        run_after = validate_success(api.get_packaging_run(ctx["run"]["id"], plant_manager_headers))
        assert run_after["status"] == "HOLD"
        assert run_after["held_from"] == "SEALED"
        lot = validate_success(api.get_production_lot(ctx["lot_id"], qa_manager_headers))
        assert lot["hold_status"] == "QUARANTINE_HOLD"
        assert lot["units_quarantined"] == 3
        assert lot["qa_status"] == "RELEASED"  # unaffected dimension

    def test_exposure_cascade_forces_planned_shipment_to_exception(self, api, logistics_headers, batch_operator_headers):
        """PRD §3.9: "The moisture cascade reaches shipments directly: any shipment in `PLANNED` or `CONFIRMED` that contains a line for a lot entering `QUARANTINE_HOLD` is moved to `EXCEPTION`."

        Design: Difficulty/transitive_cascade/moisture_exposure_run_lot_shipment_chain
        """
        ctx = self._setup(api, logistics_headers, batch_operator_headers)
        resp = api.create_exposure_event(
            ctx["run"]["id"],
            {"exposure_minutes": 45, "occurred_at": "2026-05-01T08:45:00Z", "note": "door left open"},
            batch_operator_headers,
        )
        validate_success(resp, expected_status=201)

        shipment = validate_success(api.get_shipment(ctx["shipment"]["id"], logistics_headers))
        assert shipment["status"] == "EXCEPTION"


class TestRunStateGuards:
    def test_run_complete_from_hold_returns_409(self, api, batch_operator_headers, plant_manager_headers):
        """PRD §3.4: "Completing a run — a `BatchOperator` action valid only while the run is `OPEN` (otherwise `ERR_RUN_INVALID_STATE`)"

        Design: Corner/state_machines/run_complete_from_hold_returns_409
        """
        set_clock()
        formulation = create_formulation("EPX-HLD", activate=True)
        vessel = create_vessel("V-HLD", capacity_liters=100)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        run = create_and_complete_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        validate_success(
            api.create_exposure_event(
                run["id"], {"exposure_minutes": 45, "occurred_at": "2026-05-01T08:45:00Z"}, batch_operator_headers
            ),
            expected_status=201,
        )
        resp = api.complete_run(run["id"], batch_operator_headers)
        validate_error(resp, ApiErrorId.ERR_RUN_INVALID_STATE)
        run_after = validate_success(api.get_packaging_run(run["id"], plant_manager_headers))
        assert run_after["status"] == "HOLD"
