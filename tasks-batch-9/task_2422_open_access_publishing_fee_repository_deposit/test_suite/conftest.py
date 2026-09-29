"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def agreement_admin_headers() -> dict:
    return TEST_USERS["agreement_admin_headers"]


@pytest.fixture
def librarian_headers() -> dict:
    return TEST_USERS["librarian_headers"]


@pytest.fixture
def fund_manager_headers() -> dict:
    return TEST_USERS["fund_manager_headers"]


@pytest.fixture
def fund_payer_headers() -> dict:
    return TEST_USERS["fund_payer_headers"]


@pytest.fixture
def curator_headers() -> dict:
    return TEST_USERS["curator_headers"]


@pytest.fixture
def corresponding_author_headers() -> dict:
    """Shared CorrespondingAuthor headers.

    Only for calls that never pass an ownership check: use
    ``make_corresponding_author_headers(author["id"])`` whenever the call is
    ownership-gated.
    """
    return TEST_USERS["corresponding_author_headers"]
