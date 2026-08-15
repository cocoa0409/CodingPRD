"""Error type and catalog (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    fail("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role is not permitted on this endpoint"):
    fail("ERR_FORBIDDEN", 403, msg)


def not_owner(msg="Caller is not the owner or assigned party of the target resource"):
    fail("ERR_NOT_RESOURCE_OWNER", 403, msg)


def not_found(what="resource"):
    fail("ERR_NOT_FOUND", 404, f"The requested {what} does not exist")


def stale(msg="expected_work_order_version does not match current WorkOrder.version"):
    fail("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="Resource status does not allow the requested transition"):
    fail("ERR_INVALID_STATE", 409, msg)


def entry_rule(msg="Entry authorization rule violated"):
    fail("ERR_ENTRY_RULE_VIOLATION", 422, msg)


def notice_too_short(msg="notice_posted_at missing or scheduled start inside the notice lead time"):
    fail("ERR_ENTRY_NOTICE_TOO_SHORT", 422, msg)


def vendor_not_active(msg="Vendor is not ACTIVE"):
    fail("ERR_VENDOR_NOT_ACTIVE", 409, msg)


def vendor_insurance(msg="Vendor insurance does not cover the scheduled start"):
    fail("ERR_VENDOR_INSURANCE_EXPIRED", 409, msg)


def tech_conflict(msg="Technician has an overlapping scheduled work order"):
    fail("ERR_TECHNICIAN_SCHEDULE_CONFLICT", 409, msg)


def vendor_conflict_err(msg="Vendor job gap is smaller than the property travel buffer"):
    fail("ERR_VENDOR_SCHEDULE_CONFLICT", 409, msg)


def recall_expired(msg="Recall window has expired since completion"):
    fail("ERR_RECALL_WINDOW_EXPIRED", 409, msg)


def trade_mismatch(msg="Assignee trade or property does not match the work order"):
    fail("ERR_TRADE_MISMATCH", 409, msg)


def part_stock(msg="Insufficient stock or part belongs to a different property"):
    fail("ERR_PART_INSUFFICIENT_STOCK", 409, msg)


def duplicate_sku(msg="Part sku already exists within the property"):
    fail("ERR_DUPLICATE_SKU", 409, msg)


def open_purchase_requests(msg="Work order has purchase requests in PENDING or APPROVED status"):
    fail("ERR_OPEN_PURCHASE_REQUESTS", 409, msg)


def signoff_required(msg="Resident sign-off is required before completion"):
    fail("ERR_RESIDENT_SIGNOFF_REQUIRED", 409, msg)


def photos_required(msg="At least one completion photo URL is required"):
    fail("ERR_COMPLETION_PHOTOS_REQUIRED", 422, msg)


def chargeback_lines(msg="A non-empty line_items array with valid line fields is required"):
    fail("ERR_CHARGEBACK_LINES_REQUIRED", 422, msg)


def validation(msg="Malformed request"):
    fail("ERR_VALIDATION", 400, msg)
