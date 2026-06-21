"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the
server lifecycle (restarting it before every test so each test sees an empty
database). conftest only wires up fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def officer_headers():
    """LicensingOfficer (opaque operator identity)."""
    return TEST_USERS["licensing_officer_headers"]


@pytest.fixture
def inspector_headers():
    """InspectionOfficer (opaque operator identity)."""
    return TEST_USERS["inspection_officer_headers"]


@pytest.fixture
def applicant_headers():
    """Applicant fallback constant (non-ownership calls only)."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
