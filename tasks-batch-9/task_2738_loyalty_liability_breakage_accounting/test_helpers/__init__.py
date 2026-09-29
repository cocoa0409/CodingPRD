"""
Shared test infrastructure for the Loyalty Liability & Breakage Accounting API.

The layers are:

- ``constants``   — roles, enum values, the reference programme configuration and
                    the rounding discipline the contract mandates.
- ``types``       — the field inventory of every resource and of the envelope.
- ``api_errors``  — every error_id with its HTTP status, registered with the
                    generic validators.
- ``api_client``  — one method per endpoint, with ISO-8601 canonicalisation.
- ``test_users``  — acting identities, opaque and entity-backed.
- ``factories``   — request-body builders.
- ``assertions``  — envelope shortcuts and the domain's accounting identities.
- ``fixtures``    — composite setup that drives the real API.
"""

from test_helpers.api_client import ApiClient, api_client, canonical_timestamp, raw_json
from test_helpers.api_errors import (
    ERROR_HTTP_STATUS,
    HTTP_STATUS_CODES,
    NOT_FOUND_CODES,
    ApiErrorId,
)

__all__ = [
    "ApiClient",
    "api_client",
    "canonical_timestamp",
    "raw_json",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_CODES",
]
