"""Pytest fixtures exposing test_helpers infrastructure.

PRD.md section 2.1 splits the eight roles into opaque identities, whose
``X-User-ID`` is never resolved to a stored row, and entity-backed identities,
which must carry the id of a real row created by the test itself. Only the
opaque roles get a ready-made headers fixture here; the four shop-floor
technician roles and Customer are minted per test by the composite fixtures in
test_helpers, which return the matching headers alongside the row they create.
"""

import pytest

from test_helpers import (
    ApiClient,
    NO_AUTH_HEADERS,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlantAdmin — an opaque identity needing no stored row."""
    return TEST_USERS["PlantAdmin"]


@pytest.fixture
def planner_headers():
    """LogisticsPlanner — an opaque identity needing no stored row."""
    return TEST_USERS["LogisticsPlanner"]


@pytest.fixture
def warranty_agent_headers():
    """WarrantyAgent — an opaque identity needing no stored row."""
    return TEST_USERS["WarrantyAgent"]


@pytest.fixture
def no_auth_headers():
    """Empty headers, for tests asserting the missing-identity path."""
    return NO_AUTH_HEADERS


@pytest.fixture
def unresolvable_role_headers():
    """Well-formed headers whose identity resolves to no row, keyed by role.

    Intended only for identity-failure assertions; using one on a happy path is
    a guaranteed identity failure rather than a shortcut.
    """
    return {
        role: TEST_USERS[role]
        for role in (
            "ResinTechnician",
            "MoldingOperator",
            "AssemblyTechnician",
            "QualityInspector",
            "Customer",
        )
    }
