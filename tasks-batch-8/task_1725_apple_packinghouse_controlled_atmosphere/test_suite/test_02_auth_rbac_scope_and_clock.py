"""Authentication, role-based access control, grower scoping, existence checks,
and the logical clock."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_allocation_payload,
    create_grower,
    create_grower_with_block,
    create_pool_payload,
    create_room,
    make_grower_headers,
    presize_payload,
    receive_lot,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
STORAGE = TEST_USERS["storage_operator_headers"]
SUPERVISOR = TEST_USERS["packing_supervisor_headers"]


class TestAuthentication:
    def test_request_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing or unrecognized header is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401); a recognized role attempting an
        operation outside its grant is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/errors/c_request_missing_auth_headers_unauthenticated
        """
        grower, block = create_grower_with_block()
        lot = receive_lot(grower["id"], block["id"])

        resp = api.get_lot(lot["id"], {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestPeerRoleAuthorization:
    def test_peer_role_writes_forbidden(self, api):
        """PRD §2.1: "a recognized role attempting an operation outside its grant
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`PoolManager` is the marketing office: packaging specs, pools,
        pooled sales, pool closes and reopens, and settlement advances."
        PRD §2.1: "`StorageOperator` runs CA storage: room registration and
        scheduling, sealing and opening, atmosphere readings, disorder
        inspections, bin allocations, releases, and lot diversion."

        Design: Corner/rbac/c_peer_role_writes_forbidden
        """
        grower, block = create_grower_with_block()
        lot = receive_lot(grower["id"], block["id"])
        room = create_room()

        # ReceivingClerk stepping onto the marketing surface.
        resp1 = api.create_pool(create_pool_payload(), CLERK)
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)

        # PackingSupervisor stepping onto the CA-storage surface.
        resp2 = api.create_allocation(
            room["id"], create_allocation_payload(lot["id"], 5), SUPERVISOR)
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)


class TestGrowerScope:
    def test_grower_scope_own_vs_other(self, api):
        """PRD §2.1: "A grower caller addressing another grower's record, block
        list, lots, allocations, or settlements is rejected with
        `ERR_GROWER_SCOPE_VIOLATION` (HTTP 403); this scoping applies to the
        grower self-read, the grower's block list, the lot list and detail, the
        allocation list and detail, and the settlement list and detail."
        PRD §2.1: "On the lot, allocation, and settlement list endpoints, grower
        callers are force-filtered to their own data — the lot list is constrained
        to the caller's own `grower_id`, the allocation list to allocations of the
        caller's own lots, and the settlement list to the caller's own rows."

        Design: Corner/rbac/c_grower_scope_own_vs_other
        """
        grower1, block1 = create_grower_with_block(grower_name="Grower One",
                                                   grower_code="G1")
        grower2 = create_grower("Grower Two", "G2")
        lot1 = receive_lot(grower1["id"], block1["id"])

        own = validate_success(api.get_lot(lot1["id"],
                                           make_grower_headers(grower1["id"])))
        assert own["id"] == lot1["id"], "self read allowed"

        resp = api.get_lot(lot1["id"], make_grower_headers(grower2["id"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_SCOPE_VIOLATION)

        # Settlement list is force-filtered to the caller's own grower even when
        # the caller passes a foreign grower_id filter.
        data, meta = validate_paginated(api.list_settlements(
            make_grower_headers(grower2["id"]),
            params={"grower_id": grower1["id"]}))
        assert meta["total_count"] == 0, "foreign grower_id filter is overridden"
        assert data == []


class TestExistence:
    def test_get_unknown_lot_returns_not_found(self, api):
        """PRD §2.9: "4. **Existence** — path identifiers resolve left to right,
        then body-supplied foreign keys exist, else `ERR_NOT_FOUND`."

        Design: Corner/validations/c_get_unknown_lot_returns_not_found
        """
        resp = api.get_lot(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_presize_unknown_lot_existence_beats_state(self, api):
        """PRD §2.9: "When several checks would fail on a single call, the first
        applicable tier below determines the response."
        PRD §2.9: "4. **Existence** — path identifiers resolve left to right,
        then body-supplied foreign keys exist, else `ERR_NOT_FOUND`."

        Design: Corner/validations/c_presize_unknown_lot_existence_beats_state
        """
        resp = api.presize_lot(NON_EXISTENT_UUID, presize_payload(), CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLogicalClock:
    def test_clock_rejects_backwards(self, api):
        """PRD §2.4: "An `Admin` may set the clock through a test-driving
        capability that accepts a `to_iso8601` instant, which must be a valid ISO
        8601 UTC timestamp. Setting the clock backwards is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/c_clock_rejects_backwards
        """
        ok = api.set_logical_clock(set_clock_payload("2026-08-10T00:00:00Z"), ADMIN)
        validate_success(ok)
        resp = api.set_logical_clock(set_clock_payload("2026-08-05T00:00:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
