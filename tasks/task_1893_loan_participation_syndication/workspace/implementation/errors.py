"""Error types and the error-id catalog for the syndication API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- catalog (PRD section 5) -------------------------------------------------
def missing_context(msg="X-User-ID and X-User-Role headers are required"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def forbidden_role(msg="Role is not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", msg, 403)


def not_owner(msg="Caller does not own the target resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", msg, 403)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_request(msg="Request is malformed"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def invalid_state(msg="Resource state does not permit this transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg, 409)


def facility_not_committed(msg="Facility is not COMMITTED"):
    return ApiError("ERR_FACILITY_NOT_COMMITTED", msg, 409)


def facility_in_default(msg="Facility is in default or accelerated"):
    return ApiError("ERR_FACILITY_IN_DEFAULT", msg, 409)


def stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def default_already_active(msg="A DECLARED default case already exists on this facility"):
    return ApiError("ERR_DEFAULT_ALREADY_ACTIVE", msg, 409)


def commitment_exceeds_total(msg="Committed total would exceed the facility total"):
    return ApiError("ERR_COMMITMENT_EXCEEDS_TOTAL", msg, 409)


def draw_window_overlap(msg="Draw accrual window overlaps an existing draw"):
    return ApiError("ERR_DRAW_WINDOW_OVERLAP", msg, 409)


def draw_exceeds_commitment(msg="Cumulative draws exceed total commitment"):
    return ApiError("ERR_DRAW_EXCEEDS_COMMITMENT", msg, 409)


def draw_has_confirmed_funds(msg="Draw has confirmed funds and cannot be cancelled"):
    return ApiError("ERR_DRAW_HAS_CONFIRMED_FUNDS", msg, 409)


def funding_amount_mismatch(msg="Received amount does not equal due amount"):
    return ApiError("ERR_FUNDING_AMOUNT_MISMATCH", msg, 409)


def penalty_amount_mismatch(msg="Penalty received does not equal the computed penalty"):
    return ApiError("ERR_PENALTY_AMOUNT_MISMATCH", msg, 409)


def funding_not_yet_due(msg="Funding due date has not passed"):
    return ApiError("ERR_FUNDING_NOT_YET_DUE", msg, 409)


def payment_exceeds_outstanding(msg="Principal pool exceeds outstanding principal"):
    return ApiError("ERR_PAYMENT_EXCEEDS_OUTSTANDING", msg, 409)


def voting_closed(msg="Voting is closed for this solicitation"):
    return ApiError("ERR_VOTING_CLOSED", msg, 409)


def voting_still_open(msg="Voting window is still open"):
    return ApiError("ERR_VOTING_STILL_OPEN", msg, 409)


def duplicate_vote(msg="Participant already has a live vote here"):
    return ApiError("ERR_DUPLICATE_VOTE", msg, 409)


def participant_not_eligible(msg="Participant is not eligible for this action"):
    return ApiError("ERR_PARTICIPANT_NOT_ELIGIBLE", msg, 409)


def modification_not_passed(msg="Modification request is not PASSED"):
    return ApiError("ERR_MODIFICATION_NOT_PASSED", msg, 409)


def acceleration_threshold(msg="Acceleration threshold not met"):
    return ApiError("ERR_ACCELERATION_THRESHOLD_NOT_MET", msg, 409)


def waiver_threshold(msg="Waiver threshold not met"):
    return ApiError("ERR_WAIVER_THRESHOLD_NOT_MET", msg, 409)


def solicitation_overlap(msg="Solicitation window within 24h of another window"):
    return ApiError("ERR_SOLICITATION_WINDOW_OVERLAP", msg, 409)


def duplicate_statement(msg="Statement already registered for this facility/type/period"):
    return ApiError("ERR_DUPLICATE_STATEMENT", msg, 409)


def statement_not_received(msg="Attached statement has not been received"):
    return ApiError("ERR_STATEMENT_NOT_RECEIVED", msg, 409)


def package_window_overlap(msg="Reporting package period overlaps another package"):
    return ApiError("ERR_PACKAGE_WINDOW_OVERLAP", msg, 409)


def transfer_below_minimum(msg="Transfer amount below the facility minimum"):
    return ApiError("ERR_TRANSFER_BELOW_MINIMUM", msg, 409)


def transfer_exceeds_commitment(msg="Transfer amount exceeds remaining commitment"):
    return ApiError("ERR_TRANSFER_EXCEEDS_COMMITMENT", msg, 409)


def transfer_stub_below_minimum(msg="Partial transfer would leave a stub below minimum"):
    return ApiError("ERR_TRANSFER_STUB_BELOW_MINIMUM", msg, 409)


def transfer_target_ambiguous(msg="Exactly one transferee designator is required"):
    return ApiError("ERR_TRANSFER_TARGET_AMBIGUOUS", msg, 400)


def self_transfer(msg="Cannot transfer to oneself"):
    return ApiError("ERR_SELF_TRANSFER", msg, 409)


def settlement_in_blackout(msg="Settlement date falls inside a payment blackout window"):
    return ApiError("ERR_SETTLEMENT_IN_BLACKOUT", msg, 409)


def buyback_already_pending(msg="An open buyback demand already exists for this participant"):
    return ApiError("ERR_BUYBACK_ALREADY_PENDING", msg, 409)


def buyback_not_funded(msg="Demanding participant is not FUNDED"):
    return ApiError("ERR_BUYBACK_NOT_FUNDED", msg, 409)


def writedown_exceeds(msg="Write-down exceeds outstanding principal"):
    return ApiError("ERR_WRITEDOWN_EXCEEDS_OUTSTANDING", msg, 409)
