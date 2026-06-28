"""Payments (read-only; created via deposit/balance flows). PRD §3.6."""
from flask import Blueprint, request

import db
import response
from middleware import get_identity, require_role, parse_pagination
from services import serialize
from services.store import require, paginate, guardian_owns_camper

bp = Blueprint("payments", __name__)


def _owned_application_ids(uid):
    owned_campers = {c["id"] for c in db.campers.values() if c["guardian_user_id"] == uid}
    return {a["id"] for a in db.applications.values() if a["camper_id"] in owned_campers}


@bp.route("/payments", methods=["GET"])
def list_payments():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    limit, offset = parse_pagination()

    app_f = request.args.get("application_id")
    status_f = request.args.get("status")

    items = list(db.payments.values())
    if role == "Guardian":
        owned = _owned_application_ids(uid)
        items = [p for p in items if p["application_id"] in owned]
    if app_f is not None:
        items = [p for p in items if p["application_id"] == app_f]
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.payment(p) for p in page], limit, offset, total)


@bp.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    p = require(db.payments, pid)
    if role == "Guardian":
        application = db.applications.get(p["application_id"])
        if application is not None:
            camper = db.campers.get(application["camper_id"])
            if camper is not None:
                guardian_owns_camper(uid, role, camper)
    return response.success(serialize.payment(p), 200)
