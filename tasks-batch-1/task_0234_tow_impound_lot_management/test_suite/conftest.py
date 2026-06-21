"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; this file
only wires test_helpers into pytest fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def lot_operator_headers():
    return TEST_USERS["lot_operator_headers"]


@pytest.fixture
def police_officer_headers():
    return TEST_USERS["police_officer_headers"]


@pytest.fixture
def claimant_headers():
    return TEST_USERS["claimant_headers"]


@pytest.fixture
def auction_official_headers():
    return TEST_USERS["auction_official_headers"]


@pytest.fixture
def tow_provider_headers():
    return TEST_USERS["tow_provider_headers"]
