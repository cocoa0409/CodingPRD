"""Rungs 1-4 of the validation ladder: authentication, role gate, ownership."""
from flask import g, request

from errors import fail

ROLES = (
    "ProgramAdmin",
    "DistributorAgent",
    "CenterOperator",
    "PlantCounter",
    "AccountHolder",
    "RetailClerk",
)


def authenticate(*allowed_roles):
    """Rungs 1-3. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID") or ""
    role = request.headers.get("X-User-Role") or ""
    uid = uid.strip()
    role = role.strip()
    if not uid or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role does not name a recognised role.")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    g.user_id = uid
    g.role = role
    return uid, role


def narrow(action, program_admin_only=(), role_actions=None):
    """Action-level narrowing (rung 3). Refuses with ERR_UNAUTHORIZED."""
    role = g.role
    if action in program_admin_only and role != "ProgramAdmin":
        fail("ERR_UNAUTHORIZED", "Action %s is reserved to ProgramAdmin." % action)
    if role_actions:
        allowed = role_actions.get(role)
        if allowed is not None and action not in allowed:
            fail("ERR_UNAUTHORIZED", "Role %s may not request action %s." % (role, action))


def _forbid():
    fail("ERR_FORBIDDEN_RESOURCE", "The acting principal does not own this resource.")


def own(distributor_id=None, center_id=None, account_id=None, retailer_id=None):
    """Rung 4. Only the entity-backed role that matches the supplied kind is checked."""
    role = getattr(g, "role", None)
    uid = getattr(g, "user_id", None)
    if role == "DistributorAgent":
        if distributor_id is not None and distributor_id != uid:
            _forbid()
    elif role == "CenterOperator":
        if center_id is not None and center_id != uid:
            _forbid()
    elif role == "AccountHolder":
        if account_id is not None and account_id != uid:
            _forbid()
    elif role == "RetailClerk":
        if retailer_id is not None and retailer_id != uid:
            _forbid()


def own_visit(visit):
    own(center_id=visit.get("center_id"), retailer_id=visit.get("retailer_id"),
        account_id=visit.get("account_id"))


def own_machine(machine):
    own(center_id=machine.get("center_id"))


def own_bag_drop(bag):
    own(center_id=bag.get("center_id"), account_id=bag.get("account_id"))


def own_batch(batch):
    own(center_id=batch.get("center_id"))


def own_product(product):
    own(distributor_id=product.get("distributor_id"))
