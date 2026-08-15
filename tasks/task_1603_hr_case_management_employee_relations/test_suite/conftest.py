"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_investigator_headers,
    make_er_manager_headers,
    make_legal_counsel_headers,
    make_hr_analyst_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def er_manager_headers():
    return TEST_USERS["er_manager_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def hr_analyst_headers():
    return TEST_USERS["hr_analyst_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]
