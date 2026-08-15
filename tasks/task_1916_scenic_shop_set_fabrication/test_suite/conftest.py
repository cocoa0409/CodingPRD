"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shop_admin_headers():
    return TEST_USERS["shop_admin_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def shop_foreman_headers():
    return TEST_USERS["shop_foreman_headers"]


@pytest.fixture
def shop_foreman_other_headers():
    return TEST_USERS["shop_foreman_other_headers"]


@pytest.fixture
def staff_engineer_headers():
    return TEST_USERS["staff_engineer_headers"]


@pytest.fixture
def staff_engineer_preparer_headers():
    return TEST_USERS["staff_engineer_preparer_headers"]


@pytest.fixture
def paint_charge_headers():
    return TEST_USERS["paint_charge_headers"]


@pytest.fixture
def transport_coordinator_headers():
    return TEST_USERS["transport_coordinator_headers"]


@pytest.fixture
def client_pm_headers():
    """Fallback ClientPM headers — safe only for tests that do not exercise
    ownership. Ownership-gated calls must use make_client_pm_headers(client_id)."""
    return TEST_USERS["client_pm_headers"]


@pytest.fixture
def super_user_headers():
    """Headers with a role outside the declared set (PRD §2.1)."""
    return TEST_USERS["super_user_headers"]
