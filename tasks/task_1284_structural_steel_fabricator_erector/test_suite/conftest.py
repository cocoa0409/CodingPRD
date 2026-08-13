"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def fabricator_admin_headers():
    return TEST_USERS["fabricator_admin_headers"]


@pytest.fixture
def detailer_headers():
    return TEST_USERS["detailer_headers"]


@pytest.fixture
def eor_headers():
    return TEST_USERS["eor_headers"]


@pytest.fixture
def foreman_headers():
    return TEST_USERS["foreman_headers"]


@pytest.fixture
def welder_headers():
    return TEST_USERS["welder_headers"]


@pytest.fixture
def qc_inspector_headers():
    return TEST_USERS["qc_inspector_headers"]


@pytest.fixture
def gc_pm_headers():
    return TEST_USERS["gc_pm_headers"]
