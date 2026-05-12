"""Machine + compartment provisioning, heartbeat, OOS toggle — PRD §3.1, §3.2."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CapacityWarningLevel,
    CompartmentStatus,
    LockerMachineOnlineStatus,
    assert_capacity_invariant,
    assert_compartment,
    assert_locker_machine,
    create_compartment,
    create_compartment_payload,
    create_locker_machine_payload,
    create_machine,
    deposit_parcel,
    get_compartment,
    get_machine,
    heartbeat,
    heartbeat_payload,
    offline_machine,
    setup_basic_scenario,
    setup_deposited_parcel,
    setup_machine_with_compartments,
    validate_error,
    validate_success,
)


class TestCreateLockerMachine:
    """PRD §3.1: 'A locker site begins life when an OperationsAdmin
    registers a new LockerMachine by supplying its site_code, partner_id,
    and initial firmware_version.'"""

    def test_create_machine_starts_online_with_degraded_false(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'Newly created machines start online_status = ONLINE
        with degraded_mode = false and have no compartments yet.'

        Claim: POST /locker-machines yields online_status=ONLINE,
        degraded_mode=false, and total_compartments=0.
        """
        resp = api.create_locker_machine(
            create_locker_machine_payload(),
            operations_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_locker_machine(data)
        assert data["online_status"] == LockerMachineOnlineStatus.ONLINE.value
        assert data["degraded_mode"] is False
        assert data["total_compartments"] == 0


class TestForceOfflineAndDegraded:
    """PRD §3.1: 'Operations may also force OFFLINE directly … Any
    transition to OFFLINE sets degraded_mode to true, advances version,
    refreshes updated_at, and immediately blocks new deposits at this
    machine with ERR_MACHINE_OFFLINE_DEGRADED.'"""

    def test_offline_sets_degraded_mode_true(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'Any transition to OFFLINE sets degraded_mode to true,
        advances version, refreshes updated_at, and immediately blocks new
        deposits at this machine with ERR_MACHINE_OFFLINE_DEGRADED.'

        Claim: POST /offline yields online_status=OFFLINE AND degraded_mode=true.
        """
        machine = create_machine()
        before_version = machine["version"]
        resp = api.offline_locker_machine(
            machine["id"], operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["online_status"] == LockerMachineOnlineStatus.OFFLINE.value
        assert data["degraded_mode"] is True
        assert data["version"] > before_version, (
            "PRD §3.1: 'advances version'"
        )

    def test_heartbeat_recovers_machine_to_online(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'when a previously offline machine pings with a
        firmware that meets the minimum supported baseline … the machine
        transitions back to ONLINE.'

        Claim: after offline, a heartbeat with valid firmware flips
        online_status back to ONLINE and clears degraded_mode.
        """
        machine = create_machine(firmware_version="9.9.9")
        offline_machine(machine["id"])
        resp = api.heartbeat_locker_machine(
            machine["id"],
            heartbeat_payload(firmware_version="9.9.9"),
            operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["online_status"] == LockerMachineOnlineStatus.ONLINE.value
        assert data["degraded_mode"] is False


class TestCreateCompartment:
    """PRD §3.1: 'Compartments are added one at a time, each carrying a
    slot_label … and a size of SMALL, MEDIUM, or LARGE. A fresh
    compartment enters with status = AVAILABLE and no current_parcel_id.'"""

    def test_compartment_starts_available(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'A fresh compartment enters with status = AVAILABLE
        and no current_parcel_id.'

        Claim: POST /compartments yields status=AVAILABLE and
        current_parcel_id is null.
        """
        machine = create_machine()
        resp = api.create_compartment(
            machine["id"],
            create_compartment_payload(size="LARGE", slot_label="L-001"),
            operations_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_compartment(data)
        assert data["status"] == CompartmentStatus.AVAILABLE.value
        assert data.get("current_parcel_id") in (None, "")


class TestCompartmentOutOfService:
    """PRD §3.1: 'if the compartment is currently OCCUPIED, the operator
    must first arrange a recall or disposal of the inhabiting parcel;
    attempting to take an occupied compartment out of service without
    that step is rejected with ERR_OCCUPIED_COMPARTMENT_NEEDS_CLEAR.'"""

    def test_oos_on_occupied_without_clear_rejected(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'attempting to take an occupied compartment out of
        service without that step is rejected with
        ERR_OCCUPIED_COMPARTMENT_NEEDS_CLEAR.'

        Claim: POST /out-of-service on an OCCUPIED compartment whose
        parcel has not been recalled/disposed returns
        ERR_OCCUPIED_COMPARTMENT_NEEDS_CLEAR.
        """
        machine, comp, _, parcel = setup_deposited_parcel()
        resp = api.out_of_service_compartment(
            machine["id"], parcel["compartment_id"],
            operations_admin_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_OCCUPIED_COMPARTMENT_NEEDS_CLEAR.value,
        )

    def test_oos_on_available_succeeds(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'Toggling a compartment to OUT_OF_SERVICE from
        AVAILABLE, RESERVED, or OCCUPIED is permitted with one safety
        rule …'

        Claim: from AVAILABLE the toggle succeeds and the compartment
        status becomes OUT_OF_SERVICE.
        """
        machine, [comp] = setup_machine_with_compartments(sizes=["MEDIUM"])
        resp = api.out_of_service_compartment(
            machine["id"], comp["id"], operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["status"] == CompartmentStatus.OUT_OF_SERVICE.value

    def test_in_service_restores_to_available(
        self, api, operations_admin_headers,
    ):
        """PRD §3.1: 'Returning a compartment from OUT_OF_SERVICE to
        AVAILABLE carries no preconditions.'

        Claim: in-service toggle returns status=AVAILABLE.
        """
        machine, [comp] = setup_machine_with_compartments(sizes=["SMALL"])
        api.out_of_service_compartment(
            machine["id"], comp["id"], operations_admin_headers,
        )
        resp = api.in_service_compartment(
            machine["id"], comp["id"], operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["status"] == CompartmentStatus.AVAILABLE.value


class TestMachineDerivedFields:
    """PRD §2.5: 'The system also recomputes derived occupancy and rating
    fields on read, so that LockerMachine.capacity_warning_level,
    LockerMachine.occupied_count_small … always reflect the current
    ledger of compartments and parcels.'"""

    def test_machine_with_no_compartments_is_normal(
        self, api,
    ):
        """PRD §3.2: 'For each size in SMALL, MEDIUM, LARGE: count
        size_total as the number of compartments at this machine with
        that size whose status is anything other than DECOMMISSIONED, and
        size_occupied as the number of compartments at this machine with
        that size whose status is exactly OCCUPIED.'

        Claim: a fresh machine with no compartments has
        capacity_warning_level=NORMAL and zero occupied counts.
        """
        machine = create_machine()
        # Re-read to engage derived-field recomputation
        m = get_machine(machine["id"])
        assert m["capacity_warning_level"] == (
            CapacityWarningLevel.NORMAL.value
        )
        assert m["occupied_count_small"] == 0
        assert m["occupied_count_medium"] == 0
        assert m["occupied_count_large"] == 0
        assert m["total_compartments"] == 0
        assert_capacity_invariant(m)

    def test_occupied_count_increments_on_deposit(self, api):
        """PRD §3.2: 'The exact running tallies of each size's occupancy
        are exposed on the machine record as occupied_count_small,
        occupied_count_medium, and occupied_count_large.'

        Claim: after a deposit on a MEDIUM compartment, the machine's
        occupied_count_medium reads back as 1.
        """
        machine, _, _, parcel = setup_deposited_parcel(
            sizes=["MEDIUM"], required_size="MEDIUM",
        )
        m = get_machine(machine["id"])
        assert m["occupied_count_medium"] == 1, (
            f"expected occupied_count_medium=1; got {m['occupied_count_medium']}"
        )
        assert m["occupied_count_small"] == 0
        assert m["occupied_count_large"] == 0
