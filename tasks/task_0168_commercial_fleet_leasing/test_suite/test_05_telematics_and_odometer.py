"""Telematics ingest and odometer reconciliation — PRD §3.4, §2.10.

Covers: ACCEPTED vs REJECTED_STALE classification, odometer
advancement, and that rejected events still return 201.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_telematics_event,
    api_client,
    create_telematics_event_payload,
    create_vehicle,
    get_vehicle,
    setup_active_lease,
    TEST_USERS,
    validate_success,
)


class TestTelematicsReconciliation:

    def test_accepted_event_advances_odometer(self, api):
        """PRD §3.4: "if `odometer_reading` is strictly less than the
        vehicle's existing `odometer_current_miles`, the event is
        recorded with `ingest_status` of `REJECTED_STALE` and the
        vehicle's odometer is not advanced; otherwise the event is
        recorded with `ingest_status` of `ACCEPTED` and the vehicle's
        `odometer_current_miles` is set to the new reading."

        Claim: an event whose odometer_reading exceeds the vehicle's
        current is ACCEPTED and advances the vehicle's
        odometer_current_miles.
        """
        vehicle = create_vehicle(odometer_baseline_miles=1000)
        h = TEST_USERS["vendor_ops_headers"]
        resp = api.create_telematics_event(
            vehicle["id"],
            create_telematics_event_payload(
                event_ts="2026-03-15T12:00:00.000Z",
                odometer_reading=2500,
            ),
            h,
        )
        ev = validate_success(resp, expected_status=201)
        assert_telematics_event(ev)
        assert ev["ingest_status"] == "ACCEPTED"
        v = get_vehicle(vehicle["id"])
        assert v["odometer_current_miles"] == 2500, (
            f"odometer_current_miles must advance to 2500, "
            f"got {v['odometer_current_miles']!r}"
        )

    def test_rejected_stale_event_returns_201_and_does_not_advance(
        self, api,
    ):
        """PRD §3.4: "Both events return 201 — the rejected-stale
        outcome is a stored record, not an HTTP error — but only
        accepted events feed overage and collision math downstream."

        Claim: a stale event (odometer < current) is recorded with
        REJECTED_STALE, returns 201, and the vehicle's odometer is
        NOT advanced.
        """
        vehicle = create_vehicle(odometer_baseline_miles=2000)
        h = TEST_USERS["vendor_ops_headers"]
        # First event advances to 5000.
        ev1 = api.create_telematics_event(
            vehicle["id"],
            create_telematics_event_payload(
                event_ts="2026-03-10T00:00:00.000Z",
                odometer_reading=5000,
            ),
            h,
        )
        validate_success(ev1, expected_status=201)
        # Second event with odometer < 5000 is REJECTED_STALE.
        resp = api.create_telematics_event(
            vehicle["id"],
            create_telematics_event_payload(
                event_ts="2026-03-11T00:00:00.000Z",
                odometer_reading=4500,
            ),
            h,
        )
        ev2 = validate_success(resp, expected_status=201)
        assert ev2["ingest_status"] == "REJECTED_STALE"
        v = get_vehicle(vehicle["id"])
        assert v["odometer_current_miles"] == 5000, (
            f"odometer_current_miles must NOT advance on stale event; "
            f"expected 5000, got {v['odometer_current_miles']!r}"
        )

    def test_equal_odometer_reading_accepted(self, api):
        """PRD §3.4: "if `odometer_reading` is strictly less than the
        vehicle's existing `odometer_current_miles`, the event is
        recorded with `ingest_status` of `REJECTED_STALE`."

        Claim: an event whose odometer_reading equals the vehicle's
        current is ACCEPTED (boundary is "strictly less than").
        """
        vehicle = create_vehicle(odometer_baseline_miles=3000)
        h = TEST_USERS["vendor_ops_headers"]
        # Advance to 7000.
        validate_success(api.create_telematics_event(
            vehicle["id"],
            create_telematics_event_payload(
                event_ts="2026-03-10T00:00:00.000Z",
                odometer_reading=7000,
            ),
            h,
        ), expected_status=201)
        # Equal reading 7000 — boundary is "strictly less than",
        # so equality is ACCEPTED.
        resp = api.create_telematics_event(
            vehicle["id"],
            create_telematics_event_payload(
                event_ts="2026-03-11T00:00:00.000Z",
                odometer_reading=7000,
            ),
            h,
        )
        ev = validate_success(resp, expected_status=201)
        assert ev["ingest_status"] == "ACCEPTED", (
            f"equal odometer must be ACCEPTED (boundary 'strictly "
            f"less than'), got {ev['ingest_status']!r}"
        )

    def test_telematics_event_is_append_only(self, api):
        """PRD §2.4: "Two entities — `FuelCardTransaction` and
        `TelematicsEvent` — are immutable append-only records: they
        carry `id` and `created_at` only, and both `updated_at` and
        `version` are absent because there is no in-place edit path
        that could refresh them."

        Claim: a TelematicsEvent response omits updated_at / version.
        """
        vehicle = create_vehicle()
        resp = api.create_telematics_event(
            vehicle["id"],
            create_telematics_event_payload(
                event_ts="2026-03-15T12:00:00.000Z",
                odometer_reading=100,
            ),
            TEST_USERS["vendor_ops_headers"],
        )
        ev = validate_success(resp, expected_status=201)
        assert "updated_at" not in ev, (
            f"TelematicsEvent must omit updated_at, "
            f"got {ev.get('updated_at')!r}"
        )
        assert "version" not in ev, (
            f"TelematicsEvent must omit version, "
            f"got {ev.get('version')!r}"
        )
