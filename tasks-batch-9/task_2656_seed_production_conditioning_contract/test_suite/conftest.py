"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture(scope="session")
def users() -> dict:
    return TEST_USERS
