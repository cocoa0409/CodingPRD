"""Pytest fixtures exposing the test_helpers infrastructure.

The client is function-scoped on purpose: the harness relaunches the server
(against a fresh, empty database) before every test, so each test must resolve
the base URL for itself rather than reuse a session-scoped client.
"""

import pytest

from test_helpers import ApiClient
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
    VERIFIER_HEADERS,
)


@pytest.fixture
def api() -> ApiClient:
    """API client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def operator_headers() -> dict:
    """PlantOperator auth headers."""
    return OPERATOR_HEADERS


@pytest.fixture
def trader_headers() -> dict:
    """FeedstockTrader auth headers."""
    return TRADER_HEADERS


@pytest.fixture
def analyst_headers() -> dict:
    """QualityAnalyst auth headers."""
    return ANALYST_HEADERS


@pytest.fixture
def officer_headers() -> dict:
    """ComplianceOfficer auth headers (officer A)."""
    return OFFICER_A_HEADERS


@pytest.fixture
def officer_b_headers() -> dict:
    """A second, distinct ComplianceOfficer for segregation-of-duties flows."""
    return OFFICER_B_HEADERS


@pytest.fixture
def verifier_headers() -> dict:
    """IndependentVerifier auth headers."""
    return VERIFIER_HEADERS
