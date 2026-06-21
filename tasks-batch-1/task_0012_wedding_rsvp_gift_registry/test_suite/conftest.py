"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_couple_headers,
    make_guest_self_headers,
    make_platform_admin_headers,
    make_platform_integration_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_integration_headers():
    return TEST_USERS["platform_integration_headers"]


@pytest.fixture
def couple_headers_shared():
    """Shared Couple header constant. Use only for tests that do NOT exercise
    ownership (e.g., negative tests or tests whose wedding's `couple_user_id`
    matches this constant's user id by construction).
    """
    return TEST_USERS["couple_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing per-role builder functions so tests can mint per-entity
    headers."""
    return {
        "couple": make_couple_headers,
        "guest_self": make_guest_self_headers,
        "platform_admin": make_platform_admin_headers,
        "platform_integration": make_platform_integration_headers,
    }
