"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_risk_owner_headers,
    make_risk_manager_headers,
    make_control_owner_headers,
    make_board_reporter_headers,
    make_internal_auditor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# Per-role header fixtures — shared constants for opaque roles (PRD §2.1).
@pytest.fixture
def risk_owner_headers():
    return TEST_USERS["risk_owner_headers"]


@pytest.fixture
def risk_owner_2_headers():
    return TEST_USERS["risk_owner_2_headers"]


@pytest.fixture
def risk_manager_headers():
    return TEST_USERS["risk_manager_headers"]


@pytest.fixture
def risk_manager_2_headers():
    return TEST_USERS["risk_manager_2_headers"]


@pytest.fixture
def control_owner_headers():
    return TEST_USERS["control_owner_headers"]


@pytest.fixture
def board_reporter_headers():
    return TEST_USERS["board_reporter_headers"]


@pytest.fixture
def internal_auditor_headers():
    return TEST_USERS["internal_auditor_headers"]
