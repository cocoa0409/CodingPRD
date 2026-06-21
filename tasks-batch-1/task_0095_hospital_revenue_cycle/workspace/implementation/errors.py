"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Exact (error_id, http_status) pairs from the catalogue.
def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="The acting role is not permitted to invoke this operation."):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def segregation_of_duties(msg="The approver may not be the coder who finalized this encounter's coding."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def not_found(msg="The requested resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def reference_not_found(msg="A referenced resource does not exist."):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 404, msg)


def invalid_request(msg="The request body is missing a required field, has a wrong type, or an out-of-set enum value."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg="The target resource is not in a state from which this transition is defined."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def no_policy_on_encounter(msg="The encounter has no insurance policy attached."):
    return ApiError("ERR_NO_POLICY_ON_ENCOUNTER", 409, msg)


def policy_not_active(msg="The referenced insurance policy is not ACTIVE."):
    return ApiError("ERR_POLICY_NOT_ACTIVE", 409, msg)


def payer_inactive(msg="The payer is not currently accepting claims."):
    return ApiError("ERR_PAYER_INACTIVE", 409, msg)


def timely_filing_exceeded(msg="The claim was submitted after the payer's timely filing window."):
    return ApiError("ERR_TIMELY_FILING_EXCEEDED", 409, msg)


def appeal_window_closed(msg="The appeal was filed after the payer's appeal window."):
    return ApiError("ERR_APPEAL_WINDOW_CLOSED", 409, msg)


def not_appealable(msg="This denial reason is not appealable."):
    return ApiError("ERR_NOT_APPEALABLE", 409, msg)


def not_correctable(msg="This denial reason is not correctable."):
    return ApiError("ERR_NOT_CORRECTABLE", 409, msg)


def aging_not_met(msg="The statement has not aged long enough to be sent to collections."):
    return ApiError("ERR_AGING_NOT_MET", 409, msg)


def charges_closed(msg="Charge capture is closed for this encounter."):
    return ApiError("ERR_CHARGES_CLOSED", 409, msg)


def no_charges(msg="The encounter has no POSTED charges to discharge."):
    return ApiError("ERR_NO_CHARGES", 409, msg)


def claim_lines_mismatch(msg="The claim lines do not sum to allowed_amount_cents."):
    return ApiError("ERR_CLAIM_LINES_MISMATCH", 422, msg)


def overpayment(msg="The payment exceeds the statement's outstanding balance."):
    return ApiError("ERR_OVERPAYMENT", 422, msg)


def coding_not_cleared(msg="The encounter's coding has not been cleared."):
    return ApiError("ERR_CODING_NOT_CLEARED", 409, msg)


def policy_in_use(msg="The policy is referenced by an open encounter."):
    return ApiError("ERR_POLICY_IN_USE", 409, msg)


def stale_encounter_version(msg="expected_encounter_version does not match the encounter's current version."):
    return ApiError("ERR_STALE_ENCOUNTER_VERSION", 412, msg)


def stale_statement_version(msg="expected_patient_statement_version does not match the statement's current version."):
    return ApiError("ERR_STALE_STATEMENT_VERSION", 412, msg)


def validation_out_of_range(msg="A numeric field is outside its allowed range."):
    return ApiError("ERR_VALIDATION_OUT_OF_RANGE", 422, msg)
