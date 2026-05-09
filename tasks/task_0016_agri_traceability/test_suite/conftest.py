"""Pytest fixtures exposing test_helpers infrastructure for the Agri-Traceability API."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# Shared role-header fixtures. For owner-gated calls, tests must instead build
# headers with make_grower_headers / make_distributor_headers from test_helpers.

@pytest.fixture
def grower_headers():
    return TEST_USERS["grower_headers"]


@pytest.fixture
def grower_headers_alt():
    return TEST_USERS["grower_headers_alt"]


@pytest.fixture
def distributor_headers():
    return TEST_USERS["distributor_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_headers_alt():
    return TEST_USERS["inspector_headers_alt"]


@pytest.fixture
def regulatory_headers():
    return TEST_USERS["regulatory_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]
