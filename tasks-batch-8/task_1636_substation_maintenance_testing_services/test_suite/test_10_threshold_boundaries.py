"""Boundary precision (PRD §3.4, §3.7): one step across a threshold flips the
outcome — inclusive oil-ppm grading bounds and half-open reservation adjacency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_certified_technician,
    create_spare_reservation,
    create_spare_unit,
    create_test_event,
    setup_asset,
    submit_test_event,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestOilMoistureThresholdBoundary:
    def _setup(self) -> dict:
        base = setup_asset("POWER_TRANSFORMER", install_date="2020-01-01T00:00:00Z")
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        return {**base, "tech_headers": tech_headers}

    def test_reading_exactly_at_warn_threshold_is_marginal(self):
        """PRD §3.4: "For `OIL_MOISTURE`, the comparison is inclusive at both
        bounds: a `value_primary` at or above `oil_critical_ppm` grades `FAIL`;
        strictly below that but at or above `oil_warn_ppm` grades `MARGINAL`;
        below `oil_warn_ppm` grades `PASS`. A reading exactly equal to
        `oil_warn_ppm` is `MARGINAL`; exactly equal to `oil_critical_ppm` is
        `FAIL`."

        Design: Difficulty/boundary_precision_check/oil_moisture_threshold_boundary
        """
        ctx = self._setup()
        event = create_test_event(
            ctx["asset"]["id"], ctx["tech_headers"], "OIL_MOISTURE",
            value_primary=20, measured_at="2026-07-05T10:00:00Z",
        )
        submitted = submit_test_event(event["id"], ctx["tech_headers"])
        assert submitted["result"] == "MARGINAL"

    def test_reading_just_below_warn_threshold_is_pass(self):
        """PRD §3.4: "For `OIL_MOISTURE`, the comparison is inclusive at both
        bounds: a `value_primary` at or above `oil_critical_ppm` grades `FAIL`;
        strictly below that but at or above `oil_warn_ppm` grades `MARGINAL`;
        below `oil_warn_ppm` grades `PASS`. A reading exactly equal to
        `oil_warn_ppm` is `MARGINAL`; exactly equal to `oil_critical_ppm` is
        `FAIL`."

        Design: Difficulty/boundary_precision_check/oil_moisture_threshold_boundary
        """
        ctx = self._setup()
        event = create_test_event(
            ctx["asset"]["id"], ctx["tech_headers"], "OIL_MOISTURE",
            value_primary=19.99, measured_at="2026-07-05T11:00:00Z",
        )
        submitted = submit_test_event(event["id"], ctx["tech_headers"])
        assert submitted["result"] == "PASS"


class TestSpareReservationZeroGapBoundary:
    def _setup_unit_with_reservation(self) -> dict:
        unit = create_spare_unit(
            unit_type="SPARE_TRANSFORMER", rating_mva=25, voltage_class_kv=115,
            impedance_pct=6.5, home_location="Yard-A",
        )
        reservation = create_spare_reservation(
            "2026-09-10T10:00:00Z", "2026-09-10T14:00:00Z",
            spare_unit_id=unit["id"],
        )
        return {"unit": unit, "reservation": reservation}

    def test_back_to_back_reservation_at_end_boundary_succeeds(self):
        """PRD §3.7: "the new reservation must not overlap any existing
        `ACTIVE` reservation of the same unit under half-open semantics;
        adjacency, where one reservation's `end_ts` equals the next's
        `start_ts`, is permitted with zero buffer."

        Design: Difficulty/boundary_precision_check/spare_reservation_zero_gap_boundary
        """
        ctx = self._setup_unit_with_reservation()
        # Starts exactly at the existing reservation's end: zero-gap adjacency.
        payload = {
            "spare_unit_id": ctx["unit"]["id"],
            "unit_type": "SPARE_TRANSFORMER",
            "required_mva": 20,
            "required_voltage_kv": 115,
            "start_ts": "2026-09-10T14:00:00Z",
            "end_ts": "2026-09-10T18:00:00Z",
        }
        reservation = validate_success(api_client.create_spare_reservation(payload, COORD), 201)
        assert reservation["status"] == "ACTIVE"

    def test_one_second_earlier_start_overlaps_and_is_rejected(self):
        """PRD §3.7: "the new reservation must not overlap any existing
        `ACTIVE` reservation of the same unit under half-open semantics;
        adjacency, where one reservation's `end_ts` equals the next's
        `start_ts`, is permitted with zero buffer. An overlap is
        `ERR_SPARE_RESERVATION_CONFLICT` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/spare_reservation_zero_gap_boundary
        """
        ctx = self._setup_unit_with_reservation()
        payload = {
            "spare_unit_id": ctx["unit"]["id"],
            "unit_type": "SPARE_TRANSFORMER",
            "required_mva": 20,
            "required_voltage_kv": 115,
            "start_ts": "2026-09-10T13:59:59Z",
            "end_ts": "2026-09-10T15:00:00Z",
        }
        resp = api_client.create_spare_reservation(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_SPARE_RESERVATION_CONFLICT)
