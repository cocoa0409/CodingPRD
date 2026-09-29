"""Shared route helpers: referential lookups and collection filters."""
from flask import request

import db
from errors import ApiError
from services.compliance import in_window
from validation import query_bool, query_ts

API_PREFIX = "/repair-program"


def get_model(model_id):
    row = db.db.models.get(model_id)
    if row is None:
        raise ApiError("ERR_MODEL_NOT_FOUND")
    return row


def get_part(part_id, error_id="ERR_PART_NOT_FOUND"):
    row = db.db.parts.get(part_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_compat(compatibility_id):
    row = db.db.compats.get(compatibility_id)
    if row is None:
        raise ApiError("ERR_COMPATIBILITY_NOT_FOUND")
    return row


def get_revision(revision_id):
    row = db.db.revisions.get(revision_id)
    if row is None:
        raise ApiError("ERR_MANUAL_REVISION_NOT_FOUND")
    return row


def get_assessment(assessment_id):
    row = db.db.assessments.get(assessment_id)
    if row is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND")
    return row


def get_order(order_id):
    row = db.db.orders.get(order_id)
    if row is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    return row


def get_line(line_id, order_id=None):
    row = db.db.lines.get(line_id)
    if row is None:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND")
    if order_id is not None and row["order_id"] != order_id:
        # Nesting is an ownership assertion (PRD 2.8).
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND")
    return row


def get_ack(acknowledgment_id):
    row = db.db.acks.get(acknowledgment_id)
    if row is None:
        raise ApiError("ERR_ACKNOWLEDGMENT_NOT_FOUND")
    return row


def get_provider(provider_id):
    row = db.db.providers.get(provider_id)
    if row is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND")
    return row


def get_cert(certification_id):
    row = db.db.certs.get(certification_id)
    if row is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND")
    return row


def get_case(case_id):
    row = db.db.cases.get(case_id)
    if row is None:
        raise ApiError("ERR_RETURN_CASE_NOT_FOUND")
    return row


def get_obligation(obligation_id):
    row = db.db.obligations.get(obligation_id)
    if row is None:
        raise ApiError("ERR_OBLIGATION_NOT_FOUND")
    return row


def find_profile(region_code):
    for row in db.ordered(db.db.profiles.all()):
        if row["region_code"] == region_code:
            return row
    raise ApiError("ERR_REGION_PROFILE_NOT_FOUND")


def profile_or_none(region_code):
    for row in db.ordered(db.db.profiles.all()):
        if row["region_code"] == region_code:
            return row
    return None


def obligation_for(model_id, region_code):
    for row in db.ordered(db.db.obligations.all()):
        if row["model_id"] == model_id and row["region_code"] == region_code:
            return row
    return None


# --------------------------------------------------------------------------
# collection filters
# --------------------------------------------------------------------------

def filter_eq(rows, field, argname=None):
    value = request.args.get(argname or field)
    if value is None or value == "":
        return rows
    return [r for r in rows if r.get(field) == value]


def filter_bool(rows, field):
    value = query_bool(field)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) is value]


def filter_as_of_date(rows):
    at = query_ts("as_of_date")
    if at is None:
        return rows
    return [r for r in rows if in_window(r, at)]
