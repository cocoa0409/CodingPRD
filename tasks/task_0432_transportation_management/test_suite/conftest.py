"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shipper_ops_headers():
    return TEST_USERS["shipper_ops_headers"]


@pytest.fixture
def carrier_ops_headers():
    return TEST_USERS["carrier_ops_headers"]


@pytest.fixture
def dock_ops_headers():
    return TEST_USERS["dock_ops_headers"]


@pytest.fixture
def freight_auditor_headers():
    return TEST_USERS["freight_auditor_headers"]
