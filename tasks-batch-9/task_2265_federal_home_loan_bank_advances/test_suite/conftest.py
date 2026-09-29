"""Shared pytest fixtures for the FHLB Advances Collateral Pledging suite."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402
from test_helpers.fixtures import (  # noqa: E402,F401
    active,
    applicant,
    clock,
    harbor,
    pledging,
    standard_product,
)
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The API client. Stateless, so one instance serves the whole session."""
    return api_client


@pytest.fixture
def system_admin():
    return TEST_USERS["system_admin"]


@pytest.fixture
def credit_officer():
    return TEST_USERS["credit_officer"]


@pytest.fixture
def credit_officer_two():
    return TEST_USERS["credit_officer_two"]


@pytest.fixture
def collateral_custodian():
    return TEST_USERS["collateral_custodian"]


@pytest.fixture
def collateral_review_auditor():
    return TEST_USERS["collateral_review_auditor"]


@pytest.fixture
def community_lending_manager():
    return TEST_USERS["community_lending_manager"]


@pytest.fixture
def unscoped_treasury_officer():
    return TEST_USERS["unscoped_treasury_officer"]
