"""Financial-aid application routes: submit, fetch, approve, deny."""
from flask import Blueprint, request

from db import db, common_create_fields, touch
from errors import err, ERR_INVALID_STATE
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner
from validate import require_body, require_int
from services.calc import band_aid_tier
import serialize
from response import success

bp = Blueprint("financial_aid", __name__)


@bp.route("/clients/<cid>/financial-aid-applications", methods=["POST"])
def submit_aid(cid):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    client = get_or_404(db.clients, cid)
    check_client_owner(role, user_id, cid)
    data = require_body(request.get_json(silent=True))
    income = require_int(data, "annual_income_cents", minimum=0)
    household = require_int(data, "household_size", minimum=1)
    app = {
        **common_create_fields(),
        "client_id": cid,
        "annual_income_cents": income,
        "household_size": household,
        "status": "SUBMITTED",
        "awarded_tier": "NONE",
    }
    db.aid_applications[app["id"]] = app
    return success(serialize.aid_out(app), status=201)


@bp.route("/financial-aid-applications/<aid>", methods=["GET"])
def get_aid(aid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    app = get_or_404(db.aid_applications, aid)
    check_client_owner(role, user_id, app["client_id"])
    return success(serialize.aid_out(app))


@bp.route("/financial-aid-applications/<aid>/approve", methods=["POST"])
def approve_aid(aid):
    user_id, role = get_auth()
    require_role(role, {"BillingAdmin"})
    app = get_or_404(db.aid_applications, aid)
    if app["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application not in SUBMITTED")
    tier = band_aid_tier(app["annual_income_cents"], app["household_size"])
    app["status"] = "APPROVED"
    app["awarded_tier"] = tier
    touch(app)
    client = db.clients.get(app["client_id"])
    if client:
        client["financial_aid_tier"] = tier
        touch(client)
    return success(serialize.aid_out(app))


@bp.route("/financial-aid-applications/<aid>/deny", methods=["POST"])
def deny_aid(aid):
    user_id, role = get_auth()
    require_role(role, {"BillingAdmin"})
    app = get_or_404(db.aid_applications, aid)
    if app["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application not in SUBMITTED")
    app["status"] = "DENIED"
    touch(app)
    return success(serialize.aid_out(app))
