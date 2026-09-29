"""Shared infrastructure for the Municipal Clerk Records & Ordinance
Codification test suite.

Importing this package gives a test everything it needs:

* ``api_client`` -- one method per endpoint declared in PRD section 4.
* ``factories``  -- payload builders whose defaults already satisfy PRD shape rules.
* ``fixtures``   -- composite setup builders that drive entities into a state.
* ``assertions`` -- domain assertions for the invariants PRD sections 2 and 3 declare.
* ``constants``  -- every named business constant the PRD fixes.
* ``api_errors`` -- the error catalogue of PRD section 5 with its HTTP mapping.
* ``test_users`` -- pre-built auth headers for the roles of PRD 2.1.

Importing ``api_errors`` also registers the error-id to HTTP-status mapping with
the runner's validators, so ``validate_error`` can check the status code without
each test restating it.
"""

from . import (  # noqa: F401
    api_errors,
    assertions,
    constants,
    factories,
    fixtures,
    test_users,
    types,
)
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_all_cents_integers,
    assert_ascending_by,
    assert_axes,
    assert_cents,
    assert_common_fields,
    assert_contains_id,
    assert_custody_triple,
    assert_envelope_meta,
    assert_excludes_id,
    assert_fee_ledger,
    assert_fields,
    assert_ids_equal,
    assert_initial_version,
    assert_invoice,
    assert_meeting_notice_mirror,
    assert_no_mirrored_notice,
    assert_nulls,
    assert_pagination_meta,
    assert_response_type,
    assert_section_refs,
    assert_status,
    assert_version_advanced_by,
    assert_vote_arithmetic,
)
from .constants import (
    API_PREFIX,
    DEFAULT_CLOCK_DATE,
    DEFAULT_CLOCK_UTC,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
    STAFF_ROLES,
)
from .test_users import (
    ANONYMOUS,
    ANONYMOUS_ALT,
    CITY_CLERK,
    CITY_CLERK_ALT,
    CODIFICATION_EDITOR,
    CODIFICATION_EDITOR_ALT,
    CODIFICATION_EDITOR_FOURTH,
    CODIFICATION_EDITOR_THIRD,
    DEPUTY_CLERK,
    DEPUTY_CLERK_ALT,
    NO_AUTH_HEADERS,
    PRESIDING_OFFICER,
    RECORDS_OFFICER,
    RECORDS_OFFICER_ALT,
    STAFF_HEADERS,
    TEST_USERS,
    UNKNOWN_ROLE_HEADERS,
    make_headers,
    make_requester_headers,
)
from .types import Entity, EntityList, Headers, Payload

__all__ = [
    # modules
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    # client
    "ApiClient",
    "api_client",
    # errors
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    # assertions
    "assert_all_cents_integers",
    "assert_ascending_by",
    "assert_axes",
    "assert_cents",
    "assert_common_fields",
    "assert_contains_id",
    "assert_custody_triple",
    "assert_envelope_meta",
    "assert_excludes_id",
    "assert_fee_ledger",
    "assert_fields",
    "assert_ids_equal",
    "assert_initial_version",
    "assert_invoice",
    "assert_meeting_notice_mirror",
    "assert_no_mirrored_notice",
    "assert_nulls",
    "assert_pagination_meta",
    "assert_response_type",
    "assert_section_refs",
    "assert_status",
    "assert_version_advanced_by",
    "assert_vote_arithmetic",
    # constants
    "API_PREFIX",
    "DEFAULT_CLOCK_DATE",
    "DEFAULT_CLOCK_UTC",
    "DEFAULT_LIMIT",
    "DEFAULT_OFFSET",
    "MAX_LIMIT",
    "MIN_LIMIT",
    "STAFF_ROLES",
    # identities
    "ANONYMOUS",
    "ANONYMOUS_ALT",
    "CITY_CLERK",
    "CITY_CLERK_ALT",
    "CODIFICATION_EDITOR",
    "CODIFICATION_EDITOR_ALT",
    "CODIFICATION_EDITOR_FOURTH",
    "CODIFICATION_EDITOR_THIRD",
    "DEPUTY_CLERK",
    "DEPUTY_CLERK_ALT",
    "NO_AUTH_HEADERS",
    "PRESIDING_OFFICER",
    "RECORDS_OFFICER",
    "RECORDS_OFFICER_ALT",
    "STAFF_HEADERS",
    "TEST_USERS",
    "UNKNOWN_ROLE_HEADERS",
    "make_headers",
    "make_requester_headers",
    # types
    "Entity",
    "EntityList",
    "Headers",
    "Payload",
]
