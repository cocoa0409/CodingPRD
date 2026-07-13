"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-per-test) and PYTHONPATH are owned by
prd-bench-local-runner; these fixtures only surface the shared client and role
headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, make_member_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is (re)launched by the runner."""
    return api_client


@pytest.fixture
def admin():
    return TEST_USERS["club_admin_headers"]


@pytest.fixture
def staff():
    return TEST_USERS["dock_staff_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def member_hdr():
    """Builder fixture: call member_hdr(member_id) for ownership-gated Member calls."""
    return make_member_headers
