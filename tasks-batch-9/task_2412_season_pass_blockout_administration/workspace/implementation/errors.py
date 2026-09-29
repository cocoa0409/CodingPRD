"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""

ERROR_CATALOG = {
    # --- authentication / authorisation ---
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or invalid"),
    "ERR_ROLE_NOT_PERMITTED": (403, "The caller role may not perform this operation"),
    "ERR_NOT_PASS_OWNER": (403, "The caller is not the owner of this season pass"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same user may not both open and decide this case"),
    # --- schema ---
    "ERR_INVALID_REQUEST": (400, "The request body or query parameters are invalid"),
    # --- existence ---
    "ERR_PROGRAM_NOT_FOUND": (404, "Pass program not found"),
    "ERR_TIER_NOT_FOUND": (404, "Pass tier not found"),
    "ERR_PARK_DAY_NOT_FOUND": (404, "Park day not found"),
    "ERR_ASSIGNMENT_NOT_FOUND": (404, "Blockout assignment not found"),
    "ERR_PASSHOLDER_NOT_FOUND": (404, "Passholder not found"),
    "ERR_PASS_NOT_FOUND": (404, "Season pass not found"),
    "ERR_PLAN_NOT_FOUND": (404, "Payment plan not found"),
    "ERR_INSTALLMENT_NOT_FOUND": (404, "Installment not found"),
    "ERR_RESERVATION_NOT_FOUND": (404, "Reservation not found"),
    "ERR_VISIT_NOT_FOUND": (404, "Visit not found"),
    "ERR_CASE_NOT_FOUND": (404, "Sharing case not found"),
    "ERR_UPGRADE_ORDER_NOT_FOUND": (404, "Upgrade order not found"),
    # --- concurrency ---
    "ERR_STALE_PASS_VERSION": (412, "The supplied season pass version is stale"),
    "ERR_STALE_PARK_DAY_VERSION": (412, "The supplied park day version is stale"),
    # --- gate readiness ---
    "ERR_PHOTO_NOT_CAPTURED": (422, "The pass has no captured photo or bound identity"),
    # --- state ---
    "ERR_INVALID_PROGRAM_TRANSITION": (409, "The requested program transition is not allowed"),
    "ERR_PROGRAM_STATUS_INVALID": (409, "The program status does not permit this operation"),
    "ERR_PROGRAM_NOT_IN_RENEWAL": (409, "The target program is not open for renewal"),
    "ERR_TIER_NOT_PUBLISHED": (409, "The tier transition is not allowed"),
    "ERR_PASS_ALREADY_PROCESSED": (409, "The pass has already been processed"),
    "ERR_PASS_NOT_ACTIVE": (409, "The season pass is not active"),
    "ERR_PASS_NOT_SUSPENDED": (409, "The season pass is not suspended"),
    "ERR_PASS_BILLING_NOT_CURRENT": (409, "The season pass billing is not current"),
    "ERR_PASS_NOT_RENEWABLE": (409, "The season pass is not renewable"),
    "ERR_INSTALLMENT_NOT_PAYABLE": (409, "The installment is not payable"),
    "ERR_RESERVATION_NOT_CANCELLABLE": (409, "The reservation is not cancellable"),
    "ERR_VISIT_ALREADY_CLOSED": (409, "The visit is already closed"),
    "ERR_INVALID_CASE_STATE": (409, "The sharing case is not in a state that permits this operation"),
    "ERR_APPEAL_LIMIT_REACHED": (409, "The appeal limit for this case has been reached"),
    "ERR_UPGRADE_ORDER_NOT_ACTIONABLE": (409, "The upgrade order is not actionable"),
    "ERR_ASSIGNMENT_ALREADY_LIFTED": (409, "The blockout assignment has already been lifted"),
    "ERR_PARK_DAY_CAPACITY_LOCKED": (409, "The park day is capacity locked"),
    # --- business safety ---
    "ERR_PASS_TRANSFER_PROHIBITED": (422, "The pass is under a transfer-prohibition hold"),
    "ERR_ANTIPASSBACK_VIOLATION": (422, "Anti-passback interval violated"),
    # --- business temporal ---
    "ERR_PARK_DAY_PROGRAM_MISMATCH": (422, "The park day belongs to a different program"),
    "ERR_ENTRY_DATE_MISMATCH": (422, "The entry timestamp does not fall on the park day"),
    "ERR_PARK_DAY_IN_PAST": (422, "The park day is in the past"),
    "ERR_ARRIVAL_WINDOW_INVALID": (422, "The arrival window is invalid"),
    "ERR_BLOCKOUT_DATE": (422, "The tier is blocked out on this park day"),
    # --- business referential ---
    "ERR_TIER_PROGRAM_MISMATCH": (422, "The tier belongs to a different program"),
    "ERR_DUPLICATE_ACTIVE_PASS": (422, "The passholder already holds a live pass in this program"),
    "ERR_DUPLICATE_BLOCKOUT_ASSIGNMENT": (422, "An active blockout already exists for this tier and day"),
    "ERR_DUPLICATE_RESERVATION": (422, "The pass already holds a reservation for this day"),
    "ERR_NOT_AN_UPGRADE": (422, "The requested tier change is not an upgrade"),
    "ERR_INVALID_EVIDENCE": (422, "The supplied evidence is invalid"),
    # --- business constraint ---
    "ERR_INSTALLMENT_COUNT_OUT_OF_RANGE": (422, "The installment count is out of range"),
    "ERR_DOWN_PAYMENT_TOO_LOW": (422, "The down payment is below the required minimum"),
    "ERR_RESERVATION_QUOTA_EXCEEDED": (422, "The peak reservation quota for this tier is exhausted"),
    "ERR_RESERVATION_REQUIRED": (422, "A confirmed reservation is required for this park day"),
    # --- business fiscal ---
    "ERR_PARK_DAY_CAPACITY_FULL": (422, "The park day has no reservation capacity left"),
    "ERR_RESERVATION_SLOT_FULL": (422, "The arrival window has no slots left"),
    "ERR_PAYMENT_AMOUNT_MISMATCH": (422, "The payment amount does not match the installment amount"),
    "ERR_UPGRADE_PAYMENT_INSUFFICIENT": (422, "The upgrade payment does not match the amount due"),
    "ERR_CURE_AMOUNT_MISMATCH": (422, "The cure amount does not match the outstanding missed installments"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Request failed"))
        self.error_id = error_id
        self.http_status = http_status or status
        self.message = message or default_message


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
