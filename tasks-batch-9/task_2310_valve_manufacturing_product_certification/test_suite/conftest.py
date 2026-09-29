"""Pytest fixtures exposing the Valve Manufacturing test infrastructure.

The runner sets PYTHONPATH so ``test_helpers`` is importable without sys.path
hacks. The runner also restarts the API server before every individual test, so
each test starts against an empty database and builds all of its own state
through the endpoints the PRD declares.
"""

import pytest

from test_helpers import (
    ROLE_FIELD_SERVICE_COORDINATOR,
    ROLE_MONOGRAM_AUDITOR,
    ROLE_PROCUREMENT_SPECIALIST,
    ROLE_PRODUCT_ENGINEER,
    ROLE_QUALITY_MANAGER,
    ROLE_TEST_TECHNICIAN,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# ─── One fixture per role that carries an opaque identity (PRD §2.1) ───


@pytest.fixture
def product_engineer_headers():
    return TEST_USERS[ROLE_PRODUCT_ENGINEER]


@pytest.fixture
def procurement_specialist_headers():
    return TEST_USERS[ROLE_PROCUREMENT_SPECIALIST]


@pytest.fixture
def test_technician_headers():
    return TEST_USERS[ROLE_TEST_TECHNICIAN]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS[ROLE_QUALITY_MANAGER]


@pytest.fixture
def monogram_auditor_headers():
    return TEST_USERS[ROLE_MONOGRAM_AUDITOR]


@pytest.fixture
def field_service_coordinator_headers():
    return TEST_USERS[ROLE_FIELD_SERVICE_COORDINATOR]


# ``SupplierRep`` deliberately has no shared fixture: when ``X-User-Role`` is
# ``SupplierRep``, ``X-User-ID`` is the ``id`` of the acting ``Foundry``, so its
# headers must be built per foundry with ``make_supplier_rep_headers(foundry_id)``.
