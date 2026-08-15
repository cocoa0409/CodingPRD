"""Cross-cutting gate helpers used by multiple route modules."""

import db
from errors import ApiError, ERR_PROJECT_NOT_ACTIVE, ERR_NOT_PROJECT_COUNTERPARTY


def require_project_active(project: dict, allow_substantial: bool = False):
    allowed = ("ACTIVE", "SUBSTANTIAL_COMPLETION_ACHIEVED") if allow_substantial else ("ACTIVE",)
    if project["status"] not in allowed:
        raise ApiError(
            ERR_PROJECT_NOT_ACTIVE,
            "Operation requires the project in ACTIVE"
            + (" or SUBSTANTIAL_COMPLETION_ACHIEVED" if allow_substantial else ""),
            409,
        )


def check_counterparty(role: str, user_id: str, project: dict):
    """Counterparty ownership for Contractor/Owner writes (priority 6)."""
    if role == "Contractor" and user_id != project["contractor_user_id"]:
        raise ApiError(
            ERR_NOT_PROJECT_COUNTERPARTY,
            "Contractor write where X-User-ID does not match the project's contractor_user_id",
            403,
        )
    if role == "Owner" and user_id != project["owner_user_id"]:
        raise ApiError(
            ERR_NOT_PROJECT_COUNTERPARTY,
            "Owner write where X-User-ID does not match the project's owner_user_id",
            403,
        )
