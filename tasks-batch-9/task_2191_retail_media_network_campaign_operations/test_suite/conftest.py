"""Shared pytest wiring for the retail media network test suite.

The runner restarts the server before every individual test, so each test opens on an
empty database and a logical clock reading its startup instant. Nothing is torn down
here: there is nothing to carry over.

The role fixtures are thin conveniences over the header builders in `test_helpers`.
There is deliberately no `advertiser_user` fixture, because an advertiser seat's
`X-User-ID` is the acting advertiser's own `id` and therefore cannot be known before
the test has created one — use `make_advertiser_user_headers(advertiser["id"])`, or the
`advertiser_headers(world)` shorthand, inside the test.
"""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    BILLING_OPS,
    CATALOG_OPS,
    CREDIT_ANALYST,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    SECOND_ACCOUNT_MANAGER,
    SECOND_BILLING_OPS,
    SECOND_CATALOG_OPS,
    SECOND_CREDIT_ANALYST,
    SECOND_MEASUREMENT_ANALYST,
    SECOND_NETWORK_ADMIN,
    api_client,
    factories,
    register_error_http_statuses,
)


@pytest.fixture(scope="session", autouse=True)
def error_http_statuses():
    """Tell the validators which HTTP status belongs to each documented error.

    With the map registered, asserting an error identifier also asserts its status, so
    an implementation that reports the right identifier under the wrong status fails.
    """
    register_error_http_statuses()


@pytest.fixture(scope="session")
def api():
    """The API client. One instance serves the whole session."""
    return api_client


@pytest.fixture(autouse=True)
def fresh_unique_tokens():
    """Restart the unique-code counter so each test's generated codes start from one."""
    factories.reset_unique_counter()


# --- Role headers ----------------------------------------------------------


@pytest.fixture
def network_admin():
    """Headers for a network administrator."""
    return NETWORK_ADMIN


@pytest.fixture
def second_network_admin():
    """Headers for a different network administrator, for two-operator chains."""
    return SECOND_NETWORK_ADMIN


@pytest.fixture
def account_manager():
    """Headers for an account manager."""
    return ACCOUNT_MANAGER


@pytest.fixture
def second_account_manager():
    """Headers for a different account manager, for two-operator chains."""
    return SECOND_ACCOUNT_MANAGER


@pytest.fixture
def credit_analyst():
    """Headers for a credit analyst."""
    return CREDIT_ANALYST


@pytest.fixture
def second_credit_analyst():
    """Headers for a different credit analyst, for two-operator chains."""
    return SECOND_CREDIT_ANALYST


@pytest.fixture
def measurement_analyst():
    """Headers for a measurement analyst."""
    return MEASUREMENT_ANALYST


@pytest.fixture
def second_measurement_analyst():
    """Headers for a different measurement analyst, for two-operator chains."""
    return SECOND_MEASUREMENT_ANALYST


@pytest.fixture
def billing_ops():
    """Headers for a billing operator."""
    return BILLING_OPS


@pytest.fixture
def second_billing_ops():
    """Headers for a different billing operator, for two-operator chains."""
    return SECOND_BILLING_OPS


@pytest.fixture
def catalog_ops():
    """Headers for a catalog operator."""
    return CATALOG_OPS


@pytest.fixture
def second_catalog_ops():
    """Headers for a different catalog operator, for two-operator chains."""
    return SECOND_CATALOG_OPS


@pytest.fixture
def auction_service():
    """Headers for the auction service."""
    return AUCTION_SERVICE
