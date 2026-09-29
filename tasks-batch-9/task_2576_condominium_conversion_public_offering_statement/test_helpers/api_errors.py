"""The PRD error catalogue: error_id -> HTTP status.

The map below is a verbatim transcription of the PRD's error catalogue table.
Registering it with the shared validators means every `validate_error` call
cross-checks the HTTP status the PRD pins for that error_id.
"""

from prd_bench_local_runner.testing.validators import set_error_http_status_map

ERROR_HTTP_STATUS = {
    # --- identity and authorization ---
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_ENGINEERING_ARTIFACT_NOT_FOUND": 404,
    "ERR_DECLARATION_ARTIFACT_NOT_FOUND": 404,
    "ERR_DISCLOSURE_ARTIFACT_NOT_FOUND": 404,
    "ERR_TENANT_NOT_FOUND": 404,
    "ERR_FINANCIAL_ARTIFACT_NOT_FOUND": 404,
    "ERR_SALES_ARTIFACT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_DUPLICATE_KEY": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_STALE_REPORT_VERSION": 412,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    # --- posture gates ---
    "ERR_PROJECT_FROZEN": 409,
    "ERR_PROJECT_RESTRICTED": 409,
    # --- state machine ---
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_POS_NOT_EFFECTIVE": 409,
    "ERR_DECLARATION_NOT_RECORDED": 409,
    "ERR_RESERVE_STUDY_NOT_ADOPTED": 409,
    "ERR_POS_NOT_DELIVERED": 409,
    # --- engineering and disclosure gates ---
    "ERR_LIFE_SAFETY_COMPONENT_EXPIRED": 422,
    "ERR_SUITABILITY_GATE_FAILED": 409,
    "ERR_NO_VERIFIED_COMPONENTS": 409,
    "ERR_POS_SECTIONS_INCOMPLETE": 409,
    # --- temporal windows ---
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 409,
    "ERR_ROFR_WINDOW_EXPIRED": 409,
    "ERR_RESCISSION_PERIOD_OPEN": 409,
    "ERR_RESCISSION_PERIOD_CLOSED": 409,
    "ERR_WARRANTY_PERIOD_EXPIRED": 409,
    "ERR_BATCH_WINDOW_OVERLAP": 409,
    "ERR_REMEDIATION_WINDOW_OVERLAP": 409,
    "ERR_REMEDIATION_CAPACITY_EXCEEDED": 409,
    # --- referential and constraint ---
    "ERR_PROJECT_SCOPE_MISMATCH": 409,
    "ERR_ROFR_UNIT_NOT_LINKED": 409,
    "ERR_AGREEMENT_ALREADY_ASSIGNED": 409,
    "ERR_PERCENTAGE_INTEREST_NOT_BALANCED": 409,
    "ERR_LAST_INCLUDED_UNIT": 409,
    "ERR_NO_INCLUDED_UNITS": 409,
    "ERR_CLAIM_REOPEN_LIMIT_REACHED": 409,
    # --- fiscal ---
    "ERR_ESCROW_AMOUNT_MISMATCH": 422,
    "ERR_ESCROW_NOT_FUNDED": 402,
    "ERR_RELOCATION_AMOUNT_MISMATCH": 422,
    "ERR_PRESALE_THRESHOLD_NOT_MET": 409,
}

set_error_http_status_map(ERROR_HTTP_STATUS)
