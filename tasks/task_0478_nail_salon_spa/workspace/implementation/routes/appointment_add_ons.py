"""AppointmentAddOn junction read endpoints (PRD §4)."""
from flask import Blueprint, request

from common import parse_pagination, paginate
from db import db
from middleware import authorize
from lookup import get_appointment_add_on
from response import success_object, success_list
from serialize import appointment_add_on_out

bp = Blueprint("appointment_add_ons", __name__)

READ_ROLES = {"FrontDesk", "SalonManager", "Technician"}


@bp.route("/appointment-add-ons", methods=["GET"])
def list_appointment_add_ons():
    authorize(READ_ROLES)
    items = list(db.appointment_add_ons.values())
    apt = request.args.get("appointment_id")
    if apt is not None:
        items = [r for r in items if r["appointment_id"] == apt]
    aid = request.args.get("add_on_id")
    if aid is not None:
        items = [r for r in items if r["add_on_id"] == aid]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([appointment_add_on_out(r) for r in page], limit, offset, total)


@bp.route("/appointment-add-ons/<jid>", methods=["GET"])
def get_one_appointment_add_on(jid):
    authorize(READ_ROLES)
    rec = get_appointment_add_on(jid)
    return success_object(appointment_add_on_out(rec), status=200)
