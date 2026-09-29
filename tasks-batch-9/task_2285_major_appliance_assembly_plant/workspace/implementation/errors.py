"""Error catalog (SCAFFOLD §1.6 / PRD §5) and the ApiError exception."""

ERROR_CATALOG = {
    # --- envelope / auth ---
    "ERR_UNAUTHENTICATED": (401, "X-User-ID header is required"),
    "ERR_ROLE_NOT_PERMITTED": (403, "Role is not permitted to perform this operation"),
    "ERR_INVALID_REQUEST": (400, "Request body or query parameters are invalid"),
    "ERR_SUPPLIER_SCOPE_VIOLATION": (403, "Supplier callers may only act on their own records"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The submitter of an engineering change may not decide it"),
    # --- concurrency ---
    "ERR_STALE_MODEL_VARIANT_VERSION": (412, "Model variant was modified by another writer"),
    "ERR_STALE_LINE_VERSION": (412, "Line was modified by another writer"),
    # --- existence ---
    "ERR_LINE_NOT_FOUND": (404, "Line not found"),
    "ERR_STATION_NOT_FOUND": (404, "Station not found"),
    "ERR_MODEL_VARIANT_NOT_FOUND": (404, "Model variant not found"),
    "ERR_SUPPLIER_NOT_FOUND": (404, "Supplier not found"),
    "ERR_PART_NOT_FOUND": (404, "Part not found"),
    "ERR_BOM_LINE_NOT_FOUND": (404, "BOM line not found"),
    "ERR_DELIVERY_CALL_NOT_FOUND": (404, "Delivery call not found"),
    "ERR_SHIFT_PLAN_NOT_FOUND": (404, "Shift plan not found"),
    "ERR_BUILD_SLOT_NOT_FOUND": (404, "Build slot not found"),
    "ERR_PRODUCTION_UNIT_NOT_FOUND": (404, "Production unit not found"),
    "ERR_ENGINEERING_CHANGE_NOT_FOUND": (404, "Engineering change not found"),
    "ERR_WARRANTY_RETURN_NOT_FOUND": (404, "Warranty return not found"),
    # --- state / uniqueness ---
    "ERR_INVALID_STATE": (409, "Entity is not in a state that allows this transition"),
    "ERR_DUPLICATE_CODE": (409, "Code already in use"),
    # --- quality gates ---
    "ERR_TEST_NOT_APPLICABLE": (422, "This test type does not apply to the unit's model variant"),
    "ERR_QUALITY_GATE_ORDER": (409, "Quality gates must be completed in order"),
    "ERR_UNIT_QUARANTINED": (409, "Unit is quarantined"),
    "ERR_EFFICIENCY_LIMIT_EXCEEDED": (422, "Efficiency index exceeds the certification limit"),
    # --- product / BOM lifecycle ---
    "ERR_MODEL_NOT_RELEASED": (409, "Model variant is not in RELEASED status"),
    "ERR_BOM_NOT_EFFECTIVE": (422, "No effective BOM resolves for the requested sequence index"),
    "ERR_PART_CHANGE_PENDING": (409, "A part on the effective BOM is not available for production"),
    "ERR_LINE_NOT_STOPPED": (409, "Line must be stopped to cut in an engineering change"),
    "ERR_CUT_IN_INDEX_TOO_LOW": (422, "Cut-in sequence index must be ahead of released production"),
    "ERR_REPLACEMENT_PART_REQUIRED": (422, "A replacement part is required to cut in this change"),
    "ERR_SERVICE_OBLIGATION_ACTIVE": (409, "Service part supply obligation has not elapsed"),
    "ERR_CHANGEOVER_REQUIRED": (409, "Line is tooled for a different product family"),
    # --- scheduling / capacity ---
    "ERR_DOCK_WINDOW_CONFLICT": (409, "Delivery window conflicts with another call at this station"),
    "ERR_SHIFT_WINDOW_OVERLAP": (409, "Shift window overlaps an active plan on this line"),
    "ERR_NO_SHIFT_COVERAGE": (422, "No active shift plan covers the requested instant"),
    "ERR_SEQUENCE_INDEX_TAKEN": (409, "Sequence index is already taken on this line"),
    "ERR_LINE_POSTURE_BLOCKED": (409, "Line posture does not allow this operation"),
    "ERR_SUPPLIER_NOT_APPROVED": (409, "Supplier is not approved"),
    "ERR_SYNC_DELIVERY_MISSING": (422, "No synchronous delivery covers a sequenced module"),
    "ERR_OPTION_LOAD_WINDOW_EXCEEDED": (422, "Option content exceeds the rolling window cap"),
    "ERR_PRESENTATION_SLOTS_EXHAUSTED": (422, "Line-side presentation slots are exhausted at a station"),
    "ERR_LABOR_CAPACITY_EXCEEDED": (422, "Shift labour capacity exceeded"),
    # --- routing fallbacks ---
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_METHOD_NOT_ALLOWED": (405, "Method not allowed"),
    "ERR_INTERNAL": (500, "Internal server error"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        status, default_message = ERROR_CATALOG.get(error_id, (400, error_id))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else status
        self.message = message if message is not None else default_message


def invalid(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
