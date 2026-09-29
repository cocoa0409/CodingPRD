"""Error catalog (PRD section 5) and the exception type carrying it."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# --- authentication / authorisation -----------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_OWNERSHIP_MISMATCH = "ERR_OWNERSHIP_MISMATCH"

# --- existence ---------------------------------------------------------------
ERR_PROGRAM_YEAR_NOT_FOUND = "ERR_PROGRAM_YEAR_NOT_FOUND"
ERR_APPLICANT_NOT_FOUND = "ERR_APPLICANT_NOT_FOUND"
ERR_APPLICATION_NOT_FOUND = "ERR_APPLICATION_NOT_FOUND"
ERR_INSPECTION_NOT_FOUND = "ERR_INSPECTION_NOT_FOUND"
ERR_WRITE_UP_NOT_FOUND = "ERR_WRITE_UP_NOT_FOUND"
ERR_WORK_ITEM_NOT_FOUND = "ERR_WORK_ITEM_NOT_FOUND"
ERR_CONTRACTOR_NOT_FOUND = "ERR_CONTRACTOR_NOT_FOUND"
ERR_SOLICITATION_NOT_FOUND = "ERR_SOLICITATION_NOT_FOUND"
ERR_BID_NOT_FOUND = "ERR_BID_NOT_FOUND"
ERR_LOAN_NOT_FOUND = "ERR_LOAN_NOT_FOUND"
ERR_DRAW_NOT_FOUND = "ERR_DRAW_NOT_FOUND"
ERR_CHANGE_ORDER_NOT_FOUND = "ERR_CHANGE_ORDER_NOT_FOUND"
ERR_COMPLAINT_NOT_FOUND = "ERR_COMPLAINT_NOT_FOUND"

# --- schema / concurrency / state -------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"

# --- domain gates ------------------------------------------------------------
ERR_INCOME_NOT_VERIFIED = "ERR_INCOME_NOT_VERIFIED"
ERR_OWNERSHIP_NOT_VERIFIED = "ERR_OWNERSHIP_NOT_VERIFIED"
ERR_LEAD_CLEARANCE_REQUIRED = "ERR_LEAD_CLEARANCE_REQUIRED"
ERR_HISTORIC_CLEARANCE_REQUIRED = "ERR_HISTORIC_CLEARANCE_REQUIRED"
ERR_DRAW_INSPECTION_NOT_PASSED = "ERR_DRAW_INSPECTION_NOT_PASSED"
ERR_LIEN_NOT_RECORDED = "ERR_LIEN_NOT_RECORDED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_INSPECTION_WINDOW_CONFLICT = "ERR_INSPECTION_WINDOW_CONFLICT"
ERR_BID_WINDOW_CLOSED = "ERR_BID_WINDOW_CLOSED"
ERR_CONTRACTOR_CAPACITY_CONFLICT = "ERR_CONTRACTOR_CAPACITY_CONFLICT"
ERR_WARRANTY_EXPIRED = "ERR_WARRANTY_EXPIRED"
ERR_LOAN_LIMIT_EXCEEDED = "ERR_LOAN_LIMIT_EXCEEDED"
ERR_ALLOCATION_INSUFFICIENT = "ERR_ALLOCATION_INSUFFICIENT"
ERR_DRAW_EXCEEDS_CONTRACT_BALANCE = "ERR_DRAW_EXCEEDS_CONTRACT_BALANCE"
ERR_CHANGE_ORDER_EXCEEDS_LIMIT = "ERR_CHANGE_ORDER_EXCEEDS_LIMIT"
ERR_DUPLICATE_BID = "ERR_DUPLICATE_BID"
ERR_INSUFFICIENT_BIDS = "ERR_INSUFFICIENT_BIDS"
ERR_BID_NOT_RESPONSIVE = "ERR_BID_NOT_RESPONSIVE"
ERR_CONTRACTOR_NOT_APPROVED = "ERR_CONTRACTOR_NOT_APPROVED"
ERR_CONTRACTOR_NOT_LEAD_CERTIFIED = "ERR_CONTRACTOR_NOT_LEAD_CERTIFIED"
ERR_WRITE_UP_EMPTY = "ERR_WRITE_UP_EMPTY"
ERR_PRIORITY_REPAIRS_NOT_ADDRESSED = "ERR_PRIORITY_REPAIRS_NOT_ADDRESSED"
ERR_APPLICANT_OVER_INCOME = "ERR_APPLICANT_OVER_INCOME"


HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_OWNERSHIP_MISMATCH: 403,
    ERR_PROGRAM_YEAR_NOT_FOUND: 404,
    ERR_APPLICANT_NOT_FOUND: 404,
    ERR_APPLICATION_NOT_FOUND: 404,
    ERR_INSPECTION_NOT_FOUND: 404,
    ERR_WRITE_UP_NOT_FOUND: 404,
    ERR_WORK_ITEM_NOT_FOUND: 404,
    ERR_CONTRACTOR_NOT_FOUND: 404,
    ERR_SOLICITATION_NOT_FOUND: 404,
    ERR_BID_NOT_FOUND: 404,
    ERR_LOAN_NOT_FOUND: 404,
    ERR_DRAW_NOT_FOUND: 404,
    ERR_CHANGE_ORDER_NOT_FOUND: 404,
    ERR_COMPLAINT_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_STATE: 409,
    ERR_INCOME_NOT_VERIFIED: 409,
    ERR_OWNERSHIP_NOT_VERIFIED: 409,
    ERR_LEAD_CLEARANCE_REQUIRED: 409,
    ERR_HISTORIC_CLEARANCE_REQUIRED: 409,
    ERR_DRAW_INSPECTION_NOT_PASSED: 409,
    ERR_LIEN_NOT_RECORDED: 409,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_INSPECTION_WINDOW_CONFLICT: 409,
    ERR_BID_WINDOW_CLOSED: 409,
    ERR_CONTRACTOR_CAPACITY_CONFLICT: 409,
    ERR_WARRANTY_EXPIRED: 409,
    ERR_LOAN_LIMIT_EXCEEDED: 422,
    ERR_ALLOCATION_INSUFFICIENT: 409,
    ERR_DRAW_EXCEEDS_CONTRACT_BALANCE: 422,
    ERR_CHANGE_ORDER_EXCEEDS_LIMIT: 422,
    ERR_DUPLICATE_BID: 409,
    ERR_INSUFFICIENT_BIDS: 409,
    ERR_BID_NOT_RESPONSIVE: 422,
    ERR_CONTRACTOR_NOT_APPROVED: 422,
    ERR_CONTRACTOR_NOT_LEAD_CERTIFIED: 422,
    ERR_WRITE_UP_EMPTY: 422,
    ERR_PRIORITY_REPAIRS_NOT_ADDRESSED: 422,
    ERR_APPLICANT_OVER_INCOME: 422,
}


DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "Authentication headers are missing or the role is not recognised.",
    ERR_FORBIDDEN_ROLE: "The acting role may not perform this operation.",
    ERR_OWNERSHIP_MISMATCH: "The addressed record does not belong to the acting user.",
    ERR_PROGRAM_YEAR_NOT_FOUND: "Program year not found.",
    ERR_APPLICANT_NOT_FOUND: "Applicant not found.",
    ERR_APPLICATION_NOT_FOUND: "Rehabilitation application not found.",
    ERR_INSPECTION_NOT_FOUND: "Property inspection not found.",
    ERR_WRITE_UP_NOT_FOUND: "Work write-up not found.",
    ERR_WORK_ITEM_NOT_FOUND: "Work item not found.",
    ERR_CONTRACTOR_NOT_FOUND: "Contractor not found.",
    ERR_SOLICITATION_NOT_FOUND: "Bid solicitation not found.",
    ERR_BID_NOT_FOUND: "Bid not found.",
    ERR_LOAN_NOT_FOUND: "Rehabilitation loan not found.",
    ERR_DRAW_NOT_FOUND: "Draw request not found.",
    ERR_CHANGE_ORDER_NOT_FOUND: "Change order not found.",
    ERR_COMPLAINT_NOT_FOUND: "Complaint case not found.",
    ERR_INVALID_REQUEST: "The request payload or query is invalid.",
    ERR_STALE_VERSION: "The supplied expected version does not match the stored version.",
    ERR_INVALID_STATE: "The addressed row is not in a state from which this transition is defined.",
    ERR_INCOME_NOT_VERIFIED: "The household income has not been certified.",
    ERR_OWNERSHIP_NOT_VERIFIED: "Property ownership has not been verified.",
    ERR_LEAD_CLEARANCE_REQUIRED: "Lead hazard clearance is required before this operation.",
    ERR_HISTORIC_CLEARANCE_REQUIRED: "Historic review clearance is required before this operation.",
    ERR_DRAW_INSPECTION_NOT_PASSED: "The draw has not passed its inspection.",
    ERR_LIEN_NOT_RECORDED: "The rehabilitation lien has not been recorded.",
    ERR_SEGREGATION_OF_DUTIES: "The acting user may not approve their own work.",
    ERR_INSPECTION_WINDOW_CONFLICT: "The requested inspection window overlaps an existing visit.",
    ERR_BID_WINDOW_CLOSED: "The bid window for this solicitation has closed.",
    ERR_CONTRACTOR_CAPACITY_CONFLICT: "The contractor already holds an overlapping award.",
    ERR_WARRANTY_EXPIRED: "The warranty period for this case has expired.",
    ERR_LOAN_LIMIT_EXCEEDED: "The awarded amount exceeds the program-year loan maximum.",
    ERR_ALLOCATION_INSUFFICIENT: "The program year has insufficient uncommitted allocation.",
    ERR_DRAW_EXCEEDS_CONTRACT_BALANCE: "The requested draw exceeds the remaining contract balance.",
    ERR_CHANGE_ORDER_EXCEEDS_LIMIT: "The cumulative change order delta exceeds the allowed limit.",
    ERR_DUPLICATE_BID: "This contractor has already bid on this solicitation.",
    ERR_INSUFFICIENT_BIDS: "The solicitation has not received the minimum number of bids.",
    ERR_BID_NOT_RESPONSIVE: "The named bid is not responsive.",
    ERR_CONTRACTOR_NOT_APPROVED: "The contractor is not on the approved list.",
    ERR_CONTRACTOR_NOT_LEAD_CERTIFIED: "The contractor is not lead-safe certified.",
    ERR_WRITE_UP_EMPTY: "The write-up carries no work items.",
    ERR_PRIORITY_REPAIRS_NOT_ADDRESSED: "The write-up carries no health-safety or code repair lines.",
    ERR_APPLICANT_OVER_INCOME: "The household is over the program income limit.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, HTTP_STATUS[error_id], message)
