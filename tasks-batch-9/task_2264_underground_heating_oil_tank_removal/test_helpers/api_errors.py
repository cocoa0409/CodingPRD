"""The error catalogue: every identifier the PRD declares and its HTTP status.

Registering the mapping with the framework at import time lets ``validate_error``
cross-check the status code of any error it is handed, even when a test does not
name the status explicitly.
"""
from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # --- authentication, authorisation and segregation of duties ---------- #
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_ROLE_NOT_PERMITTED = "ERR_ROLE_NOT_PERMITTED"
    ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

    # --- existence -------------------------------------------------------- #
    ERR_PROPERTY_NOT_FOUND = "ERR_PROPERTY_NOT_FOUND"
    ERR_TANK_PROJECT_NOT_FOUND = "ERR_TANK_PROJECT_NOT_FOUND"
    ERR_DISCLOSURE_NOT_FOUND = "ERR_DISCLOSURE_NOT_FOUND"
    ERR_PERMIT_NOT_FOUND = "ERR_PERMIT_NOT_FOUND"
    ERR_CREW_NOT_FOUND = "ERR_CREW_NOT_FOUND"
    ERR_WORK_ORDER_NOT_FOUND = "ERR_WORK_ORDER_NOT_FOUND"
    ERR_LABORATORY_NOT_FOUND = "ERR_LABORATORY_NOT_FOUND"
    ERR_SOIL_SAMPLE_NOT_FOUND = "ERR_SOIL_SAMPLE_NOT_FOUND"
    ERR_CHANGE_ORDER_NOT_FOUND = "ERR_CHANGE_ORDER_NOT_FOUND"
    ERR_CLAIM_NOT_FOUND = "ERR_CLAIM_NOT_FOUND"
    ERR_NFA_LETTER_NOT_FOUND = "ERR_NFA_LETTER_NOT_FOUND"
    ERR_INSURANCE_NOTIFICATION_NOT_FOUND = "ERR_INSURANCE_NOTIFICATION_NOT_FOUND"

    # --- request shape and paging ----------------------------------------- #
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"
    ERR_METHOD_OVERRIDE_REASON_REQUIRED = "ERR_METHOD_OVERRIDE_REASON_REQUIRED"
    ERR_CLOSING_DATE_IN_PAST = "ERR_CLOSING_DATE_IN_PAST"

    # --- project version freshness ---------------------------------------- #
    ERR_STALE_PROJECT_VERSION = "ERR_STALE_PROJECT_VERSION"

    # --- state legality --------------------------------------------------- #
    ERR_PROJECT_STATE_INVALID = "ERR_PROJECT_STATE_INVALID"
    ERR_DISCLOSURE_STATE_INVALID = "ERR_DISCLOSURE_STATE_INVALID"
    ERR_PERMIT_STATE_INVALID = "ERR_PERMIT_STATE_INVALID"
    ERR_WORK_ORDER_STATE_INVALID = "ERR_WORK_ORDER_STATE_INVALID"
    ERR_SAMPLE_STATE_INVALID = "ERR_SAMPLE_STATE_INVALID"
    ERR_CHANGE_ORDER_STATE_INVALID = "ERR_CHANGE_ORDER_STATE_INVALID"
    ERR_CLAIM_STATE_INVALID = "ERR_CLAIM_STATE_INVALID"
    ERR_NFA_STATE_INVALID = "ERR_NFA_STATE_INVALID"

    # --- the regulatory safety family ------------------------------------- #
    ERR_NO_TANK_LOCATED = "ERR_NO_TANK_LOCATED"
    ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE = "ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE"
    ERR_PERMIT_NOT_ISSUED = "ERR_PERMIT_NOT_ISSUED"
    ERR_PERMIT_EXPIRED = "ERR_PERMIT_EXPIRED"
    ERR_DISCLOSURE_EXPIRED = "ERR_DISCLOSURE_EXPIRED"
    ERR_DISCLOSURE_NOT_ACKNOWLEDGED = "ERR_DISCLOSURE_NOT_ACKNOWLEDGED"
    ERR_LAB_NOT_ACCREDITED = "ERR_LAB_NOT_ACCREDITED"
    ERR_NFA_BLOCKED = "ERR_NFA_BLOCKED"

    # --- optional links and reason fields --------------------------------- #
    ERR_SUPERSEDE_TARGET_INVALID = "ERR_SUPERSEDE_TARGET_INVALID"
    ERR_RETEST_TARGET_INVALID = "ERR_RETEST_TARGET_INVALID"

    # --- temporal constraints --------------------------------------------- #
    ERR_CREW_BOOKING_CONFLICT = "ERR_CREW_BOOKING_CONFLICT"
    ERR_LAB_CAPACITY_EXCEEDED = "ERR_LAB_CAPACITY_EXCEEDED"
    ERR_HOLDING_TIME_EXCEEDED = "ERR_HOLDING_TIME_EXCEEDED"

    # --- fiscal ceilings --------------------------------------------------- #
    ERR_EXCAVATION_LIMIT_EXCEEDED = "ERR_EXCAVATION_LIMIT_EXCEEDED"
    ERR_CLAIM_NOT_ELIGIBLE = "ERR_CLAIM_NOT_ELIGIBLE"

    # --- uniqueness and quota constraints --------------------------------- #
    ERR_DUPLICATE_FINAL_CLAIM = "ERR_DUPLICATE_FINAL_CLAIM"
    ERR_DUPLICATE_DISCLOSURE = "ERR_DUPLICATE_DISCLOSURE"
    ERR_WORK_ORDER_ALREADY_OPEN = "ERR_WORK_ORDER_ALREADY_OPEN"
    ERR_INFO_REQUEST_LIMIT_REACHED = "ERR_INFO_REQUEST_LIMIT_REACHED"


#: Every error identifier the PRD catalogues, with the status it must carry.
HTTP_STATUS_CODES = {
    ApiErrorId.ERR_UNAUTHENTICATED.value: 401,
    ApiErrorId.ERR_ROLE_NOT_PERMITTED.value: 403,
    ApiErrorId.ERR_NOT_RESOURCE_OWNER.value: 403,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value: 403,
    ApiErrorId.ERR_PROPERTY_NOT_FOUND.value: 404,
    ApiErrorId.ERR_TANK_PROJECT_NOT_FOUND.value: 404,
    ApiErrorId.ERR_DISCLOSURE_NOT_FOUND.value: 404,
    ApiErrorId.ERR_PERMIT_NOT_FOUND.value: 404,
    ApiErrorId.ERR_CREW_NOT_FOUND.value: 404,
    ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value: 404,
    ApiErrorId.ERR_LABORATORY_NOT_FOUND.value: 404,
    ApiErrorId.ERR_SOIL_SAMPLE_NOT_FOUND.value: 404,
    ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND.value: 404,
    ApiErrorId.ERR_CLAIM_NOT_FOUND.value: 404,
    ApiErrorId.ERR_NFA_LETTER_NOT_FOUND.value: 404,
    ApiErrorId.ERR_INSURANCE_NOTIFICATION_NOT_FOUND.value: 404,
    ApiErrorId.ERR_INVALID_REQUEST.value: 422,
    ApiErrorId.ERR_INVALID_PAGINATION.value: 422,
    ApiErrorId.ERR_METHOD_OVERRIDE_REASON_REQUIRED.value: 422,
    ApiErrorId.ERR_CLOSING_DATE_IN_PAST.value: 422,
    ApiErrorId.ERR_STALE_PROJECT_VERSION.value: 412,
    ApiErrorId.ERR_PROJECT_STATE_INVALID.value: 409,
    ApiErrorId.ERR_DISCLOSURE_STATE_INVALID.value: 409,
    ApiErrorId.ERR_PERMIT_STATE_INVALID.value: 409,
    ApiErrorId.ERR_WORK_ORDER_STATE_INVALID.value: 409,
    ApiErrorId.ERR_SAMPLE_STATE_INVALID.value: 409,
    ApiErrorId.ERR_CHANGE_ORDER_STATE_INVALID.value: 409,
    ApiErrorId.ERR_CLAIM_STATE_INVALID.value: 409,
    ApiErrorId.ERR_NFA_STATE_INVALID.value: 409,
    ApiErrorId.ERR_NO_TANK_LOCATED.value: 409,
    ApiErrorId.ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE.value: 409,
    ApiErrorId.ERR_PERMIT_NOT_ISSUED.value: 409,
    ApiErrorId.ERR_PERMIT_EXPIRED.value: 409,
    ApiErrorId.ERR_DISCLOSURE_EXPIRED.value: 409,
    ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED.value: 409,
    ApiErrorId.ERR_LAB_NOT_ACCREDITED.value: 409,
    ApiErrorId.ERR_NFA_BLOCKED.value: 409,
    ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value: 409,
    ApiErrorId.ERR_RETEST_TARGET_INVALID.value: 409,
    ApiErrorId.ERR_CREW_BOOKING_CONFLICT.value: 409,
    ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED.value: 409,
    ApiErrorId.ERR_HOLDING_TIME_EXCEEDED.value: 409,
    ApiErrorId.ERR_EXCAVATION_LIMIT_EXCEEDED.value: 409,
    ApiErrorId.ERR_CLAIM_NOT_ELIGIBLE.value: 409,
    ApiErrorId.ERR_DUPLICATE_FINAL_CLAIM.value: 409,
    ApiErrorId.ERR_DUPLICATE_DISCLOSURE.value: 409,
    ApiErrorId.ERR_WORK_ORDER_ALREADY_OPEN.value: 409,
    ApiErrorId.ERR_INFO_REQUEST_LIMIT_REACHED.value: 409,
}

# Hand the mapping to the framework so every validate_error call cross-checks
# the status code even when the caller does not spell it out.
set_error_http_status_map(HTTP_STATUS_CODES)
