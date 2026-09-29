"""Shared pytest fixtures for the Juried Exhibition Administration suite.

The API server is restarted before every individual test, so each test starts
against an empty database and builds whatever state it needs through the
documented endpoints.
"""

import pytest

from test_helpers import (
    CALL_MANAGER,
    FINANCE_A,
    FINANCE_B,
    JURY_CHAIR_A,
    JURY_CHAIR_B,
    REGISTRAR,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def call_manager() -> dict:
    return CALL_MANAGER


@pytest.fixture
def jury_chair() -> dict:
    return JURY_CHAIR_A


@pytest.fixture
def other_jury_chair() -> dict:
    return JURY_CHAIR_B


@pytest.fixture
def registrar() -> dict:
    return REGISTRAR


@pytest.fixture
def finance_officer() -> dict:
    return FINANCE_A


@pytest.fixture
def other_finance_officer() -> dict:
    return FINANCE_B
