"""Error catalogue (PRD section 5 / scaffold 1.6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        entry = ERRORS.get(error_id, {})
        self.message = message or entry.get("message", error_id)
        self.http_status = http_status or entry.get("http_status", 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


ERRORS = {
    "ERR_UNAUTHENTICATED": {
        "http_status": 401,
        "message": "Authentication headers are missing or malformed",
    },
    "ERR_FORBIDDEN_ROLE": {
        "http_status": 403,
        "message": "Role is not permitted to perform this operation",
    },
    "ERR_BASE_NOT_OWNED": {
        "http_status": 403,
        "message": "Chief pilot may only act on pilots of their own base",
    },
    "ERR_SEGREGATION_OF_DUTIES": {
        "http_status": 403,
        "message": "The acting party may not adjudicate its own submission or its own offer",
    },
    "ERR_AGREEMENT_NOT_FOUND": {"http_status": 404, "message": "Agreement not found"},
    "ERR_CREW_BASE_NOT_FOUND": {"http_status": 404, "message": "Crew base not found"},
    "ERR_AIRCRAFT_NOT_FOUND": {"http_status": 404, "message": "Aircraft not found"},
    "ERR_PILOT_NOT_FOUND": {"http_status": 404, "message": "Pilot not found"},
    "ERR_SCHEDULE_CYCLE_NOT_FOUND": {
        "http_status": 404,
        "message": "Schedule cycle not found",
    },
    "ERR_FLIGHT_LEG_NOT_FOUND": {"http_status": 404, "message": "Flight leg not found"},
    "ERR_CANCELLATION_CLAIM_NOT_FOUND": {
        "http_status": 404,
        "message": "Cancellation claim not found",
    },
    "ERR_PASSTHROUGH_CLAIM_NOT_FOUND": {
        "http_status": 404,
        "message": "Pass-through claim not found",
    },
    "ERR_SCORECARD_NOT_FOUND": {"http_status": 404, "message": "Scorecard not found"},
    "ERR_INVOICE_NOT_FOUND": {"http_status": 404, "message": "Invoice not found"},
    "ERR_BRAND_AUDIT_NOT_FOUND": {"http_status": 404, "message": "Brand audit not found"},
    "ERR_NEGOTIATION_NOT_FOUND": {
        "http_status": 404,
        "message": "Extension negotiation not found",
    },
    "ERR_REFERENCE_NOT_FOUND": {
        "http_status": 404,
        "message": "A referenced resource in the request body does not exist",
    },
    "ERR_INVALID_REQUEST": {
        "http_status": 400,
        "message": "Request body or query is structurally invalid",
    },
    "ERR_AGREEMENT_NOT_ACTIVE": {
        "http_status": 409,
        "message": "Governing agreement is not ACTIVE",
    },
    "ERR_STALE_AGREEMENT_VERSION": {
        "http_status": 412,
        "message": "expected_agreement_version does not match the current agreement version",
    },
    "ERR_STALE_CYCLE_VERSION": {
        "http_status": 412,
        "message": "expected_schedule_cycle_version does not match the current schedule cycle version",
    },
    "ERR_INVALID_STATE": {
        "http_status": 409,
        "message": "Resource is not in a state that allows this transition",
    },
    "ERR_ALREADY_TERMINAL": {
        "http_status": 409,
        "message": "Resource is already in a terminal state",
    },
    "ERR_AIRCRAFT_NOT_AVAILABLE": {
        "http_status": 409,
        "message": "Aircraft is not in revenue service",
    },
    "ERR_PILOT_NOT_QUALIFIED": {
        "http_status": 409,
        "message": "Captain is not line qualified",
    },
    "ERR_BASE_UNDERSTAFFED": {
        "http_status": 409,
        "message": "Base does not have enough line-qualified pilots to support another tail",
    },
    "ERR_CROSS_AGREEMENT_REFERENCE": {
        "http_status": 409,
        "message": "Aircraft or captain belongs to a different agreement than the schedule cycle",
    },
    "ERR_DUPLICATE_PASSTHROUGH_CATEGORY": {
        "http_status": 409,
        "message": "A live pass-through claim already exists for this category in this cycle",
    },
    "ERR_DUPLICATE_RESOURCE": {
        "http_status": 409,
        "message": "A resource with this natural key already exists in this scope",
    },
    "ERR_INVALID_INTERVAL": {
        "http_status": 422,
        "message": "Arrival instant must be strictly after the departure instant",
    },
    "ERR_AIRCRAFT_TURN_CONFLICT": {
        "http_status": 409,
        "message": "Leg violates the minimum turn buffer for this aircraft",
    },
    "ERR_PILOT_DUTY_CAP_EXCEEDED": {
        "http_status": 409,
        "message": "Captain would exceed the rolling 24-hour block-hour cap",
    },
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": {
        "http_status": 409,
        "message": "Cancellation classification dispute rounds are exhausted",
    },
    "ERR_COUNTER_ROUNDS_EXHAUSTED": {
        "http_status": 409,
        "message": "Extension negotiation counter rounds are exhausted",
    },
    "ERR_CYCLE_HAS_OPEN_LEGS": {
        "http_status": 409,
        "message": "Cycle still has legs that are neither completed nor cancelled",
    },
    "ERR_AIRCRAFT_HAS_OPEN_LEGS": {
        "http_status": 409,
        "message": "Aircraft still has scheduled legs",
    },
    "ERR_EVIDENCE_REQUIRED": {
        "http_status": 422,
        "message": "evidence_ref is required to mark remediation VERIFIED",
    },
    "ERR_REMEDIATION_NOT_VERIFIED": {
        "http_status": 409,
        "message": "Finding cannot be closed until remediation is VERIFIED",
    },
    "ERR_CLAIM_ALREADY_FINALIZED": {
        "http_status": 409,
        "message": "Cancellation classification is already final for this leg",
    },
    "ERR_FLEET_ALLOCATION_EXCEEDED": {
        "http_status": 409,
        "message": "Base fleet allocation cap would be exceeded",
    },
    "ERR_INVOICE_VARIANT_NOT_FINAL": {
        "http_status": 422,
        "message": "Only a FINAL invoice can be issued for settlement",
    },
    "ERR_PASSTHROUGH_UNRECONCILED": {
        "http_status": 409,
        "message": "Cycle has pass-through claims that are not yet reconciled or rejected",
    },
    "ERR_SCORECARD_STALE": {
        "http_status": 409,
        "message": "Cycle scorecard is stale and must be recomputed before settlement",
    },
    "ERR_DEPARTURE_LEDGER_OVERFLOW": {
        "http_status": 422,
        "message": "Cancellation would push recorded departures past the published departure count",
    },
    "ERR_EXTENSION_TERM_NOT_LATER": {
        "http_status": 422,
        "message": "Proposed term end date must be later than the current term end date",
    },
}
