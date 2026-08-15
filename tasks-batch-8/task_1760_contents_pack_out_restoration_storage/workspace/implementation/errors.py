"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_NOT_REFERRAL_SUBCONTRACTOR = "ERR_NOT_REFERRAL_SUBCONTRACTOR"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_STALE_ITEM_VERSION = "ERR_STALE_ITEM_VERSION"
ERR_STALE_JOB_VERSION = "ERR_STALE_JOB_VERSION"
ERR_INVALID_TRANSITION = "ERR_INVALID_TRANSITION"
ERR_ITEM_TERMINAL = "ERR_ITEM_TERMINAL"
ERR_ITEM_NOT_SALVAGEABLE = "ERR_ITEM_NOT_SALVAGEABLE"
ERR_JOB_ITEMS_NOT_TERMINAL = "ERR_JOB_ITEMS_NOT_TERMINAL"
ERR_JOB_NOT_READY_FOR_PACKBACK = "ERR_JOB_NOT_READY_FOR_PACKBACK"
ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK = "ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK"
ERR_OPEN_CLAIM_BLOCKS_PACKBACK = "ERR_OPEN_CLAIM_BLOCKS_PACKBACK"
ERR_STATEMENT_PERIOD_OPEN = "ERR_STATEMENT_PERIOD_OPEN"
ERR_HAZMAT_STORAGE_FORBIDDEN = "ERR_HAZMAT_STORAGE_FORBIDDEN"
ERR_CLIMATE_CLASS_INCOMPATIBLE = "ERR_CLIMATE_CLASS_INCOMPATIBLE"
ERR_HAZMAT_MANIFEST_REQUIRED = "ERR_HAZMAT_MANIFEST_REQUIRED"
ERR_VAULT_CAPACITY_EXCEEDED = "ERR_VAULT_CAPACITY_EXCEEDED"
ERR_DUPLICATE_BARCODE = "ERR_DUPLICATE_BARCODE"
ERR_SUBCONTRACTOR_AT_CAPACITY = "ERR_SUBCONTRACTOR_AT_CAPACITY"
ERR_CREW_WINDOW_OVERLAP = "ERR_CREW_WINDOW_OVERLAP"
ERR_WINDOW_INVALID = "ERR_WINDOW_INVALID"
ERR_CUSTODY_EVENT_OUT_OF_ORDER = "ERR_CUSTODY_EVENT_OUT_OF_ORDER"
ERR_SPECIALTY_REQUIRED = "ERR_SPECIALTY_REQUIRED"
ERR_PAYMENT_EXCEEDS_BALANCE = "ERR_PAYMENT_EXCEEDS_BALANCE"
ERR_INVOICE_BALANCE_OUTSTANDING = "ERR_INVOICE_BALANCE_OUTSTANDING"


def unauthenticated(msg="Authentication headers missing"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not authorized for this endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def sod(msg="Segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def not_referral_subcontractor(msg="Not the referral's subcontractor"):
    return ApiError(ERR_NOT_REFERRAL_SUBCONTRACTOR, 403, msg)


def validation(msg="Request validation failed"):
    return ApiError(ERR_VALIDATION, 400, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def stale_item_version(msg="Stale item version"):
    return ApiError(ERR_STALE_ITEM_VERSION, 412, msg)


def stale_job_version(msg="Stale job version"):
    return ApiError(ERR_STALE_JOB_VERSION, 412, msg)


def invalid_transition(msg="Invalid state transition"):
    return ApiError(ERR_INVALID_TRANSITION, 409, msg)


def item_terminal(msg="Item is in a terminal processing status"):
    return ApiError(ERR_ITEM_TERMINAL, 409, msg)


def item_not_salvageable(msg="Item condition_triage is not SALVAGEABLE"):
    return ApiError(ERR_ITEM_NOT_SALVAGEABLE, 409, msg)


def job_items_not_terminal(msg="Not all items of the job are terminal"):
    return ApiError(ERR_JOB_ITEMS_NOT_TERMINAL, 409, msg)


def job_not_ready_for_packback(msg="Job structure_status is not COMPLETE"):
    return ApiError(ERR_JOB_NOT_READY_FOR_PACKBACK, 409, msg)


def no_eligible_items(msg="No eligible items for pack-back"):
    return ApiError(ERR_NO_ELIGIBLE_ITEMS_FOR_PACKBACK, 422, msg)


def open_claim_blocks_packback(msg="An eligible item has an open handling claim"):
    return ApiError(ERR_OPEN_CLAIM_BLOCKS_PACKBACK, 409, msg)


def statement_period_open(msg="Job has a PROVISIONAL statement or no FINALIZED statements"):
    return ApiError(ERR_STATEMENT_PERIOD_OPEN, 409, msg)


def hazmat_storage_forbidden(msg="Hazmat items may not be placed in vault storage"):
    return ApiError(ERR_HAZMAT_STORAGE_FORBIDDEN, 422, msg)


def climate_incompatible(msg="Item category requires a CLIMATE_CONTROLLED vault"):
    return ApiError(ERR_CLIMATE_CLASS_INCOMPATIBLE, 422, msg)


def hazmat_manifest_required(msg="Hazmat disposal requires manifest_number and HAZARDOUS_WASTE method"):
    return ApiError(ERR_HAZMAT_MANIFEST_REQUIRED, 422, msg)


def vault_capacity_exceeded(msg="Vault capacity would be exceeded"):
    return ApiError(ERR_VAULT_CAPACITY_EXCEEDED, 422, msg)


def duplicate_barcode(msg="Barcode already used within this job"):
    return ApiError(ERR_DUPLICATE_BARCODE, 409, msg)


def subcontractor_at_capacity(msg="Subcontractor is at referral capacity"):
    return ApiError(ERR_SUBCONTRACTOR_AT_CAPACITY, 422, msg)


def crew_window_overlap(msg="Crew window overlaps another confirmed schedule"):
    return ApiError(ERR_CREW_WINDOW_OVERLAP, 422, msg)


def window_invalid(msg="window_end_hour must be greater than window_start_hour"):
    return ApiError(ERR_WINDOW_INVALID, 422, msg)


def custody_out_of_order(msg="Custody event_at must be strictly increasing per referral"):
    return ApiError(ERR_CUSTODY_EVENT_OUT_OF_ORDER, 422, msg)


def specialty_required(msg="Specialty referral requirement not satisfied"):
    return ApiError(ERR_SPECIALTY_REQUIRED, 422, msg)


def payment_exceeds_balance(msg="Payment amount exceeds invoice balance"):
    return ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, 422, msg)


def invoice_balance_outstanding(msg="Invoice balance is not zero"):
    return ApiError(ERR_INVOICE_BALANCE_OUTSTANDING, 422, msg)
