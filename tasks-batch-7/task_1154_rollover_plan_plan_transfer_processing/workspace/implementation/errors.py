"""Error types and the full error catalog (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- 401 / 403 ---
def err_unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role is not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_sod(msg="Segregation of duties: actor matches eligibility_decided_by"):
    return ApiError("ERR_SOD_VIOLATION", 403, msg)


# --- 400 ---
def err_validation(msg="Malformed payload"):
    return ApiError("ERR_VALIDATION", 400, msg)


# --- 404 ---
def err_plan_not_found(msg="Referenced plan does not exist"):
    return ApiError("ERR_PLAN_NOT_FOUND", 404, msg)


def err_participant_not_found(msg="Referenced participant does not exist"):
    return ApiError("ERR_PARTICIPANT_NOT_FOUND", 404, msg)


def err_account_not_found(msg="Referenced account does not exist"):
    return ApiError("ERR_ACCOUNT_NOT_FOUND", 404, msg)


def err_case_not_found(msg="Referenced case does not exist"):
    return ApiError("ERR_CASE_NOT_FOUND", 404, msg)


def err_document_not_found(msg="Referenced document does not exist"):
    return ApiError("ERR_DOCUMENT_NOT_FOUND", 404, msg)


def err_verification_not_found(msg="Referenced verification does not exist"):
    return ApiError("ERR_VERIFICATION_NOT_FOUND", 404, msg)


def err_disbursement_not_found(msg="Referenced disbursement does not exist"):
    return ApiError("ERR_DISBURSEMENT_NOT_FOUND", 404, msg)


def err_redeposit_not_found(msg="Referenced redeposit does not exist"):
    return ApiError("ERR_REDEPOSIT_NOT_FOUND", 404, msg)


def err_loan_not_found(msg="Referenced loan does not exist"):
    return ApiError("ERR_LOAN_NOT_FOUND", 404, msg)


def err_tax_form_not_found(msg="Referenced tax form does not exist"):
    return ApiError("ERR_TAX_FORM_NOT_FOUND", 404, msg)


# --- 409 state ---
def err_case_invalid_state(msg="Case status does not permit the operation"):
    return ApiError("ERR_CASE_INVALID_STATE", 409, msg)


def err_plan_frozen(msg="Plan is FROZEN"):
    return ApiError("ERR_PLAN_FROZEN", 409, msg)


def err_plan_terminated(msg="Plan is TERMINATED"):
    return ApiError("ERR_PLAN_TERMINATED", 409, msg)


def err_plan_not_frozen(msg="Plan is not FROZEN"):
    return ApiError("ERR_PLAN_NOT_FROZEN", 409, msg)


def err_account_not_active(msg="Account is not ACTIVE"):
    return ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, msg)


def err_document_invalid_state(msg="Document status does not permit the operation"):
    return ApiError("ERR_DOCUMENT_INVALID_STATE", 409, msg)


def err_disbursement_already_exists(msg="A non-CANCELLED disbursement already exists for the case"):
    return ApiError("ERR_DISBURSEMENT_ALREADY_EXISTS", 409, msg)


def err_disbursement_invalid_state(msg="Disbursement status does not permit the operation"):
    return ApiError("ERR_DISBURSEMENT_INVALID_STATE", 409, msg)


def err_redeposit_invalid_state(msg="Redeposit is not PENDING_VERIFICATION"):
    return ApiError("ERR_REDEPOSIT_INVALID_STATE", 409, msg)


def err_verification_invalid_state(msg="Verification is not PENDING"):
    return ApiError("ERR_VERIFICATION_INVALID_STATE", 409, msg)


def err_tax_form_invalid_state(msg="Tax form status does not permit the operation"):
    return ApiError("ERR_TAX_FORM_INVALID_STATE", 409, msg)


def err_loan_invalid_state(msg="Loan is not ACTIVE"):
    return ApiError("ERR_LOAN_INVALID_STATE", 409, msg)


def err_account_already_exists(msg="Account already exists for (participant_id, plan_id)"):
    return ApiError("ERR_ACCOUNT_ALREADY_EXISTS", 409, msg)


def err_open_case_exists(msg="Source account already has a non-terminal rollover case"):
    return ApiError("ERR_OPEN_CASE_EXISTS", 409, msg)


def err_verification_not_verified(msg="Required verification is not VERIFIED"):
    return ApiError("ERR_VERIFICATION_NOT_VERIFIED", 409, msg)


def err_documents_outstanding(msg="Required documents are not all ACCEPTED"):
    return ApiError("ERR_DOCUMENTS_OUTSTANDING", 409, msg)


def err_loans_outstanding(msg="ACTIVE loans remain on the source account"):
    return ApiError("ERR_LOANS_OUTSTANDING", 409, msg)


def err_freeze_window_overlap(msg="Freeze window overlaps an existing window of the same plan"):
    return ApiError("ERR_FREEZE_WINDOW_OVERLAP", 409, msg)


# --- 422 ---
def err_not_eligible(msg="No qualifying event at submit"):
    return ApiError("ERR_NOT_ELIGIBLE", 422, msg)


def err_withholding_ack(msg="INDIRECT_ROLLOVER_OUT requires withholding_acknowledged"):
    return ApiError("ERR_WITHHOLDING_ACK_REQUIRED", 422, msg)


def err_plan_capability(msg="Plan capability flag rejects the operation"):
    return ApiError("ERR_PLAN_CAPABILITY_REJECTED", 422, msg)


def err_same_plan_transfer(msg="PLAN_TRANSFER receiving plan equals the source plan"):
    return ApiError("ERR_SAME_PLAN_TRANSFER", 422, msg)


def err_participant_mismatch(msg="Receiving account belongs to a different participant"):
    return ApiError("ERR_ACCOUNT_PARTICIPANT_MISMATCH", 422, msg)


def err_loan_not_transferrable(msg="Receiving plan does not accept loan transfers or is not ACTIVE"):
    return ApiError("ERR_LOAN_NOT_TRANSFERRABLE", 422, msg)


def err_disbursement_in_freeze(msg="Issue date falls inside a plan freeze window"):
    return ApiError("ERR_DISBURSEMENT_IN_FREEZE_WINDOW", 422, msg)


def err_window_range_invalid(msg="Freeze window start_date is after end_date"):
    return ApiError("ERR_WINDOW_RANGE_INVALID", 422, msg)


def err_deposit_past_deadline(msg="Redeposit received_date is past the applicable deadline"):
    return ApiError("ERR_DEPOSIT_PAST_DEADLINE", 422, msg)


def err_deposit_exceeds_remaining(msg="Redeposit amount exceeds the remaining shortfall"):
    return ApiError("ERR_DEPOSIT_EXCEEDS_REMAINING", 422, msg)


def err_amount_exceeds_vested(msg="requested_amount_cents exceeds vested_balance_cents"):
    return ApiError("ERR_AMOUNT_EXCEEDS_VESTED", 422, msg)


# --- 412 ---
def err_stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
