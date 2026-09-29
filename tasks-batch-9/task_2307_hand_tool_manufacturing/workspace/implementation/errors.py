"""Error catalogue (§1.6 / PRD §5)."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_CLAIMANT_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not found
    "ERR_TOOL_SKU_NOT_FOUND": 404,
    "ERR_PRODUCTION_LOT_NOT_FOUND": 404,
    "ERR_FURNACE_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_CHAMBER_NOT_FOUND": 404,
    "ERR_TEST_RUN_NOT_FOUND": 404,
    "ERR_PACK_CONFIG_NOT_FOUND": 404,
    "ERR_WARRANTY_PROGRAM_NOT_FOUND": 404,
    "ERR_CLAIMANT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_WINDOW": 400,
    "ERR_READING_COUNT_MISMATCH": 422,
    "ERR_CHAMBER_REQUIRED": 422,
    "ERR_CHAMBER_NOT_APPLICABLE": 422,
    # state preconditions
    "ERR_LOT_CERT_STATE_INVALID": 409,
    "ERR_LOT_PROCESS_STATE_INVALID": 409,
    "ERR_LOT_QUARANTINED": 409,
    "ERR_LOT_ALREADY_DISPOSITIONED": 409,
    "ERR_TEST_RUN_STATE_INVALID": 409,
    "ERR_CAMPAIGN_STATE_INVALID": 409,
    "ERR_PACK_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    "ERR_CLAIMANT_STATE_INVALID": 409,
    "ERR_CLAIMANT_BLOCKED": 409,
    "ERR_FURNACE_STATUS_UNCHANGED": 409,
    # optimistic concurrency
    "ERR_STALE_SKU_VERSION": 412,
    "ERR_STALE_PROGRAM_VERSION": 412,
    # cross-entity state
    "ERR_HEAT_TREAT_NOT_COMPLETED": 409,
    "ERR_SKU_WARRANTY_RESTRICTED": 409,
    "ERR_FURNACE_UNAVAILABLE": 409,
    "ERR_MEMBER_SKU_NOT_CERTIFIED": 409,
    "ERR_MEMBER_SKU_RESTRICTED": 409,
    # business safety
    "ERR_ALLOY_NOT_SUPPORTED": 422,
    "ERR_TEST_STAGE_TOO_EARLY": 409,
    "ERR_MANDATORY_TEST_MISSING": 422,
    "ERR_FAILED_TEST_PRESENT": 409,
    "ERR_HARDNESS_MARGIN_NOT_MET": 422,
    "ERR_LOT_NOT_CERTIFIED": 409,
    "ERR_WARRANTY_TIER_NOT_COVERED": 422,
    "ERR_REWORK_LIMIT_EXCEEDED": 409,
    "ERR_SOAK_TIME_TOO_SHORT": 422,
    # business temporal
    "ERR_FURNACE_WINDOW_CONFLICT": 409,
    "ERR_TEST_WINDOW_BEFORE_HEAT_TREAT": 422,
    # business capacity
    "ERR_FURNACE_CHARGE_EXCEEDED": 422,
    "ERR_SPECIMENS_EXHAUSTED": 409,
    "ERR_CHAMBER_CAPACITY_EXCEEDED": 409,
    "ERR_REPLACEMENT_STOCK_INSUFFICIENT": 409,
    # business fiscal
    "ERR_RESERVE_INSUFFICIENT": 402,
    "ERR_FRAUD_SCORE_TOO_HIGH": 409,
    # business integrity
    "ERR_CLAIM_HAS_NO_LINES": 422,
    "ERR_DUPLICATE_OPEN_CLAIM": 409,
    "ERR_SKU_LINEAGE_CYCLE": 422,
    "ERR_LINEAGE_FAMILY_MISMATCH": 422,
    "ERR_LINEAGE_DEPTH_EXCEEDED": 422,
    "ERR_DUPLICATE_PACK_MEMBER": 409,
    "ERR_CHANNEL_MIX_FORBIDDEN": 422,
    "ERR_PACK_CONFIG_INVALID": 422,
    "ERR_DUPLICATE_CODE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-Role header is absent or names an unknown role.",
    "ERR_ROLE_NOT_PERMITTED": "The calling role is not authorised for this endpoint.",
    "ERR_CLAIMANT_MISMATCH": "A claimant may only act on their own claims.",
    "ERR_SEGREGATION_OF_DUTIES": "The user who placed the fraud hold may not clear or approve the claim.",
    "ERR_INVALID_REQUEST": "The request body is missing a required field or carries an invalid value.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id) or error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
