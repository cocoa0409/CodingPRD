"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_appeal_board_headers,
    make_auditor_headers,
    make_policy_admin_headers,
    make_reviewer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def policy_admin_headers():
    """PlatformPolicyAdmin is an opaque platform role with no tenancy scoping."""
    return make_policy_admin_headers()


@pytest.fixture
def reviewer_headers():
    return make_reviewer_headers()


@pytest.fixture
def second_reviewer_headers():
    """A distinct reviewer identity, for the segregation-of-duties comparisons."""
    return make_reviewer_headers("u-reviewer-2")


@pytest.fixture
def appeal_board_headers():
    return make_appeal_board_headers()


@pytest.fixture
def auditor_headers():
    return make_auditor_headers()
