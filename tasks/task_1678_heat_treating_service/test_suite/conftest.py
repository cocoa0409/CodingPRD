"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_service_rep_headers():
    return TEST_USERS["customer_service_rep"]


@pytest.fixture
def shop_scheduler_headers():
    return TEST_USERS["shop_scheduler"]


@pytest.fixture
def furnace_operator_headers():
    return TEST_USERS["furnace_operator"]


@pytest.fixture
def calibration_tech_headers():
    return TEST_USERS["calibration_tech"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer"]


@pytest.fixture
def quality_engineer_2_headers():
    return TEST_USERS["quality_engineer_2"]


@pytest.fixture
def nadcap_auditor_headers():
    return TEST_USERS["nadcap_auditor"]
