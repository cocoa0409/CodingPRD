"""Error type and the scaffold 1.6 / PRD 5 error catalog (64 ids).

Every failure raises ApiError carrying the exact error_id and HTTP status
from the catalog. The error body shape lives in respond.error.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Authoritative error_id -> HTTP status mapping (PRD section 5).
STATUS = {
    # auth / request
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_INVALID_REQUEST": 400,
    # not found
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_COMPATIBILITY_RULE_NOT_FOUND": 404,
    "ERR_TRAILER_NOT_FOUND": 404,
    "ERR_DRIVER_NOT_FOUND": 404,
    "ERR_WASH_BAY_NOT_FOUND": 404,
    "ERR_WASH_CERT_NOT_FOUND": 404,
    "ERR_RACK_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_METER_TICKET_NOT_FOUND": 404,
    "ERR_DELIVERY_TICKET_NOT_FOUND": 404,
    "ERR_RETAIN_SAMPLE_NOT_FOUND": 404,
    "ERR_SPILL_PLAN_NOT_FOUND": 404,
    "ERR_SPILL_INCIDENT_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    # concurrency
    "ERR_STALE_VERSION": 412,
    # state
    "ERR_CUSTOMER_NOT_ACTIVE": 409,
    "ERR_TRAILER_NOT_AVAILABLE": 409,
    "ERR_DRIVER_NOT_ACTIVE": 409,
    "ERR_SHIPMENT_INVALID_STATE": 409,
    "ERR_CERT_INVALID_STATE": 409,
    "ERR_DELIVERY_TICKET_NOT_OPEN": 409,
    "ERR_SAMPLE_NOT_RETAINED": 409,
    "ERR_SPILL_PLAN_INVALID_STATE": 409,
    "ERR_INCIDENT_INVALID_STATE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_WEIGHTS_ALREADY_VERIFIED": 409,
    "ERR_WEIGHTS_NOT_VERIFIED": 409,
    "ERR_PLACARDS_NOT_CONFIRMED": 409,
    "ERR_OPEN_INCIDENT": 409,
    "ERR_SHIPMENT_NOT_DELIVERED": 409,
    # business safety
    "ERR_PRODUCT_INCOMPATIBILITY_FORBIDDEN": 422,
    "ERR_COMPATIBILITY_RULE_MISSING": 422,
    "ERR_WASH_LEVEL_INSUFFICIENT": 422,
    "ERR_WASH_CERT_EXPIRED": 422,
    "ERR_DRIVER_ENDORSEMENT_MISSING": 422,
    "ERR_DRIVER_ENDORSEMENT_EXPIRED": 422,
    "ERR_PLACARD_MISMATCH": 422,
    "ERR_AXLE_LIMIT_EXCEEDED": 422,
    "ERR_GVWR_EXCEEDED": 422,
    "ERR_WEIGHT_SUM_INCONSISTENT": 422,
    "ERR_SPILL_PLAN_NOT_APPROVED": 422,
    # business temporal
    "ERR_WINDOW_OUTSIDE_OPERATING_HOURS": 422,
    "ERR_RACK_WINDOW_CONFLICT": 409,
    "ERR_WASH_BAY_WINDOW_CONFLICT": 409,
    "ERR_RACK_WINDOW_NOT_ACTIVE": 422,
    "ERR_REPORT_DEADLINE_MISSED": 422,
    "ERR_SAMPLE_STILL_IN_RETENTION": 422,
    "ERR_AGREEMENT_PERIOD_CONFLICT": 409,
    "ERR_MONTH_NOT_CLOSABLE": 422,
    # business constraint
    "ERR_DUPLICATE_UNIT_NUMBER": 409,
    "ERR_DUPLICATE_CDL_NUMBER": 409,
    "ERR_DUPLICATE_COMPATIBILITY_RULE": 409,
    "ERR_TARE_AXLE_MISMATCH": 422,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_TRAILER_DEDICATION_MISMATCH": 422,
    "ERR_TRAILER_ALREADY_DEDICATED": 409,
    "ERR_SAME_OPERATOR_SEGREGATION": 403,
    "ERR_NOT_PROGRAM_ENROLLED": 422,
    # referential / fiscal
    "ERR_RACK_NOT_AUTHORIZED_FOR_PRODUCT": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
}

# Collection name -> dedicated not-found error id (PRD 2.8 step 3).
NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "compat_rules": "ERR_COMPATIBILITY_RULE_NOT_FOUND",
    "trailers": "ERR_TRAILER_NOT_FOUND",
    "drivers": "ERR_DRIVER_NOT_FOUND",
    "wash_bays": "ERR_WASH_BAY_NOT_FOUND",
    "wash_certs": "ERR_WASH_CERT_NOT_FOUND",
    "racks": "ERR_RACK_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "meter_tickets": "ERR_METER_TICKET_NOT_FOUND",
    "delivery_tickets": "ERR_DELIVERY_TICKET_NOT_FOUND",
    "retain_samples": "ERR_RETAIN_SAMPLE_NOT_FOUND",
    "spill_plans": "ERR_SPILL_PLAN_NOT_FOUND",
    "spill_incidents": "ERR_SPILL_INCIDENT_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
}


def err(error_id, message):
    return ApiError(error_id, STATUS[error_id], message)


def invalid_request(message):
    return err("ERR_INVALID_REQUEST", message)


def not_found_for(collection, entity_id):
    return err(NOT_FOUND[collection], "No %s with id %s" % (collection[:-1], entity_id))
