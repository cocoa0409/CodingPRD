"""
Test infrastructure for the Urology Practice & In-Office Procedure Suite API.

``constants`` holds the contract's vocabulary and numeric thresholds, ``types``
the entity shapes, ``api_client`` one method per endpoint, ``api_errors`` the
error catalogue and its HTTP statuses, ``assertions`` the domain assertions,
``factories`` the request payload builders, ``test_users`` the seven role
identities, and ``fixtures`` the composite setup flows.
"""

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .test_users import (  # noqa: F401
    PRACTICE_ADMIN_USER_ID,
    PRACTICE_ADMIN_USER_ID_ALT,
    make_headers,
    make_headers_blank_user_id,
    make_headers_missing_role,
    make_headers_missing_user_id,
    make_pathology_liaison_headers,
    make_pelvic_health_coordinator_headers,
    make_practice_admin_headers,
    make_procedure_nurse_headers,
    make_scheduler_headers,
    make_sterile_processing_tech_headers,
    make_urologist_headers,
)

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
]
