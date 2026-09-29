"""Test infrastructure for the Contact Center Workforce Management API.

Barrel export: everything the test suite needs is importable from this package.
"""

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_BY_ENTITY, ApiErrorId
from .assertions import (
    assert_agent_coaching,
    assert_agent_hours,
    assert_cents,
    assert_common_fields,
    assert_coverage_summary_shape,
    assert_cycle_ledgers,
    assert_declared_fields,
    assert_hours,
    assert_instant_equals,
    assert_interval_coverage,
    assert_interval_forecast,
    assert_interval_outsourcing,
    assert_no_bookkeeping_fields,
    assert_partner_ledgers,
    assert_ratio,
    assert_settlement_amounts,
    assert_settlement_fields_null,
    assert_shift_adherence,
    assert_shift_axes,
    assert_shift_hours,
    normalize_instant,
)

__all__ = [
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "NOT_FOUND_BY_ENTITY",
    "assert_agent_coaching",
    "assert_agent_hours",
    "assert_cents",
    "assert_common_fields",
    "assert_coverage_summary_shape",
    "assert_cycle_ledgers",
    "assert_declared_fields",
    "assert_hours",
    "assert_instant_equals",
    "assert_interval_coverage",
    "assert_interval_forecast",
    "assert_interval_outsourcing",
    "assert_no_bookkeeping_fields",
    "assert_partner_ledgers",
    "assert_ratio",
    "assert_settlement_amounts",
    "assert_settlement_fields_null",
    "assert_shift_adherence",
    "assert_shift_axes",
    "assert_shift_hours",
    "normalize_instant",
]
