"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def site_host_headers():
    return TEST_USERS["site_host_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def route_operator_headers():
    return TEST_USERS["route_operator_headers"]


@pytest.fixture
def processing_partner_headers():
    return TEST_USERS["processing_partner_headers"]


@pytest.fixture
def municipal_auditor_headers():
    return TEST_USERS["municipal_auditor_headers"]
