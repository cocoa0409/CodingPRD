"""Pytest fixtures exposing the fire protection test_helpers infrastructure.

The runner restarts the server before every test, so every fixture below builds
its state from scratch through the documented endpoints.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401  (re-exported as fixtures)
    admin_headers,
    client,
    contractor_headers,
    converged_ctx,
    coordinated_ctx,
    design_ctx,
    directory,
    evaluated_ctx,
    iterating_ctx,
    permitted_ctx,
    project_ctx,
    qc_passed_ctx,
    sealed_ctx,
    submitted_ctx,
    under_review_ctx,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def shared_contractor_headers():
    return TEST_USERS["contractor_headers"]
