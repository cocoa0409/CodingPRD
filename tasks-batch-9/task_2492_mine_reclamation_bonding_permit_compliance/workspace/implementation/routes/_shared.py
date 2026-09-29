"""Helpers shared by the route modules: list plumbing and the reusable
ladder steps (ownership, decision-reason coupling, permit admission sets)."""

import constants as C
from db import db, sort_rows
from errors import ApiError
from response import list_response, paginate
from validation import pagination, query_enum, query_string

READ_ALL = C.ALL_ROLES


def apply_filters(rows, filters):
    """filters: sequence of (query_param, row_field, allowed_values_or_None).

    Every declared parameter is validated even when it filters nothing out,
    because a malformed query string is a band-3 rejection.
    """
    for param, field, allowed in filters:
        if allowed is None:
            value = query_string(param)
        else:
            value = query_enum(param, allowed)
        if value is not None:
            rows = [row for row in rows if row[field] == value]
    return rows


def paged(rows, serializer):
    limit, offset = pagination()
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response([serializer(row) for row in page], total, limit, offset)


def paged_ordered(rows, serializer):
    """Pagination without the default created_at re-ordering."""
    limit, offset = pagination()
    page, total = paginate(list(rows), limit, offset)
    return list_response([serializer(row) for row in page], total, limit, offset)


def collection_filtered(rows, filters, serializer):
    return paged(apply_filters(list(rows), filters), serializer)


# --------------------------------------------------------------------------
# Band 6 — ownership
# --------------------------------------------------------------------------
def require_permit_operator(role, user_id, permit):
    if role == C.ROLE_OPERATOR and user_id != permit["operator_id"]:
        raise ApiError(
            "ERR_NOT_PERMIT_OPERATOR",
            "The acting user is not the operator of the targeted permit.",
        )


def require_assigned_inspector(role, user_id, inspection):
    if role == C.ROLE_INSPECTOR and user_id != inspection["inspector_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_INSPECTOR",
            "The acting user is not the inspector assigned to this inspection.",
        )


# --------------------------------------------------------------------------
# Band 9 / 10 — state admission
# --------------------------------------------------------------------------
def require_permit_status(permit, allowed):
    if permit["status"] not in allowed:
        raise ApiError(
            "ERR_PERMIT_STATE_INVALID",
            "Permit status %s does not admit this operation." % permit["status"],
        )


def require_state(row, field, allowed, error_id):
    if row[field] not in allowed:
        raise ApiError(
            error_id, "State %s does not admit this operation." % row[field]
        )


# --------------------------------------------------------------------------
# Band 13 — the decision / denial_reason coupling
# --------------------------------------------------------------------------
def precheck_denial_reason(body):
    """Band 3 only checks the declared type. Emptiness and the coupling with
    `decision` belong to band 13, so an empty reason on a DENY must surface as
    ERR_DECISION_REASON_REQUIRED rather than ERR_INVALID_REQUEST."""
    if "denial_reason" in body and body["denial_reason"] is not None:
        if not isinstance(body["denial_reason"], str):
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field 'denial_reason' must be a string."
            )


def check_decision_reason(decision, body):
    supplied = body.get("denial_reason")
    present = "denial_reason" in body and supplied is not None
    if decision == "DENY":
        if not present or not isinstance(supplied, str) or supplied.strip() == "":
            raise ApiError(
                "ERR_DECISION_REASON_REQUIRED",
                "A non-empty denial_reason is required when the decision is DENY.",
            )
        return supplied
    if present:
        raise ApiError(
            "ERR_DECISION_REASON_REQUIRED",
            "denial_reason must be absent unless the decision is DENY.",
        )
    return None


def permit_of(row):
    return db.permits[row["permit_id"]]
