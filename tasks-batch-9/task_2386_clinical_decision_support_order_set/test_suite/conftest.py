"""Pytest fixtures exposing the governance test_helpers infrastructure.

Every test runs against a freshly launched server, so the logical clock always
starts at its documented instant and the database is always empty. Any
precondition a test needs is therefore built through published endpoints by the
composite helpers in `test_helpers.fixtures`.
"""

import pytest
from test_helpers import TEST_USERS, ApiClient, api_client, fixtures


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def clinical_sponsor_headers():
    return TEST_USERS["clinical_sponsor_headers"]


@pytest.fixture
def informatics_builder_headers():
    return TEST_USERS["informatics_builder_headers"]


@pytest.fixture
def peer_reviewer_headers():
    return TEST_USERS["peer_reviewer_headers"]


@pytest.fixture
def specialty_approver_headers():
    return TEST_USERS["specialty_approver_headers"]


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def pharmacy_informaticist_headers():
    return TEST_USERS["pharmacy_informaticist_headers"]


@pytest.fixture
def committee():
    """The standard registered committee cast with per-identity headers.

    The reviewer pools are disjoint from the sponsor, the builder and the
    pharmacist, so no helper trips a segregation-of-duties or self-review
    constraint by accident.
    """
    return fixtures.setup_committee()
