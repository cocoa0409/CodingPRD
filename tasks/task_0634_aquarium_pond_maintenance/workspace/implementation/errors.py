"""Error catalogue and the ApiError exception type.

Every error_id and HTTP status traces verbatim to PRD section 5
(Error Code Catalogue) and SCAFFOLD §1.6.
"""


# error_id -> http status code
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_TECH_MISMATCH": 403,
    "ERR_TECH_NOT_CERTIFIED": 422,
    "ERR_OVERSTOCKED": 422,
    "ERR_TECH_DOUBLE_BOOKED": 409,
    "ERR_QT_TANK_OCCUPIED": 409,
    "ERR_INVALID_QT_TANK": 422,
    "ERR_VISIT_KIND_MISMATCH": 422,
    "ERR_BAD_WINDOW": 422,
    "ERR_OVERPAYMENT": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_CONTRACT_NOT_ACTIVE": 422,
    "ERR_SYSTEM_NOT_PROVISIONING": 422,
    "ERR_OPEN_INSTALL_BLOCKS_COMMISSION": 409,
    "ERR_BALANCE_OUTSTANDING": 422,
    "ERR_VISIT_IN_FLIGHT": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_NO_SYSTEM_ON_CONTRACT": 422,
    "ERR_INVALID_REQUEST": 422,
}


class ApiError(Exception):
    """Raised anywhere in request handling to abort with a structured error."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_CATALOG.get(error_id, 400)
        self.message = message or error_id
        super().__init__(self.message)
