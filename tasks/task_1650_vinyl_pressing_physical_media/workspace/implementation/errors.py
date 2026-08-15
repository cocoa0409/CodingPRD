"""Error classes and error ID constants for the Vinyl Pressing API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Auth ---
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"

# --- Request shape ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# --- Not found ---
ERR_CUSTOMER_NOT_FOUND = "ERR_CUSTOMER_NOT_FOUND"
ERR_RELEASE_NOT_FOUND = "ERR_RELEASE_NOT_FOUND"
ERR_PRESS_ORDER_NOT_FOUND = "ERR_PRESS_ORDER_NOT_FOUND"
ERR_TOOLING_JOB_NOT_FOUND = "ERR_TOOLING_JOB_NOT_FOUND"
ERR_TEST_PRESSING_NOT_FOUND = "ERR_TEST_PRESSING_NOT_FOUND"
ERR_PRINT_JOB_NOT_FOUND = "ERR_PRINT_JOB_NOT_FOUND"
ERR_PRESS_LINE_NOT_FOUND = "ERR_PRESS_LINE_NOT_FOUND"
ERR_PLATING_BATH_NOT_FOUND = "ERR_PLATING_BATH_NOT_FOUND"
ERR_QC_REPORT_NOT_FOUND = "ERR_QC_REPORT_NOT_FOUND"
ERR_INVENTORY_LOT_NOT_FOUND = "ERR_INVENTORY_LOT_NOT_FOUND"
ERR_SHIPMENT_NOT_FOUND = "ERR_SHIPMENT_NOT_FOUND"
ERR_INVOICE_NOT_FOUND = "ERR_INVOICE_NOT_FOUND"

# --- State ---
ERR_ORDER_INVALID_STATE = "ERR_ORDER_INVALID_STATE"
ERR_TOOLING_JOB_INVALID_STATE = "ERR_TOOLING_JOB_INVALID_STATE"
ERR_TEST_PRESSING_INVALID_STATE = "ERR_TEST_PRESSING_INVALID_STATE"
ERR_PRINT_JOB_INVALID_STATE = "ERR_PRINT_JOB_INVALID_STATE"
ERR_QC_REPORT_ALREADY_DECIDED = "ERR_QC_REPORT_ALREADY_DECIDED"
ERR_SHIPMENT_INVALID_STATE = "ERR_SHIPMENT_INVALID_STATE"
ERR_INVOICE_INVALID_STATE = "ERR_INVOICE_INVALID_STATE"
ERR_CUSTOMER_SUSPENDED = "ERR_CUSTOMER_SUSPENDED"

# --- OCC ---
ERR_STALE_VERSION = "ERR_STALE_VERSION"

# --- Safety / compliance ---
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

# --- Referential gates ---
ERR_STAMPERS_NOT_READY = "ERR_STAMPERS_NOT_READY"
ERR_PRINT_JOBS_NOT_DELIVERED = "ERR_PRINT_JOBS_NOT_DELIVERED"
ERR_QC_HOLD_REQUIRES_REPRESS = "ERR_QC_HOLD_REQUIRES_REPRESS"

# --- Business constraint ---
ERR_ORDER_BELOW_MINIMUM = "ERR_ORDER_BELOW_MINIMUM"
ERR_VARIANT_BELOW_MINIMUM = "ERR_VARIANT_BELOW_MINIMUM"
ERR_VARIANT_SUM_MISMATCH = "ERR_VARIANT_SUM_MISMATCH"
ERR_DUPLICATE_CODE = "ERR_DUPLICATE_CODE"
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"
ERR_CHANGEOVER_BUFFER_VIOLATION = "ERR_CHANGEOVER_BUFFER_VIOLATION"
ERR_MAINTENANCE_WINDOW_CONFLICT = "ERR_MAINTENANCE_WINDOW_CONFLICT"
ERR_BATH_TIME_CONFLICT = "ERR_BATH_TIME_CONFLICT"
ERR_BATH_RINSE_GAP_VIOLATION = "ERR_BATH_RINSE_GAP_VIOLATION"
ERR_SLOT_UNITS_MISMATCH = "ERR_SLOT_UNITS_MISMATCH"

# --- Temporal ---
ERR_LEAD_TIME_VIOLATION = "ERR_LEAD_TIME_VIOLATION"
ERR_PRESS_DATE_NOT_REACHED = "ERR_PRESS_DATE_NOT_REACHED"

# --- Fiscal / capacity ---
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
ERR_LINE_DAILY_CAPACITY_EXCEEDED = "ERR_LINE_DAILY_CAPACITY_EXCEEDED"
ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED = "ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED"
ERR_PAYMENT_EXCEEDS_BALANCE = "ERR_PAYMENT_EXCEEDS_BALANCE"


def raise_error(error_id, message=None):
    messages = {
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: "X-User-ID or X-User-Role header missing, or role not declared",
        ERR_UNAUTHORIZED_ROLE: "Authenticated role is not in the endpoint's permitted roles",
        ERR_INVALID_REQUEST: "Request body is invalid",
        ERR_CUSTOMER_NOT_FOUND: "Customer id does not exist",
        ERR_RELEASE_NOT_FOUND: "Release id does not exist",
        ERR_PRESS_ORDER_NOT_FOUND: "Press order id does not exist",
        ERR_TOOLING_JOB_NOT_FOUND: "Tooling job id does not exist",
        ERR_TEST_PRESSING_NOT_FOUND: "Test pressing id does not exist",
        ERR_PRINT_JOB_NOT_FOUND: "Print job id does not exist",
        ERR_PRESS_LINE_NOT_FOUND: "Press line id does not exist",
        ERR_PLATING_BATH_NOT_FOUND: "Plating bath id does not exist",
        ERR_QC_REPORT_NOT_FOUND: "QC report id does not exist",
        ERR_INVENTORY_LOT_NOT_FOUND: "Inventory lot id does not exist",
        ERR_SHIPMENT_NOT_FOUND: "Shipment id does not exist",
        ERR_INVOICE_NOT_FOUND: "Invoice id does not exist",
        ERR_ORDER_INVALID_STATE: "PressOrder is not in the required state for this transition",
        ERR_TOOLING_JOB_INVALID_STATE: "ToolingJob stage does not allow the requested event",
        ERR_TEST_PRESSING_INVALID_STATE: "TestPressing is not in the required state",
        ERR_PRINT_JOB_INVALID_STATE: "PrintJob stage does not allow the requested event",
        ERR_QC_REPORT_ALREADY_DECIDED: "QC report has already been decided",
        ERR_SHIPMENT_INVALID_STATE: "Shipment is not in the required state",
        ERR_INVOICE_INVALID_STATE: "Invoice is not in the required state, or order not invoiceable",
        ERR_CUSTOMER_SUSPENDED: "Customer is SUSPENDED (credit hold)",
        ERR_STALE_VERSION: "Expected version does not match the resource's current version",
        ERR_SEGREGATION_OF_DUTIES: "QC decision may not be made by the filing inspector",
        ERR_STAMPERS_NOT_READY: "Latest tooling job is not STAMPER_READY",
        ERR_PRINT_JOBS_NOT_DELIVERED: "Not all non-CANCELLED print jobs are DELIVERED",
        ERR_QC_HOLD_REQUIRES_REPRESS: "QC report outcome is HOLD; decision must be REPRESS",
        ERR_ORDER_BELOW_MINIMUM: "quantity_ordered is below the 100 unit minimum",
        ERR_VARIANT_BELOW_MINIMUM: "A variant quantity is below its color-config minimum",
        ERR_VARIANT_SUM_MISMATCH: "Variant quantities do not sum to quantity_ordered",
        ERR_DUPLICATE_CODE: "line_code, bath_code, or catalog_number is already in use",
        ERR_SLOT_OVERLAP: "PRODUCTION slot overlaps another PRODUCTION slot on the same line and date",
        ERR_CHANGEOVER_BUFFER_VIOLATION: "Adjacent slots of different color families require a 1-hour changeover buffer",
        ERR_MAINTENANCE_WINDOW_CONFLICT: "PRODUCTION slot conflicts with a MAINTENANCE window",
        ERR_BATH_TIME_CONFLICT: "Bath booking overlaps another booking on the same bath",
        ERR_BATH_RINSE_GAP_VIOLATION: "Bath bookings lack the mandatory rinse gap between them",
        ERR_SLOT_UNITS_MISMATCH: "Total planned units are below the remaining requirement, or a slot exceeds hours x hourly rate",
        ERR_LEAD_TIME_VIOLATION: "requested_completion_date is earlier than today + 21 days",
        ERR_PRESS_DATE_NOT_REACHED: "The logical clock date has not reached the order's earliest slot date",
        ERR_CREDIT_LIMIT_EXCEEDED: "Outstanding balance plus quote total exceeds the credit limit",
        ERR_LINE_DAILY_CAPACITY_EXCEEDED: "Sum of planned_units on the line and date exceeds daily_unit_capacity",
        ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED: "Zone daily receiving pallet capacity exceeded",
        ERR_PAYMENT_EXCEEDS_BALANCE: "Payment or credit memo exceeds the invoice's remaining balance",
    }
    statuses = {
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: 400,
        ERR_UNAUTHORIZED_ROLE: 403,
        ERR_INVALID_REQUEST: 400,
        ERR_CUSTOMER_NOT_FOUND: 404,
        ERR_RELEASE_NOT_FOUND: 404,
        ERR_PRESS_ORDER_NOT_FOUND: 404,
        ERR_TOOLING_JOB_NOT_FOUND: 404,
        ERR_TEST_PRESSING_NOT_FOUND: 404,
        ERR_PRINT_JOB_NOT_FOUND: 404,
        ERR_PRESS_LINE_NOT_FOUND: 404,
        ERR_PLATING_BATH_NOT_FOUND: 404,
        ERR_QC_REPORT_NOT_FOUND: 404,
        ERR_INVENTORY_LOT_NOT_FOUND: 404,
        ERR_SHIPMENT_NOT_FOUND: 404,
        ERR_INVOICE_NOT_FOUND: 404,
        ERR_ORDER_INVALID_STATE: 409,
        ERR_TOOLING_JOB_INVALID_STATE: 409,
        ERR_TEST_PRESSING_INVALID_STATE: 409,
        ERR_PRINT_JOB_INVALID_STATE: 409,
        ERR_QC_REPORT_ALREADY_DECIDED: 409,
        ERR_SHIPMENT_INVALID_STATE: 409,
        ERR_INVOICE_INVALID_STATE: 409,
        ERR_CUSTOMER_SUSPENDED: 409,
        ERR_STALE_VERSION: 412,
        ERR_SEGREGATION_OF_DUTIES: 403,
        ERR_STAMPERS_NOT_READY: 409,
        ERR_PRINT_JOBS_NOT_DELIVERED: 409,
        ERR_QC_HOLD_REQUIRES_REPRESS: 409,
        ERR_ORDER_BELOW_MINIMUM: 422,
        ERR_VARIANT_BELOW_MINIMUM: 422,
        ERR_VARIANT_SUM_MISMATCH: 422,
        ERR_DUPLICATE_CODE: 409,
        ERR_SLOT_OVERLAP: 409,
        ERR_CHANGEOVER_BUFFER_VIOLATION: 409,
        ERR_MAINTENANCE_WINDOW_CONFLICT: 409,
        ERR_BATH_TIME_CONFLICT: 409,
        ERR_BATH_RINSE_GAP_VIOLATION: 409,
        ERR_SLOT_UNITS_MISMATCH: 422,
        ERR_LEAD_TIME_VIOLATION: 422,
        ERR_PRESS_DATE_NOT_REACHED: 409,
        ERR_CREDIT_LIMIT_EXCEEDED: 402,
        ERR_LINE_DAILY_CAPACITY_EXCEEDED: 409,
        ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED: 409,
        ERR_PAYMENT_EXCEEDS_BALANCE: 400,
    }
    raise ApiError(error_id, message or messages.get(error_id, error_id), statuses[error_id])
