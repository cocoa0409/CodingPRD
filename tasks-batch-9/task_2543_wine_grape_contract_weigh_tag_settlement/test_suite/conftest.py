"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_grower_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def scale_operator_headers():
    return TEST_USERS["scale_operator_headers"]


@pytest.fixture
def lab_tech_headers():
    return TEST_USERS["lab_tech_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def unbound_grower_headers():
    """Producer headers whose `X-User-ID` is bound to no producer row. Only for
    calls that never reach an ownership comparison."""
    return TEST_USERS["grower_headers"]


@pytest.fixture
def grower_headers_for():
    """Factory returning producer headers bound to a specific producer `id`."""
    return make_grower_headers
