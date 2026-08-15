"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_admin_headers,
    make_hm_headers,
    make_do_headers,
    make_co_headers,
    make_interviewer_headers,
    make_candidate_headers,
    make_vendorrep_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def hm_headers():
    return TEST_USERS["hm_headers"]


@pytest.fixture
def hm2_headers():
    return TEST_USERS["hm2_headers"]


@pytest.fixture
def do_headers():
    return TEST_USERS["do_headers"]


@pytest.fixture
def co_headers():
    return TEST_USERS["co_headers"]


# Entity-backed header builders — fixtures MUST be built per entity id.
@pytest.fixture
def interviewer_headers_factory():
    return make_interviewer_headers


@pytest.fixture
def candidate_headers_factory():
    return make_candidate_headers


@pytest.fixture
def vendorrep_headers_factory():
    return make_vendorrep_headers
