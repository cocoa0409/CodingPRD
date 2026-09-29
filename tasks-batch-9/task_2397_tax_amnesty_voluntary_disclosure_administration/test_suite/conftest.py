"""Pytest bridge between the shared helper package and the test modules.

The suite runs against a freshly launched server for every test, so no fixture
here holds business state — only the client and the identity headers of the
five roles PRD §2.1 recognizes.
"""

import os
import sys

import pytest

# Make the sibling ``test_helpers`` package importable regardless of how pytest
# was invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, ApiClient, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client covering every endpoint the PRD §4 table declares."""
    return api_client


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def disclosure_officer_headers():
    return TEST_USERS["disclosure_officer_headers"]


@pytest.fixture
def second_disclosure_officer_headers():
    return TEST_USERS["second_disclosure_officer_headers"]


@pytest.fixture
def third_disclosure_officer_headers():
    return TEST_USERS["third_disclosure_officer_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def second_compliance_auditor_headers():
    return TEST_USERS["second_compliance_auditor_headers"]
