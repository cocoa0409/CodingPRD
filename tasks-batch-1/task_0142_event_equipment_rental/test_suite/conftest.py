"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and injects
API_BASE_URL before launching pytest. The server lifecycle (restart before
every test) is owned by prd-bench-local-runner — these fixtures never start,
stop, or health-check the server.
"""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_customer_headers,
    make_rental_agent_headers,
    make_deposit_adjuster_headers,
    anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def agent_headers():
    return TEST_USERS["rental_agent_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["deposit_adjuster_headers"]


@pytest.fixture
def customer_headers():
    """Unowned shared Customer headers — for non-ownership tests only."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def make_customer():
    return make_customer_headers


@pytest.fixture
def make_agent():
    return make_rental_agent_headers


@pytest.fixture
def make_adjuster():
    return make_deposit_adjuster_headers


@pytest.fixture
def anon():
    return anonymous_headers()
