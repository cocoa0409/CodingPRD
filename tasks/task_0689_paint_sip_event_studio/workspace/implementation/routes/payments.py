"""Payment read endpoints (PRD §3.5). Payments are created by the pay waterfall."""
from flask import Blueprint, g, request

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response, array_response

bp = Blueprint("payments", __name__)


def _customer_owns_payment(payment):
    reservation = db.reservations.get(payment["reservation_id"])
    return reservation is not None and g.user_id == reservation["customer_id"]


@bp.get("/studio-ops/payments/<pid>")
def get_payment(pid):
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    rec = db.payments.get(pid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Payment not found")
    if middleware.is_customer() and not _customer_owns_payment(rec):
        raise err(errors.ERR_FORBIDDEN, "Customer does not own this payment")
    return object_response(models.serialize_payment(rec), 200)


@bp.get("/studio-ops/payments")
def list_payments():
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    reservation_id = request.args.get("reservation_id")
    gift_card_id = request.args.get("gift_card_id")
    method = request.args.get("method")
    status = request.args.get("status")
    rows = list(db.payments.values())
    if reservation_id:
        rows = [r for r in rows if r["reservation_id"] == reservation_id]
    if gift_card_id:
        rows = [r for r in rows if r["gift_card_id"] == gift_card_id]
    if method:
        rows = [r for r in rows if r["method"] == method]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if middleware.is_customer():
        owned = {res["id"] for res in db.reservations.values()
                 if res["customer_id"] == g.user_id}
        rows = [r for r in rows if r["reservation_id"] in owned]
    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_payment(r) for r in page],
                          limit, offset, total, 200)
