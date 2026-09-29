"""Error catalogue for the Public Procurement Protest & Debarment API (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_CATALOG.get(error_id, (500, ""))[0]
        self.message = message or ERROR_CATALOG.get(error_id, (500, ""))[1]
        super().__init__(self.message)


# error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "authentication headers missing or unrecognised"),
    "ERR_FORBIDDEN_ROLE": (403, "role not permitted for this operation"),
    "ERR_INVALID_REQUEST": (400, "request body failed shape validation"),
    "ERR_DUPLICATE_FACTOR_CODE": (422, "factor or evidence code list contains a repeated member"),
    "ERR_VENDOR_NOT_FOUND": (404, "vendor not found"),
    "ERR_SOLICITATION_NOT_FOUND": (404, "solicitation not found"),
    "ERR_BID_NOT_FOUND": (404, "bid not found"),
    "ERR_QUESTION_NOT_FOUND": (404, "question submission not found"),
    "ERR_PROTEST_NOT_FOUND": (404, "protest not found"),
    "ERR_HEARING_NOT_FOUND": (404, "protest hearing not found"),
    "ERR_AWARD_NOT_FOUND": (404, "award not found"),
    "ERR_PROCEEDING_NOT_FOUND": (404, "debarment proceeding not found"),
    "ERR_PETITION_NOT_FOUND": (404, "reinstatement petition not found"),
    "ERR_SCREENING_NOT_FOUND": (404, "subcontractor screening not found"),
    "ERR_DUPLICATE_TAX_ID": (409, "a vendor with this tax id already exists"),
    "ERR_DUPLICATE_SOLICITATION_NUMBER": (409, "solicitation number already in use"),
    "ERR_DUPLICATE_REQUIREMENT_CODE": (409, "requirement code already present on this solicitation"),
    "ERR_VENDOR_IDENTITY_MISMATCH": (403, "acting vendor does not own this resource"),
    "ERR_STALE_SOLICITATION_VERSION": (412, "solicitation version is stale; re-read and retry"),
    "ERR_STALE_PROCEEDING_VERSION": (412, "proceeding version is stale; re-read and retry"),
    "ERR_INVALID_SOLICITATION_STATE": (409, "solicitation state does not permit this operation"),
    "ERR_SOLICITATION_NOT_PROTESTABLE": (409, "this solicitation cannot be protested in its current state"),
    "ERR_INVALID_BID_STATE": (409, "bid state does not permit this operation"),
    "ERR_INVALID_PROTEST_STATE": (409, "protest state does not permit this operation"),
    "ERR_INVALID_HEARING_STATE": (409, "hearing state does not permit this operation"),
    "ERR_INVALID_PROCEEDING_STATE": (409, "proceeding state does not permit this operation"),
    "ERR_INVALID_PETITION_STATE": (409, "petition has already been decided"),
    "ERR_QUESTION_PERIOD_CLOSED": (409, "the question period for this solicitation is closed"),
    "ERR_QUESTION_PERIOD_OPEN": (409, "the question period has not expired yet"),
    "ERR_BID_PERIOD_OPEN": (409, "the bid due date has not passed yet"),
    "ERR_BID_DEADLINE_PASSED": (409, "the bid due date has passed"),
    "ERR_VENDOR_NOT_ELIGIBLE": (409, "vendor is suspended or debarred"),
    "ERR_ALREADY_RESOLICITED": (409, "this solicitation already has a successor"),
    "ERR_HEARING_NOT_YET_STARTED": (409, "the hearing cannot be convened before its scheduled start"),
    "ERR_HEARING_OFFICER_CONFLICT": (403, "the hearing officer may not be the official who issued the solicitation"),
    "ERR_REVIEWER_CONFLICT": (403, "the responsibility reviewer may not be the official who determined responsiveness"),
    "ERR_PROTESTER_LACKS_STANDING": (403, "protester is neither an actual nor a qualifying prospective bidder"),
    "ERR_AGENCY_RECORD_INCOMPLETE": (409, "the agency record does not yet contain enough items for this step"),
    "ERR_HEARING_NOT_CONCLUDED": (409, "no concluded hearing exists on this protest"),
    "ERR_DEBARMENT_HEARING_RIGHTS_NOT_EXHAUSTED": (409, "the respondent's response window has not expired"),
    "ERR_MATERIAL_REQUIREMENT_UNMET": (422, "a material addendum requirement is unacknowledged"),
    "ERR_INTERIM_SUSPENSION_THRESHOLD_NOT_MET": (422, "severity score too low for interim suspension"),
    "ERR_SEVERITY_BELOW_DEBARMENT_FLOOR": (422, "severity score maps to a zero-month period; debarment cannot be entered"),
    "ERR_RESPONSIBILITY_SCORE_BELOW_THRESHOLD": (422, "composite responsibility score below the responsible threshold"),
    "ERR_PROTEST_UNTIMELY": (409, "protest filed after the statutory deadline"),
    "ERR_PROTEST_TRIGGER_EVENT_MISSING": (422, "the event this ground protests has not occurred"),
    "ERR_PETITION_PREMATURE": (409, "the required portion of the debarment period has not been served"),
    "ERR_RESPONSE_WINDOW_CLOSED": (409, "the response window has closed"),
    "ERR_HEARING_ROOM_CONFLICT": (409, "the room is occupied within the changeover buffer"),
    "ERR_OFFICER_DOCKET_CAPACITY_EXCEEDED": (409, "hearing officer daily docket capacity exceeded"),
    "ERR_ACTIVE_PROCEEDING_EXISTS": (409, "the vendor already has an occupying debarment proceeding at this instant"),
    "ERR_EXTENSION_CAP_EXCEEDED": (422, "cumulative bid-due extension cap exceeded"),
    "ERR_CONTINUANCE_LIMIT_EXCEEDED": (409, "no further continuance may be granted"),
    "ERR_NO_MANDATORY_REQUIREMENTS": (422, "the solicitation identifies no mandatory requirement"),
    "ERR_NO_BIDS_RECEIVED": (409, "no bids were received"),
    "ERR_NO_APPARENT_LOW_BIDDER": (409, "no apparent low bidder is identified"),
    "ERR_AWARD_STAYED": (409, "an active protest stay blocks award activity"),
    "ERR_SUBCONTRACT_TIER_UNSUPPORTED": (422, "subcontract tier outside the supported range 1..3"),
    "ERR_SELF_SUBCONTRACT": (422, "a vendor may not subcontract to itself"),
    "ERR_BID_NOT_ON_SOLICITATION": (422, "the referenced bid belongs to a different solicitation"),
    "ERR_QUESTION_NOT_ON_SOLICITATION": (422, "the referenced question belongs to a different solicitation"),
    "ERR_NOT_APPARENT_LOW_BIDDER": (409, "this bid is not the apparent low bidder"),
    "ERR_VENDOR_ALREADY_DEBARRED": (409, "the vendor is already debarred"),
    "ERR_PETITION_ALREADY_PENDING": (409, "a reinstatement petition is already pending on this proceeding"),
    "ERR_INSUFFICIENT_FEE_BALANCE": (402, "insufficient protest filing fee balance"),
}


def err(error_id, message=None):
    return ApiError(error_id, message)


def invalid(detail=None):
    msg = "request body failed shape validation"
    if detail:
        msg = "request failed shape validation: %s" % detail
    return ApiError("ERR_INVALID_REQUEST", msg)
