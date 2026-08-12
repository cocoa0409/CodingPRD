"""Tests for spill reporting and glycol recycling."""
import pytest

from test_helpers import (

    ApiErrorId,
    TEST_USERS,
    create_fluid_tank,
    create_recycling_contract_payload,
    create_spill_report_payload,
    create_station,
    make_environmental_officer_headers,
    record_shipment_payload,
    setup_operation_cleared,
    setup_recycling_contract_with_pool,
    setup_spill_confirmed,
    setup_spill_report,
    validate_error,
    validate_success,
)


class TestSpillClassification:
    def test_spill_classification_minor_below_100(self, api):
        """PRD §3.7: "its `classification` is derived: `REPORTABLE` when the
        quantity is 100 liters or more — a spill of exactly 100 liters is
        reportable — and `MINOR` below that."

        Design: Difficulty/boundary_precision_check/spill_reportable_at_exactly_100_liters
        """
        station, tank, _ = setup_spill_report(quantity_liters=1)

        # 99.99 L → MINOR.
        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=99.99
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        data = validate_success(resp, expected_status=201)
        assert data["classification"] == "MINOR"

        # 100.0 L → REPORTABLE.
        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=100.0
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        data = validate_success(resp, expected_status=201)
        assert data["classification"] == "REPORTABLE"

    def test_spill_reportable_at_exactly_100_liters(self, api):
        """PRD §3.7: "its `classification` is derived: `REPORTABLE` when the
        quantity is 100 liters or more — a spill of exactly 100 liters is
        reportable — and `MINOR` below that."

        Design: Difficulty/boundary_precision_check/spill_reportable_at_exactly_100_liters
        """
        station, tank, _ = setup_spill_report(quantity_liters=1)

        # Exactly 100.0 L → REPORTABLE.
        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=100.0
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        data = validate_success(resp, expected_status=201)
        assert data["classification"] == "REPORTABLE"

        # 99.99 L → MINOR.
        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=99.99
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        data = validate_success(resp, expected_status=201)
        assert data["classification"] == "MINOR"


class TestSpillDeadline:
    def test_spill_confirm_deadline_boundary(self, api):
        """PRD §3.7: "Confirmation must happen quickly: confirming is rejected
        with `ERR_SPILL_DEADLINE_PASSED` once the logical clock has advanced
        beyond 120 minutes past `occurred_at`."

        Design: Corner/errors/spill_confirm_deadline_boundary
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=5000,
            reorder_threshold_liters=300,
        )
        # Two spills reported at the default clock instant.
        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=10
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        sp1 = validate_success(resp, expected_status=201)

        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=10
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        sp2 = validate_success(resp, expected_status=201)

        # At exactly +120 min: confirm succeeds.
        api.set_current_utc(
            {"to_iso8601": "2026-05-01T02:00:00Z"},
            TEST_USERS["station_admin_headers"],
        )
        resp = api.confirm_spill_report(
            sp1["id"], make_environmental_officer_headers("eo-2")
        )
        assert validate_success(resp)["status"] == "CONFIRMED"

        # At +121 min: confirm fails.
        api.set_current_utc(
            {"to_iso8601": "2026-05-01T02:01:00Z"},
            TEST_USERS["station_admin_headers"],
        )
        resp = api.confirm_spill_report(
            sp2["id"], make_environmental_officer_headers("eo-2")
        )
        validate_error(resp, ApiErrorId.ERR_SPILL_DEADLINE_PASSED)

        # Tank deducted only for sp1.
        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["environmental_officer_headers"]
        )
        assert validate_success(resp)["on_hand_liters"] == 4990


class TestSpillSegregationOfDuties:
    def test_spill_close_by_reporter_sod_rejected(self, api):
        """PRD §3.7: "segregation of duties forbids the reporter from closing
        their own report, so a `closed_by` equal to `reporter_id` is rejected
        with `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/spill_close_by_reporter_sod_rejected
        """
        station, tank, spill = setup_spill_confirmed(
            quantity_liters=20, reporter_id="eo-1", confirmer_id="eo-2"
        )

        # Reporter cannot close.
        resp = api.close_spill_report(
            spill["id"], make_environmental_officer_headers("eo-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        # Another officer closes.
        resp = api.close_spill_report(
            spill["id"], make_environmental_officer_headers("eo-2")
        )
        data = validate_success(resp)
        assert data["status"] == "CLOSED"
        assert data["closed_by"] == "eo-2"


class TestSpillConfirmCascade:
    def test_spill_confirm_deducts_from_tank(self, api):
        """PRD §3.7: "A successful confirm moves the report to `CONFIRMED`,
        records the confirming officer as `confirmed_by`, deducts the spilled
        `quantity_liters` from the source tank's `on_hand_liters` — flooring at
        zero so a tank never goes negative — and recomputes the tank's status
        and the station's supply alert."

        Design: Difficulty/transitive_cascade/spill_confirm_tank_threshold_cascade
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=5000,
            reorder_threshold_liters=300,
        )
        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=100
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        spill = validate_success(resp, expected_status=201)

        resp = api.confirm_spill_report(
            spill["id"], make_environmental_officer_headers("eo-2")
        )
        assert validate_success(resp)["status"] == "CONFIRMED"

        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["environmental_officer_headers"]
        )
        tank_after = validate_success(resp)
        assert tank_after["on_hand_liters"] == 4900

    def test_spill_confirm_tank_threshold_cascade(self, api):
        """PRD §3.7: "A successful confirm moves the report to `CONFIRMED`,
        records the confirming officer as `confirmed_by`, deducts the spilled
        `quantity_liters` from the source tank's `on_hand_liters` — flooring at
        zero so a tank never goes negative — and recomputes the tank's status
        and the station's supply alert."
        PRD §2.7: "The station's `active_supply_alert` flag is true whenever
        any of its tanks is in `REORDER_PENDING` or `EMPTY` status."

        Design: Difficulty/transitive_cascade/spill_confirm_tank_threshold_cascade
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_IV",
            concentration_pct=100,
            capacity_liters=4000,
            on_hand_liters=800,
            reorder_threshold_liters=500,
        )
        payload = create_spill_report_payload(
            station["id"], tank["id"], quantity_liters=350
        )
        resp = api.create_spill_report(
            payload, make_environmental_officer_headers("eo-1")
        )
        spill = validate_success(resp, expected_status=201)
        assert spill["classification"] == "REPORTABLE"

        # Confirm.
        resp = api.confirm_spill_report(
            spill["id"], make_environmental_officer_headers("eo-2")
        )
        assert validate_success(resp)["status"] == "CONFIRMED"

        # Tank drops below threshold.
        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["environmental_officer_headers"]
        )
        tank_after = validate_success(resp)
        assert tank_after["on_hand_liters"] == 450
        assert tank_after["status"] == "REORDER_PENDING"

        # Station alert raised.
        resp = api.get_station(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        assert validate_success(resp)["active_supply_alert"] is True


class TestRecycling:
    def test_recycle_shipment_below_quality_rejected(self, api):
        """PRD §3.8: "the load's concentration must meet or exceed the
        contract's `min_concentration_pct`, else `ERR_RECYCLE_QUALITY`."

        Design: Corner/errors/recycle_shipment_below_quality_rejected
        """
        station, permit, tank, pad, airline, request, operation, contract = (
            setup_recycling_contract_with_pool(
                pool_liters=400, actual_liters=600,
                contract_overrides={"min_concentration_pct": 40}
            )
        )

        resp = api.record_shipment(
            contract["id"],
            record_shipment_payload(volume_liters=100, concentration_pct=30),
            TEST_USERS["station_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RECYCLE_QUALITY)

        resp = api.get_recycling_contract(
            contract["id"], TEST_USERS["station_admin_headers"]
        )
        assert validate_success(resp)["delivered_liters"] == 0

        resp = api.get_station(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        assert validate_success(resp)["collected_pool_liters"] == 400

    def test_recycle_shipment_exceeding_pool_rejected(self, api):
        """PRD §3.8: "the shipment volume must not exceed the station's current
        `collected_pool_liters`, else `ERR_INSUFFICIENT_COLLECTED_GLYCOL`."

        Design: Corner/errors/recycle_shipment_exceeding_pool_rejected
        """
        station, permit, tank, pad, airline, request, operation, contract = (
            setup_recycling_contract_with_pool(
                pool_liters=400, actual_liters=600,
                contract_overrides={"min_concentration_pct": 40}
            )
        )

        resp = api.record_shipment(
            contract["id"],
            record_shipment_payload(volume_liters=500, concentration_pct=50),
            TEST_USERS["station_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COLLECTED_GLYCOL)

    def test_fulfilled_contract_rejects_further_shipments(self, api):
        """PRD §3.8: "When cumulative `delivered_liters` reach or exceed
        `contracted_min_liters`, the contract fulfills itself, moving from
        `ACTIVE` to `FULFILLED` and incrementing its `version`." And: "the
        contract must still be `ACTIVE` — shipments against a `FULFILLED`
        contract are rejected with `ERR_INVALID_STATE`."
        PRD §2.5: "Recycling revenue per shipment is the shipment volume
        multiplied by the contract's per-liter price, rounded half-up to
        integer cents."

        Design: Corner/errors/fulfilled_contract_rejects_further_shipments
        """
        station, permit, tank, pad, airline, request, operation, contract = (
            setup_recycling_contract_with_pool(
                pool_liters=400, actual_liters=600,
                contract_overrides={
                    "min_concentration_pct": 40,
                    "price_per_liter_cents": 12,
                    "contracted_min_liters": 300,
                }
            )
        )

        # First shipment: 350 L at 55% → fulfills the contract.
        resp = api.record_shipment(
            contract["id"],
            record_shipment_payload(volume_liters=350, concentration_pct=55),
            TEST_USERS["station_admin_headers"],
        )
        data = validate_success(resp)
        assert data["delivered_liters"] == 350
        assert data["last_shipment_revenue_cents"] == 4200
        assert data["status"] == "FULFILLED"

        # Second shipment rejected.
        resp = api.record_shipment(
            contract["id"],
            record_shipment_payload(volume_liters=10, concentration_pct=55),
            TEST_USERS["station_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
