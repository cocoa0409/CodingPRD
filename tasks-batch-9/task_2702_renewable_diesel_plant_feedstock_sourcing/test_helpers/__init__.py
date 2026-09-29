"""Test infrastructure for the renewable-diesel feedstock-sourcing API.

Importing this package registers the error identifier -> HTTP status map with
the framework validators, so `validate_error(response, ERR_X)` checks the status
code as well as the identifier without each test restating it.

Sub-modules:
    types        domain vocabulary (roles, enums, statuses)
    constants    numeric constants and the round-half-up helper
    api_errors   error identifiers and their HTTP statuses
    api_client   one method per endpoint
    test_users   pre-built auth headers per role
    factories    valid-by-default request payloads
    fixtures     composite state builders driven through the public API
    assertions   domain assertion helpers
"""

from . import (  # noqa: F401
    api_client,
    api_errors,
    assertions,
    constants,
    factories,
    fixtures,
    test_users,
    types,
)
from .api_client import ApiClient  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import (  # noqa: F401
    assert_activity_index,
    assert_append_only_shape,
    assert_decimal_places,
    assert_fields_equal,
    assert_fields_null,
    assert_identity_fields,
    assert_money,
    assert_mass,
    assert_one_decimal,
    assert_timestamp_equals,
    read_entity,
)
from .constants import round_half_up  # noqa: F401
from .test_users import (  # noqa: F401
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
    OPERATOR_HEADERS,
    TEST_USERS,
    TRADER_HEADERS,
    VERIFIER_HEADERS,
    make_supplier_headers,
)
