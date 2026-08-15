"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def gc_pm_headers():
    return TEST_USERS["gc_pm_headers"]


@pytest.fixture
def gc_inspector_headers():
    return TEST_USERS["gc_inspector_headers"]


@pytest.fixture
def owner_rep_headers():
    return TEST_USERS["owner_rep_headers"]


@pytest.fixture
def subcontractor_headers():
    return TEST_USERS["subcontractor_headers"]
