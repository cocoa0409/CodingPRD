"""Test infrastructure for the Scholarly Journal Peer Review & Publishing API.

Importing this package registers the error_id -> HTTP status map with the
framework validators, so `validate_error()` cross-checks status codes.
"""

from . import assertions, constants, factories, fixtures  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .test_users import (  # noqa: F401
    PRODUCTION_STAFF_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    TEST_USERS,
    make_author_headers,
    make_editor_in_chief_headers,
    make_handling_editor_headers,
    make_production_staff_headers,
    make_reviewer_headers,
    make_system_admin_headers,
    headers_without_role,
    headers_without_user_id,
)
from .types import UserRole  # noqa: F401
