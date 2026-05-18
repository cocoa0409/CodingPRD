"""Common helpers for route handlers."""

from flask import request

from db import store
from errors import raise_error
from utils import to_decimal


def get_json_body():
    """Return JSON body as dict, accepting empty body as {}.

    Raises ERR_VALIDATION_FAILED if body is non-empty and not valid JSON or not an object.
    """
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_error("ERR_VALIDATION_FAILED", "request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION_FAILED", "request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise_error("ERR_VALIDATION_FAILED", f"missing required field '{name}'")
    return body[name]


def require_property(property_id):
    rec = store.properties.get(property_id)
    if rec is None:
        raise_error("ERR_NOT_FOUND", f"property '{property_id}' not found")
    return rec


def require_owner(owner_id):
    rec = store.owners.get(owner_id)
    if rec is None:
        raise_error("ERR_NOT_FOUND", f"owner '{owner_id}' not found")
    return rec


def require_hearing_officer(officer_id):
    rec = store.hearing_officers.get(officer_id)
    if rec is None:
        raise_error("ERR_NOT_FOUND", f"hearing officer '{officer_id}' not found")
    return rec


def require_assessment(property_id, assessment_id):
    require_property(property_id)
    rec = store.assessments.get(assessment_id)
    if rec is None or rec["property_id"] != property_id:
        raise_error("ERR_NOT_FOUND", f"assessment '{assessment_id}' not found")
    return rec


def require_appeal(property_id, appeal_id):
    require_property(property_id)
    rec = store.appeals.get(appeal_id)
    if rec is None or rec["property_id"] != property_id:
        raise_error("ERR_NOT_FOUND", f"appeal '{appeal_id}' not found")
    return rec


def require_exemption_application(property_id, app_id):
    require_property(property_id)
    rec = store.exemption_applications.get(app_id)
    if rec is None or rec["property_id"] != property_id:
        raise_error("ERR_NOT_FOUND", f"exemption application '{app_id}' not found")
    return rec


def require_tax_bill(property_id, bill_id):
    require_property(property_id)
    rec = store.tax_bills.get(bill_id)
    if rec is None or rec["property_id"] != property_id:
        raise_error("ERR_NOT_FOUND", f"tax bill '{bill_id}' not found")
    return rec


def require_deferral_plan(property_id, bill_id, plan_id):
    require_tax_bill(property_id, bill_id)
    rec = store.deferral_plans.get(plan_id)
    if rec is None or rec["tax_bill_id"] != bill_id:
        raise_error("ERR_NOT_FOUND", f"deferral plan '{plan_id}' not found")
    return rec


def check_version(record, body):
    """OCC check: if 'version' is in the body, compare against record's version."""
    if body is None:
        return
    if "version" not in body or body["version"] is None:
        return
    submitted = body["version"]
    if not isinstance(submitted, int) or isinstance(submitted, bool):
        raise_error("ERR_VALIDATION_FAILED", "version must be an integer")
    if submitted != record["version"]:
        raise_error("ERR_VERSION_MISMATCH")


def bump(record):
    record["updated_at"] = store.clock.now()
    record["version"] = record.get("version", 1) + 1


def parse_number(value, field_name):
    try:
        return to_decimal(value)
    except Exception:
        raise_error("ERR_VALIDATION_FAILED", f"'{field_name}' must be a number")
