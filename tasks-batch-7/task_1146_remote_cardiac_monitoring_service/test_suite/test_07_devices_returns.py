"""Device refurbishment buffer, fleet conservation, and shipment terminal
lockdown (PRD §2.10, §3.2, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_iso_prefix,
    create_enrollment_payload,
    create_order_payload,
    make_physician_headers,
    read_device,
    register_patient,
    run_sweep,
    set_clock,
    setup_open_order,
    setup_returned_device,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["enrollment_coordinator_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]


def _event_fleet_count(api) -> int:
    _, meta = validate_paginated(api.list_devices(COORD, params={"model": "EVENT"}))
    return meta["total_count"]


class TestRefurbishmentBuffer:
    def _setup_refurbishing_device_and_second_order(self, api):
        """First episode returned at 2026-05-10T12:00:00Z (device REFURBISHING,
        due 2026-05-12T12:00:00Z); a second patient with an OPEN EVENT order."""
        ctx1 = setup_returned_device(
            prescribed_days=7, return_clock="2026-05-10T12:00:00Z"
        )
        patient2 = register_patient()
        order2 = validate_success(
            api.create_order(
                create_order_payload(patient2["id"], prescribed_days=7),
                make_physician_headers(ctx1["physician"]["id"]),
            ),
            201,
        )
        return ctx1, order2

    def test_reservation_inside_buffer_rejected(self, api):
        """PRD §3.2: "A device in `REFURBISHING` passes the state rung and is
        judged instead at the temporal rung: if its 48-hour refurbishment
        buffer has not yet elapsed — `refurbishment_due_at` still lies in the
        future — the reservation is rejected with `ERR_DEVICE_NOT_REFURBISHED`
        (HTTP 409)."
        PRD §3.9: "An `InventoryManager` marks a shipment received from either
        `LABEL_CREATED` or `OVERDUE`; the shipment moves to its terminal
        `RECEIVED` state with `received_at` stamped, and the device moves from
        `RETURN_IN_TRANSIT` to `REFURBISHING` with `refurbishment_due_at` set
        48 hours after receipt."

        Design: Difficulty/resource_temporal_overlap/device_refurbishment_buffer
        """
        ctx1, order2 = self._setup_refurbishing_device_and_second_order(api)
        device = read_device(ctx1["device"]["id"])
        assert device["status"] == "REFURBISHING"
        assert_iso_prefix(
            device["refurbishment_due_at"], "2026-05-12T12:00:00", "refurbishment_due_at"
        )

        # 24h into the 48h buffer.
        set_clock("2026-05-11T12:00:00Z")
        resp = api.create_enrollment(
            order2["id"],
            create_enrollment_payload(ctx1["device"]["id"], order2["version"]),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_REFURBISHED)

    def test_reservation_after_buffer_succeeds(self, api):
        """PRD §3.9: "The sweep's first stage then completes refurbishment: a
        `REFURBISHING` device whose `refurbishment_due_at` has been reached
        returns to `IN_STOCK`, reservable again under the eligibility rules of
        §3.2."
        PRD §3.2: "A successful reservation moves the device to `RESERVED`,
        increments the order's `version`, and supersedes any prior non-terminal
        enrollment of the same order: each prior enrollment in `INITIATED`,
        `EDUCATED`, or `ACTIVATION_FAILED` moves to `ABORTED`, and any device
        those enrollments held is released back to `IN_STOCK`."

        Design: Difficulty/resource_temporal_overlap/device_refurbishment_buffer
        """
        ctx1, order2 = self._setup_refurbishing_device_and_second_order(api)

        set_clock("2026-05-11T12:00:00Z")
        resp = api.create_enrollment(
            order2["id"],
            create_enrollment_payload(ctx1["device"]["id"], order2["version"]),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_REFURBISHED)

        # Past the buffer; the sweep's first stage returns the device to stock.
        set_clock("2026-05-12T13:00:00Z")
        run_sweep()
        assert read_device(ctx1["device"]["id"])["status"] == "IN_STOCK"

        enrollment = validate_success(
            api.create_enrollment(
                order2["id"],
                create_enrollment_payload(ctx1["device"]["id"], order2["version"]),
                COORD,
            ),
            201,
        )
        assert enrollment["status"] == "INITIATED"
        assert read_device(ctx1["device"]["id"])["status"] == "RESERVED"


class TestFleetConservation:
    def test_reserve_keeps_fleet_count_constant(self, api):
        """PRD §2.10: "A conservation invariant holds at all times: the counts
        of devices in `IN_STOCK`, `RESERVED`, `DEPLOYED`, `RETURN_IN_TRANSIT`,
        `REFURBISHING`, and `LOST` always sum to the registered fleet size."
        PRD §2.10: "The device list read surfaces this accounting and can be
        filtered by `status` and `model`."

        Design: Difficulty/compensating_invariant/device_pool_unit_conservation
        """
        ctx = setup_open_order(prescribed_days=7)
        assert _event_fleet_count(api) == 1

        enrollment = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD,
            ),
            201,
        )
        device = read_device(ctx["device"]["id"])
        assert device["status"] == "RESERVED"
        assert _event_fleet_count(api) == 1, "reservation reclassifies; it never creates"

        validate_success(api.abort_enrollment(enrollment["id"], COORD))

    def test_abort_compensates_reservation(self, api):
        """PRD §3.2: "Independently, a coordinator may abort any single
        non-terminal enrollment directly, with the same per-enrollment effect:
        `ABORTED`, and its reserved device released."
        PRD §2.10: "A conservation invariant holds at all times: the counts of
        devices in `IN_STOCK`, `RESERVED`, `DEPLOYED`, `RETURN_IN_TRANSIT`,
        `REFURBISHING`, and `LOST` always sum to the registered fleet size."

        Design: Difficulty/compensating_invariant/device_pool_unit_conservation
        """
        ctx = setup_open_order(prescribed_days=7)
        enrollment = validate_success(
            api.create_enrollment(
                ctx["order"]["id"],
                create_enrollment_payload(ctx["device"]["id"], ctx["order"]["version"]),
                COORD,
            ),
            201,
        )
        assert read_device(ctx["device"]["id"])["status"] == "RESERVED"

        validate_success(api.abort_enrollment(enrollment["id"], COORD))
        device = read_device(ctx["device"]["id"])
        assert device["status"] == "IN_STOCK", (
            f"abort is the compensating action: expected IN_STOCK, got {device['status']}"
        )
        assert _event_fleet_count(api) == 1, "the reserve/abort pair must not change the fleet"


class TestShipmentTerminalLockdown:
    def test_shipment_double_receive_rejected(self, api):
        """PRD §3.9: "An `InventoryManager` marks a shipment received from
        either `LABEL_CREATED` or `OVERDUE`; the shipment moves to its terminal
        `RECEIVED` state with `received_at` stamped, and the device moves from
        `RETURN_IN_TRANSIT` to `REFURBISHING` with `refurbishment_due_at` set
        48 hours after receipt."
        PRD §2.8: "5. **State-machine preconditions** — from-state and guard
        checks: generic failures yield `ERR_INVALID_STATE` (409); a device
        already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409);
        activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a
        stale order version yields `ERR_STALE_VERSION` (412)."

        Design: Corner/state_machines/shipment_double_receive_rejected
        """
        ctx = setup_returned_device(prescribed_days=7)
        assert ctx["shipment"]["status"] == "RECEIVED"
        resp = api.mark_shipment_received(ctx["shipment"]["id"], INVENTORY)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        refreshed = validate_success(api.get_return_shipment(ctx["shipment"]["id"], INVENTORY))
        assert refreshed["status"] == "RECEIVED"
