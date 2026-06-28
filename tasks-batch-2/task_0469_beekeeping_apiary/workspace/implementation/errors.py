"""Error catalog. Error IDs and HTTP statuses come verbatim from PRD §5 / SCAFFOLD errors."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth gates (PRD §2.1 / §2.8) ---
def unauthenticated(msg="Authentication required: X-User-ID or X-User-Role missing or unknown."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="Acting role is not permitted to perform this operation."):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def not_resource_owner(msg="ApiaryManager X-User-ID does not own the apiary owning the target resource."):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


# --- Existence (PRD §2.7) ---
def not_found(msg="Path-referenced resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def fk_not_found(msg="Body foreign key references a non-existent resource."):
    return ApiError("ERR_FK_NOT_FOUND", 404, msg)


# --- State ---
def invalid_state(msg="Resource is not in a state from which this transition is allowed."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def terminal_state(msg="Operation attempted on a terminal-state resource."):
    return ApiError("ERR_TERMINAL_STATE", 409, msg)


# --- Business safety / referential / temporal / constraint ---
def harvest_blocked_withdrawal(msg="A contributing hive is within its chemical withdrawal window."):
    return ApiError("ERR_HARVEST_BLOCKED_WITHDRAWAL", 409, msg)


def apiary_not_registered(msg="The hive's apiary registration is not ACTIVE."):
    return ApiError("ERR_APIARY_NOT_REGISTERED", 409, msg)


def hive_not_placeable(msg="Hive is not HEALTHY (or otherwise ineligible) at placement confirm."):
    return ApiError("ERR_HIVE_NOT_PLACEABLE", 409, msg)


def hive_double_booked(msg="Hive already CONFIRMED on a placement whose window overlaps the requested one."):
    return ApiError("ERR_HIVE_DOUBLE_BOOKED", 409, msg)


def site_capacity_exceeded(msg="Confirming would push overlapping-window hive count above max_hives_on_site."):
    return ApiError("ERR_SITE_CAPACITY_EXCEEDED", 409, msg)


def insufficient_brood_frames(msg="NUC ship draws more brood frames than the source hive holds."):
    return ApiError("ERR_INSUFFICIENT_BROOD_FRAMES", 422, msg)


def yard_capacity_exceeded(msg="Voiding the sale would push active_colony_count above the yard cap."):
    return ApiError("ERR_YARD_CAPACITY_EXCEEDED", 409, msg)


def empty_lot(msg="Extract attempted on a lot with zero RECORDED harvest contributions."):
    return ApiError("ERR_EMPTY_LOT", 422, msg)


def too_early(msg="Time-gated transition attempted before the logical clock reached the required date."):
    return ApiError("ERR_TOO_EARLY", 409, msg)


def stale_contract_version(msg="expected_contract_version does not match the contract's current version."):
    return ApiError("ERR_STALE_CONTRACT_VERSION", 412, msg)


# --- Well-formedness / generic validation ---
def invalid_request(msg="Malformed body, bad enum/type, missing required field, or uniqueness violation."):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def validation(msg="Field-level validation failure."):
    return ApiError("ERR_VALIDATION", 422, msg)
