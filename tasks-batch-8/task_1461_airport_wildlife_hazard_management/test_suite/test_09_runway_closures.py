"""Runway closures: buffered half-open overlap semantics and the CRITICAL
release gate."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_airport,
    create_species,
    create_biologist,
    create_atc_controller,
    setup_airport_with_biologists,
    create_requested_closure,
    authorize_closure,
    create_draft_strike,
    force_airport_hazard,
    make_biologist_headers,
    make_atc_controller_headers,
    ApiErrorId,
)


class TestBufferedHalfOpenOverlap:
    """An AUTHORIZED closure's end is padded by fifteen minutes for conflict
    checks; adjacent-after-buffer is allowed."""

    def _setup_with_authorized_closure(self, icao_code):
        set_clock()
        airport = create_airport(icao_code=icao_code)
        b1 = create_biologist(airport["id"], is_senior=True,
                              full_name="B One", certification_id="CERT-1401")
        c1 = create_atc_controller(airport["id"], facility_id=f"TWR-{icao_code[1:]}")
        rc1 = create_requested_closure(
            airport["id"], b1, runway_designator="09L",
            closure_start="2026-08-01T09:00:00Z",
            closure_end="2026-08-01T10:15:00Z",
        )
        authorize_closure(rc1["id"], c1)
        return airport, b1, c1, rc1

    def test_closure_overlapping_buffered_end_conflicts(self, api):
        """PRD §3.5: "two closures on the same runway conflict when one's
        start precedes the other's end and vice versa, with the further rule
        that every `AUTHORIZED` or `ACTIVE` closure's end is padded by a
        fifteen-minute safety buffer for conflict-check purposes only, and
        adjacent endpoints without overlap do not conflict. A conflicting
        request is rejected with `ERR_CLOSURE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/runway_closure_buffered_half_open_overlap
        """
        airport, b1, c1, rc1 = self._setup_with_authorized_closure("KOOO")
        # Existing AUTHORIZED 09:00 -> 10:15, buffered end 10:30.
        # New closure 10:00 -> 12:00 starts before the buffered end.
        res = api.create_runway_closure(
            {
                "airport_id": airport["id"],
                "runway_designator": "09L",
                "requested_by_biologist_id": b1["id"],
                "closure_start": "2026-08-01T10:00:00Z",
                "closure_end": "2026-08-01T12:00:00Z",
                "reason": "STRIKE_RESPONSE",
            },
            make_biologist_headers(b1["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CLOSURE_CONFLICT.value, expected_status=409)

    def test_closure_adjacent_after_buffer_accepted(self, api):
        """PRD §3.5: "two closures on the same runway conflict when one's
        start precedes the other's end and vice versa, with the further rule
        that every `AUTHORIZED` or `ACTIVE` closure's end is padded by a
        fifteen-minute safety buffer for conflict-check purposes only, and
        adjacent endpoints without overlap do not conflict."

        Design: Difficulty/resource_temporal_overlap/runway_closure_buffered_half_open_overlap
        """
        airport, b1, c1, rc1 = self._setup_with_authorized_closure("KOOP")
        # Starts exactly at the buffered end (10:15 + 15 min = 10:30).
        rc3 = validate_success(
            api.create_runway_closure(
                {
                    "airport_id": airport["id"],
                    "runway_designator": "09L",
                    "requested_by_biologist_id": b1["id"],
                    "closure_start": "2026-08-01T10:30:00Z",
                    "closure_end": "2026-08-01T12:00:00Z",
                    "reason": "STRIKE_RESPONSE",
                },
                make_biologist_headers(b1["id"]),
            ),
            201,
        )
        assert rc3["status"] == "REQUESTED"


class TestRunwayReleaseHazardGate:
    """Release of an ACTIVE closure is blocked while the airport is CRITICAL."""

    def _setup_active_closure(self, api, icao_code):
        set_clock()
        airport, b1, b2, b1h, b2h = setup_airport_with_biologists(
            icao_code=icao_code, cert_senior=f"CERT-{icao_code[1:]}1",
            cert_junior=f"CERT-{icao_code[1:]}2",
        )
        sp = create_species(
            common_name="Ring-billed Gull", scientific_name="Larus delawarensis",
            guild="GULL", risk_tier="MEDIUM", body_mass_g=550,
            is_protected_federally=True,
        )
        c1 = create_atc_controller(airport["id"], facility_id=f"TWR-{icao_code[1:]}")
        rc = create_requested_closure(
            airport["id"], b1, runway_designator="09L",
            closure_start="2026-08-01T00:00:00Z",
            closure_end="2026-08-01T02:00:00Z",
        )
        authorize_closure(rc["id"], c1)
        # Clock reaching closure_start moves AUTHORIZED -> ACTIVE.
        set_clock("2026-08-01T00:30:00Z")
        rc_active = validate_success(
            api.get_runway_closure(rc["id"], make_atc_controller_headers(c1["id"])),
            200,
        )
        assert rc_active["status"] == "ACTIVE"
        return airport, b1, b2, c1, sp, rc

    def test_release_blocked_when_airport_critical(self, api):
        """PRD §2.8: "A `CRITICAL` posture is a hard stop on four operations
        across the system: submitting a new strike report from `DRAFT` to
        `SUBMITTED`, starting work on an approved mitigation action,
        publishing an approved annual plan, and releasing an active runway
        closure back to operations. All four reject with
        `ERR_HAZARD_CRITICAL_BLOCK` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/runway_release_blocked_by_airport_hazard_critical
        """
        airport, b1, b2, c1, sp, rc = self._setup_active_closure(api, "KNNN")
        force_airport_hazard(airport["id"], b2, b1, sp["id"], "CRITICAL")

        res = api.release_runway_closure(rc["id"], make_atc_controller_headers(c1["id"]))
        validate_error(res, ApiErrorId.ERR_HAZARD_CRITICAL_BLOCK.value, expected_status=409)

        rc_after = validate_success(
            api.get_runway_closure(rc["id"], make_atc_controller_headers(c1["id"])),
            200,
        )
        assert rc_after["status"] == "ACTIVE"

    def test_release_allowed_when_airport_high(self, api):
        """PRD §3.5: "Release moves `ACTIVE → RELEASED`, must be performed by
        a controller at the same airport, and is blocked while the airport is
        at `CRITICAL` hazard; release stamps `actual_released_at` with the
        current time."

        Design: Difficulty/cross_entity_state_dependency/runway_release_blocked_by_airport_hazard_critical
        """
        airport, b1, b2, c1, sp, rc = self._setup_active_closure(api, "KNNO")
        force_airport_hazard(airport["id"], b2, b1, sp["id"], "HIGH")

        released = validate_success(
            api.release_runway_closure(rc["id"], make_atc_controller_headers(c1["id"])),
            200,
        )
        assert released["status"] == "RELEASED"
        assert released["actual_released_at"], (
            "release must stamp actual_released_at with the current time"
        )
