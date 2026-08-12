"""Shipments: FIFO, hazmat classification and mode gate, shelf-life gating,
consignment agreement gating, exception/replan, line reservations."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_distributor,
    create_dry_room,
    create_formulation,
    create_shipment_payload,
    create_vessel,
    lot_under_review_with_passing_full,
    set_clock,
    setup_released_lot,
    validate_error,
    validate_success,
)


def _draft_shipment(api, distributor_id, logistics_headers, **overrides):
    return validate_success(
        api.create_shipment(create_shipment_payload(distributor_id, **overrides), logistics_headers),
        expected_status=201,
    )


class TestHazmatClassificationMultiInput:
    """Difficulty instance hazmat_classification_multi_input_mode_a."""

    def _setup(self, api, logistics_headers):
        ctx = setup_released_lot(
            "SLV-HZ-1", volume_ml=500000, planned_units=2,
            pack_format="DRUM", unit_volume_ml=200000,
            chemistry_family="ACRYLIC", solvent_content_pct=30.0, flash_point_c=20.0,
        )
        distributor = create_distributor(name="Dist HZ", contact_email="h@x.com")
        ship_air = _draft_shipment(api, distributor["id"], logistics_headers,
                                   transport_mode="AIR", ship_date="2026-06-01")
        validate_success(api.add_shipment_line(ship_air["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))
        ship_air = validate_success(api.plan_shipment(ship_air["id"], logistics_headers))
        ship_road = _draft_shipment(api, distributor["id"], logistics_headers,
                                    transport_mode="ROAD", ship_date="2026-06-01")
        validate_success(api.add_shipment_line(ship_road["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))
        ship_road = validate_success(api.plan_shipment(ship_road["id"], logistics_headers))
        return ctx, ship_air, ship_road

    def test_plan_computes_worst_hazmat_class_across_lines(self, api, logistics_headers):
        """PRD §3.9: "Each line is classified from its formulation and pack: when the formulation's `solvent_content_pct` is at least 24.0 and its `flash_point_c` is below 60.5 °C, the line falls under UN1133 Class 3 — packing group `UN1133_CLASS3_PG_II` when `flash_point_c` is below 23.0 °C, otherwise `UN1133_CLASS3_PG_III`. Any other formulation is `NON_REGULATED`."

        Design: Difficulty/combinatorial_formula/hazmat_classification_multi_input_mode_a
        """
        _ctx, ship_air, _ship_road = self._setup(api, logistics_headers)
        # solvent 30.0 >= 24.0 AND flash 20.0 < 23.0 -> UN1133 PG_II.
        assert ship_air["hazmat_class"] == "UN1133_CLASS3_PG_II"

    def test_air_mode_gate_rejects_pgii_large_unit_but_road_confirms(self, api, logistics_headers):
        """PRD §3.9: "The hazmat mode gate applies only when `transport_mode` is `AIR`: any line classified `UN1133_CLASS3_PG_II` whose lot's `unit_volume_ml` exceeds 5000 ml is forbidden, and any `UN1133_CLASS3_PG_III` line packed as a `DRUM` is likewise forbidden; both surface as `ERR_HAZMAT_MODE_FORBIDDEN`. `ROAD` and `SEA` impose no additional gate."

        Design: Difficulty/combinatorial_formula/hazmat_classification_multi_input_mode_a
        """
        _ctx, ship_air, ship_road = self._setup(api, logistics_headers)
        resp_air = api.confirm_shipment(ship_air["id"], logistics_headers)
        validate_error(resp_air, ApiErrorId.ERR_HAZMAT_MODE_FORBIDDEN)
        air_after = validate_success(api.get_shipment(ship_air["id"], logistics_headers))
        assert air_after["status"] == "PLANNED"

        confirmed_road = validate_success(api.confirm_shipment(ship_road["id"], logistics_headers))
        assert confirmed_road["status"] == "CONFIRMED"


class TestMinShelfLifeBoundaryOnConfirm:
    """Difficulty instance min_shelf_life_inclusive_boundary_on_confirm."""

    def _setup(self, api, logistics_headers):
        # Manufactured 2026-05-01, shelf life 6 months -> expiry 2026-11-01; min 90 days.
        ctx = setup_released_lot("EPX-SHL-1", volume_ml=5000, planned_units=10)
        distributor = create_distributor(name="Dist SHL", contact_email="sh@x.com")
        return ctx, distributor

    def test_confirm_at_exact_min_remaining_days_passes(self, api, logistics_headers):
        """PRD §3.9: "the remaining days are the calendar-day difference between the lot's `expiry_date` and the `ship_date`, and the line passes when the remainder is at least the applicable minimum — equality passes, anything less fails with `ERR_MIN_SHELF_LIFE_VIOLATION`."

        Design: Difficulty/boundary_precision_check/min_shelf_life_inclusive_boundary_on_confirm
        """
        ctx, distributor = self._setup(api, logistics_headers)
        # 2026-08-03 -> 90 days remaining == min 90 (inclusive pass).
        ship1 = _draft_shipment(api, distributor["id"], logistics_headers, ship_date="2026-08-03")
        validate_success(api.add_shipment_line(ship1["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))
        validate_success(api.plan_shipment(ship1["id"], logistics_headers))
        confirmed = validate_success(api.confirm_shipment(ship1["id"], logistics_headers))
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_one_day_short_fails(self, api, logistics_headers):
        """PRD §3.9: "the remaining days are the calendar-day difference between the lot's `expiry_date` and the `ship_date`, and the line passes when the remainder is at least the applicable minimum — equality passes, anything less fails with `ERR_MIN_SHELF_LIFE_VIOLATION`."

        Design: Difficulty/boundary_precision_check/min_shelf_life_inclusive_boundary_on_confirm
        """
        ctx, distributor = self._setup(api, logistics_headers)
        # 2026-08-04 -> 89 days remaining < 90.
        ship2 = _draft_shipment(api, distributor["id"], logistics_headers, ship_date="2026-08-04")
        validate_success(api.add_shipment_line(ship2["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))
        validate_success(api.plan_shipment(ship2["id"], logistics_headers))
        resp = api.confirm_shipment(ship2["id"], logistics_headers)
        validate_error(resp, ApiErrorId.ERR_MIN_SHELF_LIFE_VIOLATION)
        ship2_after = validate_success(api.get_shipment(ship2["id"], logistics_headers))
        assert ship2_after["status"] == "PLANNED"


class TestConfirmSafetyBeatsTemporal:
    """Difficulty instance confirm_dual_failure_safety_beats_temporal."""

    def _setup(self, api, logistics_headers):
        # PG_II DRUM 200000 ml, expiry 2026-11-01, formulation min 90 days.
        ctx = setup_released_lot(
            "SLV-ST-1", volume_ml=500000, planned_units=2,
            pack_format="DRUM", unit_volume_ml=200000,
            chemistry_family="ACRYLIC", solvent_content_pct=30.0, flash_point_c=20.0,
        )
        distributor = create_distributor(name="Dist ST", contact_email="s@x.com")
        # ship_date 2026-08-04 -> 89 days remaining (< 90): temporal ALSO fails.
        ship = _draft_shipment(api, distributor["id"], logistics_headers,
                               transport_mode="AIR", ship_date="2026-08-04")
        validate_success(api.add_shipment_line(ship["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))
        ship = validate_success(api.plan_shipment(ship["id"], logistics_headers))
        return ship

    def test_dual_failure_reports_hazmat_safety_error(self, api, logistics_headers):
        """PRD §3.9: "Confirmation moves `PLANNED` to `CONFIRMED` and applies its gates **in order: safety first, then temporal**."

        Design: Difficulty/priority_pair_validation_conflict/confirm_dual_failure_safety_beats_temporal
        """
        ship = self._setup(api, logistics_headers)
        resp = api.confirm_shipment(ship["id"], logistics_headers)
        validate_error(resp, ApiErrorId.ERR_HAZMAT_MODE_FORBIDDEN)
        assert resp.json()["data"]["error_id"] != "ERR_MIN_SHELF_LIFE_VIOLATION"

    def test_dual_failure_leaves_shipment_planned(self, api, logistics_headers):
        """PRD §3.9: "Confirmation moves `PLANNED` to `CONFIRMED` and applies its gates **in order: safety first, then temporal**."

        Design: Difficulty/priority_pair_validation_conflict/confirm_dual_failure_safety_beats_temporal
        """
        ship = self._setup(api, logistics_headers)
        api.confirm_shipment(ship["id"], logistics_headers)
        after = validate_success(api.get_shipment(ship["id"], logistics_headers))
        assert after["status"] == "PLANNED"


class TestConsignmentConfirmBlockedBySuspendedAgreement:
    """Difficulty instance consignment_confirm_blocked_by_suspended_agreement."""

    def _setup(self, api, logistics_headers, commercial_manager_headers):
        ctx = setup_released_lot(
            "PU-XEN-2", volume_ml=5000, planned_units=10, chemistry_family="POLYURETHANE"
        )
        distributor = create_distributor(name="Dist X2", contact_email="x2@x.com")
        from test_helpers import create_agreement_payload
        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    distributor["id"], ctx["formulation"]["id"],
                    unit_price_cents=1000, max_consigned_value_cents=500000,
                    reorder_threshold_units=0, reorder_qty_units=100,
                ),
                commercial_manager_headers,
            ),
            expected_status=201,
        )
        agreement = validate_success(api.activate_agreement(agreement["id"], commercial_manager_headers))
        ship = _draft_shipment(
            api, distributor["id"], logistics_headers,
            shipment_kind="CONSIGNMENT", agreement_id=agreement["id"], ship_date="2026-06-01",
        )
        validate_success(api.add_shipment_line(ship["id"], {"lot_id": ctx["lot_id"], "units": 5}, logistics_headers))
        ship = validate_success(api.plan_shipment(ship["id"], logistics_headers))
        validate_success(api.suspend_agreement(agreement["id"], commercial_manager_headers))
        return ctx, ship

    def test_confirm_rejected_while_agreement_suspended(self, api, logistics_headers, commercial_manager_headers):
        """PRD §3.9: "For consignment kinds, confirmation also requires the agreement to be `ACTIVE`, failing with `ERR_AGREEMENT_NOT_ACTIVE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/consignment_confirm_blocked_by_suspended_agreement
        """
        _ctx, ship = self._setup(api, logistics_headers, commercial_manager_headers)
        resp = api.confirm_shipment(ship["id"], logistics_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_shipment_unchanged_after_blocked_confirm(self, api, logistics_headers, commercial_manager_headers):
        """PRD §3.9: "For consignment kinds, confirmation also requires the agreement to be `ACTIVE`, failing with `ERR_AGREEMENT_NOT_ACTIVE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/consignment_confirm_blocked_by_suspended_agreement
        """
        _ctx, ship = self._setup(api, logistics_headers, commercial_manager_headers)
        api.confirm_shipment(ship["id"], logistics_headers)
        after = validate_success(api.get_shipment(ship["id"], logistics_headers))
        assert after["status"] == "PLANNED"
        # The shipment-local checks are fine; the rejection is purely the
        # cross-entity agreement gate.
        assert after["hazmat_class"] == "NON_REGULATED"


class TestShipmentTransitionsAndLines:
    def test_dispatch_from_planned_returns_409(self, api, logistics_headers, qa_manager_headers):
        """PRD §3.9: "Any state call against a shipment not in the expected from-state fails with `ERR_SHIPMENT_INVALID_STATE`."
        PRD §3.9: "Dispatch moves `CONFIRMED` to `DISPATCHED`. For consignment kinds the agreement must still be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`)."

        Design: Corner/state_machines/dispatch_from_planned_returns_409
        """
        ctx = setup_released_lot("EPX-DSP", volume_ml=5000, planned_units=10)
        distributor = create_distributor(name="Dist DSP", contact_email="d@x.com")
        ship = _draft_shipment(api, distributor["id"], logistics_headers)
        validate_success(api.add_shipment_line(ship["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))
        validate_success(api.plan_shipment(ship["id"], logistics_headers))

        resp = api.dispatch_shipment(ship["id"], logistics_headers)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_INVALID_STATE)

        after = validate_success(api.get_shipment(ship["id"], logistics_headers))
        assert after["status"] == "PLANNED"
        lot = validate_success(api.get_production_lot(ctx["lot_id"], qa_manager_headers))
        assert lot["units_shipped"] == 0

    def test_line_add_duplicate_lot_returns_409(self, api, logistics_headers):
        """PRD §3.9: "Lines are added to a shipment only while it is in `DRAFT` or `EXCEPTION`; each line names a `lot_id` and a `units` count, and a lot may appear at most once per shipment — a duplicate line is rejected with `ERR_DUPLICATE_LOT_LINE`."

        Design: Corner/endpoints/line_add_duplicate_lot_returns_409
        """
        ctx = setup_released_lot("EPX-DUP", volume_ml=5000, planned_units=10)
        distributor = create_distributor(name="Dist DUP", contact_email="du@x.com")
        ship = _draft_shipment(api, distributor["id"], logistics_headers)
        validate_success(api.add_shipment_line(ship["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))

        resp = api.add_shipment_line(ship["id"], {"lot_id": ctx["lot_id"], "units": 2}, logistics_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_LINE)

        after = validate_success(api.get_shipment(ship["id"], logistics_headers))
        assert len(after["lines"]) == 1
        assert after["lines"][0]["lot_id"] == ctx["lot_id"]
        assert after["lines"][0]["units"] == 1

    def test_sale_dispatch_decrements_lot_units_and_stock_check(self, api, logistics_headers, qa_manager_headers):
        """PRD §3.9: "Availability itself is computed as the lot's `units_filled` minus `units_quarantined` minus `units_condemned` minus `units_shipped` minus a reservation term that sums the `units` of every line referencing the lot across all shipments in `DRAFT`, `PLANNED`, or `CONFIRMED`; a line whose `units` exceed that availability is rejected with `ERR_INSUFFICIENT_LOT_STOCK`."
        PRD §3.9: "Dispatch performs two stock effects per line: the lot's `units_shipped` grows by the line's `units`, and for consignment kinds the **ConsignmentStock** row keyed by the unique `(agreement_id, lot_id)` pair (carried on the row's `row_key`) is upserted — created on first dispatch with counters at zero, thereafter incremented — with `qty_shipped` and `qty_on_hand` each growing by the line's `units`."

        Design: Corner/endpoints/sale_dispatch_decrements_lot_units_and_stock_check
        """
        ctx = setup_released_lot("EPX-SAL", volume_ml=5000, planned_units=10)
        distributor = create_distributor(name="Dist SAL", contact_email="sa@x.com")
        ship1 = _draft_shipment(api, distributor["id"], logistics_headers)
        validate_success(api.add_shipment_line(ship1["id"], {"lot_id": ctx["lot_id"], "units": 2}, logistics_headers))
        validate_success(api.plan_shipment(ship1["id"], logistics_headers))
        validate_success(api.confirm_shipment(ship1["id"], logistics_headers))
        ship2 = _draft_shipment(api, distributor["id"], logistics_headers)

        dispatched = validate_success(api.dispatch_shipment(ship1["id"], logistics_headers))
        assert dispatched["status"] == "DISPATCHED"
        lot = validate_success(api.get_production_lot(ctx["lot_id"], qa_manager_headers))
        assert lot["units_shipped"] == 2

        # 10 filled - 2 shipped = 8 available; 9 exceeds it.
        resp = api.add_shipment_line(ship2["id"], {"lot_id": ctx["lot_id"], "units": 9}, logistics_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_STOCK)

    def test_line_remove_releases_reservation(self, api, logistics_headers):
        """PRD §3.9: "Lines may similarly be removed while the shipment is in `DRAFT` or `EXCEPTION`, releasing the reservation."

        Design: Corner/endpoints/line_remove_releases_reservation
        """
        ctx = setup_released_lot("EPX-REL", volume_ml=5000, planned_units=10)
        distributor = create_distributor(name="Dist REL", contact_email="re@x.com")
        ship1 = _draft_shipment(api, distributor["id"], logistics_headers)
        validate_success(api.add_shipment_line(ship1["id"], {"lot_id": ctx["lot_id"], "units": 10}, logistics_headers))
        ship2 = _draft_shipment(api, distributor["id"], logistics_headers)

        resp = api.add_shipment_line(ship2["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_STOCK)

        validate_success(api.remove_shipment_line(ship1["id"], ctx["lot_id"], logistics_headers))
        ok = validate_success(api.add_shipment_line(ship2["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers))
        assert any(line["lot_id"] == ctx["lot_id"] and line["units"] == 1 for line in ok["lines"])

    def test_line_add_unreleased_lot_returns_409(self, api, logistics_headers):
        """PRD §3.9: "The lot must be shippable: `qa_status` `RELEASED`, `hold_status` `CLEAR`, and an `expiry_date` strictly after the shipment's `ship_date`. A lot failing the release or dating leg is rejected with `ERR_LOT_NOT_SHIPPABLE`; a lot under quarantine is rejected with `ERR_LOT_ON_HOLD`."

        Design: Corner/errors/line_add_unreleased_lot_returns_409
        """
        # Build a lot that sits in UNDER_REVIEW (never released) per the design:
        # mixed batch, then record+accept a passing FULL test without releasing.
        from test_helpers import create_mixed_batch
        set_clock()
        formulation = create_formulation("EPX-UNR", activate=True)
        vessel = create_vessel("V-UNR", capacity_liters=100)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        lot_id = batch["production_lot_id"]
        lot_under_review_with_passing_full(lot_id)
        lot = validate_success(api.get_production_lot(lot_id, logistics_headers))
        assert lot["qa_status"] == "UNDER_REVIEW"

        distributor = create_distributor(name="Dist UNR", contact_email="un@x.com")
        ship = _draft_shipment(api, distributor["id"], logistics_headers)
        resp = api.add_shipment_line(ship["id"], {"lot_id": lot_id, "units": 1}, logistics_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_SHIPPABLE)

    def test_line_add_quarantined_lot_returns_409(self, api, logistics_headers, batch_operator_headers):
        """PRD §3.9: "The lot must be shippable: `qa_status` `RELEASED`, `hold_status` `CLEAR`, and an `expiry_date` strictly after the shipment's `ship_date`. A lot failing the release or dating leg is rejected with `ERR_LOT_NOT_SHIPPABLE`; a lot under quarantine is rejected with `ERR_LOT_ON_HOLD`."

        Design: Corner/errors/line_add_quarantined_lot_returns_409
        """
        ctx = setup_released_lot(
            "EPX-QHL", volume_ml=5000, planned_units=3,
            moisture_sensitive=True, with_dry_room=True,
        )
        validate_success(
            api.create_exposure_event(
                ctx["run"]["id"], {"exposure_minutes": 45, "occurred_at": "2026-05-01T08:45:00Z"},
                batch_operator_headers,
            ),
            expected_status=201,
        )
        distributor = create_distributor(name="Dist QHL", contact_email="qh@x.com")
        ship = _draft_shipment(api, distributor["id"], logistics_headers)
        resp = api.add_shipment_line(ship["id"], {"lot_id": ctx["lot_id"], "units": 1}, logistics_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_ON_HOLD)


class TestReplanAfterException:
    def test_replan_blocked_until_blocked_lines_removed(self, api, logistics_headers, batch_operator_headers):
        """PRD §3.9: "From `EXCEPTION`, a `LogisticsCoordinator` replans once every blocked line has been removed — replan requires that no remaining line reference a lot whose `hold_status` is not `CLEAR`, else `ERR_SHIPMENT_BLOCKED_LINES` — and the shipment returns to `PLANNED` with `hazmat_class` recomputed from the remaining lines."

        Design: Corner/endpoints/replan_blocked_until_blocked_lines_removed
        """
        ctx = setup_released_lot(
            "EPX-RPL", volume_ml=5000, planned_units=3,
            moisture_sensitive=True, with_dry_room=True,
        )
        distributor = create_distributor(name="Dist RPL", contact_email="rp@x.com")
        ship = _draft_shipment(api, distributor["id"], logistics_headers)
        validate_success(api.add_shipment_line(ship["id"], {"lot_id": ctx["lot_id"], "units": 2}, logistics_headers))
        validate_success(api.plan_shipment(ship["id"], logistics_headers))

        # Drive the lot into QUARANTINE_HOLD; the PLANNED shipment -> EXCEPTION.
        validate_success(
            api.create_exposure_event(
                ctx["run"]["id"], {"exposure_minutes": 45, "occurred_at": "2026-05-01T08:45:00Z"},
                batch_operator_headers,
            ),
            expected_status=201,
        )
        blocked = validate_success(api.get_shipment(ship["id"], logistics_headers))
        assert blocked["status"] == "EXCEPTION"

        resp = api.replan_shipment(ship["id"], logistics_headers)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_BLOCKED_LINES)

        validate_success(api.remove_shipment_line(ship["id"], ctx["lot_id"], logistics_headers))
        replanned = validate_success(api.replan_shipment(ship["id"], logistics_headers))
        assert replanned["status"] == "PLANNED"
        assert replanned["lines"] == []
        assert replanned["hazmat_class"] == "NON_REGULATED"


class TestFifoLotSelection:
    def test_fifo_violation_blocks_newer_lot_until_oldest_exhausted(self, api, logistics_headers):
        """PRD §3.9: "Then strict FIFO applies across the formulation: among every `RELEASED`, `CLEAR` lot of the same `formulation_id` whose `expiry_date` lies strictly after `ship_date` and which still has available units, the lot with the earliest `expiry_date` (ties broken by the earliest `created_at`) must be the lot on the line; choosing any newer eligible lot while an older one still has availability is rejected with `ERR_FIFO_VIOLATION`."

        Design: Corner/calculations/fifo_violation_blocks_newer_lot_until_oldest_exhausted
        """
        # Lot 1: manufactured 2026-05-01 (expiry 2026-11-01), 10 units.
        ctx1 = setup_released_lot("EPX-FIFO", volume_ml=5000, planned_units=10)
        formulation_id = ctx1["formulation"]["id"]
        vessel_id = ctx1["vessel"]["id"]
        # Lot 2: manufactured 2026-06-01 (expiry 2026-12-01), 10 units.
        from test_helpers import api_client as _api
        from test_helpers import TEST_USERS as _TU
        from test_helpers import create_mixed_batch, create_and_complete_run
        set_clock("2026-06-01T08:00:00Z")
        batch2 = create_mixed_batch(
            formulation_id, vessel_id,
            mix_start_at="2026-06-01T08:00:00Z", mix_end_at="2026-06-01T08:30:00Z",
            batch_volume_ml=5000,
        )
        lot2_id = batch2["production_lot_id"]
        create_and_complete_run(
            batch2["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=10,
            planned_start_at="2026-06-01T08:10:00Z", planned_end_at="2026-06-01T09:30:00Z",
        )
        lot_under_review_with_passing_full(lot2_id)
        from test_helpers import release_lot as _release
        _release(lot2_id)

        distributor = create_distributor(name="Dist FIFO", contact_email="ff@x.com")
        ship = _draft_shipment(api, distributor["id"], logistics_headers, ship_date="2026-08-01")

        # Step 1: the newer lot is blocked while the older still has availability.
        resp = api.add_shipment_line(ship["id"], {"lot_id": lot2_id, "units": 1}, logistics_headers)
        validate_error(resp, ApiErrorId.ERR_FIFO_VIOLATION)

        # Step 2: lining the required oldest lot succeeds.
        validate_success(api.add_shipment_line(ship["id"], {"lot_id": ctx1["lot_id"], "units": 10}, logistics_headers))

        # Step 3: with the older lot fully reserved, the newer lot is now eligible.
        final = validate_success(api.add_shipment_line(ship["id"], {"lot_id": lot2_id, "units": 5}, logistics_headers))
        assert len(final["lines"]) == 2
        assert sum(line["units"] for line in final["lines"]) == 15
