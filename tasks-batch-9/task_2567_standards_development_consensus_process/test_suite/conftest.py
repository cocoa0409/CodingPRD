"""
Shared pytest fixtures for the standards-development consensus API test suite.

The harness restarts the API before every test, so the store is empty and the
logical clock reads its startup instant at the top of each test. Fixtures here
build whatever state a test needs through published endpoints only.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers import fixtures as fx
from test_helpers.test_users import APPEALS_BOARD_HEADERS, STAFF_HEADERS


@pytest.fixture
def api():
    """Client for the API under test."""
    return ApiClient()


@pytest.fixture
def staff_headers():
    """Secretariat headers; the operational identity is opaque."""
    return STAFF_HEADERS


@pytest.fixture
def appeals_headers():
    """Appeals panel headers; the operational identity is opaque."""
    return APPEALS_BOARD_HEADERS


@pytest.fixture
def scenario(api):
    """An empty scenario bound to the client, for tests that build their own state."""
    return fx.Scenario(api)


@pytest.fixture
def balanced_committee(api):
    """Three seats in three interest categories on an ACTIVE committee."""
    return fx.balanced_active_committee(api)


@pytest.fixture
def work_item(api):
    """A scope-approved work item sponsored by the balanced committee."""
    return fx.work_item_in_development(api)


@pytest.fixture
def draft(api):
    """A revision-1 draft in DRAFTING on a work item in development."""
    return fx.work_item_with_draft(api)


@pytest.fixture
def open_ballot(api):
    """An OPEN subcommittee ballot on the revision-1 draft, no votes cast."""
    return fx.open_subcommittee_ballot(api)


@pytest.fixture
def voted_ballot(api):
    """An OPEN subcommittee ballot with two affirmatives and one negative."""
    return fx.voted_subcommittee_ballot(api)


@pytest.fixture
def review_ready_draft(api):
    """A draft whose unanimous subcommittee ballot has been closed."""
    return fx.draft_ready_for_public_review(api)


@pytest.fixture
def reviewed_draft(api):
    """A draft that has run and closed a zero-comment public review."""
    return fx.draft_through_public_review(api)


@pytest.fixture
def consensus_work_item(api):
    """A work item carried through public review and a consensus-body ballot."""
    return fx.consensus_approved_work_item(api)


@pytest.fixture
def published(api):
    """A published standard, with its maintenance dates in place."""
    return fx.published_work_item(api)
