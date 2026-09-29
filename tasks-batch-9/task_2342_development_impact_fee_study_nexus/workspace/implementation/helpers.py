"""Path identifier resolution, body parsing and query filter helpers."""

from flask import request

import db
from errors import raise_error
from util import Body

# Declared enum vocabularies, used by body and query validation.
LAND_USE_CATEGORIES = ("SINGLE_FAMILY", "MULTI_FAMILY", "RETAIL", "OFFICE", "INDUSTRIAL")
UNIT_BASES = ("PER_DWELLING", "PER_1000_SQFT")
METHODOLOGIES = ("PLAN_BASED", "STANDARD_BASED")
LOS_POLICIES = ("EXISTING_DEFICIENCY_EXCLUDED", "PLANNED_STANDARD_ALLOWED")
NOTICE_METHODS = ("NEWSPAPER", "WEBSITE", "MAILED")
STUDY_STATUSES = ("DRAFT", "NEXUS_CERTIFIED", "NOTICE_PUBLISHED", "PROTEST_CLEARED",
                  "ADOPTED", "EFFECTIVE", "SUPERSEDED")
ALLOCATION_STATUSES = ("PENDING", "VALID", "STALE")
SCHEDULE_STATUSES = ("VALID", "STALE")
PROTEST_STATUSES = ("RECORDED", "WITHDRAWN", "VOIDED")
ASSESSMENT_STATUSES = ("UNASSESSED", "ASSESSED", "REASSESSED")
COLLECTION_STATUSES = ("NOT_DUE", "DUE", "DEFERRED", "DELINQUENT", "PAID")
COLLECTION_TRIGGERS = ("PERMIT", "CERTIFICATE_OF_OCCUPANCY")
CLAIM_STATUSES = ("SUBMITTED", "APPROVED_FULL", "APPROVED_PARTIAL", "DENIED")
CREDIT_TYPES = ("DEVELOPER_IMPROVEMENT", "EXISTING_TAX_CONTRIBUTION")
VALUATION_METHODS = ("NOMINAL", "PRESENT_VALUE")
CLAIM_DECISIONS = ("APPROVE_FULL", "APPROVE_PARTIAL", "DENY")
AGREEMENT_STATUSES = ("REQUESTED", "EXECUTED", "DENIED", "SATISFIED", "DEFAULTED")
SECURITY_TYPES = ("CASH_BOND", "LETTER_OF_CREDIT", "LIEN")
AGREEMENT_DECISIONS = ("EXECUTE", "DENY")
LEDGER_KINDS = ("COLLECTION", "EXPENDITURE", "REFUND")
ENTRY_STATUSES = ("OPEN", "PARTIALLY_EXPENDED", "FULLY_EXPENDED", "REFUND_DUE",
                  "REFUNDED", "POSTED")
FUND_POSTURES = ("COMPLIANT", "AT_RISK", "REFUND_DUE")

CODE_PATTERN = r"[A-Z_]{2,12}"
JURISDICTION_PATTERN = r"[A-Z0-9]{2,10}"


# --------------------------------------------------------------------------- #
# Request body
# --------------------------------------------------------------------------- #


def json_body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return Body({})
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise_error("ERR_INVALID_REQUEST")
    return Body(data)


# --------------------------------------------------------------------------- #
# Path identifier resolution (PRD 2.7)
# --------------------------------------------------------------------------- #


def _resolve(table, identifier, error_id):
    record = table.get(identifier)
    if record is None:
        raise_error(error_id)
    return record


def get_program(identifier):
    return _resolve(db.fee_programs, identifier, "ERR_FEE_PROGRAM_NOT_FOUND")


def get_category(identifier):
    return _resolve(db.facility_categories, identifier, "ERR_FACILITY_CATEGORY_NOT_FOUND")


def get_study(identifier):
    return _resolve(db.fee_studies, identifier, "ERR_FEE_STUDY_NOT_FOUND")


def get_component(identifier):
    return _resolve(db.nexus_components, identifier, "ERR_NEXUS_COMPONENT_NOT_FOUND")


def get_application(identifier):
    return _resolve(db.development_applications, identifier,
                    "ERR_DEVELOPMENT_APPLICATION_NOT_FOUND")


def get_claim(identifier):
    return _resolve(db.credit_claims, identifier, "ERR_CREDIT_CLAIM_NOT_FOUND")


def get_agreement(identifier):
    return _resolve(db.deferral_agreements, identifier, "ERR_DEFERRAL_AGREEMENT_NOT_FOUND")


def get_filing(identifier):
    return _resolve(db.protest_filings, identifier, "ERR_PROTEST_FILING_NOT_FOUND")


def get_entry(identifier):
    return _resolve(db.fund_ledger_entries, identifier, "ERR_FUND_LEDGER_ENTRY_NOT_FOUND")


# --------------------------------------------------------------------------- #
# Query filters
# --------------------------------------------------------------------------- #


def arg_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def arg_enum(name, choices):
    value = arg_string(name)
    if value is None:
        return None
    if value not in choices:
        raise_error("ERR_INVALID_REQUEST")
    return value


def arg_bool(name):
    value = arg_string(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise_error("ERR_INVALID_REQUEST")


def arg_int(name, required=False):
    value = arg_string(name)
    if value is None:
        if required:
            raise_error("ERR_INVALID_REQUEST")
        return None
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        raise_error("ERR_INVALID_REQUEST")


def matches(record, filters):
    for field, expected in filters.items():
        if expected is None:
            continue
        if record.get(field) != expected:
            return False
    return True
