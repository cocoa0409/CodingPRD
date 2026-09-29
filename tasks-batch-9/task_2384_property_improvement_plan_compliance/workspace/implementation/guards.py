"""Guard helpers shared across route modules, ordered per PRD section 2.6."""

from flask import g

import repo
from errors import ApiError


def resolve_body_fk(body, field, collection):
    """Band 2: resolve a body foreign key.  Absent/null defers to band 3."""
    if field not in body or body[field] is None:
        return None
    row = repo.find(collection, body[field])
    if row is None:
        raise ApiError(repo.NOT_FOUND[collection])
    return row


def require_owner(prop):
    """Band 8: every owner-side action must be the property's franchisee."""
    if g.user_id != prop["franchisee_id"]:
        raise ApiError(
            "ERR_NOT_PROPERTY_FRANCHISEE",
            "acting user is not the franchisee of the governing property",
        )


def require_franchise_not_terminated(prop):
    """Band 4: nothing new may be created against a terminated agreement."""
    if prop["franchise_agreement_status"] == "TERMINATED":
        raise ApiError(
            "ERR_FRANCHISE_TERMINATED",
            "the property's franchise agreement is terminated",
        )


def require_plan_draft(plan):
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", "the plan is no longer in DRAFT")


def require_execution_window(plan, statuses=("OWNER_ACKNOWLEDGED", "IN_EXECUTION")):
    if plan["status"] not in statuses:
        raise ApiError(
            "ERR_PLAN_NOT_IN_EXECUTION_WINDOW",
            "the plan is not inside its execution window",
        )


def require_state(row, field, allowed, error_id, message):
    if row[field] not in allowed:
        raise ApiError(error_id, message)


def require_assigned_inspector(inspection):
    if g.user_id != inspection["inspector_user_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_INSPECTOR",
            "acting user is not the inspector assigned to this inspection",
        )
