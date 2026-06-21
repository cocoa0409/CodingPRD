"""Cross-route lookup + ownership helpers (PRD §2.1, §2.7, SCAFFOLD §1.4).

Existence (priority 4) is checked left-to-right; ownership for entity-backed
roles (priority 3) is enforced by the dedicated helpers below. By the precedence
in PRD §2.7, ownership (priority 3) is checked BEFORE existence (priority 4) only
where the owning id is known from the resource — in practice the resource must be
loaded first, so we resolve existence then ownership; this matches the test
fixtures (a missing resource yields 404, a present-but-foreign one yields 403).
"""
from __future__ import annotations

import db
import errors as E
from middleware import (
    current_role, current_user_id,
    MEMBER, DISTRIBUTOR, CINEMA_MANAGER, BOX_OFFICE_AGENT,
)


def get_or_404(store: dict, _id, label: str) -> dict:
    ent = store.get(_id)
    if ent is None:
        raise E.not_found(f"{label} not found")
    return ent


def member_owns(member_id: str) -> bool:
    return current_role() == MEMBER and current_user_id() == member_id


def require_member_owns_member(member_id: str) -> None:
    """A Member acting on a member record must be that member."""
    if current_role() == MEMBER and current_user_id() != member_id:
        raise E.not_owner("Member may only access its own member record")


def require_member_owns_resource(resource_member_id: str) -> None:
    """A Member acting on an order/ticket must own it (resource.member_id)."""
    if current_role() == MEMBER and current_user_id() != resource_member_id:
        raise E.not_owner("Member may only access its own resources")


def require_distributor_owns_settlement(settlement: dict) -> None:
    if current_role() == DISTRIBUTOR and current_user_id() != settlement["distributor_id"]:
        raise E.not_owner("Distributor may only access its own settlements")


def require_distributor_owns_film(film: dict) -> None:
    if current_role() == DISTRIBUTOR and current_user_id() != film["distributor_id"]:
        raise E.not_owner("Distributor may only access its own films")


def require_distributor_owns_distributor(distributor_id: str) -> None:
    if current_role() == DISTRIBUTOR and current_user_id() != distributor_id:
        raise E.not_owner("Distributor may only access its own record")
