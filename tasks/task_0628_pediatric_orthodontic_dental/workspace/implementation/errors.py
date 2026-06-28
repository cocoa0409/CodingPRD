"""Error classes and error-id constants (PRD §5 / scaffold §1.6).

Each ApiError carries the exact error_id, HTTP status, and a human-readable
message, surfaced through the standard error envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (PRD §5).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_STALE_PLAN_VERSION = "ERR_STALE_PLAN_VERSION"      # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_CROSS_ENTITY_STATE = "ERR_CROSS_ENTITY_STATE"      # 409
ERR_NO_PHASES = "ERR_NO_PHASES"                        # 409
ERR_RECORDS_INCOMPLETE = "ERR_RECORDS_INCOMPLETE"      # 409
ERR_NO_ORTHO_RIDER = "ERR_NO_ORTHO_RIDER"              # 409
ERR_POLICY_TERMINATED = "ERR_POLICY_TERMINATED"        # 409
ERR_POLICY_HAS_OPEN_CLAIMS = "ERR_POLICY_HAS_OPEN_CLAIMS"  # 409
ERR_CHAIR_CONFLICT = "ERR_CHAIR_CONFLICT"              # 409
ERR_PROVIDER_CONFLICT = "ERR_PROVIDER_CONFLICT"        # 409
ERR_NOT_YET_DUE = "ERR_NOT_YET_DUE"                    # 409
ERR_TOO_EARLY_CHECKIN = "ERR_TOO_EARLY_CHECKIN"        # 409
ERR_TOO_EARLY_NOSHOW = "ERR_TOO_EARLY_NOSHOW"          # 409
ERR_DOWN_PAYMENT_EXCEEDS = "ERR_DOWN_PAYMENT_EXCEEDS"  # 409
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                    # 409
ERR_CONTRACT_CLOSED = "ERR_CONTRACT_CLOSED"            # 409
ERR_VALIDATION = "ERR_VALIDATION"                      # 422


def unauthenticated(msg="Missing or unrecognized authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid or malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def stale_plan_version(msg="expected_plan_version does not match current plan version"):
    return ApiError(ERR_STALE_PLAN_VERSION, 412, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def cross_entity_state(msg="A referenced entity is not in the required state"):
    return ApiError(ERR_CROSS_ENTITY_STATE, 409, msg)


def no_phases(msg="Plan has no treatment phases"):
    return ApiError(ERR_NO_PHASES, 409, msg)


def records_incomplete(msg="Patient growth records are incomplete"):
    return ApiError(ERR_RECORDS_INCOMPLETE, 409, msg)


def no_ortho_rider(msg="Policy carries no orthodontic rider"):
    return ApiError(ERR_NO_ORTHO_RIDER, 409, msg)


def policy_terminated(msg="Policy is terminated"):
    return ApiError(ERR_POLICY_TERMINATED, 409, msg)


def policy_has_open_claims(msg="Policy has an approved (open) claim"):
    return ApiError(ERR_POLICY_HAS_OPEN_CLAIMS, 409, msg)


def chair_conflict(msg="Chair interval conflicts with an existing appointment"):
    return ApiError(ERR_CHAIR_CONFLICT, 409, msg)


def provider_conflict(msg="Provider interval conflicts with an existing appointment"):
    return ApiError(ERR_PROVIDER_CONFLICT, 409, msg)


def not_yet_due(msg="Installment is not yet due"):
    return ApiError(ERR_NOT_YET_DUE, 409, msg)


def too_early_checkin(msg="Check-in attempted more than 60 minutes before start"):
    return ApiError(ERR_TOO_EARLY_CHECKIN, 409, msg)


def too_early_noshow(msg="No-show marked before the appointment start"):
    return ApiError(ERR_TOO_EARLY_NOSHOW, 409, msg)


def down_payment_exceeds(msg="Down payment exceeds estimated patient responsibility"):
    return ApiError(ERR_DOWN_PAYMENT_EXCEEDS, 409, msg)


def overpayment(msg="Payment exceeds the contract balance remaining"):
    return ApiError(ERR_OVERPAYMENT, 409, msg)


def contract_closed(msg="Contract is closed"):
    return ApiError(ERR_CONTRACT_CLOSED, 409, msg)


def validation(msg="Semantically invalid value"):
    return ApiError(ERR_VALIDATION, 422, msg)
