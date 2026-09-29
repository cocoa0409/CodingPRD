"""Test infrastructure for the condominium conversion registry API.

Importing this package installs the PRD's error_id -> HTTP status map into the
shared validators, so `validate_error` cross-checks status codes for free.
"""

from . import api_errors  # noqa: F401  (registers the error/status map)
from .api_client import ConversionApiClient
from .constants import (
    CLOCK_DEFAULT_UTC,
    POS_SECTION_CODES,
    POS_SECTION_MIN_WORD_COUNT,
    TOTAL_UNDIVIDED_INTEREST_BP,
)
from .test_users import (
    ROLE_HEADERS,
    admin_headers,
    engineer_headers,
    escrow_headers,
    lender_headers,
    peer_headers,
    purchaser_headers,
    regulator_headers,
    sponsor_headers,
    tenant_headers,
)

__all__ = [
    "ConversionApiClient",
    "CLOCK_DEFAULT_UTC",
    "POS_SECTION_CODES",
    "POS_SECTION_MIN_WORD_COUNT",
    "TOTAL_UNDIVIDED_INTEREST_BP",
    "ROLE_HEADERS",
    "admin_headers",
    "engineer_headers",
    "escrow_headers",
    "lender_headers",
    "peer_headers",
    "purchaser_headers",
    "regulator_headers",
    "sponsor_headers",
    "tenant_headers",
]
