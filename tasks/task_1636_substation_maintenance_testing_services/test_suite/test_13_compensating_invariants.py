"""Compensating invariants (PRD §3.2, §3.7): an action and its compensating
action leave the conserved quantity exactly at its pre-action value."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_outage_window,
    assert_money_equals,
    create_outage_window,
    create_spare_reservation,
    create_spare_unit,
    setup_asset,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestOutageApproveCancelHoursInvariant:
    def _setup_requested_8h_window(self) -> dict:
        base = setup_asset("POWER_TRANSFORMER", install_date="2020-01-01T00:00:00Z")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-09-20T08:00:00Z", "2026-09-20T16:00:00Z", purpose="Invariant probe",
        )
        return {**base, "window": window}

    def test_approve_adds_duration_hours(self):
        """PRD §3.2: "A successful approval transitions the window `REQUESTED →
        APPROVED`, stamps `approved_by` from the caller's `X-User-ID`, adds the
        window's `duration_hours` into the asset's `approved_outage_hours`, and
        increments the window's `version`."

        Design: Difficulty/compensating_invariant/outage_approve_cancel_hours_invariant
        """
        ctx = self._setup_requested_8h_window()
        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        assert_money_equals(asset["approved_outage_hours"], "0.00")
        approve_outage_window(ctx["window"]["id"], "ops-mgr-1")
        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        assert_money_equals(asset["approved_outage_hours"], "8.00")

    def test_cancel_restores_pre_approve_hours_exactly(self):
        """PRD §3.2: "Cancelling from `APPROVED` performs compensation: the
        window's `duration_hours` is subtracted from the asset's
        `approved_outage_hours`, and every linked `WorkOrder` still in `DRAFT`
        or `SCHEDULED` is transitioned to `CANCELLED` — with each such
        cancellation in turn returning its linked `Defect` from `WORK_ORDERED`
        to `OPEN`."

        Design: Difficulty/compensating_invariant/outage_approve_cancel_hours_invariant
        """
        ctx = self._setup_requested_8h_window()
        approve_outage_window(ctx["window"]["id"], "ops-mgr-1")
        cancelled = validate_success(
            api_client.cancel_outage_window(ctx["window"]["id"], COORD)
        )
        assert cancelled["status"] == "CANCELLED"
        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        # Compensation leaves zero drift relative to the pre-approve value.
        assert_money_equals(asset["approved_outage_hours"], "0.00")


class TestSpareReserveCancelCountInvariant:
    def _setup_unit(self) -> dict:
        unit = create_spare_unit(
            unit_type="SPARE_TRANSFORMER", rating_mva=25, voltage_class_kv=115,
            impedance_pct=6.5, home_location="Yard-C",
        )
        return {"unit": unit}

    def test_reserve_then_cancel_restores_unit_status(self):
        """PRD §3.7: "A successful reservation arrives `ACTIVE` and drives its
        unit from `AVAILABLE` to `RESERVED`."
        PRD §3.7: "Cancellation transitions the reservation `ACTIVE →
        CANCELLED` and recomputes the unit's status: `AVAILABLE` when no
        `ACTIVE` reservation remains on the unit, else `RESERVED`."

        Design: Difficulty/compensating_invariant/spare_reserve_cancel_count_invariant
        """
        ctx = self._setup_unit()
        assert ctx["unit"]["status"] == "AVAILABLE"
        reservation = create_spare_reservation(
            "2026-10-01T08:00:00Z", "2026-10-01T16:00:00Z",
            spare_unit_id=ctx["unit"]["id"],
        )
        unit = validate_success(api_client.get_spare_unit(ctx["unit"]["id"], OPS))
        assert unit["status"] == "RESERVED"
        cancelled = validate_success(
            api_client.cancel_spare_reservation(reservation["id"], COORD)
        )
        assert cancelled["status"] == "CANCELLED"
        unit = validate_success(api_client.get_spare_unit(ctx["unit"]["id"], OPS))
        assert unit["status"] == "AVAILABLE"

    def test_cancelled_reservation_history_preserved_with_zero_active(self):
        """PRD §3.7: "Cancellation transitions the reservation `ACTIVE →
        CANCELLED` and recomputes the unit's status: `AVAILABLE` when no
        `ACTIVE` reservation remains on the unit, else `RESERVED`."
        PRD §3.7: "it stays `RESERVED` while at least one `ACTIVE` reservation
        exists."

        Design: Difficulty/compensating_invariant/spare_reserve_cancel_count_invariant
        """
        ctx = self._setup_unit()
        reservation = create_spare_reservation(
            "2026-10-01T08:00:00Z", "2026-10-01T16:00:00Z",
            spare_unit_id=ctx["unit"]["id"],
        )
        validate_success(api_client.cancel_spare_reservation(reservation["id"], COORD))
        rows, meta = validate_paginated(
            api_client.list_spare_unit_reservations(ctx["unit"]["id"], OPS)
        )
        assert meta["total_count"] == 1, "cancelled reservation remains in history"
        assert rows[0]["id"] == reservation["id"]
        assert rows[0]["status"] == "CANCELLED"
        active = [row for row in rows if row["status"] == "ACTIVE"]
        assert len(active) == 0, "no ACTIVE reservation may remain after cancellation"
