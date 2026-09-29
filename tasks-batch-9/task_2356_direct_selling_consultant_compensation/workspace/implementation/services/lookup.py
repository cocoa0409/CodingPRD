"""Reference resolution and the not-found catalogue (PRD section 2.9)."""

from db import db
from errors import ApiError

_TABLES = {
    "plan": ("plans", "ERR_PLAN_NOT_FOUND"),
    "jurisdiction": ("jurisdictions", "ERR_JURISDICTION_NOT_FOUND"),
    "product": ("products", "ERR_PRODUCT_NOT_FOUND"),
    "application": ("applications", "ERR_APPLICATION_NOT_FOUND"),
    "consultant": ("consultants", "ERR_CONSULTANT_NOT_FOUND"),
    "order": ("orders", "ERR_ORDER_NOT_FOUND"),
    "period": ("periods", "ERR_PERIOD_NOT_FOUND"),
    "qualification": ("qualifications", "ERR_QUALIFICATION_NOT_FOUND"),
    "run": ("runs", "ERR_RUN_NOT_FOUND"),
    "statement": ("statements", "ERR_STATEMENT_NOT_FOUND"),
    "buyback": ("buybacks", "ERR_BUYBACK_NOT_FOUND"),
    "case": ("cases", "ERR_CASE_NOT_FOUND"),
    "disclosure": ("disclosures", "ERR_DISCLOSURE_NOT_FOUND"),
}


def peek(kind, row_id):
    table, _ = _TABLES[kind]
    if not isinstance(row_id, str):
        return None
    return getattr(db, table).get(row_id)


def fetch(kind, row_id):
    row = peek(kind, row_id)
    if row is None:
        raise ApiError(_TABLES[kind][1])
    return row


def jurisdiction_by_state(state_code):
    for row in db.jurisdictions.values():
        if row["state_code"] == state_code:
            return row
    raise ApiError("ERR_JURISDICTION_NOT_FOUND")


def period_by_code(plan_id, period_code):
    for row in db.periods.values():
        if row["compensation_plan_id"] == plan_id and row["period_code"] == period_code:
            return row
    raise ApiError("ERR_PERIOD_NOT_FOUND")


def period_by_code_any(period_code):
    for row in db.periods.values():
        if row["period_code"] == period_code:
            return row
    return None
