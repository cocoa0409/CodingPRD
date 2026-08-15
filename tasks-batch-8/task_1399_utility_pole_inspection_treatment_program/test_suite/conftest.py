"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def qa_reviewer_headers():
    return TEST_USERS["qa_reviewer_headers"]


@pytest.fixture
def contractor_headers():
    # Fallback only: ownership-gated calls must use make_contractor_headers(crew_id).
    return TEST_USERS["contractor_headers"]


@pytest.fixture
def attacher_rep_headers():
    return TEST_USERS["attacher_rep_headers"]
