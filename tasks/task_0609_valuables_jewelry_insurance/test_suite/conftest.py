"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so test_helpers is importable) and the server
lifecycle (restarted before every test). These fixtures only wire helpers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]


@pytest.fixture
def repair_shop_headers():
    return TEST_USERS["repair_shop_headers"]
