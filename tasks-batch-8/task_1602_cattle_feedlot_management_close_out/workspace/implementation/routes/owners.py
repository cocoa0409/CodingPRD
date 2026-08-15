"""Owner endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_OWNER_NOT_FOUND, ERR_INVALID_STATE_TRANSITION, raise_err
from serializers import owner_out, lot_out, invoice_out
from util import body_json, get_or_404, list_response, new_record, bump, \
    req_str, success_object

bp = Blueprint("owners", __name__)


@bp.route("/feedlot/owners", methods=["POST"])
def create_owner():
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    body = body_json()
    owner_name = req_str(body, "owner_name")
    billing_email = req_str(body, "billing_email")

    rec = new_record()
    rec.update({
        "owner_name": owner_name,
        "billing_email": billing_email,
        "status": "ACTIVE",
        "outstanding_balance_cents": 0,
    })
    store.owners[rec["id"]] = rec
    return success_object(owner_out(rec), 201)


@bp.route("/feedlot/owners", methods=["GET"])
def list_owners():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(list(store.owners.values()), owner_out)


@bp.route("/feedlot/owners/<owner_id>", methods=["GET"])
def get_owner(owner_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.owners, owner_id, ERR_OWNER_NOT_FOUND, "Owner")
    return success_object(owner_out(rec))


@bp.route("/feedlot/owners/<owner_id>", methods=["PATCH"])
def patch_owner(owner_id):
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    rec = get_or_404(store.owners, owner_id, ERR_OWNER_NOT_FOUND, "Owner")
    body = body_json()
    new_status = req_str(body, "status")

    if new_status == rec["status"]:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Owner %s already has status %s" % (owner_id, new_status))

    if new_status == "SUSPENDED":
        if rec["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      "Owner %s cannot transition to SUSPENDED from %s" % (owner_id, rec["status"]))
        rec["status"] = "SUSPENDED"
    elif new_status == "ACTIVE":
        if rec["status"] != "SUSPENDED":
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      "Owner %s cannot transition to ACTIVE from %s" % (owner_id, rec["status"]))
        rec["status"] = "ACTIVE"
    else:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Invalid status transition: %s -> %s" % (rec["status"], new_status))

    bump(rec)
    return success_object(owner_out(rec))


@bp.route("/feedlot/owners/<owner_id>/lots", methods=["GET"])
def list_owner_lots(owner_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.owners, owner_id, ERR_OWNER_NOT_FOUND, "Owner")
    lots = [lot for lot in store.lots.values() if lot["owner_id"] == owner_id]
    return list_response(lots, lot_out)


@bp.route("/feedlot/owners/<owner_id>/invoices", methods=["GET"])
def list_owner_invoices(owner_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.owners, owner_id, ERR_OWNER_NOT_FOUND, "Owner")
    invoices = [inv for inv in store.invoices.values() if inv["owner_id"] == owner_id]
    return list_response(invoices, invoice_out)
