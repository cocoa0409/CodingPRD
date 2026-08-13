"""Error type and the error-id catalog (SCAFFOLD Table 6 / PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# Error catalog ids (verbatim from the scaffold error table).
MISSING_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"   # 400
FORBIDDEN = "ERR_FORBIDDEN_FOR_ROLE"                             # 403
INVALID_REQUEST = "ERR_INVALID_REQUEST"                          # 400
NOT_FOUND = "ERR_NOT_FOUND"                                      # 404
INVALID_STATE = "ERR_INVALID_STATE_TRANSITION"                   # 409
STALE_VERSION = "ERR_STALE_VERSION"                              # 412
SEGREGATION = "ERR_SEGREGATION_OF_DUTIES"                        # 409
ENTITY_INACTIVE = "ERR_ENTITY_INACTIVE"                          # 409
SAME_LEGAL_ENTITY = "ERR_SAME_LEGAL_ENTITY"                      # 409
ENTITY_HAS_ACTIVE_AGREEMENTS = "ERR_ENTITY_HAS_ACTIVE_AGREEMENTS"  # 409
AGREEMENT_PERIOD_OVERLAP = "ERR_AGREEMENT_PERIOD_OVERLAP"        # 409
AGREEMENT_NOT_IN_EFFECT = "ERR_AGREEMENT_NOT_IN_EFFECT"          # 409
AGREEMENT_NOT_ACTIVE = "ERR_AGREEMENT_NOT_ACTIVE"                # 409
AGREEMENT_HAS_OPEN_TRANSACTIONS = "ERR_AGREEMENT_HAS_OPEN_TRANSACTIONS"  # 409
APA_LOCKED = "ERR_APA_LOCKED"                                    # 409
STALE_BENCHMARK = "ERR_STALE_BENCHMARK"                          # 409
ELIMINATION_MISMATCH = "ERR_ELIMINATION_MISMATCH"                # 409
NO_ELIMINATED_TRANSACTIONS = "ERR_NO_ELIMINATED_TRANSACTIONS"    # 409
YEAR_NOT_CLOSING = "ERR_YEAR_NOT_CLOSING"                        # 409
YEAR_HAS_OPEN_TRANSACTIONS = "ERR_YEAR_HAS_OPEN_TRANSACTIONS"    # 409
YEAR_HAS_OPEN_TRUE_UPS = "ERR_YEAR_HAS_OPEN_TRUE_UPS"            # 409
BOOKS_CLOSED = "ERR_BOOKS_CLOSED"                                # 409
CBC_NOT_REQUIRED = "ERR_CBC_NOT_REQUIRED"                        # 409
CBC_FILING_MISSING = "ERR_CBC_FILING_MISSING"                    # 409
DUPLICATE_CBC_REPORT = "ERR_DUPLICATE_CBC_REPORT"                # 409
DOC_NOT_FINAL = "ERR_DOC_NOT_FINAL"                              # 409
DEFENSE_FILE_EMPTY = "ERR_DEFENSE_FILE_EMPTY"                    # 409
APA_YEAR_OVERLAP = "ERR_APA_YEAR_OVERLAP"                        # 409
POOL_NOT_ZERO_SUM = "ERR_POOL_NOT_ZERO_SUM"                      # 409
DUPLICATE_CASH_POOL = "ERR_DUPLICATE_CASH_POOL"                  # 409
