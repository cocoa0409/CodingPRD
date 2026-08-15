"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; these fixtures only bridge
the pre-built role headers and the shared API client into test functions.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ap_clerk_headers():
    return TEST_USERS["ap_clerk_headers"]


@pytest.fixture
def tax_specialist_headers():
    return TEST_USERS["tax_specialist_headers"]


@pytest.fixture
def tax_transmitter_headers():
    return TEST_USERS["tax_transmitter_headers"]


@pytest.fixture
def tax_admin_headers():
    return TEST_USERS["tax_admin_headers"]


@pytest.fixture
def irs_system_headers():
    return TEST_USERS["irs_system_headers"]


@pytest.fixture
def vendor_portal_headers():
    return TEST_USERS["vendor_portal_headers"]
