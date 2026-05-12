"""Error classes and error ID constants per scaffold §1.6 and PRD §5."""


class APIError(Exception):
    """Carries error_id, message, http_status for the standard error envelope."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (mirror PRD §5)
ERR_MISSING_AUTH_HEADERS = "ERR_MISSING_AUTH_HEADERS"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_POLL_INTERVAL_OUT_OF_RANGE = "ERR_POLL_INTERVAL_OUT_OF_RANGE"
ERR_VALVE_GROUP_INVALID = "ERR_VALVE_GROUP_INVALID"
ERR_VALVE_GROUP_PUMP_MISMATCH = "ERR_VALVE_GROUP_PUMP_MISMATCH"
ERR_PUMP_INTERLOCK_BUSY = "ERR_PUMP_INTERLOCK_BUSY"
ERR_PLAN_WINDOW_OVERLAP = "ERR_PLAN_WINDOW_OVERLAP"
ERR_QUOTA_EXCEEDED = "ERR_QUOTA_EXCEEDED"
ERR_OVERRIDE_AMOUNT_INVALID = "ERR_OVERRIDE_AMOUNT_INVALID"
ERR_OVERRIDE_ALREADY_DECIDED = "ERR_OVERRIDE_ALREADY_DECIDED"
ERR_FEEDBACK_ALREADY_RECORDED = "ERR_FEEDBACK_ALREADY_RECORDED"
ERR_BILL_PERIOD_INVALID = "ERR_BILL_PERIOD_INVALID"
ERR_BILL_STATE_CONFLICT = "ERR_BILL_STATE_CONFLICT"
ERR_PRECONDITION_NOT_MET = "ERR_PRECONDITION_NOT_MET"


# Convenience constructors
def auth_required(msg="Missing or blank X-User-ID/X-User-Role header"):
    return APIError(ERR_MISSING_AUTH_HEADERS, msg, 401)


def forbidden(msg="Role not authorized for this endpoint"):
    return APIError(ERR_FORBIDDEN_ROLE, msg, 403)


def not_found(msg="Resource not found"):
    return APIError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg="Operation not legal in current state"):
    return APIError(ERR_INVALID_STATE, msg, 409)


def validation_error(msg="Invalid request body"):
    return APIError(ERR_VALIDATION, msg, 400)


def stale_version(msg="Version mismatch (OCC)"):
    return APIError(ERR_STALE_VERSION, msg, 409)


def poll_interval_out_of_range(msg="poll_interval_seconds must be in [30, 3600]"):
    return APIError(ERR_POLL_INTERVAL_OUT_OF_RANGE, msg, 422)


def valve_group_invalid(msg="ValveGroup definition violates constraints"):
    return APIError(ERR_VALVE_GROUP_INVALID, msg, 422)


def valve_group_pump_mismatch(msg="ValveGroup.pump_id does not match Plot.pump_id"):
    return APIError(ERR_VALVE_GROUP_PUMP_MISMATCH, msg, 422)


def pump_interlock_busy(msg="Pump-and-valve interlock blocks dispatch"):
    return APIError(ERR_PUMP_INTERLOCK_BUSY, msg, 409)


def plan_window_overlap(msg="IrrigationPlan window overlaps an existing plan"):
    return APIError(ERR_PLAN_WINDOW_OVERLAP, msg, 409)


def quota_exceeded(msg="ControlCommand would exceed quota without APPROVED override"):
    return APIError(ERR_QUOTA_EXCEEDED, msg, 422)


def override_amount_invalid(msg="extra_liters out of range"):
    return APIError(ERR_OVERRIDE_AMOUNT_INVALID, msg, 422)


def override_already_decided(msg="Quota override already decided"):
    return APIError(ERR_OVERRIDE_ALREADY_DECIDED, msg, 409)


def feedback_already_recorded(msg="ControlCommand feedback already recorded"):
    return APIError(ERR_FEEDBACK_ALREADY_RECORDED, msg, 409)


def bill_period_invalid(msg="WaterBill period invalid"):
    return APIError(ERR_BILL_PERIOD_INVALID, msg, 422)


def bill_state_conflict(msg="WaterBill version conflict"):
    return APIError(ERR_BILL_STATE_CONFLICT, msg, 409)


def precondition_not_met(msg="Precondition not met"):
    return APIError(ERR_PRECONDITION_NOT_MET, msg, 422)
