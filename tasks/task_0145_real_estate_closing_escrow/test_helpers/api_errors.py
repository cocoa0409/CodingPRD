"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition, the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth / existence — PRD §2.1, §2.8
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # FK type checking — PRD §3.6, §2.12
    ERR_BENEFICIARY_KIND_MISMATCH = "ERR_BENEFICIARY_KIND_MISMATCH"

    # State / concurrency — PRD §2.6, §2.8
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_CROSS_ENTITY_STATE = "ERR_CROSS_ENTITY_STATE"
    ERR_VERSION_MISMATCH = "ERR_VERSION_MISMATCH"

    # Wire / SoD — PRD §2.11, §3.6
    ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
    ERR_WIRE_CALLBACK_MISSING = "ERR_WIRE_CALLBACK_MISSING"
    ERR_WIRE_LOCKED_BY_DISBURSEMENT = "ERR_WIRE_LOCKED_BY_DISBURSEMENT"

    # CD / clock — PRD §2.10, §3.5
    ERR_CD_WAITING_PERIOD = "ERR_CD_WAITING_PERIOD"

    # §1031 — PRD §3.8, §2.13
    ERR_1031_45DAY_LAPSED = "ERR_1031_45DAY_LAPSED"
    ERR_1031_180DAY_LAPSED = "ERR_1031_180DAY_LAPSED"
    ERR_1031_GAIN_INVARIANT = "ERR_1031_GAIN_INVARIANT"

    # Title — PRD §3.3
    ERR_LENDERS_REQUIRES_OWNERS = "ERR_LENDERS_REQUIRES_OWNERS"
    ERR_TITLE_NOT_CLEARED = "ERR_TITLE_NOT_CLEARED"

    # EMD — PRD §3.2
    ERR_EMD_BELOW_FLOOR = "ERR_EMD_BELOW_FLOOR"
    ERR_EMD_SPLIT_INVARIANT = "ERR_EMD_SPLIT_INVARIANT"

    # CCR — PRD §3.4, §3.9
    ERR_CCR_NOT_ACKNOWLEDGED = "ERR_CCR_NOT_ACKNOWLEDGED"

    # Disbursement / pool — PRD §3.7
    ERR_DISBURSEMENT_OVERDRAW = "ERR_DISBURSEMENT_OVERDRAW"

    # Idempotency — PRD §2.7
    ERR_IDEMPOTENCY_REPLAY_MISMATCH = "ERR_IDEMPOTENCY_REPLAY_MISMATCH"

    # Generic bad request — PRD §2.8
    ERR_BAD_REQUEST = "ERR_BAD_REQUEST"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN_ROLE: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_BENEFICIARY_KIND_MISMATCH: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_CROSS_ENTITY_STATE: 409,
    ApiErrorId.ERR_VERSION_MISMATCH: 409,
    ApiErrorId.ERR_SOD_VIOLATION: 403,
    ApiErrorId.ERR_WIRE_CALLBACK_MISSING: 422,
    ApiErrorId.ERR_WIRE_LOCKED_BY_DISBURSEMENT: 409,
    ApiErrorId.ERR_CD_WAITING_PERIOD: 409,
    ApiErrorId.ERR_1031_45DAY_LAPSED: 409,
    ApiErrorId.ERR_1031_180DAY_LAPSED: 409,
    ApiErrorId.ERR_1031_GAIN_INVARIANT: 422,
    ApiErrorId.ERR_LENDERS_REQUIRES_OWNERS: 409,
    ApiErrorId.ERR_TITLE_NOT_CLEARED: 409,
    ApiErrorId.ERR_EMD_BELOW_FLOOR: 422,
    ApiErrorId.ERR_EMD_SPLIT_INVARIANT: 422,
    ApiErrorId.ERR_CCR_NOT_ACKNOWLEDGED: 409,
    ApiErrorId.ERR_DISBURSEMENT_OVERDRAW: 422,
    ApiErrorId.ERR_IDEMPOTENCY_REPLAY_MISMATCH: 409,
    ApiErrorId.ERR_BAD_REQUEST: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
