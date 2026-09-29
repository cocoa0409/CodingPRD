"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """Headers for the reference-data administrator."""
    return ADMIN_HEADERS


@pytest.fixture
def csr_headers():
    """Headers for the investigating customer service representative."""
    return CSR_HEADERS


@pytest.fixture
def supervisor_headers():
    """Headers for the approving billing supervisor."""
    return SUPERVISOR_HEADERS


@pytest.fixture
def technician_headers():
    """Headers for the meter technician."""
    return TECHNICIAN_HEADERS


@pytest.fixture
def clerk_headers():
    """Headers for the utility board clerk."""
    return CLERK_HEADERS
