"""Fleet creation, configuration, and virtual-clock semantics.

PRD section 2.4 governs the common fields and virtual clock; section
3.8 governs the charging-threshold constraints; section 2.5 governs
optimistic concurrency on version.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FLEET_INITIAL_CLOCK,
    TEST_USERS,
    advance_clock,
    advance_clock_payload,
    api_client,
    assert_fleet,
    create_fleet,
    create_fleet_payload,
    get_fleet,
    validate_error,
    validate_success,
)


class TestFleetCreation:
    def test_new_fleet_clock_initialised_to_epoch(self, fleet_admin_headers):
        """PRD section 2.4: 'A newly created fleet has its clock_now
        initialised to 1970-01-01T00:00:00.000Z.'

        Claim: a freshly created fleet has clock_now ==
        '1970-01-01T00:00:00.000Z'.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        assert_fleet(fleet)
        assert fleet["clock_now"] == FLEET_INITIAL_CLOCK, (
            f"Expected clock_now={FLEET_INITIAL_CLOCK}, got {fleet['clock_now']!r}"
        )

    def test_fleet_version_starts_at_one(self, fleet_admin_headers):
        """PRD section 2.4: 'version is an integer that starts at 1 on
        creation and is incremented by 1 on every successful mutation.'

        Claim: new fleet version == 1.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        assert fleet["version"] == 1, (
            f"Expected version=1, got {fleet['version']!r}"
        )

    def test_fleet_defaults_applied(self, fleet_admin_headers):
        """PRD section 3.8: 'charging_low_threshold_pct defaults to 20,
        charging_opportunity_pct defaults to 60 and must be strictly
        greater than charging_low_threshold_pct, and charging_full_pct
        defaults to 95 and must be strictly greater than
        charging_opportunity_pct.'

        Claim: fleet without overrides applies these defaults.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        assert fleet["charging_low_threshold_pct"] == 20
        assert fleet["charging_opportunity_pct"] == 60
        assert fleet["charging_full_pct"] == 95


class TestVirtualClock:
    def test_advance_clock_moves_clock_forward(self, fleet_admin_headers, operator_headers):
        """PRD section 3.10: 'During the advance, in order, the system:
        increases Fleet.clock_now by delta_seconds...'

        Claim: advance_clock with delta_seconds=10 moves clock_now to
        1970-01-01T00:00:10.000Z.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        advance_clock(fleet["id"], 10, headers=operator_headers)
        refreshed = get_fleet(fleet["id"], headers=operator_headers)
        assert refreshed["clock_now"] == "1970-01-01T00:00:10.000Z", (
            f"Expected clock_now=1970-01-01T00:00:10.000Z, got {refreshed['clock_now']!r}"
        )

    def test_advance_clock_with_delta_one_succeeds(
        self, fleet_admin_headers, operator_headers
    ):
        """PRD section 2.4: 'delta_seconds must be at least 1 and the
        resulting clock_now must be strictly greater than the current
        clock_now.'

        Claim: delta_seconds=1 is accepted (boundary X=1 succeeds).
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        resp = api_client.advance_clock(
            fleet["id"], advance_clock_payload(delta_seconds=1), operator_headers
        )
        validate_success(resp, expected_status=200)

    def test_advance_clock_with_delta_zero_rejected(
        self, fleet_admin_headers, operator_headers
    ):
        """PRD section 2.4: 'delta_seconds must be at least 1 and the
        resulting clock_now must be strictly greater than the current
        clock_now. A request that violates either condition is rejected
        with ERR_CLOCK_BACKWARDS.'

        Claim: delta_seconds=0 -> ERR_CLOCK_BACKWARDS (boundary X=0 fails).
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        resp = api_client.advance_clock(
            fleet["id"], advance_clock_payload(delta_seconds=0), operator_headers
        )
        validate_error(resp, ApiErrorId.ERR_CLOCK_BACKWARDS.value)


class TestVersionIncrement:
    def test_clock_advance_increments_fleet_version(
        self, fleet_admin_headers, operator_headers
    ):
        """PRD section 2.4: 'version ... is incremented by 1 on every
        successful mutation.' and PRD section 2.8: 'Every transition
        that mutates a resource bumps that resource's version by 1 and
        refreshes its updated_at to the current Fleet.clock_now.'

        Claim: a successful :advance_clock bumps Fleet.version by 1.
        """
        fleet = create_fleet(headers=fleet_admin_headers)
        v_before = fleet["version"]
        advance_clock(fleet["id"], 5, headers=operator_headers)
        refreshed = get_fleet(fleet["id"], headers=operator_headers)
        assert refreshed["version"] == v_before + 1, (
            f"Expected version={v_before + 1}, got {refreshed['version']}"
        )
