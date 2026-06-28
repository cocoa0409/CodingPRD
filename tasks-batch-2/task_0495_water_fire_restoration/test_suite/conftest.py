"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_technician_headers,
    make_admin_headers,
    make_dispatcher_headers,
    make_estimator_headers,
    make_adjuster_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]
