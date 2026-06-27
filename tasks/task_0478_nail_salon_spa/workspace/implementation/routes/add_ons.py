"""Add-ons catalogue (PRD §3.3)."""
from flask import Blueprint, request

from common import (json_body, make_record, get_str, get_int,
                    parse_pagination, paginate)
from db import db
from middleware import authorize
from lookup import get_add_on
from response import success_object, success_list
from serialize import add_on_out

bp = Blueprint("add_ons", __name__)

READ_ROLES = {"SalonManager", "FrontDesk", "Technician"}


@bp.route("/add-ons", methods=["POST"])
def create_add_on():
    authorize({"SalonManager"})
    body = json_body(optional=False)
    name = get_str(body, "name", required=True)
    price_cents = get_int(body, "price_cents", required=True, minimum=0)
    extra_minutes = get_int(body, "extra_minutes", required=False, default=0, minimum=0)

    rec = make_record({
        "name": name,
        "price_cents": price_cents,
        "extra_minutes": extra_minutes,
        "is_active": True,
    })
    db.add_ons[rec["id"]] = rec
    return success_object(add_on_out(rec), status=201)


@bp.route("/add-ons", methods=["GET"])
def list_add_ons():
    authorize(READ_ROLES)
    items = list(db.add_ons.values())
    ia = request.args.get("is_active")
    if ia is not None:
        want = ia.lower() == "true"
        items = [a for a in items if a["is_active"] == want]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([add_on_out(a) for a in page], limit, offset, total)


@bp.route("/add-ons/<aid>", methods=["GET"])
def get_one_add_on(aid):
    authorize(READ_ROLES)
    rec = get_add_on(aid)
    return success_object(add_on_out(rec), status=200)
