import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, ApiClient, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture(scope="session")
def users() -> dict:
    return TEST_USERS
