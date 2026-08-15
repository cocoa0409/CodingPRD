"""Error classes and error ID constants (PRD §5 catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_user_context(msg="X-User-ID and X-User-Role headers must be present and role must be a declared role"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def err_forbidden(msg="Caller role is not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", msg, 403)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_stale_contract_version(msg="expected_contract_version does not equal the contract's current version"):
    return ApiError("ERR_STALE_CONTRACT_VERSION", msg, 412)


def err_invalid_state(msg="Entity is not in a valid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg, 409)


def err_contract_not_draft(msg="Direct creation requires the contract to be DRAFT"):
    return ApiError("ERR_CONTRACT_NOT_DRAFT", msg, 409)


def err_contract_not_active(msg="Operation requires the contract to be ACTIVE"):
    return ApiError("ERR_CONTRACT_NOT_ACTIVE", msg, 409)


def err_proposal_stale(msg="Proposal is stale; re-run the model"):
    return ApiError("ERR_PROPOSAL_STALE", msg, 409)


def err_sod_amendment(msg="Amendment creator may not approve their own amendment"):
    return ApiError("ERR_SOD_AMENDMENT_SELF_APPROVE", msg, 409)


def err_sod_write_off(msg="The user who claimed the case may not write it off"):
    return ApiError("ERR_SOD_WRITE_OFF_SELF", msg, 409)


def err_payer_inactive(msg="Payer is INACTIVE"):
    return ApiError("ERR_PAYER_INACTIVE", msg, 409)


def err_prior_contract_mismatch(msg="prior_contract_id references a contract of a different payer"):
    return ApiError("ERR_PRIOR_CONTRACT_MISMATCH", msg, 409)


def err_amendment_supersede_mismatch(msg="supersedes_amendment_id references an amendment of a different contract"):
    return ApiError("ERR_AMENDMENT_SUPERSEDE_MISMATCH", msg, 409)


def err_appeal_level_mismatch(msg="Appeal level does not equal the level the case is eligible to file next"):
    return ApiError("ERR_APPEAL_LEVEL_MISMATCH", msg, 409)


def err_no_matching_term(msg="The resolved contract has no ContractTerm for the claim's service_category"):
    return ApiError("ERR_NO_MATCHING_TERM", msg, 409)


def err_contract_window_invalid(msg="expiration_date is not after today"):
    return ApiError("ERR_CONTRACT_WINDOW_INVALID", msg, 409)


def err_contract_window_overlap(msg="Same-payer contract windows may not share a date outside renewal-link allowance"):
    return ApiError("ERR_CONTRACT_WINDOW_OVERLAP", msg, 409)


def err_amendment_out_of_term(msg="Amendment effective_date/retroactive_to_date outside allowed window"):
    return ApiError("ERR_AMENDMENT_EFFECTIVE_OUT_OF_TERM", msg, 409)


def err_escalator_out_of_term(msg="Escalator effective_date outside the contract term"):
    return ApiError("ERR_ESCALATOR_OUT_OF_TERM", msg, 409)


def err_escalator_date_collision(msg="Another escalator with the same effective_date exists on the contract"):
    return ApiError("ERR_ESCALATOR_DATE_COLLISION", msg, 409)


def err_network_agreement_overlap(msg="Same payer + network_name agreement windows may not overlap"):
    return ApiError("ERR_NETWORK_AGREEMENT_OVERLAP", msg, 409)


def err_line_outside_stay(msg="Claim line service_date outside [admission_date, discharge_date]"):
    return ApiError("ERR_LINE_OUTSIDE_STAY", msg, 409)


def err_appeal_window_closed(msg="Appeal filing window has closed"):
    return ApiError("ERR_APPEAL_WINDOW_CLOSED", msg, 409)


def err_appeal_already_open(msg="The case already has an appeal in DRAFT or FILED"):
    return ApiError("ERR_APPEAL_ALREADY_OPEN", msg, 409)


def err_case_already_active(msg="A non-terminal case already exists for the claim"):
    return ApiError("ERR_CASE_ALREADY_ACTIVE", msg, 409)


def err_duplicate_contract_code(msg="contract_code already used by another contract of the same payer"):
    return ApiError("ERR_DUPLICATE_CONTRACT_CODE", msg, 409)


def err_duplicate_service_category(msg="A ContractTerm for this service_category already exists on the contract"):
    return ApiError("ERR_DUPLICATE_SERVICE_CATEGORY", msg, 409)


def err_duplicate_claim_number(msg="claim_number already exists for this payer"):
    return ApiError("ERR_DUPLICATE_CLAIM_NUMBER", msg, 409)


def err_invalid_rate_parameters(msg="Rate-field incoherence"):
    return ApiError("ERR_INVALID_RATE_PARAMETERS", msg, 422)


def err_missing_drg_weight(msg="Pricing a DRG_BASE claim without drg_weight"):
    return ApiError("ERR_MISSING_DRG_WEIGHT", msg, 422)


def err_claim_has_no_lines(msg="Pricing requires at least one claim line"):
    return ApiError("ERR_CLAIM_HAS_NO_LINES", msg, 422)


def err_write_off_amount_mismatch(msg="amount_cents must equal current_outstanding_cents"):
    return ApiError("ERR_WRITE_OFF_AMOUNT_MISMATCH", msg, 422)


def err_recovery_amount_invalid(msg="Invalid recovered_amount_cents for the outcome"):
    return ApiError("ERR_RECOVERY_AMOUNT_INVALID", msg, 422)


def err_remittance_exceeds_charges(msg="POSTED remittance total would exceed total_billed_charges_cents"):
    return ApiError("ERR_REMITTANCE_EXCEEDS_CHARGES", msg, 409)


def err_write_off_cap_exceeded(msg="current_outstanding_cents exceeds WRITE_OFF_DIRECTOR_CAP_CENTS"):
    return ApiError("ERR_WRITE_OFF_CAP_EXCEEDED", msg, 409)


def err_escalation_min_not_met(msg="Arbitration requires current_outstanding_cents >= 100000"):
    return ApiError("ERR_ESCALATION_MIN_NOT_MET", msg, 409)


def err_escalation_blocked(msg="Prior-level appeal outcome does not permit escalation"):
    return ApiError("ERR_ESCALATION_BLOCKED", msg, 409)
