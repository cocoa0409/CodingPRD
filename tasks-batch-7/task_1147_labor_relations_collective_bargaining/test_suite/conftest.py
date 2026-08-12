"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def lr_admin_headers():
    return TEST_USERS["lr_admin_headers"]


@pytest.fixture
def lr_manager_headers():
    return TEST_USERS["lr_manager_headers"]


@pytest.fixture
def negotiator_headers():
    return TEST_USERS["negotiator_headers"]


@pytest.fixture
def chief_negotiator_headers():
    return TEST_USERS["chief_negotiator_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def union_representative_headers():
    return TEST_USERS["union_representative_headers"]
