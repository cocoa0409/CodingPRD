"""Authentication, endpoint-level and action-level RBAC (PRD 2.1, ladder steps 1-3)."""

from flask import request

from errors import fail

ROLES = ("ShopAdmin", "Planner", "Inspector", "ReliabilityEngineer", "Customer")

ALL_ROLES = list(ROLES)


def authenticate():
    """Ladder step 1 — headers present and role valid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'" % role)
    return str(user_id).strip(), role


def require_roles(role, allowed):
    """Ladder step 2 — endpoint-level authorisation."""
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint" % role)


def require_action_role(role, action, action_map):
    """Ladder step 3 — action-level authorisation.

    Only fires when the supplied action is a known discriminator value; an
    unknown or missing action falls through to the body-shape check (step 5).
    """
    if action in action_map and role not in action_map[action]:
        fail(
            "ERR_ACTION_NOT_PERMITTED_FOR_ROLE",
            "Role %s may not perform action %s" % (role, action),
        )


# Action-level permission map (PRD 2.1)
ORDER_ACTIONS = {
    "QUOTE": {"Planner", "ShopAdmin"},
    "SCHEDULE": {"Planner", "ShopAdmin"},
    "START": {"Planner", "ShopAdmin"},
    "COMPLETE": {"Planner", "ShopAdmin"},
    "DELIVER": {"Planner", "ShopAdmin"},
}

INSPECTION_ACTIONS = {
    "SUBMIT": {"Inspector"},
    "ACCEPT": {"Inspector", "ShopAdmin"},
    "RETURN": {"ReliabilityEngineer", "ShopAdmin"},
    "REOPEN": {"Inspector"},
}

PART_LINE_ACTIONS = {
    "SUBMIT": {"Planner", "ShopAdmin"},
    "REVISE": {"Planner", "ShopAdmin"},
}

CORE_UNIT_ACTIONS = {
    "REINSPECT": {"Inspector", "ShopAdmin"},
    "SCRAP": {"ShopAdmin"},
    "RETURN_AS_IS": {"ShopAdmin"},
}

RESERVATION_ACTIONS = {
    "CONFIRM": {"Planner", "ShopAdmin"},
    "RELEASE": {"Planner", "ShopAdmin"},
}

INSTALLATION_ACTIONS = {
    "RECORD_HOURS": {"ShopAdmin", "Customer"},
    "FAIL": {"ShopAdmin", "Customer"},
    "REMOVE": {"ShopAdmin"},
}

CLAIM_ACTIONS = {
    "REVIEW": {"ShopAdmin"},
    "REQUEST_INFO": {"ShopAdmin"},
    "ISSUE_CREDIT": {"ShopAdmin"},
    "RESUBMIT": {"Customer", "ShopAdmin"},
}
