"""Error classes and error ID constants for the HCV Landlord Participation API."""


class APIError(Exception):
    """Exception carrying an error_id, message, and HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error IDs (from SCAFFOLD.yaml §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_NOT_OWNER = "ERR_NOT_OWNER"
ERR_LANDLORD_SUSPENDED = "ERR_LANDLORD_SUSPENDED"
ERR_INCREASE_TOO_EARLY = "ERR_INCREASE_TOO_EARLY"
ERR_SCHEDULE_IN_PAST = "ERR_SCHEDULE_IN_PAST"
ERR_VOUCHER_SIZE_MISMATCH = "ERR_VOUCHER_SIZE_MISMATCH"
ERR_UNIT_ALREADY_UNDER_CONTRACT = "ERR_UNIT_ALREADY_UNDER_CONTRACT"
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"
ERR_RENT_NOT_REASONABLE = "ERR_RENT_NOT_REASONABLE"
ERR_FAIL_REQUIRES_ITEMS = "ERR_FAIL_REQUIRES_ITEMS"
ERR_OPEN_REPAIR_ITEMS = "ERR_OPEN_REPAIR_ITEMS"


def unauthenticated(message: str = "Missing or unknown X-User-Role header, or missing X-User-ID for an entity-backed role"):
    return APIError(ERR_UNAUTHENTICATED, message, 401)


def unauthorized(message: str = "Role not permitted to call this endpoint"):
    return APIError(ERR_UNAUTHORIZED, message, 403)


def not_found(message: str = "Referenced resource does not exist"):
    return APIError(ERR_NOT_FOUND, message, 404)


def invalid_state(message: str = "Target resource not in a state from which the requested transition is defined"):
    return APIError(ERR_INVALID_STATE, message, 409)


def stale_version(message: str = "OCC expected_*_version does not match the parent entity's current version"):
    return APIError(ERR_STALE_VERSION, message, 412)


def not_owner(message: str = "Acting Landlord does not own the resource's property chain"):
    return APIError(ERR_NOT_OWNER, message, 403)


def landlord_suspended(message: str = "Landlord is SUSPENDED (or TERMINATED) and the operation requires ACTIVE"):
    return APIError(ERR_LANDLORD_SUSPENDED, message, 409)


def increase_too_early(message: str = "Rent increase effective_date precedes the contract's next_recert_due_date"):
    return APIError(ERR_INCREASE_TOO_EARLY, message, 422)


def schedule_in_past(message: str = "Inspection scheduled_date precedes the current logical date"):
    return APIError(ERR_SCHEDULE_IN_PAST, message, 422)


def voucher_size_mismatch(message: str = "Voucher bedroom size is smaller than unit bedroom count"):
    return APIError(ERR_VOUCHER_SIZE_MISMATCH, message, 422)


def unit_already_under_contract(message: str = "Unit already has a HAPContract in a non-terminal status"):
    return APIError(ERR_UNIT_ALREADY_UNDER_CONTRACT, message, 409)


def invalid_amount(message: str = "Rent or income amount is non-positive where a positive value is required, or negative income"):
    return APIError(ERR_INVALID_AMOUNT, message, 422)


def rent_not_reasonable(message: str = "Requested rent exceeds the rent-reasonableness ceiling"):
    return APIError(ERR_RENT_NOT_REASONABLE, message, 422)


def fail_requires_items(message: str = "FAIL result submitted without any RepairItem attached to the inspection"):
    return APIError(ERR_FAIL_REQUIRES_ITEMS, message, 422)


def open_repair_items(message: str = "Reinspection requested while some RepairItems are not REPAIRED"):
    return APIError(ERR_OPEN_REPAIR_ITEMS, message, 409)
