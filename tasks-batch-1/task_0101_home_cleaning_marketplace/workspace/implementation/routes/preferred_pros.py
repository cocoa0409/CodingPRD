"""Preferred-pro association routes."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     parse_pagination, paginate, ownership_customer)
from response import success, list_success

bp = Blueprint("preferred_pros", __name__)


@bp.route("/cleaning/preferred-pros", methods=["POST"])
def create_preferred_pro():
    principal = authenticate()
    authorize(principal, {"Customer"})
    body = get_json_body()
    require_fields(body, ["customer_id", "cleaner_id", "priority"])
    # Existence resolved left-to-right: customer_id then cleaner_id.
    customer = require_resource(db.customers, body["customer_id"], "customer")
    cleaner = require_resource(db.cleaners, body["cleaner_id"], "cleaner")
    ownership_customer(principal, customer["id"])
    priority = body["priority"]
    if isinstance(priority, bool) or not isinstance(priority, int) or priority < 1:
        raise err("ERR_INVALID_REQUEST", "priority must be an integer >= 1")
    rec = {
        "customer_id": customer["id"],
        "cleaner_id": cleaner["id"],
        "priority": priority,
    }
    db.insert(db.preferred_pros, rec)
    return success(S.preferred_pro(rec), status=201)


@bp.route("/cleaning/preferred-pros/<pid>", methods=["GET"])
def get_preferred_pro(pid):
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    rec = require_resource(db.preferred_pros, pid, "preferred_pro")
    ownership_customer(principal, rec["customer_id"])
    return success(S.preferred_pro(rec), status=200)


@bp.route("/cleaning/preferred-pros", methods=["GET"])
def list_preferred_pros():
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    cleaner_id = request.args.get("cleaner_id")
    records = list(db.preferred_pros.values())
    if customer_id is not None:
        records = [r for r in records if r["customer_id"] == customer_id]
    if cleaner_id is not None:
        records = [r for r in records if r["cleaner_id"] == cleaner_id]
    if principal.role == "Customer":
        records = [r for r in records if r["customer_id"] == principal.user_id]
    page, total = paginate(records, limit, offset)
    return list_success([S.preferred_pro(r) for r in page], limit, offset, total)
