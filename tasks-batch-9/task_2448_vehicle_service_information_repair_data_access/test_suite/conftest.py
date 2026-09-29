"""Pytest fixtures exposing test_helpers infrastructure.

The two entity-backed roles — ``ShopManager`` and ``Technician`` — cannot have
static fixtures, because their ``X-User-ID`` must be the id of a live Shop or
Technician row; tests build those headers from the entities they create.
"""

import pytest

from test_helpers import (
    COMPLIANCE_OFFICER_1_USER_ID,
    COMPLIANCE_OFFICER_2_USER_ID,
    CONTENT_PUBLISHER_1_USER_ID,
    CONTENT_PUBLISHER_2_USER_ID,
    ApiClient,
    api_client,
    make_compliance_officer_headers,
    make_content_publisher_headers,
    make_platform_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return make_platform_admin_headers()


@pytest.fixture
def content_publisher_headers():
    return make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)


@pytest.fixture
def other_content_publisher_headers():
    return make_content_publisher_headers(CONTENT_PUBLISHER_2_USER_ID)


@pytest.fixture
def compliance_officer_headers():
    return make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID)


@pytest.fixture
def other_compliance_officer_headers():
    return make_compliance_officer_headers(COMPLIANCE_OFFICER_2_USER_ID)
