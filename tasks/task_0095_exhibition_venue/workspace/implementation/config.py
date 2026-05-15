"""Configuration constants read from scaffold / PRD."""

# Pagination — from response_envelope.pagination_defaults
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Roles — from §1.7 RBAC matrix / PRD §2.1
ROLE_VENUE_ADMIN = "VenueAdmin"
ROLE_VENUE_OPS = "VenueOps"
ROLE_EXHIBITOR = "Exhibitor"
ROLE_SERVICE_PROVIDER = "ServiceProvider"
ROLE_GATE_OPERATOR = "GateOperator"
ROLE_TEST_HARNESS = "TestHarness"

VALID_ROLES = {
    ROLE_VENUE_ADMIN,
    ROLE_VENUE_OPS,
    ROLE_EXHIBITOR,
    ROLE_SERVICE_PROVIDER,
    ROLE_GATE_OPERATOR,
    ROLE_TEST_HARNESS,
}

# Auth header names — from PRD §2.1
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"
