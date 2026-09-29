"""Authentication, role authorization and plant/order ownership (PRD 2.1, 2.8)."""

from flask import g, request

from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "CorporateOps",
    "PlantOperator",
    "QualityEngineer",
    "CertificationOfficer",
    "EnvironmentalCompliance",
    "ChannelManager",
    "ChannelBuyer",
)


def authenticate(allowed_roles):
    """Ladder rungs 1 and 2: authentication then authorization."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "%s header is required" % USER_ID_HEADER)
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "%s header is required" % USER_ROLE_HEADER)
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHORIZED", "unknown role %s" % role)
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def actor():
    return g.user_id


def role():
    return g.user_role


def require_plant_owned(plant_id):
    """Ladder rung 4.  A PlantOperator's X-User-ID *is* the Plant id."""
    if g.user_role == "PlantOperator" and str(plant_id) != str(g.user_id):
        fail("ERR_PLANT_NOT_OWNED", "plant %s is not owned by this operator" % plant_id)


def require_order_owned(order):
    """Ladder rung 4 for the ChannelBuyer cancelling its own order."""
    if g.user_role == "ChannelBuyer" and str(order.get("placed_by_user_id")) != str(g.user_id):
        fail("ERR_ORDER_NOT_OWNED", "order %s was not placed by this buyer" % order.get("id"))
