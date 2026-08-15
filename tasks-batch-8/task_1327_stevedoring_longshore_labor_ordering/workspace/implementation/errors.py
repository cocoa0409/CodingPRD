"""Error type and the full error catalog (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    return ApiError(error_id, message, http_status)


# --- catalog helpers (id, http) ---
def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return err("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Role not permitted on this endpoint"):
    return err("ERR_FORBIDDEN", msg, 403)


def not_found(msg="Resource not found"):
    return err("ERR_NOT_FOUND", msg, 404)


def validation(msg="Invalid request"):
    return err("ERR_VALIDATION", msg, 400)


def cargo_plan_required(msg="Cargo plan may not be empty: planned_moves and planned_tons are both zero"):
    return err("ERR_CARGO_PLAN_REQUIRED", msg, 400)


def shift_window_invalid(msg="Shift end must be later than start and duration must not exceed 960 minutes"):
    return err("ERR_SHIFT_WINDOW_INVALID", msg, 400)


def fault_pct_out_of_range(msg="fault_pct is required on an ACCEPTED decision and must be within 0..100"):
    return err("ERR_FAULT_PCT_OUT_OF_RANGE", msg, 400)


def stale_gang_order(msg="expected_gang_order_version does not match the gang order's current version"):
    return err("ERR_STALE_GANG_ORDER_VERSION", msg, 412)


def stale_worker(msg="expected_worker_version does not match the worker's current version"):
    return err("ERR_STALE_WORKER_VERSION", msg, 412)


def stale_invoice(msg="expected_invoice_version does not match the invoice's current version"):
    return err("ERR_STALE_INVOICE_VERSION", msg, 412)


def invalid_state(msg="Entity state does not permit the requested operation"):
    return err("ERR_INVALID_STATE", msg, 409)


def shift_not_open(msg="Gang orders may only be placed against a shift in OPEN_FOR_ORDERS"):
    return err("ERR_SHIFT_NOT_OPEN_FOR_ORDERS", msg, 409)


def invoice_not_finalizable(msg="Invoice may only be finalized once the vessel call is COMPLETED"):
    return err("ERR_INVOICE_NOT_FINALIZABLE", msg, 409)


def work_stoppage(msg="The vessel's work posture blocks this operation"):
    return err("ERR_WORK_STOPPAGE_ACTIVE", msg, 409)


def no_equipment(msg="start-work requires assigned_equipment_ok to be true"):
    return err("ERR_NO_EQUIPMENT_ASSIGNED", msg, 409)


def worker_not_on_gang(msg="Worker holds no qualifying assignment on this gang order"):
    return err("ERR_WORKER_NOT_ON_GANG", msg, 422)


def worker_double_booked(msg="Worker is already assigned to an overlapping shift window"):
    return err("ERR_WORKER_DOUBLE_BOOKED", msg, 409)


def equipment_window_conflict(msg="Booking violates the 30-minute buffered-window rule"):
    return err("ERR_EQUIPMENT_WINDOW_CONFLICT", msg, 409)


def move_period_overlap(msg="Move-record period overlaps another RECORDED period on this gang order"):
    return err("ERR_MOVE_PERIOD_OVERLAP", msg, 409)


def timesheet_exceeds_shift(msg="work_minutes exceeds the shift duration plus 120 minutes"):
    return err("ERR_TIMESHEET_EXCEEDS_SHIFT", msg, 422)


def gang_full(msg="Gang is already at its required headcount"):
    return err("ERR_GANG_FULL", msg, 409)


def equipment_unavailable(msg="Equipment unit is DOWN and cannot be booked"):
    return err("ERR_EQUIPMENT_UNAVAILABLE", msg, 409)


def duplicate_registration(msg="registration_number already exists"):
    return err("ERR_DUPLICATE_REGISTRATION", msg, 409)


def segregation(msg="Segregation of duties violated"):
    return err("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def invoice_credit_limit(msg="Invoice total exceeds the vessel call's credit limit"):
    return err("ERR_INVOICE_CREDIT_LIMIT", msg, 402)


def payment_exceeds_balance(msg="Payment exceeds the remaining balance"):
    return err("ERR_PAYMENT_EXCEEDS_BALANCE", msg, 422)


def worker_ineligible(msg="Worker fails dispatch eligibility"):
    return err("ERR_WORKER_INELIGIBLE", msg, 409)
