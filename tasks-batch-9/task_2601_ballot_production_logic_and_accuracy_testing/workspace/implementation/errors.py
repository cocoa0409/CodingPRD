"""Error catalog and the exception type every guard raises."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or unrecognized X-Role header."),
    "ERR_UNAUTHORIZED": (403, "Role may not perform this operation."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "This action must be performed by a different user."),
    "ERR_INVALID_REQUEST": (400, "Request payload failed schema validation."),
    "ERR_ELECTION_NOT_FOUND": (404, "Election does not exist."),
    "ERR_CONTEST_NOT_FOUND": (404, "Contest does not exist."),
    "ERR_CANDIDATE_NOT_FOUND": (404, "Candidate does not exist."),
    "ERR_PRECINCT_NOT_FOUND": (404, "Precinct does not exist."),
    "ERR_BALLOT_STYLE_NOT_FOUND": (404, "Ballot style does not exist."),
    "ERR_PRINT_VENDOR_NOT_FOUND": (404, "Print vendor does not exist."),
    "ERR_PRINT_JOB_NOT_FOUND": (404, "Print job does not exist."),
    "ERR_BALLOT_LOT_NOT_FOUND": (404, "Ballot lot does not exist."),
    "ERR_TABULATOR_NOT_FOUND": (404, "Tabulator unit does not exist."),
    "ERR_TEST_DECK_NOT_FOUND": (404, "Test deck does not exist."),
    "ERR_LA_SESSION_NOT_FOUND": (404, "Logic and accuracy session does not exist."),
    "ERR_STALE_ELECTION_VERSION": (412, "Election version no longer current."),
    "ERR_STALE_BALLOT_STYLE_VERSION": (412, "Ballot style version no longer current."),
    "ERR_ELECTION_PHASE_INVALID": (409, "Election phase does not permit this operation."),
    "ERR_CONTEST_STATE_INVALID": (409, "Contest state does not permit this operation."),
    "ERR_CANDIDATE_STATE_INVALID": (409, "Candidate state does not permit this operation."),
    "ERR_STYLE_STATE_INVALID": (409, "Ballot style state does not permit this operation."),
    "ERR_JOB_STATE_INVALID": (409, "Print job state does not permit this operation."),
    "ERR_LOT_STATE_INVALID": (409, "Ballot lot state does not permit this operation."),
    "ERR_UNIT_STATE_INVALID": (409, "Tabulator state does not permit this operation."),
    "ERR_DECK_STATE_INVALID": (409, "Test deck state does not permit this operation."),
    "ERR_SESSION_STATE_INVALID": (409, "Session state does not permit this operation."),
    "ERR_VENDOR_NOT_SECURE": (409, "Vendor is not a certified secure facility."),
    "ERR_PROOF_VERSION_STALE": (409, "Proof was taken against a stale style version."),
    "ERR_LOT_NOT_FOR_PRECINCT": (409, "Lot was not printed for the precinct's assigned style."),
    "ERR_UNIT_STYLE_MISMATCH": (409, "Unit is not programmed for the precinct's assigned style."),
    "ERR_SEAL_MISMATCH": (409, "Seal does not match the shipped seal."),
    "ERR_SEAL_NUMBER_DUPLICATE": (409, "Seal number is already in use in this election."),
    "ERR_PRESS_CAPACITY_EXCEEDED": (409, "Vendor has no press line free for the requested window."),
    "ERR_UNIT_TEST_WINDOW_CONFLICT": (409, "Tabulator already has a test session in the requested window."),
    "ERR_PUBLIC_NOTICE_TOO_LATE": (409, "Public notice lead is below the required minimum."),
    "ERR_OUTSIDE_TEST_WINDOW": (409, "Current time is outside the session's admission window."),
    "ERR_INSUFFICIENT_OBSERVERS": (409, "Too few observers signed in."),
    "ERR_LANGUAGE_COVERAGE_INCOMPLETE": (409, "Style is missing translations or alternative formats."),
    "ERR_EMPTY_TEST_DECK": (409, "A test deck must contain at least one ballot."),
    "ERR_DECK_MARK_OFF_STYLE": (409, "Expected mark references a contest or candidate that is not printed on this style."),
    "ERR_DECK_MARKS_EXCEED_CAPACITY": (409, "Expected marks exceed the mark capacity of the deck's ballots."),
    "ERR_NO_CERTIFIED_CONTESTS": (409, "Election has no certified contests to order."),
    "ERR_BALLOT_ORDER_COLLISION": (409, "Contests cannot be ordered deterministically."),
    "ERR_DEPLOYMENT_NOT_READY": (409, "Election is not deployment-ready."),
    "ERR_LOTS_NOT_RETURNED": (409, "Lots are still issued; a final canvass requires every lot returned."),
    "ERR_RETENTION_BEFORE_RECONCILIATION": (409, "Retention seals may only be applied after reconciliation."),
    "ERR_QUANTITY_BELOW_REQUIREMENT": (409, "Ordered quantity is below the requirement of the style's precincts."),
    "ERR_ISSUE_QUANTITY_EXCEEDS_RECEIPT": (409, "Cannot issue more ballots than the lot received."),
    "ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT": (409, "Accounted ballots exceed the ballots received."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Request failed."))
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
