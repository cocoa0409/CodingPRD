"""Error classes and error ID constants (from the scaffold's error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for the endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_ownership(msg="Customer X-User-ID does not own the target order/invoice"):
    return ApiError("ERR_OWNERSHIP_MISMATCH", 403, msg)


def err_validation(msg="Missing required field, bad type, out-of-range enum, or uniqueness violation"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_not_found(msg="Referenced resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_stale_version(msg="expected_*_version no longer equals the parent entity's version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_state(msg="Transition not allowed from the resource's current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_already_terminal(msg="Resource is in a terminal state; no further transitions"):
    return ApiError("ERR_ALREADY_TERMINAL", 409, msg)


def err_sod(msg="Segregation of duties violation"):
    return ApiError("ERR_SOD_VIOLATION", 403, msg)


def err_wc_ratio(msg="Batch water plus requested extra would push w/c above max_wc_ratio"):
    return ApiError("ERR_WC_RATIO_EXCEEDED", 422, msg)


def err_mix_not_active(msg="Mix design not ACTIVE"):
    return ApiError("ERR_MIX_NOT_ACTIVE", 409, msg)


def err_price_list_missing(msg="No exactly-one ACTIVE price list for (plant_id, mix_design_id)"):
    return ApiError("ERR_PRICE_LIST_MISSING", 409, msg)


def err_slump(msg="Order slump outside +/-1.0 in of the mix design slump"):
    return ApiError("ERR_SLUMP_OUT_OF_TOLERANCE", 422, msg)


def err_window(msg="pour_window_end not strictly after pour_window_start"):
    return ApiError("ERR_ORDER_WINDOW_INVALID", 422, msg)


def err_pour_date_past(msg="pour_date before the current logical-clock date"):
    return ApiError("ERR_POUR_DATE_PAST", 422, msg)


def err_break_too_early(msg="Break recorded before cast_at + 7d / + 28d"):
    return ApiError("ERR_BREAK_TOO_EARLY", 422, msg)


def err_plant_batch_conflict(msg="Batch interval overlaps another in-flight batch interval on the same plant"):
    return ApiError("ERR_PLANT_BATCH_CONFLICT", 409, msg)


def err_truck_overlap(msg="Batch time before the truck's latest prior batch_time + 90 minutes"):
    return ApiError("ERR_TRUCK_OVERLAP", 409, msg)


def err_truck_not_available(msg="Truck not AVAILABLE"):
    return ApiError("ERR_TRUCK_NOT_AVAILABLE", 409, msg)


def err_no_truck_available(msg="Selector found zero eligible trucks"):
    return ApiError("ERR_NO_TRUCK_AVAILABLE", 409, msg)


def err_truck_capacity(msg="Load qty exceeds the truck's capacity_yd3"):
    return ApiError("ERR_TRUCK_CAPACITY_EXCEEDED", 422, msg)


def err_short_load_forbidden(msg="Load below min_load_yd3 while customer.short_load_allowed is false"):
    return ApiError("ERR_SHORT_LOAD_FORBIDDEN", 422, msg)


def err_volume(msg="Volume not conserved"):
    return ApiError("ERR_VOLUME_NOT_CONSERVED", 422, msg)


def err_index_dup(msg="A cement price index already exists for (plant_id, effective_month)"):
    return ApiError("ERR_INDEX_MONTH_DUPLICATE", 409, msg)


def err_order_has_active_loads(msg="Cancel blocked: order has loads in SCHEDULED..POURING"):
    return ApiError("ERR_ORDER_HAS_ACTIVE_LOADS", 409, msg)


def err_credit_hold(msg="Customer on credit HOLD"):
    return ApiError("ERR_CREDIT_HOLD", 402, msg)


def err_payment_mismatch(msg="Payment amount_cents != invoice total_cents"):
    return ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422, msg)
