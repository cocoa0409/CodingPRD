"""Shared test infrastructure for the commuter benefit program service.

Importing this package installs the error-code -> HTTP-status map used by
``validate_error``, so tests can omit the expected status and still have it
cross-checked.
"""

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, CommuterBenefitApiClient
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_account_conservation,
    assert_append_only_common_fields,
    assert_election_axes,
    assert_entry_types,
    assert_exclusion_split,
    assert_invoice_totals,
    assert_ledger_matches_account,
    assert_ledger_sequence,
    assert_media_line,
    assert_mutable_common_fields,
    assert_pagination_meta,
    assert_unchanged,
)
from .test_users import (
    ALL_ROLES,
    COMPLIANCE_REVIEWER,
    ORDER_DESK,
    PAYROLL_PROCESSOR,
    PROGRAM_ADMIN,
    ROLE_COMPLIANCE_REVIEWER,
    ROLE_EMPLOYEE,
    ROLE_ORDER_DESK,
    ROLE_PAYROLL_PROCESSOR,
    ROLE_PROGRAM_ADMIN,
    TEST_USERS,
    make_compliance_reviewer_headers,
    make_employee_headers,
    make_headers,
    make_order_desk_headers,
    make_payroll_processor_headers,
    make_program_admin_headers,
)

__all__ = [
    "ApiClient",
    "CommuterBenefitApiClient",
    "ERROR_HTTP_STATUS",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "assert_account_conservation",
    "assert_append_only_common_fields",
    "assert_election_axes",
    "assert_entry_types",
    "assert_exclusion_split",
    "assert_invoice_totals",
    "assert_ledger_matches_account",
    "assert_ledger_sequence",
    "assert_media_line",
    "assert_mutable_common_fields",
    "assert_pagination_meta",
    "assert_unchanged",
    "ALL_ROLES",
    "COMPLIANCE_REVIEWER",
    "ORDER_DESK",
    "PAYROLL_PROCESSOR",
    "PROGRAM_ADMIN",
    "ROLE_COMPLIANCE_REVIEWER",
    "ROLE_EMPLOYEE",
    "ROLE_ORDER_DESK",
    "ROLE_PAYROLL_PROCESSOR",
    "ROLE_PROGRAM_ADMIN",
    "TEST_USERS",
    "make_compliance_reviewer_headers",
    "make_employee_headers",
    "make_headers",
    "make_order_desk_headers",
    "make_payroll_processor_headers",
    "make_program_admin_headers",
]
