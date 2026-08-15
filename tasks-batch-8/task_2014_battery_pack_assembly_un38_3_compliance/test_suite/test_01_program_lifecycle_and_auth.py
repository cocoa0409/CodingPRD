"""Program lifecycle, retrieval, pagination, posture gating, and auth gates."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_integration_program,
    create_battery_pack,
    create_cell_lot_payload,
    create_program,
    create_program_payload,
    get_program,
    make_any_headers,
    make_quality_engineer_headers,
    setup_program_with_bom,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramCreation:
    def test_creation_applies_documented_defaults(self, api):
        """PRD §3.1: "A newly created program starts with `status` equal to `OPEN`, a
        `compliance_risk_index` of 100, `wh_committed` at 0, `recall_count` at 0, and
        `version` at 1."
        PRD §2.8: "and `wh_available` is the difference between the two."

        Design: Corner/entities/integration_program_creation_defaults_applied
        """
        resp = api.create_program(
            create_program_payload("PRG-Z1", 5000), TEST_USERS["safety_officer_headers"]
        )
        program = validate_success(resp, 201)
        assert_integration_program(program)
        assert program["compliance_risk_index"] == 100
        assert program["wh_committed"] == 0
        assert program["wh_available"] == 5000
        assert program["recall_count"] == 0
        assert program["status"] == "OPEN"
        assert program["version"] == 1

    def test_get_by_id_returns_persisted_program(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."
        PRD §3.1: "Everything begins when a `SafetyOfficer` opens an integration program
        by supplying a unique `program_code`".

        Design: Corner/entities/integration_program_get_by_id_returns_persisted
        """
        created = create_program("PRG-Z2", 5000)
        resp = api.get_program(created["id"], make_any_headers())
        fetched = validate_success(resp, 200)
        assert_integration_program(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["program_code"] == "PRG-Z2"

    def test_get_missing_program_returns_404(self, api):
        """PRD §2.5: "Nested endpoints are validated strictly left to right: the server
        resolves the program first, then the resource named at the next segment, and so
        on, rejecting immediately with the `404` error of the first path segment that
        does not resolve — `ERR_PROGRAM_NOT_FOUND`".

        Design: Corner/entities/integration_program_get_missing_returns_404
        """
        resp = api.get_program(NON_EXISTENT_UUID, make_any_headers())
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)

    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
        to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset`
        parameter skips a number of items from the front of the result set and defaults
        to 0."
        PRD §2.3: "and every list response carries `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/integration_program_list_pagination_envelope
        """
        for code in ("PRG-P1", "PRG-P2", "PRG-P3"):
            create_program(code, 5000)
        resp = api.list_programs(make_any_headers(), params={"limit": 2, "offset": 1})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 2, f"expected page of 2, got {len(data)}"
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        returned_codes = {p["program_code"] for p in data}
        assert returned_codes <= {"PRG-P1", "PRG-P2", "PRG-P3"}


class TestProgramPosture:
    def test_close_blocked_with_unresolved_packs(self, api):
        """PRD §3.1: "The close is rejected with `ERR_UNRESOLVED_PACKS_REMAIN` if any pack
        exists whose assembly axis has not reached `RECALLED` and whose logistics axis has
        not reached `DELIVERED` or `RETURNED`".

        Design: Corner/state_machines/program_close_blocked_with_unresolved_packs
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        create_battery_pack(program_id, bundle["bom"]["id"])  # pack stays BUILT
        resp = api.close_program(program_id, TEST_USERS["safety_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_PACKS_REMAIN)
        assert get_program(program_id)["status"] == "OPEN"

    def test_suspend_gates_child_creation(self, api):
        """PRD §2.6: "Any call that creates or mutates a child resource under a program
        requires that program to be `OPEN`; when it is not, the call is rejected with
        `ERR_PROGRAM_NOT_OPEN`."

        Design: Corner/state_machines/program_suspend_gates_child_creation
        """
        program = create_program("PRG-SM2", 5000)
        suspended = validate_success(
            api.suspend_program(program["id"], TEST_USERS["safety_officer_headers"]), 200
        )
        assert suspended["status"] == "SUSPENDED"
        resp = api.create_cell_lot(
            program["id"],
            create_cell_lot_payload("LOT-SM2", 10, 3000, 40.0),
            make_quality_engineer_headers("qe-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)


class TestAuthGates:
    def test_wrong_role_rejected_with_insufficient_permissions(self, api):
        """PRD §2.1: "An authenticated operator who attempts an operation reserved for a
        different role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/errors/insufficient_permissions_triggerable
        """
        resp = api.create_program(
            create_program_payload("PRG-RBAC", 5000),
            make_quality_engineer_headers("qe-not-so"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    @pytest.mark.parametrize(
        "headers",
        [
            {},  # both headers missing
            {"X-User-Role": "SafetyOfficer", "Content-Type": "application/json"},  # no X-User-ID
            {"X-User-ID": "so-1", "Content-Type": "application/json"},  # no X-User-Role
        ],
        ids=["both-missing", "missing-user-id", "missing-user-role"],
    )
    def test_missing_user_context_header_rejected(self, api, headers):
        """PRD §2.1: "A request in which either header is missing or malformed is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/errors/missing_user_context_header_triggerable
        """
        resp = api.create_program(create_program_payload("PRG-AUTH", 5000), headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
