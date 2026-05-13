"""Error definitions for the gym-membership API."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Map of error_id -> http_status from PRD §5
ERROR_HTTP = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_CARD_TYPE_RETIRED": 409,
    "ERR_TRAINER_INACTIVE": 409,
    "ERR_SPECIALTY_MISMATCH": 422,
    "ERR_SLOT_ALREADY_RESERVED": 409,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_CLASS_OVERLAP": 409,
    "ERR_CAPACITY_REACHED": 409,
    "ERR_CANCEL_WINDOW_EXPIRED": 409,
    "ERR_REFUND_NOT_ELIGIBLE": 422,
    "ERR_REFUND_FROZEN_CARD_BLOCKED": 422,
    "ERR_TRANSFER_NOT_ELIGIBLE": 422,
    "ERR_TRANSFER_INELIGIBLE_RECIPIENT": 422,
    "ERR_FREEZE_BUDGET_EXHAUSTED": 422,
    "ERR_FREEZE_IN_PROGRESS": 409,
    "ERR_FREEZE_CONFLICTS_WITH_BOOKING": 409,
    "ERR_INSUFFICIENT_BALANCE": 422,
    "ERR_CARD_VISITS_EXHAUSTED": 422,
    "ERR_FAMILY_SHARE_NOT_AUTHORIZED": 403,
    "ERR_RECHARGE_AMOUNT_INVALID": 422,
    "ERR_PAYOUT_CYCLE_OPEN": 409,
    "ERR_WALLET_LEDGER_CONFLICT": 409,
    "ERR_VALIDATION": 422,
}


def raise_err(error_id: str, message: str = ""):
    http = ERROR_HTTP.get(error_id, 422)
    raise APIError(error_id, http, message)
