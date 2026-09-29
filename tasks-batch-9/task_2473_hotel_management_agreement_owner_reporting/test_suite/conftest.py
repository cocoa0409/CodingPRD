"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, Scenario, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture()
def scenario(api: ApiClient) -> Scenario:
    """Chain builder for composing pre-state through the declared endpoints."""
    return Scenario(api)


@pytest.fixture(scope="session")
def users():
    return TEST_USERS
