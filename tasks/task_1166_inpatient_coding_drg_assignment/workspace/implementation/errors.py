"""Error type and the scaffold's error-id catalog."""


class ApiError(Exception):
    def __init__(self, http_status, error_id, message):
        super().__init__(message)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                # 403
ERR_ACCOUNT_NOT_FOUND = "ERR_ACCOUNT_NOT_FOUND"                # 404
ERR_CHART_NOT_FOUND = "ERR_CHART_NOT_FOUND"                    # 404
ERR_CODER_NOT_FOUND = "ERR_CODER_NOT_FOUND"                    # 404
ERR_ASSIGNMENT_NOT_FOUND = "ERR_ASSIGNMENT_NOT_FOUND"          # 404
ERR_BILL_NOT_FOUND = "ERR_BILL_NOT_FOUND"                      # 404
ERR_CODED_CASE_NOT_FOUND = "ERR_CODED_CASE_NOT_FOUND"          # 404
ERR_AUDIT_NOT_FOUND = "ERR_AUDIT_NOT_FOUND"                    # 404
ERR_FINDING_NOT_FOUND = "ERR_FINDING_NOT_FOUND"                # 404
ERR_REVIEW_NOT_FOUND = "ERR_REVIEW_NOT_FOUND"                  # 404
ERR_REBILL_NOT_FOUND = "ERR_REBILL_NOT_FOUND"                  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                    # 400 (and 404 for line/deficiency/sweep refs)
ERR_INVALID_STATE = "ERR_INVALID_STATE"                        # 409
ERR_CHART_NOT_READY = "ERR_CHART_NOT_READY"                    # 409
ERR_CHART_NOT_CODED = "ERR_CHART_NOT_CODED"                    # 409
ERR_CODER_INACTIVE = "ERR_CODER_INACTIVE"                      # 409
ERR_CODER_CREDENTIAL_INSUFFICIENT = "ERR_CODER_CREDENTIAL_INSUFFICIENT"  # 422
ERR_SELF_AUDIT_FORBIDDEN = "ERR_SELF_AUDIT_FORBIDDEN"          # 403
ERR_POA_INVALID_FOR_CODE = "ERR_POA_INVALID_FOR_CODE"          # 422
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 403
ERR_PRINCIPAL_DX_REQUIRED = "ERR_PRINCIPAL_DX_REQUIRED"        # 422
ERR_INVALID_PRINCIPAL_CODE = "ERR_INVALID_PRINCIPAL_CODE"      # 422
ERR_DUPLICATE_SEQUENCE = "ERR_DUPLICATE_SEQUENCE"              # 422
ERR_MANIFESTATION_ORDER = "ERR_MANIFESTATION_ORDER"            # 422
ERR_ASSIGNMENT_EXISTS = "ERR_ASSIGNMENT_EXISTS"                # 409
ERR_NO_ELIGIBLE_CODER = "ERR_NO_ELIGIBLE_CODER"                # 422
ERR_CASE_NOT_IN_SAMPLE = "ERR_CASE_NOT_IN_SAMPLE"              # 422
ERR_WORKLOAD_OVERLAP = "ERR_WORKLOAD_OVERLAP"                  # 409
ERR_AUDIT_WINDOW_OVERLAP = "ERR_AUDIT_WINDOW_OVERLAP"          # 409
ERR_TIMELY_FILING_EXPIRED = "ERR_TIMELY_FILING_EXPIRED"        # 422
ERR_OPEN_FINDINGS_REMAIN = "ERR_OPEN_FINDINGS_REMAIN"          # 409
ERR_REBILL_DELTA_MISMATCH = "ERR_REBILL_DELTA_MISMATCH"        # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412


def fail(http_status, error_id, message):
    raise ApiError(http_status, error_id, message)
