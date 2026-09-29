"""Shared state guards used by the action endpoints (PRD §2.8 steps 7-9)."""

from errors import ApiError


def invalid_state(message=None):
    raise ApiError("ERR_INVALID_STATE", message)


def check_not_void(rating):
    """Step 8 — the rating reached from the target resource is not voided."""
    if rating is not None and rating["stage"] == "VOID":
        raise ApiError("ERR_RATING_VOID")


def check_not_locked(rating):
    """Step 9 — the rating reached from the target resource is not file-locked."""
    if rating is not None and rating["file_locked"]:
        raise ApiError("ERR_RATING_FILE_LOCKED")


def is_void(rating):
    return rating is not None and rating["stage"] == "VOID"
