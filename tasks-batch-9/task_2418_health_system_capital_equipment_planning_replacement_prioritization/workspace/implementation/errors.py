"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_CATALOG = {
    "ERR_USER_CONTEXT_REQUIRED": (401, "Authentication context is required."),
    "ERR_UNAUTHORIZED": (403, "The caller's role may not perform this operation."),
    "ERR_VALIDATION": (422, "The request payload failed validation."),
    "ERR_DUPLICATE_KEY": (409, "A row with that unique key already exists."),

    "ERR_FACILITY_NOT_FOUND": (404, "Facility not found."),
    "ERR_DEPARTMENT_NOT_FOUND": (404, "Department not found."),
    "ERR_CYCLE_NOT_FOUND": (404, "Capital cycle not found."),
    "ERR_ALLOCATION_NOT_FOUND": (404, "Facility allocation not found."),
    "ERR_ASSET_NOT_FOUND": (404, "Equipment asset not found."),
    "ERR_REQUEST_NOT_FOUND": (404, "Replacement request not found."),
    "ERR_MEMBER_NOT_FOUND": (404, "Committee member not found."),
    "ERR_CONTRACT_NOT_FOUND": (404, "Contract not found."),
    "ERR_GPO_CONTRACT_NOT_FOUND": (404, "GPO contract not found."),
    "ERR_QUOTE_NOT_FOUND": (404, "Vendor quote not found."),
    "ERR_PROJECT_NOT_FOUND": (404, "Installation project not found."),
    "ERR_AUDIT_NOT_FOUND": (404, "Utilization audit not found."),

    "ERR_DEPARTMENT_SCOPE_VIOLATION": (403, "The caller may only act on its own department."),
    "ERR_FACILITY_SCOPE_VIOLATION": (403, "The caller may only act on its own facility."),

    "ERR_ASSET_FACILITY_MISMATCH": (422, "The asset's department does not belong to the given facility."),
    "ERR_ASSET_DEPARTMENT_MISMATCH": (422, "The asset does not belong to the request's department."),
    "ERR_MODIFICATION_COST_EXCEEDS_CAP": (422, "Facility modification cost exceeds the allowed share of estimated capital."),
    "ERR_MANDATE_DEADLINE_REQUIRED": (422, "A regulatory mandate requires a mandate deadline."),

    "ERR_CYCLE_INVALID_STATE": (409, "The capital cycle is not in a state that permits this operation."),
    "ERR_REQUEST_INVALID_STATE": (409, "The replacement request is not in a state that permits this operation."),
    "ERR_ASSET_INVALID_STATE": (409, "The equipment asset is not in a state that permits this operation."),
    "ERR_QUOTE_INVALID_STATE": (409, "The vendor quote is not in a state that permits this operation."),
    "ERR_PROJECT_INVALID_STATE": (409, "The installation project is not in a state that permits this operation."),
    "ERR_AUDIT_INVALID_STATE": (409, "The utilization audit is not in a state that permits this operation."),
    "ERR_CONTINGENCY_ALREADY_RELEASED": (409, "The facility contingency reserve has already been released."),

    "ERR_STALE_REQUEST_VERSION": (412, "The supplied request version does not match the stored version."),
    "ERR_STALE_CYCLE_VERSION": (412, "The supplied cycle version does not match the stored version."),

    "ERR_ASSET_NOT_REPLACEMENT_ELIGIBLE": (422, "The asset does not meet the replacement eligibility gate."),
    "ERR_DUPLICATE_ASSET_REQUEST": (409, "Another live request already targets this asset in this cycle."),
    "ERR_REVISION_LIMIT_EXCEEDED": (409, "The request has exhausted its revision allowance."),
    "ERR_NEGOTIATION_ROUND_LIMIT": (409, "The quote has exhausted its negotiation rounds."),
    "ERR_GPO_CONTRACT_EXPIRED": (409, "The GPO contract has expired."),
    "ERR_QUOTE_EXPIRED": (409, "The vendor quote has expired."),
    "ERR_TRADE_IN_ASSET_MISMATCH": (422, "The trade-in asset does not belong to the request's facility."),
    "ERR_TRADE_IN_ASSET_UNAVAILABLE": (409, "The trade-in asset is not available for trade-in."),
    "ERR_TRADE_IN_NOT_HELD": (422, "The asset is not held for trade-in."),
    "ERR_SAFETY_REVIEW_REQUIRED": (422, "A safety review acknowledgement is required."),
    "ERR_EVENT_DATE_IN_FUTURE": (422, "The event date lies in the future."),

    "ERR_SOD_ALLOCATOR_CANNOT_FUND": (403, "The user who ran the allocation may not fund requests in that cycle."),
    "ERR_VOTE_CONFLICT_OF_INTEREST": (403, "The member is not eligible to vote on this request."),
    "ERR_VETO_NOT_PERMITTED": (422, "Only the safety officer may cast a veto."),
    "ERR_CHAIR_REQUIRED": (403, "Only the committee chair may close voting."),
    "ERR_NO_ELIGIBLE_VOTERS": (409, "No eligible voters exist for this request."),
    "ERR_QUORUM_NOT_MET": (409, "Quorum has not been met."),

    "ERR_NO_FACILITY_ALLOCATION": (409, "No facility allocation exists for the cycle and facility."),
    "ERR_ALLOCATION_INSUFFICIENT": (409, "The facility allocation has insufficient available funds."),
    "ERR_CONTINGENCY_RESERVE_EXCEEDED": (422, "Facility contingency reserves exceed the system contingency."),
    "ERR_ALLOCATION_ALREADY_COMMITTED": (409, "The allocation already carries committed funds."),
    "ERR_NO_ELIGIBLE_REQUESTS": (409, "No eligible requests exist for the allocation run."),

    "ERR_INVALID_INTERVAL": (422, "The supplied interval is not valid."),
    "ERR_CONSTRUCTION_WINDOW_REQUIRED": (422, "The construction window does not agree with construction_required."),
    "ERR_DOWNTIME_WINDOW_CONFLICT": (409, "The downtime window conflicts with another project in the department."),
    "ERR_CONSTRUCTION_CAPACITY_EXCEEDED": (409, "The facility's concurrent construction ceiling would be exceeded."),
    "ERR_PROJECT_DEPENDENCY_CYCLE": (422, "The predecessor chain would form a cycle."),
    "ERR_PREDECESSOR_NOT_COMMISSIONED": (409, "The predecessor project has not been commissioned."),
    "ERR_AUDIT_WINDOW_INVALID": (422, "The audit window is not valid for the installation project."),
    "ERR_PROJECT_ACTIVE": (409, "An active installation project blocks this operation."),
    "ERR_INSTALLATION_NOT_COMMISSIONED": (409, "The installation project has not been commissioned."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        status, default_message = ERROR_CATALOG.get(error_id, (400, error_id))
        self.http_status = http_status if http_status is not None else status
        self.message = message if message is not None else default_message
