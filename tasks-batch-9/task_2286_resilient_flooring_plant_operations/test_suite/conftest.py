"""Pytest fixtures exposing the test_helpers infrastructure.

This module is a thin bridge only: all behaviour lives in ``test_helpers``.
Importing ``test_helpers`` also registers the PRD's error-code to HTTP-status
map with the framework validators.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The endpoint-per-method HTTP client."""
    return api_client


@pytest.fixture
def plant_admin_headers() -> dict:
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def formulator_headers() -> dict:
    return TEST_USERS["formulator_headers"]


@pytest.fixture
def formulator_b_headers() -> dict:
    return TEST_USERS["formulator_b_headers"]


@pytest.fixture
def technical_director_headers() -> dict:
    return TEST_USERS["technical_director_headers"]


@pytest.fixture
def technical_director_b_headers() -> dict:
    return TEST_USERS["technical_director_b_headers"]


@pytest.fixture
def qa_technician_headers() -> dict:
    return TEST_USERS["qa_technician_headers"]


@pytest.fixture
def qa_technician_b_headers() -> dict:
    return TEST_USERS["qa_technician_b_headers"]


@pytest.fixture
def production_planner_headers() -> dict:
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def warranty_adjuster_headers() -> dict:
    return TEST_USERS["warranty_adjuster_headers"]


@pytest.fixture
def warranty_adjuster_b_headers() -> dict:
    return TEST_USERS["warranty_adjuster_b_headers"]
