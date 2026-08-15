"""CustomerAccount endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("customers", __name__)

VALID_LOCALES = {"US_CA", "US_TX", "DE"}
VALID_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.route("/genset-packaging/customers", methods=["POST"])
def create_customer():
    mw.require_roles("PlatformAdmin")
    body = mw.get_json_body()

    name = mw.require_string(body, "name")
    credit_limit_cents = mw.require_int(body, "credit_limit_cents", minimum=0)
    primary_locale = mw.require_enum(body, "primary_locale", VALID_LOCALES)
    status = mw.optional_enum(body, "status", VALID_STATUSES, "ACTIVE")

    record = {
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "credit_utilized_cents": 0,
        "primary_locale": primary_locale,
        "status": status,
    }
    db.stamp_new(record)
    db.customers[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/customers/<customerId>", methods=["GET"])
def get_customer(customerId):
    mw.authenticate()
    record = db.customers.get(customerId)
    if record is None:
        raise errors.not_found("Customer account not found")
    return resp.success_object(record)
