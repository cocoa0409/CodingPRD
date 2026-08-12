"""Error type carrying the scaffold-declared error_id / http_status.

Every error id and HTTP status below is read from SCAFFOLD.yaml section 1.6
(error catalog). Nothing here is invented.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# --- priority 1-3: auth / permissions / ownership ---------------------------
def missing_context(msg="X-User-ID or X-User-Role header missing or empty"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def insufficient_permissions(msg="Caller's role is not authorized for this endpoint"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


def not_resource_owner(msg="Caller does not own the referenced resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


def self_certification(msg="Certifying technician must differ from the performing technician"):
    return ApiError("ERR_SELF_CERTIFICATION", 403, msg)


# --- malformed payloads ------------------------------------------------------
def invalid_request(msg="Request payload is missing a required field or is malformed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- priority 4: existence (one id per resource type) ------------------------
def facility_not_found(msg="Facility id not found"):
    return ApiError("ERR_FACILITY_NOT_FOUND", 404, msg)


def tank_not_found(msg="TankSystem id not found"):
    return ApiError("ERR_TANK_SYSTEM_NOT_FOUND", 404, msg)


def component_not_found(msg="Component id not found"):
    return ApiError("ERR_COMPONENT_NOT_FOUND", 404, msg)


def technician_not_found(msg="Technician id not found"):
    return ApiError("ERR_TECHNICIAN_NOT_FOUND", 404, msg)


def order_not_found(msg="ServiceOrder id not found"):
    return ApiError("ERR_SERVICE_ORDER_NOT_FOUND", 404, msg)


def result_record_not_found(msg="ResultRecord id not found"):
    return ApiError("ERR_RESULT_RECORD_NOT_FOUND", 404, msg)


def deficiency_not_found(msg="Deficiency id not found"):
    return ApiError("ERR_DEFICIENCY_NOT_FOUND", 404, msg)


def submission_not_found(msg="RegulatorySubmission id not found"):
    return ApiError("ERR_SUBMISSION_NOT_FOUND", 404, msg)


def record_not_found(msg="ReleaseDetectionRecord id not found"):
    return ApiError("ERR_RECORD_NOT_FOUND", 404, msg)


def operator_not_found(msg="OperatorPerson id not found"):
    return ApiError("ERR_OPERATOR_NOT_FOUND", 404, msg)


def training_record_not_found(msg="TrainingRecord id not found"):
    return ApiError("ERR_TRAINING_RECORD_NOT_FOUND", 404, msg)


def release_event_not_found(msg="ReleaseEvent id not found"):
    return ApiError("ERR_RELEASE_EVENT_NOT_FOUND", 404, msg)


def fund_claim_not_found(msg="StateFundClaim id not found"):
    return ApiError("ERR_FUND_CLAIM_NOT_FOUND", 404, msg)


# --- priority 5: state preconditions -----------------------------------------
def facility_not_active(msg="Operation requires facility status ACTIVE"):
    return ApiError("ERR_FACILITY_NOT_ACTIVE", 409, msg)


def no_tank_registered(msg="Facility activation requires at least one TankSystem"):
    return ApiError("ERR_NO_TANK_REGISTERED", 409, msg)


def tanks_not_closed(msg="Facility closure requires all tanks PERMANENTLY_CLOSED"):
    return ApiError("ERR_TANKS_NOT_CLOSED", 409, msg)


def tank_not_in_service(msg="Operation requires the tank to be IN_SERVICE (or not PERMANENTLY_CLOSED)"):
    return ApiError("ERR_TANK_NOT_IN_SERVICE", 409, msg)


def order_not_requested(msg="Schedule requires order status REQUESTED"):
    return ApiError("ERR_ORDER_NOT_REQUESTED", 409, msg)


def order_not_scheduled(msg="Start requires order status SCHEDULED"):
    return ApiError("ERR_ORDER_NOT_SCHEDULED", 409, msg)


def order_not_in_progress(msg="Results require order status IN_PROGRESS"):
    return ApiError("ERR_ORDER_NOT_IN_PROGRESS", 409, msg)


def order_not_under_review(msg="Certify/return-for-correction require order status UNDER_REVIEW"):
    return ApiError("ERR_ORDER_NOT_UNDER_REVIEW", 409, msg)


def order_not_cancellable(msg="Cancel requires order status REQUESTED or SCHEDULED"):
    return ApiError("ERR_ORDER_NOT_CANCELLABLE", 409, msg)


def order_not_editable(msg="PUT requires order status REQUESTED or SCHEDULED"):
    return ApiError("ERR_ORDER_NOT_EDITABLE", 409, msg)


def deficiency_not_open(msg="order-correction requires deficiency status OPEN or ESCALATED"):
    return ApiError("ERR_DEFICIENCY_NOT_OPEN", 409, msg)


def deficiency_not_ordered(msg="mark-corrected requires deficiency status CORRECTION_ORDERED"):
    return ApiError("ERR_DEFICIENCY_NOT_ORDERED", 409, msg)


def submission_not_draft(msg="submit requires submission status DRAFT"):
    return ApiError("ERR_SUBMISSION_NOT_DRAFT", 409, msg)


def submission_not_submitted(msg="accept/reject require submission status SUBMITTED"):
    return ApiError("ERR_SUBMISSION_NOT_SUBMITTED", 409, msg)


def submission_not_rejected(msg="amend requires submission status REJECTED"):
    return ApiError("ERR_SUBMISSION_NOT_REJECTED", 409, msg)


def release_not_suspected(msg="confirm/dismiss require release status SUSPECTED"):
    return ApiError("ERR_RELEASE_NOT_SUSPECTED", 409, msg)


def release_not_confirmed(msg="begin-cleanup requires release status CONFIRMED"):
    return ApiError("ERR_RELEASE_NOT_CONFIRMED", 409, msg)


def release_not_cleanup(msg="close requires release status CLEANUP_IN_PROGRESS"):
    return ApiError("ERR_RELEASE_NOT_CLEANUP", 409, msg)


def claim_not_draft(msg="submit requires claim status DRAFT"):
    return ApiError("ERR_CLAIM_NOT_DRAFT", 409, msg)


def claim_not_submitted(msg="adjudicate requires claim status SUBMITTED"):
    return ApiError("ERR_CLAIM_NOT_SUBMITTED", 409, msg)


def claim_not_withdrawable(msg="withdraw requires claim status DRAFT or SUBMITTED"):
    return ApiError("ERR_CLAIM_NOT_WITHDRAWABLE", 409, msg)


def operator_not_activatable(msg="Operation requires operator status DESIGNATED or LAPSED"):
    return ApiError("ERR_OPERATOR_NOT_ACTIVATABLE", 409, msg)


def critical_deficiency_open(msg="return-to-service blocked by an open CRITICAL deficiency on the tank"):
    return ApiError("ERR_CRITICAL_DEFICIENCY_OPEN", 409, msg)


def open_release_on_tank(msg="return-to-service blocked by an open release on the tank"):
    return ApiError("ERR_OPEN_RELEASE_ON_TANK", 409, msg)


# --- priority 7-9: business safety -------------------------------------------
def endorsement_missing(msg="Technician lacks the endorsement mapped from service_type or is inactive"):
    return ApiError("ERR_ENDORSEMENT_MISSING", 422, msg)


def instructor_not_trainer(msg="Issuing technician has trainer == false"):
    return ApiError("ERR_INSTRUCTOR_NOT_TRAINER", 422, msg)


def class_mismatch(msg="course_class differs from the operator's operator_class"):
    return ApiError("ERR_CLASS_MISMATCH", 422, msg)


def posture_blocks_claim(msg="Facility compliance_posture is NON_COMPLIANT"):
    return ApiError("ERR_FACILITY_POSTURE_BLOCKS_CLAIM", 422, msg)


# --- priority 10: uniqueness ---------------------------------------------------
def duplicate_tank_tag(msg="tank_tag already exists within the facility"):
    return ApiError("ERR_DUPLICATE_TANK_TAG", 409, msg)


def duplicate_record(msg="A ReleaseDetectionRecord already exists for (tank_system_id, period_month)"):
    return ApiError("ERR_DUPLICATE_RECORD", 409, msg)


# --- priority 11-16: business temporal ---------------------------------------
def invalid_window(msg="window_end must be strictly after window_start"):
    return ApiError("ERR_INVALID_WINDOW", 422, msg)


def technician_double_booked(msg="Technician has a SCHEDULED/IN_PROGRESS order whose window intersects"):
    return ApiError("ERR_TECHNICIAN_DOUBLE_BOOKED", 409, msg)


def tank_stabilization_window(msg="A TANK_TIGHTNESS order sits within the 8h stabilization buffer"):
    return ApiError("ERR_TANK_STABILIZATION_WINDOW", 409, msg)


def outside_service_window(msg="Order start outside [window_start, window_end]"):
    return ApiError("ERR_OUTSIDE_SERVICE_WINDOW", 422, msg)


def close_too_early(msg="Monthly close for period_month requires clock >= day 11 of the following month"):
    return ApiError("ERR_CLOSE_TOO_EARLY", 422, msg)


def future_period(msg="period_month is after the current clock's month"):
    return ApiError("ERR_FUTURE_PERIOD", 422, msg)


def training_missing(msg="No TrainingRecord exists for the operator's class"):
    return ApiError("ERR_TRAINING_MISSING", 422, msg)


def training_expired(msg="Latest class TrainingRecord has expires_at <= clock"):
    return ApiError("ERR_TRAINING_EXPIRED", 422, msg)


# --- type constraints ---------------------------------------------------------
def mode_not_allowed(msg="MANUAL_GAUGING release detection requires capacity_gallons <= 2000"):
    return ApiError("ERR_MODE_NOT_ALLOWED_FOR_CAPACITY", 422, msg)


# --- priority 17: cross-referential alignment --------------------------------
def tank_facility_mismatch(msg="tank_system_id does not belong to the referenced facility"):
    return ApiError("ERR_TANK_FACILITY_MISMATCH", 422, msg)


def component_mismatch(msg="component_id missing/present/wrong-typed/wrong-tank for the service_type"):
    return ApiError("ERR_COMPONENT_MISMATCH", 422, msg)


def deficiency_link_invalid(msg="linked_deficiency_id belongs to a different tank or has invalid status"):
    return ApiError("ERR_DEFICIENCY_LINK_INVALID", 422, msg)


def bundle_item_mismatch(msg="Submission bundle missing for its type or contains mismatched items"):
    return ApiError("ERR_BUNDLE_ITEM_MISMATCH", 422, msg)


def claim_release_mismatch(msg="release_event_id belongs to a different facility"):
    return ApiError("ERR_CLAIM_RELEASE_MISMATCH", 422, msg)


# --- priority 18: fiscal gates -------------------------------------------------
def claim_release_not_confirmed(msg="Fund claim requires release status CONFIRMED, CLEANUP_IN_PROGRESS, or CLOSED"):
    return ApiError("ERR_CLAIM_RELEASE_NOT_CONFIRMED", 402, msg)


def fees_not_current(msg="annual_fee_paid_through is before the current clock"):
    return ApiError("ERR_FEES_NOT_CURRENT", 402, msg)


def fund_cap_exceeded(msg="payable_amount_cents exceeds facility fund_cap_remaining_cents"):
    return ApiError("ERR_FUND_CAP_EXCEEDED", 402, msg)


# --- priority 19: optimistic concurrency --------------------------------------
def stale_version(msg="expected_*_version does not match the resource's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
