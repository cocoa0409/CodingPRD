"""Error catalogue for the pension-risk-transfer API (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status=None, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 409)
        self.message = message if message else DEFAULT_MESSAGE.get(error_id, error_id)


ERROR_HTTP = {
    # --- authentication / authorisation ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_STRATEGY_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_ELECTION_NOT_FOUND": 404,
    "ERR_TRANCHE_NOT_FOUND": 404,
    "ERR_INSURER_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_EXPERT_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_SETTLEMENT_ENTRY_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    # --- shape / numeric ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_AMOUNT": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_NOTICE_PERIOD_TOO_SHORT": 422,
    "ERR_INVALID_PAGINATION": 422,
    # --- optimistic concurrency ---
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_TRANCHE_VERSION": 412,
    "ERR_STALE_PARTICIPANT_VERSION": 412,
    # --- payment required ---
    "ERR_PLAN_ASSETS_INSUFFICIENT": 402,
    # --- state / business (409) ---
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_PLAN_NOT_SETTLEMENT_AUTHORIZED": 409,
    "ERR_STRATEGY_STATE_INVALID": 409,
    "ERR_STRATEGY_NOT_APPROVED": 409,
    "ERR_PARTICIPANT_STATE_INVALID": 409,
    "ERR_PARTICIPANT_DATA_NOT_CLEAN": 409,
    "ERR_PARTICIPANT_ALREADY_ASSIGNED": 409,
    "ERR_PARTICIPANT_NOT_TRANSFERRED": 409,
    "ERR_PARTICIPANT_PLAN_MISMATCH": 409,
    "ERR_WINDOW_QUIET_PERIOD_CONFLICT": 409,
    "ERR_MORTALITY_NOT_CONFIRMED": 409,
    "ERR_ADDRESS_SEARCH_TIER_EXHAUSTED": 409,
    "ERR_AUDIT_STATE_INVALID": 409,
    "ERR_WINDOW_STATE_INVALID": 409,
    "ERR_WINDOW_NOT_OPEN": 409,
    "ERR_WINDOW_CAP_EXCEEDED": 409,
    "ERR_ELECTION_STATE_INVALID": 409,
    "ERR_REVOCATION_PERIOD_ELAPSED": 409,
    "ERR_LUMP_SUM_NOT_ELIGIBLE": 409,
    "ERR_TRANCHE_STATE_INVALID": 409,
    "ERR_TRANCHE_NOT_SELECTED": 409,
    "ERR_TRANCHE_NOT_TRANSFERRED": 409,
    "ERR_TRANCHE_EMPTY": 409,
    "ERR_QUOTE_STATE_INVALID": 409,
    "ERR_QUOTE_NOT_REQUESTED": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_QUOTE_TRANCHE_MISMATCH": 409,
    "ERR_DUPLICATE_QUOTE_REQUEST": 409,
    "ERR_NO_ELIGIBLE_QUOTE": 409,
    "ERR_INSURER_RATING_BELOW_FLOOR": 409,
    "ERR_INSURER_CAPACITY_EXCEEDED": 409,
    "ERR_EXPERT_STATE_INVALID": 409,
    "ERR_EXPERT_NOT_ENGAGED": 409,
    "ERR_EXPERT_OPINION_REQUIRED": 409,
    "ERR_EXPERT_CONFLICT_DISCLOSED": 409,
    "ERR_TRANSFER_STATE_INVALID": 409,
    "ERR_TRANSFER_NOT_INITIATED": 409,
    "ERR_TRANSFER_VALUE_SHORTFALL": 409,
    "ERR_COMPLAINT_STATE_INVALID": 409,
    "ERR_COMPLAINT_NOT_TRIAGED": 409,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role may not perform this operation.",
    "ERR_IDENTITY_MISMATCH": "The caller's identity does not match the referenced entity.",
    "ERR_SEGREGATION_OF_DUTIES": "The same user may not act on both sides of this decision.",
    "ERR_PLAN_NOT_FOUND": "Pension plan not found.",
    "ERR_STRATEGY_NOT_FOUND": "De-risking strategy not found.",
    "ERR_PARTICIPANT_NOT_FOUND": "Participant record not found.",
    "ERR_AUDIT_NOT_FOUND": "Benefit audit not found.",
    "ERR_WINDOW_NOT_FOUND": "Lump-sum window not found.",
    "ERR_ELECTION_NOT_FOUND": "Participant election not found.",
    "ERR_TRANCHE_NOT_FOUND": "Buyout tranche not found.",
    "ERR_INSURER_NOT_FOUND": "Insurer not found.",
    "ERR_QUOTE_NOT_FOUND": "Annuity quote not found.",
    "ERR_EXPERT_NOT_FOUND": "Independent expert not found.",
    "ERR_TRANSFER_NOT_FOUND": "Asset transfer not found.",
    "ERR_SETTLEMENT_ENTRY_NOT_FOUND": "Settlement entry not found.",
    "ERR_COMPLAINT_NOT_FOUND": "Participant complaint not found.",
    "ERR_INVALID_REQUEST": "The request body is malformed or missing required fields.",
    "ERR_INVALID_AMOUNT": "A numeric field falls outside its permitted range.",
    "ERR_INVALID_INTERVAL": "A date interval is not well formed.",
    "ERR_NOTICE_PERIOD_TOO_SHORT": "The statutory notice period is not satisfied.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are out of range.",
    "ERR_STALE_PLAN_VERSION": "The supplied plan version is stale.",
    "ERR_STALE_TRANCHE_VERSION": "The supplied tranche version is stale.",
    "ERR_STALE_PARTICIPANT_VERSION": "The supplied participant version is stale.",
    "ERR_PLAN_ASSETS_INSUFFICIENT": "Plan assets are insufficient for this operation.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP.get(error_id, 409), message)
