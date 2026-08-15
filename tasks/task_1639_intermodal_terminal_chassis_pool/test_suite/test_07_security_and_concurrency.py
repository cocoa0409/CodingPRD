"""Authentication, RBAC, optimistic concurrency, and the operations checkpoint
counter (PRD §2.1, §2.9, §3.8, §4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    apply_ledger_payment,
    assert_terminal,
    book_appointment,
    check_in,
    check_in_payload,
    complete_transaction,
    create_arrived_train,
    create_carrier,
    create_chassis,
    create_pool,
    create_slot,
    create_terminal,
    create_terminal_payload,
    enroll_carrier,
    get_carrier,
    get_container,
    get_pool,
    get_terminal,
    ground_container,
    list_ledger_entries,
    open_transaction,
    register_container,
    reserve_chassis,
    run_ops,
    set_clock,
    setup_grounded_container,
    setup_terminal_with_slots,
    TEST_USERS,
    validate_error,
    validate_success,
)

TM = TEST_USERS["terminal_manager_headers"]
PA = TEST_USERS["pool_administrator_headers"]
YP = TEST_USERS["yard_planner_headers"]
GC = TEST_USERS["gate_clerk_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestAuthentication:
    @pytest.mark.parametrize("headers", [
        {},  # neither header present
        {"X-User-ID": "test-no-role-1"},  # role header missing
    ])
    def test_missing_auth_headers_unauthenticated(self, api, headers):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        resp = api.get_terminal(NON_EXISTENT_UUID, headers=headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_gate_clerk_cannot_create_terminal(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint per the RBAC matrix in §4 is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "| POST | `/terminals` | Create a Terminal | TerminalManager |"

        Design: Corner/validations/unauthorized_role_cannot_create_terminal
        """
        resp = api.create_terminal(create_terminal_payload(), GC)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_pool_administrator_cannot_ground_container(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint per the RBAC matrix in §4 is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "| POST | `/terminals/{tid}/containers/{cid}/ground` | Ground
        an INBOUND_TRAIN container into a yard slot | YardPlanner |"

        Design: Corner/rbac/pool_admin_cannot_ground_container
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=20, num_slots=1)
        tid = terminal["id"]
        train = create_arrived_train(tid)
        container = register_container(tid, train["id"])
        set_clock("2026-08-01T00:00:00Z")
        version = get_terminal(tid)["version"]

        resp = api.ground_container(
            tid, container["id"], {"expected_terminal_version": version}, PA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_container(tid, container["id"])["status"] == "INBOUND_TRAIN"

    def test_billing_clerk_cannot_void_container(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint per the RBAC matrix in §4 is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "| POST | `/terminals/{tid}/containers/{cid}/void` | Void an
        ON_GROUND container (no OPEN damage allowed) | TerminalManager |"

        Design: Corner/rbac/billing_clerk_cannot_void_container
        """
        ctx = setup_grounded_container()
        tid = ctx["terminal"]["id"]

        resp = api.void_container(tid, ctx["container"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_container(tid, ctx["container"]["id"])["status"] == "ON_GROUND"

    def test_all_eight_roles_can_get_terminal(self, api):
        """PRD §4: "| GET | `/terminals/{tid}` | Get a Terminal |
        TerminalManager, GateSupervisor, YardPlanner, RailCoordinator,
        PoolAdministrator, MaintenancePlanner, BillingClerk, GateClerk |"

        Design: Corner/rbac/peer_roles_shared_get_access
        """
        terminal = create_terminal()
        for key in ("terminal_manager_headers", "gate_supervisor_headers",
                    "yard_planner_headers", "rail_coordinator_headers",
                    "pool_administrator_headers", "maintenance_planner_headers",
                    "billing_clerk_headers", "gate_clerk_headers"):
            resp = api.get_terminal(terminal["id"], TEST_USERS[key])
            data = validate_success(resp, 200)
            assert data["id"] == terminal["id"], (
                f"Role behind {key} must be able to GET the terminal")


def _two_chassis_two_appointments():
    """Terminal (2 slots) + pool with 2 chassis + one carrier with ACTIVE
    membership + arrived train + 2 grounded containers + 2 CHECKED_IN OUT
    appointments. Returns a context dict."""
    terminal, slots = setup_terminal_with_slots(yard_slot_count=20, num_slots=2)
    tid = terminal["id"]
    pool = create_pool(tid)
    chassis_1 = create_chassis(tid, pool["id"], chassis_number="CH-001")
    chassis_2 = create_chassis(tid, pool["id"], chassis_number="CH-002")
    carrier = create_carrier()
    enroll_carrier(tid, pool["id"], carrier["id"])
    train = create_arrived_train(tid)
    set_clock("2026-08-01T00:00:00Z")
    c1 = ground_container(tid, register_container(tid, train["id"], "C0000000001")["id"])
    c2 = ground_container(tid, register_container(tid, train["id"], "C0000000002")["id"])
    set_clock("2026-08-02T10:00:00Z")
    appt_1 = check_in(tid, book_appointment(
        tid, carrier["id"], c1["id"], "OUT",
        "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")["id"])
    appt_2 = check_in(tid, book_appointment(
        tid, carrier["id"], c2["id"], "OUT",
        "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")["id"])
    return {"terminal": get_terminal(tid), "pool": pool,
            "chassis": [chassis_1, chassis_2], "carrier": carrier,
            "train": train, "containers": [c1, c2],
            "appointments": [appt_1, appt_2]}


class TestOptimisticConcurrency:
    def test_reserve_with_stale_pool_version_rejected(self, api):
        """PRD §2.9: "against a pool requires `expected_pool_version`, matched
        against the current `version` of the ChassisPool." and "if the supplied
        value does not match the parent's current `version` on the server, the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)." and "A
        successful reservation itself increments the pool's `version` by one."

        The first reserve advances the pool version past the snapshot both
        callers took; the second caller's view is stale.

        Design: Corner/errors/error_stale_version_chassis_reserve
        """
        ctx = _two_chassis_two_appointments()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        snapshot = get_pool(tid, pid)["version"]

        first = validate_success(api.reserve_chassis(
            tid, pid, ctx["chassis"][0]["id"],
            {"appointment_id": ctx["appointments"][0]["id"],
             "expected_pool_version": snapshot},
            TEST_USERS["gate_supervisor_headers"]), 200)
        assert first["status"] == "RESERVED"
        assert get_pool(tid, pid)["version"] == snapshot + 1

        resp = api.reserve_chassis(
            tid, pid, ctx["chassis"][1]["id"],
            {"appointment_id": ctx["appointments"][1]["id"],
             "expected_pool_version": snapshot},
            TEST_USERS["gate_supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_ground_with_stale_terminal_version_rejected(self, api):
        """PRD §2.9: "requires `expected_terminal_version`, matched against the
        current `version` of the Terminal." and "if the supplied value does not
        match the parent's current `version` on the server, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)." and "A successful ground
        increments the terminal's `version` by one."

        Design: Corner/cross_cutting_layers/occ_ground_container_stale_terminal
        """
        terminal, slots = setup_terminal_with_slots(yard_slot_count=20, num_slots=2)
        tid = terminal["id"]
        train = create_arrived_train(tid)
        c1 = register_container(tid, train["id"], "C0000000001")
        c2 = register_container(tid, train["id"], "C0000000002")
        set_clock("2026-08-01T00:00:00Z")
        snapshot = get_terminal(tid)["version"]

        grounded = validate_success(api.ground_container(
            tid, c1["id"], {"expected_terminal_version": snapshot}, YP), 200)
        assert grounded["status"] == "ON_GROUND"
        assert get_terminal(tid)["version"] == snapshot + 1

        resp = api.ground_container(
            tid, c2["id"], {"expected_terminal_version": snapshot}, YP)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_container(tid, c2["id"])["status"] == "INBOUND_TRAIN"

    def test_ledger_apply_with_stale_carrier_version_rejected(self, api):
        """PRD §2.9: "to a carrier's ledger entry requires
        `expected_carrier_version`, matched against the current `version` of
        the Carrier." and "if the supplied value does not match the parent's
        current `version` on the server, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)." and "A successful apply increments the
        carrier's `version` by one."

        Two completed out-gates give the same carrier two OPEN FLIP_FEE
        entries; the first apply advances the carrier version past the
        snapshot.

        Design: Corner/cross_cutting_layers/occ_ledger_apply_stale_carrier
        """
        ctx = _two_chassis_two_appointments()
        tid = ctx["terminal"]["id"]
        pid = ctx["pool"]["id"]
        carrier_id = ctx["carrier"]["id"]

        transactions = []
        for chassis, appointment in zip(ctx["chassis"], ctx["appointments"]):
            reserve_chassis(tid, pid, chassis["id"], appointment["id"])
            transactions.append(open_transaction(
                tid, appointment["id"], chassis_id=chassis["id"]))
        for tx in transactions:
            complete_transaction(tid, tx["id"])

        entries = list_ledger_entries(tid, entry_kind="FLIP_FEE",
                                      carrier_id=carrier_id)
        assert len(entries) == 2, "Setup failed: expected two OPEN FLIP_FEE entries"
        snapshot = get_carrier(carrier_id)["version"]

        applied = validate_success(api.apply_ledger_payment(
            tid, entries[0]["id"],
            {"apply_cents": 5000, "expected_carrier_version": snapshot}, BC), 200)
        assert applied["status"] == "APPLIED"
        assert get_carrier(carrier_id)["version"] == snapshot + 1

        resp = api.apply_ledger_payment(
            tid, entries[1]["id"],
            {"apply_cents": 5000, "expected_carrier_version": snapshot}, BC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestRunOpsCheckpoint:
    def test_run_ops_increments_ops_run_index_monotonically(self, api):
        """PRD §3.8: "It increments the terminal's `ops_run_index` by one." and
        PRD §3.1: "the `ops_run_index` monotone counter starts at zero."

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_epoch_advancement
        """
        terminal = create_terminal()
        tid = terminal["id"]
        assert_terminal(terminal)
        assert terminal["ops_run_index"] == 0

        for expected in (1, 2, 3):
            data = run_ops(tid)
            assert data["ops_run_index"] == expected, (
                f"run_ops #{expected} must leave ops_run_index == {expected}, "
                f"got {data['ops_run_index']}")
