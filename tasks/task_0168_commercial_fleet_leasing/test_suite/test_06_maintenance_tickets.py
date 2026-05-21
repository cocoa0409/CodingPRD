"""Maintenance tickets — PRD §3.5.

Covers: ticket lifecycle (OPEN → IN_SHOP → CLOSED, OPEN → CANCELLED),
vehicle_status side-effects, and the actual_cents > 0 closure
precondition (the §1.8 difficulty-design boundary).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_maintenance_ticket,
    cancel_maintenance_ticket,
    close_maintenance_ticket,
    close_maintenance_ticket_payload,
    create_maintenance_ticket_payload,
    get_vehicle,
    open_maintenance_ticket,
    setup_active_lease,
    start_maintenance_ticket,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestMaintenanceLifecycle:

    def test_open_ticket_stamps_opened_at_odometer(self, api):
        """PRD §3.5: "At creation, the ticket records the vehicle's
        then-current `odometer_current_miles` into its own
        `opened_at_odometer` field as a permanent stamp. The ticket
        is born in `OPEN`."

        Claim: a fresh ticket has ticket_status=OPEN and
        opened_at_odometer equal to the vehicle's
        odometer_current_miles at creation time.
        """
        from test_helpers import (
            create_vehicle, post_telematics_event,
        )
        vehicle = create_vehicle(odometer_baseline_miles=10_000)
        post_telematics_event(
            vehicle_id=vehicle["id"],
            event_ts="2026-03-01T00:00:00.000Z",
            odometer_reading=15_000,
        )
        resp = api.create_maintenance_ticket(
            vehicle["id"],
            create_maintenance_ticket_payload(
                ticket_kind="PM", estimate_cents=2_500,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_maintenance_ticket(data)
        assert data["ticket_status"] == "OPEN"
        assert data["opened_at_odometer"] == 15_000, (
            f"opened_at_odometer must stamp the vehicle's odometer "
            f"at create time (15000), got {data['opened_at_odometer']!r}"
        )

    def test_start_ticket_flips_vehicle_to_in_shop(self, api):
        """PRD §3.5: "A `VendorOps` user starts the work, advancing
        the ticket from `OPEN` to `IN_SHOP` (i.e. the ticket's
        `ticket_status` field moves from `OPEN` to `IN_SHOP`). The
        starting precondition is that the ticket is `OPEN` and the
        vehicle's `vehicle_status` is either `ALLOCATED` or
        `GROUNDED` ... Starting the ticket flips the vehicle's
        `vehicle_status` to `IN_SHOP`."

        Claim: start flips ticket to IN_SHOP and vehicle to IN_SHOP.
        """
        _, vehicle, _ = setup_active_lease()
        t = open_maintenance_ticket(
            vehicle_id=vehicle["id"], estimate_cents=5_000,
        )
        resp = api.start_maintenance_ticket(
            t["id"], TEST_USERS["vendor_ops_headers"],
        )
        data = validate_success(resp)
        assert data["ticket_status"] == "IN_SHOP"
        v = get_vehicle(vehicle["id"])
        assert v["vehicle_status"] == "IN_SHOP"

    def test_close_with_zero_actual_cents_rejected(self, api):
        """PRD §3.5: "closure requires `actual_cents` to be strictly
        greater than zero (a value of zero is rejected with
        `ERR_ACTUAL_COST_REQUIRED`)."

        Claim: closing with actual_cents == 0 returns
        ERR_ACTUAL_COST_REQUIRED.
        """
        _, vehicle, _ = setup_active_lease()
        t = open_maintenance_ticket(
            vehicle_id=vehicle["id"], estimate_cents=5_000,
        )
        start_maintenance_ticket(t["id"])
        resp = api.close_maintenance_ticket(
            t["id"],
            close_maintenance_ticket_payload(actual_cents=0),
            TEST_USERS["vendor_ops_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ACTUAL_COST_REQUIRED.value)

    def test_close_with_one_cent_succeeds(self, api):
        """PRD §3.5: "closure requires `actual_cents` to be strictly
        greater than zero."

        Claim: actual_cents == 1 succeeds and moves ticket to CLOSED.
        """
        _, vehicle, _ = setup_active_lease()
        t = open_maintenance_ticket(
            vehicle_id=vehicle["id"], estimate_cents=5_000,
        )
        start_maintenance_ticket(t["id"])
        resp = api.close_maintenance_ticket(
            t["id"],
            close_maintenance_ticket_payload(actual_cents=1),
            TEST_USERS["vendor_ops_headers"],
        )
        data = validate_success(resp)
        assert data["ticket_status"] == "CLOSED"
        assert data["actual_cents"] == 1

    def test_close_restores_vehicle_status_to_allocated(self, api):
        """PRD §3.5: "On closure, the vehicle is restored to its
        prior workflow state — `ALLOCATED` if the vehicle is
        currently tied to a `current_lease_id`, otherwise
        `GROUNDED`."

        Claim: closing a ticket on a vehicle with a current_lease_id
        restores it to ALLOCATED (not IN_SHOP, not GROUNDED).
        """
        _, vehicle, _ = setup_active_lease()
        t = open_maintenance_ticket(
            vehicle_id=vehicle["id"], estimate_cents=5_000,
        )
        start_maintenance_ticket(t["id"])
        close_maintenance_ticket(t["id"], actual_cents=4_500)
        v = get_vehicle(vehicle["id"])
        assert v["vehicle_status"] == "ALLOCATED", (
            f"close must restore vehicle to ALLOCATED when it has a "
            f"current_lease_id, got {v['vehicle_status']!r}"
        )

    def test_cancel_open_ticket_succeeds(self, api):
        """PRD §3.5: "A `FleetManager` may also cancel a ticket that
        is still `OPEN`, sending it to `CANCELLED` with no further
        side effects; tickets that have already entered `IN_SHOP` may
        no longer be cancelled and must be closed instead."

        Claim: cancelling an OPEN ticket succeeds.
        """
        _, vehicle, _ = setup_active_lease()
        t = open_maintenance_ticket(
            vehicle_id=vehicle["id"], estimate_cents=5_000,
        )
        resp = api.cancel_maintenance_ticket(
            t["id"], TEST_USERS["fleet_manager_headers"],
        )
        data = validate_success(resp)
        assert data["ticket_status"] == "CANCELLED"

    def test_cancel_in_shop_ticket_rejected(self, api):
        """PRD §3.5: "tickets that have already entered `IN_SHOP`
        may no longer be cancelled and must be closed instead."

        Claim: attempting to cancel an IN_SHOP ticket returns
        ERR_INVALID_STATE.
        """
        _, vehicle, _ = setup_active_lease()
        t = open_maintenance_ticket(
            vehicle_id=vehicle["id"], estimate_cents=5_000,
        )
        start_maintenance_ticket(t["id"])
        resp = api.cancel_maintenance_ticket(
            t["id"], TEST_USERS["fleet_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
