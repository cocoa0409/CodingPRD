"""MakeGood endpoints: get, list, ACCEPT (extends the flight, reopens the
campaign) / DECLINE (grants a cash credit on the DRAFT invoice)."""

from flask import Blueprint, request

import db
from errors import (
    err_not_found,
    err_invalid,
    err_conflict,
    err_forbidden,
    err_agency_mismatch,
    ERR_MAKE_GOOD_STATE,
)
from helpers import body_of, require_int
from middleware import require_roles
from response import success_object, list_response, serialize
from services import (
    Changes,
    shortfall_credit,
    commission_and_net,
    extend_flight_end,
)

bp = Blueprint("make_goods", __name__)

READ_ROLES = {"AdOps", "Advertiser", "Agency", "Finance"}
WRITE_ROLES = {"Advertiser", "Agency", "AdOps"}


def get_make_good_or_404(mg_id):
    mg = db.make_goods.get(mg_id)
    if mg is None:
        raise err_not_found(f"MakeGood '{mg_id}' not found")
    return mg


@bp.route("/adnet/make-goods/<mg_id>", methods=["GET"])
def get_make_good(mg_id):
    require_roles(READ_ROLES)
    return success_object(serialize(get_make_good_or_404(mg_id)))


@bp.route("/adnet/make-goods", methods=["GET"])
def list_make_goods():
    require_roles(READ_ROLES)
    items = list(db.make_goods.values())
    campaign_id = request.args.get("campaign_id")
    invoice_id = request.args.get("invoice_id")
    status = request.args.get("status")
    if campaign_id is not None:
        items = [m for m in items if m["campaign_id"] == campaign_id]
    if invoice_id is not None:
        items = [m for m in items if m["invoice_id"] == invoice_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return list_response(items, request.args)


@bp.route("/adnet/make-goods/<mg_id>/transition", methods=["POST"])
def transition_make_good(mg_id):
    user_id, role = require_roles(WRITE_ROLES)
    mg = get_make_good_or_404(mg_id)
    body = body_of(request)

    # Ownership / agency representation.
    campaign = db.campaigns.get(mg["campaign_id"])
    if role == "Advertiser":
        if campaign is None or campaign["advertiser_id"] != user_id:
            raise err_forbidden("Advertiser may answer only its own make-goods")
    elif role == "Agency":
        advertiser = (
            db.advertisers.get(campaign["advertiser_id"]) if campaign else None
        )
        if advertiser is None or advertiser.get("agency_id") != user_id:
            raise err_agency_mismatch()

    # State: offers are answered only while OFFERED.
    if mg["status"] != "OFFERED":
        raise err_conflict(
            ERR_MAKE_GOOD_STATE,
            f"MakeGood is {mg['status']}; transitions require OFFERED",
        )

    action = body.get("action")
    if action not in ("ACCEPT", "DECLINE"):
        raise err_invalid("Field 'action' must be one of ACCEPT, DECLINE")

    ch = Changes()
    if action == "ACCEPT":
        extension_days = require_int(body, "extension_days", minimum=1, maximum=30)
        # Reopen the campaign: ENDED -> ACTIVE, flight extended; baseline is
        # the delivered_impressions snapshot at acceptance.
        extend_flight_end(campaign, extension_days, ch)
        ch.update(
            mg,
            status="ACCEPTED",
            baseline_delivered_impressions=campaign["delivered_impressions"],
        )
    else:  # DECLINE — grant the cash credit on the still-DRAFT invoice.
        ch.update(mg, status="DECLINED")
        invoice = db.invoices.get(mg["invoice_id"])
        if invoice is not None:
            credit = shortfall_credit(campaign, invoice["shortfall_impressions"])
            commission, net = commission_and_net(
                campaign, invoice["gross_cents"], invoice["shortfall_impressions"], credit
            )
            ch.update(
                invoice,
                make_good_credit_cents=credit,
                agency_commission_cents=commission,
                net_cents=net,
            )
    ch.commit()
    return success_object(serialize(mg))
