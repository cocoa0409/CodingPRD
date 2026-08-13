"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def foundry_admin_headers():
    return TEST_USERS["foundry_admin_headers"]


@pytest.fixture
def pattern_maker_headers():
    return TEST_USERS["pattern_maker_headers"]


@pytest.fixture
def melt_supervisor_headers():
    return TEST_USERS["melt_supervisor_headers"]


@pytest.fixture
def spectro_1_headers():
    return TEST_USERS["spectro_1_headers"]


@pytest.fixture
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def qi_1_headers():
    return TEST_USERS["qi_1_headers"]


@pytest.fixture
def wm_1_headers():
    return TEST_USERS["wm_1_headers"]


@pytest.fixture
def wm_2_headers():
    return TEST_USERS["wm_2_headers"]
