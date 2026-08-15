"""Error classes and error ID constants (from SCAFFOLD errors table / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id):
    return ERROR_MAP[error_id]


def raise_error(error_id, message=None):
    http, default_msg = ERROR_MAP[error_id]
    raise ApiError(error_id, message or default_msg, http)


ERROR_MAP = {
    "ERR_MISSING_CONTEXT_HEADER": (400, "X-User-ID or X-User-Role header missing or role not declared"),
    "ERR_INVALID_REQUEST": (400, "Malformed body, missing required field, invalid enum value, negative quantity, or unknown field"),
    "ERR_FORBIDDEN_ROLE": (403, "Role not permitted for this endpoint"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "Segregation of duties violation"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_INVALID_STATE_TRANSITION": (409, "Target resource lifecycle does not permit the requested transition"),
    "ERR_STALE_VERSION": (412, "expected version does not match current version"),
    "ERR_RACK_NOT_OPERATING": (409, "Rack is not OPERATING"),
    "ERR_WATER_LOOP_SANITATION_HOLD": (409, "Water loop is in sanitation"),
    "ERR_CONTRACT_NOT_ACTIVE": (409, "Contract is not ACTIVE"),
    "ERR_SHIFT_NOT_PUBLISHED": (409, "Labor shift is not PUBLISHED"),
    "ERR_BATCH_SAFETY_PENDING": (422, "Batch safety_status is PENDING"),
    "ERR_BATCH_QUARANTINED": (422, "Batch safety_status is QUARANTINED"),
    "ERR_BATCH_CONDEMNED": (422, "Batch safety_status is CONDEMNED"),
    "ERR_SAME_DAY_PACK_VIOLATION": (422, "Pack attempted on a different UTC date than harvested_at"),
    "ERR_SANITATION_RECENCY_MISSING": (422, "No PASSED sanitation cycle within 72h"),
    "ERR_HARVEST_NOT_DUE": (422, "mark-harvest-ready attempted before projected_harvest_at - 48h"),
    "ERR_CYCLE_NOT_DUE": (422, "Sanitation start attempted more than 30 minutes before scheduled_start_at"),
    "ERR_TOWER_INTERVAL_OVERLAP": (422, "Tower allocation interval overlap"),
    "ERR_SANITATION_OVERLAP": (422, "Sanitation cycle window overlap or 4h buffer violation"),
    "ERR_CYCLE_DURATION_INVALID": (422, "Cycle window shorter than 2h or longer than 12h"),
    "ERR_SHIFT_OVERLAP": (422, "Worker shift assignment overlap"),
    "ERR_CERTIFICATION_MISSING": (422, "Worker lacks required certification"),
    "ERR_HEADCOUNT_EXCEEDED": (422, "Assignment would exceed headcount_required"),
    "ERR_WEEKLY_HOURS_EXCEEDED": (422, "Assignment would exceed weekly hours hard cap"),
    "ERR_STRESS_CAP_REACHED": (422, "Stress extension cap reached"),
    "ERR_CONTRACT_COMMITMENT_EXCEEDED": (422, "Weekly commitment pool exceeded"),
    "ERR_DOCK_CAPACITY_EXCEEDED": (422, "Dock day quota exceeded"),
    "ERR_SHIPMENT_CROP_MISMATCH": (422, "Shipment line batch crop differs from contract crop"),
    "ERR_SHIPMENT_WINDOW_CLOSED": (422, "Shipment window closed"),
    "ERR_LINE_NOT_PACKED": (409, "Shipment line still RESERVED at ship time"),
    "ERR_SHIP_DATE_MISMATCH": (422, "ship_date mismatch with batch harvest date or window outside ship_date"),
    "ERR_PRICE_BELOW_FLOOR": (422, "price_per_pound_cents below crop floor"),
    "ERR_CONTRACT_WINDOW_INVALID": (422, "end_date <= start_date"),
    "ERR_WEEK_NOT_SETTLABLE": (422, "Week not settlable"),
    "ERR_ENERGY_PERIOD_OVERLAP": (422, "Energy reading period overlap"),
    "ERR_CROP_RETIRED": (422, "Crop is RETIRED"),
    "ERR_NO_ACTIVE_RECIPE": (422, "Crop has no ACTIVE recipe"),
    "ERR_RECIPE_IN_USE": (422, "Recipe referenced by non-terminal batches"),
    "ERR_DUPLICATE_CODE": (422, "Duplicate code"),
    "ERR_REPLANT_NO_TOWERS": (422, "Tower selector found no candidate rack"),
    "ERR_REPLANT_ALREADY_QUEUED": (422, "A QUEUED ReplantRequest already exists for this failure"),
    "ERR_REPLANT_STILL_QUEUED": (422, "ReplantRequest still QUEUED"),
    "ERR_BATCH_NOT_PACKED": (409, "Batch is not PACKED"),
    "ERR_BATCH_POUNDS_INSUFFICIENT": (422, "Batch packed_available_lb insufficient"),
    "ERR_CROP_IN_USE": (422, "Crop retire blocked"),
    "ERR_HARVEST_IN_FLIGHT": (409, "Batch HARVEST_READY or HARVESTED on loop"),
    "ERR_RACK_HAS_ACTIVE_BATCHES": (409, "Rack has ACTIVE tower allocations"),
    "ERR_SHIPMENT_IN_FLIGHT": (409, "Contract has PACKED shipment"),
    "ERR_UNCONFIRMED_ASSIGNMENTS": (409, "Assignments remain ASSIGNED"),
}
