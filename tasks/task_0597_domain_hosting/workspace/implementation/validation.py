"""Request-shape validation (priority 3 -> ERR_INVALID_REQUEST) and lookups."""

import re

from flask import request

import config
import db
from errors import ApiError

DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9-]{1,63}$")


def bad(message="The request is malformed."):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def has(data, name):
    return name in data and data[name] is not None


def req_str(data, name, allow_empty=False):
    value = data.get(name)
    if not isinstance(value, str) or (not allow_empty and value == ""):
        raise bad("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(data, name, default=None, allow_empty=True):
    if not has(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or (not allow_empty and value == ""):
        raise bad("Field '%s' must be a string." % name)
    return value


def _as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    return value


def req_int(data, name, minimum=0, maximum=None):
    if not has(data, name):
        raise bad("Field '%s' is required." % name)
    value = _as_int(data[name], name)
    _range(value, name, minimum, maximum)
    return value


def opt_int(data, name, default=None, minimum=0, maximum=None):
    if not has(data, name):
        return default
    value = _as_int(data[name], name)
    _range(value, name, minimum, maximum)
    return value


def _range(value, name, minimum, maximum):
    if minimum is not None and value < minimum:
        raise bad("Field '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise bad("Field '%s' is above its maximum." % name)


def req_number(data, name, minimum=0):
    if not has(data, name):
        raise bad("Field '%s' is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' is below its minimum." % name)
    return value


def req_bool(data, name):
    value = data.get(name)
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not has(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def req_enum(data, name, allowed):
    value = data.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not has(data, name):
        return default
    return req_enum(data, name, allowed)


def req_dt(data, name):
    if not has(data, name):
        raise bad("Field '%s' is required." % name)
    try:
        return db.parse_dt(data[name])
    except (ValueError, TypeError):
        raise bad("Field '%s' must be an ISO-8601 instant." % name)


def opt_dt(data, name, default=None):
    if not has(data, name):
        return default
    try:
        return db.parse_dt(data[name])
    except (ValueError, TypeError):
        raise bad("Field '%s' must be an ISO-8601 instant." % name)


def domain_label(value, name="domain_name"):
    if not isinstance(value, str) or not DOMAIN_LABEL_RE.match(value):
        raise bad("Field '%s' must be 1..63 characters of [a-z0-9-]." % name)
    return value


# ------------------------------------------------------------------ query
def query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        raise bad("Query parameter '%s' is out of range." % name)
    return value


def pagination():
    limit = query_int("limit", config.DEFAULT_LIMIT, config.MIN_LIMIT, config.MAX_LIMIT)
    offset = query_int("offset", config.DEFAULT_OFFSET, 0, None)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad("Query parameter '%s' is invalid." % name)
    return raw


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset : offset + limit]
    return [serializer(r) for r in window], total


# ------------------------------------------------------------------ lookups
def get_account(account_id):
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND")
    return account


def get_domain(domain_id):
    domain = db.domains.get(domain_id)
    if domain is None:
        raise ApiError("ERR_DOMAIN_NOT_FOUND")
    return domain


def get_dns_record(record_id):
    record = db.dns_records.get(record_id)
    if record is None:
        raise ApiError("ERR_DNS_RECORD_NOT_FOUND")
    return record


def get_plan(plan_id):
    plan = db.hosting_plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_HOSTING_PLAN_NOT_FOUND")
    return plan


def get_subscription(subscription_id):
    subscription = db.subscriptions.get(subscription_id)
    if subscription is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND")
    return subscription


def get_add_on(add_on_id):
    add_on = db.add_ons.get(add_on_id)
    if add_on is None:
        raise ApiError("ERR_ADDON_NOT_FOUND")
    return add_on


def get_transfer_request(transfer_id):
    transfer = db.transfer_requests.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_TRANSFER_REQUEST_NOT_FOUND")
    return transfer


def get_invoice(invoice_id):
    invoice = db.invoices.get(invoice_id)
    if invoice is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    return invoice


def get_billing_period(period_id):
    period = db.billing_periods.get(period_id)
    if period is None:
        raise ApiError("ERR_BILLING_PERIOD_NOT_FOUND")
    return period


def get_abuse_report(report_id):
    report = db.abuse_reports.get(report_id)
    if report is None:
        raise ApiError("ERR_ABUSE_REPORT_NOT_FOUND")
    return report


def get_promo_code(code):
    for promo in db.promo_codes.values():
        if promo["code"] == code:
            return promo
    raise ApiError("ERR_PROMO_CODE_NOT_FOUND")
