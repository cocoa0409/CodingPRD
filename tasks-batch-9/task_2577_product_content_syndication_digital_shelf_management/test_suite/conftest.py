"""Shared pytest configuration for the Product Content Syndication & Digital
Shelf API suite.

The server is started, and its database reset, by the harness before each test,
so every fixture below builds the state it needs from scratch through the
documented endpoints.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from test_helpers.test_users import (  # noqa: E402
    make_account_team_headers,
    make_brand_approver_headers,
    make_content_author_headers,
    make_legal_reviewer_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

# Composite world fixtures live in test_helpers.fixtures; importing them here
# publishes them to every test module in this directory.
from test_helpers.fixtures import (  # noqa: E402,F401
    alpha_beta_world,
    bigbox_world,
    bigbox_world_capacity_6,
    bigbox_world_single_window,
    clock_at_base,
    flag_pair_world,
    mega_world,
    shop_world,
    simplemart_world,
    simplemart_world_auto_live,
    simplemart_world_draft_request,
    simplemart_world_unpinned,
    taxonomy_only_world,
    tight_description_world,
)


@pytest.fixture
def admin_headers():
    return make_shelf_admin_headers()


@pytest.fixture
def author_headers():
    return make_content_author_headers()


@pytest.fixture
def legal_headers():
    return make_legal_reviewer_headers()


@pytest.fixture
def brand_headers():
    return make_brand_approver_headers()


@pytest.fixture
def operator_headers():
    return make_syndication_operator_headers()


@pytest.fixture
def account_team_headers():
    return make_account_team_headers()
