"""Bike registration, on-/off-shelf transitions, recall lifecycle.

Covers PRD §3.2 (bikes from warehouse to street) and §3.7 (recall and
release-recall).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_bike,
    create_bike,
    create_bike_payload,
    create_region,
    create_workorder,
    get_bike,
    get_region,
    recall_bike,
    release_recall_bike,
    setup_basic_ride_scenario,
    setup_region_with_bikes,
    shelf_bike_off,
    shelf_bike_on,
    shelf_payload,
    start_ride,
    validate_error,
    validate_success,
    ADMIN,
    OPERATOR,
)


class TestBikeRegistration:
    def test_new_bike_initial_state(self, api):
        """PRD §3.2: 'New bikes start with shelf_state of OFF_SHELF,
        region_id null, status of AVAILABLE ..., lock_state of LOCKED,
        and fault_categories an empty array.'"""
        bike = create_bike(model="STANDARD")
        assert_bike(bike)
        assert bike["shelf_state"] == "OFF_SHELF", (
            "PRD §3.2: shelf_state starts at OFF_SHELF"
        )
        assert bike["region_id"] is None, (
            "PRD §3.2: region_id null on registration"
        )
        assert bike["status"] == "AVAILABLE"
        assert bike["lock_state"] == "LOCKED"
        assert bike["fault_categories"] == []

    def test_standard_bike_battery_is_100(self, api):
        """PRD §3.2: 'A standard bike's battery_pct is always 100.'"""
        bike = create_bike(model="STANDARD")
        assert bike["battery_pct"] == 100, (
            f"PRD §3.2: STANDARD bike battery_pct must be 100, "
            f"got {bike['battery_pct']}"
        )

    def test_battery_pct_must_be_in_range_0_to_100(self, api, admin_headers):
        """PRD §3.2: 'battery_pct must lie in the closed range 0 to
        100.'"""
        resp = api.create_bike(
            create_bike_payload(model="E_BIKE", battery_pct=101),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


class TestShelfTransitions:
    def test_on_shelf_sets_region_status_and_recomputes_counts(self, api):
        """PRD §3.2: 'On success the bike's shelf_state becomes ON_SHELF,
        status is set to AVAILABLE, region_id is set to the path-supplied
        region, both deployed_count and available_count are recomputed.'"""
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        bike = create_bike(model="STANDARD")
        shelf_bike_on(region["id"], bike["id"])
        # Refetch
        bike = get_bike(bike["id"])
        region = get_region(region["id"])
        assert bike["shelf_state"] == "ON_SHELF"
        assert bike["status"] == "AVAILABLE"
        assert bike["region_id"] == region["id"]
        assert region["deployed_count"] == 1
        assert region["available_count"] == 1

    def test_on_shelf_exceeds_quota_rejected(self, api, admin_headers):
        """PRD §3.2: 'The region's deployed_count plus one must not exceed
        deployment_quota — otherwise ERR_QUOTA_EXCEEDED.'"""
        region, bikes = setup_region_with_bikes(
            deployment_quota=1, low_density_threshold=0,
            high_density_threshold=999, num_bikes=1,
        )
        # One more bike for the boundary attempt.
        extra = create_bike(model="STANDARD")
        resp = api.shelf_bike(
            region["id"], extra["id"], shelf_payload(action="ON"), OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_QUOTA_EXCEEDED.value, 409)

    def test_on_shelf_blocked_by_open_workorder(self, api, admin_headers):
        """PRD §3.2: 'The bike must not have any WorkOrder whose status
        is OPEN or ASSIGNED — otherwise ERR_BIKE_HAS_OPEN_WORKORDER.'"""
        # On-shelf a bike, open a fault on it, take it off-shelf, then
        # try to put it back on-shelf with the OPEN WorkOrder still around.
        region, bikes = setup_region_with_bikes(num_bikes=1)
        bike = bikes[0]
        # Open a fault → WorkOrder OPEN, Bike status=FAULT.
        api.fault_report_bike(
            bike["id"], {"category": "FLAT_TIRE"}, OPERATOR,
        )
        # Bike is now FAULT — can't take off-shelf if IN_USE; but FAULT is
        # not IN_USE so OFF works.
        # Per PRD §3.2 OFF requires !IN_USE — but the off-shelf preserves
        # the WorkOrder. Push bike OFF_SHELF then try ON_SHELF again.
        # Some implementations may bar OFF when fault present; tolerate by
        # using a freshly-registered bike with an explicit WorkOrder.
        new_bike = create_bike(model="STANDARD")
        create_workorder(bike_id=new_bike["id"], cause="USER_REPORT",
                         category="FLAT_TIRE", sla_minutes=240)
        # Now new_bike is OFF_SHELF with an OPEN WorkOrder; try to bring
        # it on-shelf into the region.
        resp = api.shelf_bike(
            region["id"], new_bike["id"], shelf_payload(action="ON"),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_HAS_OPEN_WORKORDER.value, 409)

    def test_on_shelf_e_bike_low_battery_rejected(
        self, api, admin_headers,
    ):
        """PRD §3.2: 'And for an E_BIKE, battery_pct must be at least 20
        — otherwise ERR_BATTERY_TOO_LOW.'"""
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        bike = create_bike(model="E_BIKE", battery_pct=19)
        resp = api.shelf_bike(
            region["id"], bike["id"], shelf_payload(action="ON"), OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_BATTERY_TOO_LOW.value, 409)

    def test_on_shelf_e_bike_at_boundary_succeeds(self, api):
        """PRD §3.2: 'battery_pct must be at least 20.' Boundary case:
        battery_pct == 20 succeeds (inclusive >=)."""
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        bike = create_bike(model="E_BIKE", battery_pct=20)
        shelf_bike_on(region["id"], bike["id"])
        bike = get_bike(bike["id"])
        assert bike["shelf_state"] == "ON_SHELF"

    def test_off_shelf_in_use_rejected(self, api):
        """PRD §3.2: 'Taking a bike off-shelf — the same shelf endpoint
        with the opposite action — is only legal when the bike is not
        currently IN_USE; otherwise ERR_BIKE_IN_USE.'"""
        ctx = setup_basic_ride_scenario()
        # Start a ride to put bike in IN_USE
        start_ride(ctx["rider"], ctx["bike"])
        resp = api.shelf_bike(
            ctx["region"]["id"], ctx["bike"]["id"],
            shelf_payload(action="OFF"),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_IN_USE.value, 409)


class TestRecallRelease:
    def test_recall_flips_status_to_recall(self, api):
        """PRD §3.7: 'On success the bike's status is set to RECALL
        (locking it out of new rides), the region's available_count
        decrements.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        recall_bike(bikes[0]["id"])
        bike = get_bike(bikes[0]["id"])
        region = get_region(region["id"])
        assert bike["status"] == "RECALL"
        assert region["available_count"] == 0, (
            "PRD §3.7: available_count decrements on recall"
        )

    def test_recall_requires_available_status(self, api, admin_headers):
        """PRD §3.7: 'Recalling a bike requires its status to be
        AVAILABLE (otherwise ERR_BIKE_NOT_AVAILABLE).'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        recall_bike(bikes[0]["id"])
        # Already RECALL — a second recall is rejected.
        resp = api.recall_bike(bikes[0]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409)

    def test_release_recall_requires_recall_status(self, api, admin_headers):
        """PRD §3.7: 'the bike's status must be RECALL (otherwise
        ERR_BIKE_NOT_IN_RECALL).'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        resp = api.release_recall_bike(bikes[0]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BIKE_NOT_IN_RECALL.value, 409)

    def test_release_recall_returns_to_available(self, api):
        """PRD §3.7: 'On success the bike returns to AVAILABLE.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        recall_bike(bikes[0]["id"])
        release_recall_bike(bikes[0]["id"])
        bike = get_bike(bikes[0]["id"])
        region = get_region(region["id"])
        assert bike["status"] == "AVAILABLE"
        assert region["available_count"] == 1
