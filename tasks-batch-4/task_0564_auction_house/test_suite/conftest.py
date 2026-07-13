"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages server
lifecycle (restarting the API before every test). These fixtures only wire up
the client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def settlement_headers():
    return TEST_USERS["settlement_headers"]


@pytest.fixture
def bidder_headers():
    return TEST_USERS["bidder_headers"]


@pytest.fixture
def consignor_headers():
    return TEST_USERS["consignor_headers"]
