"""Authentication and role-based access control (PRD §2.1, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    create_circuit,
    make_role_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
SO1 = TEST_USERS["safety_officer_headers"]

ALL_ROLES = [
    "SystemAdmin", "NetworkPlanner", "TestSupervisor", "FieldTechnician",
    "SafetyOfficer", "FaultCrewLead", "DispatchCoordinator", "AssetEngineer",
]


class TestAuthentication:
    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        name the system does not declare, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        circuit = create_circuit("CKT-V1")
        resp = api.get_circuit(circuit["id"], None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_safety_officer_cannot_create_window(self, api):
        """PRD §4: "| POST | /cable-diagnostics/outage-windows | Request an outage window | NetworkPlanner |".
        PRD §2.1: "Once authenticated, the role must be among the roles
        allowed for the specific endpoint; otherwise the request is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/safety_officer_cannot_create_window
        """
        circuit = create_circuit("CKT-R1")
        resp = api.create_outage_window(
            {
                "circuit_id": circuit["id"],
                "kind": "PLANNED_DIAGNOSTIC",
                "window_start": "2026-08-10T08:00:00Z",
                "window_end": "2026-08-10T12:00:00Z",
            },
            SO1,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSharedReads:
    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_all_roles_can_read_circuit(self, api, role):
        """PRD §4: "| GET | /cable-diagnostics/circuits/{id} | Get a circuit | All roles |",
        where "\"All roles\" means all eight roles enumerated in §2.1."

        Design: Corner/rbac/all_roles_can_read_circuit
        """
        # The server restarts per test: each parametrized run creates its own.
        circuit = create_circuit("CKT-R4", "KV_69", 5200, 1999)
        data = validate_success(
            api.get_circuit(circuit["id"], make_role_headers(f"{role.lower()}-1", role))
        )
        assert data["circuit_ref"] == "CKT-R4"
