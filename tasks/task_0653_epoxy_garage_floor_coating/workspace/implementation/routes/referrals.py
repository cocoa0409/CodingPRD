"""Referral endpoints (SCAFFOLD §1.5 / PRD §3.2)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.calc import REFERRAL_CREDIT_CENTS
from services.common import get_body, new_row, require_str, touch

bp = Blueprint("referrals", __name__)


@bp.route("/referrals", methods=["POST"])
def create_referral():
    _, role = authenticate()
    require_role(role, {"SalesRep"})
    body = get_body()
    referrer_customer_id = require_str(body, "referrer_customer_id")
    referred_customer_id = require_str(body, "referred_customer_id")
    project_id = require_str(body, "project_id")

    # priority 5: body references resolve
    if db.customers.get(referrer_customer_id) is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "referrer_customer_id does not resolve")
    if db.customers.get(referred_customer_id) is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "referred_customer_id does not resolve")
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "project_id does not resolve")

    # priority 7: self-referral check
    if referrer_customer_id == referred_customer_id:
        raise err("ERR_SELF_REFERRAL", "referred customer must differ from referrer")

    row = new_row({
        "referrer_customer_id": referrer_customer_id,
        "referred_customer_id": referred_customer_id,
        "project_id": project_id,
        "credit_cents": REFERRAL_CREDIT_CENTS,
        "status": "PENDING",
    })
    db.referrals[row["id"]] = row

    # pins itself to the referred project by setting that project's referral_id
    project["referral_id"] = row["id"]
    touch(project)

    return success(serialize.referral(row), 201)


@bp.route("/referrals/<id>", methods=["GET"])
def get_referral(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep", "Customer"})
    row = db.referrals.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Referral not found")
    return success(serialize.referral(row), 200)
