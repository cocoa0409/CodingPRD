"""Test infrastructure for the Government Cloud Authorization Program API.

Layout:

- ``api_client``  — one method per PRD 4 endpoint
- ``api_errors``  — error identifiers plus the PRD 5 error -> HTTP status map
- ``types``       — enum vocabularies and role names
- ``constants``   — business figures (rates, allowances, thresholds, deadlines)
- ``factories``   — request payload builders with ``**overrides``
- ``assertions``  — domain assertions, instant arithmetic, derived figures
- ``test_users``  — acting identities and header builders
- ``fixtures``    — composite state builders for the workflow progressions
"""

from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, VALIDATION_TIER, register_error_status_map

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "VALIDATION_TIER",
    "register_error_status_map",
]
