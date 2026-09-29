"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_appeal_panelist_headers,
    make_evaluator_headers,
    make_hr_admin_headers,
    make_teacher_headers,
    make_union_rep_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def hr_admin_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def hr_admin_2_headers():
    return TEST_USERS["hr_admin_2_headers"]


@pytest.fixture
def union_rep_headers():
    return TEST_USERS["union_rep_headers"]


@pytest.fixture
def evaluator_headers():
    return TEST_USERS["evaluator_headers"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def appeal_panelist_headers():
    return TEST_USERS["appeal_panelist_headers"]


@pytest.fixture
def evaluator_headers_for():
    return make_evaluator_headers


@pytest.fixture
def teacher_headers_for():
    return make_teacher_headers


@pytest.fixture
def panelist_headers_for():
    return make_appeal_panelist_headers


@pytest.fixture
def hr_admin_headers_for():
    return make_hr_admin_headers


@pytest.fixture
def union_rep_headers_for():
    return make_union_rep_headers
