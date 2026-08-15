"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def builder_headers():
    """Shared Builder headers — only for calls that are not ownership-gated.
    For ownership-gated calls use make_builder_headers(builder["id"])."""
    return TEST_USERS["builder_headers"]


@pytest.fixture
def inspector_headers():
    """Shared Inspector headers — only for calls that are not ownership-gated.
    For witnessing/result calls use make_inspector_headers(inspector["id"])."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def rep_headers():
    return TEST_USERS["rep_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def clerk_c_headers():
    return TEST_USERS["clerk_c_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def gis_analyst_headers():
    return TEST_USERS["gis_analyst_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
