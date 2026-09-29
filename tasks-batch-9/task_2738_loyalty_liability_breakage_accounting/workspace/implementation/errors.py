"""Error catalogue and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not a recognised role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted on this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "The request is malformed or a value is out of range.",
    "ERR_PROGRAM_NOT_FOUND": "No LoyaltyProgram with the given id.",
    "ERR_STATE_EXPIRY_RULE_NOT_FOUND": "No StateExpiryRule with the given id.",
    "ERR_COHORT_NOT_FOUND": "No Cohort with the given id.",
    "ERR_MEMBER_NOT_FOUND": "No Member with the given id.",
    "ERR_PERIOD_NOT_FOUND": "No AccountingPeriod with the given id.",
    "ERR_PARTNER_AGREEMENT_NOT_FOUND": "No PartnerAgreement with the given id.",
    "ERR_POINT_LOT_NOT_FOUND": "No PointLot with the given id.",
    "ERR_REDEMPTION_EVENT_NOT_FOUND": "No RedemptionEvent with the given id.",
    "ERR_BREAKAGE_ESTIMATE_NOT_FOUND": "No BreakageEstimate with the given id.",
    "ERR_SETTLEMENT_STATEMENT_NOT_FOUND": "No SettlementStatement with the given id.",
    "ERR_CHANGE_ORDER_NOT_FOUND": "No ProgramChangeOrder with the given id.",
    "ERR_STALE_PROGRAM_VERSION": "expected_program_version does not match the programme version.",
    "ERR_STALE_AGREEMENT_VERSION": "expected_partner_agreement_version does not match the agreement version.",
    "ERR_PERIOD_NOT_OPEN": "The addressed AccountingPeriod is not OPEN.",
    "ERR_PROGRAM_NOT_ACTIVE": "The owning LoyaltyProgram is not ACTIVE.",
    "ERR_INVALID_STATE_TRANSITION": "The addressed resource is not in a legal source state for this transition.",
    "ERR_AGREEMENT_NOT_ACTIVE": "The addressed PartnerAgreement is not ACTIVE.",
    "ERR_PERIOD_HARD_CLOSED": "The AccountingPeriod is HARD_CLOSED and immutable.",
    "ERR_SEGREGATION_OF_DUTIES": "The approver may not be the preparer of the estimate.",
    "ERR_MEMO_NARRATIVE_REQUIRED": "The approved estimate carries no actuarial memorandum.",
    "ERR_ESTIMATE_NOT_APPROVED": "No APPROVED BreakageEstimate exists for the period.",
    "ERR_UNALLOCATED_REDEMPTIONS": "A RedemptionEvent of the period is still REQUESTED.",
    "ERR_INVALID_WINDOW": "The window end must fall strictly after its start.",
    "ERR_PERIOD_OVERLAP": "The proposed period window overlaps an existing period.",
    "ERR_PARTNER_WINDOW_CONFLICT": "The proposed agreement window conflicts with a prior agreement.",
    "ERR_PERIOD_NOT_ENDED": "The period window has not elapsed yet.",
    "ERR_CHANGE_NOT_YET_EFFECTIVE": "The change order has not reached its effective instant.",
    "ERR_PERIOD_PROGRAM_MISMATCH": "The AccountingPeriod belongs to a different LoyaltyProgram.",
    "ERR_COHORT_PROGRAM_MISMATCH": "The Cohort belongs to a different LoyaltyProgram.",
    "ERR_AGREEMENT_PROGRAM_MISMATCH": "The PartnerAgreement belongs to a different LoyaltyProgram.",
    "ERR_DUPLICATE_CODE": "The code is already used within this LoyaltyProgram.",
    "ERR_TIER_MULTIPLIER_KEYS_INVALID": "tier multiplier keys must be exactly BASE, SILVER, GOLD, PLATINUM.",
    "ERR_UNSETTLED_STATEMENTS": "A SettlementStatement of the period is not settled.",
    "ERR_REVISION_LIMIT_EXCEEDED": "The estimate revision budget is exhausted.",
    "ERR_REOPEN_LIMIT_EXCEEDED": "The period reopen budget is exhausted.",
    "ERR_DISPUTE_LIMIT_EXCEEDED": "The statement dispute budget is exhausted.",
    "ERR_SENSITIVITY_BAND_INVALID": "The sensitivity band must straddle the measured rate.",
    "ERR_PROMO_MULTIPLIER_ABOVE_CAP": "promo_multiplier_bp exceeds the programme cap.",
    "ERR_OUTSTANDING_SETTLEMENT": "The agreement still carries an outstanding settlement balance.",
    "ERR_PERIODS_NOT_CLOSED": "Every AccountingPeriod must be HARD_CLOSED first.",
    "ERR_ISSUANCE_CAP_EXCEEDED": "points_issued exceeds the per-issuance point cap.",
    "ERR_INSUFFICIENT_POINT_BALANCE": "The member's outstanding balance is insufficient.",
    "ERR_NO_OUTSTANDING_POINTS": "No cohort in scope carries outstanding points.",
    "ERR_PROGRAM_CONFIG_INCOMPLETE": "The programme needs a state expiry rule and a cohort.",
}


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def conflict(error_id, message=None):
    return ApiError(error_id, 409, message)


def not_found(error_id):
    return ApiError(error_id, 404)
