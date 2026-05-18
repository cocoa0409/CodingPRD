"""Error IDs and HTTP status mapping — PRD §5 Error Code Catalogue.

After definition, the mapping is registered with the framework so
validate_error() auto-checks HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth — PRD §2.1
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    # State / OCC — PRD §2.6, §2.7
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Roster — PRD §3.1
    ERR_SHARE_FACTOR_SUM_INVALID = "ERR_SHARE_FACTOR_SUM_INVALID"
    # Liens — PRD §3.6
    ERR_LIEN_COOLING_OFF = "ERR_LIEN_COOLING_OFF"
    # ACC voting — PRD §3.4
    ERR_NOT_ON_ACC = "ERR_NOT_ON_ACC"
    # Elections — PRD §3.7
    ERR_VOTER_INELIGIBLE = "ERR_VOTER_INELIGIBLE"
    ERR_VOTING_CLOSED = "ERR_VOTING_CLOSED"
    ERR_DUPLICATE_BALLOT = "ERR_DUPLICATE_BALLOT"
    ERR_NOMINATION_CLOSED = "ERR_NOMINATION_CLOSED"
    # Assessment fiscal — PRD §3.2, §3.3
    ERR_LEVY_TOO_SMALL = "ERR_LEVY_TOO_SMALL"
    ERR_AMOUNT_INVALID = "ERR_AMOUNT_INVALID"
    # ACC begin-review — PRD §3.4
    ERR_OWNER_DELINQUENT = "ERR_OWNER_DELINQUENT"
    ERR_RESERVE_POSTURE_BLOCKS_ACC = "ERR_RESERVE_POSTURE_BLOCKS_ACC"
    # Segregation of duties — PRD §3.5, §3.8
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    # Board resolutions — PRD §3.8
    ERR_RESOLUTION_TARGET_INVALID = "ERR_RESOLUTION_TARGET_INVALID"
    # Clock — PRD §2.4
    ERR_TIME_TRAVEL = "ERR_TIME_TRAVEL"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_SHARE_FACTOR_SUM_INVALID: 422,
    ApiErrorId.ERR_LIEN_COOLING_OFF: 409,
    ApiErrorId.ERR_NOT_ON_ACC: 403,
    ApiErrorId.ERR_VOTER_INELIGIBLE: 403,
    ApiErrorId.ERR_VOTING_CLOSED: 409,
    ApiErrorId.ERR_DUPLICATE_BALLOT: 409,
    ApiErrorId.ERR_NOMINATION_CLOSED: 409,
    ApiErrorId.ERR_LEVY_TOO_SMALL: 422,
    ApiErrorId.ERR_AMOUNT_INVALID: 422,
    ApiErrorId.ERR_OWNER_DELINQUENT: 409,
    ApiErrorId.ERR_RESERVE_POSTURE_BLOCKS_ACC: 409,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_RESOLUTION_TARGET_INVALID: 422,
    ApiErrorId.ERR_TIME_TRAVEL: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
