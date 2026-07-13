"""Multi-link cascades: FAIL-accept, repair completion, replacement, and the device cycle."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, factories, fixtures,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/non_linear_state_machine/device_cycle_active_needs_repair_active
# --------------------------------------------------------------------------- #
def test_device_returns_to_active_after_repair_cycle(api):
    """PRD §3.4: "A `REPAIR` completion returns the device to service via the
    `NEEDS_REPAIR → ACTIVE` cascade: the device becomes `ACTIVE`; the connection's posture
    is recomputed, clearing `NON_COMPLIANT` if no other blocker remains".

    Design: Difficulty/non_linear_state_machine/device_cycle_active_needs_repair_active
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    order = get_success_data(api.create_repair_order(
        factories.repair_order_payload(ctx["device"]["id"], order_type="REPAIR",
                                       description="reseat first check valve"), ADMIN))
    get_success_data(api.complete_repair_order(order["id"], {}, ADMIN))
    data = validate_success(api.get_device(ctx["device"]["id"], ADMIN))
    assert data["status"] == "ACTIVE", \
        f"device cycled ACTIVE -> NEEDS_REPAIR -> ACTIVE, got {data['status']}"


def test_device_enters_needs_repair_on_fail_accept(api):
    """PRD §3.3: "When the accepted report's result is `FAIL`, the device enters a
    three-link cascade: the device transitions `ACTIVE → NEEDS_REPAIR`".

    Design: Difficulty/non_linear_state_machine/device_cycle_active_needs_repair_active
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    data = validate_success(api.get_device(ctx["device"]["id"], ADMIN))
    assert data["status"] == "NEEDS_REPAIR", \
        f"FAIL accept drives ACTIVE -> NEEDS_REPAIR, got {data['status']}"


# --------------------------------------------------------------------------- #
# Difficulty/transitive_cascade/fail_accept_cascade_device_posture_notice
# --------------------------------------------------------------------------- #
def test_fail_accept_cascade_device_and_posture(api):
    """PRD §3.3: "When the accepted report's result is `FAIL`, the device enters a
    three-link cascade: the device transitions `ACTIVE → NEEDS_REPAIR`; because a device is
    now in repair, the connection's posture is recomputed to `NON_COMPLIANT`; and because
    the connection is now non-compliant, a shutoff notice with reason `FAILED_TEST` is
    auto-issued in `ISSUED` status and the connection's `open_notice_count` is incremented
    by one."

    Design: Difficulty/transitive_cascade/fail_accept_cascade_device_posture_notice
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    dev = validate_success(api.get_device(ctx["device"]["id"], ADMIN))
    conn = validate_success(api.get_connection(ctx["connection"]["id"], ADMIN))
    assert dev["status"] == "NEEDS_REPAIR", f"link1: got {dev['status']}"
    assert conn["compliance_posture"] == "NON_COMPLIANT", f"link2: got {conn['compliance_posture']}"


def test_fail_accept_cascade_auto_issues_failed_test_notice(api):
    """PRD §3.3: "because the connection is now non-compliant, a shutoff notice with reason
    `FAILED_TEST` is auto-issued in `ISSUED` status and the connection's `open_notice_count`
    is incremented by one."

    Design: Difficulty/transitive_cascade/fail_accept_cascade_device_posture_notice
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    conn = validate_success(api.get_connection(ctx["connection"]["id"], ADMIN))
    assert conn["open_notice_count"] == 1, f"link3 count: got {conn['open_notice_count']}"
    assert ctx["notice"]["reason"] == "FAILED_TEST", f"got {ctx['notice']['reason']}"
    assert ctx["notice"]["status"] == "ISSUED", f"got {ctx['notice']['status']}"


# --------------------------------------------------------------------------- #
# Difficulty/transitive_cascade/repair_complete_cascade_device_posture_rescind
# --------------------------------------------------------------------------- #
def test_repair_complete_cascade_device_and_posture(api):
    """PRD §3.4: "A `REPAIR` completion returns the device to service via the
    `NEEDS_REPAIR → ACTIVE` cascade: the device becomes `ACTIVE`; the connection's posture
    is recomputed, clearing `NON_COMPLIANT` if no other blocker remains".

    Design: Difficulty/transitive_cascade/repair_complete_cascade_device_posture_rescind
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    order = get_success_data(api.create_repair_order(
        factories.repair_order_payload(ctx["device"]["id"], order_type="REPAIR",
                                       description="reseat check valve"), ADMIN))
    get_success_data(api.complete_repair_order(order["id"], {}, ADMIN))
    dev = validate_success(api.get_device(ctx["device"]["id"], ADMIN))
    conn = validate_success(api.get_connection(ctx["connection"]["id"], ADMIN))
    assert dev["status"] == "ACTIVE", f"link1: got {dev['status']}"
    assert conn["compliance_posture"] == "COMPLIANT", \
        f"link2 (device due 2027-01-01, not in the 30-day window): got {conn['compliance_posture']}"


def test_repair_complete_cascade_auto_rescinds_notice(api):
    """PRD §3.4: "because no device is now in `NEEDS_REPAIR` and the connection has no
    overdue devices, any `ISSUED` shutoff notice whose reason is `FAILED_TEST` or
    `UNREPAIRED_DEVICE` is auto-rescinded and `open_notice_count` decremented".

    Design: Difficulty/transitive_cascade/repair_complete_cascade_device_posture_rescind
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    order = get_success_data(api.create_repair_order(
        factories.repair_order_payload(ctx["device"]["id"], order_type="REPAIR",
                                       description="reseat check valve"), ADMIN))
    get_success_data(api.complete_repair_order(order["id"], {}, ADMIN))
    notice = validate_success(api.get_notice(ctx["notice"]["id"], ADMIN))
    conn = validate_success(api.get_connection(ctx["connection"]["id"], ADMIN))
    assert notice["status"] == "RESCINDED", f"link3 auto-rescind: got {notice['status']}"
    assert conn["open_notice_count"] == 0, f"got {conn['open_notice_count']}"


# --------------------------------------------------------------------------- #
# Difficulty/compensating_invariant/protected_device_count_conserved_on_replacement
# --------------------------------------------------------------------------- #
def test_protected_count_conserved_on_replacement(api):
    """PRD §3.4: "The connection's `protected_device_count` is deliberately unchanged: the
    retiring device leaves the protected set and the new device enters it, a compensating
    one-out-one-in invariant."

    Design: Difficulty/compensating_invariant/protected_device_count_conserved_on_replacement
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    order = get_success_data(api.create_repair_order(
        factories.repair_order_payload(ctx["device"]["id"], order_type="REPLACEMENT",
                                       description="replace assembly",
                                       replacement_serial_number="SN-REPL-B"), ADMIN))
    get_success_data(api.complete_repair_order(order["id"],
                                               {"replacement_serial_number": "SN-REPL-B"}, ADMIN))
    old = validate_success(api.get_device(ctx["device"]["id"], ADMIN))
    conn = validate_success(api.get_connection(ctx["connection"]["id"], ADMIN))
    assert old["status"] == "REPLACED", f"old device retired, got {old['status']}"
    assert conn["protected_device_count"] == 1, \
        f"old -1 out, new +1 in -> conserved at 1, got {conn['protected_device_count']}"


def test_replacement_installs_new_active_device_with_new_serial(api):
    """PRD §3.4: "the old device becomes `REPLACED`, and a new device is created in `ACTIVE`
    status on the same connection, carrying the `replacement_serial_number` as its serial
    and copying the old device's `device_type`, `hazard_rating`, and
    `test_interval_months`, with its `install_date` set to `current_utc`."

    Design: Difficulty/compensating_invariant/protected_device_count_conserved_on_replacement
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    order = get_success_data(api.create_repair_order(
        factories.repair_order_payload(ctx["device"]["id"], order_type="REPLACEMENT",
                                       description="replace assembly",
                                       replacement_serial_number="SN-REPL-C"), ADMIN))
    get_success_data(api.complete_repair_order(order["id"],
                                               {"replacement_serial_number": "SN-REPL-C"}, ADMIN))
    devices, _ = validate_paginated(
        api.list_devices(ADMIN, params={"service_connection_id": ctx["connection"]["id"]}))
    new_devices = [d for d in devices if d["serial_number"] == "SN-REPL-C"]
    assert len(new_devices) == 1, f"exactly one new device with the replacement serial, got {len(new_devices)}"
    assert new_devices[0]["status"] == "ACTIVE", f"new device ACTIVE, got {new_devices[0]['status']}"


# --------------------------------------------------------------------------- #
# Corner/validations/complete_replacement_without_serial_returns_required
# --------------------------------------------------------------------------- #
def test_complete_replacement_without_serial_returns_required(api):
    """PRD §3.4: "For a `REPLACEMENT` order, a `replacement_serial_number` must be present
    at completion; its absence is rejected with `ERR_REPLACEMENT_SERIAL_REQUIRED`."

    Design: Corner/validations/complete_replacement_without_serial_returns_required
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    order = get_success_data(api.create_repair_order(
        factories.repair_order_payload(ctx["device"]["id"], order_type="REPLACEMENT",
                                       description="replace assembly"), ADMIN))
    validate_error(api.complete_repair_order(order["id"], {}, ADMIN),
                   ApiErrorId.ERR_REPLACEMENT_SERIAL_REQUIRED)


# --------------------------------------------------------------------------- #
# Corner/validations/rescind_blocked_while_device_needs_repair
# --------------------------------------------------------------------------- #
def test_rescind_blocked_while_device_needs_repair(api):
    """PRD §3.6: "it must have no device in `NEEDS_REPAIR` status and an
    `overdue_device_count` of zero, otherwise the rescind is blocked with
    `ERR_NOTICE_RESCIND_BLOCKED`".

    Design: Corner/validations/rescind_blocked_while_device_needs_repair
    """
    ctx = fixtures.setup_device_needs_repair(api, ADMIN)
    validate_error(api.rescind_notice(ctx["notice"]["id"], ADMIN),
                   ApiErrorId.ERR_NOTICE_RESCIND_BLOCKED)
