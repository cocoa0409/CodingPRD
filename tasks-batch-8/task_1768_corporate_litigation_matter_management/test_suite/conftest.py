"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]


@pytest.fixture
def dgc_headers():
    return TEST_USERS["dgc_headers"]


@pytest.fixture
def gc_headers():
    return TEST_USERS["gc_headers"]


@pytest.fixture
def cfo_headers():
    return TEST_USERS["cfo_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def fin_headers():
    return TEST_USERS["fin_headers"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def board_headers():
    return TEST_USERS["board_headers"]
