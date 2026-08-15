"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def item_writer_headers():
    return TEST_USERS["item_writer_headers"]


@pytest.fixture
def content_reviewer_headers():
    return TEST_USERS["content_reviewer_headers"]


@pytest.fixture
def bias_reviewer_headers():
    return TEST_USERS["bias_reviewer_headers"]


@pytest.fixture
def psychometrician_headers():
    return TEST_USERS["psychometrician_headers"]


@pytest.fixture
def test_assembler_headers():
    return TEST_USERS["test_assembler_headers"]


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def translation_specialist_headers():
    return TEST_USERS["translation_specialist_headers"]
