"""Error classes and error ID constants."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error IDs (from SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ENTITY_DISSOLVED = "ERR_ENTITY_DISSOLVED"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_BOI_INVALID = "ERR_BOI_INVALID"
ERR_OPERATING_AGREEMENT_INVALID = "ERR_OPERATING_AGREEMENT_INVALID"
ERR_FQ_AGENT_MISMATCH = "ERR_FQ_AGENT_MISMATCH"
ERR_AGENT_STATE_MISMATCH = "ERR_AGENT_STATE_MISMATCH"
ERR_REPORT_PERIOD_TAKEN = "ERR_REPORT_PERIOD_TAKEN"
ERR_FQ_OVERLAP = "ERR_FQ_OVERLAP"
ERR_BOI_PAST_DEADLINE = "ERR_BOI_PAST_DEADLINE"
ERR_FQ_SAME_STATE = "ERR_FQ_SAME_STATE"
ERR_TEMPLATE_TYPE_MISMATCH = "ERR_TEMPLATE_TYPE_MISMATCH"
ERR_FRANCHISE_TAX_CAP_EXCEEDED = "ERR_FRANCHISE_TAX_CAP_EXCEEDED"
ERR_FRANCHISE_TAX_IN_ARREARS = "ERR_FRANCHISE_TAX_IN_ARREARS"


def err_unauthenticated(msg=""):
    return APIError(ERR_UNAUTHENTICATED, 401, msg or "Missing or unrecognized auth headers.")


def err_unauthorized(msg=""):
    return APIError(ERR_UNAUTHORIZED, 403, msg or "Role not authorized for this endpoint.")


def err_not_found(msg=""):
    return APIError(ERR_NOT_FOUND, 404, msg or "Resource not found.")


def err_invalid_state(msg=""):
    return APIError(ERR_INVALID_STATE, 409, msg or "Invalid state for requested transition.")


def err_entity_dissolved(msg=""):
    return APIError(ERR_ENTITY_DISSOLVED, 409, msg or "Parent business entity is DISSOLVED.")


def err_invalid_request(msg=""):
    return APIError(ERR_INVALID_REQUEST, 400, msg or "Invalid request payload.")


def err_stale_version(msg=""):
    return APIError(ERR_STALE_VERSION, 412, msg or "Optimistic concurrency check failed.")


def err_boi_invalid(msg=""):
    return APIError(ERR_BOI_INVALID, 422, msg or "Invalid BOI disclosure payload.")


def err_operating_agreement_invalid(msg=""):
    return APIError(ERR_OPERATING_AGREEMENT_INVALID, 422, msg or "Invalid operating agreement members.")


def err_fq_agent_mismatch(msg=""):
    return APIError(ERR_FQ_AGENT_MISMATCH, 422, msg or "Foreign qualification agent mismatch.")


def err_agent_state_mismatch(msg=""):
    return APIError(ERR_AGENT_STATE_MISMATCH, 422, msg or "Agent state code does not match formation state.")


def err_report_period_taken(msg=""):
    return APIError(ERR_REPORT_PERIOD_TAKEN, 409, msg or "Annual report period already taken.")


def err_fq_overlap(msg=""):
    return APIError(ERR_FQ_OVERLAP, 409, msg or "Foreign qualification overlaps an existing qualified one.")


def err_boi_past_deadline(msg=""):
    return APIError(ERR_BOI_PAST_DEADLINE, 422, msg or "BOI submission is past deadline.")


def err_fq_same_state(msg=""):
    return APIError(ERR_FQ_SAME_STATE, 422, msg or "Foreign state must differ from formation state.")


def err_template_type_mismatch(msg=""):
    return APIError(ERR_TEMPLATE_TYPE_MISMATCH, 422, msg or "Operating agreement template does not match entity type.")


def err_franchise_tax_cap_exceeded(msg=""):
    return APIError(ERR_FRANCHISE_TAX_CAP_EXCEEDED, 422, msg or "Franchise tax cumulative cap exceeded.")


def err_franchise_tax_in_arrears(msg=""):
    return APIError(ERR_FRANCHISE_TAX_IN_ARREARS, 422, msg or "Prior annual report is not in FILED or VOIDED.")
