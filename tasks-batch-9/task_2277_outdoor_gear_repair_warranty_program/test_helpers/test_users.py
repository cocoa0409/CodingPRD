"""Actor identities and auth headers (PRD §2.1).

Every request carries `X-User-ID` and `X-User-Role`. Two of the five roles are
backed by persisted entities: a `Customer` header must carry the id of a real
Customer row and a `RepairTechnician` header must carry the id of a real
Technician row, otherwise the request is rejected with ERR_UNKNOWN_ACTOR. The
remaining three roles — ServiceAgent, PartsCoordinator, ProgramAdmin — are
opaque principals whose identifier is not resolved against any registry, so a
fixed identifier is fine for them.

Consequence for tests: ownership-gated and technician-gated calls MUST be made
with make_customer_headers(<customer id>) / make_technician_headers(
<technician id>) built from the entity actually created in the scenario.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_CUSTOMER = "Customer"
ROLE_SERVICE_AGENT = "ServiceAgent"
ROLE_REPAIR_TECHNICIAN = "RepairTechnician"
ROLE_PARTS_COORDINATOR = "PartsCoordinator"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    ROLE_CUSTOMER,
    ROLE_SERVICE_AGENT,
    ROLE_REPAIR_TECHNICIAN,
    ROLE_PARTS_COORDINATOR,
    ROLE_PROGRAM_ADMIN,
)

# Opaque principals — identifier is never resolved against a registry.
SERVICE_AGENT_ID = "agent-fern-holloway"
PARTS_COORDINATOR_ID = "parts-abel-quintero"
PROGRAM_ADMIN_ID = "admin-mira-lindqvist"

SERVICE_AGENT_HEADERS = build_user_headers(SERVICE_AGENT_ID, ROLE_SERVICE_AGENT)
PARTS_COORDINATOR_HEADERS = build_user_headers(
    PARTS_COORDINATOR_ID, ROLE_PARTS_COORDINATOR
)
PROGRAM_ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN)

TEST_USERS = {
    ROLE_SERVICE_AGENT: SERVICE_AGENT_HEADERS,
    ROLE_PARTS_COORDINATOR: PARTS_COORDINATOR_HEADERS,
    ROLE_PROGRAM_ADMIN: PROGRAM_ADMIN_HEADERS,
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the Customer role — `customer_id` must be a real Customer id."""
    return build_user_headers(customer_id, ROLE_CUSTOMER)


def make_technician_headers(technician_id: str) -> dict:
    """Headers for the RepairTechnician role — must be a real Technician id."""
    return build_user_headers(technician_id, ROLE_REPAIR_TECHNICIAN)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role / identifier pair."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = SERVICE_AGENT_ID) -> dict:
    """Only X-User-ID present — drives ERR_MISSING_AUTH_HEADERS (PRD §2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_SERVICE_AGENT) -> dict:
    """Only X-User-Role present — drives ERR_MISSING_AUTH_HEADERS (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = SERVICE_AGENT_ID) -> dict:
    """Blank role value — PRD §2.1 treats blank as absent."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }
