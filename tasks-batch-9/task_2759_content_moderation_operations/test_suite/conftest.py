"""Pytest fixtures exposing the moderation test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ADMIN_ALT_HEADERS,
    LEGAL_HEADERS,
    POLICY_ACTIVATOR_HEADERS,
    POLICY_AUTHOR_HEADERS,
)

# The composite setup fixtures live in test_helpers.fixtures; re-exporting them
# here makes them visible to every test module in this directory.
from test_helpers.fixtures import (  # noqa: F401
    account,
    appeal_under_review,
    assigned_case,
    audited_sample,
    auto_action_case,
    clock_at_t0,
    computed_report,
    decided_case,
    draft_report,
    drawn_sample,
    escalated_case,
    legal_case,
    manual_case,
    pending_case,
    policy_baseline,
    submitted_appeal,
    workforce,
    world,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def trust_safety_admin_headers():
    """Headers for the TrustSafetyAdmin operator."""
    return dict(ADMIN_HEADERS)


@pytest.fixture
def trust_safety_admin_alt_headers():
    """Headers for a second, distinct TrustSafetyAdmin operator."""
    return dict(ADMIN_ALT_HEADERS)


@pytest.fixture
def policy_author_headers():
    """Headers for the PolicyManager who authors policy versions."""
    return dict(POLICY_AUTHOR_HEADERS)


@pytest.fixture
def policy_activator_headers():
    """Headers for the second PolicyManager who activates policy versions."""
    return dict(POLICY_ACTIVATOR_HEADERS)


@pytest.fixture
def legal_counsel_headers():
    """Headers for the LegalCounsel operator."""
    return dict(LEGAL_HEADERS)
