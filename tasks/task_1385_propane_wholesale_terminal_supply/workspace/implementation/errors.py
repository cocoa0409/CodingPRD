"""Error classes and error ID constants (per SCAFFOLD §1.6 catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing/invalid X-User-Role or X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_invalid_request(msg="Malformed request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_forbidden(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_dealer_mismatch(msg="DealerUser acting on a resource whose dealer_id != X-User-ID"):
    return ApiError("ERR_DEALER_MISMATCH", 403, msg)


def err_not_found(msg="Path id does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_referenced_not_found(msg="Body foreign key does not resolve to an existing entity"):
    return ApiError("ERR_REFERENCED_NOT_FOUND", 422, msg)


def err_stale_terminal_version(msg="expected_terminal_version != Terminal.version"):
    return ApiError("ERR_STALE_TERMINAL_VERSION", 412, msg)


def err_stale_dealer_version(msg="expected_dealer_version != Dealer.version"):
    return ApiError("ERR_STALE_DEALER_VERSION", 412, msg)


def err_invalid_state(msg="Entity not in a valid from-state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_contract_not_active(msg="Referenced contract not ACTIVE"):
    return ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, msg)


def err_dealer_suspended(msg="Dealer credit_status == SUSPENDED"):
    return ApiError("ERR_DEALER_SUSPENDED", 409, msg)


def err_truck_not_available(msg="Truck status != AVAILABLE"):
    return ApiError("ERR_TRUCK_NOT_AVAILABLE", 409, msg)


def err_terminal_not_curtailed(msg="Terminal allocation_posture != CURTAILED"):
    return ApiError("ERR_TERMINAL_NOT_CURTAILED", 409, msg)


def err_cold_snap_already_active(msg="Another ColdSnapEvent on this terminal is already ACTIVE"):
    return ApiError("ERR_COLD_SNAP_ALREADY_ACTIVE", 409, msg)


def err_run_not_computed(msg="Run not in COMPUTED"):
    return ApiError("ERR_RUN_NOT_COMPUTED", 409, msg)


def err_payment_already_returned(msg="Return attempted on a non-POSTED payment"):
    return ApiError("ERR_PAYMENT_ALREADY_RETURNED", 409, msg)


def err_driver_hours_exceeded(msg="Truck weekly committed minutes + candidate exceeds limit"):
    return ApiError("ERR_DRIVER_HOURS_EXCEEDED", 422, msg)


def err_reserve_floor_breach(msg="Load would breach the effective reserve floor"):
    return ApiError("ERR_RESERVE_FLOOR_BREACH", 422, msg)


def err_truck_capacity_exceeded(msg="allocated_gal > truck.capacity_gal"):
    return ApiError("ERR_TRUCK_CAPACITY_EXCEEDED", 422, msg)


def err_truck_terminal_mismatch(msg="Truck home terminal != order terminal"):
    return ApiError("ERR_TRUCK_TERMINAL_MISMATCH", 422, msg)


def err_zone_terminal_mismatch(msg="Freight zone does not belong to the order terminal"):
    return ApiError("ERR_ZONE_TERMINAL_MISMATCH", 422, msg)


def err_contract_terminal_mismatch(msg="DealerContract terminal != order terminal"):
    return ApiError("ERR_CONTRACT_TERMINAL_MISMATCH", 422, msg)


def err_contract_dealer_mismatch(msg="DealerContract belongs to a different dealer than the caller"):
    return ApiError("ERR_CONTRACT_DEALER_MISMATCH", 422, msg)


def err_truck_schedule_conflict(msg="Buffered window overlap with another order on the same truck"):
    return ApiError("ERR_TRUCK_SCHEDULE_CONFLICT", 409, msg)


def err_rack_capacity_exceeded(msg="Overlapping SCHEDULED/LOADED orders >= terminal.rack_bay_count"):
    return ApiError("ERR_RACK_CAPACITY_EXCEEDED", 422, msg)


def err_window_invalid(msg="Window end <= start"):
    return ApiError("ERR_WINDOW_INVALID", 400, msg)


def err_outside_contract_window(msg="Date outside the contract window"):
    return ApiError("ERR_OUTSIDE_CONTRACT_WINDOW", 422, msg)


def err_shipment_window_violation(msg="scheduled_arrival_date outside the receipt window"):
    return ApiError("ERR_SHIPMENT_WINDOW_VIOLATION", 422, msg)


def err_duplicate_zone_code(msg="zone_code already exists on this terminal"):
    return ApiError("ERR_DUPLICATE_ZONE_CODE", 409, msg)


def err_duplicate_truck_unit(msg="unit_number already exists on this terminal"):
    return ApiError("ERR_DUPLICATE_TRUCK_UNIT", 409, msg)


def err_duplicate_index_publication(msg="(index_name, effective_date) already published"):
    return ApiError("ERR_DUPLICATE_INDEX_PUBLICATION", 409, msg)


def err_volume_invalid(msg="Volume not a valid positive integer"):
    return ApiError("ERR_VOLUME_INVALID", 400, msg)


def err_credit_limit_exceeded(msg="committed_before + provisional_total_cents > credit_limit_cents"):
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402, msg)


def err_overpayment(msg="Payment amount exceeds total open invoice balance"):
    return ApiError("ERR_OVERPAYMENT", 422, msg)


def err_no_index_published(msg="No index publication effective on the reference date"):
    return ApiError("ERR_NO_INDEX_PUBLISHED", 422, msg)


def err_insufficient_supply(msg="requested_gal > available_to_promise_gal"):
    return ApiError("ERR_INSUFFICIENT_SUPPLY", 422, msg)
