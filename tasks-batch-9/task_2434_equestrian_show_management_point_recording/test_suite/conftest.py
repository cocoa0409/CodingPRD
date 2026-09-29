"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def show_secretary_headers() -> dict:
    return TEST_USERS["show_secretary_headers"]


@pytest.fixture
def federation_officer_headers() -> dict:
    return TEST_USERS["federation_officer_headers"]


@pytest.fixture
def ring_master_headers() -> dict:
    return TEST_USERS["ring_master_headers"]


@pytest.fixture
def grounds_manager_headers() -> dict:
    return TEST_USERS["grounds_manager_headers"]


@pytest.fixture
def exhibitor_headers() -> dict:
    """Shared Exhibitor headers.

    Only for calls that never reach an identity check: an `Exhibitor`'s
    ``X-User-ID`` must resolve to a stored `Rider`, so use
    ``make_exhibitor_headers(rider["id"])`` for every entry submission,
    class entry, payment and withdrawal.
    """
    return TEST_USERS["exhibitor_headers"]


@pytest.fixture
def judge_headers() -> dict:
    """Shared Judge headers; use ``make_judge_headers(official["id"])`` for cards."""
    return TEST_USERS["judge_headers"]


@pytest.fixture
def steward_headers() -> dict:
    """Shared Steward headers; use ``make_steward_headers(official["id"])`` for cases."""
    return TEST_USERS["steward_headers"]
