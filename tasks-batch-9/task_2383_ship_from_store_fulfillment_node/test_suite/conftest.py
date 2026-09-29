"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_store_associate_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def associate_headers():
    """Unowned StoreAssociate identity — only for calls where no node scope is
    evaluated. Node-scoped calls must build headers per node."""
    return TEST_USERS["store_associate_headers"]


@pytest.fixture
def carrier_headers():
    return TEST_USERS["carrier_coordinator_headers"]


@pytest.fixture
def care_headers():
    return TEST_USERS["customer_care_headers"]


@pytest.fixture
def associate_for():
    """Factory fixture: ``associate_for(store_id)`` → StoreAssociate headers
    scoped to that node."""
    return make_store_associate_headers
