"""Shared pytest fixtures for the Comics Direct Market Publishing API suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client, shared for the whole session."""
    return api_client


@pytest.fixture
def editor_in_chief_headers() -> dict:
    """`EditorInChief`: the title portfolio and the creative-terms surface."""
    return TEST_USERS["editor_in_chief_headers"]


@pytest.fixture
def managing_editor_headers() -> dict:
    """`ManagingEditor`: the issue slate and the production board."""
    return TEST_USERS["managing_editor_headers"]


@pytest.fixture
def sales_director_headers() -> dict:
    """`SalesDirector`: catalogs, covers, retailer accounts, cut-off and release."""
    return TEST_USERS["sales_director_headers"]


@pytest.fixture
def royalty_accountant_headers() -> dict:
    """`RoyaltyAccountant`: revenue events and royalty statements."""
    return TEST_USERS["royalty_accountant_headers"]


@pytest.fixture
def second_royalty_accountant_headers() -> dict:
    """A second `RoyaltyAccountant` operator, for segregation of duties."""
    return TEST_USERS["royalty_accountant_2_headers"]


@pytest.fixture
def creator_headers() -> dict:
    """A `Creator` identity not backed by any registered creator record.

    Ownership-gated calls must instead use `make_creator_headers(creator["id"])`.
    """
    return TEST_USERS["creator_headers"]


@pytest.fixture
def retailer_headers() -> dict:
    """A `Retailer` identity not backed by any registered retailer record.

    Ownership-gated calls must instead use `make_retailer_headers(retailer["id"])`.
    """
    return TEST_USERS["retailer_headers"]
