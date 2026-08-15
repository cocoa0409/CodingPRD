"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def architect_headers():
    return TEST_USERS["architect_headers"]


@pytest.fixture
def production_lead_headers():
    return TEST_USERS["production_lead_headers"]


@pytest.fixture
def label_authority_headers():
    return TEST_USERS["label_authority_headers"]


@pytest.fixture
def qa_inspector_headers():
    return TEST_USERS["qa_inspector_headers"]


@pytest.fixture
def shipping_coordinator_headers():
    return TEST_USERS["shipping_coordinator_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
