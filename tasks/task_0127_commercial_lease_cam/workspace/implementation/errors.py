"""Domain error classes and the error-id catalog (SCAFFOLD §1.6 / PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from the scaffold error catalog (PRD §5).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                  # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                        # 403
ERR_NOT_LEASE_OWNER = "ERR_NOT_LEASE_OWNER"                  # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"     # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                             # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                 # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                     # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                     # 412
ERR_YEAR_MISMATCH = "ERR_YEAR_MISMATCH"                     # 422
ERR_POOL_LOCKED = "ERR_POOL_LOCKED"                         # 409
ERR_EMPTY_DENOMINATOR = "ERR_EMPTY_DENOMINATOR"             # 422
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"             # 422
ERR_DUPLICATE_RECON_PERIOD = "ERR_DUPLICATE_RECON_PERIOD"  # 409
ERR_PCT_RENT_ALREADY_RUN = "ERR_PCT_RENT_ALREADY_RUN"      # 409
ERR_TI_ALLOWANCE_EXCEEDED = "ERR_TI_ALLOWANCE_EXCEEDED"    # 422
ERR_ESTOPPEL_BALANCE_MISMATCH = "ERR_ESTOPPEL_BALANCE_MISMATCH"  # 422
ERR_DISPUTE_NOTE_REQUIRED = "ERR_DISPUTE_NOTE_REQUIRED"    # 422
ERR_VALIDATION = "ERR_VALIDATION"                          # 422
