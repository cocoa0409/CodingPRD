"""Request-shape validation (band 6), enum membership (band 7), path/FK resolution
(bands 4-5) and optimistic concurrency (band 11).  See PRD 2.5 for the ordering.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import clock
import store
from errors import ApiError

_MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION_FAILED", "Request body must be a JSON object.")
    return data


def fail(field=None):
    if field:
        raise ApiError("ERR_VALIDATION_FAILED", "Field '%s' is invalid." % field)
    raise ApiError("ERR_VALIDATION_FAILED")


def require_present(data, keys):
    """Band 6, first pass: every required field must be present and non-null."""
    for key in keys:
        if data.get(key, _MISSING) is _MISSING or data.get(key) is None:
            raise ApiError("ERR_VALIDATION_FAILED", "Field '%s' is required." % key)


def has(data, key):
    return data.get(key, _MISSING) is not _MISSING and data.get(key) is not None


def as_str(data, key, min_len=None, max_len=None):
    value = data.get(key)
    if not isinstance(value, str):
        fail(key)
    if min_len is not None and len(value) < min_len:
        fail(key)
    if max_len is not None and len(value) > max_len:
        fail(key)
    return value


def as_state_code(data, key):
    value = as_str(data, key, 2, 2)
    if not value.isalpha() or value != value.upper():
        fail(key)
    return value


def as_int(data, key, low=None, high=None):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except (TypeError, ValueError):
                fail(key)
        elif isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            fail(key)
    if low is not None and value < low:
        fail(key)
    if high is not None and value > high:
        fail(key)
    return value


def as_bool(data, key):
    value = data.get(key)
    if not isinstance(value, bool):
        fail(key)
    return value


def as_decimal(data, key, low=None, high=None):
    value = data.get(key)
    if isinstance(value, bool):
        fail(key)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(str(value))
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            fail(key)
    else:
        fail(key)
    if not number.is_finite():
        fail(key)
    if low is not None and number < Decimal(str(low)):
        fail(key)
    if high is not None and number > Decimal(str(high)):
        fail(key)
    return number


def as_date(data, key):
    value = clock.parse_date(data.get(key))
    if value is None:
        fail(key)
    return value


def as_instant(data, key):
    value = clock.parse_instant(data.get(key))
    if value is None:
        fail(key)
    return value


def as_enum(data, key, allowed):
    """Band 7: membership.  Presence must already have been checked in band 6."""
    value = data.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM_VALUE", "Field '%s' is not a permitted value." % key)
    return value


def as_enum_list(data, key, allowed):
    value = data.get(key)
    if not isinstance(value, list):
        fail(key)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise ApiError(
                "ERR_INVALID_ENUM_VALUE",
                "Field '%s' contains a value that is not permitted." % key)
    seen = []
    for item in value:
        if item not in seen:
            seen.append(item)
    return seen


def as_str_list(data, key, max_len=None):
    value = data.get(key)
    if not isinstance(value, list):
        fail(key)
    for item in value:
        if not isinstance(item, str):
            fail(key)
        if max_len is not None and len(item) > max_len:
            fail(key)
    return list(value)


def as_client_history(data, key):
    """prior_engagement_team_clients: objects of {client_name, exit_date}."""
    value = data.get(key)
    if not isinstance(value, list):
        fail(key)
    parsed = []
    for item in value:
        if not isinstance(item, dict):
            fail(key)
        name = item.get("client_name")
        exit_date = clock.parse_date(item.get("exit_date"))
        if not isinstance(name, str) or not name or exit_date is None:
            fail(key)
        parsed.append({"client_name": name, "exit_date": item["exit_date"]})
    return parsed


# --------------------------------------------------------------------------- #
# Bands 4-5: path and body foreign-key resolution
# --------------------------------------------------------------------------- #

def need(collection, row_id, error_id):
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def need_firm(firm_id):
    return need(store.FIRMS, firm_id, "ERR_FIRM_NOT_FOUND")


def need_partner(partner_id):
    return need(store.PARTNERS, partner_id, "ERR_PARTNER_NOT_FOUND")


def need_engagement(engagement_id):
    return need(store.ENGAGEMENTS, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")


def need_risk(risk_id):
    return need(store.QUALITY_RISKS, risk_id, "ERR_QUALITY_RISK_NOT_FOUND")


def need_response(response_id):
    return need(store.RISK_RESPONSES, response_id, "ERR_RISK_RESPONSE_NOT_FOUND")


def need_review(eqr_id):
    return need(store.QUALITY_REVIEWS, eqr_id, "ERR_QUALITY_REVIEW_NOT_FOUND")


def need_inspection(inspection_id):
    return need(store.INSPECTIONS, inspection_id, "ERR_INSPECTION_NOT_FOUND")


def need_selection(selection_id):
    return need(
        store.INSPECTION_SELECTIONS, selection_id, "ERR_INSPECTION_SELECTION_NOT_FOUND")


def need_finding(finding_id):
    return need(store.FINDINGS, finding_id, "ERR_FINDING_NOT_FOUND")


def need_rca(rca_id):
    return need(store.RCAS, rca_id, "ERR_RCA_NOT_FOUND")


def need_plan(plan_id):
    return need(store.PLANS, plan_id, "ERR_REMEDIATION_PLAN_NOT_FOUND")


def need_reviewer(reviewer_id):
    return need(store.PEER_REVIEWERS, reviewer_id, "ERR_PEER_REVIEWER_NOT_FOUND")


def need_peer_review(peer_review_id):
    return need(store.PEER_REVIEWS, peer_review_id, "ERR_PEER_REVIEW_NOT_FOUND")


def need_pr_selection(selection_id):
    return need(
        store.PR_SELECTIONS, selection_id, "ERR_PEER_REVIEW_SELECTION_NOT_FOUND")


def need_cap(cap_id):
    return need(store.CAPS, cap_id, "ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND")


# --------------------------------------------------------------------------- #
# Band 11: optimistic concurrency
# --------------------------------------------------------------------------- #

def check_version(data, key, row):
    """When the expected-version field is supplied it must equal the parent's current
    version, otherwise ERR_STALE_VERSION (412).  Omitted means skip the check."""
    if not has(data, key):
        return
    expected = as_int(data, key)
    if expected != row["version"]:
        raise ApiError("ERR_STALE_VERSION")
