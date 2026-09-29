"""Shared pytest fixtures for the Instant Payments Participation & Liquidity suite.

The harness restarts the service before each test, so every test begins against
an empty database and builds its own preconditions through declared endpoints.
The client itself is stateless, so one instance is shared for the whole session.
"""

import pytest

from test_helpers import (
    ApiClient,
    CORE_BANKING_SYSTEM,
    FRAUD_REVIEWER,
    LIQUIDITY_OFFICER,
    NETWORK_OPERATOR,
    PAYMENT_OPERATOR_ALPHA,
    PAYMENT_OPERATOR_BETA,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client under test. Server lifecycle belongs to the runner."""
    return ApiClient()


@pytest.fixture()
def operator() -> dict:
    """`NetworkOperator` headers: the rail operator who drives clearing and the day."""
    return NETWORK_OPERATOR


@pytest.fixture()
def officer() -> dict:
    """`LiquidityOfficer` headers: opens positions, funds them, acknowledges alerts."""
    return LIQUIDITY_OFFICER


@pytest.fixture()
def alpha_ops() -> dict:
    """`PaymentOperator` headers for the sending bank's payments desk."""
    return PAYMENT_OPERATOR_ALPHA


@pytest.fixture()
def beta_ops() -> dict:
    """`PaymentOperator` headers for the receiving bank's payments desk."""
    return PAYMENT_OPERATOR_BETA


@pytest.fixture()
def reviewer() -> dict:
    """`FraudReviewer` headers: takes and decides held-transfer reviews."""
    return FRAUD_REVIEWER


@pytest.fixture()
def core_platform() -> dict:
    """`CoreBankingSystem` headers: submits reconciliation runs."""
    return CORE_BANKING_SYSTEM
