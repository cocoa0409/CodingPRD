"""Domain error class and the full error-id catalogue (PRD §5 / scaffold §1.6).

Each error carries its exact error_id and the HTTP status from the PRD error
catalogue. error_ids and statuses are taken verbatim from the PRD — never
assumed.
"""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth ---
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"                    # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"        # 403

# --- existence (all 404) ---
ERR_CUSTOMER_NOT_FOUND = "ERR_CUSTOMER_NOT_FOUND"
ERR_CATALOG_NOT_FOUND = "ERR_CATALOG_NOT_FOUND"
ERR_CREW_NOT_FOUND = "ERR_CREW_NOT_FOUND"
ERR_PLAN_NOT_FOUND = "ERR_PLAN_NOT_FOUND"
ERR_JOB_NOT_FOUND = "ERR_JOB_NOT_FOUND"
ERR_ROOM_NOT_FOUND = "ERR_ROOM_NOT_FOUND"
ERR_ADDON_NOT_FOUND = "ERR_ADDON_NOT_FOUND"
ERR_INVOICE_NOT_FOUND = "ERR_INVOICE_NOT_FOUND"
ERR_CLAIM_NOT_FOUND = "ERR_CLAIM_NOT_FOUND"

# --- request validation ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"              # 422
ERR_EMAIL_TAKEN = "ERR_EMAIL_TAKEN"                      # 409
ERR_SERVICE_TYPE_TAKEN = "ERR_SERVICE_TYPE_TAKEN"        # 409

# --- state (all 409) ---
ERR_CUSTOMER_SUSPENDED = "ERR_CUSTOMER_SUSPENDED"
ERR_JOB_NOT_DRAFT = "ERR_JOB_NOT_DRAFT"
ERR_JOB_NOT_QUOTED = "ERR_JOB_NOT_QUOTED"
ERR_JOB_NOT_BOOKED = "ERR_JOB_NOT_BOOKED"
ERR_JOB_NOT_IN_PROGRESS = "ERR_JOB_NOT_IN_PROGRESS"
ERR_JOB_NOT_COMPLETED = "ERR_JOB_NOT_COMPLETED"
ERR_JOB_ALREADY_BILLED = "ERR_JOB_ALREADY_BILLED"
ERR_SLOT_NOT_RESERVED = "ERR_SLOT_NOT_RESERVED"
ERR_CLAIM_NOT_FILED = "ERR_CLAIM_NOT_FILED"
ERR_INVOICE_NOT_OPEN = "ERR_INVOICE_NOT_OPEN"

# --- business referential / safety / temporal (all 409) ---
ERR_NO_ROOMS = "ERR_NO_ROOMS"
ERR_SERVICE_TYPE_MISMATCH = "ERR_SERVICE_TYPE_MISMATCH"
ERR_CREW_UNAVAILABLE = "ERR_CREW_UNAVAILABLE"
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"
ERR_GUARANTEE_WINDOW_EXPIRED = "ERR_GUARANTEE_WINDOW_EXPIRED"
ERR_DUPLICATE_ADDON = "ERR_DUPLICATE_ADDON"

# --- fiscal ---
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                      # 402
ERR_INVOICE_HAS_PAYMENTS = "ERR_INVOICE_HAS_PAYMENTS"    # 409

# --- concurrency (OCC, all 412) ---
ERR_STALE_CREW_VERSION = "ERR_STALE_CREW_VERSION"
ERR_STALE_INVOICE_VERSION = "ERR_STALE_INVOICE_VERSION"


def err(error_id: str, http_status: int, message: str = "") -> APIError:
    return APIError(error_id, http_status, message)
