"""Test infrastructure for the model deployment and monitoring service.

Importing this package registers the error catalogue's HTTP status mapping with
the shared validators, so `validate_error(response, ERR_X)` cross-checks the
status code without any test restating it.
"""

from . import api_errors  # noqa: F401  (import registers the status mapping)
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_BY_FAMILY
from .assertions import (
    assert_allocated_traffic,
    assert_append_only_fields,
    assert_ascending,
    assert_common_fields,
    assert_dataset_state,
    assert_deltas_sum_to,
    assert_deployment_state,
    assert_descending,
    assert_drift_outcome,
    assert_envelope_meta,
    assert_error_meta_is_minimal,
    assert_four_dp,
    assert_health_score,
    assert_ledger_reasons,
    assert_pct,
    assert_promotion_outcome,
    assert_ramp_step_row,
    assert_skew_outcome,
    assert_sweep_counters,
    assert_two_dp,
    assert_urgency_snapshot,
    assert_version_state,
    ids_of,
)

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_BY_FAMILY",
    "assert_allocated_traffic",
    "assert_append_only_fields",
    "assert_ascending",
    "assert_common_fields",
    "assert_dataset_state",
    "assert_deltas_sum_to",
    "assert_deployment_state",
    "assert_descending",
    "assert_drift_outcome",
    "assert_envelope_meta",
    "assert_error_meta_is_minimal",
    "assert_four_dp",
    "assert_health_score",
    "assert_ledger_reasons",
    "assert_pct",
    "assert_promotion_outcome",
    "assert_ramp_step_row",
    "assert_skew_outcome",
    "assert_sweep_counters",
    "assert_two_dp",
    "assert_urgency_snapshot",
    "assert_version_state",
    "ids_of",
]
