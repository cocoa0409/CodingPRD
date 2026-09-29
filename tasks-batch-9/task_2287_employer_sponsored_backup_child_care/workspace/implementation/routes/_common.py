"""Route-layer helpers shared by every blueprint."""

from flask import request

from errors import ApiError
from util import parse_date_value


def need(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def qs_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST")
    return raw


def qs_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST")
    return raw


def qs_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw in ("true", "True", "TRUE", "1"):
        return True
    if raw in ("false", "False", "FALSE", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST")


def qs_date(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    parse_date_value(raw)
    return raw


def keep(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


CARE_MODES = ("CENTER_BASED", "IN_HOME")
REQUESTED_CARE_MODES = ("CENTER_BASED", "IN_HOME", "EITHER")
CONTRACT_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATED")
INVOICING_CYCLES = ("MONTHLY", "QUARTERLY")
PLAN_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")
EMPLOYMENT_STATUSES = ("ACTIVE", "LEAVE", "TERMINATED")
ELIGIBILITY_STATUSES = ("ELIGIBLE", "RESTRICTED", "INELIGIBLE")
DEPENDENT_TYPES = ("CHILD", "ADULT_ELDER")
DEPENDENT_STATUSES = ("ACTIVE", "INACTIVE")
NETWORK_STATUSES = (
    "PENDING",
    "CREDENTIALED",
    "PROBATION",
    "SUSPENDED",
    "DEPROVISIONED",
)
CREDENTIAL_TYPES = ("LICENSE", "BACKGROUND_CHECK", "CPR", "INSURANCE")
CREDENTIAL_STATUSES = ("VALID", "EXPIRED", "REVOKED")
BLOCK_STATUSES = ("OPEN", "FULL", "CLOSED")
FULFILLMENT_STATUSES = (
    "INTAKE",
    "MATCHING",
    "OFFERED",
    "CONFIRMED",
    "IN_SERVICE",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
    "UNFULFILLED",
)
BILLING_STATUSES = ("NOT_BILLABLE", "ACCRUED", "INVOICED", "PAID")
OFFER_STATUSES = ("PROPOSED", "SELECTED", "REJECTED", "EXPIRED")
LEDGER_ENTRY_TYPES = (
    "RESERVE",
    "COMMIT",
    "RELEASE",
    "OVERAGE_ACCRUE",
    "OVERAGE_REVERSE",
    "NO_SHOW_CHARGE",
    "LATE_CANCEL_CHARGE",
)
INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "VOID")
LINE_TYPES = ("CARE_COPAY", "CARE_OVERAGE", "NO_SHOW_CHARGE", "LATE_CANCEL_CHARGE")
SEVERITIES = ("MINOR", "MODERATE", "SEVERE")
CATEGORIES = ("SUPERVISION", "FACILITY", "MEDICAL", "CONDUCT", "DOCUMENTATION")
INCIDENT_STATUSES = ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")
QA_ACTIONS = ("NONE", "PROBATION", "SUSPENSION", "DEPROVISION")
