"""Shared pytest fixtures for the film extrusion and bag converting suite.

Each test runs against a freshly started server with an empty database, so
every fixture below is a thin accessor: the domain preconditions themselves are
built inside each test through the composite helpers in ``test_helpers``.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The HTTP client used by every test in the suite."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def blend_engineer_headers():
    return TEST_USERS["blend_engineer_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def extrusion_operator_headers():
    return TEST_USERS["extrusion_operator_headers"]


@pytest.fixture
def print_operator_headers():
    return TEST_USERS["print_operator_headers"]


@pytest.fixture
def converting_operator_headers():
    return TEST_USERS["converting_operator_headers"]
