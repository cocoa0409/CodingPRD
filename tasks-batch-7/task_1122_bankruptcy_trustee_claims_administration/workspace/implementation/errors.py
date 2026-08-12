"""Error catalog (SCAFFOLD Table 6 / PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_MISSING_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"   # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                      # 404
ERR_CASE_CLOSED = "ERR_CASE_CLOSED"                                  # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                              # 409
ERR_NOT_ASSIGNED_TRUSTEE = "ERR_NOT_ASSIGNED_TRUSTEE"                # 403
ERR_BAR_DATE_NOT_PASSED = "ERR_BAR_DATE_NOT_PASSED"                  # 409
ERR_INVALID_BAR_DATE = "ERR_INVALID_BAR_DATE"                        # 422
ERR_NO_ASSETS_SCHEDULED = "ERR_NO_ASSETS_SCHEDULED"                  # 409
ERR_CLAIMS_UNREVIEWED = "ERR_CLAIMS_UNREVIEWED"                      # 409
ERR_ASSETS_PENDING_SALE = "ERR_ASSETS_PENDING_SALE"                  # 409
ERR_OBJECTIONS_PENDING = "ERR_OBJECTIONS_PENDING"                    # 409
ERR_NO_FUNDS_TO_DISTRIBUTE = "ERR_NO_FUNDS_TO_DISTRIBUTE"            # 409
ERR_PLAN_EXECUTING = "ERR_PLAN_EXECUTING"                            # 409
ERR_PLAN_ALREADY_ACTIVE = "ERR_PLAN_ALREADY_ACTIVE"                  # 409
ERR_CASE_NOT_IN_DISTRIBUTION = "ERR_CASE_NOT_IN_DISTRIBUTION"        # 409
ERR_STALE_CASE_VERSION = "ERR_STALE_CASE_VERSION"                    # 412
ERR_OBJECTION_ALREADY_PENDING = "ERR_OBJECTION_ALREADY_PENDING"      # 409
ERR_SETTLEMENT_NOT_PARTIAL = "ERR_SETTLEMENT_NOT_PARTIAL"            # 422
ERR_CASE_BEYOND_REOPEN = "ERR_CASE_BEYOND_REOPEN"                    # 409
ERR_DIVIDEND_POSTED = "ERR_DIVIDEND_POSTED"                          # 409
ERR_ASSET_EXEMPT = "ERR_ASSET_EXEMPT"                                # 409
ERR_SALE_ALREADY_PENDING = "ERR_SALE_ALREADY_PENDING"                # 409
ERR_BELOW_MINIMUM_PRICE = "ERR_BELOW_MINIMUM_PRICE"                  # 422
ERR_OBJECTION_WINDOW_OPEN = "ERR_OBJECTION_WINDOW_OPEN"              # 409
ERR_OBJECTION_WINDOW_CLOSED = "ERR_OBJECTION_WINDOW_CLOSED"          # 409
ERR_TRANSFER_NOT_AVOIDABLE = "ERR_TRANSFER_NOT_AVOIDABLE"            # 409
ERR_INVALID_DEMAND_AMOUNT = "ERR_INVALID_DEMAND_AMOUNT"              # 422
ERR_PLAN_RELIES_ON_RECOVERY = "ERR_PLAN_RELIES_ON_RECOVERY"          # 409
ERR_APPROVAL_EXCEEDS_REQUEST = "ERR_APPROVAL_EXCEEDS_REQUEST"        # 422
ERR_FEE_NOT_YET_EFFECTIVE = "ERR_FEE_NOT_YET_EFFECTIVE"              # 409
ERR_INSUFFICIENT_ESTATE_FUNDS = "ERR_INSUFFICIENT_ESTATE_FUNDS"      # 409
ERR_DUPLICATE = "ERR_DUPLICATE"                                      # 409
ERR_REFERENTIAL_INTEGRITY = "ERR_REFERENTIAL_INTEGRITY"              # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                          # 400
ERR_FINAL_REPORT_NOT_READY = "ERR_FINAL_REPORT_NOT_READY"            # 409


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, 404, f"The requested {what} does not exist.")


def invalid_request(message):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message):
    return ApiError(ERR_INVALID_STATE, 409, message)
