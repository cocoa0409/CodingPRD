"""Domain error classes and the error-ID catalog (PRD §5 / SCAFFOLD §1.6)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---- error_id constants (exact strings from the scaffold catalog) -----------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                      # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_CROSS_ENTITY_STATE = "ERR_CROSS_ENTITY_STATE"    # 409
ERR_STACKING_VIOLATION = "ERR_STACKING_VIOLATION"    # 409
ERR_SLOT_OCCUPIED = "ERR_SLOT_OCCUPIED"              # 409
ERR_BERTH_DRAFT_EXCEEDED = "ERR_BERTH_DRAFT_EXCEEDED"    # 409
ERR_BERTH_LENGTH_EXCEEDED = "ERR_BERTH_LENGTH_EXCEEDED"  # 409
ERR_BERTH_CLOSED = "ERR_BERTH_CLOSED"                # 409
ERR_BERTH_CONFLICT = "ERR_BERTH_CONFLICT"            # 409
ERR_GATE_SLOT_CONFLICT = "ERR_GATE_SLOT_CONFLICT"    # 409
ERR_OUTSIDE_WINDOW = "ERR_OUTSIDE_WINDOW"            # 409
ERR_NO_SHOW_CAP = "ERR_NO_SHOW_CAP"                  # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412


def err(error_id: str, http_status: int, message: str = "") -> APIError:
    return APIError(error_id, http_status, message)
