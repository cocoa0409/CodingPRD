"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    COACH_A_HEADERS,
    COACH_B_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    NO_AUTH_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin() -> dict:
    """Headers for the NetworkAdmin operator."""
    return NETWORK_ADMIN_HEADERS


@pytest.fixture
def fiscal() -> dict:
    """Headers for the FiscalOfficer operator."""
    return FISCAL_OFFICER_HEADERS


@pytest.fixture
def coach_a() -> dict:
    """Headers for the first QualityCoach operator."""
    return COACH_A_HEADERS


@pytest.fixture
def coach_b() -> dict:
    """Headers for the second QualityCoach operator."""
    return COACH_B_HEADERS


@pytest.fixture
def anonymous() -> dict:
    """Headers carrying no identity at all."""
    return NO_AUTH_HEADERS
