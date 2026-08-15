"""Error catalogue (PRD section 5) and the exception used to raise errors."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_MECHANIC_OVERBOOKED": 409,
    "ERR_TRACEABILITY_MISSING": 422,
    "ERR_AIRWORTHINESS_BLOCKED": 422,
    "ERR_OWNER_DECISION_REQUIRED": 422,
    "ERR_INVOICE_LOCKED": 409,
    "ERR_VALIDATION": 400,
    "ERR_CHECKLIST_INCOMPLETE": 422,
    "ERR_DUPLICATE_INVOICE": 409,
    "ERR_CERTIFICATE_INSUFFICIENT": 422,
    # Fallback for unexpected server faults; never asserted by the catalogue.
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid X-User-Role / X-User-ID headers.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted for this endpoint.",
    "ERR_NOT_FOUND": "Referenced resource id does not exist.",
    "ERR_INVALID_STATE": "Entity is not in a state permitting the requested transition.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_SLOT_OVERLAP": "Hangar slot interval intersects an existing RESERVED/OCCUPIED slot for the same hangar_code.",
    "ERR_INVALID_WINDOW": "ends_at must be strictly after starts_at and the slot may not exceed 30 days.",
    "ERR_MECHANIC_OVERBOOKED": "Labor entry would push the mechanic's same-day cumulative billable time past 10 hours.",
    "ERR_TRACEABILITY_MISSING": "OVERHAUL/SERVICEABLE part lacks a non-empty trace_doc_ref.",
    "ERR_AIRWORTHINESS_BLOCKED": "Regulatory gate failed: open AD, unrectified AIRWORTHINESS discrepancy, segregation-of-duties violation, or missing IA signoff.",
    "ERR_OWNER_DECISION_REQUIRED": "Discrepancy at-or-above the owner cap requires the registered owner's decision.",
    "ERR_INVOICE_LOCKED": "Mutation attempted on a work order whose invoice is ISSUED or PAID.",
    "ERR_VALIDATION": "Malformed input: missing required field, invalid enum, or out-of-range value.",
    "ERR_CHECKLIST_INCOMPLETE": "complete-inspection requires zero PENDING items and, for ANNUAL scope, at least one non-NA item.",
    "ERR_DUPLICATE_INVOICE": "A second active (non-VOIDED) invoice for the same work order is not permitted.",
    "ERR_CERTIFICATE_INSUFFICIENT": "Mechanic certificate_class insufficient for operation (IA required).",
    "ERR_INTERNAL": "Unexpected server error.",
}
