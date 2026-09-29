"""Shared route helpers: path resolution, scoping, list plumbing."""

from flask import request

import auth
import store
from errors import fail
from validate import pagination, window

PREFIX = "/correspondent-banking"

NOT_FOUND = {
    "respondents": "ERR_RESPONDENT_NOT_FOUND",
    "jurisdictions": "ERR_JURISDICTION_PROFILE_NOT_FOUND",
    "owners": "ERR_BENEFICIAL_OWNER_NOT_FOUND",
    "questionnaires": "ERR_QUESTIONNAIRE_NOT_FOUND",
    "control_assessments": "ERR_CONTROL_ASSESSMENT_NOT_FOUND",
    "nested": "ERR_NESTED_RELATIONSHIP_NOT_FOUND",
    "profiles": "ERR_MONITORING_PROFILE_NOT_FOUND",
    "observations": "ERR_ACTIVITY_OBSERVATION_NOT_FOUND",
    "alerts": "ERR_MONITORING_ALERT_NOT_FOUND",
    "rfis": "ERR_INFORMATION_REQUEST_NOT_FOUND",
    "media": "ERR_ADVERSE_MEDIA_EVENT_NOT_FOUND",
    "refreshes": "ERR_PERIODIC_REFRESH_NOT_FOUND",
    "payments": "ERR_PAYMENT_INSTRUCTION_NOT_FOUND",
    "plans": "ERR_CLOSURE_PLAN_NOT_FOUND",
}


def need(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        fail(NOT_FOUND[collection], "%s does not resolve." % collection)
    return row


def need_respondent(respondent_id):
    return need("respondents", respondent_id)


def start(allowed_roles, respondent_id=None):
    """Priorities 1, 2 and (for a path-supplied respondent id) 3."""
    ctx = auth.authenticate(allowed_roles)
    if respondent_id is not None:
        auth.scope(ctx, respondent_id)
    return ctx


def respondent_of(collection, row):
    """The owning respondent id for any child row, following the chain."""
    if collection in ("respondents",):
        return row["id"]
    if "respondent_bank_id" in row:
        return row["respondent_bank_id"]
    if collection == "control_assessments":
        parent = store.get("questionnaires", row["questionnaire_id"])
        return parent["respondent_bank_id"] if parent else None
    if collection == "observations":
        parent = store.get("profiles", row["monitoring_profile_id"])
        return parent["respondent_bank_id"] if parent else None
    return None


def scoped_child(collection, row_id, ctx):
    """Resolve a child row then apply the RespondentContact scope check."""
    row = need(collection, row_id)
    if ctx.is_contact:
        auth.scope(ctx, respondent_of(collection, row))
    return row


def list_scope(ctx, args_key="respondent_bank_id"):
    """The respondent filter a list read must apply for the acting role."""
    wanted = request.args.get(args_key)
    if ctx.is_contact:
        if wanted is not None and wanted != ctx.user_id:
            fail("ERR_RESPONDENT_SCOPE_VIOLATION",
                 "This respondent contact may only list its own rows.")
        return ctx.user_id
    return wanted


def paged(rows):
    limit, offset = pagination()
    page, total = window(rows, limit, offset)
    return page, limit, offset, total


def arg(name):
    value = request.args.get(name)
    return value if value not in ("",) else None


def eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def eq_bool(rows, field, raw):
    if raw is None:
        return rows
    want = raw.strip().lower() in ("true", "1", "yes")
    return [r for r in rows if bool(r.get(field)) is want]


ALL = auth.ALL_ROLES
OPS = auth.OPERATOR_ROLES
