"""Shared test infrastructure for the Corporate Archives & Heritage API suite.

Importing this package gives a test module the whole toolbox: the HTTP client,
the error-code vocabulary (whose HTTP-status map is registered on import of
``api_errors``), the payload factories, the composite state builders, the
identity headers and the domain assertion helpers.
"""

from . import constants, factories, fixtures, types
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_BY_COLLECTION
from .assertions import (
    assert_budget_ledger,
    assert_common_fields,
    assert_cost_breakdown,
    assert_custody_triple,
    assert_empty,
    assert_envelope_meta,
    assert_fields,
    assert_ids_exactly,
    assert_instant,
    assert_is_error_envelope,
    assert_money_cents,
    assert_no_common_fields,
    assert_nulls,
    assert_one_decimal,
    assert_score_2dp,
    assert_server_assigned_id,
    assert_total_count,
    assert_unit_custody_identity,
    created,
    failed,
    ok,
    page,
    setup,
)
from .constants import DEFAULT_CLOCK, DEFAULT_CLOCK_MS, MISSING_UUID
from .fixtures import AccessCase, Holding
from .test_users import (
    ARCHIVIST_A,
    ARCHIVIST_A_ID,
    ARCHIVIST_B,
    ARCHIVIST_B_ID,
    COUNSEL_A,
    COUNSEL_A_ID,
    COUNSEL_B,
    COUNSEL_B_ID,
    DIRECTOR_A,
    DIRECTOR_A_ID,
    DIRECTOR_B,
    DIRECTOR_B_ID,
    OFFICER_A,
    OFFICER_A_ID,
    OFFICER_B,
    OFFICER_B_ID,
    OFFICER_C,
    OFFICER_C_ID,
    OPERATOR,
    OPERATOR_ID,
    PRESERV_A,
    PRESERV_A_ID,
    PRESERV_B,
    PRESERV_B_ID,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_requester_headers,
)

__all__ = [
    "ApiClient",
    "AccessCase",
    "Holding",
    "constants",
    "factories",
    "fixtures",
    "types",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_BY_COLLECTION",
    "DEFAULT_CLOCK",
    "DEFAULT_CLOCK_MS",
    "MISSING_UUID",
    "created",
    "ok",
    "failed",
    "page",
    "setup",
]
