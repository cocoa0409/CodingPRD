"""Test helpers for the district new-teacher induction and mentorship API.

Importing this package registers the error catalogue's HTTP status mapping with
the shared response validators.
"""

from . import api_errors  # noqa: F401  (registers the error/status mapping)
from .api_client import InductionApiClient
from .assertions import (
    assert_created_at_ascending,
    assert_ascending_by,
    assert_date_component,
    assert_four_decimals,
    assert_immutable_system_fields,
    assert_instant_equals,
    assert_money_cents,
    assert_novice_counters,
    assert_pagination_defaults,
    assert_system_fields,
    assert_three_fractional_digits,
    assert_two_decimals,
    ids_of,
    parse_instant,
)

__all__ = [
    "InductionApiClient",
    "api_errors",
    "assert_created_at_ascending",
    "assert_ascending_by",
    "assert_date_component",
    "assert_four_decimals",
    "assert_immutable_system_fields",
    "assert_instant_equals",
    "assert_money_cents",
    "assert_novice_counters",
    "assert_pagination_defaults",
    "assert_system_fields",
    "assert_three_fractional_digits",
    "assert_two_decimals",
    "ids_of",
    "parse_instant",
]
