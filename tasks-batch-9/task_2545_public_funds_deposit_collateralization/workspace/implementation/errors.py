"""Error catalogue (PRD 5) and the exception type carrying it."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SIGNATURE_PARTY_MISMATCH": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    "ERR_STALE_DEPOSITORY_VERSION": 412,
    "ERR_STALE_DEPOSIT_ACCOUNT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_DEPOSITORY_NOT_APPROVED": 409,
    "ERR_DEPOSITORY_POSTURE_FROZEN": 409,
    "ERR_AGREEMENT_NOT_EXECUTED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CUSTODIAN_NOT_ELIGIBLE": 409,
    "ERR_DEPOSITORY_RISK_GRADE_BLOCKED": 409,
    "ERR_MTM_WINDOW_OVERLAP": 409,
    "ERR_CURE_WINDOW_CLOSED": 409,
    "ERR_ALLOCATION_OVERSUBSCRIBED": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_ROUND_LIMIT_REACHED": 409,
    "ERR_PARTY_ALREADY_SIGNED": 409,
    "ERR_COLLATERAL_TYPE_INELIGIBLE": 422,
    "ERR_CUSTODIAN_MISMATCH": 422,
    "ERR_DEPOSITORY_MISMATCH": 422,
    "ERR_BENEFICIARY_TARGET_INVALID": 422,
    "ERR_PLEDGING_MODE_MISMATCH": 422,
    "ERR_ALLOCATION_NOT_UNDER_AGREEMENT": 422,
    "ERR_STALE_COLLATERAL_PRICE": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_FORECAST_WINDOW_DISCONTINUITY": 422,
    "ERR_CUSTODIAN_CONCENTRATION_EXCEEDED": 422,
    "ERR_CURE_ALLOCATION_INELIGIBLE": 422,
    "ERR_SUBSTITUTION_VALUE_SHORTFALL": 422,
    "ERR_STATUTORY_DEPOSIT_LIMIT": 422,
    "ERR_INSUFFICIENT_LEDGER_BALANCE": 422,
    "ERR_PLEDGE_CAPACITY_EXCEEDED": 422,
    "ERR_CAPACITY_ABOVE_STATUTORY_CEILING": 422,
    "ERR_CURE_EXCEEDS_OUTSTANDING": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unrecognised role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting identity does not own the target resource.",
    "ERR_SIGNATURE_PARTY_MISMATCH": "The acting role is not entitled to stamp the requested party.",
    "ERR_RESOURCE_NOT_FOUND": "The requested resource does not exist.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_STALE_AGREEMENT_VERSION": "The supplied pledge agreement version is stale.",
    "ERR_STALE_DEPOSITORY_VERSION": "The supplied depository version is stale.",
    "ERR_STALE_DEPOSIT_ACCOUNT_VERSION": "The supplied deposit account version is stale.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition is defined.",
    "ERR_DEPOSITORY_NOT_APPROVED": "The depository is not APPROVED.",
    "ERR_DEPOSITORY_POSTURE_FROZEN": "The depository's collateral posture is FROZEN.",
    "ERR_AGREEMENT_NOT_EXECUTED": "The pledge agreement is not EXECUTED.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting identity may not perform this step.",
    "ERR_CUSTODIAN_NOT_ELIGIBLE": "The custodian is not eligible to serve on a tri-party agreement.",
    "ERR_DEPOSITORY_RISK_GRADE_BLOCKED": "The depository's risk grade blocks this operation.",
    "ERR_MTM_WINDOW_OVERLAP": "The mark-to-market window collides with or crowds a prior run.",
    "ERR_CURE_WINDOW_CLOSED": "The margin call's cure window has closed.",
    "ERR_ALLOCATION_OVERSUBSCRIBED": "The pledge would commit more par than the asset has.",
    "ERR_DUPLICATE_IDENTIFIER": "The business identifier is already taken in its scope.",
    "ERR_ROUND_LIMIT_REACHED": "The permitted number of rounds has been reached.",
    "ERR_PARTY_ALREADY_SIGNED": "The requested party has already signed.",
    "ERR_COLLATERAL_TYPE_INELIGIBLE": "The collateral asset is not eligible for public funds.",
    "ERR_CUSTODIAN_MISMATCH": "The asset's custodian does not match the agreement's custodian.",
    "ERR_DEPOSITORY_MISMATCH": "The asset's depository does not match the agreement's depository.",
    "ERR_BENEFICIARY_TARGET_INVALID": "The beneficiary discriminator and reference disagree.",
    "ERR_PLEDGING_MODE_MISMATCH": "The pledging mode contradicts the public unit's preference.",
    "ERR_ALLOCATION_NOT_UNDER_AGREEMENT": "The outgoing allocation is not an ACTIVE allocation of the named agreement.",
    "ERR_STALE_COLLATERAL_PRICE": "The asset's last price observation is too old.",
    "ERR_INVALID_INTERVAL": "The supplied interval is empty or otherwise inadmissible.",
    "ERR_FORECAST_WINDOW_DISCONTINUITY": "The projection windows are not a contiguous chain covering the horizon.",
    "ERR_CUSTODIAN_CONCENTRATION_EXCEEDED": "The allocation would breach the custodian's concentration limit.",
    "ERR_CURE_ALLOCATION_INELIGIBLE": "An offered allocation fails the cure-credit test.",
    "ERR_SUBSTITUTION_VALUE_SHORTFALL": "The incoming collateral is worth less than the outgoing collateral.",
    "ERR_STATUTORY_DEPOSIT_LIMIT": "The deposit would breach the public unit's statutory deposit limit.",
    "ERR_INSUFFICIENT_LEDGER_BALANCE": "The withdrawal exceeds the account's ledger balance.",
    "ERR_PLEDGE_CAPACITY_EXCEEDED": "The pledge would exceed the depository's approved pledge capacity.",
    "ERR_CAPACITY_ABOVE_STATUTORY_CEILING": "The requested pledge capacity exceeds the statutory ceiling.",
    "ERR_CURE_EXCEEDS_OUTSTANDING": "The credited value exceeds the margin call's outstanding amount.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
