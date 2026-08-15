"""Error classes carrying error_id / message / http_status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---- Auth ----
def unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role header"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def segregation_of_duties(msg="Approver must differ from preparer"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


# ---- Existence ----
def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


# ---- Malformed ----
def invalid_request(msg="Malformed payload"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


# ---- State ----
def invalid_state(msg="Entity not in a valid from-state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def project_not_open(msg="Capital project is not OPEN"):
    return ApiError("ERR_PROJECT_NOT_OPEN", msg, 409)


def asset_not_in_service(msg="Asset is not IN_SERVICE or FULLY_DEPRECIATED"):
    return ApiError("ERR_ASSET_NOT_IN_SERVICE", msg, 409)


def already_disposed(msg="Asset is DISPOSED"):
    return ApiError("ERR_ALREADY_DISPOSED", msg, 409)


def run_not_counting(msg="Inventory run is not in COUNTING status"):
    return ApiError("ERR_RUN_NOT_COUNTING", msg, 409)


def asset_not_in_scope(msg="Asset was not seeded into this inventory run"):
    return ApiError("ERR_ASSET_NOT_IN_SCOPE", msg, 409)


def asset_under_inventory_review(msg="Asset has an open inventory exception"):
    return ApiError("ERR_ASSET_UNDER_INVENTORY_REVIEW", msg, 409)


def unresolved_inventory_items(msg="Run has unresolved inventory items"):
    return ApiError("ERR_UNRESOLVED_INVENTORY_ITEMS", msg, 409)


def uncounted_lines(msg="Run has lines that have not been counted"):
    return ApiError("ERR_UNCOUNTED_LINES", msg, 409)


# ---- Uniqueness / structural ----
def duplicate_tag(msg="Duplicate unique identifier (asset_tag / project_code / class_code)"):
    return ApiError("ERR_DUPLICATE_TAG", msg, 409)


def duplicate_run_period(msg="An OPEN run already exists for this period"):
    return ApiError("ERR_DUPLICATE_RUN_PERIOD", msg, 409)


def period_already_posted(msg="A POSTED run already exists for this period"):
    return ApiError("ERR_PERIOD_ALREADY_POSTED", msg, 409)


def period_gap(msg="Run period must be exactly latest POSTED period + 1 month"):
    return ApiError("ERR_PERIOD_GAP", msg, 409)


def period_closed(msg="Effective period is on or before the latest POSTED run period"):
    return ApiError("ERR_PERIOD_CLOSED", msg, 409)


def impairment_review_open(msg="An OPEN impairment review already exists for the asset"):
    return ApiError("ERR_IMPAIRMENT_REVIEW_OPEN", msg, 409)


def duplicate_schedule(msg="Schedule already exists for (asset_id, schedule_type, schedule_year)"):
    return ApiError("ERR_DUPLICATE_SCHEDULE", msg, 409)


# ---- Monetary / field value ----
def below_capitalization_threshold(msg="Amount is below the class capitalization threshold"):
    return ApiError("ERR_BELOW_CAPITALIZATION_THRESHOLD", msg, 422)


def invalid_amount(msg="Invalid monetary amount"):
    return ApiError("ERR_INVALID_AMOUNT", msg, 422)


def invalid_salvage_value(msg="salvage_value_cents must be >= 0 and < acquisition_cost_cents"):
    return ApiError("ERR_INVALID_SALVAGE_VALUE", msg, 422)


def invalid_disposal_fields(msg="Invalid disposal field combination"):
    return ApiError("ERR_INVALID_DISPOSAL_FIELDS", msg, 422)


def bonus_not_allowed(msg="bonus_elected not permitted by asset class"):
    return ApiError("ERR_BONUS_NOT_ALLOWED", msg, 422)


def no_impairment_indicated(msg="Computed write-down is zero; dismiss instead"):
    return ApiError("ERR_NO_IMPAIRMENT_INDICATED", msg, 422)


def invalid_schedule_fields(msg="Invalid schedule field combination"):
    return ApiError("ERR_INVALID_SCHEDULE_FIELDS", msg, 422)


def field_immutable(msg="Field may not be edited on an IN_SERVICE asset"):
    return ApiError("ERR_FIELD_IMMUTABLE", msg, 422)


def stale_version(msg="expected_asset_version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)
