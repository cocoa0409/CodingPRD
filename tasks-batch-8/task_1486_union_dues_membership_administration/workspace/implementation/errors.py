"""Error type carrying the scaffold's exact error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# --- Auth ---
def missing_context():
    return err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
               "X-User-ID and X-User-Role headers are required and the role must be declared")


def insufficient_permissions():
    return err("ERR_INSUFFICIENT_PERMISSIONS", 403,
               "Role is not permitted to call this endpoint")


def not_resource_owner():
    return err("ERR_NOT_RESOURCE_OWNER", 403,
               "Member-role caller may only act on their own resources")


def segregation_of_duties():
    return err("ERR_SEGREGATION_OF_DUTIES", 403,
               "The same operator may not perform both sides of this controlled step")


# --- Existence (404 path) ---
def local_not_found():
    return err("ERR_LOCAL_NOT_FOUND", 404, "Referenced local does not exist")


def member_not_found():
    return err("ERR_MEMBER_NOT_FOUND", 404, "Referenced member does not exist")


def employer_not_found():
    return err("ERR_EMPLOYER_NOT_FOUND", 404, "Referenced employer does not exist")


def classification_not_found():
    return err("ERR_CLASSIFICATION_NOT_FOUND", 404, "Referenced classification does not exist")


def remittance_not_found():
    return err("ERR_REMITTANCE_NOT_FOUND", 404, "Referenced remittance does not exist")


def notice_not_found():
    return err("ERR_NOTICE_NOT_FOUND", 404, "Referenced notice does not exist")


def objector_case_not_found():
    return err("ERR_OBJECTOR_CASE_NOT_FOUND", 404, "Referenced objector case does not exist")


def transfer_not_found():
    return err("ERR_TRANSFER_NOT_FOUND", 404, "Referenced transfer does not exist")


def per_capita_report_not_found():
    return err("ERR_PER_CAPITA_REPORT_NOT_FOUND", 404, "Referenced per-capita report does not exist")


def election_not_found():
    return err("ERR_ELECTION_NOT_FOUND", 404, "Referenced election does not exist")


# --- Existence (422 body references) ---
def local_not_found_body():
    return err("ERR_LOCAL_NOT_FOUND", 422, "Referenced local does not exist")


def member_not_found_body():
    return err("ERR_MEMBER_NOT_FOUND", 422, "Referenced member does not exist")


def employer_not_found_body():
    return err("ERR_EMPLOYER_NOT_FOUND", 422, "Referenced employer does not exist")


def classification_not_found_body():
    return err("ERR_CLASSIFICATION_NOT_FOUND", 422,
               "Referenced classification does not exist or belongs to a different local")


# --- Generic request ---
def invalid_request(message="Missing or malformed required field"):
    return err("ERR_INVALID_REQUEST", 400, message)


# --- OCC ---
def stale_member_version():
    return err("ERR_STALE_MEMBER_VERSION", 412,
               "expected_member_version does not equal the member's current version")


def stale_local_version():
    return err("ERR_STALE_LOCAL_VERSION", 412,
               "expected_local_version does not equal the local's current version")


# --- State ---
def member_terminal_state():
    return err("ERR_MEMBER_TERMINAL_STATE", 409,
               "Operation requires a non-terminal member; member is WITHDRAWN or EXPELLED")


def member_not_suspended():
    return err("ERR_MEMBER_NOT_SUSPENDED", 409, "Reinstatement requires member status SUSPENDED")


def not_good_standing():
    return err("ERR_NOT_GOOD_STANDING", 409,
               "Operation requires good standing (status ACTIVE and zero arrears)")


def member_state_forbidden():
    return err("ERR_MEMBER_STATE_FORBIDDEN", 409,
               "The member's current status forbids this operation")


def local_not_active():
    return err("ERR_LOCAL_NOT_ACTIVE", 409, "Operation requires an ACTIVE local")


def remittance_not_received():
    return err("ERR_REMITTANCE_NOT_RECEIVED", 409,
               "Operation requires remittance status RECEIVED")


def remittance_not_reconciled():
    return err("ERR_REMITTANCE_NOT_RECONCILED", 409,
               "Posting requires remittance status RECONCILED")


def remittance_not_posted():
    return err("ERR_REMITTANCE_NOT_POSTED", 409, "Void requires remittance status POSTED")


def dispute_not_active():
    return err("ERR_DISPUTE_NOT_ACTIVE", 409,
               "Resolve-dispute requires dispute_status DISPUTED")


def notice_state_forbidden():
    return err("ERR_NOTICE_STATE_FORBIDDEN", 409, "Notice send requires DRAFT status")


def objector_case_state_forbidden():
    return err("ERR_OBJECTOR_CASE_STATE_FORBIDDEN", 409,
               "Objector-case action not valid from the case's current status")


def transfer_state_forbidden():
    return err("ERR_TRANSFER_STATE_FORBIDDEN", 409,
               "Transfer action not valid from the transfer's current status")


def report_state_forbidden():
    return err("ERR_REPORT_STATE_FORBIDDEN", 409,
               "Per-capita action not valid from the report's current status")


def election_state_forbidden():
    return err("ERR_ELECTION_STATE_FORBIDDEN", 409,
               "Election action not valid from the election's current status or window")


# --- Referential ---
def member_not_on_roster():
    return err("ERR_MEMBER_NOT_ON_ROSTER", 422,
               "Member is not on this employer's roster for this local (or is terminal)")


def target_local_unavailable():
    return err("ERR_TARGET_LOCAL_UNAVAILABLE", 409,
               "Transfer target local is missing, CLOSED, or equals the origin local")


# --- Temporal ---
def invalid_period():
    return err("ERR_INVALID_PERIOD", 422,
               "Period is not a valid YYYY-MM string or violates the clock-period rule")


def prior_period_unposted():
    return err("ERR_PRIOR_PERIOD_UNPOSTED", 409,
               "Remittance posting/voiding must proceed in strict chronological order")


def notice_window_open():
    return err("ERR_NOTICE_WINDOW_OPEN", 409,
               "Another notice's cure window is still open, or a DRAFT notice already exists")


def election_window_overlap():
    return err("ERR_ELECTION_WINDOW_OVERLAP", 409,
               "Nomination window intersects another election's window for this local")


def transfer_not_ready():
    return err("ERR_TRANSFER_NOT_READY", 409,
               "Transfer completion before the current clock period reaches effective_period")


# --- Constraint ---
def duplicate_classification():
    return err("ERR_DUPLICATE_CLASSIFICATION", 409,
               "Classification code already exists within the local")


def duplicate_member_number():
    return err("ERR_DUPLICATE_MEMBER_NUMBER", 409,
               "member_number already exists within the local")


def remittance_exists():
    return err("ERR_REMITTANCE_EXISTS", 409,
               "A remittance already exists for this employer and period")


def duplicate_remittance_line():
    return err("ERR_DUPLICATE_REMITTANCE_LINE", 409,
               "A line for this member already exists in the remittance")


def assessment_run_exists():
    return err("ERR_ASSESSMENT_RUN_EXISTS", 409,
               "An assessment run already exists for this local and period")


def objector_case_exists():
    return err("ERR_OBJECTOR_CASE_EXISTS", 409,
               "Member already has a non-terminal objector case")


def pct_out_of_range():
    return err("ERR_PCT_OUT_OF_RANGE", 422, "chargeable_share_pct must be within [0, 100]")


def payment_invalid_amount():
    return err("ERR_PAYMENT_INVALID_AMOUNT", 422, "Payment amount_cents must be positive")


# --- Fiscal ---
def remittance_unbalanced():
    return err("ERR_REMITTANCE_UNBALANCED", 409,
               "remitted_cents does not equal the sum of line deducted_cents")


def arrears_outstanding():
    return err("ERR_ARREARS_OUTSTANDING", 409,
               "Operation requires arrears_cents == 0")


def reinstatement_amount_mismatch():
    return err("ERR_REINSTATEMENT_AMOUNT_MISMATCH", 422,
               "amount_cents does not equal the quoted total_due_cents")


def stale_per_capita_rate():
    return err("ERR_STALE_PER_CAPITA_RATE", 409,
               "Local per_capita_rate_cents changed since the DRAFT was created")


def period_locked():
    return err("ERR_PERIOD_LOCKED", 409,
               "The period's per-capita report is SUBMITTED or PAID; void is blocked")
