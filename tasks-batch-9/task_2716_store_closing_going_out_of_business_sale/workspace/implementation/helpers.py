"""Shared route plumbing: existence resolution, pagination and posture gates."""

import calc
import db
import response
from errors import ApiError

NOT_FOUND = {
    "jurisdictions": "ERR_JURISDICTION_NOT_FOUND",
    "engagements": "ERR_ENGAGEMENT_NOT_FOUND",
    "stores": "ERR_STORE_NOT_FOUND",
    "lots": "ERR_INVENTORY_LOT_NOT_FOUND",
    "consignments": "ERR_CONSIGNMENT_NOT_FOUND",
    "stages": "ERR_MARKDOWN_STAGE_NOT_FOUND",
    "licenses": "ERR_LICENSE_NOT_FOUND",
    "employees": "ERR_EMPLOYEE_NOT_FOUND",
    "sales_days": "ERR_SALES_DAY_NOT_FOUND",
    "expense_items": "ERR_EXPENSE_ITEM_NOT_FOUND",
    "leases": "ERR_LEASE_DISPOSITION_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
}


def require(table, row_id):
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[table])
    return row


def paginate(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset : offset + limit]
    return response.ok_list([serializer(row) for row in window], limit, offset, total)


# ------------------------------------------------------------ posture gates

def posture(engagement):
    return calc.compliance_posture(engagement["compliance_strike_count"])


def deny_frozen(engagement):
    if posture(engagement) == "FROZEN":
        raise ApiError("ERR_ENGAGEMENT_COMPLIANCE_FROZEN")


def deny_restricted(engagement):
    if posture(engagement) == "RESTRICTED":
        raise ApiError("ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED")


# -------------------------------------------------------------- state gates

def store_open_for_children(store):
    """PRD 2.11 step 10: a child of a store needs a store that has not shut."""
    if store["store_status"] in ("CLOSED", "SURRENDERED"):
        raise ApiError("ERR_STORE_STATE_INVALID")


def engagement_not_closed(engagement):
    if engagement["engagement_status"] == "CLOSED":
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")


def engagement_money_open(engagement):
    """A money-bearing engagement child needs ACTIVE or WIND_DOWN."""
    if engagement["engagement_status"] not in ("ACTIVE", "WIND_DOWN"):
        raise ApiError("ERR_ENGAGEMENT_STATE_INVALID")


def engagement_of_store(store):
    return db.get("engagements", store["engagement_id"])


def jurisdiction_of_store(store):
    return db.get("jurisdictions", store["jurisdiction_id"])
