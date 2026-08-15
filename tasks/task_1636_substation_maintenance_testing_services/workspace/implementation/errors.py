"""Error classes carrying error_id + http_status from the scaffold catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience factories ------------------------------------------------------

def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_validation(msg="Malformed body"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_not_found(msg="Referenced resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_policy_not_found(msg="No AssetClassPolicy exists for the asset_class"):
    return ApiError("ERR_POLICY_NOT_FOUND", 404, msg)


def err_duplicate_key(msg="Uniqueness constraint violated"):
    return ApiError("ERR_DUPLICATE_KEY", 409, msg)


def err_state_transition(msg="Current entity state does not permit the requested transition"):
    return ApiError("ERR_STATE_TRANSITION", 409, msg)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_certification_required(msg="Acting technician lacks the required ACTIVE certification"):
    return ApiError("ERR_CERTIFICATION_REQUIRED", 403, msg)


def err_segregation_of_duties(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_open_critical_defect(msg="Asset has an open critical (C1) defect"):
    return ApiError("ERR_OPEN_CRITICAL_DEFECT", 422, msg)


def err_interval_in_past(msg="Interval start is not in the future"):
    return ApiError("ERR_INTERVAL_IN_PAST", 422, msg)


def err_outside_window(msg="Action attempted outside [start_ts, end_ts)"):
    return ApiError("ERR_OUTSIDE_WINDOW", 422, msg)


def err_outage_window_conflict(msg="Outage window overlaps or violates 24h buffer"):
    return ApiError("ERR_OUTAGE_WINDOW_CONFLICT", 409, msg)


def err_spare_reservation_conflict(msg="Spare reservation overlaps an existing ACTIVE reservation"):
    return ApiError("ERR_SPARE_RESERVATION_CONFLICT", 409, msg)


def err_no_compatible_spare(msg="No eligible SpareUnit found"):
    return ApiError("ERR_NO_COMPATIBLE_SPARE", 422, msg)


def err_step_order_violation(msg="Lower-sequence sibling steps not yet VERIFIED"):
    return ApiError("ERR_STEP_ORDER_VIOLATION", 409, msg)


def err_steps_not_verified(msg="Not all switching steps are VERIFIED"):
    return ApiError("ERR_STEPS_NOT_VERIFIED", 409, msg)


def err_outage_needs_revalidation(msg="Window needs revalidation"):
    return ApiError("ERR_OUTAGE_NEEDS_REVALIDATION", 409, msg)


def err_deferral_limit_exceeded(msg="Deferral limit (2) reached"):
    return ApiError("ERR_DEFERRAL_LIMIT_EXCEEDED", 422, msg)


def err_asset_not_in_service(msg="Asset is not IN_SERVICE"):
    return ApiError("ERR_ASSET_NOT_IN_SERVICE", 409, msg)


def err_relay_coordination_violation(msg="Upstream pickup below 1.3x downstream pickup"):
    return ApiError("ERR_RELAY_COORDINATION_VIOLATION", 422, msg)


def err_asset_decommissioned(msg="Operation references a DECOMMISSIONED asset"):
    return ApiError("ERR_ASSET_DECOMMISSIONED", 422, msg)


def err_active_reservations(msg="Spare unit has ACTIVE reservations"):
    return ApiError("ERR_ACTIVE_RESERVATIONS", 409, msg)


def err_outage_not_cleared(msg="Linked outage window is not CLEARED"):
    return ApiError("ERR_OUTAGE_NOT_CLEARED", 409, msg)


def err_outage_capacity_exceeded(msg="estimated_hours exceeds remaining uncommitted hours"):
    return ApiError("ERR_OUTAGE_CAPACITY_EXCEEDED", 422, msg)
