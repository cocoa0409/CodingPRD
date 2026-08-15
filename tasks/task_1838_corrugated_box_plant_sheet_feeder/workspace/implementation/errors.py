"""Error classes carrying scaffold error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_ownership_mismatch(msg="Customer-role caller does not own the target program/release"):
    return ApiError("ERR_OWNERSHIP_MISMATCH", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Malformed body: missing required field, invalid enum, non-positive number"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_quantity(msg="Quantity out of its allowed range"):
    return ApiError("ERR_INVALID_QUANTITY", msg, 400)


def err_invalid_state(msg="Target resource not in a state from which the requested transition is defined"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="expected_order_version does not match the BoxOrder's current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_program_not_releasable(msg="Release create/approve/ship while program status does not permit it"):
    return ApiError("ERR_PROGRAM_NOT_RELEASABLE", msg, 409)


def err_quote_not_open(msg="Accept attempted on a quote that is not OPEN"):
    return ApiError("ERR_QUOTE_NOT_OPEN", msg, 409)


def err_quote_expired(msg="Accept attempted after quote.expires_on per the logical clock"):
    return ApiError("ERR_QUOTE_EXPIRED", msg, 409)


def err_ect_spec_not_met(msg="order.min_ect_required exceeds the grade's ect_rating_lbs_per_in"):
    return ApiError("ERR_ECT_SPEC_NOT_MET", msg, 422)


def err_warp_below_threshold(msg="BOARD_WARP claim with measured_warp_pct < 2.0"):
    return ApiError("ERR_WARP_BELOW_THRESHOLD", msg, 422)


def err_supplier_required(msg="SHEET_FEEDER order without sheet_supplier_name, or INTERNAL order with one"):
    return ApiError("ERR_SUPPLIER_REQUIRED", msg, 422)


def err_board_source_mismatch(msg="INTERNAL order sent to mark-sheets-received, or SHEET_FEEDER order attached to a corrugator run"):
    return ApiError("ERR_BOARD_SOURCE_MISMATCH", msg, 422)


def err_duplicate_code(msg="board grade_code already exists"):
    return ApiError("ERR_DUPLICATE_CODE", msg, 409)


def err_machine_type_mismatch(msg="Run on a non-CORRUGATOR shift, or booking machine incompatible with routing_type"):
    return ApiError("ERR_MACHINE_TYPE_MISMATCH", msg, 422)


def err_order_grade_mismatch(msg="Attached order's grade differs from the run's grade"):
    return ApiError("ERR_ORDER_GRADE_MISMATCH", msg, 422)


def err_trim_width_exceeds_web(msg="Attach would push consumed_width_in above web_width_in"):
    return ApiError("ERR_TRIM_WIDTH_EXCEEDS_WEB", msg, 422)


def err_trim_waste_excessive(msg="At run completion, trim_waste_in exceeds 8.0 inches"):
    return ApiError("ERR_TRIM_WASTE_EXCESSIVE", msg, 422)


def err_overrun_tolerance_exceeded(msg="produced_qty outside the +/-10% inclusive band around quantity"):
    return ApiError("ERR_OVERRUN_TOLERANCE_EXCEEDED", msg, 422)


def err_sod_self_adjudication(msg="Resolving user id equals the claim's filed_by_user_id"):
    return ApiError("ERR_SOD_CLAIM_SELF_ADJUDICATION", msg, 422)


def err_grade_discontinued(msg="Order creation or quote acceptance references a DISCONTINUED grade"):
    return ApiError("ERR_GRADE_DISCONTINUED", msg, 422)


def err_outside_shift_window(msg="Run/booking window not contained in the shift window"):
    return ApiError("ERR_OUTSIDE_SHIFT_WINDOW", msg, 422)


def err_run_window_overlap(msg="Corrugator run overlaps another non-CANCELLED run on the shift"):
    return ApiError("ERR_RUN_WINDOW_OVERLAP", msg, 409)


def err_booking_changeover_conflict(msg="Booking violates the append-after-latest rule with the 15/45-minute ink changeover gap"):
    return ApiError("ERR_BOOKING_CHANGEOVER_CONFLICT", msg, 409)


def err_credit_limit_exceeded(msg="Acceptance would push customer exposure above credit_limit_dollars"):
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", msg, 422)


def err_insufficient_program_balance(msg="Release qty exceeds program available_qty"):
    return ApiError("ERR_INSUFFICIENT_PROGRAM_BALANCE", msg, 422)
