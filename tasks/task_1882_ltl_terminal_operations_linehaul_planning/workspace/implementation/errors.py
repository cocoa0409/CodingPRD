"""Error types and the scaffold error catalog (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or invalid X-User-Role or X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role is not permitted to call this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Path id does not resolve"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_reference_not_found(msg="Body foreign-key field does not resolve"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Missing required field, enum violation, or range violation"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Entity state precondition for the requested transition not met"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_trailer_version(msg="expected_trailer_version does not match trailer.version"):
    return ApiError("ERR_STALE_TRAILER_VERSION", msg, 412)


def err_osd_hold(msg="Shipment is under an active OS&D hold and may not be manifested"):
    return ApiError("ERR_SHIPMENT_ON_OSD_HOLD", msg, 409)


def err_destination_mismatch(msg="Trailer destination does not match shipment destination_terminal_id"):
    return ApiError("ERR_DESTINATION_MISMATCH", msg, 422)


def err_door_kind_mismatch(msg="Dock door kind does not match its intended use"):
    return ApiError("ERR_DOOR_KIND_MISMATCH", msg, 422)


def err_stop_outside_shift(msg="planned_arrival_minute is outside the route shift window"):
    return ApiError("ERR_STOP_OUTSIDE_SHIFT", msg, 422)


def err_relay_connect_infeasible(msg="Relay leg departs less than 45 minutes after the prior leg's planned arrival"):
    return ApiError("ERR_RELAY_CONNECT_INFEASIBLE", msg, 422)


def err_leg_window_invalid(msg="planned_arrival_utc must be strictly after planned_departure_utc"):
    return ApiError("ERR_LEG_WINDOW_INVALID", msg, 422)


def err_trailer_over_capacity(msg="Projected loaded weight or cube exceeds trailer caps"):
    return ApiError("ERR_TRAILER_OVER_CAPACITY", msg, 422)


def err_not_billable(msg="Shipment is not billable: not DELIVERED or an OS&D case is open"):
    return ApiError("ERR_SHIPMENT_NOT_BILLABLE", msg, 409)


def err_trailer_not_loadable(msg="mark-ready requires at least one ACTIVE manifest entry and utilization_pct >= 60.0"):
    return ApiError("ERR_TRAILER_NOT_LOADABLE", msg, 422)


def err_scan_shipment_mismatch(msg="Inspection scan_id references a scan of a different shipment"):
    return ApiError("ERR_SCAN_SHIPMENT_MISMATCH", msg, 422)


def err_terminal_closed(msg="Operation targets a Terminal with status CLOSED"):
    return ApiError("ERR_TERMINAL_CLOSED", msg, 409)


def err_route_not_dispatched(msg="Stop arrival requires the route to be DISPATCHED"):
    return ApiError("ERR_ROUTE_NOT_DISPATCHED", msg, 409)


def err_relay_sequence(msg="Departing leg requires the prior same-trailer relay leg to be ARRIVED"):
    return ApiError("ERR_RELAY_SEQUENCE_VIOLATION", msg, 409)
