"""Shared test infrastructure for the mobile driver license issuance API."""

from . import api_errors  # noqa: F401  (registers the error/status map on import)
from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import MdlApiClient  # noqa: F401
from .test_users import (  # noqa: F401
    ADJUDICATOR,
    ADJUDICATOR_ALT,
    ADMIN,
    ADMIN_ALT,
    NO_AUTH_HEADERS,
    PRIVACY_AUDITOR,
    PROOFING_AGENT,
    PROOFING_AGENT_ALT,
    TEST_USERS,
    make_adjudicator_headers,
    make_admin_headers,
    make_holder_headers,
    make_privacy_auditor_headers,
    make_proofing_agent_headers,
    make_verifier_operator_headers,
)

__all__ = [
    "MdlApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "ADMIN",
    "ADMIN_ALT",
    "PROOFING_AGENT",
    "PROOFING_AGENT_ALT",
    "ADJUDICATOR",
    "ADJUDICATOR_ALT",
    "PRIVACY_AUDITOR",
    "NO_AUTH_HEADERS",
    "TEST_USERS",
    "make_holder_headers",
    "make_verifier_operator_headers",
    "make_proofing_agent_headers",
    "make_adjudicator_headers",
    "make_admin_headers",
    "make_privacy_auditor_headers",
]
