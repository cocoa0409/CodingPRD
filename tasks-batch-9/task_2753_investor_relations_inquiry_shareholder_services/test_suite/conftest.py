"""Pytest fixtures exposing the test_helpers infrastructure.

The server is restarted before every test, so each test starts against an empty
store with the logical clock at its default instant. All state is therefore
built inside the test through the documented endpoints.
"""

import pytest

from test_helpers import (
    ApiClient,
    DISCLOSURE_OFFICER,
    IR_ADMIN,
    IR_ANALYST,
    TRANSFER_AGENT,
    fixtures,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return ApiClient()


@pytest.fixture
def ir_admin_headers():
    return IR_ADMIN


@pytest.fixture
def ir_analyst_headers():
    return IR_ANALYST


@pytest.fixture
def disclosure_officer_headers():
    return DISCLOSURE_OFFICER


@pytest.fixture
def transfer_agent_headers():
    return TRANSFER_AGENT


@pytest.fixture
def company(api: ApiClient):
    """One issuer with the default register size and no blackout window."""
    return fixtures.create_company(api)


@pytest.fixture
def register(api: ApiClient):
    """An issuer plus one institutional holder, keyed by ``company_id``/``holder``."""
    return fixtures.build_register_world(api)
