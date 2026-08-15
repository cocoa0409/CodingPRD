"""Resource temporal overlap (PRD §3.2, §3.7): outage windows of one asset
carry a 24-hour buffer rule; spare reservations of one unit use pure half-open
overlap with zero buffer."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_outage_window,
    create_spare_reservation,
    create_spare_unit,
    setup_asset,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
OPS = TEST_USERS["ops_manager_headers"]


class TestOutageWindowBufferSemantics:
    def _setup_existing_window(self) -> dict:
        base = setup_asset("POWER_TRANSFORMER", install_date="2020-01-01T00:00:00Z")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-09-01T08:00:00Z", "2026-09-01T16:00:00Z", purpose="W1",
        )
        return {**base, "window": window}

    def test_adjacent_window_rejected_by_buffer_rule(self):
        """PRD §3.2: "Any overlap under half-open semantics, or a gap to the
        nearest such window of strictly less than 24 hours, is rejected with
        `ERR_OUTAGE_WINDOW_CONFLICT` (HTTP 409); a gap of exactly 24 hours is
        permitted."

        Design: Difficulty/resource_temporal_overlap/outage_window_buffer_semantics
        """
        ctx = self._setup_existing_window()
        # [16:00, next-day 08:00) does not geometrically overlap the existing
        # [08:00, 16:00) window, but the gap of 0 hours violates the buffer.
        resp = api_client.create_outage_window(
            {
                "substation_id": ctx["substation"]["id"],
                "asset_id": ctx["asset"]["id"],
                "start_ts": "2026-09-01T16:00:00Z",
                "end_ts": "2026-09-02T08:00:00Z",
                "purpose": "W2 adjacent",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_OUTAGE_WINDOW_CONFLICT, 409)

    def test_exactly_24h_gap_is_permitted(self):
        """PRD §3.2: "Any overlap under half-open semantics, or a gap to the
        nearest such window of strictly less than 24 hours, is rejected with
        `ERR_OUTAGE_WINDOW_CONFLICT` (HTTP 409); a gap of exactly 24 hours is
        permitted."

        Design: Difficulty/resource_temporal_overlap/outage_window_buffer_semantics
        """
        ctx = self._setup_existing_window()
        # Starts exactly 24 hours after the existing window's end.
        window = validate_success(
            api_client.create_outage_window(
                {
                    "substation_id": ctx["substation"]["id"],
                    "asset_id": ctx["asset"]["id"],
                    "start_ts": "2026-09-02T16:00:00Z",
                    "end_ts": "2026-09-03T00:00:00Z",
                    "purpose": "W3 24h gap",
                },
                COORD,
            ),
            201,
        )
        assert window["status"] == "REQUESTED"


class TestSpareReservationHalfOpenOverlap:
    def _setup_reserved_unit(self) -> dict:
        unit = create_spare_unit(
            unit_type="MOBILE_SUBSTATION", rating_mva=30, voltage_class_kv=115,
            impedance_pct=8.0, home_location="Depot-9",
        )
        reservation = create_spare_reservation(
            "2026-09-10T10:00:00Z", "2026-09-10T14:00:00Z",
            spare_unit_id=unit["id"], unit_type="MOBILE_SUBSTATION", required_mva=25,
        )
        return {"unit": unit, "reservation": reservation}

    def test_contained_interval_rejected(self):
        """PRD §3.7: "the new reservation must not overlap any existing
        `ACTIVE` reservation of the same unit under half-open semantics;
        adjacency, where one reservation's `end_ts` equals the next's
        `start_ts`, is permitted with zero buffer. An overlap is
        `ERR_SPARE_RESERVATION_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/spare_reservation_halfopen_overlap
        """
        ctx = self._setup_reserved_unit()
        # [12:00, 13:00) is fully contained in the existing [10:00, 14:00).
        resp = api_client.create_spare_reservation(
            {
                "spare_unit_id": ctx["unit"]["id"],
                "unit_type": "MOBILE_SUBSTATION",
                "required_mva": 25,
                "required_voltage_kv": 115,
                "start_ts": "2026-09-10T12:00:00Z",
                "end_ts": "2026-09-10T13:00:00Z",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_SPARE_RESERVATION_CONFLICT, 409)

    def test_zero_gap_successor_accepted_and_unit_stays_reserved(self):
        """PRD §3.7: "adjacency, where one reservation's `end_ts` equals the
        next's `start_ts`, is permitted with zero buffer."
        PRD §3.7: "A unit that already has an `ACTIVE` reservation may accept
        additional non-overlapping reservations; it stays `RESERVED` while at
        least one `ACTIVE` reservation exists."

        Design: Difficulty/resource_temporal_overlap/spare_reservation_halfopen_overlap
        """
        ctx = self._setup_reserved_unit()
        # Back-to-back at the existing reservation's end: no buffer required.
        reservation2 = validate_success(
            api_client.create_spare_reservation(
                {
                    "spare_unit_id": ctx["unit"]["id"],
                    "unit_type": "MOBILE_SUBSTATION",
                    "required_mva": 25,
                    "required_voltage_kv": 115,
                    "start_ts": "2026-09-10T14:00:00Z",
                    "end_ts": "2026-09-10T18:00:00Z",
                },
                COORD,
            ),
            201,
        )
        assert reservation2["status"] == "ACTIVE"
        unit = validate_success(api_client.get_spare_unit(ctx["unit"]["id"], OPS))
        assert unit["status"] == "RESERVED"
