"""Error catalog. Error IDs and HTTP statuses come verbatim from PRD §5 / SCAFFOLD §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, default_msg):
    def _make(msg=None):
        return ApiError(error_id, http_status, msg or default_msg)
    return _make


# --- Universal gates (PRD §2.12 ordering) ---
unauthenticated = err("ERR_UNAUTHENTICATED", 401,
                      "Authentication required: X-User-ID/X-User-Role missing or unknown role.")
forbidden_role = err("ERR_FORBIDDEN_ROLE", 403,
                     "Acting role is not permitted to perform this operation.")
not_found = err("ERR_NOT_FOUND", 404, "Referenced resource does not exist.")
invalid_state = err("ERR_INVALID_STATE", 409,
                    "Resource is not in a state from which this transition is defined.")
stale_version = err("ERR_STALE_VERSION", 412,
                    "The expected version does not match the resource's current version.")

# --- Business rules ---
tank_not_operational = err("ERR_TANK_NOT_OPERATIONAL", 409,
                           "Tank posture or cohort operational status forbids the operation.")
withdrawal_active = err("ERR_WITHDRAWAL_ACTIVE", 409,
                        "Harvest is forbidden while the cohort is not HEALTHY or is within the withdrawal window.")
tank_occupancy_overlap = err("ERR_TANK_OCCUPANCY_OVERLAP", 409,
                             "New stocking interval overlaps an existing occupancy interval on the same tank.")
treatment_window_conflict = err("ERR_TREATMENT_WINDOW_CONFLICT", 409,
                                "New treatment starts before a prior treatment's withdrawal_end_at on this tank.")
fish_count_mismatch = err("ERR_FISH_COUNT_MISMATCH", 422,
                          "Sum of planned split fish counts does not equal the source cohort's fish_count.")
lot_depleted = err("ERR_LOT_DEPLETED", 409, "A referenced product lot is DEPLETED at confirm time.")
insufficient_lot_weight = err("ERR_INSUFFICIENT_LOT_WEIGHT", 422,
                              "Reservation exceeds the product lot's available weight.")
tank_biomass_exceeded = err("ERR_TANK_BIOMASS_EXCEEDED", 422,
                            "Operation would push tank current_biomass_kg above max_biomass_kg.")
broodstock_insufficient = err("ERR_BROODSTOCK_INSUFFICIENT", 422,
                              "Cohort draw exceeds the broodstock batch's remaining fingerlings.")
invalid_request = err("ERR_INVALID_REQUEST", 400,
                      "Missing required field, bad type, out-of-range numeric, or invalid enum value.")
duplicate_code = err("ERR_DUPLICATE_CODE", 409, "Species code already exists.")
validation_limit_range = err("ERR_VALIDATION_LIMIT_RANGE", 400,
                             "Pagination limit/offset out of range.")
invalid_split_target = err("ERR_INVALID_SPLIT_TARGET", 409,
                           "A planned split target tank posture is not OPEN.")
harvest_count_exceeds = err("ERR_HARVEST_COUNT_EXCEEDS", 422,
                            "Harvested/planned fish count exceeds the cohort's fish_count.")
processing_weight_exceeds = err("ERR_PROCESSING_WEIGHT_EXCEEDS", 422,
                                "actual_processed_weight_kg exceeds the batch's input_live_weight_kg.")
empty_order = err("ERR_EMPTY_ORDER", 422, "Confirm attempted on a sales order with zero lines.")
treatment_not_due = err("ERR_TREATMENT_NOT_DUE", 409,
                        "Treatment complete/clear attempted before its boundary.")
water_temp_out_of_band = err("ERR_WATER_TEMP_OUT_OF_BAND", 422,
                             "Reading water_temp_c is outside the residing cohorts' species band.")
duplicate_line_lot = err("ERR_DUPLICATE_LINE_LOT", 409,
                         "Two lines on the same order reference the same product_lot_id.")
posture_override_invalid = err("ERR_POSTURE_OVERRIDE_INVALID", 400,
                               "posture_override value must be RESTRICTED, FROZEN, or null.")
grading_split_empty = err("ERR_GRADING_SPLIT_EMPTY", 422,
                          "planned_splits is empty or contains a split with fish_count <= 0.")
clock_backwards = err("ERR_CLOCK_BACKWARDS", 422,
                      "Event timestamp precedes resource creation or is in the future relative to the clock.")
