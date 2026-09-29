"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def production_coordinator_headers():
    return TEST_USERS["production_coordinator_headers"]


@pytest.fixture
def adaptor_headers():
    return TEST_USERS["adaptor_headers"]


@pytest.fixture
def native_reviewer_headers():
    return TEST_USERS["native_reviewer_headers"]


@pytest.fixture
def casting_director_headers():
    return TEST_USERS["casting_director_headers"]


@pytest.fixture
def voice_talent_headers():
    return TEST_USERS["voice_talent_headers"]


@pytest.fixture
def mix_engineer_headers():
    return TEST_USERS["mix_engineer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
