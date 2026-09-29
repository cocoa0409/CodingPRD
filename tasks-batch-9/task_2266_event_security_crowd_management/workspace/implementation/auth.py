"""Authentication headers, endpoint RBAC and per-action authority (PRD 2.1, 2.5)."""

from flask import request

from db import db
from errors import ApiError

ROLES = (
    "SecurityDirector",
    "RiskAnalyst",
    "StaffingCoordinator",
    "CredentialAuditor",
    "PostSupervisor",
    "IncidentCommander",
    "SubcontractorLiaison",
    "SystemOperator",
)

ALL_ROLES = set(ROLES)

# Per-action authority map (PRD 2.1). Only the endpoints listed at rank 3 of the
# judgment order consult this map.
ACTION_ROLES = {
    "risk_decision": {
        "SUBMIT": {"RiskAnalyst"},
        "REVISE": {"RiskAnalyst"},
        "APPROVE": {"SecurityDirector"},
        "REJECT": {"SecurityDirector"},
    },
    "plan_lifecycle": {
        "PUBLISH": {"StaffingCoordinator"},
        "RECALL": {"StaffingCoordinator"},
        "ACTIVATE": {"SecurityDirector"},
        "LOCK": {"SecurityDirector"},
        "CLOSE": {"SecurityDirector"},
    },
    "duty_events": {
        "CONFIRM": {"StaffingCoordinator"},
        "CANCEL": {"StaffingCoordinator"},
        "BRIEF": {"PostSupervisor"},
        "CHECK_IN": {"PostSupervisor"},
        "MARK_NO_SHOW": {"PostSupervisor"},
        "RELIEVE": {"PostSupervisor"},
    },
    "cred_verification": {
        "SUBMIT_FOR_REVIEW": {"StaffingCoordinator", "SubcontractorLiaison"},
        "VERIFY": {"CredentialAuditor"},
        "REJECT": {"CredentialAuditor"},
        "DISQUALIFY": {"CredentialAuditor"},
    },
    "review_decision": {
        "SUBMIT": {"IncidentCommander"},
        "REVISE": {"IncidentCommander"},
        "RETURN": {"SecurityDirector"},
        "FINALIZE": {"SecurityDirector"},
    },
}


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_supervisor(self):
        return self.role == "PostSupervisor"

    @property
    def is_liaison(self):
        return self.role == "SubcontractorLiaison"


def authenticate(allowed_roles):
    """Rank 1 (headers present) then rank 2 (role permitted on this endpoint)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role '%s' may not access this endpoint." % role,
        )
    return Actor(user_id, role)


def require_action(payload, group):
    """Rank 4/5: the action must be recognised, then permitted for the role."""
    raw = payload.get("action")
    table = ACTION_ROLES[group]
    if raw is None or not isinstance(raw, str) or raw.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field 'action' is required.")
    if raw not in table:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'action' must be one of %s." % ", ".join(sorted(table)),
        )
    return raw


def check_action_authority(actor, group, action):
    allowed = ACTION_ROLES[group][action]
    if actor.role not in allowed:
        raise ApiError(
            "ERR_ACTION_NOT_PERMITTED_FOR_ROLE",
            "Role '%s' may not perform action '%s'." % (actor.role, action),
        )


def plain_action(payload, allowed_actions):
    """Action parsing for endpoints whose authority is endpoint-level only."""
    raw = payload.get("action")
    if raw is None or not isinstance(raw, str) or raw.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field 'action' is required.")
    if raw not in allowed_actions:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'action' must be one of %s." % ", ".join(sorted(allowed_actions)),
        )
    return raw


def acting_guard(actor):
    """For PostSupervisor, X-User-ID must resolve to a Guard (PRD 2.1)."""
    guard = db.guards.get(actor.user_id)
    if guard is None:
        raise ApiError("ERR_GUARD_NOT_FOUND", "The acting supervisor is not a known guard.")
    return guard


def check_supervisor_standing(actor, assignment, post, plan):
    """A PostSupervisor must own the assignment or hold a CONFIRMED SUPERVISOR post."""
    if assignment.get("guard_id") == actor.user_id:
        return
    if plan is not None:
        supervisor_post_ids = set()
        for candidate in db.posts.values():
            if (
                candidate.get("staffing_plan_id") == plan["id"]
                and candidate.get("post_type") == "SUPERVISOR"
            ):
                supervisor_post_ids.add(candidate["id"])
        if supervisor_post_ids:
            for other in db.assignments.values():
                if (
                    other.get("guard_id") == actor.user_id
                    and other.get("assignment_status") == "CONFIRMED"
                    and other.get("post_id") in supervisor_post_ids
                ):
                    return
    raise ApiError(
        "ERR_NOT_POST_SUPERVISOR",
        "The acting guard does not supervise this assignment's plan.",
    )
