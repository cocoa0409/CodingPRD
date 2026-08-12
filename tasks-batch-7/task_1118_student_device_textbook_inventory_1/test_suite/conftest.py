"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["tech_headers"]


@pytest.fixture
def family_headers():
    """Shared Family headers — only for tests whose outcome does not depend on
    ownership (e.g. RBAC denial). Ownership-gated Family calls must use
    test_helpers.make_family_headers(student_id)."""
    return TEST_USERS["family_headers"]
