"""Error types and the error catalog (id -> http status)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# id -> (http_status, default message)
ERROR_CATALOG = {
    'ERR_UNAUTHENTICATED': (401, 'Missing/unknown X-User-Role or missing X-User-ID'),
    'ERR_UNAUTHORIZED_ROLE': (403, 'Role not in the endpoint roles list'),
    'ERR_NOT_ASSIGNED_DISPATCHER': (403, 'Caller is not the dispatcher of record on the target resource'),
    'ERR_NOT_ASSIGNED_CAPTAIN': (403, 'Caller is not the captain of record on the target resource'),
    'ERR_NOT_FOUND': (404, 'Resource or referenced foreign key does not exist'),
    'ERR_INVALID_REQUEST': (400, 'Malformed body: missing required field, wrong type, unknown field, invalid enum, or non-positive quantity'),
    'ERR_STALE_VERSION': (412, 'Optimistic concurrency check failed: expected version does not match current version'),
    'ERR_INVALID_STATE': (409, 'Target resource is in a state that does not admit this transition'),
    'ERR_RELEASE_NOT_PENDING': (409, 'Release is not in PENDING_SIGNATURES'),
    'ERR_LEG_NOT_IN_FLIGHT': (409, 'Leg is not in ops_status DEPARTED'),
    'ERR_RELEASE_EXISTS': (409, 'A non-terminal FlightRelease already exists for the leg'),
    'ERR_MANIFEST_EXISTS': (409, 'A PayloadManifest already exists for the leg'),
    'ERR_PLAN_IN_USE': (409, 'A non-terminal release references the leg LOCKED plan'),
    'ERR_PLAN_NOT_LOCKED': (409, 'Operation requires the leg current plan to be LOCKED'),
    'ERR_MANIFEST_MISSING': (409, 'Operation requires a PayloadManifest for the leg'),
    'ERR_MEL_ITEM_EXPIRED': (409, 'An EXPIRED MelCdlItem exists on the aircraft'),
    'ERR_WORST_CASE_REQUIRED': (409, 'An OPEN MelCdlItem with fuel_penalty_pct > 0 forces wind_assumption WORST_CASE'),
    'ERR_WEATHER_NOT_CURRENT': (422, 'No ACTIVE WeatherPackage covers the current sched_arr_utc at the arrival station'),
    'ERR_WEATHER_BELOW_MINIMA': (422, 'Covering weather is below arrival-station minima (plus MEL bump)'),
    'ERR_CAPTAIN_NOT_QUALIFIED': (422, 'Captain lacks the aircraft type_code in qualified_type_codes'),
    'ERR_DUAL_ROLE_ASSIGNMENT': (422, 'Captain and dispatcher license_no coincide'),
    'ERR_REST_VIOLATION': (409, 'Non-overlapping shifts of one dispatcher separated by less than 30 minutes'),
    'ERR_SHIFT_OVERLAP': (409, 'Shift windows of one dispatcher intersect'),
    'ERR_WEATHER_WINDOW_OVERLAP': (409, 'ACTIVE weather windows of one station intersect'),
    'ERR_WINDOW_INVALID': (422, 'Window end is not strictly after start'),
    'ERR_DELAY_INVALID_TIME': (422, 'Delay times must be strictly increasing'),
    'ERR_REPAIR_WINDOW_EXCEEDED': (422, 'repair_deadline_utc exceeds the deferral-category interval'),
    'ERR_DUPLICATE_RESOURCE': (409, 'Unique field collision'),
    'ERR_DUPLICATE_SIGNATURE': (409, 'A valid signature already exists for this slot in the current cycle'),
    'ERR_MZFW_EXCEEDED': (422, 'zero_fuel_weight_kg exceeds aircraft mzfw_kg'),
    'ERR_MTOW_EXCEEDED': (422, 'takeoff_weight_kg exceeds aircraft mtow_kg'),
    'ERR_MLW_EXCEEDED': (422, 'landing_weight_kg exceeds aircraft mlw_kg'),
    'ERR_CG_OUT_OF_ENVELOPE': (422, 'cg_percent_mac outside the applicable envelope'),
    'ERR_PAYLOAD_EXCEEDS_LIMIT': (422, 'total_payload_kg exceeds max_payload_kg'),
    'ERR_FUEL_EXCEEDS_CAPACITY': (422, 'required_fuel_kg exceeds aircraft fuel_capacity_kg'),
    'ERR_NO_SUITABLE_ALTERNATE': (422, 'Alternate selection pool is empty'),
    'ERR_DISPATCHER_OVERLOADED': (409, 'Dispatcher workload_leg_count reached max_active_legs'),
    'ERR_DESK_OVERLOADED': (409, 'Shift would exceed desk max_dispatchers at some covered instant'),
    'ERR_NO_ACTIVE_SHIFT': (422, 'No ACTIVE DeskShift for the assigned dispatcher covers the current clock'),
    'ERR_NO_DESK_AVAILABLE': (422, 'Desk auto-select pool is empty'),
    'ERR_NO_DISPATCHER_AVAILABLE': (422, 'Dispatcher auto-select pool is empty'),
    'ERR_INTERNAL': (500, 'Internal server error'),
}


def err(error_id, message=None):
    status, default_msg = ERROR_CATALOG[error_id]
    return ApiError(error_id, status, message or default_msg)
