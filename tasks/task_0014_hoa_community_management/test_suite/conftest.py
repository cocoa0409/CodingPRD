"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_acc_member_headers,
    make_board_president_headers,
    make_board_secretary_headers,
    make_homeowner_headers,
    make_platform_admin_headers,
    make_treasurer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def board_president_headers():
    return TEST_USERS["board_president_headers"]


@pytest.fixture
def board_secretary_headers():
    return TEST_USERS["board_secretary_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def acc_member_headers():
    return TEST_USERS["acc_member_headers"]


@pytest.fixture
def home_owner_headers_shared():
    """Shared HomeOwner header. Use only for tests that do NOT exercise
    ownership (e.g. cross-owner ERR_UNAUTHORIZED)."""
    return TEST_USERS["home_owner_headers"]


@pytest.fixture
def headers_factory():
    """Per-role builder functions; tests mint per-entity headers as needed."""
    return {
        "platform_admin": make_platform_admin_headers,
        "board_president": make_board_president_headers,
        "board_secretary": make_board_secretary_headers,
        "treasurer": make_treasurer_headers,
        "acc_member": make_acc_member_headers,
        "homeowner": make_homeowner_headers,
    }
