"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def gc_admin_headers():
    return TEST_USERS["gc_admin_headers"]


@pytest.fixture
def buyout_lead_headers():
    return TEST_USERS["buyout_lead_headers"]


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def project_exec_headers():
    return TEST_USERS["project_exec_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def vice_president_headers():
    return TEST_USERS["vice_president_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def supplier_diversity_headers():
    return TEST_USERS["supplier_diversity_headers"]
