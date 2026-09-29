"""Path- and body-level existence checks (ranks 3 and 7 of the PRD 2.9 ladder)."""

from flask import request

from db import db, ordered
from errors import ApiError


def _find(collection, row_id, error_id, label):
    if not isinstance(row_id, str):
        raise ApiError(error_id, "%s not found." % label)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, "%s '%s' not found." % (label, row_id))
    return row


def get_vendor(row_id):
    return _find(db.vendors, row_id, "ERR_VENDOR_NOT_FOUND", "Vendor")


def get_item(row_id):
    return _find(db.items, row_id, "ERR_ITEM_NOT_FOUND", "Catalog item")


def get_spec(row_id):
    return _find(db.specs, row_id, "ERR_SPEC_NOT_FOUND", "Measurement specification")


def get_chart(row_id):
    return _find(db.charts, row_id, "ERR_CHART_NOT_FOUND", "Size chart")


def get_mapping(row_id):
    return _find(db.mappings, row_id, "ERR_MAPPING_NOT_FOUND", "Size chart mapping")


def get_customer(row_id):
    return _find(db.customers, row_id, "ERR_CUSTOMER_PROFILE_NOT_FOUND",
                 "Customer profile")


def get_policy(row_id):
    return _find(db.policies, row_id, "ERR_POLICY_NOT_FOUND", "Return policy")


def get_order_line(row_id):
    return _find(db.order_lines, row_id, "ERR_ORDER_LINE_NOT_FOUND", "Order line")


def get_return_case(row_id):
    return _find(db.return_cases, row_id, "ERR_RETURN_CASE_NOT_FOUND", "Return case")


def get_feedback(row_id):
    return _find(db.feedback, row_id, "ERR_FEEDBACK_NOT_FOUND", "Fit feedback")


def get_intervention(row_id):
    return _find(db.interventions, row_id, "ERR_INTERVENTION_NOT_FOUND", "Intervention")


def get_deployment(row_id):
    return _find(db.deployments, row_id, "ERR_DEPLOYMENT_NOT_FOUND", "Deployment")


def ensure_not_delisted(item):
    """Rank 9: ten operations refuse to touch a DELISTED item."""
    if item["listing_status"] == "DELISTED":
        raise ApiError("ERR_ITEM_DELISTED",
                       "Catalog item '%s' is DELISTED." % item["id"])
    return item


def filtered(rows, filter_spec):
    """Additive equality filters read from the query string."""
    args = request.args
    result = []
    for row in rows:
        keep = True
        for param, key in filter_spec.items():
            wanted = args.get(param)
            if wanted is None:
                continue
            if row.get(key) != wanted:
                keep = False
                break
        if keep:
            result.append(row)
    return ordered(result)
