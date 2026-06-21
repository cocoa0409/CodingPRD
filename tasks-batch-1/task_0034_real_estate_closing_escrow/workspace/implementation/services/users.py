"""User registration (immutable)."""
from __future__ import annotations

from typing import Any

from clock import CLOCK
from db import DB_INSTANCE, new_id
from errors import ERR_INVALID_REQUEST, err
from validation import require_enum, require_fields, require_str


USER_ROLES = {"EscrowOfficer", "TitleAgent", "ComplianceOfficer"}


def create_user(body: dict) -> dict:
    require_fields(body, ["full_name", "role"])
    full_name = require_str(body, "full_name")
    role = require_enum(body, "role", USER_ROLES)
    u = {
        "id": new_id(),
        "created_at": CLOCK.now(),
        "role": role,
        "full_name": full_name,
    }
    DB_INSTANCE.users[u["id"]] = u
    return u


def list_users(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.users.values())
    if filters.get("role"):
        items = [u for u in items if u["role"] == filters["role"]]
    items.sort(key=lambda u: u["created_at"])
    return items
